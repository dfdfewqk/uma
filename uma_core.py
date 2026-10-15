"""Uma Trainer KR - inspectable heuristic decision engine.

All numerical weights in this file are exploratory design parameters,
NOT official game mechanics or trained/validated ML predictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple
from scenario_policies import IslandPostPatchPolicy, POLICIES, SCENARIOS

STATS = ('스피드', '스태미나', '파워', '근성', '지능')
TRAININGS = STATS + ('섬 트레이닝', '휴식', '외출', '레이스')
EVENTS = ('챔피언스 미팅', '리그 오브 히어로즈')
DISTANCES = ('단거리', '마일', '중거리', '장거리')
STYLES = ('도주', '선행', '선입', '추입')
DEFAULT_TARGETS = {
    '단거리': (1700, 750, 1300, 1200, 1200),
    '마일': (1700, 950, 1250, 1150, 1200),
    '중거리': (1700, 1200, 1200, 1100, 1150),
    '장거리': (1700, 1500, 1150, 1000, 1150),
}
# Above targets are UI starting examples, NOT recommended competitive thresholds.


def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


@dataclass
class RunProfile:
    scenario: str = 'island_post_patch_v1'
    event: str = '챔피언스 미팅'
    distance: str = '중거리'
    style: str = '선행'
    character: str = ''
    target_stats: Dict[str, int] = field(default_factory=lambda: dict(zip(STATS, DEFAULT_TARGETS['중거리'])))
    target_skill_points: int = 2500
    notes: str = ''
    course: str = ''
    surface: str = '잔디'
    course_direction: str = '미정'
    race_conditions: str = ''
    support_deck: str = ''
    inheritance_notes: str = ''


@dataclass
class TurnState:
    turn_label: str = '주니어급 7월 전반'
    remaining_turns: int = 48
    energy: int = 80
    mood: str = '보통'
    stats: Dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATS, 300))
    skill_points: int = 200
    island_tickets: int = 0
    turns_until_next_ticket: int = -1  # -1 unknown
    development_points: int = 0
    building_levels: Dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATS + ('해변의 집',), 0))
    core_skill_status: str = '미확인'
    screenshot: str = ''


@dataclass
class Action:
    name: str
    gains: Dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATS, 0))
    skill_points: int = 0
    energy_delta: int = 0  # negative=spend, positive=recover
    friend_types: int = 0  # distinct friendship training locations; important for island
    bond_gain: int = 0    # user-assessed heuristic units
    failure_percent: float = 0.0
    development_points: int = 0
    notes: str = ''
    observed: bool = False  # Distinguish unentered/unavailable from truly zero gains


@dataclass
class RankedAction:
    name: str
    score: float
    reasons: List[str]
    breakdown: Dict[str, float]




def default_actions() -> Dict[str, Action]:
    return {name: Action(name=name) for name in TRAININGS}


def value_weights(profile: RunProfile, state: TurnState) -> Dict[str, float]:
    # Soft priorities favor missing target stats. The cap prevents implausible runaway scores.
    weights: Dict[str, float] = {}
    importance = {
        '단거리': (1.15, 0.77, 1.11, 1.02, 1.02),
        '마일': (1.14, 0.88, 1.08, 1.04, 1.02),
        '중거리': (1.12, 1.05, 1.07, 0.99, 1.01),
        '장거리': (1.08, 1.19, 1.03, 0.98, 1.00),
    }[profile.distance]
    for stat, imp in zip(STATS, importance):
        target = max(1, int(profile.target_stats.get(stat, 1)))
        current = int(state.stats.get(stat, 0))
        deficit_ratio = clamp((target - current) / target, -0.5, 1.0)
        weights[stat] = round(imp * clamp(0.70 + deficit_ratio * 0.95, 0.18, 1.68), 4)
    return weights


def rank_actions(profile: RunProfile, state: TurnState, actions: Dict[str, Action]) -> List[RankedAction]:
    """Rank manually-entered observed choice outcomes using explainable, tunable proxies."""
    policy = POLICIES.get(profile.scenario)
    if policy is None:
        raise ValueError('아직 지원되지 않는 시나리오입니다.')
    weights = value_weights(profile, state)
    results: List[RankedAction] = []
    energy_factor = clamp((67.0 - state.energy) / 67.0, 0, 1)
    phase = clamp(state.remaining_turns / 50.0, 0, 1)
    for name, action in actions.items():
        if not action_is_observed(action):
            continue  # Never recommend an unentered option as if its gains were zero.
        if action.name == '섬 트레이닝' and state.island_tickets <= 0:
            continue  # The unavailable ticket action must never appear as the top suggestion.
        if action.energy_delta < 0 and state.energy + action.energy_delta < 0:
            continue  # Exclude impossible-energy options instead of recommending a negative score.
        reasons: List[str] = []
        parts: Dict[str, float] = {}
        if name != action.name:
            raise ValueError(f'선택 항목 불일치: {name}')
        gains_value = sum(max(0, action.gains.get(s, 0)) * weights[s] for s in STATS)
        # Skill points are treated as proxy for usable competitive skill choices.
        skill_value = max(0, action.skill_points) * 0.65
        bond_value = clamp(action.bond_gain, 0, 100) * (0.65 * phase)
        energy_value = action.energy_delta * (0.24 + 0.88 * energy_factor)
        # Deliberately penalize bad failure rolls based on risk and action reward.
        # LoH consistency is rewarded slightly more than Champ Meeting high roll.
        risk_importance = 1.20 if profile.event == '리그 오브 히어로즈' else 1.0
        failure_cost = clamp(action.failure_percent, 0, 100) / 100.0 * (28 + 0.65 * gains_value) * risk_importance
        parts.update({'스탯 기대 기여': round(gains_value, 2), '스킬 Pt 기여': round(skill_value, 2),
                      '인연도 기여(추정)': round(bond_value, 2), '체력 변화': round(energy_value, 2),
                      '실패 위험': round(-failure_cost, 2)})
        score = gains_value + skill_value + bond_value + energy_value - failure_cost
        if gains_value:
            best = sorted(((s, action.gains.get(s, 0)) for s in STATS), key=lambda t: t[1] * weights[t[0]], reverse=True)[0]
            reasons.append(f'{best[0]} +{best[1]} 포함, 목표 부족 스탯 가중 평가')
        if action.skill_points:
            reasons.append(f'스킬 Pt +{action.skill_points} (실전 스킬 확보용 자원으로 추정)')
        if action.energy_delta < 0 and state.energy + action.energy_delta < 0:
            score -= 100000
            parts['체력 불가'] = -100000.0
            reasons.append('체력 부족: 선택 불가 또는 입력값 확인 필요')
        elif action.energy_delta < 0 and state.energy + action.energy_delta < 15:
            score -= 9.0
            parts['다음 턴 체력 부담'] = -9.0
            reasons.append('선택 후 체력이 매우 낮아질 수 있음')
        extra, explain, extra_parts = policy.adjust(profile, state, action)
        score += extra
        reasons.extend(explain)
        parts.update(extra_parts)
        if not reasons:
            reasons.append('현재 입력한 수치로 계산함. 실제 훈련 정보가 비어 있으면 판단할 수 없음')
        results.append(RankedAction(name=name, score=round(score, 2), reasons=reasons, breakdown=parts))
    return sorted(results, key=lambda item: item.score, reverse=True)


def action_is_observed(action: Action) -> bool:
    # Legacy V0.1 data may have no observed field. Recover nonempty entries.
    return bool(action.observed or any(action.gains.values()) or action.skill_points
                or action.energy_delta or action.bond_gain or action.development_points
                or action.failure_percent or action.friend_types)


def input_coverage(actions: Dict[str, Action]) -> int:
    """Count entries with at least one meaningful manual estimate."""
    return sum(1 for a in actions.values() if action_is_observed(a))


def assess_run(profile: RunProfile, state: TurnState) -> Tuple[str, List[str]]:
    """Cautious status check. No win-rate probability or definitive quit decision."""
    if state.remaining_turns <= 0:
        return '종료 확인', ['남은 턴이 없습니다. 최종 스탯과 스킬을 직접 평가하세요.']
    warnings = []
    for stat in STATS:
        target = profile.target_stats.get(stat, 0)
        gap = max(0, target - state.stats.get(stat, 0))
        if gap > 0:
            per_turn = gap / max(1, state.remaining_turns)
            if per_turn >= 45:
                warnings.append(f'{stat}: 목표까지 {gap} 필요 / 남은 턴당 평균 {per_turn:.1f} (높은 추격 부담)')
    if state.core_skill_status == '미확보':
        warnings.append('필수 스킬 미확보: 대체 스킬 및 획득 경로 확인 필요')
    if state.island_tickets > 0 and state.turns_until_next_ticket == 0:
        warnings.append('티켓 보유 중 다음 지급 직전: 사용 여부 확인')
    if warnings:
        return '주의 · 재계산 필요', warnings + ['도축은 추천하지 않습니다. 현재 수치만으로 포기 여부를 단정할 수 없습니다.']
    return '육성 계속 검토', ['현재 입력한 목표 대비 명백한 위험 신호는 제한적입니다.',
                           '이 평가는 간단한 기준선으로, 실전 승률·결과 보장이 아닙니다.']


def profile_to_dict(profile: RunProfile) -> dict:
    return asdict(profile)


def state_to_dict(state: TurnState) -> dict:
    return asdict(state)


def action_to_dict(action: Action) -> dict:
    return asdict(action)
