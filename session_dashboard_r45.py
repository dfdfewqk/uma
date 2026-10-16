"""R45 read-only cultivation dashboard for the existing Tk companion.

Only an existing, validated R44 session can supply a completed-run counter.
Choosing a tournament/style/repeat count is a PLAN, not proof of progress.
No game client, background loop, automated clicks, or ML training is started.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cultivation_session_r44 import load_session
from planning_prefs_r44 import Preferences
from target_selector_r39 import Target

PHASE_LABELS = {
    "setup": "초기 설정 확인 대기",
    "need_tp": "다음 육성 준비 확인 필요",
    "waiting_tp": "TP 자연 회복 대기",
    "in_run": "진행 중이던 육성 재확인 필요",
    "awaiting_verification": "게임 화면 검증 대기",
    "finished": "설정한 육성 횟수 완료",
}


@dataclass(frozen=True)
class Dashboard:
    """A snapshot of an existing record; never a derived actual game state."""

    status: str
    progress: str
    breakdown: str
    detail: str
    recorded: bool = False
    compatible: bool = False
    completed: int | None = None
    requested: int | None = None
    fraction: float | None = None
    needs_review: bool = True
    permits_game_input: bool = False


def _unrecorded(target: Target | None, repeats: int) -> Dashboard:
    if target is None:
        return Dashboard(
            "목표 선택 대기",
            f"기록된 진행 없음 · 반복 {repeats}회 계획",
            "성공 — · 평범 — · 도축 — · 실패 —",
            "통합 대회 회차와 각질을 선택하세요. 자동 육성은 시작되지 않았습니다.",
        )
    return Dashboard(
        "자동 육성 시작 전",
        f"기록된 진행 없음 · {repeats}회 계획",
        "성공 — · 평범 — · 도축 — · 실패 —",
        "게임에서 캐릭터·서포트 덱·계승과 TP를 확인해야 합니다. "
        "회차/각질 선택만으로 육성 횟수를 시작하거나 기록하지 않습니다.",
    )


def read_dashboard(target: Target | None, preferences: Preferences,
                   session_path: str | Path) -> Dashboard:
    """Read only the canonical R44 session file, never migrate or rewrite it.

    A changed UI plan does not erase or silently repurpose a different session.
    load_session() enforces a paused state after a program restart.
    """
    preferences.validate()
    if target is not None:
        target.validate()
    path = Path(session_path)
    if path.is_symlink():
        return Dashboard(
            "기록 파일 검토 필요",
            f"기존 진행 기록 확인 전 · 선택한 계획 {preferences.repeats}회",
            "고점 — · 평범 — · 도축 — · 실패 —",
            "세션 파일이 다른 경로로 연결되어 있습니다. 원본은 변경하지 않고 조회를 보류합니다.",
        )
    if not path.exists():
        return _unrecorded(target, preferences.repeats)
    try:
        session = load_session(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return Dashboard(
            "기록 파일 검토 필요",
            f"기존 진행 기록 확인 전 · 선택한 계획 {preferences.repeats}회",
            "성공 — · 평범 — · 도축 — · 실패 —",
            "세션 내용이 손상되었거나 버전이 다릅니다. 원본은 그대로 보존했습니다. "
            "자동 진행·재개는 보류합니다.",
        )
    if session is None:
        return _unrecorded(target, preferences.repeats)
    session.validate()
    snapshot = session.summary
    actual_target = session.progress.config.target
    compatible = (target is not None and actual_target == target and
                  snapshot["requested"] == preferences.repeats)
    completed, requested = snapshot["completed"], snapshot["requested"]
    fractions = completed / requested  # actual validated R44 record only
    progress_text = f"저장된 완료 {completed} / {requested}회 · 남은 {snapshot['remaining']}회"
    outcomes = ("고점 {good} · 평범 {ordinary} · 도축 {disposed} · 실패 {failed}"
                .format(**snapshot))
    if not compatible:
        return Dashboard(
            "이전 육성 계획의 기록",
            progress_text,
            outcomes,
            f"저장된 목표: {actual_target.label}. 현재 선택과 다르므로 기존 기록을 "
            "덮어쓰거나 현재 계획에 합산하지 않습니다.",
            recorded=True, compatible=False, completed=completed,
            requested=requested, fraction=fractions, needs_review=True,
        )
    phase = session.progress.phase
    status = PHASE_LABELS.get(phase, "확인되지 않은 진행 상태")
    if session.tp_refresh_required:
        status = "무료 TP 아이템 사용 후 재확인 대기"
    if phase == "finished":
        detail = "검증된 기록에 요청한 횟수만큼 종료가 반영되어 있습니다. "
        detail += "게임 화면을 다시 확인하기 전에는 자동 동작을 실행하지 않습니다."
    else:
        detail = ("프로그램 재실행 후 자동 일시 정지 상태. 기존 캐릭터·덱·계승·"
                  "진행 중 육성 ID를 실제 게임에서 재확인해야 재개할 수 있습니다.")
        if phase == "in_run":
            detail += " 진행 중인 육성은 중복 집계하지 않습니다."
    if session.paused and phase != "finished":
        status += " · 일시 정지"
    return Dashboard(
        status=status, progress=progress_text, breakdown=outcomes,
        detail=detail, recorded=True, compatible=True,
        completed=completed, requested=requested, fraction=fractions,
        needs_review=(phase != "finished"),
    )
