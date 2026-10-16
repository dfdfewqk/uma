"""R41 connect preserved 2025 JP research to combined four KR target slots.

Reference profiles are not validated Korean-client skill recommendations.
"""
from __future__ import annotations
from dataclasses import dataclass
from plan_r13 import load_pack
from target_selector_r39 import Target,ROUND_JP_IDS,load_courses,course_for

@dataclass(frozen=True)
class ReferenceProfile:
    label:str
    reference_id:str
    source_region:str
    target_skills:tuple[str,...]
    avoid_skills:tuple[str,...]
    notes:str
    source_ids:tuple[str,...]
    kr_course_verified:bool
    kr_course_source:str|None
    eligible_for_auto_buy:bool=False
    eligible_for_ml:bool=False

def load_reference(target:Target,*,pack=None,kr_courses=None)->ReferenceProfile:
    target.validate()
    pack=load_pack() if pack is None else pack
    if (pack.get('schema')!='r13.v1' or pack.get('region')!='JP'
            or pack.get('applied_to_KR') is not False):
        raise ValueError('일본 연구 원본 데이터 출처 확인 필요')
    event_id=ROUND_JP_IDS[target.round]
    event=next((e for e in pack['events'] if e['id']==event_id),None)
    profile=next((p for p in pack['profiles']
                  if p['event_id']==event_id and p['style']==target.style),None)
    if event is None or profile is None:
        raise ValueError('해당 회차·각질의 기존 공략 연구 데이터가 없습니다.')
    courses=load_courses() if kr_courses is None else kr_courses
    kr=course_for(target,courses)
    return ReferenceProfile(
        label=target.label,reference_id=event_id,source_region='JP',
        target_skills=tuple(profile['skill_targets']),
        avoid_skills=tuple(profile.get('avoid_skills',())),
        notes=profile.get('note',''),
        source_ids=tuple(profile['source_ids']),
        kr_course_verified=bool(kr),
        kr_course_source=kr['source'] if kr else None)

def skill_reference_notice(profile:ReferenceProfile):
    if not profile.kr_course_verified:
        return '한국 서버 코스 미확정. 일본 2025 공략 스킬은 자동 구매하지 않습니다.'
    return '한국 대회 코스 참고 가능. 일본 공략 스킬은 발동 조건·패치·보유 카드 검증 전 자동 구매하지 않습니다.'
