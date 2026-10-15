"""Versioned, scenario-specific ML signal adapters for R16.

The common learner's vocabulary intentionally has only generic signal slots.
A new scenario must implement a new adapter AND its own test fixtures.
"""
from __future__ import annotations
import math


def _number(value, default=0.):
    if isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value):
        return float(value)
    return default


def island_signals(values: dict) -> tuple[float, float, float, float]:
    levels = values.get('building_levels') or {}
    lv = [_number(x) for x in levels.values()] if isinstance(levels,dict) else []
    return (max(0.,min(1.,_number(values.get('island_tickets'))/3)),
            max(0.,min(3.,_number(values.get('development_points'))/600)),
            sum(lv)/max(1,len(lv))/5,
            1.0 if values.get('turns_until_next_ticket') in (0,1,2) else 0.)


ADAPTERS = {'island_post_patch_v1':island_signals}


def extract_ml_signals(scenario_id: str, features: dict) -> tuple[float,float,float,float]:
    if scenario_id not in ADAPTERS:
        raise ValueError(f'R16 시나리오 ML 특징 어댑터 미등록: {scenario_id}')
    result = ADAPTERS[scenario_id](features)
    if len(result)!=4 or any(not math.isfinite(x) or abs(x)>5 for x in result):
        raise ValueError('R16 시나리오 특징 수치 오류')
    return result
