"""R33 study provenance and untrained-model boundary regression."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from research.r33_high_score_island.validate_study import validate

PACK=Path(__file__).resolve().parents[1]/"research"/"r33_high_score_island"/"study_pack.json"

class R33HighScoreStudyTests(unittest.TestCase):
    def setUp(self):
        self.pack=json.loads(PACK.read_text(encoding="utf-8"))
    def _mutated(self,change):
        data=json.loads(json.dumps(self.pack))
        change(data)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"study.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(path)
    def test_current_study_is_research_only(self):
        self.assertEqual(validate()["conditional_hypotheses"],9)
        self.assertEqual(self.pack["quality"]["ml_trainable_labels"],0)
    def test_sources_cannot_be_promoted_to_frame_reviewed(self):
        self._mutated(lambda d:d["source_records"][0].update(verified_frames=1))
    def test_manual_claim_cannot_become_model_weights(self):
        self._mutated(lambda d:d["conditional_hypotheses"][0].update(engine_action="apply"))
    def test_training_status_cannot_be_forged(self):
        self._mutated(lambda d:d["quality"].update(training_model_fitted=True))
    def test_source_references_must_be_present(self):
        self._mutated(lambda d:d["conditional_hypotheses"][0].update(source_ids=["missing"]))
    def test_evaluation_and_competition_targets_are_separated(self):
        self.assertEqual({p["target"] for p in self.pack["conditional_hypotheses"]},{"score","competition"})
        self._mutated(lambda d:d["conditional_hypotheses"][0].update(target="win_probability"))

if __name__=="__main__":
    unittest.main()
