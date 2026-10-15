"""R12 course-specific competitive skill review.

Does not estimate race-win probability or fabricate skill activation rates.
Observed activation/effective frequency uses user-verified race samples only.
Rules are deliberately conservative, transparent and versionable.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
from typing import Optional, Sequence
import json, math
from pathlib import Path

SOURCE_TRACKS='https://gametora.com/ko/umamusume/racetracks'
SOURCE_SKILLS='https://gametora.com/ko/umamusume/skills'

COURSES = {
 '도쿄 잔디 2400m': {'venue':'도쿄','meters':2400,'surface':'잔디','direction':'좌회전','end':'코너','source':'https://game8.jp/umamusume/605243','stamina_guidance':'2025년 일본 공략 참고: 스태미나 약 1400+금회복1 또는 약 1600. 캐릭터/환경에 따라 다름'},
 '삿포로 잔디 2600m': {'venue':'삿포로','meters':2600,'surface':'잔디','direction':'우회전','end':'코너','source':'https://gamewith.jp/uma-musume/article/show/506953','stamina_guidance':'일본 2025년 8월 리오히: 장거리 회복 스킬과 체력 계산 필수, 보편 최적 수치는 미확인'},
 '교토 잔디 2000m': {'venue':'교토','meters':2000,'surface':'잔디','direction':'우회전','end':'코너','source':'https://gamewith.jp/uma-musume/article/show/512814','stamina_guidance':'2025년 9월 일본 특정 선입 공략: 스태미나 1200 이상을 제안. 캐릭터·회복·대회 환경에 따라 달라짐'},
 '니가타 잔디 1200m': {'venue':'니가타','meters':1200,'surface':'잔디','direction':'좌회전','end':'직선','source':'https://gamewith.jp/uma-musume/article/show/518724','stamina_guidance':'2025년 10월 일본 특정 추입 공략: 스태미나 700 이상 제안. 타 각질과 환경 일반화 불가'},
 '한신 잔디 2200m': {'venue':'한신','meters':2200,'surface':'잔디','direction':'우회전','end':'코너','source':'https://gamewith.jp/uma-musume/article/show/506494','stamina_guidance':'기준 실측 전: 스태미나 수치 추천 보류'},
 '나카야마 잔디 2500m': {'venue':'나카야마','meters':2500,'surface':'잔디','direction':'우회전','end':'직선','source':'https://gamewith.jp/uma-musume/article/show/472721','stamina_guidance':'2024년 말 일본 공략 참고: 스태미나 약 1300 이상. 최신 한국 서버 검증 전'},
 '교토 잔디 3200m': {'venue':'교토','meters':3200,'surface':'잔디','direction':'우회전','end':'미검증','source':'https://gamewith.jp/uma-musume/article/show/488825','stamina_guidance':'2025년 일본 공략 참고: 스태미나 약 1600+금회복2. 캐릭터/환경에 따라 다름'},
}
STYLES=('도주','선행','선입','추입')
EVENTS=('챔피언스 미팅','리그 오브 히어로즈')

@dataclass(frozen=True)
class Course:
    venue: str
    meters: int
    surface: str
    direction: str
    season: str = '미정'
    weather: str = '미정'
    ground: str = '미정'
    end: str = '미검증'
    style: str = '선행'
    event: str = '챔피언스 미팅'
    source: str = ''

    def validate(self):
        if not self.venue or not 800 <= self.meters <= 4000: raise ValueError('경기장과 거리(800~4000m)를 확인하세요.')
        if self.surface not in ('잔디','더트','미정'): raise ValueError('마장이 잘못되었습니다.')
        if self.direction not in ('좌회전','우회전','직선','미정'): raise ValueError('코스 방향이 잘못되었습니다.')
        if self.end not in ('코너','직선','미검증'): raise ValueError('종반 시작 지형을 확인하세요.')
        if self.style not in STYLES or self.event not in EVENTS: raise ValueError('각질이나 대회가 잘못되었습니다.')
        if self.season not in ('봄','여름','가을','겨울','미정'): raise ValueError('계절을 확인하세요.')
        if self.weather not in ('맑음','흐림','비','눈','미정'): raise ValueError('날씨를 확인하세요.')
        if self.ground not in ('양호','다습','포화','불량','미정'): raise ValueError('마장 상태를 확인하세요.')

@dataclass(frozen=True)
class Candidate:
    name: str
    points: Optional[int] = None
    status: str = '미확인' # 구매가능 / 보유 / 미확인
    races: Optional[int] = None
    activated: Optional[int] = None
    effective: Optional[int] = None

    def validate(self):
        if not self.name or len(self.name)>90: raise ValueError('스킬명이 잘못되었습니다.')
        if self.status not in ('구매가능','보유','미확인'): raise ValueError('스킬 상태를 확인하세요.')
        if self.points is not None and not 1 <= self.points <= 5000: raise ValueError('확인한 구매비용(Pt)은 1~5000이어야 합니다.')
        sample = (self.races, self.activated, self.effective)
        if any(n is not None for n in sample):
            if any(n is None or not isinstance(n,int) for n in sample): raise ValueError('경기수·발동수·유효수는 세 개를 모두 입력하세요.')
            if not (1 <= self.races <= 100000 and 0 <= self.effective <= self.activated <= self.races):
                raise ValueError('관측값은 0 ≤ 유효수 ≤ 발동수 ≤ 경기수를 만족해야 합니다.')

@dataclass(frozen=True)
class Advice:
    name: str
    verdict: str
    condition: str
    activation: str
    timing: str
    efficiency: str
    cost: str
    note: str
    source: str
    order: int
    observed_rate: Optional[float] = None
    effective_rate: Optional[float] = None
    wilson_range: Optional[tuple] = None


# Phase information reflects the course cited for the preset; race/position checks
# remain dynamic and cannot be reduced to an unconditional trigger percentage.
SPECIAL = {
    '왕수': {'category':'가속','styles':('선행','선입'), 'modes':('코너',), 'reason':'종반이 코너에서 시작하는 코스에서 유효한 가속 후보. 순위/위치 조건 검토 필요', 'src':'https://gamewith.jp/uma-musume/article/show/496441'},
    '육박하는 그림자': {'category':'가속','styles':('추입',), 'modes':('직선',), 'reason':'종반 직선 코스에서 강한 가속 후보. 발동 조건·경기 전개 확인 필요', 'src':'https://gamewith.jp/uma-musume/article/show/472721'},
    '앵글링×스키밍': {'category':'가속','styles':('도주',), 'modes':('코너',), 'reason':'종반 코너 선두 조건의 계승 가속 후보. 선두 유지에 좌우됨', 'src':'https://gamewith.jp/uma-musume/article/show/477855'},
    '중거리 직선○': {'category':'속도','styles':STYLES, 'distance':'중거리','reason':'중거리 직선 속도 후보. 종반 가속기와 역할이 달라 병행 검토', 'src':'https://gametora.com/ko/umamusume/skills'},
    '중거리 코너○': {'category':'속도','styles':STYLES, 'distance':'중거리','reason':'중거리 코너 속도 후보. 발동 시점에 따라 효율 달라짐', 'src':'https://gametora.com/ko/umamusume/skills'},
    '스피드 이터': {'category':'속도','styles':STYLES, 'distance':'마일','reason':'마일 중반 전방 조건. 발동 가능성은 상대 위치에 좌우됨', 'src':'https://gametora.com/ko/umamusume/supports/20030-ines-fujin'},
}

SEASONS={'봄':'봄 우마무스메○','여름':'여름 우마무스메○','가을':'가을 우마무스메○','겨울':'겨울 우마무스메○'}
WEATHERS={'맑음':'맑은 날○','흐림':'흐린 날○','비':'비 오는 날○','눈':'눈 오는 날○'}
VENUES={'도쿄':'도쿄 경기장○','한신':'한신 경기장○','나카야마':'나카야마 경기장○','교토':'교토 경기장○','삿포로':'삿포로 경기장○','니가타':'니가타 경기장○'}

def distance_type(meters):
    if meters<=1400:return '단거리'
    if meters<=1800:return '마일'
    if meters<=2400:return '중거리'
    return '장거리'

def green_rules(course):
    """Map Korean game skill labels to *known* course condition predicates.

    None denotes unknown race condition, not necessarily a failed trigger.
    """
    rules={}
    def put(key,val):rules[key]=val
    if course.direction=='미정':
        put('시계(우) 방향○',None);put('반시계(좌) 방향○',None)
    else:
        put('시계(우) 방향○',course.direction=='우회전')
        put('반시계(좌) 방향○',course.direction=='좌회전')
    put('근간거리○',course.meters%400==0)
    put('비근간거리○',course.meters%400!=0)
    for ven,skill in VENUES.items():put(skill,ven==course.venue)
    for season,skill in SEASONS.items(): put(skill,None if course.season=='미정' else season==course.season)
    for weather,skill in WEATHERS.items(): put(skill,None if course.weather=='미정' else weather==course.weather)
    put('양호한 경기장○',None if course.ground=='미정' else course.ground=='양호')
    put('진창길○',None if course.ground=='미정' else course.ground in ('다습','포화','불량'))
    return rules

def wilson(success:int,total:int):
    if not total:return (0,1)
    z=1.96;p=success/total;d=1+z*z/total
    mid=(p+z*z/(2*total))/d
    half=z*math.sqrt((p*(1-p)+z*z/(4*total))/total)/d
    return (round(max(0,mid-half),3),round(min(1,mid+half),3))

def rate_text(success,total):
    return f'{100*success/total:.1f}% ({success}/{total}, 관측)' if total is not None else '미측정'

def advise(course:Course, candidates:Sequence[Candidate]):
    course.validate()
    green=green_rules(course)
    results=[]
    for item in candidates:
        item.validate()
        activation='관측 데이터 없음'; timing='미확인';source=SOURCE_SKILLS
        note='스킬의 상세 발동 조건과 코스별 유효 시점은 아직 검증 전입니다.'
        verdict='판단 보류';order=4
        if item.name in green:
            match=green[item.name]
            if match is True:
                verdict='조건 일치';order=1
                activation='레이스 조건 확정 · 지능 추첨형 퍼센트와 별개'
                timing='상시 능력치 조건'
                note='대회 조건에 맞는 녹색 스킬. 실전 가치와 필요한 스탯은 별도 검토'
                if item.name in ('시계(우) 방향○','반시계(좌) 방향○',*SEASONS.values()):note+=' · 스피드 계열'
                elif item.name in ('근간거리○','비근간거리○',*VENUES.values()):note+=' · 스태미나 계열'
                elif item.name in ('양호한 경기장○','진창길○'):note+=' · 파워 계열'
                elif item.name in WEATHERS.values():note+=' · 근성 계열'
            elif match is False:
                verdict='조건 불일치';order=6
                activation='해당 코스에서는 조건 불충족'
                timing='효과 없음'
                note='현재 입력한 경기 조건에서는 추천하지 않음'
            else:
                verdict='조건 미확인';order=5
                activation='레이스 조건을 먼저 입력해야 함'
                timing='확인 필요'
                note='날씨·마장 상태 등 확정되지 않은 조건이 있음'
        elif item.name in SPECIAL:
            sp=SPECIAL[item.name];source=sp['src'];note=sp['reason'];timing=sp['category']
            d=distance_type(course.meters)
            if course.style not in sp['styles'] or (sp.get('distance') and d!=sp['distance']):
                verdict='각질·거리 불일치';order=6;activation='현 각질·거리 조건 불일치'
            elif sp.get('modes') and course.end!='미검증' and course.end not in sp['modes']:
                verdict='코스 비효율';order=5;activation='발동하더라도 종반 타이밍이 늦거나 맞지 않을 수 있음'
            elif sp.get('modes') and course.end=='미검증':
                verdict='구간 검증 필요';order=4;activation='코스 종반 지형 미확인'
            else:
                verdict='우선 검토';order=2
                activation='각질·코스 조건 후보 · 실제 발동은 순위/전개 등 영향'
        # Observed probability only if verified by user. Always separate trigger and effective.
        obsrate=effrate=interval=None
        if item.races is not None:
            obsrate=item.activated/item.races
            effrate=item.effective/item.races
            interval=wilson(item.effective,item.races)
            activation += ' / 사용자 입력 발동 '+rate_text(item.activated,item.races)
            timing += ' / 사용자 입력 유효 '+rate_text(item.effective,item.races)
            if item.races < 20:note+=' (경기 표본 20회 미만: 통계 해석 주의)'
        cost='유효 Pt 비용 미확인' if item.points is None else f'{item.points} Pt (사용자 확인값)'
        if item.points and effrate is not None:
            efficiency=f'유효 관측 빈도 / 100 Pt: {100*effrate/item.points:.3f} (효과 크기 미반영)'
        elif item.points:
            efficiency='실전 효율 미산출 · Pt 확인, 유효 발동 표본 없음'
        else:
            efficiency='실전 효율 미산출 · Pt/유효 발동 근거 필요'
        if item.status=='보유':verdict+=' · 획득됨'
        elif item.status=='미확인':note+=' · 실제 스킬 구매 가능 여부 미확인'
        results.append(Advice(name=item.name,verdict=verdict,condition=('조건 적합' if order<=2 else '재확인'),
                     activation=activation,timing=timing,efficiency=efficiency,cost=cost,note=note,
                     source=source,order=order,observed_rate=obsrate,effective_rate=effrate,wilson_range=interval))
    return sorted(results,key=lambda x:(x.order,x.name))

def default_candidates(course):
    """Course preview list != list of owned/purchasable skills."""
    greens=green_rules(course)
    names=[n for n,v in greens.items() if v is True]
    names += [n for n,sp in SPECIAL.items() if course.style in sp['styles']
              and (not sp.get('distance') or distance_type(course.meters)==sp['distance'])]
    return [Candidate(n) for n in dict.fromkeys(names)]

def parse_candidate_lines(raw):
    out=[];seen=set()
    for index,line in enumerate(raw.splitlines(),1):
        if not line.strip():continue
        cells=[c.strip() for c in line.split('|')]
        if len(cells) not in (1,3,6):
            raise ValueError(f'{index}행: 스킬명 | Pt | 상태 | 경기수 | 발동수 | 유효수 형식(또는 스킬명만)')
        name=cells[0]
        if name in seen: raise ValueError(f'{index}행: 중복 스킬 {name}')
        seen.add(name)
        if len(cells)==1: candidate=Candidate(name)
        else:
            def value(txt):
                if not txt:return None
                if not txt.isascii() or not txt.isdecimal():raise ValueError(f'{index}행: 숫자를 확인하세요.')
                return int(txt)
            parts=(cells+['','',''])[:6]
            candidate=Candidate(parts[0],value(parts[1]),parts[2] or '미확인',*(value(v) for v in parts[3:6]))
        candidate.validate();out.append(candidate)
    return out

def save_report(path,course,candidates,advices):
    body={'schema':'r12_course_skill_1','origin':'user_manual_or_reference_candidate','user_observation_independently_verified':False,'estimated_winrate':None,
        'course':asdict(course),'candidates':[asdict(c) for c in candidates],
        'recommendations':[asdict(a) for a in advices]}
    Path(path).write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')
    return body
