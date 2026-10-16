"""R37 click-only Companion UI smoke under an actual Tk virtual display.

No game client is launched. Synthetic demo and state changes are not training data.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCHEMA = 'uma_r37_click_only_helper_smoke_v1'


def inspect_helper(factory):
    app = None
    try:
        app = factory()
        app.withdraw()
        app.update_idletasks()
        if not app.winfo_exists() or not app.monitoring:
            raise RuntimeError('helper is not active on first launch')
        if app.dev_visible or app.dev_panel.winfo_manager():
            raise RuntimeError('advanced input and inspection tools are visible by default')
        if app.helper_switch is None or app.helper_switch.cget('state') != 'normal':
            raise RuntimeError('click-only control not available')
        if not app.action.get() or not app.reason.get():
            raise RuntimeError('main recommendation/status panel missing')
        # Inspect actual widget tree, excluding collapsed developer controls.
        # A withdrawn root cannot use winfo_ismapped() as evidence.
        editable=0
        stack=[child for child in app.body.winfo_children() if child is not app.dev_panel]
        while stack:
            node=stack.pop()
            cls=node.winfo_class()
            if cls in ('Entry', 'Text', 'TEntry', 'TText'):
                editable+=1
            if cls=='TCombobox' and str(node.cget('state'))!='readonly':
                editable+=1
            stack.extend(node.winfo_children())
        if editable:
            raise RuntimeError('typing required by primary helper interface')
        if not hasattr(app,'target_round') or not hasattr(app,'target_style'):
            raise RuntimeError('R39 target selectors are missing')
        app.event_var.set('챔피언스 미팅')
        app.target_round.set('2회차')
        app.target_style.set('추입')
        app._target_changed()
        if app.current_target is None or app.current_target.key!='cm-2':
            raise RuntimeError('R39 target settings not applied')
        if '코스 정보 미검증' not in app.target_status.get():
            raise RuntimeError('Unverified KR course must not be presented as verified')
        app._helper()
        if app.monitoring or app.action.get() != '헬퍼 일시 정지':
            raise RuntimeError('pause button did not clear active helper state')
        if not app.helper_switch.cget('text').startswith('화면 분석 다시'):
            raise RuntimeError('resume affordance not displayed')
        app._helper()
        if not app.monitoring or not app.helper_switch.cget('text').startswith('화면 분석 일시'):
            raise RuntimeError('helper did not resume')
        app._toggle_dev_tools()
        if not app.dev_panel.winfo_manager():
            raise RuntimeError('optional advanced controls did not open')
        app._toggle_dev_tools()
        if app.dev_panel.winfo_manager():
            raise RuntimeError('advanced controls did not close')
        return {
            'schema': SCHEMA, 'result': 'PASS', 'synthetic_only': True,
            'gui_platform': sys.platform,
            'typeable_fields_in_helper': editable,
            'starts_monitoring': True, 'click_only_pause_resume': True,
            'developer_tools_hidden_by_default': True,
            'developer_tools_can_be_collapsed': True,
            'game_client_tested': False, 'automatic_click_enabled': False
        }
    finally:
        if app is not None:
            app.destroy()


def maybe_run_cli(factory, argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if '--helper-smoke-report' not in argv:
        return False
    if len(argv)!=2 or argv[0]!='--helper-smoke-report' or not argv[1]:
        raise SystemExit(2)
    target=Path(argv[1])
    if target.exists() or target.is_symlink():
        raise SystemExit('Refusing to overwrite helper report')
    with tempfile.TemporaryDirectory(prefix='uma_r37_helper_') as folder:
        old=os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA']=folder
        try:
            try:
                report=inspect_helper(factory)
                exit_code=0
            except Exception as error:
                report={'schema':SCHEMA,'result':'FAIL',
                        'failure_type':type(error).__name__,
                        'synthetic_only':True,'game_client_tested':False,
                        'automatic_click_enabled':False}
                exit_code=1
        finally:
            if old is None:os.environ.pop('LOCALAPPDATA',None)
            else:os.environ['LOCALAPPDATA']=old
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as output:
        json.dump(report,output,ensure_ascii=False,indent=2)
    raise SystemExit(exit_code)
