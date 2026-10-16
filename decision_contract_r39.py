"""Pure future decision contracts; not connected to live game or automation."""
from dataclasses import dataclass
from target_selector_r39 import STYLES

@dataclass(frozen=True)
class SkillCondition:
    name:str
    distance:str|None=None
    style:str|None=None
    surface:str|None=None
    verified:bool=False


def skill_fit(skill,*,style,distance,surface=None):
    if style not in STYLES:raise ValueError('각질 오류')
    if not skill.verified:return ('unverified','스킬 발동 조건이 미검증입니다.')
    if skill.style and skill.style!=style:return ('ineligible','현재 각질에서 발동하지 않습니다.')
    if skill.distance:
        if distance is None:return ('unverified','현재 레이스 거리가 확인되지 않았습니다.')
        if skill.distance!=distance:return ('ineligible','현재 거리에서 발동하지 않습니다.')
    if skill.surface:
        if surface is None:return ('unverified','현재 마장을 확인하지 못했습니다.')
        if skill.surface!=surface:return ('ineligible','현재 마장에서 발동하지 않습니다.')
    return ('eligible','검증된 조건은 일치합니다. 발동 시점은 별도 검토가 필요합니다.')

@dataclass(frozen=True)
class RepeatPlan:
    requested:int
    completed:int=0
    good:int=0
    disposed:int=0
    failed:int=0

    def validate(self):
        vals=(self.requested,self.completed,self.good,self.disposed,self.failed)
        if (any(type(x) is not int for x in vals) or not 1<=self.requested<=10000
                or not 0<=self.completed<=self.requested
                or any(x<0 for x in vals[2:])
                or self.good+self.disposed+self.failed>self.completed):
            raise ValueError('반복 육성 횟수/결과 오류')
        return self

    @property
    def remaining(self):
        return self.requested-self.validate().completed

    def finish(self,outcome):
        self.validate()
        if self.remaining==0 or outcome not in ('good','ordinary','disposed','failed'):
            raise ValueError('완료 횟수 초과 또는 결과 값 오류')
        return RepeatPlan(self.requested,self.completed+1,
                          self.good+(outcome=='good'),self.disposed+(outcome=='disposed'),
                          self.failed+(outcome=='failed')).validate()


def next_turn_buff_useful(next_turn_mandatory_race):
    if next_turn_mandatory_race is None:return None
    if type(next_turn_mandatory_race) is not bool:raise ValueError('필수 레이스 상태 오류')
    return not next_turn_mandatory_race
