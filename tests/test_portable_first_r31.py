"""R31 portable-first CI: real EXE selfchecks stay mandatory; installer is optional."""
from pathlib import Path
import json
import tempfile
import unittest
from package_selftest_r25 import inspect
from scripts.verify_windows_package_r25 import verify, PROGRAMS
from portable_update_r30 import CURRENT_VERSION

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

    def test_version_consistency(self):
        self.assertIn('Version: '+CURRENT_VERSION,(ROOT/'VERSION.txt').read_text('utf-8'))
        self.assertIn('"'+CURRENT_VERSION+'"',(ROOT/'UmaTrainerKR_Setup.iss').read_text('utf-8'))

    def test_manual_workflow_portable_first(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text('utf-8')
        self.assertIn('build_installer:',workflow)
        self.assertIn("if: ${{ inputs.build_installer == true }}",workflow)
        self.assertIn('verify_windows_package_r25.py dist $version --portable-only',workflow)
        self.assertIn('name: UmaTrainerKR-R31-Windows-Verified',workflow)
        self.assertIn('if: ${{ inputs.publish_release == true }}',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)

if __name__=='__main__':unittest.main()
