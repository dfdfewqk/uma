"""R38: screen-derived race-calendar and Tucker outing readiness, no typed turns.

This is a read-only observation/planning module, not an autonomous decision
engine and not a validated Korean-client OCR model.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / 'research' / 'r38_tucker_outings_jp.json'
YEARS = ('주니어', '클래식', '시니어')
HALVES = ('전반', '후반')
CHARACTER_SCOPES = ('character_screen_review', 'character_goal_curated')


@dataclass(frozen=True)
class RaceGoal:
    year: str
    month: int
    half: str
    name: str
    kind: str = 'race'

    def position(self) -> int:
        if self.year not in YEARS or self.half not in HALVES or type(self.month) is not int or not 1 <= self.month <= 12:
            raise ValueError('목표 레이스의 연도/월/전후반이 올바르지 않습니다.')
        if self.year == '주니어' and self.month < 7:
            raise ValueError('주니어 첫 육성 턴보다 이전입니다.')
        if self.kind not in ('race', 'fans', 'other'):
            raise ValueError('알 수 없는 목표 유형입니다.')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError('목표 레이스 이름이 없습니다.')
        index = (YEARS.index(self.year) * 24 + (self.month - 1) * 2 + HALVES.index(self.half))
        return index - 12  # Junior Jul early=0; Classic Jan early=12; Senior Jan early=36.


@dataclass(frozen=True)
class CharacterCalendar:
    character_id: str
    variant_id: str
    server: str
    patch_version: str
    scenario: str
    source: str
    goals: tuple[RaceGoal, ...]
    complete: bool = False

    def validate(self):
        if (not all(isinstance(x, str) and x for x in (self.character_id, self.variant_id,
                self.patch_version)) or self.server not in ('KR','JP')
                or self.scenario != 'island_post_patch_v1'
                or self.source not in CHARACTER_SCOPES or type(self.complete) is not bool):
            raise ValueError('캐릭터 목표 레이스 자료의 서버/버전/출처가 잘못되었습니다.')
        if not isinstance(self.goals, tuple):
            raise ValueError('목표 목록은 순서가 있는 튜플이어야 합니다.')
        positions=[goal.position() for goal in self.goals]
        if len(positions) != len(set(positions)):
            raise ValueError('동일 턴에 두 목표가 중복됩니다.')
        if self.complete and not self.goals:
            raise ValueError('완전한 달력으로 표시할 레이스 자료가 없습니다.')
        return self


@dataclass(frozen=True)
class ScreenTurn:
    character_id: str | None
    variant_id: str | None
    server: str
    patch_version: str
    scenario: str
    year: str | None
    month: int | None
    half: str | None
    energy: int | None = None
    energy_cap: int | None = None
    tucker_outing_stage: int | None = None   # NEXT stage, 1..5; unknown None
    tucker_4lb_confirmed: bool = False
    tucker_outing_unlocked: bool | None = None
    goal_screen_verified: bool = False
    outing_screen_verified: bool = False

    def validate(self):
        if self.server not in ('KR','JP') or self.scenario != 'island_post_patch_v1' or not self.patch_version:
            raise ValueError('서버/시나리오/패치 출처를 확인할 수 없습니다.')
        if self.year is not None or self.month is not None or self.half is not None:
            RaceGoal(self.year, self.month, self.half, 'current', 'other').position()
        for label, value in (('체력', self.energy),('체력 상한',self.energy_cap)):
            if value is not None and (type(value) is not int or not 0 <= value <= 150):
                raise ValueError(label+'은 확인된 정수여야 합니다.')
        if self.energy_cap is not None and self.energy is not None and self.energy > self.energy_cap:
            raise ValueError('현재 체력이 화면의 상한보다 큽니다.')
        if self.tucker_outing_stage is not None and (type(self.tucker_outing_stage) is not int
                or not 1 <= self.tucker_outing_stage <= 5):
            raise ValueError('친구 외출 단계가 올바르지 않습니다.')
        for flag in ('tucker_4lb_confirmed','goal_screen_verified','outing_screen_verified'):
            if type(getattr(self,flag)) is not bool:raise ValueError('화면 확인 상태 오류: '+flag)
        if self.tucker_outing_unlocked is not None and type(self.tucker_outing_unlocked) is not bool:
            raise ValueError('친구 외출 해금 상태 오류')
        return self


@dataclass(frozen=True)
class TurnAdvisory:
    heading: str
    messages: tuple[str, ...]
    immediate_action: str | None = None
    optimal_action_verified: bool = False
    requires_typed_input: bool = False
    source_reference_only: bool = True


def load_tucker(path: Path = DATA_PATH) -> dict:
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if (data.get('schema')!='uma_r38_jp_tucker_outing_reference_v1'
            or data.get('server')!='JP' or data.get('patch_after')!='2025-06-30'
            or data.get('kr_verified') is not False
            or data.get('auto_applied_score_weights') is not False
            or data.get('usable_as_ml_ground_truth') is not False):
        raise ValueError('터커 외출 자료의 검증 범위를 확인할 수 없습니다.')
    if set(data.get('effects',{})) != {'1','2','3','4','5'}:
        raise ValueError('터커 외출 단계가 누락되었습니다.')
    for stage, entries in data['effects'].items():
        if not entries or any(type(e.get('energy_recovery')) is not int
                or not 0 <= e['energy_recovery'] <= 150 for e in entries):
            raise ValueError('터커 외출 회복량 형식 오류')
    return data


def next_goal(current: RaceGoal, calendar: CharacterCalendar | None) -> tuple[RaceGoal | None, int | None]:
    if calendar is None: return None, None
    calendar.validate()
    now=current.position()
    upcoming=sorted((goal for goal in calendar.goals if goal.position() >= now),
                    key=lambda x:x.position())
    if not upcoming: return None, None
    return upcoming[0], upcoming[0].position()-now


def assess_turn(observed: ScreenTurn, calendar: CharacterCalendar | None = None,
                *, tucker_data: dict | None = None) -> TurnAdvisory:
    """Only actions witnessed in a verified target-race UI may be definitive.

    Card reference is read-only JP 4LB data, never a promise of KR energy gain.
    """
    observed.validate()
    messages=[]
    goal = None
    delta = None
    if (calendar is not None and observed.character_id is not None
            and observed.variant_id is not None
            and calendar.character_id == observed.character_id
            and calendar.variant_id == observed.variant_id
            and calendar.server == observed.server
            and calendar.patch_version == observed.patch_version
            and calendar.scenario == observed.scenario):
        if (observed.year is not None and observed.goal_screen_verified):
            goal,delta=next_goal(RaceGoal(observed.year, observed.month, observed.half,
                                          'current', 'other'),calendar)
            if delta is not None:
                if delta == 0:
                    messages.append('현재 턴 목표: '+goal.name+' ('+goal.kind+')')
                elif delta == 1:
                    messages.append('다음 턴 목표: '+goal.name+' · 다음 턴 효과 소비와 충돌 가능')
                else:
                    messages.append(f'{delta}턴 후 확인한 목표: '+goal.name)
            if not calendar.complete:
                messages.append('캐릭터의 목표 레이스 목록은 아직 일부만 확인됐습니다.')
        else:
            messages.append('현재 연도·월·턴을 게임 화면에서 확실하게 확인하지 못했습니다.')
    else:
        messages.append('현재 캐릭터·의상·패치와 일치하는 필수 목표 레이스 달력이 아직 없습니다.')
    if calendar is not None and not calendar.complete:
        if '캐릭터의 목표 레이스 목록은 아직 일부만 확인됐습니다.' not in messages:
            messages.append('목표 레이스 달력이 완성되지 않아 이후 일정을 단정할 수 없습니다.')

    immediate = None
    if delta == 0 and goal is not None and goal.kind == 'race':
        immediate = '목표 레이스'
        messages.append('화면에서 현재 턴 필수 출전이 확인된 경우에만 이 레이스를 우선 안내합니다.')
    elif delta == 0 and goal is not None:
        messages.append('현재 목표는 레이스 출전과 다릅니다. 목표 조건을 확인하세요.')

    if observed.tucker_outing_unlocked is False:
        messages.append('터커 외출이 아직 해금되지 않아 외출 후보를 계산하지 않습니다.')
    elif (observed.outing_screen_verified and observed.tucker_outing_unlocked is True
          and observed.tucker_outing_stage is not None
          and observed.tucker_4lb_confirmed):
        data = load_tucker() if tucker_data is None else tucker_data
        if (data.get('kr_verified') is not False or data.get('server') != 'JP'
                or data.get('schema') != 'uma_r38_jp_tucker_outing_reference_v1'):
            raise ValueError('터커 일본 자료의 출처 확인이 필요합니다.')
        effects = data['effects'][str(observed.tucker_outing_stage)]
        numbers=sorted({a['energy_recovery'] for a in effects})
        messages.append(f'터커 외출 {observed.tucker_outing_stage}회차: '
                        +'일본 최대돌파 공략 참고 회복 '+('/'.join(map(str,numbers)))
                        +' · 실제 한국 화면 수치 미검증')
        if observed.energy is not None and observed.energy_cap is not None:
            usable=sorted({min(r,max(0,observed.energy_cap-observed.energy)) for r in numbers})
            messages.append('현재 체력 상한에 따른 이론상 회복 상한: '
                            +('/'.join(map(str,usable)))+' (일본 공략 수치 기준)')
        if delta in (0,1):
            messages.append('현재/다음 턴 필수 목표와 외출의 다음 턴 특기율 효과 충돌 가능')
    else:
        messages.append('터커 외출 단계·해금/돌파 상태를 화면에서 아직 확인하지 못했습니다.')
    if observed.energy is None:
        messages.append('현재 체력이 확인되지 않아 휴식과 외출의 회복 효율을 비교할 수 없습니다.')
    messages.append('일반 훈련·휴식·외출·자유 레이스 전체의 화면별 실효 수치 검증 전: 최적 행동 판정 보류')
    return TurnAdvisory(
        heading=immediate+' · 확인된 필수 일정' if immediate else '턴 일정·터커 외출 확인 중',
        messages=tuple(messages), immediate_action=immediate)
