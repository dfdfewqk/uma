"""R1 new research pack must stay auditable, without made-up supervised examples."""
import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'research'/'jp_post_patch_2025'))
from validate_research import verify
class ResearchTests(unittest.TestCase):
    def test_research_tables_and_evidence_traceable(self):
        data=verify()
        self.assertGreaterEqual(data['sources'],20)
        self.assertGreaterEqual(data['evidence_items'],20)
        self.assertEqual(data['verified_frame_or_turn_annotations'],0)
