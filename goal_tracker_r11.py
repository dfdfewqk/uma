"""R11: evidence-aware competition goal-gap tracker (NOT a win predictor).

Scores here are *arithmetic gap inspections*, not probability, survival estimates,
future training effects, learning labels or a 'quit' recommendation. Synthetic
test records are never treated as field observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from uma_core import EVENTS, STATS, RunProfile, TurnState
from island_planner_r7 import FACILITIES
from scenario_policies import POLICIES

SCHEMA = 'uma_r11_goal_gap_v1'
SKILL_STATUSES = ('미확인', '미확보', '힌트확보', '획득완료')


@dataclass(frozen=True)
class RequiredSkill:
    name: str
    status: str = '미확인'
    effective_cost: int | None = None  # User-reviewed, after hint discounts; NOT a game formula


@dataclass
class GoalResult:
    status: str = '분석 보류'
    context_hash: str = ''
    errors: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    stats: list[dict[str, Any]] = field(default_factory=list)
    skills: dict[str, Any] = field(default_factory=dict)
    facilities: list[dict[str, Any]] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    island_tickets: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    achieved_requirements: bool = False
    completion_probability: None = None
    verified_optimal: bool = False
    trained_model: bool = False
    experimental_only: bool = True


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _inputs(profile: RunProfile, state: TurnState, skills: Sequence[RequiredSkill],
            facility_targets: Mapping[str, int], *, skills_confirmed: bool,
            evaluation_target: int | None, turns_until_evaluation: int | None) -> dict:
    state_dict = asdict(state)
    state_dict.pop('screenshot', None)  # Image path is not a game mechanic
    return {'profile': asdict(profile), 'state': state_dict,
            'skills': [asdict(x) for x in skills],
            'facility_targets': dict(facility_targets), 'skills_confirmed': skills_confirmed,
            'evaluation_target': evaluation_target,
            'turns_until_evaluation': turns_until_evaluation}


def context_fingerprint(profile: RunProfile, state: TurnState, skills: Sequence[RequiredSkill],
                        facility_targets: Mapping[str, int], *, skills_confirmed: bool = False,
                        evaluation_target: int | None = None,
                        turns_until_evaluation: int | None = None) -> str:
    return hashlib.sha256(_json(_inputs(profile, state, skills, facility_targets,
                         skills_confirmed=skills_confirmed, evaluation_target=evaluation_target,
                         turns_until_evaluation=turns_until_evaluation)).encode('utf-8')).hexdigest()


def _valid_int(v, minimum: int, maximum: int) -> bool:
    return type(v) is int and minimum <= v <= maximum


def assess_goals(profile: RunProfile, state: TurnState, skills: Sequence[RequiredSkill] = (),
                 facility_targets: Mapping[str, int] | None = None, *,
                 skills_confirmed: bool = False, evaluation_target: int | None = None,
                 turns_until_evaluation: int | None = None,
                 observed_trend: Mapping[str, Any] | None = None) -> GoalResult:
    """Compare explicit current facts with player-specified targets. Never extrapolate a win probability.

    observed_trend must be the *current exact snapshot* report returned by
    verified_current_run_trend; arbitrary data is never accepted into an estimate.
    """
    facilities = dict(facility_targets or {})
    result = GoalResult()
    if profile.scenario not in POLICIES:
        result.errors.append('지원하지 않는 시나리오입니다.')
    if profile.event not in EVENTS:
        result.errors.append('챔미·리오히 실전 목표만 지원합니다.')
    if not _valid_int(state.remaining_turns, 0, 150):
        result.errors.append('남은 턴 수가 유효하지 않습니다.')
    for key in STATS:
        if not _valid_int(profile.target_stats.get(key), 0, 5000):
            result.errors.append(f'{key} 목표 스탯이 잘못되었습니다.')
        if not _valid_int(state.stats.get(key), 0, 5000):
            result.errors.append(f'{key} 현재 스탯이 잘못되었습니다.')
    if not _valid_int(profile.target_skill_points, 0, 20000) or not _valid_int(state.skill_points, 0, 20000):
        result.errors.append('스킬 Pt 입력 범위를 확인하세요.')
    if not _valid_int(state.island_tickets, 0, 99) or not _valid_int(state.turns_until_next_ticket, -1, 150):
        result.errors.append('섬 티켓 수량과 다음 지급 시점을 확인하세요.')
    if not _valid_int(state.development_points, 0, 30000):
        result.errors.append('발전 Pt 입력을 확인하세요.')
    if len(skills) > 100:
        result.errors.append('필수 스킬은 최대 100개입니다.')
    names = set()
    for entry in skills:
        if not isinstance(entry, RequiredSkill) or not (0 < len(entry.name.strip()) <= 100):
            result.errors.append('필수 스킬 이름이 올바르지 않습니다.')
            continue
        if entry.name.strip() in names:
            result.errors.append(f'필수 스킬 중복: {entry.name}')
        names.add(entry.name.strip())
        if entry.status not in SKILL_STATUSES:
            result.errors.append(f'{entry.name}: 스킬 상태를 확인하세요.')
        if entry.effective_cost is not None and not _valid_int(entry.effective_cost, 0, 9999):
            result.errors.append(f'{entry.name}: 유효 스킬 Pt 비용을 확인하세요.')
    for name, target in facilities.items():
        maximum = 3 if name == '해변의 집' else 5
        if name not in FACILITIES or not _valid_int(target, 0, maximum):
            result.errors.append(f'시설 목표 오류: {name}')
    for name in FACILITIES:
        maximum = 3 if name == '해변의 집' else 5
        if not _valid_int(state.building_levels.get(name), 0, maximum):
            result.errors.append(f'현재 시설 Lv 오류: {name}')
    if (evaluation_target is None) != (turns_until_evaluation is None):
        result.errors.append('평가회 발전 Pt 목표와 남은 턴은 함께 입력해야 합니다.')
    if evaluation_target is not None:
        if not _valid_int(evaluation_target, 0, 30000) or not _valid_int(turns_until_evaluation, 0, 150):
            result.errors.append('평가회 목표/기한은 음이 아닌 정수여야 합니다.')
    if type(skills_confirmed) is not bool:
        result.errors.append('필수 스킬 목록 확인 상태가 잘못되었습니다.')
    if result.errors:
        return result
    result.context_hash = context_fingerprint(
        profile, state, skills, facilities, skills_confirmed=skills_confirmed,
        evaluation_target=evaluation_target, turns_until_evaluation=turns_until_evaluation)

    remaining = state.remaining_turns
    for name in STATS:
        current = state.stats[name]
        target = profile.target_stats[name]
        gap = max(0, target - current)
        required = (round(gap / remaining, 2) if remaining > 0 else None) if gap else 0.0
        result.stats.append({'name': name, 'current': current, 'target': target,
                             'gap': gap, 'required_per_remaining_turn': required,
                             'flag': '기준 도달' if not gap else ('남은 턴 없음' if not remaining else '추격 필요')})
    unknown_skills = [s.name for s in skills if s.status == '미확인']
    to_buy = [s for s in skills if s.status in ('미확보','힌트확보')]
    unknown_costs = [s.name for s in to_buy if s.effective_cost is None]
    already = [s.name for s in skills if s.status == '획득완료']
    known_cost = sum(s.effective_cost for s in to_buy if s.effective_cost is not None)
    all_cost_known = bool(skills_confirmed) and not unknown_costs and not unknown_skills
    shortfall = max(0, known_cost - state.skill_points) if all_cost_known else None
    result.skills = {'list_confirmed': skills_confirmed, 'required_count': len(skills),
                     'acquired': already, 'missing': [s.name for s in to_buy],
                     'unknown_status': unknown_skills, 'unknown_effective_cost': unknown_costs,
                     'known_unpurchased_effective_cost': known_cost,
                     'current_skill_points': state.skill_points, 'point_shortfall_if_buy_now': shortfall,
                     'budget_complete': all_cost_known,
                     'reference_target_sp_gap': max(0, profile.target_skill_points - state.skill_points)}
    for name in FACILITIES:
        current = state.building_levels[name]
        target = facilities.get(name)
        result.facilities.append({'name': name, 'current': current, 'target': target,
                                  'levels_needed': max(0, target-current) if target is not None else None,
                                  'flag': '미설정' if target is None else ('현재 달성' if current>=target else '강화 필요')})
    if evaluation_target is None:
        result.evaluation = {'status':'평가회 조건 미확인', 'target':None,
                             'remaining_turns':None,'gap':None,'required_per_turn':None}
    else:
        gap = max(0, evaluation_target-state.development_points)
        result.evaluation = {'status':('기준 도달' if gap == 0 else '기한 도달/미달' if turns_until_evaluation == 0 else '부족분 확인'),
                             'target':evaluation_target, 'current':state.development_points,
                             'remaining_turns':turns_until_evaluation,'gap':gap,
                             'required_per_turn':round(gap / turns_until_evaluation,2) if gap and turns_until_evaluation else (0.0 if not gap else None)}
    result.island_tickets = {'held':state.island_tickets,
                             'until_next':None if state.turns_until_next_ticket == -1 else state.turns_until_next_ticket,
                             'status':('다음 지급 시점 미확인' if state.turns_until_next_ticket == -1 else
                                       '보유 티켓/지급 타이밍 확인 필요' if state.island_tickets > 0 and state.turns_until_next_ticket<=1 else '사용 시점 별도 비교 필요')}
    if observed_trend:
        # Only a report carrying exact current-state verified by a trusted caller.
        if observed_trend.get('verified_current_snapshot') is True and observed_trend.get('context_hash') == result.context_hash:
            result.evidence = {'consecutive_turn_intervals':observed_trend.get('intervals', 0),
                               'past_median_per_stat':observed_trend.get('medians',{}),
                               'interpretation':'과거 같은 육성에서 관찰한 증감의 중앙값. 미래 성장률이 아닙니다.'}
        else:
            result.cautions.append('과거 추세 근거가 현재 턴/목표와 일치하지 않아 사용하지 않았습니다.')
    if not skills_confirmed:
        result.cautions.append('필수 스킬 목록을 확인하지 않았습니다. 실전 육성 조건 충족 여부를 판단할 수 없습니다.')
    if unknown_skills or unknown_costs:
        result.cautions.append('스킬 상태·유효 Pt 비용 미확인 항목이 있어 전체 스킬 확보 비용을 확정할 수 없습니다.')
    if any(f['target'] is None for f in result.facilities):
        result.cautions.append('시설 목표가 일부 미설정입니다. 강화 경로의 달성 여부를 판단하지 않습니다.')
    if evaluation_target is None:
        result.cautions.append('다음 평가회 목표·기한 미입력: 발전 Pt는 부족량 예측에 포함하지 않습니다.')
    if state.turns_until_next_ticket == -1:
        result.cautions.append('섬 티켓 수령 시점 미확인: 티켓 소비 추천을 하지 않습니다.')
    if any(x['gap'] for x in result.stats) and remaining == 0:
        result.cautions.append('남은 턴이 없어 일부 목표 스탯은 입력 기준에 미달합니다.')
    result.achieved_requirements = (all(x['gap'] == 0 for x in result.stats)
                                     and skills_confirmed and not to_buy and not unknown_skills
                                     and all(x['target'] is not None and x['levels_needed'] == 0 for x in result.facilities)
                                     and evaluation_target is not None and result.evaluation['gap'] == 0)
    if result.achieved_requirements:
        result.status = '입력한 수치 목표 충족 (실전 성능 미검증)'
    elif not skills_confirmed or (all(f['target'] is None for f in result.facilities) and evaluation_target is None):
        result.status = '정보 부족 · 목표 격차만 확인'
    else:
        result.status = '목표 격차 점검 완료 · 성공 가능성 판단 보류'
    result.cautions.append('턴별 평균 필요량은 산술적 목표 격차일 뿐 미래 성장 예측, 승률, 도축 추천이 아닙니다.')
    return result


def verified_current_run_trend(conn, run_id: int | None, profile: RunProfile, state: TurnState,
                               skills: Sequence[RequiredSkill], facility_targets: Mapping[str,int], *,
                               skills_confirmed: bool, evaluation_target: int | None,
                               turns_until_evaluation: int | None) -> dict | None:
    """Use R3 within-run medians only when SAVED run profile+last turn exactly match current UI.

    Safety: no cross-run borrowing, no unreviewed trend, no causality. Returns None
    rather than presenting stale evidence as current.
    """
    if run_id is None:
        return None
    from storage import list_runs, list_turns
    from analytics_r3 import run_audit
    run = next((r for r in list_runs(conn) if r['id'] == run_id), None)
    if not run or run['profile'] != asdict(profile):
        return None
    turns = list_turns(conn, run_id)
    if not turns:
        return None
    saved_state = dict(turns[-1]['state'])
    saved_state.pop('screenshot', None)
    current_state = asdict(state)
    current_state.pop('screenshot', None)
    if saved_state != current_state:
        return None
    audit = run_audit(conn, run_id)
    if audit['consecutive_observed_intervals'] < 5:
        return None
    medians = {g['stat']:g['observed_median'] for g in audit['targets'] if g['observed_median'] is not None}
    if len(medians) != len(STATS):
        return None
    key = context_fingerprint(profile, state, skills, facility_targets,
                              skills_confirmed=skills_confirmed, evaluation_target=evaluation_target,
                              turns_until_evaluation=turns_until_evaluation)
    return {'verified_current_snapshot': True, 'context_hash':key,
            'intervals':audit['consecutive_observed_intervals'], 'medians':medians}


def export_goal_report(path: Path, profile: RunProfile, state: TurnState,
                       skills: Sequence[RequiredSkill], facility_targets: Mapping[str,int],
                       result: GoalResult, *, skills_confirmed: bool,
                       evaluation_target: int | None = None,
                       turns_until_evaluation: int | None = None) -> Path:
    key = context_fingerprint(profile, state, skills, facility_targets,
                              skills_confirmed=skills_confirmed, evaluation_target=evaluation_target,
                              turns_until_evaluation=turns_until_evaluation)
    if result.errors or result.status == '분석 보류' or result.context_hash != key:
        raise ValueError('유효하지 않거나 변경된 R11 결과는 저장할 수 없습니다. 다시 분석하세요.')
    obj = {'schema':SCHEMA,'created_at':datetime.now(timezone.utc).isoformat(),
           'model_status':'RULE_BASED_UNVALIDATED / ML_NOT_TRAINED',
           'experiment_only':True,'completion_probability':None,
           'profile':asdict(profile),
           'state':{k:v for k,v in asdict(state).items() if k!='screenshot'},
           'inputs':{'skills':[asdict(s) for s in skills],'skills_confirmed':skills_confirmed,
                     'facility_targets':dict(facility_targets),'evaluation_target':evaluation_target,
                     'turns_until_evaluation':turns_until_evaluation},
           'result':asdict(result)}
    output = Path(path)
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(dir=str(output.parent),prefix='uma_r11_',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)
        os.replace(tmp,output)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return output

TEMPLATE_SCHEMA = 'uma_r11_goal_template_v1'


def _template_scope(profile: RunProfile) -> dict:
    return {'scenario':profile.scenario, 'event':profile.event,
            'distance':profile.distance, 'style':profile.style,
            'target_stats':dict(profile.target_stats),
            'target_skill_points':profile.target_skill_points,
            'course':profile.course,'surface':profile.surface,
            'course_direction':profile.course_direction,
            'race_conditions':profile.race_conditions}


def save_goal_template(path: Path, profile: RunProfile, skills: Sequence[RequiredSkill],
                       facility_targets: Mapping[str, int], evaluation_target: int | None = None) -> Path:
    """Save a *goal template*, never a verified observation or ML label.

    The dynamic turns-until-evaluation and review flag are deliberately not saved.
    Loading cannot silently carry verification to a new run/turn.
    """
    check = assess_goals(profile, TurnState(), skills=skills,
                         facility_targets=facility_targets, skills_confirmed=False)
    if check.errors or (evaluation_target is not None and not _valid_int(evaluation_target,0,30000)):
        raise ValueError('목표 설정에 오류가 있어 템플릿으로 저장할 수 없습니다.')
    doc = {'schema':TEMPLATE_SCHEMA, 'scope':_template_scope(profile),
           'skills':[asdict(s) for s in skills], 'facility_targets':dict(facility_targets),
           'evaluation_target':evaluation_target,
           'note':'목표 템플릿일 뿐 게임 내 확인 또는 스킬 효과 검증을 의미하지 않습니다.'}
    output=Path(path)
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='uma_r11_template_',suffix='.tmp',dir=str(output.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(doc,f,ensure_ascii=False,indent=2,allow_nan=False)
        os.replace(temp,output)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return output


def load_goal_template(path: Path, profile: RunProfile) -> dict:
    """Reject mismatched competitions or malformed untrusted files; never auto-confirm."""
    source=Path(path)
    if source.stat().st_size > 128_000:
        raise ValueError('목표 설정 파일 크기가 지나치게 큽니다.')
    obj=json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(obj,dict) or obj.get('schema') != TEMPLATE_SCHEMA or obj.get('scope') != _template_scope(profile):
        raise ValueError('현재 대회/시나리오/경기 조건/목표 스탯과 다른 설정 파일입니다.')
    raw=obj.get('skills')
    if not isinstance(raw,list) or len(raw)>100 or not isinstance(obj.get('facility_targets'),dict):
        raise ValueError('필수 스킬/시설 설정 형식이 잘못되었습니다.')
    try:
        skills=[RequiredSkill(**x) for x in raw]
    except (TypeError,ValueError) as err:
        raise ValueError('필수 스킬 형식이 잘못되었습니다.') from err
    facilities=obj['facility_targets']
    target=obj.get('evaluation_target')
    check=assess_goals(profile,TurnState(),skills,facilities,skills_confirmed=False)
    if check.errors or (target is not None and not _valid_int(target,0,30000)):
        raise ValueError('저장된 목표 수치가 올바르지 않습니다.')
    return {'skills':skills,'facility_targets':dict(facilities),
            'evaluation_target':target, 'skills_confirmed':False,
            'turns_until_evaluation':None}
