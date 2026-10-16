"""Combined four-event island target list; KR course provenance never silently JP."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path

SCENARIO='island_post_patch_v1'
KINDS=('챔피언스 미팅','리그 오브 히어로즈')
STYLES=('도주','선행','선입','추입')
ROUNDS=('1회차','2회차','3회차','4회차')
ROUND_KINDS={1:KINDS[0],2:KINDS[1],3:KINDS[0],4:KINDS[0]}
ROUND_JP_IDS={
    1:'jp-2025-07-cm',2:'jp-2025-08-loh',
    3:'jp-2025-09-cm',4:'jp-2025-10-cm'}
SCHEMA='uma_r39_target_v1'
COURSE_SCHEMA='uma_r39_kr_course_v1'
COURSE_FILE=Path(__file__).resolve().parent/'research'/'kr_island_courses_r39.json'

def kind_for_round(round_number):
    if type(round_number) is not int or round_number not in ROUND_KINDS:
        raise ValueError('이 시나리오에는 통합 1~4회차만 등록돼 있습니다.')
    return ROUND_KINDS[round_number]

def round_label(round_number):
    kind=kind_for_round(round_number)
    return f'{round_number}회차 · '+('챔미' if kind==KINDS[0] else '리오히')

@dataclass(frozen=True)
class Target:
    kind:str
    round:int
    style:str
    scenario:str=SCENARIO

    def validate(self):
        if self.scenario!=SCENARIO or self.style not in STYLES:
            raise ValueError('시나리오·각질 오류')
        if self.kind!=kind_for_round(self.round):
            raise ValueError('대회 종류와 통합 회차가 일치하지 않습니다. 다시 선택하세요.')
        return self

    @property
    def key(self):
        self.validate()
        return ('cm' if self.kind==KINDS[0] else 'loh')+'-'+str(self.round)

    @property
    def label(self):
        self.validate()
        return f'{self.round}회차 {self.kind} · {self.style}'

def read_target(path):
    path=Path(path)
    if not path.exists():return None
    if path.stat().st_size>4096:raise ValueError('설정 크기 초과')
    obj=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj,dict) or obj.get('schema')!=SCHEMA:raise ValueError('설정 형식 오류')
    return Target(obj['kind'],obj['round'],obj['style'],obj['scenario']).validate()

def save_target(path,target):
    target.validate()
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.uma_target_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump({'schema':SCHEMA,'kind':target.kind,'round':target.round,
                       'style':target.style,'scenario':target.scenario},f,ensure_ascii=False)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def load_courses(path=COURSE_FILE):
    """Load only KR-grounded entries; unconfirmed rounds remain absent."""
    path=Path(path)
    if not path.exists():return {}
    if path.stat().st_size>65536:raise ValueError('대회 자료 크기 초과')
    obj=json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(obj,dict) or obj.get('schema')!=COURSE_SCHEMA
            or obj.get('server')!='KR' or obj.get('scenario')!=SCENARIO):
        raise ValueError('한국 서버 대회 자료가 아닙니다.')
    courses={}
    for c in obj.get('courses',[]):
        if c.get('verified_for_kr') is not True:continue
        key=c['key']
        allowed={('cm' if kind==KINDS[0] else 'loh')+'-'+str(n)
                 for n,kind in ROUND_KINDS.items()}
        if key not in allowed or key in courses:
            raise ValueError('중복/잘못된 통합 회차')
        if (c.get('distance') not in ('단거리','마일','중거리','장거리')
                or c.get('surface') not in ('잔디','더트')
                or type(c.get('meters')) is not int or not 1000<=c['meters']<=4000
                or not isinstance(c.get('venue'),str) or not c['venue'].strip()
                or not isinstance(c.get('source'),str) or not c['source'].strip()
                or c.get('evidence_level') not in ('secondary_two_sources','official')):
            raise ValueError('검증 자료 필수 필드 누락')
        courses[key]=c
    return courses

def course_for(target,courses):
    if target is None:return None
    return courses.get(target.validate().key)
