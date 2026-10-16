"""R35: compare R6-confirmed current actions against R34 long-horizon context.

Evidence-gated and read-only. Not a validated policy, optimizer or ML model.
Do not alter R6 ranks/scores, unverified action choices, or game controls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from decision_r6 import (AVAILABLE, UNAVAILABLE, UNKNOWN, STATUSES,
                         _validate_action, evidence_fingerprint, state_fingerprint)
from island_context_r34 import PlanningInputs, PlanningAudit, assess_island_context
from uma_core import STATS, TRAININGS, Action, RunProfile, TurnState


@dataclass(frozen=True)
class ActionComparison:
    name: str
    r6_experimental_rank: int
    r6_experimental_score: float
    observed_gains: dict[str, int]
    gains_toward_user_target: dict[str, int]
    energy_after: int
    skill_points_gain: int
    development_points_gain: int
    notes: list[str] = field(default_factory=list)


@dataclass
class ChoiceComparison:
    status: str
    actions: list[ActionComparison] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    context_audit: PlanningAudit | None = None
    verified_optimal: bool = False
    ml_training_label_verified: bool = False
    scores_modified: bool = False


def compare_checked_choices(profile: RunProfile, state: TurnState, ctx: PlanningInputs,
                            bundle: tuple[dict, Mapping[str, Action],
                                          Mapping[str, str]] | None) -> ChoiceComparison:
    """Require a *fresh* R6 evidence review; never infer unavailable actions.

    R6 numerical ranking is displayed only as its unchanged experimental baseline.
    Long-horizon conditions are textual observations, never added weights.
    """
    audit = assess_island_context(profile, state, ctx)
    if bundle is None:
        return ChoiceComparison(
            status='R6 검수 필요 · 행동 비교 보류',
            missing=['⑦ R6 탭에서 이번 턴 선택지 가능/불가와 수치를 모두 확인하고 비교를 실행하세요.'],
            context_audit=audit)
    if not isinstance(bundle, (tuple, list)) or len(bundle) != 3:
        raise ValueError('R6 현재 턴 검수 자료 형식이 잘못되었습니다.')
    review, actions, availability = bundle
    if not isinstance(review, dict) or not isinstance(actions, Mapping) or not isinstance(availability, Mapping):
        raise ValueError('R6 검수 자료를 확인할 수 없습니다.')
    if review.get('status') == '추천 보류' or review.get('experimental_only') is not True or review.get('ml_training_label_verified') is not False:
        raise ValueError('검증된 이번 턴 R6 실험 비교가 아닙니다.')
    if review.get('context_hash') != state_fingerprint(profile, state):
        raise ValueError('R6 검수 후 목표/턴 상태가 변경됐습니다. 다시 검수하세요.')
    if review.get('evidence_hash') != evidence_fingerprint(actions, availability):
        raise ValueError('R6 검수 후 행동 입력이 변경됐습니다. 다시 검수하세요.')
    if set(availability) != set(TRAININGS) or any(v not in STATUSES for v in availability.values()):
        raise ValueError('모든 행동의 현재 가능 여부를 검수해야 합니다.')
    if review.get('availability') != dict(availability):
        raise ValueError('R6 선택지 검수와 현재 값이 불일치합니다.')
    for name in TRAININGS:
        if availability[name] == UNKNOWN:
            if name == '섬 트레이닝' and state.island_tickets == 0:
                continue
            raise ValueError('미확인 행동이 있어 추천 결과를 사용할 수 없습니다.')
    available = {name for name in TRAININGS if availability[name] == AVAILABLE}
    if state.island_tickets == 0 and '섬 트레이닝' in available:
        raise ValueError('티켓 없는 섬 훈련은 가능으로 표시할 수 없습니다.')
    for name in available:
        if name not in actions or _validate_action(name, actions[name]):
            raise ValueError(f'{name}: 확인된 행동 수치가 부족합니다.')
        if state.energy + actions[name].energy_delta < 0:
            raise ValueError(f'{name}: 현재 체력으로 가능한지 다시 확인하세요.')
    ranked = review.get('ranked')
    if not isinstance(ranked, list) or not ranked:
        raise ValueError('R6 검수된 행동 결과가 비어 있습니다.')
    if (any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
            or type(row.get('score')) not in (int, float) for row in ranked)
            or {row['name'] for row in ranked} != available
            or len({row['name'] for row in ranked}) != len(ranked)):
        raise ValueError('R6 행동 결과와 확인된 선택지 목록이 일치하지 않습니다.')

    result = ChoiceComparison(
        status='R35 조건부 행동 비교 · 최적 행동 미확정',
        missing=list(audit.missing), cautions=list(audit.cautions), context_audit=audit)
    if audit.missing:
        result.status = '장기 조건 일부 미확인 · 우열 판단 보류'
    if audit.free_turn_upper_bound is not None and ctx.planned_outings_remaining is not None:
        if state.island_tickets + ctx.planned_outings_remaining > audit.free_turn_upper_bound:
            result.cautions.append('행동 예산이 부족할 수 있습니다. 아래 각 선택의 장기 비용은 계산하지 않았습니다.')
    for index, row in enumerate(ranked, 1):
        name = row['name']
        action = actions[name]
        after = min(100, state.energy + action.energy_delta)
        toward = {stat: min(action.gains[stat], max(0, profile.target_stats[stat] - state.stats[stat]))
                  for stat in STATS}
        notes = []
        if sum(toward.values()):
            highlights = ', '.join(f'{s} +{n}' for s, n in toward.items() if n > 0)
            notes.append(f'현재 사용자 목표 부족량 중 입력 상승이 기여하는 부분: {highlights}')
        else:
            notes.append('입력한 스탯 상승으로 사용자 목표 부족량이 줄어드는 항목이 없습니다.')
        if action.energy_delta < 0 and after < 30:
            notes.append(f'선택 뒤 체력 {after}: 다음 턴 체력 부담 확인 (검증된 실패 예측 아님).')
        if name == '섬 트레이닝':
            if ctx.ticket_phase == '첫 1~2회':
                notes.append('초기 티켓: 인연 확보를 위한 조기 사용 예외를 검토. 우정 3곳 고정 조건 아님. [R33_H01]')
            elif ctx.ticket_phase == '이후':
                if action.friend_types >= 3:
                    notes.append('이후 티켓: R6에서 확인한 우정 3곳 이상. 다른 행동·만료 일정과 비교. [R33_H02]')
                else:
                    notes.append('이후 티켓: 우정 3곳 미만이지만 만료·인연 부족 예외 검토. [R33_H02]')
            else:
                notes.append('첫 티켓인지 이후 티켓인지 확인 전: 최적 사용 시점 판단 보류.')
            if ctx.friendship_locations is not None and ctx.friendship_locations != action.friend_types:
                result.missing.append('섬 훈련 우정 시설 수: ⑦ R6 입력과 R34 수동 입력이 다릅니다.')
                notes.append('R6·R34 우정 발생 시설 수 불일치. 두 화면을 확인하세요.')
            if state.turns_until_next_ticket in (0, 1):
                notes.append('다음 티켓 수령 임박: 보유 한도·중복 소멸 규칙을 확인하세요.')
            if ctx.turns_to_next_mandatory_race in (0,1):
                notes.append('현재/다음 턴 목표 레이스와 섬 훈련 사용 시점의 충돌 가능성을 확인하세요. [R33_H06]')
        elif name == '레이스':
            if ctx.turns_to_next_mandatory_race == 0:
                notes.append('이번 턴 필수 목표 레이스 여부를 직접 확인하세요.')
            else:
                notes.append('필수 목표 레이스인지 자유 출전인지는 입력만으로 확정할 수 없습니다.')
            notes.append('스킬 Pt·발전 Pt 외에 획득 힌트/기회비용은 아직 평가하지 않습니다. [R33_H05]')
        elif name == '외출':
            notes.append('외출 뒤 보너스·서포트 이벤트와 남은 외출 계획은 수치 검증 전입니다. [R33_H09]')
        elif name == '휴식':
            notes.append('휴식 회복량만 수치로 표시하며 이후 서포트 배치·훈련 이득은 예측하지 않습니다.')
        if audit.free_turn_upper_bound is not None and audit.free_turn_upper_bound <= 1 and name not in ('레이스',):
            notes.append('남은 자유 턴 상한이 매우 작아 다음 행동 계획을 먼저 확인하세요. [R33_H09]')
        result.actions.append(ActionComparison(
            name=name, r6_experimental_rank=index, r6_experimental_score=float(row['score']),
            observed_gains={s:action.gains[s] for s in STATS},
            gains_toward_user_target=toward, energy_after=after,
            skill_points_gain=action.skill_points,
            development_points_gain=action.development_points, notes=notes))
    if result.missing:
        result.status = '입력 확인 필요 · 행동 우열 판단 보류'
    result.cautions.append('R6 순위/점수는 기존 실험 휴리스틱이며 R35의 검증된 추천이 아닙니다.')
    return result
