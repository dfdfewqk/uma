"""R31 portable-first CI: real EXE selfchecks stay mandatory; installer is optional."""
from pathlib import Path
import json
import tempfile
import unittest
from package_selftest_r25 import inspect
from scripts.verify_windows_package_r25 import verify, PROGRAMS
from portable_update_r30 import CURRENT_VERSION
from scripts.validate_helper_r37 import REQUIRED as R37_HELPER_PROOF

ROOT = Path(__file__).resolve().parents[1]

class PortableFirstTests(unittest.TestCase):
    def build_mock_binary_reports(self, root: Path, *, corrupt=False):
        (root/'smoke-reports').mkdir()
        for name in PROGRAMS:
            (root/f'{name}.exe').write_bytes(b'EXE-mock' * 2000)
            report=inspect(name,root=ROOT,frozen=True)
            if corrupt and name=='UmaTrainerKR_Companion':
                report['result']='FAIL'
            (root/'smoke-reports'/f'{name}.json').write_text(json.dumps(report),encoding='utf-8')
            (root/'smoke-reports'/f'{name}_startup.json').write_text(json.dumps(report),encoding='utf-8')
        (root/'smoke-reports'/'UmaTrainerKR_gui.json').write_text(json.dumps({"schema":"uma_r36_windows_gui_synthetic_smoke_v1","result":"PASS","r6_reviewed_actions":2,"r34_panel_created":True,"r35_actions_rendered":2,"r35_stale_invalidation_checked":True,"r35_conflict_detected":True,"game_client_tested":False,"automatic_click_enabled":False,"synthetic_only":True,"gui_platform":"linux","frozen_binary":False}),encoding='utf-8')
        (root/'smoke-reports'/'UmaTrainerKR_helper.json').write_text(json.dumps(R37_HELPER_PROOF),encoding='utf-8')

    def test_portable_only_works_without_installer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            report=verify(root,CURRENT_VERSION,require_installer=False)
            self.assertEqual(len(report['files']),4)
            self.assertEqual(report['verification'],'real_windows_runner_exe_startup_portable_only')
            self.assertFalse(report['korean_game_tested'])
            self.assertFalse(report['automation_enabled'])

    def test_default_still_requires_installer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            with self.assertRaisesRegex(ValueError,'Installer missing'):
                verify(root,CURRENT_VERSION)

    def test_portable_only_still_rejects_bad_selfcheck(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root,corrupt=True)
            with self.assertRaisesRegex(ValueError,'self-check failed'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_portable_only_still_rejects_missing_exe(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            (root/'UmaTrainerKR_GameTest.exe').unlink()
            with self.assertRaisesRegex(ValueError,'missing or too small'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_empty_resource_checklist_does_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            path=root/'smoke-reports'/'UmaTrainerKR_Preflight.json'
            report=json.loads(path.read_text(encoding='utf-8'))
            report['required_resources']=[]
            path.write_text(json.dumps(report),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'resource checklist'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_forged_dependency_availability_does_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            path=root/'smoke-reports'/'UmaTrainerKR_Companion.json'
            report=json.loads(path.read_text(encoding='utf-8'))
            report['dependencies_available']['cv2']=False
            path.write_text(json.dumps(report),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'dependency or asset'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_missing_startup_report_blocks_portable_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            (root/'smoke-reports'/'UmaTrainerKR_Companion_startup.json').unlink()
            with self.assertRaisesRegex(ValueError,'startup import verification did not run'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_false_startup_report_blocks_portable_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            path=root/'smoke-reports'/'UmaTrainerKR_Preflight_startup.json'
            info=json.loads(path.read_text(encoding='utf-8'))
            info['result']='FAIL'
            path.write_text(json.dumps(info),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'startup import verification failed'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_missing_real_gui_report_blocks_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            (root/'smoke-reports'/'UmaTrainerKR_gui.json').unlink()
            with self.assertRaisesRegex(ValueError,'source Tk GUI smoke report missing'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_fake_gui_report_blocks_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            p=root/'smoke-reports'/'UmaTrainerKR_gui.json'
            data=json.loads(p.read_text(encoding='utf-8'))
            data['r35_conflict_detected']=False
            p.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'source Tk GUI smoke report invalid'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_missing_helper_gui_report_blocks_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            (root/'smoke-reports'/'UmaTrainerKR_helper.json').unlink()
            with self.assertRaisesRegex(ValueError,'R37 click-only helper GUI report missing'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_forged_helper_gui_proof_blocks_release(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.build_mock_binary_reports(root)
            path=root/'smoke-reports'/'UmaTrainerKR_helper.json'
            bad=dict(R37_HELPER_PROOF)
            bad['typeable_fields_in_helper']=1
            path.write_text(json.dumps(bad),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'R37 helper GUI report invalid'):
                verify(root,CURRENT_VERSION,require_installer=False)

    def test_version_consistency(self):
        self.assertIn('Version: '+CURRENT_VERSION,(ROOT/'VERSION.txt').read_text('utf-8'))
        self.assertIn('"'+CURRENT_VERSION+'"',(ROOT/'UmaTrainerKR_Setup.iss').read_text('utf-8'))

    def test_manual_workflow_portable_first(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text('utf-8')
        self.assertIn('build_installer:',workflow)
        self.assertIn("if: ${{ inputs.build_installer == true }}",workflow)
        self.assertIn('verify_windows_package_r25.py dist $version --portable-only',workflow)
        self.assertIn('name: UmaTrainerKR-R37-Windows-Verified',workflow)
        self.assertIn('if: ${{ inputs.publish_release == true }}',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)

if __name__=='__main__':unittest.main()
