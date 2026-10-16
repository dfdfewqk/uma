"""R36 actual Tk screen smoke: full research/settings GUI, R6 -> R34 -> R35.

Run only by explicit --gui-smoke-report on a virtual-display CI runner.
Creates no game session, no screenshots, no user records, no ML labels.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path

SCHEMA = 'uma_r36_windows_gui_synthetic_smoke_v1'


def run_gui_smoke(factory) -> dict:
    from decision_r6 import AVAILABLE, UNAVAILABLE
    from uma_core import Action, STATS, TRAININGS

    app = None
    mocks = ExitStack()
    def progress(stage: str) -> None:
        print('[UMA R36 GUI] ' + stage, flush=True)

    try:
        progress('creating Tk application')
        # Unexpected modal dialogs hang unattended CI indefinitely; fail fast.
        for dialog in ('showerror', 'showwarning', 'showinfo', 'askyesno', 'askokcancel'):
            mocks.enter_context(patch('tkinter.messagebox.' + dialog,
                side_effect=RuntimeError('Unexpected modal dialog during synthetic GUI smoke')))
        app = factory()
        progress('Tk application constructed')
        app.withdraw()
        app.update_idletasks()
        if not app.r34_panel.winfo_exists() or not app.r6_panel.winfo_exists():
            raise RuntimeError('R34/R6 panel missing from real Tk window')
        progress('loading R34 synthetic conditions')
        app.var_tickets.set('1')
        app.var_ticket_wait.set('2')
        context = app.r34_panel
        context.phase.set('이후')
        context.bonds.set('우정 준비됨')
        context.values['friendship'].set('3')
        context.values['races'].set('3')
        context.values['next_race'].set('2')
        context.values['outings'].set('1')
        audit = context.calculate()
        if audit is None or not audit.checks:
            raise RuntimeError('R34 conditional review did not render')
        app.actions['섬 트레이닝'] = Action(
            name='섬 트레이닝', gains={s: 10 for s in STATS},
            friend_types=3, energy_delta=-15, observed=True)
        app.actions['휴식'] = Action(name='휴식', energy_delta=20, observed=True)
        profile, state = app._profile(), app._state()
        panel = app.r6_panel
        panel._ensure_context(profile, state)
        panel.availability = {
            name: (AVAILABLE if name in ('섬 트레이닝', '휴식') else UNAVAILABLE)
            for name in TRAININGS
        }
        progress('reviewing R6 synthetic choices')
        r6 = panel.calculate()
        if r6 is None or r6.status == '추천 보류' or len(r6.ranked) != 2:
            raise RuntimeError('R6 synthetic all-option comparison failed')
        progress('comparing R35 verified choices')
        result = context.compare_choices()
        if result is None or {r.name for r in result.actions} != {'섬 트레이닝','휴식'}:
            raise RuntimeError('R35 did not connect reviewed R6 choices')
        if result.scores_modified or result.verified_optimal or result.ml_training_label_verified:
            raise RuntimeError('R35 incorrectly claims trained or optimal results')
        text = context.detail.get('1.0','end')
        if '섬 트레이닝' not in text or 'R6 실험' not in text:
            raise RuntimeError('R35 result not rendered in Tk text view')
        progress('checking R35 stale-result invalidation')
        context.values['friendship'].set('2')
        if context._r35_presented:
            raise RuntimeError('R35 stale result survived a manual input change')
        conflict = context.compare_choices()
        if conflict is None or not any('불일치' in s for s in conflict.missing):
            raise RuntimeError('R35 failed to detect R6/R34 mismatched friendship count')
        progress('all synthetic GUI checks complete')
        return {'schema':SCHEMA, 'result':'PASS',
                'gui_platform':sys.platform,
                'frozen_binary':bool(getattr(sys, 'frozen', False)),
                'r6_reviewed_actions':2, 'r34_panel_created':True,
                'r35_actions_rendered':2,'r35_stale_invalidation_checked':True,
                'r35_conflict_detected':True,'game_client_tested':False,
                'automatic_click_enabled':False,'synthetic_only':True}
    finally:
        try:
            if app is not None:
                progress('destroying Tk application')
                app._quit()
        finally:
            mocks.close()


def maybe_run_cli(factory, argv: list[str] | None = None) -> bool:
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--gui-smoke-report' not in argv:
        return False
    if len(argv) != 2 or argv[0] != '--gui-smoke-report' or not argv[1]:
        raise SystemExit(2)
    target = Path(argv[1])
    if target.exists():
        raise SystemExit('Refusing stale GUI smoke report')
    with tempfile.TemporaryDirectory(prefix='uma_r36_gui_') as temp:
        previous = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = temp
        try:
            try:
                report = run_gui_smoke(factory)
                code = 0
            except Exception as error:
                # Windowed executables must not open an unhandled-exception modal.
                # Keep only the exception type in the CI artifact, never local paths.
                print('[UMA R36 GUI] FAILED: ' + type(error).__name__, flush=True)
                report = {'schema': SCHEMA, 'result': 'FAIL',
                          'failure_type': type(error).__name__,
                          'gui_platform': sys.platform,
                          'frozen_binary': bool(getattr(sys, 'frozen', False)),
                          'game_client_tested': False,
                          'automatic_click_enabled': False, 'synthetic_only': True}
                code = 1
        finally:
            if previous is None:
                os.environ.pop('LOCALAPPDATA', None)
            else:
                os.environ['LOCALAPPDATA'] = previous
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)
    raise SystemExit(code)
