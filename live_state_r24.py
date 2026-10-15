"""Fail-closed, pure freshness rules for the read-only game companion.

A screenshot of a previous window/size/session must never repopulate the HUD
when a new client window or changed layout has been detected.
"""
from __future__ import annotations

class FreshnessGate:
    def __init__(self):
        self.key = None
        self.epoch = 0

    def update(self, hwnd, rect=None):
        if hwnd is None:
            key = None
        else:
            if not isinstance(rect, (tuple, list)) or len(rect) != 4:
                raise ValueError('게임 창 위치 데이터가 없습니다.')
            key = (int(hwnd), tuple(int(x) for x in rect))
        changed = key != self.key
        if changed:
            self.epoch += 1
            self.key = key
        return changed

    def ticket(self):
        return self.epoch

    def accepts(self, ticket, hwnd):
        return (self.key is not None and ticket == self.epoch
                and self.key[0] == hwnd)

    @staticmethod
    def safe_values(scene: str | None, values: dict) -> dict:
        # Numeric ROIs were calibrated for TRAINING screen only. Never reuse
        # coordinates for events, purchases, dialogs or unknown scenes.
        return dict(values) if scene == '훈련' and isinstance(values, dict) else {}


def rectangles_overlap(a, b) -> bool:
    """Guard against capturing the always-on-top companion as game pixels."""
    if len(a) != 4 or len(b) != 4:
        raise ValueError('화면 좌표는 네 개여야 합니다.')
    ax1, ay1, ax2, ay2 = map(int, a)
    bx1, by1, bx2, by2 = map(int, b)
    if ax1 >= ax2 or ay1 >= ay2 or bx1 >= bx2 or by1 >= by2:
        raise ValueError('잘못된 화면 사각형입니다.')
    return max(ax1, bx1) < min(ax2, bx2) and max(ay1, by1) < min(ay2, by2)
