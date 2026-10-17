"""R57 fail-closed witness for a foreground training click.

Dispatch is not success. A clicked training preview requires two corroborating
post-click observations before the next pointer action. A clicked training
confirmation always requires human/verified-turn follow-up; changing pixels
alone never authorizes the next turn. This module never sends game input.
"""
from __future__ import annotations
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class TransitionStatus:
    code: str
    message: str
    # For the preview only: confirmed selection, not a training outcome.
    preview_observed: bool = False
    game_turn_verified: bool = False
    game_input_allowed: bool = False


class TrainingClickGuard:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.reset()

    def reset(self):
        self.pending = None
        self.match_count = 0
        self.last_candidate = None

    @property
    def armed(self):
        return self.pending is not None

    def arm(self, intent, before_signature: str, *, issued_at=None):
        if self.pending is not None:
            raise ValueError("이전 훈련 입력 결과를 확인하기 전입니다.")
        intent.validate()
        if (intent.kind not in ("preview_training", "confirm_training") or
                intent.expected_scene != "훈련" or
                not isinstance(before_signature, str) or
                len(before_signature) != 64 or
                not intent.target_label):
            raise ValueError("훈련 클릭의 실제 화면 지문/대상을 확인할 수 없습니다.")
        when = self.clock() if issued_at is None else issued_at
        self.pending = (intent.kind, intent.hwnd, intent.rect,
                        before_signature, intent.target_label, when)
        self.match_count = 0
        self.last_candidate = None

    def observe(self, *, scene, selected, preview_selected, collected_names,
                signature, hwnd, rect, now=None):
        if self.pending is None:
            return TransitionStatus("idle", "확인 대기 중인 자동 클릭이 없습니다.")
        kind, old_hwnd, old_rect, old_signature, target, issued_at = self.pending
        moment = self.clock() if now is None else now
        if hwnd != old_hwnd or rect != old_rect:
            self.reset()
            return TransitionStatus("blocked", "게임 창/크기/위치 변경 · 자동 클릭 중단")
        timeout = 12 if kind == "preview_training" else 25
        if moment < issued_at or moment - issued_at > timeout:
            self.reset()
            return TransitionStatus("blocked", "클릭 뒤 실제 게임 화면 확인 시간 초과 · 자동 클릭 중단")
        if kind == "preview_training":
            if scene not in (None, "훈련"):
                self.reset()
                return TransitionStatus("blocked", "훈련 미리보기 도중 다른 장면 감지 · 중단")
            if scene == "훈련" and signature != old_signature:
                self.reset()
                return TransitionStatus("blocked", "미리보기 도중 턴 지문 변경 · 새 화면 검수 필요")
            good = (scene == "훈련" and selected == target and
                    preview_selected == target and target in collected_names)
            candidate = (scene, selected, signature)
            self.match_count = self.match_count + 1 if good and candidate == self.last_candidate else (1 if good else 0)
            self.last_candidate = candidate if good else None
            if self.match_count >= 2:
                self.reset()
                return TransitionStatus("preview_confirmed", "클릭한 훈련 미리보기와 OCR 2회 일치 · 다음 후보 확인 가능", preview_observed=True)
            return TransitionStatus("waiting", "클릭한 훈련의 실제 선택 표식·OCR 재확인 대기")
        # A confirmation click can lead to animation, result, modal, race or a
        # new turn; no one-screen pixel change proves which. Never autoadvance.
        if scene is not None and scene != "훈련":
            candidate = ("different_scene", scene)
        elif scene == "훈련" and signature and signature != old_signature and selected:
            candidate = ("changed_baseline", signature, selected)
        else:
            candidate = None
        self.match_count = self.match_count + 1 if candidate is not None and candidate == self.last_candidate else (1 if candidate is not None else 0)
        self.last_candidate = candidate
        if self.match_count >= 2:
            self.reset()
            return TransitionStatus("review_required", "훈련 클릭 후 새 화면 후보 관측 · 턴/보상은 미검수이므로 자동 입력 정지")
        return TransitionStatus("waiting", "훈련 버튼 입력 후 다음 화면 2회 확인 대기 · 추가 클릭 금지")
