"""R44 one-item-at-a-time FREE TP recovery planning.

This selects a read-only proposal only; every inventory/TP state must be
re-observed after an actual use. Premium currency is always excluded.
"""
from __future__ import annotations
from dataclasses import dataclass

from auto_core_r40 import TPView


@dataclass(frozen=True)
class FreeTPItem:
    item_id: str
    count: int
    recovery: int
    free: bool
    verified: bool

    def validate(self):
        if not isinstance(self.item_id, str) or not 1 <= len(self.item_id) <= 100:
            raise ValueError('TP 아이템 ID 오류')
        if (type(self.count) is not int or not 0 <= self.count <= 100000
                or type(self.recovery) is not int or not 1 <= self.recovery <= 100000
                or type(self.free) is not bool or type(self.verified) is not bool):
            raise ValueError('TP 보유량·회복량 또는 무료 여부 오류')
        return self


@dataclass(frozen=True)
class TPAdvice:
    action: str  # start_run, use_free_tp_item, wait_regen, verify, stop
    reason: str
    item_id: str | None = None
    waste: int = 0
    game_input_allowed: bool = False


def plan_tp_step(tp: TPView, items: tuple[FreeTPItem, ...] | None) -> TPAdvice:
    """Never plan repeated blind item use; choose at most ONE and re-observe."""
    tp.validate()
    if not tp.verified or tp.tp is None or tp.cost is None or tp.cost <= 0:
        return TPAdvice('verify', '현재 TP/필요 TP가 확인되지 않았습니다.')
    if tp.tp >= tp.cost:
        return TPAdvice('start_run', 'TP 충분 · 시작 버튼이 확인되면 진행 가능')
    if tp.tp_cap is not None and tp.tp_cap < tp.cost:
        return TPAdvice('verify', '보유 TP 상한보다 육성 시작 비용이 높습니다.')
    if items is None or not isinstance(items, tuple):
        return TPAdvice('verify', '무료 회복 아이템 목록 확인 필요')
    if any(not isinstance(i, FreeTPItem) for i in items):
        raise ValueError('아이템 목록 형식 오류')
    for item in items:
        item.validate()
    if len({i.item_id for i in items}) != len(items):
        raise ValueError('TP 아이템 중복')
    if any(not i.verified for i in items):
        return TPAdvice('verify', '보유한 무료 TP 아이템의 정보가 모두 검증되지 않았습니다.')
    free = [i for i in items if i.free and i.count > 0]
    if not free:
        return TPAdvice('wait_regen', '사용 가능한 무료 아이템 없음 · 자연 회복 대기')
    if tp.tp_cap is None:
        return TPAdvice('verify', 'TP 최대치 확인 전에는 무료 아이템 낭비량을 계산할 수 없습니다.')
    choices = []
    cap = tp.tp_cap
    for i in free:
        effective = i.recovery if cap is None else min(i.recovery, max(0, cap-tp.tp))
        if effective <= 0:
            continue
        reaches = tp.tp + effective >= tp.cost
        waste = max(0, i.recovery-effective)
        remaining = max(0, tp.cost-tp.tp-effective)
        # Prefer reaching the next start threshold, then avoid wasted recovery
        # and choose the least recovery that meets the target. If none reaches
        # the threshold, choose one with greatest useful gain.
        choices.append((0 if reaches else 1,
                        waste if reaches else remaining,
                        effective if reaches else -effective,
                        i.item_id, waste))
    if not choices:
        return TPAdvice('verify', '무료 아이템이 있지만 회복 가능한 TP가 0입니다.')
    choices.sort()
    _, _, _, selected, waste = choices[0]
    return TPAdvice(
        'use_free_tp_item',
        '무료 아이템 1개 사용 후보 · 실제 사용 후 TP와 잔여 수량 재확인'
        + (' · 일부 회복량이 상한에서 낭비될 수 있음' if waste else ''),
        item_id=selected, waste=waste)
