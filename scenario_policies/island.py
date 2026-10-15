"""Post-adjustment island *heuristic*. Not official mechanics or calibrated ML.

A future scenario should define a different policy and register it in __init__.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


CONFIG_FILE = Path(__file__).with_name('island_post_patch_v1.json')


def load_config() -> dict:
    config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    if config['id'] != 'island_post_patch_v1' or config['data_status'] != 'experimental_unvalidated':
        raise ValueError('무인도 설정 버전 또는 검증 상태가 잘못되었습니다.')
    return config


class IslandPostPatchPolicy:
    id = 'island_post_patch_v1'
    name = '무인도 · 일본 2025-06-30 조정 후'
    version = 'JP-after-2025-06-30 / KR-rules-unverified'

    def __init__(self):
        self.config = load_config()

    def adjust(self, profile: Any, state: Any, action: Any) -> Tuple[float, List[str], Dict[str, float]]:
        numbers = self.config['heuristic_weights']
        bonus, details, parts = 0.0, [], {}
        if action.development_points > 0:
            phase = 1.0 if state.remaining_turns >= numbers['early_phase_remaining_turns'] else 0.5
            val = action.development_points * numbers['development_point_weight'] * phase
            bonus += val
            parts['발전 Pt 잠재가치(가정)'] = round(val, 2)
            details.append(f'발전 Pt +{action.development_points}: 시설 자원으로 기록')
        if action.name == '섬 트레이닝':
            if state.island_tickets <= 0:
                return -100000.0, ['섬 트레이닝 티켓이 없어 선택 불가'], {'티켓 부족': -100000.0}
            n = action.friend_types
            if n >= 3:
                val = numbers['island_three_friend_bonus'] + numbers['per_additional_friend_bonus'] * min(n-3, 2)
                bonus += val
                parts['복수 우정 훈련 가정 보정'] = val
                details.append(f'우정 훈련 {n}곳: 섬 훈련 유리할 가능성')
            elif n == 2:
                val = numbers['island_two_friend_penalty']
                bonus += val
                parts['우정 훈련 2곳 가정 보정'] = val
            else:
                val = numbers['island_few_friend_penalty']
                bonus += val
                parts['우정 훈련 부족 가정 보정'] = val
            if state.turns_until_next_ticket in (0, 1):
                val = numbers['next_ticket_today_bonus'] if state.turns_until_next_ticket == 0 else numbers['next_ticket_tomorrow_bonus']
                bonus += val
                parts['티켓 수령 임박 가정 보정'] = val
                details.append('다음 티켓 수령 임박: 현재 사용 여부를 검토')
        elif state.island_tickets > 0 and state.turns_until_next_ticket == 0:
            val = numbers['unused_ticket_penalty']
            bonus += val
            parts['티켓 기회비용 가정 보정'] = val
        return bonus, details, parts
