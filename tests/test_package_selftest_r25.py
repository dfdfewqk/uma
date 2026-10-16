"""R25 synthetic and source-tree checks; no pretending Windows was tested."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from package_selftest_r25 import ASSETS, inspect, maybe_run_cli, maybe_run_startup_cli, write_report
from scripts.verify_windows_package_r25 import PROGRAMS, verify
from scripts.validate_helper_r37 import REQUIRED as R37_HELPER_PROOF

ROOT=Path(__file__).resolve().parent.parent

class TestR25SelfCheck(unittest.TestCase):
    def test_source_mode_all_profiles(self):
        for name in ASSETS:
            with self.subTest(name=name):
                output=inspect(name,root=ROOT,frozen=False)
                self.assertEqual(output['result'],'PASS')
                self.assertFalse(output['frozen_binary'])
                self.assertFalse(output['game_client_tested'])
                self.assertFalse(output['automatic_click_enabled'])
                self.assertTrue(all(x['ok'] for x in output['required_resources']))

    def test_missing_resource_blocks_package(self):
        with tempfile.TemporaryDirectory() as td:
            report=inspect('UmaTrainerKR_GameTest',root=Path(td),frozen=True)
        self.assertEqual(report['result'],'FAIL')
        self.assertEqual(report['failed_resource_names'],['scenario_policies/island_post_patch_v1.json'])

    def test_all_gui_packages_require_island_policy(self):
        relative='scenario_policies/island_post_patch_v1.json'
        for name, required in ASSETS.items():
            with self.subTest(executable=name):
                self.assertIn(relative,required)
                with tempfile.TemporaryDirectory() as td:
                    report=inspect(name,root=Path(td),frozen=True)
                    self.assertIn(relative,report['failed_resource_names'])

    def test_late_startup_cli_checks_after_imports(self):
        self.assertFalse(maybe_run_startup_cli('UmaTrainerKR',[]))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'startup.json'
            with self.assertRaises(SystemExit) as ctx:
                maybe_run_startup_cli('UmaTrainerKR',['--startup-check-report',str(path)])
            self.assertEqual(ctx.exception.code,0)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['result'],'PASS')

    def test_corrupt_json_blocks_package(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            sub=root/'scenario_policies';sub.mkdir()
            (sub/'island_post_patch_v1.json').write_text('{bad json',encoding='utf-8')
            report=inspect('UmaTrainerKR_GameTest',root=root,frozen=True)
        self.assertEqual(report['result'],'FAIL')

    def test_write_report_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'check.json'
            write_report({'schema':'foo'},path)
            self.assertEqual(json.loads(path.read_text())['schema'],'foo')
            with self.assertRaises(ValueError):write_report({'schema':'bar'},path)
            self.assertEqual(json.loads(path.read_text())['schema'],'foo')

    def test_cli_no_argument_launch_is_not_intercepted(self):
        self.assertIs(maybe_run_cli('UmaTrainerKR',[]),False)

    def test_cli_report_exit_code_and_report_contents(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'check.json'
            with self.assertRaises(SystemExit) as exc:
                maybe_run_cli('UmaTrainerKR',['--self-check-report',str(path)])
            self.assertEqual(exc.exception.code,0)
            self.assertEqual(json.loads(path.read_text(encoding='utf8'))['result'],'PASS')

    def test_malformed_cli_arguments_fail(self):
        with self.assertRaises(SystemExit) as ctx:maybe_run_cli('UmaTrainerKR',['--self-check-report'])
        self.assertEqual(ctx.exception.code,2)

    def test_report_excludes_local_sensitive_fields(self):
        report=inspect('UmaTrainerKR',root=ROOT)
        raw=json.dumps(report,ensure_ascii=False)
        for forbidden in ('screen_capture','user_name','window_title','ip_address','absolute_path','screenshot_data'):
            self.assertNotIn(forbidden,raw)

    def test_validate_build_artifacts_refuses_fake_files(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):verify(Path(td),'0.25.0')

    def test_fake_exes_without_reports_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in PROGRAMS:
                (root/f'{name}.exe').write_bytes(b'fake'*3000)
            with self.assertRaises(ValueError):verify(root,'0.25.0')

    def test_package_verifier_accepts_corresponding_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'smoke-reports').mkdir()
            (root/'installer').mkdir()
            for name in PROGRAMS:
                (root/f'{name}.exe').write_bytes(b'A'*10001)
                report=inspect(name,root=ROOT,frozen=True)
                (root/'smoke-reports'/f'{name}.json').write_text(json.dumps(report),encoding='utf8')
                (root/'smoke-reports'/f'{name}_startup.json').write_text(json.dumps(report),encoding='utf8')
            (root/'smoke-reports'/'UmaTrainerKR_gui.json').write_text(json.dumps({"schema":"uma_r36_windows_gui_synthetic_smoke_v1","result":"PASS","r6_reviewed_actions":2,"r34_panel_created":True,"r35_actions_rendered":2,"r35_stale_invalidation_checked":True,"r35_conflict_detected":True,"game_client_tested":False,"automatic_click_enabled":False,"synthetic_only":True,"gui_platform":"linux","frozen_binary":False}),encoding='utf8')
            (root/'smoke-reports'/'UmaTrainerKR_helper.json').write_text(json.dumps(R37_HELPER_PROOF),encoding='utf8')
            (root/'installer'/'UmaTrainerKR_Setup_0.25.0.exe').write_bytes(b'B'*10001)
            data=verify(root,'0.25.0')
            self.assertEqual(len(data['files']),5)
            self.assertFalse(data['korean_game_tested'])

    def test_corrupt_report_blocks_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'smoke-reports').mkdir();(root/'installer').mkdir()
            for name in PROGRAMS:
                (root/f'{name}.exe').write_bytes(b'A'*10001)
                report=inspect(name,root=ROOT,frozen=True)
                if name=='UmaTrainerKR_Companion':report['automatic_click_enabled']=True
                (root/'smoke-reports'/f'{name}.json').write_text(json.dumps(report),encoding='utf8')
                (root/'smoke-reports'/f'{name}_startup.json').write_text(json.dumps(report),encoding='utf8')
            (root/'smoke-reports'/'UmaTrainerKR_gui.json').write_text(json.dumps({"schema":"uma_r36_windows_gui_synthetic_smoke_v1","result":"PASS","r6_reviewed_actions":2,"r34_panel_created":True,"r35_actions_rendered":2,"r35_stale_invalidation_checked":True,"r35_conflict_detected":True,"game_client_tested":False,"automatic_click_enabled":False,"synthetic_only":True,"gui_platform":"linux","frozen_binary":False}),encoding='utf8')
            (root/'smoke-reports'/'UmaTrainerKR_helper.json').write_text(json.dumps(R37_HELPER_PROOF),encoding='utf8')
            (root/'installer'/'UmaTrainerKR_Setup_0.25.0.exe').write_bytes(b'B'*10001)
            with self.assertRaises(ValueError):verify(root,'0.25.0')

    def test_workflow_manual_only(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text(encoding='utf8')
        self.assertIn('workflow_dispatch:',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)
        self.assertIn('permissions:\n  contents: read',workflow)
        self.assertIn('--self-check-report',workflow)
        self.assertIn('verify_windows_package_r25.py',workflow)
        self.assertIn('if: ${{ inputs.publish_release == true }}',workflow)
        self.assertIn('publish-portable:',workflow)
        self.assertIn('contents: write',workflow)

if __name__=='__main__':unittest.main()
