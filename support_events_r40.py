"""R40 curated event-branch memory from game preview + actual result.

Only reviewed exact card/version/patch observations are trusted; contradictions
are quarantined instead of silently retraining a policy.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
import json,os,tempfile
from pathlib import Path

SCHEMA='uma_r40_support_event_catalog_v1'

@dataclass(frozen=True)
class EventEvidence:
    server:str
    patch:str
    card_id:str
    card_variant:str
    event_id:str
    stage:int
    choice_id:str
    effects:dict
    chain_ends:bool
    gold_skill_path:str|None
    preview_verified:bool
    result_verified:bool
    source_note:str

    def validate(self):
        strings=(self.server,self.patch,self.card_id,self.card_variant,
                 self.event_id,self.choice_id,self.source_note)
        if (self.server not in ('KR','JP') or
            any(not isinstance(x,str) or not 1<=len(x)<=200 for x in strings)):
            raise ValueError('이벤트 카드/출처 정보 오류')
        if type(self.stage) is not int or not 1<=self.stage<=20:
            raise ValueError('연속 이벤트 단계 오류')
        if type(self.chain_ends) is not bool or not isinstance(self.effects,dict):
            raise ValueError('종료 여부/효과 오류')
        if type(self.preview_verified) is not bool or type(self.result_verified) is not bool:
            raise ValueError('검증 플래그 오류')
        if self.gold_skill_path is not None and not isinstance(self.gold_skill_path,str):
            raise ValueError('금색 스킬 분기 ID 오류')
        return self

    @property
    def key(self):
        return '|'.join((self.server,self.patch,self.card_id,self.card_variant,
                         self.event_id,str(self.stage),self.choice_id))

    @property
    def reviewed(self):
        return self.validate().preview_verified and self.result_verified

def integrate_event(catalog,observation:EventEvidence):
    """Return status; never treat unknown or contradictory events as confirmed."""
    observation.validate()
    if not isinstance(catalog,dict):raise ValueError('카탈로그 구조 오류')
    if not observation.reviewed:return 'pending_review'
    item=asdict(observation)
    if observation.key in catalog:
        if catalog[observation.key]==item:return 'duplicate'
        return 'conflict'
    catalog[observation.key]=item
    return 'added'

def save_catalog(path,catalog):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    for key,item in catalog.items():
        ev=EventEvidence(**item).validate()
        if key!=ev.key or not ev.reviewed:
            raise ValueError('미검증/손상된 이벤트가 카탈로그에 있습니다.')
    fd,tmp=tempfile.mkstemp(prefix='.uma_event_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump({'schema':SCHEMA,'events':catalog},f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def load_catalog(path):
    path=Path(path)
    if not path.exists():return {}
    if path.stat().st_size>8*1024*1024:raise ValueError('이벤트 카탈로그 크기 초과')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!=SCHEMA or not isinstance(data.get('events'),dict):
        raise ValueError('이벤트 카탈로그 형식 오류')
    for key,val in data['events'].items():
        ev=EventEvidence(**val).validate()
        if not ev.reviewed or ev.key!=key:raise ValueError('검증 기록 불일치')
    return data['events']
