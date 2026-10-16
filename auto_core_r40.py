"""R40 offline automation orchestration core.

Never sends game input. Real client observation/actuation needs separately
verified adapters, and a verified observation before any future action.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import json, os, tempfile
from pathlib import Path
from target_selector_r39 import Target

OUTCOMES=('good','ordinary','disposed','failed')
PHASES=('setup','need_tp','in_run','waiting_tp','awaiting_verification','finished')
ACTIONS=('start_run','use_tp_item','wait_tp','wait_verification','stop')
SCHEMA='uma_r40_auto_progress_v1'

@dataclass(frozen=True)
class AutomationConfig:
    target:Target
    repetitions:int
    character_id:str
    deck_id:str
    inheritance_id:str
    game_patch:str='KR-unverified'

    def validate(self):
        self.target.validate()
        if type(self.repetitions) is not int or not 1<=self.repetitions<=10000:
            raise ValueError('육성 횟수 오류')
        if any(not isinstance(s,str) or not s.strip() or len(s)>120
               for s in (self.character_id,self.deck_id,self.inheritance_id,self.game_patch)):
            raise ValueError('캐릭터·덱·계승/패치 ID는 검증된 문자열이어야 합니다.')
        return self

@dataclass(frozen=True)
class TPView:
    tp:int|None
    cost:int|None
    item_count:int|None
    item_recovery:int|None
    verified:bool=False
    tp_cap:int|None=None

    def validate(self):
        for n in (self.tp,self.cost,self.item_count,self.item_recovery,self.tp_cap):
            if n is not None and (type(n) is not int or not 0<=n<=100000):
                raise ValueError('TP 화면 값 오류')
        if self.tp_cap is not None and self.tp is not None and self.tp>self.tp_cap:
            raise ValueError('현재 TP가 최대 TP보다 높습니다.')
        return self

@dataclass(frozen=True)
class Request:
    action:str
    reason:str
    game_input_allowed:bool=False  # R40: no input backend exists

def advise_tp(view:TPView)->Request:
    view.validate()
    if not view.verified or view.tp is None or view.cost is None or view.cost==0:
        return Request('wait_verification','현재 TP와 필요 TP를 실게임에서 검증해야 합니다.')
    if view.tp>=view.cost:
        return Request('start_run','TP가 충분하므로 다음 육성 시작 가능')
    if view.item_count is None or view.item_recovery is None:
        return Request('wait_verification','무료 TP 회복 아이템 보유량·회복량 확인이 필요합니다.')
    if view.item_count<1 or view.item_recovery<=0:
        return Request('wait_tp','무료 TP 회복 아이템이 없어 자연 회복 대기')
    if view.tp_cap is not None and min(view.item_recovery,view.tp_cap-view.tp)<=0:
        return Request('wait_verification','TP 상한/아이템 회복값이 충돌합니다.')
    return Request('use_tp_item','검수된 무료 TP 아이템 사용 후보 · 상한 초과 회복량을 확인하세요. 유료 재화 사용 금지')

@dataclass
class AutomationProgress:
    config:AutomationConfig
    phase:str='setup'
    completed_ids:list[str]=field(default_factory=list)
    outcomes:dict[str,str]=field(default_factory=dict)
    pending_run_id:str|None=None

    def validate(self):
        self.config.validate()
        if self.phase not in PHASES or len(self.completed_ids)>self.config.repetitions:
            raise ValueError('자동 육성 단계/횟수 오류')
        if len(self.completed_ids)!=len(set(self.completed_ids)):
            raise ValueError('중복 육성 ID')
        if set(self.completed_ids)!=set(self.outcomes):
            raise ValueError('육성 ID와 결과 목록 불일치')
        if any(v not in OUTCOMES for v in self.outcomes.values()):
            raise ValueError('육성 결과 오류')
        if self.pending_run_id in self.completed_ids:
            raise ValueError('완료된 육성 ID 재사용')
        if self.phase=='in_run' and not self.pending_run_id:
            raise ValueError('진행 중 육성 ID가 없습니다.')
        if self.phase!='in_run' and self.pending_run_id is not None:
            raise ValueError('진행 중이 아닌데 육성 ID가 남아 있습니다.')
        if self.pending_run_id is not None and (not isinstance(self.pending_run_id,str)
              or not 1<=len(self.pending_run_id)<=128):
            raise ValueError('진행 중 육성 ID 오류')
        if self.phase!='finished' and len(self.completed_ids)==self.config.repetitions:
            raise ValueError('모든 육성을 완료했지만 단계가 완료가 아닙니다.')
        if self.phase=='finished' and len(self.completed_ids)!=self.config.repetitions:
            raise ValueError('완료되지 않은 육성을 완료 처리')
        return self

    @property
    def remaining(self):
        self.validate()
        return self.config.repetitions-len(self.completed_ids)

    def arm(self):
        self.validate()
        if self.phase!='setup':raise ValueError('육성 실행 대기 상태가 아닙니다.')
        self.phase='need_tp'
        return self.validate()

    def begin(self,run_id:str,view:TPView):
        self.validate()
        if self.phase not in ('need_tp','waiting_tp') or self.remaining<=0:
            raise ValueError('다음 육성을 시작할 상태가 아닙니다.')
        if advise_tp(view).action!='start_run':
            raise ValueError('TP가 검증되지 않았거나 부족합니다.')
        if not isinstance(run_id,str) or not run_id or len(run_id)>128 or run_id in self.outcomes:
            raise ValueError('육성 식별자 오류')
        self.pending_run_id=run_id
        self.phase='in_run'
        return self.validate()

    def finish(self,run_id:str,outcome:str,verified:bool):
        self.validate()
        if (self.phase!='in_run' or run_id!=self.pending_run_id
                or outcome not in OUTCOMES or verified is not True):
            raise ValueError('실제 완료 화면 확인 전 결과를 기록하지 않습니다.')
        self.outcomes[run_id]=outcome
        self.completed_ids.append(run_id)
        self.pending_run_id=None
        self.phase='finished' if len(self.completed_ids)==self.config.repetitions else 'need_tp'
        return self.validate()

    def wait(self):
        self.validate()
        if self.phase!='need_tp':raise ValueError('TP 확인 단계가 아닙니다.')
        self.phase='waiting_tp'
        return self.validate()

    def as_json(self):
        self.validate()
        return {'schema':SCHEMA,'config':{**asdict(self.config),
                'target':asdict(self.config.target)},'phase':self.phase,
                'completed_ids':list(self.completed_ids),'outcomes':dict(self.outcomes),
                'pending_run_id':self.pending_run_id}

def restore_progress(data):
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA:
        raise ValueError('자동 육성 기록 스키마 오류')
    c=data['config']
    cfg=AutomationConfig(Target(**c['target']),c['repetitions'],c['character_id'],
                         c['deck_id'],c['inheritance_id'],c['game_patch'])
    return AutomationProgress(cfg,data['phase'],data['completed_ids'],
                              data['outcomes'],data['pending_run_id']).validate()

def save_progress(path,progress):
    payload=progress.as_json()
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.uma_r40_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(payload,f,ensure_ascii=False,indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def load_progress(path):
    path=Path(path)
    if not path.exists():return None
    if path.stat().st_size>1024*1024:raise ValueError('자동 육성 기록 크기 초과')
    return restore_progress(json.loads(path.read_text(encoding='utf-8')))

def actuate_game(*args,**kwargs):
    """Explicitly disabled until Windows client image+pointer evidence is validated."""
    raise RuntimeError('R40은 소스 단계입니다. 실게임 자동 클릭은 검증 전이므로 차단합니다.')
