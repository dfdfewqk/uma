"""R7: verifiable island facility costs + an intentionally UNCALIBRATED plan explorer.

Fixed structural rules are sourced in docs/R7_검증자료.md. The scoring weights,
future turn forecasts and suggested upgrade plans are experimental heuristics,
not official growth formulas and not ML. No gameplay automation is performed.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from itertools import product
from pathlib import Path
from typing import Mapping, Optional

from uma_core import EVENTS, STATS, RunProfile, TurnState, value_weights

FACILITIES = STATS + ('해변의 집',)
ROUTES = ('미선택', '본능', '기교')
SCHEMA = 'uma_island_r7_plan_v1'
# Number of construction-plan slots, based on Tucker support rarity/level.
SLOTS_BY_TUCKER = {
    '미편성': (3, 3, 4, 4, 6),
    'Lv1~40': (3, 4, 5, 5, 7),
    'Lv41~50': (4, 5, 6, 6, 8),
}
PHASE_NAMES = ('주니어 6월 평가회', '주니어 12월 평가회', '클래식 6월 평가회',
               '클래식 12월 평가회', '시니어 6월 최종 평가회')
# Individual incremental slot costs. Lv3+ has a mutually exclusive route.
STAT_COSTS = {'본능': (1, 1, 2, 2, 3), '기교': (1, 1, 1, 1, 2)}
BEACH_COSTS = (2, 3, 3)


@dataclass(frozen=True)
class Upgrade:
    facility: str
    new_level: int
    route: str
    cost: int


@dataclass(frozen=True)
class PhasePlan:
    phase: int
    title: str
    capacity: int
    used: int
    upgrades: tuple[Upgrade, ...]
    levels_after: dict[str, int]
    routes_after: dict[str, str]


@dataclass
class PlanCandidate:
    score_proxy: float
    phases: list[PhasePlan]
    final_levels: dict[str, int]
    final_routes: dict[str, str]
    explanation: list[str] = field(default_factory=list)


@dataclass
class R7PlanResult:
    status: str
    candidates: list[PlanCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    ticket_advice: list[str] = field(default_factory=list)
    context_hash: str = ''
    experimental_only: bool = True
    verified_optimal: bool = False


def upgrade_cost(name: str, new_level: int, route: str = '미선택') -> int:
    if name not in FACILITIES:
        raise ValueError(f'알 수 없는 시설: {name}')
    if type(new_level) is not int:
        raise ValueError('시설 레벨은 정수여야 합니다.')
    if name == '해변의 집':
        if route != '미선택' or new_level not in (1, 2, 3):
            raise ValueError('해변의 집은 Lv1~3이며 분기 선택이 없습니다.')
        return BEACH_COSTS[new_level-1]
    if new_level not in range(1, 6):
        raise ValueError('일반 시설 레벨 범위는 1~5입니다.')
    if new_level <= 2:
        if route != '미선택':
            raise ValueError('Lv1~2에는 분기가 없습니다.')
        return 1
    if route not in ('본능', '기교'):
        raise ValueError('Lv3~5에서 본능/기교 분기를 선택해야 합니다.')
    return STAT_COSTS[route][new_level-1]


def validate_levels(levels: Mapping[str, int], routes: Mapping[str, str]) -> list[str]:
    errors = []
    for name in FACILITIES:
        lv = levels.get(name)
        route = routes.get(name, '미선택')
        limit = 3 if name == '해변의 집' else 5
        if type(lv) is not int or not (0 <= lv <= limit):
            errors.append(f'{name}: 시설 레벨은 0~{limit} 정수여야 합니다.')
        if route not in ROUTES:
            errors.append(f'{name}: 분기 선택이 올바르지 않습니다.')
        if name == '해변의 집' or (type(lv) is int and lv < 3):
            if route != '미선택':
                errors.append(f'{name}: 현재 레벨에서는 분기를 선택할 수 없습니다.')
        elif route == '미선택':
            errors.append(f'{name}: Lv3 이상이므로 기존 본능/기교 분기를 확인해야 합니다.')
    if set(levels) != set(FACILITIES):
        errors.append('6개 시설의 레벨을 모두 확인해야 합니다.')
    return errors


def legal_upgrades(levels: Mapping[str, int], routes: Mapping[str, str],
                   *, facility: str) -> tuple[Upgrade, ...]:
    if facility not in FACILITIES:
        raise ValueError('시설 이름을 확인하세요.')
    lv = levels[facility]
    if lv >= (3 if facility == '해변의 집' else 5):
        return ()
    next_level = lv + 1
    if facility == '해변의 집' or next_level <= 2:
        route_choices = ('미선택',)
    elif next_level == 3:
        route_choices = ('본능', '기교')
    else:
        route_choices = (routes[facility],)  # route cannot change after Lv3
    return tuple(Upgrade(facility, next_level, route, upgrade_cost(facility, next_level, route))
                 for route in route_choices)


def fingerprint(profile: RunProfile, state: TurnState, options: Mapping) -> str:
    data = {'profile': asdict(profile),
            'state': {k: v for k, v in asdict(state).items() if k != 'screenshot'},
            'options': dict(options)}
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def exam_progress(*, development_points: int, target_points: Optional[int],
                  remaining_turns: Optional[int], expected_points_per_turn: Optional[int]) -> list[str]:
    if target_points is None or remaining_turns is None or expected_points_per_turn is None:
        return ['평가회 발전 Pt 요구량·남은 턴·턴당 예상 획득량 중 미입력 값이 있어 달성 예측을 보류합니다.']
    if any(type(x) is not int for x in (development_points, target_points, remaining_turns, expected_points_per_turn)):
        raise ValueError('평가회 발전 Pt 값은 정수로 입력해야 합니다.')
    if not (0 <= development_points <= 100000 and 0 < target_points <= 100000
            and 0 <= remaining_turns <= 150 and 0 <= expected_points_per_turn <= 2000):
        raise ValueError('평가회 입력값의 범위를 확인하세요.')
    need = max(0, target_points - development_points)
    if need == 0:
        return ['입력한 평가회 목표 발전 Pt에 이미 도달했습니다. 실제 건설 진척을 확인하세요.']
    if remaining_turns == 0:
        return [f'목표까지 발전 Pt {need} 부족하며 입력한 남은 턴이 0입니다. 평가회 상황 확인이 필요합니다.']
    per_turn = need / remaining_turns
    estimated = expected_points_per_turn * remaining_turns
    if estimated < need:
        return [f'부족 {need}Pt · 필요 평균 {per_turn:.1f}Pt/턴 · 입력한 획득 가정으로는 {need-estimated}Pt 부족할 수 있습니다.']
    return [f'부족 {need}Pt · 필요 평균 {per_turn:.1f}Pt/턴 · 입력한 획득 가정으로는 도달 가능합니다(미검증).']


def ticket_review(*, tickets: int, senior_september_or_later: bool,
                  next_ticket_turns: Optional[int], friendship_locations: Optional[int]) -> list[str]:
    if type(tickets) is not int or tickets < 0:
        raise ValueError('티켓 보유량을 확인하세요.')
    cap = 3 if senior_september_or_later else 1
    if tickets > cap:
        raise ValueError(f'입력한 시기에서는 티켓 상한이 {cap}장입니다. 시기 또는 티켓 수를 확인하세요.')
    if next_ticket_turns is not None and (type(next_ticket_turns) is not int or not 0 <= next_ticket_turns <= 100):
        raise ValueError('다음 티켓까지 턴 수를 확인하세요.')
    if friendship_locations is not None and (type(friendship_locations) is not int or not 0 <= friendship_locations <= 5):
        raise ValueError('우정 훈련이 발생한 시설 수를 확인하세요.')
    out = [f'현재 시기 보유 상한 {cap}장 · 보유 {tickets}장.']
    if senior_september_or_later:
        out.append('시니어 9월 전반 이후에는 신규 티켓 지급이 없으므로 남은 육성 턴에 맞게 사용할 시점을 비교하세요.')
    elif tickets and next_ticket_turns is not None and next_ticket_turns <= 1:
        out.append('다음 티켓이 임박했습니다. 상한으로 인한 티켓 손실 위험을 확인하세요.')
    elif tickets and next_ticket_turns is None:
        out.append('다음 티켓 수령 시점을 확인하지 못했습니다. 사용 시점 추천은 보류합니다.')
    if tickets:
        if friendship_locations is None:
            out.append('우정 훈련 발생 시설 수가 미확인입니다. 섬 트레이닝 사용 추천을 보류합니다.')
        elif friendship_locations >= 3:
            out.append(f'{friendship_locations}개 시설에서 우정 훈련을 확인했습니다. 현재 사용 기대값을 게임 화면에서 비교하세요.')
        elif friendship_locations <= 1:
            out.append('우정 훈련이 적습니다. 다만 초기 인연도 확보와 다음 티켓 임박 여부도 함께 고려해야 합니다.')
    return out


def _step_value(upgrade: Upgrade, phase: int, priorities: Mapping[str, float]) -> float:
    # PROXY, not simulated game gains or real win rates.
    if upgrade.facility == '해변의 집':
        base = (7.6, 3.2, 2.5)[upgrade.new_level-1]
    else:
        base = (2.9, 3.0, 4.8, 4.6, 6.3)[upgrade.new_level-1] * priorities[upgrade.facility]
        if upgrade.new_level >= 3 and upgrade.route == '기교':
            base *= 0.81
    # Earlier completed facilities can contribute over more future turns.
    return base * (1.0 + (5-phase)*0.10)


def _enumerate_phase(levels: tuple[int, ...], routes: tuple[str, ...], budget: int):
    """One upgrade per facility in a phase (conservative exploratory scope)."""
    lv = dict(zip(FACILITIES, levels))
    rt = dict(zip(FACILITIES, routes))
    choices = [(None,)+legal_upgrades(lv, rt, facility=name) for name in FACILITIES]
    for selected in product(*choices):
        steps = tuple(x for x in selected if x)
        spent = sum(x.cost for x in steps)
        if spent > budget:
            continue
        newlevels = lv.copy()
        newroutes = rt.copy()
        for up in steps:
            newlevels[up.facility] = up.new_level
            if up.new_level >= 3 and up.facility != '해변의 집':
                newroutes[up.facility] = up.route
        yield steps, spent, tuple(newlevels[x] for x in FACILITIES), tuple(newroutes[x] for x in FACILITIES)


def plan_island(profile: RunProfile, state: TurnState, *, phase: int, tucker: str,
                routes: Mapping[str, str], support_counts: Optional[Mapping[str,int]] = None,
                growth_bonus_stat: str = '없음', exam_target: Optional[int] = None,
                exam_turns: Optional[int] = None, expected_dp_per_turn: Optional[int] = None,
                senior_september_or_later: bool = False,
                friendship_locations: Optional[int] = None, top_n: int = 3,
                beam_width: int = 130) -> R7PlanResult:
    options = {'phase': phase, 'tucker': tucker, 'routes': dict(routes),
               'support_counts': dict(support_counts or {}), 'growth_bonus_stat': growth_bonus_stat,
               'exam_target': exam_target, 'exam_turns': exam_turns, 'expected_dp_per_turn': expected_dp_per_turn,
               'senior_september_or_later': senior_september_or_later,
               'friendship_locations': friendship_locations}
    result = R7PlanResult(status='추천 보류', context_hash=fingerprint(profile, state, options))
    if profile.scenario != 'island_post_patch_v1' or profile.event not in EVENTS:
        result.errors.append('무인도 시나리오의 챔미/리오히 프로필만 지원합니다.')
    if type(phase) is not int or phase not in range(1, 6):
        result.errors.append('건설 계획은 1~5회차만 지원합니다.')
    if tucker not in SLOTS_BY_TUCKER:
        result.errors.append('터커 브라인 등급을 선택해야 합니다.')
    result.errors.extend(validate_levels(state.building_levels, routes))
    counts = dict(support_counts or {})
    if set(counts) - set(STATS) or any(type(x) is not int or not 0 <= x <= 6 for x in counts.values()) or sum(counts.values()) > 6:
        result.errors.append('서포트 카드 타입별 장수를 0~6장(합계 6장 이하)으로 확인하세요.')
    if growth_bonus_stat not in (*STATS, '없음'):
        result.errors.append('성장 보정 스탯을 확인하세요.')
    if not 1 <= top_n <= 10 or not 10 <= beam_width <= 1000:
        result.errors.append('탐색 범위를 확인하세요.')
    if result.errors:
        return result
    try:
        result.ticket_advice = ticket_review(tickets=state.island_tickets,
            senior_september_or_later=senior_september_or_later,
            next_ticket_turns=state.turns_until_next_ticket if state.turns_until_next_ticket >= 0 else None,
            friendship_locations=friendship_locations)
        result.progress = exam_progress(development_points=state.development_points,
            target_points=exam_target, remaining_turns=exam_turns,
            expected_points_per_turn=expected_dp_per_turn)
    except ValueError as e:
        result.errors.append(str(e))
        return result
    if phase == 5 and senior_september_or_later:
        result.errors.append('시니어 9월 이후에는 건설 계획이 종료되었습니다. 기존 계획을 조회해 주세요.')
        return result
    try:
        weights = value_weights(profile, state)
    except (ValueError, KeyError, TypeError):
        result.errors.append('육성 목표와 스탯 입력을 확인하세요.')
        return result
    if sum(counts.values()) == 0:
        result.warnings.append('서포트 카드 타입별 편성 정보가 없어 편성 가중치는 적용하지 않았습니다.')
    if growth_bonus_stat == '없음':
        result.warnings.append('캐릭터 성장 보정 미입력. 시설 우선순위는 목표 스탯 부족량 위주로 계산합니다.')
    priorities = {stat: weights[stat] * (1 + 0.08*counts.get(stat, 0)) *
                  (0.90 if growth_bonus_stat == stat else 1.0) for stat in STATS}
    # Retain just the best paths by final facility/route state after every phase.
    level0 = tuple(state.building_levels[s] for s in FACILITIES)
    route0 = tuple(routes[s] for s in FACILITIES)
    beam = {(level0, route0): (0.0, [])}
    for p in range(phase, 6):
        next_beam = {}
        for (levels, route_ids), (score, path) in beam.items():
            for steps, used, lv2, rt2 in _enumerate_phase(levels, route_ids, SLOTS_BY_TUCKER[tucker][p-1]):
                # Reward progress and penalize unused build slots slightly.
                gain = sum(_step_value(up, p, priorities) for up in steps) - 0.35*(SLOTS_BY_TUCKER[tucker][p-1]-used)
                newscore = score + gain
                key = (lv2, rt2)
                if key not in next_beam or next_beam[key][0] < newscore:
                    record = PhasePlan(p, PHASE_NAMES[p-1], SLOTS_BY_TUCKER[tucker][p-1], used,
                                       steps, dict(zip(FACILITIES, lv2)), dict(zip(FACILITIES, rt2)))
                    next_beam[key] = (newscore, path+[record])
        if not next_beam:
            result.errors.append(f'{p}회차에 유효한 건설 계획을 생성하지 못했습니다.')
            return result
        beam = dict(sorted(next_beam.items(), key=lambda x: x[1][0], reverse=True)[:beam_width])
    final = sorted(beam.items(), key=lambda x: x[1][0], reverse=True)
    # The top few path options may lead to similar levels; keep candidates distinct.
    for (levels, rt), (score, path) in final[:top_n]:
        result.candidates.append(PlanCandidate(round(score,2), path,
            dict(zip(FACILITIES, levels)), dict(zip(FACILITIES, rt)),
            ['남은 단계의 건설 선택에 대한 가상 비교이며 정답 또는 최적 성장 수치가 아닙니다.',
             '현재 시설 레벨은 사용자가 확인한 완료 상태를 기준으로 합니다.']))
    result.status = '건설 경로 비교 가능 (실험용)'
    result.warnings.append('동일 회차에 한 시설을 최대 1레벨만 강화하는 보수적 탐색 가정을 사용합니다. 게임에서 추가 강화가 가능한 경우 실제 선택과 차이가 날 수 있습니다.')
    result.warnings.append('건설 진행 순서와 각 단계별 발전 Pt 획득 시점은 미모델링. 실제 보상·최적 성장 검증 전입니다.')
    return result


def export_plan(path: Path, profile: RunProfile, state: TurnState, result: R7PlanResult,
                options: Mapping) -> Path:
    if result.status != '건설 경로 비교 가능 (실험용)' or not result.candidates or result.errors:
        raise ValueError('검증 가능한 계획 결과가 없습니다.')
    if fingerprint(profile, state, options) != result.context_hash:
        raise ValueError('입력 상태가 변경되었습니다. 새로 분석한 뒤 저장하세요.')
    doc = {'schema': SCHEMA, 'experimental_only': True, 'verified_optimal': False,
           'ml_training_label_verified': False, 'profile': asdict(profile),
           'state': {k: v for k,v in asdict(state).items() if k != 'screenshot'},
           'options': dict(options), 'result': asdict(result)}
    data = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf8')
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='island_r7_', suffix='.tmp', dir=str(output.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return output
