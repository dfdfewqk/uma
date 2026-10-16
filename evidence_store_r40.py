"""R40 compact turn journal: unreviewed observations never become ML labels.

Stores structured facts only, not screenshot bytes. The program never removes
user images or existing legacy records.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from pathlib import Path
import json,os

SCHEMA='uma_r40_observation_v1'
ORIGINS=('screen_candidate','reviewed_game_screenshot','reviewed_game_video','synthetic_test')
MAX_BYTES=40*1024*1024

@dataclass(frozen=True)
class TurnObservation:
    run_id:str
    turn_id:str
    scenario:str
    patch:str
    origin:str
    screen_verified:bool
    chosen_action:str|None
    outcome_verified:bool
    before:dict=field(default_factory=dict)
    after:dict=field(default_factory=dict)
    evidence_note:str=''
    event_id:str=''

    def validate(self):
        for s in (self.run_id,self.turn_id,self.scenario,self.patch,self.origin):
            if not isinstance(s,str) or not 1<=len(s)<=128:
                raise ValueError('턴 증거 필수 값 오류')
        if self.origin not in ORIGINS:
            raise ValueError('미확인 증거 출처')
        if type(self.screen_verified) is not bool or type(self.outcome_verified) is not bool:
            raise ValueError('화면/결과 검증 값 오류')
        if self.chosen_action is not None and (not isinstance(self.chosen_action,str)
                                             or len(self.chosen_action)>120):
            raise ValueError('행동 이름 오류')
        if not isinstance(self.before,dict) or not isinstance(self.after,dict):
            raise ValueError('턴 구조화 데이터 오류')
        return self

    @property
    def fit_for_review(self):
        self.validate()
        return (self.origin in ('reviewed_game_screenshot','reviewed_game_video')
                and self.screen_verified and self.outcome_verified
                and self.chosen_action is not None)

def append_turn(path,record:TurnObservation):
    """Append a single real observation; no synthetic example is a training label."""
    record.validate()
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size>MAX_BYTES:
        raise ValueError('턴 기록 용량 상한에 도달했습니다. 내보내기 후 교체하세요.')
    data={'schema':SCHEMA,'created_at':datetime.now(timezone.utc).isoformat(),
          'training_ready':False,'review_candidate':record.fit_for_review,
          'record':asdict(record)}
    row=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    if len(row.encode('utf-8'))>65536:
        raise ValueError('한 턴 기록 크기 초과')
    with path.open('a',encoding='utf-8',newline='\n') as f:
        f.write(row)
        f.flush();os.fsync(f.fileno())
    return data

def read_turns(path):
    path=Path(path)
    if not path.exists():return []
    if path.stat().st_size>MAX_BYTES:raise ValueError('턴 기록 용량 초과')
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row.get('schema')!=SCHEMA:raise ValueError('턴 기록 스키마 오류')
        rows.append(row)
    return rows
