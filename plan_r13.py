"""R13 JP-2025 post-adjustment race prep evidence pack.

Curated historical strategy candidates; no ML fit, fabricated probabilities, or
claim that Korean server schedules/available cards match JP 2025.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import json

DATA_PATH=Path(__file__).resolve().parent/'research'/'r13'/'japan_island_2025_events.json'
STYLES=('도주','선행','선입','추입')
TYPES=('스피드','스태미나','파워','근성','지능','친구')


def load_pack(path: Path=DATA_PATH):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema')!='r13.v1' or data.get('region')!='JP' or data.get('applied_to_KR') is not False:
        raise ValueError('일본 2025년 자료팩 형식 또는 서버 구분이 잘못되었습니다.')
    if data.get('patch_after')!='2025-06-30':
        raise ValueError('6월 30일 수정 후 기준 자료인지 확인할 수 없습니다.')
    ids=[ev['id'] for ev in data['events']]
    if len(ids)!=len(set(ids)):raise ValueError('중복 대회가 존재합니다.')
    if len({(p['event_id'],p['style']) for p in data['profiles']})!=len(data['profiles']):
        raise ValueError('동일 대회·각질의 중복 전략입니다.')
    for ev in data['events']:
        if ev['status']!='2025년 일본 확정 기록' or not ev['source_ids']:
            raise ValueError('대회 출처나 확정 상태가 없습니다.')
    for p in data['profiles']:
        if p['event_id'] not in ids or p['style'] not in STYLES:raise ValueError('각질/대회 연결 오류')
    for card in data['cards']:
        if card['type'] not in TYPES or card['purpose'] not in ('본육성','인자작'):
            raise ValueError('카드 형식 오류')
        if not card['source_ids'] or not all(x in data['provenance'] for x in card['source_ids']):
            raise ValueError('카드 출처 연결 오류')
        if not all(ev in ids or ev=='*' for ev in card['events']):
            raise ValueError('카드 대회 연결 오류')
    return data

@dataclass(frozen=True)
class Recommendation:
    event_id:str
    event_label:str
    style:str
    mode:str
    selections:list
    alternatives:list
    unowned:list
    missing_types:list
    target_skills:list
    ancestors:list
    stats_reference:dict
    caveats:list
    provenance:dict
    def serializable(self):return asdict(self)


def available_cards(data, event_id:str, style:str, mode:str='본육성'):
    if mode not in ('본육성','인자작'):raise ValueError('지원하지 않는 육성 유형')
    items=[]
    for c in data['cards']:
        if c['purpose']!=mode or style not in c['styles'] or not ('*' in c['events'] or event_id in c['events']):continue
        cc=dict(c)
        # Ordering is based on source specificity & overlap with explicitly mentioned skills,
        # not competitive win rate or invented skill strength.
        cc['_specific']=int(event_id in c['events'])
        cc['_scope']=int(len(c['styles'])==1)
        items.append(cc)
    return items


def recommend(event_id, style, mode='본육성', owned:Optional[set]=None, data=None):
    data=load_pack() if data is None else data
    events={e['id']:e for e in data['events']}
    if event_id not in events:raise ValueError('대회 ID가 데이터팩에 없습니다.')
    if style not in STYLES:raise ValueError('지원하지 않는 각질입니다.')
    if mode not in ('본육성','인자작'):raise ValueError('지원하지 않는 육성 모드입니다.')
    if owned is not None and not isinstance(owned,(set,frozenset)):
        raise TypeError('보유 카드 목록은 ID 집합입니다.')
    p=next((x for x in data['profiles'] if x['event_id']==event_id and x['style']==style),None)
    if p is None: raise ValueError('이 대회 각질에 검수된 기록이 없습니다.')
    candidate=available_cards(data,event_id,style,mode)
    owned_set=set(owned) if owned is not None else None
    candidate.sort(key=lambda c:(c['_specific'],c['_scope'],len(set(c['target_skills'])&set(p['skill_targets']))),reverse=True)
    # Cards from Japanese sources may be unavailable in Korean server, unknown by default.
    available=[c for c in candidate if owned_set is None or c['id'] in owned_set]
    excluded=[c for c in candidate if owned_set is not None and c['id'] not in owned_set]
    slots=6; result=[]; used=set(); types_taken=set()
    def add(c):
        if c['id'] in used or len(result)>=slots:return
        result.append({k:v for k,v in c.items() if not k.startswith('_')})
        used.add(c['id']);types_taken.add(c['type'])
    if mode=='본육성':
        # Source-backed default island build: one of each type including friend.
        for typ in TYPES:
            opt=next((c for c in available if c['type']==typ and c['id'] not in used),None)
            if opt:add(opt)
        for c in available:
            if len(result)==slots:break
            add(c)
    else:
        # Factor-farming support choices emphasize valuable missing hints; not a fixed deck.
        for c in available:
            if c['type'] not in types_taken:add(c)
        for c in available:add(c)
    alts=[{k:v for k,v in c.items() if not k.startswith('_')} for c in available if c['id'] not in used]
    missing=([t for t in TYPES if t not in types_taken] if mode=='본육성' else [])
    refs=set(events[event_id]['source_ids']+p['source_ids'])
    for c in result:refs.update(c['source_ids'])
    warnings=[
        '일본 2025년 개최 대회/카드 데이터이며, 한국 서버 개최 일정·카드 구현 상태는 별도 검증이 필요합니다.',
        '추천 후보는 공략에서 언급된 스킬·편성 적합도를 바탕으로 필터링한 것으로, 발동률·승률·Pt 성능의 검증된 순위가 아닙니다.',
        '실제 보유 카드와 돌파·대체 카드·스킬 중복·캐릭터의 자체 스킬을 확인해야 합니다.',
    ]
    if owned_set is None:warnings.append('보유 카드를 지정하지 않았으므로 실보유 여부는 미확인입니다.')
    if mode=='본육성' and '친구' in missing:warnings.append('터커 브라인이 없어 무인도 건설 계획 코스트가 부족할 수 있습니다.')
    if mode=='인자작':warnings.append('인자작은 적합한 힌트를 확보하기 위한 후보이며 인자 승계/추첨 성공률 예측은 제공하지 않습니다.')
    if events[event_id]['hills']=='없음':warnings.append('해당 코스는 오르막·내리막이 없어 해당 지형 조건 스킬이 작동하지 않습니다.')
    if len(result)<6:warnings.append('현재 조건에 맞는 확인된 카드 후보가 6장 미만입니다. 무리하게 무관한 카드를 채우지 않았습니다.')
    return Recommendation(event_id,events[event_id]['label'],style,mode,result,alts,
         [{k:v for k,v in c.items() if not k.startswith('_')} for c in excluded],missing,
         p['skill_targets'],p['parents'],p['stats_reference'],warnings,
         {key:data['provenance'][key] for key in sorted(refs)})


def export_plan(path, recommendation:Recommendation):
    path=Path(path)
    if path.suffix.lower()!='.json':raise ValueError('JSON 파일로 저장해 주세요.')
    if path.exists():raise FileExistsError('기존 파일 덮어쓰기를 방지합니다. 다른 이름을 사용하세요.')
    path.write_text(json.dumps(recommendation.serializable(),ensure_ascii=False,indent=2),encoding='utf-8')
    return path
