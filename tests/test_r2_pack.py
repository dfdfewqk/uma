from pathlib import Path
import csv,json,unittest
class R2PackTest(unittest.TestCase):
    def test_pack_zero_real_rows_and_auditable_queue(self):
        root=Path(__file__).resolve().parents[1]
        rev=root/'research/video_reviews'
        with (rev/'verified_turns.csv').open(encoding='utf-8-sig') as f:
            self.assertEqual(len(list(csv.DictReader(f))),0)
        with (rev/'review_queue.csv').open(encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows),3)
        self.assertTrue(all(r['source_url'].startswith('https://') for r in rows))
        manifest=json.loads((rev/'R2_manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['ml_model_trained'])
        self.assertEqual(manifest['human_verified_turns_included'],0)
