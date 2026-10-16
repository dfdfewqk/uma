"""R36 CLI/source quality gates; real Tk is exercised by Windows Actions."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui_smoke_r36 import SCHEMA, maybe_run_cli

ROOT = Path(__file__).resolve().parents[1]


class R36GuiSmokeTests(unittest.TestCase):
    def test_normal_launch_not_intercepted(self):
        self.assertFalse(maybe_run_cli(lambda: None, []))

    def test_malformed_argument_cannot_start_unsafe_smoke(self):
        for args in (['--gui-smoke-report'], ['--gui-smoke-report', 'test.json', 'extra']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                maybe_run_cli(lambda: None, args)
            self.assertEqual(caught.exception.code, 2)

    def test_existing_report_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            path.write_text('original',encoding='utf8')
            with self.assertRaises(SystemExit):
                maybe_run_cli(lambda: None, ['--gui-smoke-report',str(path)])
            self.assertEqual(path.read_text(encoding='utf8'),'original')

    def test_cli_uses_isolated_localappdata_and_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'out.json'
            original=os.environ.get('LOCALAPPDATA')
            seen=[]
            def synthetic_check(_factory):
                seen.append(os.environ['LOCALAPPDATA'])
                return dict(schema=SCHEMA,result='PASS',game_client_tested=False,
                            automatic_click_enabled=False,synthetic_only=True)
            with patch('gui_smoke_r36.run_gui_smoke',side_effect=synthetic_check):
                with self.assertRaises(SystemExit) as exit_result:
                    maybe_run_cli(lambda: None,['--gui-smoke-report',str(path)])
            self.assertEqual(exit_result.exception.code,0)
            self.assertEqual(os.environ.get('LOCALAPPDATA'),original)
            self.assertEqual(len(seen),1)
            self.assertNotEqual(seen[0],original)
            self.assertTrue(path.is_file())
            data=json.loads(path.read_text(encoding='utf8'))
            self.assertTrue(data['synthetic_only'])
            self.assertFalse(data['game_client_tested'])

    def test_gui_main_and_powershell_are_wired(self):
        app=(ROOT/'app.py').read_text(encoding='utf8')
        script=(ROOT/'scripts/windows_smoke_r31.ps1').read_text(encoding='utf8')
        verifier=(ROOT/'scripts/verify_windows_package_r25.py').read_text(encoding='utf8')
        self.assertIn('r36_gui_smoke(UmaApp)',app)
        self.assertIn('--gui-smoke-report',script)
        self.assertIn('R36 real Tk GUI smoke report missing',verifier)
        self.assertIn('r35_conflict_detected',verifier)

    def test_workflow_requires_manual_dispatch_only(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text(encoding='utf8')
        self.assertIn('workflow_dispatch:',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)
        self.assertIn('UmaTrainerKR-R36-Windows-Verified',workflow)
        self.assertLess(workflow.index('Bounded Windows EXE smoke checks'),
                        workflow.index('Create and verify portable ZIP'))


if __name__=='__main__':
    unittest.main()
