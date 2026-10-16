"""R34: read-only island long-horizon conditions, not a score or trained model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

STATS = ('스피드', '스태미나', '파워', '근성', '지능')
TICKET_PHASES = ('미확인', '첫 1~2회', '이후')
BOND_PHASES = ('미확인', '인연 확보 중', '우정 준비됨')
SOURCE_IDS = ('R33_H01', 'R33_H02', 'R33_H03', 'R33_H05',
              'R33_H06', 'R33_H07', 'R33_H09')


@dataclass(frozen=True)
class PlanningInputs:
    ticket_phase: str = '미확인'
    bond_phase: str = '미확인'
    friendship_locations: int | None = None
    mandatory_races_remaining: int | None = None
    turns_to_next_mandatory_race: int | None = None
    planned_outings_remaining: int | None = None
    growth_rates: Mapping[str, int] | None = None
    facility_levels_confirmed: bool = False


@dataclass
class PlanningAudit:
    status: str
    checks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    stat_gaps: dict[str, int] = field(default_factory=dict)
    free_turn_upper_bound: int | None = None
    source_ids: tuple[str, ...] = SOURCE_IDS
    modifies_r6_scores: bool = False
    trained_model: bool = False
    optimal_action: str | None = None


def _optional_int(label: str, value: int | None, low: int, high: int) -> None:
    if value is not None and (type(value) is not int or not low <= value <= high):
        raise ValueError(f'{label}: {low}~{high} 정수 또는 미확인이 필요합니다.')


def assess_island_context(profile: object, state: object, ctx: PlanningInputs) -> PlanningAudit:
    """No action choice is emitted; unknown input is never inferred or scored."""
    if getattr(profile, 'scenario', None) != 'island_post_patch_v1':
        raise ValueError('R34는 무인도 시나리오 전용입니다.')
    if getattr(profile, 'event', None) not in ('챔피언스 미팅', '리그 오브 히어로즈'):
        raise ValueError('R34는 챔미·리오히 목적만 지원합니다.')
    remaining = getattr(state, 'remaining_turns', None)
    _optional_int('남은 턴', remaining, 0, 150)
    if remaining is None:
        raise ValueError('남은 턴 정보가 필요합니다.')
    if ctx.ticket_phase not in TICKET_PHASES or ctx.bond_phase not in BOND_PHASES:
        raise ValueError('티켓 또는 인연 단계 입력이 잘못되었습니다.')
    _optional_int('우정 시설 수', ctx.friendship_locations, 0, 5)
    _optional_int('남은 목표 레이스', ctx.mandatory_races_remaining, 0, remaining)
    _optional_int('다음 레이스까지 턴', ctx.turns_to_next_mandatory_race, 0, remaining)
    _optional_int('남은 외출', ctx.planned_outings_remaining, 0, remaining)
    if type(ctx.facility_levels_confirmed) is not bool:
        raise ValueError('시설 확인 여부는 참/거짓이어야 합니다.')
    rates = ctx.growth_rates
    if rates is not None:
        if not isinstance(rates, Mapping) or set(rates) != set(STATS):
            raise ValueError('성장률은 다섯 스탯을 모두 입력해야 합니다.')
        for stat, value in rates.items():
            _optional_int(stat+' 성장률', value, 0, 100)
            if value is None:
                raise ValueError('성장률 일부만 확인됨: 모두 입력하거나 전부 미확인으로 두세요.')
    for stat in STATS:
        target = getattr(profile, 'target_stats', {}).get(stat)
        current = getattr(state, 'stats', {}).get(stat)
        _optional_int(stat+' 목표', target, 0, 5000)
        _optional_int(stat+' 현재', current, 0, 5000)
        if target is None or current is None:
            raise ValueError(stat+' 현재/목표 스탯을 확인해 주세요.')
    tickets = getattr(state, 'island_tickets', None)
    delay = getattr(state, 'turns_until_next_ticket', None)
    points = getattr(state, 'development_points', None)
    _optional_int('섬 티켓', tickets, 0, 99)
    _optional_int('다음 티켓까지', delay, -1, 150)
    _optional_int('발전 Pt', points, 0, 30000)
    if tickets is None or delay is None or points is None:
        raise ValueError('섬 티켓/수령 시점/발전 Pt 확인이 필요합니다.')

    out = PlanningAudit(status='조건 확인 중')
    out.stat_gaps = {s: max(0, profile.target_stats[s]-state.stats[s]) for s in STATS}
    gaps = [f'{s} {n}' for s, n in sorted(out.stat_gaps.items(), key=lambda x:-x[1]) if n > 0]
    out.checks.append('사용자 목표 대비 부족: '+(', '.join(gaps) if gaps else '없음'))
    out.cautions.append('목표 스탯은 사용자 입력이며 공식 능력치 상한이나 대회 권장치가 아닙니다.')
    if rates is None:
        out.missing.append('캐릭터 성장률 5종')
    else:
        out.checks.append('확인한 성장률: '+', '.join(f'{s} +{rates[s]}%' for s in STATS)+' (미래 증가량을 예측하지 않음)')

    if not ctx.facility_levels_confirmed:
        out.missing.append('현재 시설 단계 사용자 확인')
    else:
        levels = getattr(state, 'building_levels', None)
        keys = (*STATS, '해변의 집')
        if not isinstance(levels, Mapping) or not all(type(levels.get(k)) is int and 0 <= levels[k] <= (3 if k == '해변의 집' else 5) for k in keys):
            raise ValueError('확인한 시설 레벨 여섯 개를 점검하세요.')
        out.checks.append('확인한 시설: '+', '.join(f'{k} Lv{levels[k]}' for k in keys))
        out.cautions.append('시설·발전 Pt만으로 최적 건설 순서는 알 수 없습니다. 강화 비용·경로·시점 확인 필요. [R33_H03]')

    if ctx.ticket_phase == '미확인':
        out.missing.append('이번 육성의 티켓 사용 단계')
    if ctx.bond_phase == '미확인':
        out.missing.append('인연 확보 상태')
    if tickets == 0:
        out.checks.append('섬 티켓 0개: 현재 섬 훈련 행동은 제외.')
    elif ctx.ticket_phase == '첫 1~2회':
        out.checks.append('초기 티켓: 인연 확보용 조기 사용과 일반 훈련의 인연 상승을 비교. 우정 3곳 미만을 일률적으로 배제하지 않습니다. [R33_H01]')
        if ctx.bond_phase == '우정 준비됨':
            out.cautions.append('초기 티켓에서 이미 우정 준비됨: 인연용 조기 사용 가설 재검토.')
    elif ctx.ticket_phase == '이후':
        if ctx.friendship_locations is None:
            out.missing.append('실제 우정 발생 시설 수')
        elif ctx.friendship_locations >= 3:
            out.checks.append('이후 티켓·우정 3곳 이상: 섬 훈련 비교 후보. 실제 상승량·티켓 만료 확인 필요. [R33_H02]')
        else:
            out.checks.append('이후 티켓·우정 3곳 미만: 일반 행동과 비교. 만료·중복 시 3곳 대기가 불리할 수 있음. [R33_H02]')
    if tickets > 0 and delay == -1:
        out.missing.append('다음 섬 티켓 수령 시점')
    if tickets > 0 and delay in (0,1):
        out.cautions.append('새 티켓 수령 임박: 실제 보유 한도·중복 소멸 규칙 확인 후 비교. [R33_H02]')

    if ctx.mandatory_races_remaining is None:
        out.missing.append('남은 필수 목표 레이스 수')
    else:
        out.free_turn_upper_bound = remaining-ctx.mandatory_races_remaining
        out.checks.append(f'남은 자유 턴 상한 {out.free_turn_upper_bound}턴 (필수 레이스 외 강제 일정 미반영).')
    if ctx.turns_to_next_mandatory_race is None:
        out.missing.append('다음 목표 레이스까지 턴')
    elif ctx.turns_to_next_mandatory_race == 0:
        out.cautions.append('이번 턴 목표 레이스 여부를 먼저 확인: 섬 훈련/외출 선택 가능성이 제한될 수 있음. [R33_H06]')
    elif ctx.turns_to_next_mandatory_race == 1 and tickets > 0:
        out.cautions.append('다음 턴 필수 레이스: 섬 훈련의 다음 턴 효과와 충돌 여부 확인. [R33_H06]')
    if ctx.planned_outings_remaining is None:
        out.missing.append('남은 계획 외출 횟수')
    elif out.free_turn_upper_bound is not None:
        need = ctx.planned_outings_remaining+tickets
        if need > out.free_turn_upper_bound:
            out.cautions.append(f'보유 티켓 {tickets}장 + 외출 {ctx.planned_outings_remaining}회가 남은 자유 턴 상한 {out.free_turn_upper_bound}보다 많아 일정 충돌 가능. [R33_H09]')
        else:
            out.checks.append('계획 티켓/외출 횟수는 자유 턴 상한 안에 있으나 실제 일정 충돌은 여전히 미확인. [R33_H09]')
    if getattr(state, 'core_skill_status', '미확인') != '확보':
        out.cautions.append('챔미·리오히 실전은 핵심 스킬 이벤트·구매 가능 스킬을 별도 확인해야 함. [R33_H07]')
    out.cautions.append('R33 일본 공략 가설 기반 점검: 한국 서버의 최적 행동·승률 또는 학습된 추천이 아닙니다.')
    out.status = '조건 일부 확인 · 판단 보류' if out.missing else '조건 확인 · 행동 검토 가능 (최적 미확정)'
    return out
