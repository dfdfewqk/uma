"""R5 regression tests. Synthetic fixtures, not real game measurements."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uma_core import RunProfile, TurnState, STATS
from screen_r4 import tesseract_executable
from training_r5 import (TRAINING_CHOICES, FIELDS, MANDATORY, OptionEvidence,
                         EvidenceError, compare_options, parse_value,
                         export_evidence, ocr_candidate)

ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGE = ROOT/'examples'/'synthetic_r4.png'


def filled(name):
    record=OptionEvidence(name)
    for i,field in enumerate(MANDATORY):
        if field=='체력 변화':
            v='-12'
        elif field=='실패 확률':
            v='0'
        else:
            v='42' if field.endswith('상승') else '23'
        record.confirm(field,v)
    if name=='섬 트레이닝':
        record.confirm('우정 발동 시설 수','3')
    return record


class R5Tests(unittest.TestCase):
    def setUp(self):
        self.profile = RunProfile()
        self.state = TurnState(energy=82, island_tickets=0)
        self.good = {name:filled(name) for name in TRAINING_CHOICES}

    def test_numeric_parsing_strict_and_signs(self):
        self.assertEqual(parse_value('스피드 상승','0'),0)
        self.assertEqual(parse_value('스킬 Pt 상승','1,025'),1025)
        self.assertEqual(parse_value('체력 변화','-20'),-20)
        self.assertEqual(parse_value('실패 확률','25%',ocr=True),25)
        for val in ('2O','1.5','-5','999999','', '1+2'):
            with self.assertRaises(EvidenceError): parse_value('파워 상승',val)
        with self.assertRaises(EvidenceError): parse_value('실패 확률','101')
        with self.assertRaises(EvidenceError): parse_value('체력 변화','-101')
        with self.assertRaises(EvidenceError): parse_value('bad','2')

    def test_zero_requires_confirmation(self):
        rec=OptionEvidence('스피드')
        self.assertFalse(rec.complete())
        for field in MANDATORY:
            rec.confirm(field,'0')
        self.assertTrue(rec.complete())
        self.assertTrue(rec.to_action().observed)
        self.assertEqual(rec.to_action().gains['스피드'],0)

    def test_unverified_fields_are_never_assumed_zero(self):
        rec=OptionEvidence('지능')
        rec.confirm('스피드 상승','50')
        self.assertFalse(rec.complete())
        with self.assertRaises(EvidenceError):rec.to_action()
        self.good['지능']=rec
        result=compare_options(self.profile,self.state,self.good)
        self.assertEqual(result.status,'추천 보류')
        self.assertEqual(result.ranked,[])
        self.assertIn('스킬 Pt 상승',result.missing['지능'])

    def test_success_when_all_five_training_options_checked(self):
        result=compare_options(self.profile,self.state,self.good)
        self.assertIn('비교 가능',result.status)
        self.assertEqual(len(result.ranked),5)
        self.assertNotIn('섬 트레이닝',[r.name for r in result.ranked])
        self.assertIn('휴식·레이스',result.explanation)

    def test_ticket_requires_island_option(self):
        self.state.island_tickets=1
        self.good['섬 트레이닝'].invalidate('우정 발동 시설 수')
        result=compare_options(self.profile,self.state,self.good)
        self.assertEqual(result.status,'추천 보류')
        self.assertEqual(result.missing['섬 트레이닝'],['우정 발동 시설 수'])
        self.good['섬 트레이닝'].confirm('우정 발동 시설 수','3')
        result=compare_options(self.profile,self.state,self.good)
        self.assertIn('비교 가능',result.status)
        self.assertEqual(len(result.ranked),6)

    def test_option_identity_mismatch_blocks_comparison(self):
        self.good['지능']=OptionEvidence('파워')
        self.assertEqual(compare_options(self.profile,self.state,self.good).status,'추천 보류')

    def test_invalid_energy_excludes_infeasible_training(self):
        self.state.energy=5
        result=compare_options(self.profile,self.state,self.good)
        self.assertEqual(result.status,'추천 보류')  # all known choices impossible

    def test_change_requires_new_review(self):
        self.good['스피드'].invalidate('스피드 상승')
        self.assertEqual(compare_options(self.profile,self.state,self.good).status,'추천 보류')
        self.good['스피드'].confirm('스피드 상승','0')
        self.assertIn('비교 가능',compare_options(self.profile,self.state,self.good).status)

    def test_only_known_valid_provenance(self):
        with self.assertRaises(EvidenceError):self.good['파워'].confirm('체력 변화','-12','unreviewed_ocr')
        with self.assertRaises(EvidenceError):self.good['파워'].confirm('secret','5')
        self.good['파워'].confirm('체력 변화','-12','ocr_reviewed')
        self.assertEqual(self.good['파워'].sources['체력 변화'],'ocr_reviewed')

    def test_screenshot_hash_and_reset(self):
        rec=self.good['파워']
        self.assertTrue(rec.complete())
        fingerprint=rec.attach_screenshot(TEST_IMAGE)
        self.assertEqual(len(fingerprint),64)
        self.assertEqual(rec.confirmed,set())
        self.assertFalse(rec.complete())
        self.assertEqual(rec.screenshot_sha256,fingerprint)

    def test_bad_image_cannot_clear_old_evidence(self):
        rec=self.good['파워']
        with tempfile.TemporaryDirectory() as td:
            bad=Path(td)/'broken.png'
            bad.write_bytes(b'not-png')
            with self.assertRaises(ValueError):rec.attach_screenshot(bad)
        self.assertTrue(rec.complete())

    def test_export_no_fake_ml_labels_and_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'sub'/'review.json'
            export_evidence(path,self.good,self.profile,self.state)
            doc=json.loads(path.read_text(encoding='utf8'))
            self.assertTrue(doc['not_ml_training_label'])
            self.assertEqual(doc['options']['스피드']['confirmed'],sorted(self.good['스피드'].confirmed))
            self.assertIn('event',doc)

    def test_ocr_is_not_auto_confirmed(self):
        with patch('training_r5.tesseract_executable',return_value='/mock/tesseract'):
            with patch('training_r5._recognize_one',return_value=('75',91)):
                result=ocr_candidate(TEST_IMAGE,(.1,.1,.3,.3),'스피드 상승')
        self.assertEqual(result['candidate'],75)
        self.assertIn('검수 필요',result['status'])
        self.assertEqual(self.good['스피드'].values['스피드 상승'],42)

    def test_ocr_rejects_bad_confidence_and_bad_numbers(self):
        with patch('training_r5.tesseract_executable',return_value='/mock/tesseract'):
            with patch('training_r5._recognize_one',return_value=('75',23)):
                result=ocr_candidate(TEST_IMAGE,(.1,.1,.3,.3),'스피드 상승')
        self.assertIsNone(result['candidate'])
        with patch('training_r5.tesseract_executable',return_value='/mock/tesseract'):
            with patch('training_r5._recognize_one',return_value=('7O',99)):
                result=ocr_candidate(TEST_IMAGE,(.1,.1,.3,.3),'스피드 상승')
        self.assertIsNone(result['candidate'])
        with self.assertRaises(EvidenceError):ocr_candidate(TEST_IMAGE,(0,0,1,1),'체력 변화')
        with self.assertRaises(EvidenceError):ocr_candidate(TEST_IMAGE,(0,0,1.5,1),'스피드 상승')

    @unittest.skipUnless(tesseract_executable(), 'Tesseract not installed')
    def test_synthetic_local_ocr_pipeline_requires_review(self):
        roi=json.loads((ROOT/'examples'/'synthetic_roi.json').read_text(encoding='utf-8'))['regions']['스킬 Pt']
        coords=tuple(roi[k] for k in ('x1','y1','x2','y2'))
        reading=ocr_candidate(TEST_IMAGE,coords,'스킬 Pt 상승')
        self.assertEqual(reading['candidate'],2400)
        self.assertEqual(reading['status'],'사용자 검수 필요')
        self.assertEqual(self.good['스피드'].values['스킬 Pt 상승'],42)

    def test_unavailable_tesseract_informative(self):
        with patch('training_r5.tesseract_executable',return_value=None):
            with self.assertRaisesRegex(EvidenceError,'Tesseract'):
                ocr_candidate(TEST_IMAGE,(.1,.1,.3,.3),'스피드 상승')


if __name__=='__main__': unittest.main()
