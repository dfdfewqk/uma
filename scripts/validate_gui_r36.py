"""Validate real Linux Xvfb/Tk source GUI evidence before Windows packaging.

A CI service-side Windows --windowed app cannot prove interactive GUI behavior.
This checks the artifact created from the same commit in a virtual display.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REQUIRED = {
    'schema': 'uma_r36_windows_gui_synthetic_smoke_v1',
    'result': 'PASS',
    'r6_reviewed_actions': 2,
    'r34_panel_created': True,
    'r35_actions_rendered': 2,
    'r35_stale_invalidation_checked': True,
    'r35_conflict_detected': True,
    'game_client_tested': False,
    'automatic_click_enabled': False,
    'synthetic_only': True,
    'gui_platform': 'linux',
    'frozen_binary': False,
}


def validate(data: object) -> None:
    if not isinstance(data, dict):
        raise ValueError('R36 source Tk GUI smoke report invalid')
    for key, value in REQUIRED.items():
        if key not in data or type(data[key]) is not type(value) or data[key] != value:
            raise ValueError('R36 source Tk GUI smoke report invalid: '+key)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('Usage: validate_gui_r36.py <source-GUI.json>')
    f = Path(sys.argv[1])
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(str(error))
    print('PASS: R36 synthetic source Tk GUI validated on Linux Xvfb; Windows GUI/game untested')


if __name__ == '__main__':
    main()
