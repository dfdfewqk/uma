"""R6 scenario-aware, explainable comparison of *all* reviewed actions.

Uses the original R5 exploratory scorer; all score weights are PROXY design values,
not official game mechanics, trained ML or validated win probabilities. Neither this
module nor the UI operates the game or automatically abandons a run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from uma_core import (Action, RunProfile, TurnState, RankedAction, STATS,
                      TRAININGS, rank_actions, EVENTS)
from scenario_policies import POLICIES

UNKNOWN = '미확인'
AVAILABLE = '가능'
UNAVAILABLE = '불가'
STATUSES = (UNKNOWN, AVAILABLE, UNAVAILABLE)
SCHEMA = 'uma_r6_whole_turn_review_v1'


@dataclass
class R6Result:
    status: str
    ranked: list[RankedAction] = field(default_factory=list)
    missing: dict[str, str] = field(default_factory=dict)
    cautions: list[str] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)
    context_hash: str = ''
    evidence_hash: str = ''
    # Crucially, a score sort is not a calibrated P(win) or a verified best move.
    verified_optimal: bool = False


def state_fingerprint(profile: RunProfile, state: TurnState) -> str:
    """Changes in objective or turn state require NEW confirmation of availability."""
    snapshot = {
        'profile': asdict(profile),
        'state': {k: v for k, v in asdict(state).items() if k != 'screenshot'},
    }
    data = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def evidence_fingerprint(actions: Mapping[str, Action], availability: Mapping[str, str]) -> str:
    snapshot = {'actions': {key: asdict(value) for key, value in actions.items() if key in TRAININGS},
                'availability': {name: availability.get(name, UNKNOWN) for name in TRAININGS}}
    data = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf8')).hexdigest()


def _validate_action(name: str, action: Action) -> str:
    if not isinstance(action, Action) or name != action.name:
        return '행동 이름 또는 데이터 구조가 일치하지 않습니다.'
    if not action.observed:
        return '이 행동의 수치를 사용자 확인으로 표시하지 않았습니다.'
    for stat in STATS:
        val = action.gains.get(stat)
        if type(val) is not int or not (0 <= val <= 999):
            return f'{stat} 상승량을 확인하세요.'
    if type(action.skill_points) is not int or not (0 <= action.skill_points <= 9999):
        return '스킬 Pt 상승량을 확인하세요.'
    if type(action.energy_delta) is not int or not (-100 <= action.energy_delta <= 100):
        return '체력 증감치를 확인하세요.'
    if type(action.bond_gain) is not int or not (0 <= action.bond_gain <= 100):
        return '인연도 추정치를 확인하세요.'
    if type(action.friend_types) is not int or not (0 <= action.friend_types <= 5):
        return '우정 발동 시설 수를 확인하세요.'
    if type(action.development_points) is not int or not (0 <= action.development_points <= 9999):
        return '발전 Pt 수치를 확인하세요.'
    if isinstance(action.failure_percent, bool) or not isinstance(action.failure_percent, (int, float)) or not math.isfinite(action.failure_percent) or not (0 <= action.failure_percent <= 100):
        return '실패율을 확인하세요.'
    return ''


def compare_turn(profile: RunProfile, state: TurnState,
                 actions: Mapping[str, Action], availability: Mapping[str, str],
                 *, confirmed_context_hash: str | None = None) -> R6Result:
    """Fail closed if a potentially available action or its review is missing.

    R5 training comparison only covers training. R6 requires explicit declaration of
    rests, outings and races as AVAILABLE/UNAVAILABLE before offering a whole-turn
    comparison. Unknown ticket timing adds uncertainty, never fake precision.
    """
    fingerprint = state_fingerprint(profile, state)
    result = R6Result(status='추천 보류', context_hash=fingerprint)
    if confirmed_context_hash != fingerprint:
        result.missing['턴 상태'] = '확인 후 턴 상태나 목표가 변경되었습니다. 이번 턴 선택지를 다시 검수하세요.'
        return result
    if profile.scenario not in POLICIES:
        result.missing['시나리오'] = '지원하지 않는 시나리오입니다.'
        return result
    if profile.event not in EVENTS:
        result.missing['육성 목적'] = '챔미·리오히만 지원합니다.'
        return result
    if not isinstance(state.energy, int) or not (0 <= state.energy <= 100):
        result.missing['체력'] = '체력은 0~100 사이여야 합니다.'
        return result
    if state.remaining_turns <= 0:
        result.missing['남은 턴'] = '육성이 종료된 경우 훈련 추천을 하지 않습니다.'
        return result

    allowed = set(TRAININGS)
    for unknown in set(availability) - allowed:
        result.missing[unknown] = '등록되지 않은 행동입니다.'
    checked: dict[str, Action] = {}
    for name in TRAININGS:
        val = availability.get(name, UNKNOWN)
        if val not in STATUSES:
            result.missing[name] = '유효하지 않은 선택지 상태입니다.'
            continue
        if name == '섬 트레이닝' and state.island_tickets <= 0:
            if val == AVAILABLE:
                result.missing[name] = '섬 티켓이 없으므로 가능으로 지정할 수 없습니다.'
            # No user confirmation needed to exclude an action requiring a missing ticket.
            continue
        if val == UNKNOWN:
            result.missing[name] = '이번 턴에 가능한지 확인하지 않았습니다.'
        elif val == AVAILABLE:
            action = actions.get(name)
            problem = _validate_action(name, action) if action is not None else '확인한 수치가 없습니다.'
            if problem:
                result.missing[name] = problem
            elif state.energy + action.energy_delta < 0:
                result.missing[name] = '선택 후 체력이 음수가 됩니다. 체력 변화 또는 선택 가능 여부를 확인하세요.'
            else:
                checked[name] = action
    if result.missing:
        result.explanations.append('미확인 행동이 있으면 전체 행동 중 최선을 추천하지 않습니다.')
        return result
    if not checked:
        result.missing['선택지'] = '가능한 행동이 하나도 없습니다. 입력 상태를 다시 확인하세요.'
        return result

    capped: dict[str, Action] = {}
    overflow = {}
    for name, act in checked.items():
        actual_delta = min(act.energy_delta, 100 - state.energy) if act.energy_delta > 0 else act.energy_delta
        capped[name] = replace(act, energy_delta=actual_delta)
        if actual_delta != act.energy_delta:
            overflow[name] = act.energy_delta - actual_delta

    try:
        ranked = rank_actions(profile, state, capped)
    except (KeyError, ValueError, TypeError) as err:
        result.missing['기초 엔진'] = f'기초 비교를 계산하지 못했습니다: {err}'
        return result

    updated = []
    for item in ranked:
        act = capped[item.name]
        after = state.energy + act.energy_delta
        # An intentionally *small* long-horizon adjustment; uncalibrated.
        future_penalty = -round((30 - after) * 0.45, 2) if after < 30 and act.energy_delta < 0 else 0.0
        future_gain = round(min(max(0, act.bond_gain), 30) * 0.12, 2) if state.remaining_turns >= 30 else 0.0
        parts = dict(item.breakdown)
        parts['R6 다음 턴 저체력 위험(가정)'] = future_penalty
        parts['R6 초반 인연도 미래가치(가정)'] = future_gain
        reasons = list(item.reasons)
        if item.name in overflow:
            # IMPORTANT: cap the recovery before scoring, not just warn afterward.
            reasons.append(f'체력 상한 고려: 입력 회복량 중 {overflow[item.name]}은 초과분으로 제외')
        if future_penalty < 0:
            reasons.append('다음 턴 체력이 낮아질 가능성에 소폭 페널티 적용')
        if future_gain > 0:
            reasons.append('육성 초반 인연도 증가의 미래 가치를 실험적으로 반영')
        if item.name == '레이스':
            reasons.append('레이스의 출전 조건·스킬 Pt·발전 Pt는 사용자가 확인한 수치만 반영')
        if item.name == '섬 트레이닝':
            reasons.append('섬 티켓 기회비용은 R5 무인도 엔진의 실험용 가중치 적용')
        updated.append(RankedAction(item.name, round(item.score + future_penalty + future_gain, 2), reasons, parts))
    updated.sort(key=lambda item: (-item.score, item.name))
    result.ranked = updated
    result.evidence_hash = evidence_fingerprint(actions, availability)
    result.status = '전체 행동 비교 가능 (실험값)'
    if len(updated) == 1:
        result.cautions.append('가능한 행동이 한 종류뿐이어서 다른 대안과 비교할 수 없습니다.')
    elif updated[0].score - updated[1].score < max(8, 0.05 * abs(updated[0].score)):
        result.cautions.append('상위 두 선택의 점수 차이가 작아 우열을 확정하기 어렵습니다.')
        result.status = '선택지 경합 · 추가 검토'
    if '섬 트레이닝' in checked:
        # R27 research review: post-2025-06-30 guides distinguish the first island
        # ticket (often spent early for bond) from later high-friendship ticket use.
        # TurnState does not yet record the ordinal, so preserve the old experimental
        # score but alert the player; never invent or silently infer an ordinal.
        result.cautions.append('첫 섬 트레이닝 티켓인지 자동 확인되지 않았습니다. 첫 티켓은 인연도 확보를 위한 조기 사용 예외가 있으므로 우정 훈련 인원만으로 확정하지 마세요.')
    if state.island_tickets > 0 and state.turns_until_next_ticket == -1:
        result.cautions.append('다음 섬 티켓 수령 시점이 미확인입니다. 티켓 사용의 최적 시점은 판단 불가합니다.')
        result.status = '조건부 비교 · 티켓 시점 미확인'
    if state.core_skill_status == '미확보':
        result.cautions.append('필수 스킬 미확보 상태입니다. 스킬 힌트·레이스 선택의 장기 영향을 따로 확인하세요.')
    result.explanations.extend([
        '이 점수는 입력된 행동의 상대적 평가이며 공식 게임 계산식 또는 검증된 ML 예측이 아닙니다.',
        '레이스·휴식·외출을 포함한 현재 턴 선택지만 비교합니다. 미래의 서포트 배치는 예측하지 않습니다.',
        f'대회: {profile.event} / 거리: {profile.distance} / 남은 턴: {state.remaining_turns}',
    ])
    return result


def export_comparison(path: Path, profile: RunProfile, state: TurnState,
                      actions: Mapping[str, Action], availability: Mapping[str, str],
                      result: R6Result) -> Path:
    """Atomic local research export; *never* interpreted as verified ML labels."""
    if (result.status == '추천 보류'
            or result.context_hash != state_fingerprint(profile, state)
            or result.evidence_hash != evidence_fingerprint(actions, availability)):
        raise ValueError('유효한 현재 턴 분석만 저장할 수 있습니다.')
    snapshot = {
        'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
        'experimental_only': True, 'ml_training_label_verified': False,
        'profile': asdict(profile), 'state': asdict(state), 'context_hash': result.context_hash,
        'availability': {name: availability.get(name, UNKNOWN) for name in TRAININGS},
        'actions': {name: asdict(action) for name, action in actions.items() if name in TRAININGS},
        'result': asdict(result),
    }
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2).encode('utf-8')
    if len(payload) > 3_000_000:
        raise ValueError('분석 기록이 너무 큽니다.')
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='r6_', suffix='.tmp', dir=str(out.parent))
    try:
        with os.fdopen(fd, 'wb') as fp:
            fp.write(payload)
        os.replace(temp, out)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return out
