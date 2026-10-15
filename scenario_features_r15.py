"""R15 scenario-specific, pre-action-only feature adapters.

Each scenario has its own adapter; the shared training schema must not learn
island features as though they were present in future scenarios.
"""
from __future__ import annotations
from typing import Any


def island_features(state: dict, profile: dict) -> dict[str, Any]:
    buildings = state.get('building_levels') or {}
    return {
        'island_tickets': state.get('island_tickets'),
        'turns_until_next_ticket': state.get('turns_until_next_ticket'),
        'development_points': state.get('development_points'),
        'building_levels': {str(k): int(v) for k, v in buildings.items() if isinstance(v, int) and not isinstance(v, bool)},
    }


ADAPTERS = {'island_post_patch_v1': island_features}


def extract_scenario_features(scenario_id: str, state: dict, profile: dict) -> dict:
    if scenario_id not in ADAPTERS:
        raise ValueError(f'시나리오 전용 특성 어댑터가 없습니다: {scenario_id}')
    return ADAPTERS[scenario_id](state, profile)
