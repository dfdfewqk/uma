"""Passive R53 screen-state agreement gate (NOT a click authorization).

R20 calibrated two-anchor scene, R50 registered UI scene, and R48 provisional
training must agree. Unknown/conflicting evidence immediately revokes scene.
"""
from __future__ import annotations
from dataclasses import dataclass

STAGE_SCENES = {
    "setup": "육성 준비", "tp": "TP 회복", "skill": "스킬",
    "result": "육성 결과", "repeat": "다음 육성",
}

@dataclass(frozen=True)
class ScreenState:
    scene: str | None
    status: str
    reason: str
    registered_stage: str | None = None
    provisional: bool = False
    action_authorized: bool = False

class StableScreenFusion:
    def __init__(self, frames: int = 2):
        self.frames = max(2, int(frames))
        self.reset()

    def reset(self):
        self.pending = None
        self.count = 0

    def observe(self, r20_scene: str | None, registered_stage: str | None,
                training_name: str | None) -> ScreenState:
        if registered_stage is not None and registered_stage not in STAGE_SCENES:
            self.reset()
            return ScreenState(None, "conflict", "등록 장면 식별값 오류 · 자동 조작 차단")
        candidates = []
        if r20_scene:
            candidates.append((r20_scene, "R20 두 기준 영역"))
        if registered_stage:
            candidates.append((STAGE_SCENES[registered_stage], "R50 등록 장면"))
        if training_name:
            candidates.append(("훈련", "R48 훈련 미리보기 후보"))
        if len({scene for scene, _ in candidates}) > 1:
            self.reset()
            return ScreenState(None, "conflict", "화면 인식 결과 충돌 · 현재 화면 자동 조작 차단")
        if not candidates:
            self.reset()
            return ScreenState(None, "unknown", "등록된 화면 특징 없음 · 화면 수집/등록 필요")
        scene = candidates[0][0]
        provisional = bool(training_name and not (r20_scene or registered_stage))
        if scene != self.pending:
            self.pending = scene
            self.count = 1
        else:
            self.count = min(self.frames, self.count + 1)
        if self.count < self.frames:
            return ScreenState(None, "waiting", "화면 종류 연속 확인 중", registered_stage, provisional)
        description = " · ".join(src for _, src in candidates)
        if provisional:
            description += " · 미리보기 잠정 판별 (최적 행동 검증 아님)"
        return ScreenState(scene, "confirmed", description, registered_stage, provisional)
