"""R26 regression tests for privacy-minimal readiness and packaged entrypoint."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from preflight_r23 import PreflightStatus
from runtime_probe_r26 import classify, report_from, maybe_run_cli, SCHEMA

ROOT = Path(__file__).resolve().parents[1]

def state(**updates):
    args = dict(platform_windows=True,screenshot_module_available=True,
                image_matcher_available=True,numeric_ocr_available=True,
                saved_numeric_rois_present=True,saved_scene_profiles_present=True,
                saved_button_templates_present=True,detected_game_window=True)
    args.update(updates)
    return PreflightStatus(**args)

class ReadinessTests(unittest.TestCase):
    def test_all_present_does_not_claim_game_verification(self):
        report=report_from(state())
        self.assertEqual(report['schema'],SCHEMA)
        self.assertEqual(report['readiness'],'READY_FOR_GAME_VALIDATION')
        self.assertFalse(report['real_game_ocr_verified'])
        self.assertFalse(report['automatic_clicks_enabled'])
        self.assertFalse(report['installer_compatibility_verified'])

    def test_missing_os(self):
        self.assertEqual(classify(state(platform_windows=False)),'ENVIRONMENT_INCOMPLETE')

    def test_missing_screenshot_backend(self):
        self.assertEqual(classify(state(screenshot_module_available=False)),'ENVIRONMENT_INCOMPLETE')

    def test_missing_template_matching(self):
        self.assertEqual(classify(state(image_matcher_available=False)),'ENVIRONMENT_INCOMPLETE')

    def test_ocr_unconfigured(self):
        self.assertEqual(classify(state(numeric_ocr_available=False)),'OCR_NOT_CONFIGURED')

    def test_game_not_running(self):
        self.assertEqual(classify(state(detected_game_window=False)),'GAME_NOT_DETECTED')

    def test_missing_screen_calibration(self):
        self.assertEqual(classify(state(saved_scene_profiles_present=False)),'CALIBRATION_REQUIRED')

    def test_missing_roi_and_template(self):
        self.assertEqual(classify(state(saved_numeric_rois_present=False,saved_button_templates_present=False)),'CALIBRATION_REQUIRED')

    def test_first_run_cli_is_explicit(self):
        self.assertIs(maybe_run_cli([]),False)
        with self.assertRaises(SystemExit) as ctx:maybe_run_cli(['--first-run-report'])
        self.assertEqual(ctx.exception.code,2)

    def test_cli_report_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td, patch('runtime_probe_r26.inspect_local_environment',return_value=state()):
            p=Path(td)/'first-run.json'
            with self.assertRaises(SystemExit) as ctx:maybe_run_cli(['--first-run-report',str(p)])
            self.assertEqual(ctx.exception.code,0)
            self.assertEqual(json.loads(p.read_text('utf-8'))['readiness'],'READY_FOR_GAME_VALIDATION')
            with self.assertRaises(SystemExit) as ctx:maybe_run_cli(['--first-run-report',str(p)])
            self.assertEqual(ctx.exception.code,2)

    def test_no_private_details_in_report(self):
        blob=json.dumps(report_from(state()),ensure_ascii=False).lower()
        for item in ['window_title','absolute_path','user_name','screenshot','account_id','game_process_id']:
            self.assertNotIn('"'+item+'":',blob)

    def test_ci_build_is_manual_and_includes_install_verification(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text('utf-8')
        self.assertIn('workflow_dispatch:',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)
        smoke=(ROOT/'scripts/windows_smoke_r31.ps1').read_text('utf-8')
        self.assertIn('uma_r26_windows_first_run_v1',smoke)
        self.assertIn('Get-FileHash -Algorithm SHA256',workflow)
        self.assertIn('installed_',smoke)
        self.assertIn('first_run_no_game.json',smoke)
        self.assertIn('-Mode installed',workflow)
        self.assertIn('Uninstall left binary behind',workflow)
        self.assertIn('if: ${{ inputs.publish_release == true }}',workflow)
        self.assertIn('publish-portable:',workflow)
        self.assertIn('contents: write',workflow)

if __name__=='__main__':unittest.main()
