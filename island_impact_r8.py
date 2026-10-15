"""R8: link R7 construction paths and R6 reviewed island-training evidence.

No unverified stat multipliers are invented. 'Exposure' is a structural
counterfactual under the SAME observed training distribution, not forecast
of future rolls or the facility's game-side formula.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Mapping, Optional

from uma_core import STATS, EVENTS, TRAININGS, Action, RunProfile, TurnState
from island_planner_r7 import (FACILITIES, R7PlanResult, fingerprint,
                               validate_levels, ticket_review)
from decision_r6 import state_fingerprint, evidence_fingerprint

SCHEMA = 'uma_r8_island_impact_v1'


@dataclass
class Coverage:
    phase: str
    candidate: str
    built_friendship_facilities: list[str]
    missing_facilities: list[str]
    participating_friendships: int
    distinct_facilities: int
    beach_multi_friendship_condition: bool
    new_enabled_facilities: list[str] = field(default_factory=list)


@dataclass
class R8Result:
    status: str = '판단 보류'
    context_hash: str = ''
    errors: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    current: Optional[Coverage] = None
    projections: list[Coverage] = field(default_factory=list)
    measured_island_action: Optional[dict] = None
    r6_rank: Optional[int] = None
    r6_total_compared: int = 0
    r6_experimental_score: Optional[float] = None
    construction_verified_for_current_state: bool = False
    post_patch_reference: bool = True
    experimental_only: bool = True
    verified_optimal: bool = False
    ml_training_label_verified: bool = False


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def context_hash(profile: RunProfile, state: TurnState, friendship_counts: Mapping[str, int],
                 r7_result: Optional[R7PlanResult] = None, r7_options: Optional[Mapping] = None,
                 r6_review: Optional[Mapping] = None) -> str:
    body = {'profile_state': state_fingerprint(profile, state),
            'friends': dict(friendship_counts),
            'r7_result': asdict(r7_result) if r7_result else None,
            'r7_options': dict(r7_options) if r7_options else None,
            'r6_review': dict(r6_review) if r6_review else None}
    return hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()


def coverage(phase: str, candidate: str, levels: Mapping[str, int],
             friendship_counts: Mapping[str, int], origin_levels: Optional[Mapping[str, int]] = None) -> Coverage:
    # These are OBSERVED friendship locations (types), not a probability model.
    enabled = [s for s in STATS if levels[s] > 0 and friendship_counts[s] > 0]
    disabled = [s for s in STATS if levels[s] == 0 and friendship_counts[s] > 0]
    added = ([s for s in enabled if origin_levels.get(s, 0) == 0] if origin_levels is not None else [])
    return Coverage(phase, candidate, enabled, disabled,
                    sum(friendship_counts[s] for s in enabled), len(enabled),
                    levels['해변의 집'] >= 1 and len(enabled) >= 2, added)


def inspect_island_impact(profile: RunProfile, state: TurnState, *,
                          friendship_counts: Mapping[str, int],
                          r7_result: Optional[R7PlanResult] = None,
                          r7_options: Optional[Mapping] = None,
                          r6_review: Optional[Mapping] = None,
                          actions: Optional[Mapping[str, Action]] = None,
                          availability: Optional[Mapping[str, str]] = None) -> R8Result:
    """Use only approved, current-turn observations; never infer official stat gains."""
    result = R8Result(context_hash=context_hash(profile, state, friendship_counts,
                                               r7_result, r7_options, r6_review))
    if profile.scenario != 'island_post_patch_v1' or profile.event not in EVENTS:
        result.errors.append('수정 후 무인도 챔미·리오히 육성만 지원합니다.')
    if set(friendship_counts) != set(STATS):
        result.errors.append('스피드·스태미나·파워·근성·지능 5개 시설의 우정 훈련 인원을 모두 확인하세요.')
    for name, number in friendship_counts.items():
        if name not in STATS or type(number) is not int or number < 0 or number > 6:
            result.errors.append(f'{name}: 0~6명의 실제 확인된 우정 훈련 인원만 입력하세요.')
    if result.errors:
        return result
    facility_routes = (r7_options or {}).get('routes') or {}
    # Existing Lv>=3 needs route from R7 config; also check complete level set here.
    if set(state.building_levels) != set(FACILITIES):
        result.errors.append('현재 시설 6종 레벨을 모두 입력하세요.')
        return result
    routes = {s: facility_routes.get(s, '본능' if state.building_levels[s] >= 3 else '미선택')
              for s in FACILITIES}
    # R7 paths supply actual route; without it don't pretend guessed routes verified.
    for s in STATS:
        if state.building_levels[s] >= 3 and (r7_options is None or s not in facility_routes):
            result.errors.append(f'{s} 시설 Lv3 이상인 경우 R7에서 분기를 먼저 검수하세요.')
    result.errors.extend(validate_levels(state.building_levels, routes))
    if type(state.island_tickets) is not int or not 0 <= state.island_tickets <= 3:
        result.errors.append('현재 섬 티켓 수를 확인하세요.')
    if result.errors:
        return result
    if state.island_tickets > 1 and r7_options is None:
        result.errors.append('섬 티켓 2장 이상은 후반 시기 확인이 필요합니다. R7에서 시니어 9월 전반 이후 여부를 검수하세요.')
        return result
    if r7_result is not None or r7_options is not None:
        if (r7_result is None or r7_options is None
                or r7_result.status != '건설 경로 비교 가능 (실험용)'
                or r7_result.errors or not r7_result.candidates
                or fingerprint(profile, state, r7_options) != r7_result.context_hash):
            result.errors.append('R7 건설 계획이 현재 턴과 일치하지 않습니다. R7에서 다시 계산하세요.')
            return result
        result.construction_verified_for_current_state = True

    result.current = coverage('현재 턴', '현재 시설', state.building_levels, friendship_counts)
    if result.current.missing_facilities:
        result.cautions.append('우정 훈련이 있어도 해당 시설 미건설로 섬 트레이닝 적용에서 제외되는 타입: '
                              + ', '.join(result.current.missing_facilities))
    if not state.building_levels['해변의 집'] and result.current.distinct_facilities >= 2:
        result.cautions.append('여러 시설에서 우정 훈련이 확인됐지만 해변의 집은 아직 건설되지 않았습니다.')
    if state.island_tickets == 0:
        result.cautions.append('섬 티켓이 0장이므로 이번 턴 섬 트레이닝은 선택할 수 없습니다.')
    elif state.turns_until_next_ticket < 0:
        result.cautions.append('다음 섬 티켓 지급 시점이 미확인이라 사용/대기 추천을 확정할 수 없습니다.')
    elif state.turns_until_next_ticket <= 1 and state.island_tickets >= 1:
        result.cautions.append('다음 티켓 수령이 임박했습니다. 해당 시점의 보유 상한과 손실 위험을 확인하세요.')

    if r7_result is not None:
        for idx, candidate in enumerate(r7_result.candidates, start=1):
            for phase in candidate.phases:
                result.projections.append(coverage(f'{phase.phase}회차 완료', f'경로 {idx}',
                                           phase.levels_after, friendship_counts,
                                           state.building_levels))
        result.cautions.append('미래 건설 경로 비교에는 현재 우정 훈련 배치가 동일하게 유지된다는 가상 조건을 사용했습니다. '
                              '미래 스탯 상승량·우정 발생 확률·승률을 예측하지 않습니다.')
    else:
        result.cautions.append('R7 시설 계획 검수 전이므로 현재 시설 상태만 분석합니다.')

    # R6 is ONLY used when it has rechecked all possible actions THIS turn.
    if r6_review is not None:
        valid = bool(isinstance(r6_review, Mapping) and r6_review.get('schema') == 'uma_r6_turn_review_v1'
                     and r6_review.get('context_hash') == state_fingerprint(profile, state)
                     and r6_review.get('status') != '추천 보류'
                     and actions is not None and availability is not None
                     and r6_review.get('evidence_hash') == evidence_fingerprint(actions, availability)
                     and availability.get('섬 트레이닝') == '가능')
        if valid:
            action = actions.get('섬 트레이닝')
            if isinstance(action, Action) and action.observed and state.island_tickets > 0:
                ranks = r6_review.get('ranked', [])
                match = [(i, v) for i, v in enumerate(ranks, 1) if v.get('name') == '섬 트레이닝']
                if match:
                    i, ranked = match[0]
                    result.measured_island_action = {'stats': dict(action.gains),
                                                     'skill_points': action.skill_points,
                                                     'energy_delta': action.energy_delta,
                                                     'failure_percent': action.failure_percent,
                                                     'development_points': action.development_points,
                                                     'source': '이번 턴 R6 사용자 검수 값'}
                    result.r6_rank = i
                    result.r6_total_compared = len(ranks)
                    result.r6_experimental_score = ranked.get('score')
        if result.measured_island_action is None:
            result.cautions.append('R6 전체 선택지 검수 자료가 현재 턴과 일치하지 않아 섬 훈련 수치를 연결하지 않았습니다.')
    else:
        result.cautions.append('R6 전체 행동 검수가 없어 실제 섬 훈련 상승량 및 행동 순위는 연결하지 않았습니다.')

    result.status = ('구조 비교 가능 · R6 실측 연계' if result.measured_island_action
                     else '구조 비교 가능 · 수치 예측 보류')
    return result


def export_impact(path: Path, profile: RunProfile, state: TurnState, result: R8Result,
                  *, friendship_counts: Mapping[str, int],
                  r7_result: Optional[R7PlanResult] = None, r7_options: Optional[Mapping] = None,
                  r6_review: Optional[Mapping] = None,
                  actions: Optional[Mapping[str, Action]] = None,
                  availability: Optional[Mapping[str, str]] = None) -> Path:
    if r6_review is not None and (actions is None or availability is None
                                  or r6_review.get('context_hash') != state_fingerprint(profile, state)
                                  or r6_review.get('evidence_hash') != evidence_fingerprint(actions, availability)):
        raise ValueError('R6 선택지 검수가 변경되었습니다. 다시 확인해 주세요.')
    if (result.errors or result.status == '판단 보류' or result.current is None
        or result.context_hash != context_hash(profile, state, friendship_counts,
                                               r7_result, r7_options, r6_review)):
        raise ValueError('기존 검수 이후 상태가 변경됐습니다. R8을 다시 분석해 주세요.')
    data = {'schema': SCHEMA, 'experimental_only': True, 'verified_optimal': False,
            'ml_training_label_verified': False, 'profile': asdict(profile),
            'state': {k: v for k, v in asdict(state).items() if k != 'screenshot'},
            'friendship_counts': dict(friendship_counts),
            'r7_context_hash': r7_result.context_hash if r7_result else None,
            'r6_context_hash': r6_review.get('context_hash') if r6_review else None,
            'result': asdict(result), 'method': 'structural_counterfactual_same_layout'}
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(prefix='uma_r8_', suffix='.tmp', dir=str(output.parent))
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return output
