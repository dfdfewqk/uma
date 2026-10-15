import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screen_r4 import (FIELDS, Region, ScreenProfile, ScreenError, save_profile, read_profile,
                       read_regions, load_image, parse_numeric, save_review,
                       tesseract_executable, ReadResult)

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples'/'synthetic_r4.png'
PROFILE=ROOT/'examples'/'synthetic_roi.json'

class ScreenR4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.profile=read_profile(PROFILE)

    def test_parse_strict_no_guessing(self):
        self.assertEqual(parse_numeric('1,200','스피드'),1200)
        self.assertEqual(parse_numeric('45/100','체력'),45)
        for text in ['12O0','300+20','12.5','-15','20/40','12 200','inf','99999']:
            self.assertIsNone(parse_numeric(text,'스피드'),text)
        self.assertIsNone(parse_numeric('105','체력'))
        self.assertIsNone(parse_numeric('25/100','스태미나'))
        self.assertEqual(parse_numeric('0','섬 티켓'),0)
        with self.assertRaises(ScreenError):parse_numeric('55','코인')

    def test_region_bounds_and_pixels(self):
        reg=Region('체력',.101,.201,.359,.481)
        self.assertEqual(reg.pixel_box(1000,1000),(101,201,359,481))
        for coords in [(-.1,0,.5,.5),(0,0,1.1,1),(0.3,0.3,.2,.4),(0,0,.001,.1)]:
            with self.assertRaises(ScreenError):Region('체력',*coords).validate()
        with self.assertRaises(ScreenError):Region('암호',0,0,.5,.5).validate()
        with self.assertRaises(ScreenError):Region('파워',0,0,float('nan'),.6).validate()

    def test_profile_round_trip_and_scenario_guard(self):
        target=self.folder/'regions.json'
        save_profile(self.profile,target)
        restored=read_profile(target)
        self.assertEqual(self.profile.regions,restored.regions)
        self.assertTrue(restored.matches_image(load_image(EXAMPLE)))
        with self.assertRaises(ScreenError):
            ScreenProfile('x','future',1.4,restored.regions).validate()
        target.write_text('null',encoding='utf-8')
        with self.assertRaises(ScreenError):read_profile(target)

    def test_invalid_image_and_ratio_fail_closed(self):
        target=self.folder/'not_image.png'
        target.write_bytes(b'Not a PNG')
        with self.assertRaises(ScreenError):load_image(target)
        with self.assertRaises(ScreenError):load_image(self.folder/'no.jpg')
        p=self.profile
        p.aspect_ratio=.75
        with self.assertRaises(ScreenError):read_regions(EXAMPLE,p)

    def test_no_ocr_engine_no_fabricated_readings(self):
        with patch('screen_r4.tesseract_executable',return_value=None):
            with self.assertRaisesRegex(ScreenError,'Tesseract'):
                read_regions(EXAMPLE,self.profile)

    def test_refuse_invisible_crop_and_unconfirmed_fields(self):
        p=self.profile
        p.regions.pop('발전 Pt')
        with patch('screen_r4.tesseract_executable',return_value='/stub/tesseract'):
            with patch('screen_r4._recognize_one',return_value=('12O0',99)):
                rows=read_regions(EXAMPLE,p)
        self.assertEqual(len(rows),len(FIELDS))
        self.assertIsNone(rows[0].value)
        self.assertIn('불확실',rows[0].status)
        self.assertEqual(rows[-1].status,'영역 미지정')

    def test_confidence_gate_and_zero(self):
        with patch('screen_r4.tesseract_executable',return_value='/stub/tesseract'):
            with patch('screen_r4._recognize_one',return_value=('0',64)):
                rows=read_regions(EXAMPLE,self.profile)
        self.assertEqual(rows[0].value,0)
        self.assertIn('불확실',rows[0].status)

    def test_review_requires_explicit_values_and_audits_hash(self):
        p=self.profile
        target=self.folder/'review.json'
        doc=save_review(EXAMPLE,p,[],{'스피드':1200,'체력':75},target,manual=True)
        self.assertEqual(doc['verification'],'user_manually_confirmed')
        self.assertTrue(doc['not_ml_training_label'])
        self.assertEqual(doc['confirmed_values']['체력'],75)
        self.assertEqual(len(doc['source_sha256']),64)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['confirmed_values']['스피드'],1200)
        with self.assertRaises(ScreenError):save_review(EXAMPLE,p,[],{'스피드':'1200'},target)
        with self.assertRaises(ScreenError):save_review(EXAMPLE,p,[],{'스피드':7000},target)
        with self.assertRaises(ScreenError):save_review(EXAMPLE,p,[],{'미지정':12},target)

    @unittest.skipUnless(tesseract_executable(), 'Tesseract not installed on runner')
    def test_optional_real_tesseract_on_synthetic_image_only(self):
        rows=read_regions(EXAMPLE,self.profile)
        expected={'스피드':1200,'스태미나':850,'파워':1015,'근성':700,
                  '지능':975,'체력':75,'스킬 Pt':2400,'섬 티켓':2,'발전 Pt':350}
        self.assertEqual({r.field:r.value for r in rows},expected)
        self.assertTrue(all(r.confidence >= 65 for r in rows))


if __name__=='__main__':unittest.main()
