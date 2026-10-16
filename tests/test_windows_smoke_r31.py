"""Static safety contract checks for the bounded Windows GUI-EXE smoke tests."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class WindowsSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text('utf-8')
        cls.helper=(ROOT/'scripts/windows_smoke_r31.ps1').read_text('utf-8')

    def test_exe_processes_are_bounded_and_killed_on_timeout(self):
        self.assertIn('WaitForExit($Timeout * 1000)',self.helper)
        self.assertIn('$process.Kill($true)',self.helper)
        self.assertIn('TIMEOUT ${Label}',self.helper)
        self.assertIn('ExitCode -ne 0',self.helper)
        self.assertIn('Write-Host "[UMA smoke] START',self.helper)
        self.assertIn('Write-Host "[UMA smoke] PASS',self.helper)
        self.assertNotIn('Start-Process -Wait',self.helper)

    def test_all_modes_run_in_one_common_helper(self):
        for mode in ('built','installed','install','uninstall'):
            with self.subTest(mode=mode):
                self.assertIn(f"-Mode {mode}",self.workflow)
        for app in ('UmaTrainerKR','UmaTrainerKR_Companion','UmaTrainerKR_GameTest','UmaTrainerKR_Preflight'):
            self.assertIn(app,self.helper)
        self.assertIn('--first-run-report',self.helper)
        self.assertIn('--self-check-report',self.helper)

    def test_reports_cannot_be_faked_or_reused(self):
        self.assertIn('Refusing stale smoke report',self.helper)
        self.assertIn("$result.result -ne 'PASS'",self.helper)
        self.assertIn('$result.frozen_binary -ne $true',self.helper)
        self.assertIn('$result.game_client_tested -ne $false',self.helper)
        self.assertIn('$result.automatic_click_enabled -ne $false',self.helper)
        self.assertIn('uma_r26_windows_first_run_v1',self.helper)

    def test_diagnostic_bootstrap_precedes_gui_imports(self):
        for path, profile in (
            ('app.py', 'UmaTrainerKR'),
            ('companion.py', 'UmaTrainerKR_Companion'),
            ('live_test_ui_r22.py', 'UmaTrainerKR_GameTest'),
            ('offline_replay_ui_r23.py', 'UmaTrainerKR_Preflight'),
        ):
            with self.subTest(path=path):
                source=(ROOT/path).read_text('utf-8')
                self.assertIn("_uma_early_selfcheck('"+profile+"')",source)
                self.assertLess(source.index('_uma_early_selfcheck('),
                                source.index('import tkinter as tk'))
        companion=(ROOT/'companion.py').read_text('utf-8')
        self.assertLess(companion.index('_uma_early_first_run()'),
                        companion.index('import tkinter as tk'))

    def test_failed_package_uploads_only_diagnostics(self):
        self.assertIn('Upload failure diagnostics (no binaries)',self.workflow)
        self.assertIn('if: ${{ failure() }}',self.workflow)
        self.assertIn('build/**/warn-*.txt',self.workflow)

    def test_workflow_never_publishes_failed_build(self):
        self.assertIn('needs: windows-package',self.workflow)
        self.assertIn('if: ${{ inputs.publish_release == true }}',self.workflow)
        self.assertIn('workflow_dispatch:',self.workflow)
        self.assertNotIn('  push:',self.workflow)
        self.assertIn('timeout-minutes:',self.workflow)
        # Distinct Windows-running smoke step must finish before ZIP creation.
        self.assertLess(self.workflow.index('Bounded Windows EXE smoke checks'),
                        self.workflow.index('Create and verify portable ZIP'))

if __name__=='__main__':unittest.main()
