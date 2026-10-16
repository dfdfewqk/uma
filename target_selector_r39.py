"""KR tournament selection: never substitute historical JP courses for KR."""
from __future__ import annotations
import json, os, tempfile
from dataclasses import dataclass
from pathlib import Path

SCENARIO='island_post_patch_v1'
KINDS=('챔피언스 미팅','리그 오브 히어로즈')
STYLES=('도주','선행','선입','추입')
ROUNDS=('1회차','2회차','3회차','4회차')
SCHEMA='uma_r39_target_v1'
COURSE_SCHEMA='uma_r39_kr_course_v1'
COURSE_FILE=Path(__file__).resolve().parent/'research'/'kr_island_courses_r39.json'

@dataclass(frozen=True)
class Target:
    kind:str
    round:int
    style:str
    scenario:str=SCENARIO

    def validate(self):
        if self.kind not in KINDS or self.style not in STYLES or self.scenario!=SCENARIO:
            raise ValueError('시나리오·대회·각질이 올바르지 않습니다.')
        if type(self.round) is not int or not 1<=self.round<=4:
            raise ValueError('대회 회차는 1~4만 가능합니다.')
        return self

    @property
    def key(self):
        self.validate()
        return ('cm' if self.kind==KINDS[0] else 'loh')+'-'+str(self.round)

    @property
    def label(self):
        return f'{self.kind} · {self.round}회차 · {self.style}'


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
    """KR-only entries require verified source, exact course metadata, no guessing."""
    path=Path(path)
    if not path.exists():return {}
    if path.stat().st_size>65536:raise ValueError('대회 자료 크기 초과')
    obj=json.loads(path.read_text(encoding='utf-8'))
    if (obj.get('schema')!=COURSE_SCHEMA or obj.get('server')!='KR'
            or obj.get('scenario')!=SCENARIO):
        raise ValueError('한국 서버 대회 자료가 아닙니다.')
    courses={}
    for c in obj.get('courses',[]):
        if c.get('verified_for_kr') is not True:continue
        key=c['key']
        if key not in {f'{k}-{n}' for k in ('cm','loh') for n in range(1,5)} or key in courses:
            raise ValueError('중복/잘못된 회차')
        if (c.get('distance') not in ('단거리','마일','중거리','장거리')
                or c.get('surface') not in ('잔디','더트')
                or type(c.get('meters')) is not int or not 1000<=c['meters']<=4000
                or not c.get('venue') or not c.get('source')):
            raise ValueError('검증 대회 정보 누락')
        courses[key]=c
    return courses


def course_for(target,courses):
    return courses.get(target.key) if target is not None else None
