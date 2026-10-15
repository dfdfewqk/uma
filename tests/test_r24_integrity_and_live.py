import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capture_integrity_r24 import read_pinned_image, ChangedCaptureError
from live_state_r24 import FreshnessGate, rectangles_overlap
from offline_replay_r23 import create_manifest, load_manifest, replay, file_sha256, ReplayError

ROOT=Path(__file__).resolve().parent.parent
EX=ROOT/'examples'


class TestR24CaptureEvidence(unittest.TestCase):
    def bundle(self, folder):
        roi=folder/'roi.json';roi.write_bytes((EX/'r22_mock_roi.json').read_bytes())
        image=folder/'image.png';image.write_bytes((EX/'r22_mock_1.png').read_bytes())
        manifest=create_manifest(folder,source_type='local_unverified',turn='주니어 3턴',
                                 roi_profile='roi.json', captures={'스피드':'image.png'})
        return manifest,roi,image

    def test_new_manifest_pins_roi(self):
        with tempfile.TemporaryDirectory() as td:
            path,roi,img=self.bundle(Path(td))
            doc=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(doc['roi_sha256'],file_sha256(roi))
            self.assertEqual(load_manifest(path)['roi_sha256'],doc['roi_sha256'])

    def test_roi_tamper_between_sessions_fails(self):
        with tempfile.TemporaryDirectory() as td:
            path,roi,_=self.bundle(Path(td))
            before=roi.read_bytes()
            roi.write_bytes(before+b' ')
            with self.assertRaisesRegex(ReplayError,'OCR 영역 설정이 바뀌'):
                load_manifest(path)

    def test_capture_replaced_after_first_validation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path,roi,image=self.bundle(Path(td))
            doc=load_manifest(path)
            image.write_bytes((EX/'r22_mock_2.png').read_bytes())
            with self.assertRaisesRegex(ChangedCaptureError,'바뀌'):
                read_pinned_image(image,doc['captures'][0][2])
            with patch('offline_replay_r23.load_manifest',return_value=doc):
                result=replay(path,use_ocr=False)
            self.assertEqual(len(result.findings[0].missing),7)
            self.assertEqual(result.eligible_ml_labels,0)

    def test_manifest_mutation_mid_review_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            path,_,_=self.bundle(Path(td))
            doc=load_manifest(path)
            path.write_text(path.read_text(encoding='utf8')+' ',encoding='utf8')
            with patch('offline_replay_r23.load_manifest',return_value=doc):
                with self.assertRaisesRegex(ReplayError,'목록'):
                    replay(path,use_ocr=False)

    def test_roi_mutation_mid_review_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            path,roi,_=self.bundle(Path(td))
            doc=load_manifest(path)
            roi.write_text(roi.read_text(encoding='utf8')+' ',encoding='utf8')
            with patch('offline_replay_r23.load_manifest',return_value=doc):
                with self.assertRaisesRegex(ReplayError,'OCR 영역'):
                    replay(path,use_ocr=False)

    def test_no_leakage_of_local_file_paths(self):
        with tempfile.TemporaryDirectory() as td:
            path,_,_=self.bundle(Path(td))
            report=replay(path,use_ocr=False)
            self.assertNotIn(td,json.dumps(report.public_json(),ensure_ascii=False))

    def test_rejects_invalid_bytes_even_if_digest_matches(self):
        with tempfile.TemporaryDirectory() as td:
            name=Path(td)/'still.png';name.write_bytes(b'not an image')
            with self.assertRaisesRegex(ChangedCaptureError,'이미지'):
                read_pinned_image(name,file_sha256(name))


class TestR24Freshness(unittest.TestCase):
    def test_old_window_frame_cannot_update_new_window(self):
        gate=FreshnessGate()
        self.assertTrue(gate.update(10,(100,50,900,650)))
        stale=gate.ticket()
        self.assertFalse(gate.update(10,(100,50,900,650)))
        self.assertTrue(gate.accepts(stale,10))
        self.assertTrue(gate.update(10,(110,50,910,650)))
        self.assertFalse(gate.accepts(stale,10))
        current=gate.ticket()
        self.assertTrue(gate.update(11,(100,50,900,650)))
        self.assertFalse(gate.accepts(current,11))
        self.assertTrue(gate.update(None))
        self.assertFalse(gate.accepts(gate.ticket(),11))

    def test_non_training_scene_cannot_reuse_numeric_rois(self):
        g=FreshnessGate()
        values={'스피드':1234,'체력':62}
        self.assertEqual(g.safe_values('훈련',values),values)
        for screen in (None,'이벤트','스킬','시설'):
            self.assertEqual(g.safe_values(screen,values),{})

    def test_panel_overlapping_game_is_rejected(self):
        game=(50,50,1050,800)
        self.assertTrue(rectangles_overlap(game,(900,80,1244,870)))
        self.assertFalse(rectangles_overlap(game,(1050,50,1394,850)))
        self.assertFalse(rectangles_overlap(game,(-294,50,50,850)))
        with self.assertRaises(ValueError):
            rectangles_overlap(game,(100,100,100,200))


if __name__ == '__main__':
    unittest.main()
