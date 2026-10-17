"""R58 passive inventory preflight for KR cultivation setup.

Checks which user-reviewed UI templates and numeric OCR regions exist; it does
NOT read the game, validate the actual selected character/deck/inheritance, or
permit any input. All source files and personal settings stay unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

TP_FIELDS = frozenset(("tp", "tp_cost", "tp_cap", "free_item_count", "free_item_recovery"))


@dataclass(frozen=True)
class SetupPreflight:
    missing: tuple[str, ...]
    reminders: tuple[str, ...]

    @property
    def ready_for_manual_review(self) -> bool:
        return not self.missing

    @property
    def summary(self) -> str:
        if self.missing:
            return "R58 사전 등록 부족: " + "; ".join(self.missing)
        return "R58 필수 버튼/TP OCR 등록 확인 · 실제 캐릭터·덱·계승·게임 화면은 사용자 검수 필요"


def audit_setup(profiles, rois) -> SetupPreflight:
    """Check exact actions rather than treating any button of a stage as ready."""
    actions = {(p.stage, p.action) for p in profiles if p.reviewed is True}
    missing = []
    for stage, action, label in (
        ("setup", "start_run", "육성 준비 화면 시작 버튼"),
        ("tp", "start_run", "TP 화면 시작 버튼"),
        ("repeat", "repeat_run", "반복 육성 버튼"),
    ):
        if (stage, action) not in actions:
            missing.append(label + " 미등록")
    if not any(stage == "result" and action.startswith("finish_run:")
               for stage, action in actions):
        missing.append("육성 종료 결과 버튼 미등록")

    fields = {r.field for r in rois if r.stage == "tp" and r.reviewed is True}
    absent = sorted(TP_FIELDS - fields)
    if absent:
        missing.append("TP OCR 영역 누락: " + ", ".join(absent))
    if any(p.stage == "tp" and p.action.startswith("free_tp:") and
           p.free_only is not True for p in profiles):
        missing.append("무료로 검수되지 않은 TP 회복 버튼")

    return SetupPreflight(tuple(missing), (
        "등록된 장면 템플릿은 실제 캐릭터·덱·계승 일치의 증거가 아닙니다.",
        "육성 시작 화면(setup)에서 자동 선택/시작을 할 수 있다는 뜻이 아닙니다.",
        "유료 재화나 미등록 장면을 자동 조작하지 않습니다.",
    ))
