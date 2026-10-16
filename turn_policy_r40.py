"""R40 guarded, per-turn utility prototype; NOT a trained or proven optimal policy."""
from __future__ import annotations
from dataclasses import dataclass,field
from decision_contract_r39 import SkillCondition,skill_fit,next_turn_buff_useful

VALID_KINDS=('training','rest','outing','race','island','facility','event')
STATS=('스피드','스태미나','파워','근성','지능')

@dataclass(frozen=True)
class TurnOption:
    name:str
    kind:str
    stat_gains:dict[str,int]=field(default_factory=dict)
    skill_pt:int=0
    energy_delta:int=0
    bond_points:int=0
    friendship_members:int=0
    failure_pct:float=0
    next_turn_training_bonus:float=0
    verified:bool=False

    def validate(self):
        if self.kind not in VALID_KINDS or not isinstance(self.name,str) or not self.name:
            raise ValueError('행동 타입/이름 오류')
        if not isinstance(self.stat_gains,dict):
            raise ValueError('스탯 상승량 형식 오류')
        if any(k not in STATS or type(v) is not int or v<0 or v>1000
               for k,v in self.stat_gains.items()):
            raise ValueError('스탯 변화 범위 오류')
        for k,v in (('skill_pt',self.skill_pt),('energy_delta',self.energy_delta),
                    ('bond_points',self.bond_points),('friendship_members',self.friendship_members)):
            if type(v) is not int or not -200<=v<=3000:
                raise ValueError(k+' 범위 오류')
        if (type(self.failure_pct) not in (int,float)
                or type(self.next_turn_training_bonus) not in (int,float)
                or not (0<=self.failure_pct<=100 and 0<=self.next_turn_training_bonus<=1000)):
            raise ValueError('실패율/버프 범위 오류')
        return self

@dataclass(frozen=True)
class TurnEvidence:
    stats:dict[str,int]
    targets:dict[str,int]
    energy:int
    next_turn_mandatory_race:bool|None
    all_actions_visible:bool
    verified:bool
    source:str='unverified'

    def validate(self):
        if (not isinstance(self.stats,dict) or not isinstance(self.targets,dict)
                or not set(STATS).issubset(self.stats) or not set(STATS).issubset(self.targets)
                or any(type(self.stats[x]) is not int or not 0<=self.stats[x]<=5000
                       or type(self.targets[x]) is not int or not 0<=self.targets[x]<=5000 for x in STATS)
                or type(self.energy) is not int or not 0<=self.energy<=100):
            raise ValueError('턴/목표 스탯 또는 체력 오류')
        if (self.next_turn_mandatory_race is not None
                and type(self.next_turn_mandatory_race) is not bool):
            raise ValueError('다음 턴 일정 오류')
        if type(self.verified) is not bool or type(self.all_actions_visible) is not bool:
            raise ValueError('관측값 검증 상태는 불리언이어야 합니다.')
        return self

@dataclass(frozen=True)
class Suggestion:
    action:str|None
    reason:str
    scores:tuple[tuple[str,float],...]=()
    verified_optimal:bool=False

def score_option(ctx:TurnEvidence,opt:TurnOption):
    """Transparent comparison heuristic; weights are hypotheses, not measured win rates."""
    ctx.validate();opt.validate()
    # Near-saturated target stats reduce the value of more raw gains.
    stats_value=sum(min(gain,max(0,ctx.targets[stat]-ctx.stats[stat]))*0.45
                    for stat,gain in opt.stat_gains.items())
    complete=sum(ctx.stats[k]>=ctx.targets[k]*0.95 for k in STATS)
    skill_weight=1.1 if complete<3 else 1.8
    skill_value=opt.skill_pt*skill_weight
    bond_value=max(0,opt.bond_points)*0.6 + opt.friendship_members*4
    energy_value=opt.energy_delta*0.24
    failure_cost=opt.failure_pct*1.5
    buff_works=next_turn_buff_useful(ctx.next_turn_mandatory_race)
    future=opt.next_turn_training_bonus*0.15 if buff_works is True else 0
    return round(stats_value+skill_value+bond_value+energy_value+future-failure_cost,3)

def suggest_turn(ctx:TurnEvidence,options:list[TurnOption])->Suggestion:
    ctx.validate()
    if not ctx.verified or ctx.source not in ('reviewed_game_screenshot','reviewed_game_video'):
        return Suggestion(None,'실제 게임에서 검수한 턴 상태가 아닙니다.')
    if not ctx.all_actions_visible or len(options)<2:
        return Suggestion(None,'훈련·레이스·외출 등 가능한 행동을 모두 확인하지 못했습니다.')
    if any(not o.verified for o in options):
        return Suggestion(None,'미검증 행동 보상이 있어 1순위를 확정할 수 없습니다.')
    names=[o.name for o in options]
    if len(names)!=len(set(names)):
        return Suggestion(None,'같은 이름의 선택지가 중복됐습니다.')
    rank=tuple(sorted(((o.name,score_option(ctx,o)) for o in options),
                      key=lambda x:(-x[1],x[0])))
    if rank[0][1]-rank[1][1]<3:
        return Suggestion(None,'상위 행동 효율이 비슷합니다. 추가 화면 확인이 필요합니다.',rank)
    winner=next(o for o in options if o.name==rank[0][0])
    explanation=(f'{winner.name}: 스킬 Pt {winner.skill_pt}, '
                 f'우정 인원 {winner.friendship_members}, 체력 변화 {winner.energy_delta}. '
                 '현재 목표 스탯과 다음 턴 일정을 반영한 연구용 추정치입니다.')
    return Suggestion(winner.name,explanation,rank,False)

@dataclass(frozen=True)
class EventOption:
    label:str
    event_id:str
    reward_verified:bool
    continues_chain:bool|None
    gold_skill_path:str|None
    effect_score:float=0
    awards_gold_now:bool=False

def choose_event(options:list[EventOption],desired_gold_skill:str|None):
    """Known gold skill chain preferred; a terminal branch cannot be silently chosen."""
    if len(options)<2 or any(not x.reward_verified or x.continues_chain is None for x in options):
        return None,'이벤트 분기/보상 정보 부족'
    if len({x.event_id for x in options})!=1 or len({x.label for x in options})!=len(options):
        return None,'이벤트 ID나 선택지 불일치'
    safe=[x for x in options if desired_gold_skill is None
          or (x.gold_skill_path==desired_gold_skill and (x.continues_chain or x.awards_gold_now))]
    if not safe:
        return None,'목표 금색 스킬의 검증된 연속 경로가 없습니다.'
    best=max(safe,key=lambda x:x.effect_score)
    return best.label,'검증된 이벤트 연속 진행/획득 경로를 우선합니다.'

def retry_skill_options(skills:list[tuple[SkillCondition,int]],*,style,distance,
                        surface,consecutive_losses,remaining_retries):
    """Only 1-2 verified, active skills for the exact current race; no speculative buys."""
    if type(consecutive_losses) is not int or type(remaining_retries) is not int:
        raise ValueError('연속 패배/재도전 횟수 오류')
    if consecutive_losses<2 or remaining_retries<=0:return ()
    eligible=[]
    for skill,score in skills:
        if type(score) is not int or score<0:continue
        if skill_fit(skill,style=style,distance=distance,surface=surface)[0]=='eligible':
            eligible.append((score,skill.name))
    eligible.sort(key=lambda x:(-x[0],x[1]))
    return tuple(name for _,name in eligible[:2])
