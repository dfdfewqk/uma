"""R37 proof: Companion click-only actual Tk interface on Linux Xvfb."""
from __future__ import annotations
import json
import sys
from pathlib import Path

REQUIRED = {
    'schema': 'uma_r37_click_only_helper_smoke_v1',
    'result': 'PASS',
    'synthetic_only': True,
    'gui_platform': 'linux',
    'typeable_fields_in_helper': 0,
    'starts_monitoring': True,
    'click_only_pause_resume': True,
    'developer_tools_hidden_by_default': True,
    'developer_tools_can_be_collapsed': True,
    'game_client_tested': False,
    'automatic_click_enabled': False
}


def validate(data):
    if not isinstance(data,dict):
        raise ValueError('R37 helper GUI report invalid')
    for key,value in REQUIRED.items():
        if key not in data or type(data[key]) is not type(value) or data[key]!=value:
            raise ValueError('R37 helper GUI report invalid: '+key)


def main():
    if len(sys.argv)!=2:
        raise SystemExit('usage: validate_helper_r37.py <helper.json>')
    try:
        payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        validate(payload)
    except (OSError,ValueError) as exc:
        raise SystemExit(str(exc))
    print('PASS: R37 click-only Companion Tk UI validated on Linux Xvfb (not live Korean game)')


if __name__=='__main__':
    main()
