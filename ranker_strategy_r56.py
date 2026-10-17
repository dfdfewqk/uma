"""R56: evidence-first, read-only ranking commentary for island training.

JP post-adjustment guides are RESEARCH HYPOTHESES, not Korean game rules.
A preliminary observation never authorizes a game click or R46 reviewed advice.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from training_evidence_r55 import TrainingEvidenceView, TRAININGS

RESEARCH_BASIS = "JP_2025_06_30_post_adjustment_guides_KR_unverified"

@dataclass(frozen=True)
class StrategyContext:
    server: str = "KR"
    scenario: str = "island_post_patch_v1"
    kr_patch_verified: bool = False
    phase: Optional[str] = None  # '초반' / '중반' / '후반' only when reviewed
    island_tickets: Optional[int] = None
    ticket_expiry_verified: bool = False

@dataclass(frozen=True)
class StrategyPreview:
    label: str
    notes: tuple[str, ...]
    observed_stat_leader: Optional[str] = None
    comparable_options: tuple[str, ...] = ()
    source_basis: str = RESEARCH_BASIS
    game_input_allowed: bool = False
    decision_ready: bool = False
    kr_strategy_verified: bool = False
    ml_training_label: bool = False


def _dominates(a, b):
    """Only compare a FULL set of like-for-like observed quantities.

    Missing bonds/friendships make this a *numeric* Pareto observation,
    not a best-action judgment.
    """
    av = (*a.stat_gains, a.skill_point_gain, -a.energy_cost, -a.failure_rate)
    bv = (*b.stat_gains, b.skill_point_gain, -b.energy_cost, -b.failure_rate)
    return all(x >= y for x, y in zip(av, bv)) and any(x > y for x, y in zip(av, bv))


def inspect_strategy(evidence: TrainingEvidenceView,
                     context: StrategyContext | None = None) -> StrategyPreview:
    context = context or StrategyContext()
    if context.server != "KR" or context.scenario != "island_post_patch_v1":
        return StrategyPreview("대상 서버/시나리오 불일치 · 연구 판단 제외", ())
    if evidence.source != "unreviewed_kr_ocr_candidate" or evidence.decision_ready or evidence.game_input_allowed:
        return StrategyPreview("미검수 자료/권한 정책 불일치 · 판단 보류", ())
    notes = ["JP 2025-06-30 조정 후 공략 참고이며, KR 현재 수치·랭커 실제 턴 선택은 미검증"]
    if context.phase == "초반":
        notes.append("초반엔 스탯합계 외 서포트 인연 형성·우정 개방을 비교해야 함")
    elif context.phase in ("중반", "후반"):
        notes.append("우정 훈련 인원/시설별 발동, 스킬 Pt, 목표 레이스 일정을 함께 비교해야 함")
    else:
        notes.append("실제 육성 단계가 미확인되어 초반·후반 가중치를 적용하지 않음")
    if context.island_tickets is not None:
        if type(context.island_tickets) is not int or not 0 <= context.island_tickets <= 99:
            return StrategyPreview("섬 티켓 입력 검증 실패 · 판단 보류", tuple(notes))
        notes.append("섬 티켓 사용 시 우정 인원과 다음 티켓 수급/상한을 함께 확인해야 함")
        if not context.ticket_expiry_verified:
            notes.append("티켓 소멸/초과 시점 미검증 · 사용·보류를 권고하지 않음")
    if len(evidence.options) != evidence.stat_count or len({v.name for v in evidence.options}) != len(evidence.options):
        return StrategyPreview("훈련 자료 무결성 불확실 · 판단 보류", tuple(notes))
    if any(v.name not in TRAININGS for v in evidence.options):
        return StrategyPreview("훈련 종류 오류 · 판단 보류", tuple(notes))
    if evidence.stat_count != 5:
        return StrategyPreview(f"훈련 스탯 후보 {evidence.stat_count}/5 · 전체 비교 보류", tuple(notes))
    # Stat-only leader is a descriptive fact, not an optimal recommendation.
    ranked = sorted(evidence.options, key=lambda x: (-x.stat_total, x.name))
    leader = ranked[0].name
    notes.append(f"관측 스탯 합계 1위: {leader} (+{ranked[0].stat_total}); 우정/인연 등 제외")
    all_numeric = all((v.failure_rate is not None and v.energy_cost is not None
                       and v.skill_point_gain is not None) for v in evidence.options)
    if not all_numeric:
        notes.append("훈련별 실패율·체력 소모·스킬 Pt 증가 중 미확인 값 있음")
        return StrategyPreview("스탯은 비교 가능 · 전략적 최적 훈련 판단 보류",
                               tuple(notes), observed_stat_leader=leader)
    # Pareto frontier is derived only when all comparable numeric measurements
    # are present; it cannot displace unseen friendship or alternate actions.
    pareto = tuple(v.name for v in evidence.options
                   if not any(_dominates(other, v) for other in evidence.options if other.name != v.name))
    notes.append("숫자 비열세 후보 " + "·".join(pareto) + " · 우정/인연과 레이스·휴식 미반영")
    return StrategyPreview("수치 후보 비교 가능 · R46 최종 행동 판단 보류",
                           tuple(notes), observed_stat_leader=leader,
                           comparable_options=pareto)
