"""R49 opt-in training preview tour and one-turn experiment.

Only the photographed 2026-10-16 Korean portrait *training* interface is
supported. Unknown modal/TP/skill/race/result screens halt (never guessed).
OCR observations are provisional; a user must opt into this experimental
automation knowing friendship, skill points and failure risks aren't included.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import time
from training_preview_r48 import NAMES, CENTERS, PreviewState, _turn_signature
from foreground_click_r49 import ClickIntent

TRAINING_ICON_Y = .828
TRAINING_CONFIRM_Y = .894


@dataclass(frozen=True)
class TourResult:
    intent: ClickIntent | None
    explanation: str
    status: str


class TrainingTour:
    def __init__(self):
        self.enabled = False
        self.state = "off"
        self.awaiting_name = None
        self.last_signature = None
        self.click_time = 0.0
        self.scanned = set()
        self.commits = 0

    def stop(self):
        self.enabled=False
        self.state="off"
        self.awaiting_name=None
        self.scanned.clear()

    def start(self):
        self.enabled=True
        self.state="scanning"
        self.awaiting_name=None
        self.scanned.clear()
        self.click_time=0
        self.last_signature=None

    def on_click_result(self, ok: bool, kind: str, expected_name: str, moment: float):
        if not ok:
            self.stop()
            return
        self.awaiting_name=expected_name if kind=="preview_training" else None
        self.click_time=moment
        self.state="await_preview" if kind=="preview_training" else "await_new_turn"
        if kind=="confirm_training":
            self.commits+=1

    def _intent(self,image,hwnd,rect,kind,selected,desired,clock):
        if selected not in NAMES or desired not in NAMES:
            raise ValueError("알 수 없는 훈련 명칭")
        x=CENTERS[NAMES.index(desired)]
        y=TRAINING_ICON_Y if kind=="preview_training" else TRAINING_CONFIRM_Y
        digest=hashlib.sha256((str(_turn_signature(image))+"|"+selected+"|"
                +kind+"|"+desired).encode("utf-8")).hexdigest()
        return ClickIntent(hwnd,rect,x,y,kind,"훈련",selected,digest,clock,
                           target_label=desired).validate()

    def propose(self, image, hwnd, rect, preview: PreviewState | None,
                *, scene: str | None, user_armed: bool,
                collected_names: tuple[str, ...] = (),
                clock: float | None=None) -> TourResult:
        now=time.monotonic() if clock is None else clock
        if not (self.enabled and user_armed):
            return TourResult(None,"사용자가 자동 탐색을 시작하지 않았습니다.","off")
        if scene!="훈련" or preview is None or preview.selected not in NAMES:
            self.stop()
            return TourResult(None,"훈련 미리보기 밖의 게임 화면 · 자동 조작 정지","blocked")
        signature=_turn_signature(image)
        if self.last_signature != signature:
            if self.last_signature is not None and self.state=="await_new_turn":
                self.state="scanning"
                self.scanned.clear()
                self.awaiting_name=None
            elif self.last_signature is not None:
                self.state="scanning"
                self.scanned.clear()
                self.awaiting_name=None
            self.last_signature=signature
        if self.state=="await_new_turn":
            if now-self.click_time>18:
                self.stop()
                return TourResult(None,"훈련 선택 뒤 턴 전환이 확인되지 않아 자동 실행 정지","blocked")
            return TourResult(None,"훈련 실행 후 새 턴 화면 전환 확인 대기","waiting")
        if (any(name not in NAMES for name in collected_names) or
                len(set(collected_names)) != len(collected_names)):
            self.stop()
            return TourResult(None,"훈련 후보 자료가 잘못되어 중단합니다.","blocked")
        names=set(collected_names)
        if self.state=="await_preview":
            if now-self.click_time>90:
                self.stop()
                return TourResult(None,"클릭한 훈련 미리보기 전환 확인 실패 · 자동 실행 정지","blocked")
            if preview.selected != self.awaiting_name or self.awaiting_name not in names:
                return TourResult(None,"선택한 훈련 보상의 동일 OCR 2회 재확인 대기","waiting")
            self.awaiting_name=None
            self.state="scanning"
        if preview.selected not in names:
            return TourResult(None,"선택 중인 훈련의 동일 OCR 수치 2회 확인 대기","waiting")
        if preview.collected != len(names):
            self.stop()
            return TourResult(None,"훈련 후보 횟수와 실제 관측 기록이 다릅니다.","blocked")
        if preview.collected < 5:
            missing=[name for name in NAMES if name not in names]
            if not missing:
                return TourResult(None,"훈련 5종 후보 수치 재확인 대기","waiting")
            desired=missing[0]
            if desired==preview.selected:
                return TourResult(None,"선택된 훈련 OCR 안정화 대기","waiting")
            return TourResult(self._intent(image,hwnd,rect,"preview_training",preview.selected,
                           desired,now),f"{desired} 미리보기로 이동","ready")
        if preview.recommendation not in NAMES:
            self.stop()
            return TourResult(None,"스탯 점수가 비슷하거나 자료 누락 · 임의 선택 없이 정지","blocked")
        if preview.selected!=preview.recommendation:
            return TourResult(self._intent(image,hwnd,rect,"preview_training",preview.selected,
                              preview.recommendation,now),"추천 후보 미리보기로 이동","ready")
        # Deliberate user opt-in to provisional OCR-only choice; this is not ML.
        return TourResult(self._intent(image,hwnd,rect,"confirm_training",preview.selected,
                         preview.recommendation,now),
                         "OCR 잠정 추천을 사용한 훈련 실행 실험 · 실제 효율 미검증","ready")
