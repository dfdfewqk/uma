"""R53 source-level fail-closed scene agreement. Synthetic only."""
import unittest
from pathlib import Path
from scene_fusion_r53 import StableScreenFusion,STAGE_SCENES

class FusionR53(unittest.TestCase):
    def test_registered_stage_needs_two_frames(self):
        f=StableScreenFusion()
        self.assertIsNone(f.observe(None,"tp",None).scene)
        out=f.observe(None,"tp",None)
        self.assertEqual(out.scene,"TP 회복")
        self.assertFalse(out.action_authorized)

    def test_consistent_r20_and_r50(self):
        f=StableScreenFusion()
        f.observe("스킬","skill",None)
        self.assertEqual(f.observe("스킬","skill",None).scene,"스킬")

    def test_conflict_invalidates_previous(self):
        f=StableScreenFusion()
        f.observe(None,"tp",None);f.observe(None,"tp",None)
        self.assertEqual(f.observe("훈련","tp",None).status,"conflict")
        self.assertIsNone(f.observe(None,"tp",None).scene)

    def test_training_candidate_is_provisional(self):
        f=StableScreenFusion()
        self.assertIsNone(f.observe(None,None,"스피드").scene)
        out=f.observe(None,None,"지능")
        self.assertEqual(out.scene,"훈련")
        self.assertTrue(out.provisional)
        self.assertFalse(out.action_authorized)

    def test_unknown_and_popup_clear_previous(self):
        f=StableScreenFusion()
        f.observe("훈련",None,None);f.observe("훈련",None,None)
        self.assertEqual(f.observe("팝업/기타",None,"스피드").status,"conflict")
        self.assertEqual(f.observe(None,None,None).status,"unknown")
        self.assertIsNone(f.observe("훈련",None,None).scene)

    def test_registered_stage_never_authorizes_game_input(self):
        for stage in STAGE_SCENES:
            f=StableScreenFusion()
            f.observe(None,stage,None)
            self.assertFalse(f.observe(None,stage,None).action_authorized)

    def test_companion_has_conflict_gate_and_registration(self):
        src=(Path(__file__).resolve().parents[1]/"companion.py").read_text("utf-8")
        for s in ("StableScreenFusion","self.scene_fusion.observe(",
                  "if screen.status == 'conflict':","passive_scene_ui_r53"):
            self.assertIn(s,src)
