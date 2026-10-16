"""Offline skill-purchase plan with verified cost, activation and race-fit gates.

The function builds a proposal; it never buys skills or confirms game ownership.
"""
from __future__ import annotations
from dataclasses import dataclass
from decision_contract_r39 import SkillCondition, skill_fit


@dataclass(frozen=True)
class SkillOffer:
    skill: SkillCondition
    price: int
    priority: int
    already_owned: bool = False
    price_verified: bool = False
    offered_on_screen: bool = False

    def validate(self):
        if not isinstance(self.skill, SkillCondition):
            raise ValueError('스킬 정보 오류')
        if type(self.price) is not int or not 0 < self.price <= 10000:
            raise ValueError('스킬 구매 가격 오류')
        if type(self.priority) is not int or not 0 <= self.priority <= 1000:
            raise ValueError('스킬 우선순위 오류')
        if any(type(value) is not bool for value in
               (self.already_owned, self.price_verified, self.offered_on_screen)):
            raise ValueError('스킬 검증 상태 오류')
        return self


@dataclass(frozen=True)
class PurchasePlan:
    skills: tuple[str, ...]
    total_sp: int
    remaining_sp: int
    reason: str
    proposal_only: bool = True


def plan_retry_purchase(offers: list[SkillOffer], *,
                        style: str, distance: str | None, surface: str | None,
                        skill_points: int | None, consecutive_losses: int,
                        remaining_retries: int, current_race_verified: bool,
                        skill_page_verified: bool) -> PurchasePlan:
    """No mid-run purchase except a verified same-race 2+ loss situation."""
    if (type(consecutive_losses) is not int or consecutive_losses < 0 or
            type(remaining_retries) is not int or remaining_retries < 0):
        raise ValueError('재도전 조건 오류')
    if type(current_race_verified) is not bool or type(skill_page_verified) is not bool:
        raise ValueError('검증 상태 오류')
    if skill_points is not None and (type(skill_points) is not int or
                                     not 0 <= skill_points <= 100000):
        raise ValueError('남은 스킬 Pt 오류')
    if not isinstance(offers, list) or len(offers) > 200:
        raise ValueError('스킬 목록 형식/길이 오류')
    for item in offers:
        item.validate()
    budget = 0 if skill_points is None else skill_points
    if consecutive_losses < 2 or remaining_retries == 0:
        return PurchasePlan((), 0, budget, '연속 2회 패배 후 재도전 상황이 아닙니다.')
    if not current_race_verified or not skill_page_verified or skill_points is None or distance not in ('단거리','마일','중거리','장거리'):
        return PurchasePlan((), 0, budget, '현재 레이스 거리/스킬 화면/Pt 확인 전 구매 보류')
    eligible = []
    for item in offers:
        if item.already_owned or not (item.price_verified and item.offered_on_screen):
            continue
        status, _ = skill_fit(item.skill, style=style,
                              distance=distance, surface=surface)
        if status == 'eligible':
            eligible.append(item)
    eligible.sort(key=lambda x: (-x.priority, x.price, x.skill.name))
    chosen = []
    spent = 0
    seen = set()
    for item in eligible:
        if item.skill.name in seen:
            continue
        seen.add(item.skill.name)
        if len(chosen) >= 2:
            break
        if spent + item.price <= budget:
            chosen.append(item.skill.name)
            spent += item.price
    return PurchasePlan(tuple(chosen), spent, budget - spent,
                        '구매 후보만 산출했습니다. 실제 효과와 최종 대회 계획은 추가 확인 필요' if chosen
                        else '검증되고 구매 가능한 스킬이 없어 Pt 유지')
