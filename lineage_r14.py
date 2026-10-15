"""R14 provenance-gated lineage recommendations + KR forecast planning.

Recommendations are untrained, source-backed candidates, not inherited skill odds,
compatibility scores, or proof that a character exists on the KR server.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
from pathlib import Path
from datetime import date,timedelta
import json,calendar
from plan_r13 import load_pack,STYLES

DATA_PATH=Path(__file__).resolve().parent/'research'/'r14'/'lineage_and_calendar.json'


def load_r14(path=DATA_PATH, r13=None):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    r13=load_pack() if r13 is None else r13
    if data.get('schema')!='r14.v1':raise ValueError('R14 데이터 형식이 아닙니다.')
    ids={e['id'] for e in r13['events']}
    if {e['event_id'] for e in data['events']}!=ids or len(data['events'])!=len(ids):
        raise ValueError('대회 매핑 누락 또는 중복')
    for event in data['events']:
        if not event['sources'] or any(x not in data['sources'] for x in event['sources']):
            raise ValueError('미래시 근거 출처 누락')
        if event['kr_start'] is not None:
            if not event['kr_end'] or event['kr_estimate_month'] is not None:
                raise ValueError('한국 확정·예상 월 정보가 혼재함')
            if date.fromisoformat(event['kr_end'])<date.fromisoformat(event['kr_start']):
                raise ValueError('대회 종료일 오류')
        elif event['kr_end'] is not None or not event['kr_estimate_month']:
            raise ValueError('일정 미확인 대회에 날짜를 확정할 수 없음')
    for a in data['generic_grandparents']:
        if not a['source_ids'] or any(x not in data['sources'] for x in a['source_ids']):
            raise ValueError('조부모 후보 근거 누락')
    return data

# Cosmetic variants use the same base character for conflict checks.
ALIASES={
    '신의상 라인 크래프트':'라인 크래프트','신년 키타산 블랙':'키타산 블랙',
    '크리스마스 나리타 탑 로드':'나리타 탑 로드','신의상 사쿠라 바쿠신 오':'사쿠라 바쿠신 오',
    '수영복 아그네스 타키온':'아그네스 타키온','신년 티엠 오페라 오':'티엠 오페라 오',
}

def base_name(name):
    n=' '.join(str(name).strip().split())
    return ALIASES.get(n,n)


def _candidate(name,skill,priority,origin,sources):
    return dict(name=name,skill=skill,priority=priority,origin=origin,source_ids=sources,
                availability='한국 보유 및 출시 여부 확인 필요',compatibility='실제 상성 미검증')


def recommend_lineage(event_id,style,trainee='',owned_names=None,r13=None,r14=None):
    r13=load_pack() if r13 is None else r13
    r14=load_r14(r13=r13) if r14 is None else r14
    if style not in STYLES:raise ValueError('각질을 선택해야 합니다.')
    p=next((x for x in r13['profiles'] if x['event_id']==event_id and x['style']==style),None)
    if p is None:raise ValueError('해당 대회/각질의 근거 없음')
    if owned_names is not None and not isinstance(owned_names,(list,tuple,set,frozenset)):
        raise TypeError('보유 육성마 목록은 이름 목록이어야 합니다.')
    own={base_name(n) for n in owned_names} if owned_names is not None else None
    trainee_base=base_name(trainee)
    preferred=sorted(p['parents'],key=lambda x:{'핵심 후보':4,'추천 후보':3,'조건부':2}.get(x['priority'],1),reverse=True)
    taken=set();parents=[];notes=[]
    if not trainee_base:notes.append('육성 캐릭터가 미입력이라 동일 인물 중복 검사가 완전하지 않습니다.')
    if own is None:notes.append('보유 육성마 목록이 없어서 이용 가능 여부는 미확인입니다.')
    for x in preferred:
        b=base_name(x['name'])
        if b==trainee_base or b in taken:continue
        if own is not None and b not in own:continue
        parents.append(_candidate(x['name'],x['unique_skill'],x['priority'],'대회·각질별 계승 후보 (R13)',x['source_ids']))
        taken.add(b)
        if len(parents)==2:break
    # Do not pretend general-purpose substitutes have validated course-specific unique skills.
    pool=r14['generic_grandparents']
    for c in pool:
        if len(parents)==2:break
        b=base_name(c['name'])
        if b==trainee_base or b in taken or (own is not None and b not in own):continue
        parents.append(_candidate(c['name'],'계승 고유기: 별도 검증 필요','범용 대체·조건부','일반 인자작 공략 기반 대체 후보',c['source_ids']))
        taken.add(b)
    grand=[]
    for c in pool:
        b=base_name(c['name'])
        if b==trainee_base or b in taken or (own is not None and b not in own):continue
        grand.append(_candidate(c['name'],'공통 G1·적성·스킬 인자 확인','범용 후보','조부모 재활용 후보 (코스 최적화 미검증)',c['source_ids']))
        taken.add(b)
        if len(grand)==4:break
    # Do not invent extra names or fixed duplicate ancestors to fill slots.
    while len(parents)<2:parents.append(None)
    while len(grand)<4:grand.append(None)
    branches=[]
    for i in range(2):
        branches.append({'parent':parents[i], 'grandparents':grand[i*2:i*2+2]})
    if any(x is None for x in parents+grand):notes.append('보유 조건에서 후보가 부족한 자리는 미확정으로 남겼습니다.')
    notes += ['부모는 경기 조건에 유효한 계승 스킬을, 조부모는 실제 보유 인자·상성·G1 겹침을 먼저 확인하세요.',
              '동일 이름의 의상 변경은 같은 캐릭터로 보며 조부모·육성마의 중복을 기본 회피합니다.',
              '추천은 후보 배치 초안입니다. 상성 점수, 실제 보유 인자, 승률, 계승 발동 확률은 계산하지 않았습니다.']
    sources={}
    for c in parents+grand:
        if c:
            for sid in c['source_ids']:
                d=(r13.get('provenance',{}).get(sid) or r14['sources'].get(sid))
                if d:sources[sid]=d
    return {'event_id':event_id,'style':style,'trainee':trainee,'branches':branches,
            'factor_targets':{'red':'경기 거리·각질 적성 우선 검토','green':'경기장 방향·계절 등 조건 확인',
                              'white':'필수 유효 스킬 힌트 후보 확인','blue':'목표 스탯 부족량에 맞춰 검토'},
            'warnings':notes,'sources':sources,'kind':'근거 기반 후보 자동 배치 (학습 모델 아님)'}


def event_calendar(event_id,as_of=None,r13=None,r14=None):
    r13=load_pack() if r13 is None else r13
    r14=load_r14(r13=r13) if r14 is None else r14
    meta=next((x for x in r14['events'] if x['event_id']==event_id),None)
    if meta is None:raise ValueError('대회 정보가 없음')
    race=next(x for x in r13['events'] if x['id']==event_id)
    result={'event_id':event_id,'event_label':race['label'],'kind':race['kind'],
            'course':f"{race['venue']} · {race['surface']} {race['meters']}m · {race['direction']}",
            'jp_period':f"{meta['jp_start']} ~ {meta['jp_end']}",
            'kr_status':meta['status'],'kr_period':None,'kr_month_estimate':meta['kr_estimate_month'],
            'milestones':[],'sources':{sid:r14['sources'][sid] for sid in meta['sources']},'note':r14['prep_note']}
    if meta['kr_start']:
        start=date.fromisoformat(meta['kr_start']);end=date.fromisoformat(meta['kr_end'])
        result['kr_period']=f'{start.isoformat()} ~ {end.isoformat()}'
        now=date.fromisoformat(as_of) if isinstance(as_of,str) else (as_of or date.today())
        result['days_left']=(start-now).days
        result['milestones']=[{'phase':x['phase'],'start':(start-timedelta(days=x['days_before'])).isoformat(),
                               'days_before':x['days_before'],
                               'status':'진행 시점 지남' if start-timedelta(days=x['days_before'])<=now else '예정'}
                              for x in r14['prep_offsets']]
    else:
        # Only a month-level window; no fake precise starting date.
        year,month=map(int,meta['kr_estimate_month'].split('-'))
        prev=f'{year-1}-12' if month==1 else f'{year}-{month-1:02d}'
        result['approx_prep_month']=prev
        result['milestones']=[{'phase':x['phase'],'start':None,'days_before':x['days_before'],'status':'한국 일자 확인 후 산출'}
                              for x in r14['prep_offsets']]
    return result


def export_r14_json(path,lineage,calendar_result):
    p=Path(path)
    if p.suffix.lower()!='.json':raise ValueError('JSON만 저장할 수 있습니다.')
    if p.exists():raise FileExistsError('원본 덮어쓰기 방지: 다른 파일 이름을 지정하세요.')
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as stream:
        json.dump({'schema':'r14-plan.v1','lineage':lineage,'schedule':calendar_result},stream,ensure_ascii=False,indent=2)
    return p
