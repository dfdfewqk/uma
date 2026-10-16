"""R40 compact turn journal: unreviewed observations never become ML labels.

Stores structured facts only, not screenshot bytes. The program never removes
user images or existing legacy records.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from pathlib import Path
import json,os,tempfile

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
    if path.is_symlink():
        raise ValueError('심볼릭 링크로 연결된 기록은 수정하지 않습니다.')
    if path.exists() and path.stat().st_size>MAX_BYTES:
        raise ValueError('턴 기록 용량 상한에 도달했습니다. 내보내기 후 교체하세요.')
    data={'schema':SCHEMA,'created_at':datetime.now(timezone.utc).isoformat(),
          'training_ready':False,'review_candidate':record.fit_for_review,
          'record':asdict(record)}
    row=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    if len(row.encode('utf-8'))>65536:
        raise ValueError('한 턴 기록 크기 초과')
    if path.exists() and path.stat().st_size + len(row.encode('utf-8')) > MAX_BYTES:
        raise ValueError('추가 기록으로 용량 제한을 넘습니다.')
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


def append_turn_batch_atomic(path, records):
    """Rewrite a bounded local JSONL journal atomically after reviewing all rows.

    Legacy append_turn behavior is not replaced. This helper is for grouped
    additions where partial-turn writes after a later error are unacceptable.
    It never deletes, truncates or resets an existing user journal on failure.
    Concurrent writers still require an external file lock, so callers must
    serialize access to the chosen output path.
    """
    if not isinstance(records, (tuple, list)) or len(records) > 500:
        raise ValueError('일괄 기록 수량 오류')
    if not records:
        return []
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('안전하지 않은 턴 기록 파일 경로')
    prepared = []
    for record in records:
        if not isinstance(record, TurnObservation):
            raise ValueError('턴 기록 자료 형식 오류')
        record.validate()
        data = {
            'schema':SCHEMA,
            'created_at':datetime.now(timezone.utc).isoformat(),
            'training_ready':False,
            'review_candidate':record.fit_for_review,
            'record':asdict(record)}
        row = (json.dumps(data,ensure_ascii=False,separators=(',',':'),
                          allow_nan=False)+'\n').encode('utf-8')
        if len(row)>65536:
            raise ValueError('한 턴 기록 크기 초과')
        prepared.append((data,row))
    old_size = path.stat().st_size if path.exists() else 0
    new_size = sum(len(row) for _,row in prepared)
    if old_size + new_size > MAX_BYTES:
        raise ValueError('기존 기록 보존 시 저장 제한 초과')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix='.uma_journal_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            if path.exists():
                with path.open('rb') as original:
                    while True:
                        block = original.read(1024*1024)
                        if not block:
                            break
                        out.write(block)
            for _,row in prepared:
                out.write(row)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return [entry for entry,_ in prepared]
