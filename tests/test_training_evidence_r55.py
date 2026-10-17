"""R55 offline tests: no live game, clicks, rewards or synthetic ML labels."""
from dataclasses import dataclass
import unittest
from pathlib import Path
from training_evidence_r55 import TrainingEvidenceCollector, TRAININGS


@dataclass(frozen=True)
class Reading:
    name: str
    gains: tuple[int, int, int, int, int]
    signature: str
    ocr_candidate: bool = True


SIG = 'a' * 64
RECT = (0, 0, 384, 700)
SIZE = (384, 700)


def frame(c, selected='스피드', signature=SIG, window=123, rect=RECT,
          readings=None, numbers=None, scene='훈련'):
    return c.observe(scene=scene, selected=selected, window_key=window,
                     window_rect=rect, image_size=SIZE,
                     turn_signature=signature,
                     preview_readings=readings if readings is not None else {},
                     numeric_candidates=numbers or {})


def r(name, nums=(9, 8, 7, 0, 0), sig=SIG):
    return Reading(name, nums, sig)


class TrainingEvidenceR55Tests(unittest.TestCase):
    def test_empty_does_not_recommend_or_click(self):
        result = frame(TrainingEvidenceCollector())
        self.assertEqual(result.stat_count, 0)
        self.assertFalse(result.decision_ready)
        self.assertFalse(result.game_input_allowed)
        self.assertFalse(result.ml_training_label)

    def test_all_five_stat_candidates_are_separate(self):
        c = TrainingEvidenceCollector()
        choices = {}
        for i, name in enumerate(TRAININGS):
            choices[name] = r(name, (10+i, 5, 0, 0, 0))
            out = frame(c, selected=name, readings=choices)
            self.assertEqual(out.stat_count, i+1)
        self.assertEqual(tuple(o.name for o in out.options), TRAININGS)
        self.assertEqual(out.options[-1].stat_total, 19)
        self.assertFalse(out.decision_ready)

    def test_extra_ocr_only_binds_current_selection(self):
        c=TrainingEvidenceCollector()
        readings={TRAININGS[0]:r(TRAININGS[0]),TRAININGS[1]:r(TRAININGS[1])}
        out=frame(c, selected=TRAININGS[0], readings=readings,
                  numbers={'실패율':23,'스킬 Pt 증가':15,'체력 소모':18,'스킬 Pt':9999})
        self.assertEqual(out.options[0].failure_rate,23)
        self.assertEqual(out.options[0].energy_cost,18)
        self.assertEqual(out.options[0].skill_point_gain,15)
        self.assertIsNone(out.options[1].failure_rate)
        self.assertIsNone(out.options[0].support_bond_gain)
        out=frame(c, selected=TRAININGS[1], readings=readings,
                  numbers={'실패율':4})
        self.assertEqual(out.options[0].failure_rate,23)
        self.assertEqual(out.options[1].failure_rate,4)

    def test_scope_changes_drop_old_training_data(self):
        c=TrainingEvidenceCollector()
        for kwargs in ({'signature':'b'*64}, {'window':124},
                       {'rect':(5,5,389,705)}, {'scene':'스킬'}):
            frame(c,readings={'스피드':r('스피드')})
            v=frame(c,readings={},**kwargs)
            self.assertEqual(v.stat_count,0)
            self.assertFalse(v.decision_ready)

    def test_stale_signature_and_invalid_gains_cannot_survive(self):
        c=TrainingEvidenceCollector()
        frame(c,readings={'스피드':r('스피드')})
        out=frame(c,readings={'스피드':r('스피드',sig='b'*64)})
        self.assertEqual(out.stat_count,0)
        out=frame(c,readings={'스피드':r('스피드',nums=(9,-1,0,0,0))})
        self.assertEqual(out.stat_count,0)

    def test_extra_field_not_fabricated_or_inferred_from_baseline(self):
        c=TrainingEvidenceCollector()
        out=frame(c,readings={'스피드':r('스피드')},
                  numbers={'체력':80,'스킬 Pt':800,'실패율':None})
        self.assertIsNone(out.options[0].energy_cost)
        self.assertIsNone(out.options[0].skill_point_gain)
        self.assertIsNone(out.options[0].failure_rate)

    def test_companion_wires_r48_and_r54_but_not_into_r49_clicks(self):
        src=(Path(__file__).resolve().parents[1]/"companion.py").read_text("utf-8")
        for anchor in ("TrainingEvidenceCollector()","training_evidence.observe(",
                       "training_evidence_info.set(", "turn_key=(_turn_signature(image), portrait_training)"):
            self.assertIn(anchor,src)


if __name__ == '__main__':
    unittest.main()
