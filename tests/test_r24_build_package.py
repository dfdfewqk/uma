import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestR24WindowsBuildInputs(unittest.TestCase):
    def test_manual_build_and_resources_present(self):
        build=(ROOT/'Windows_EXE_빌드.bat').read_text(encoding='utf-8')
        installer=(ROOT/'UmaTrainerKR_Setup.iss').read_text(encoding='utf-8')
        for name in ('UmaTrainerKR', 'UmaTrainerKR_Companion','UmaTrainerKR_GameTest','UmaTrainerKR_Preflight'):
            with self.subTest(exe=name):
                self.assertIn(name+'.exe',installer)
                self.assertIn('--name '+name+' ',build)
        for name in ('examples/r23_demo_manifest.json','examples/r22_mock_roi.json',
                     'examples/r22_mock_1.png','scenario_policies/island_post_patch_v1.json',
                     'capture_integrity_r24.py','live_state_r24.py'):
            with self.subTest(file=name):
                self.assertTrue((ROOT/name).is_file())

    def test_all_packagers_include_island_policy_in_every_exe(self):
        root=ROOT
        workflow=(root/'.github/workflows/windows-exe.yml').read_text('utf-8')
        full=(root/'Windows_EXE_빌드.bat').read_text('utf-8')
        companion=(root/'Windows_실시간도우미_EXE_수동빌드.bat').read_text('utf-8')
        policy=r'scenario_policies\island_post_patch_v1.json;scenario_policies'
        self.assertEqual(workflow.count(policy),4)
        self.assertEqual(full.count(policy),4)
        self.assertEqual(companion.count(policy),3)

    def test_manual_workflow_and_current_version(self):
        workflow=(ROOT/'.github/workflows/windows-exe.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:',workflow)
        self.assertNotIn('  push:',workflow)
        self.assertNotIn('  schedule:',workflow)
        self.assertIn((ROOT/'VERSION.txt').read_text(encoding='utf-8').split('Version:')[1].strip(),
                      (ROOT/'UmaTrainerKR_Setup.iss').read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
