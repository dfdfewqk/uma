import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from button_detection_r21 import (make_pattern, find_button, StableButtons,
                                   save_patterns, load_patterns, DetectionError, ButtonHit, recommended_training_marks)


def fake_game(offset=0, duplicate=False, blank=False, size=(800,1100)):
    img=Image.new('RGB', (800,1100),'#152d52')
    if not blank:
        d=ImageDraw.Draw(img)
        def draw_icon(x,y):
            d.rounded_rectangle((x-44,y-30,x+44,y+30),radius=12,fill='#e2bd60',outline='#fafafa',width=3)
            d.rectangle((x-27,y-15,x+27,y+15),fill='#164677',outline='#f3c962',width=3)
            for i in range(4):
                d.line((x-20,y-9+i*5,x+15-i*3,y-9+i*5),fill='#faf4e5',width=2)
            d.ellipse((x+17,y-22,x+28,y-11),fill='#e22c68')
        draw_icon(200+offset,850)
        if duplicate:draw_icon(280+offset,850)
    if size!=(800,1100):img=img.resize(size,Image.Resampling.BILINEAR)
    return img


class Detection(unittest.TestCase):
    def setUp(self):
        self.original=fake_game()
        self.pat=make_pattern(self.original,'스피드',200/800,850/1100)
    def test_localization_on_original(self):
        hit=find_button(self.original,self.pat)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.x,.25,delta=.008)
        self.assertGreater(hit.score,.94)
    def test_relocates_after_translation(self):
        hit=find_button(fake_game(offset=35),self.pat)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.x,235/800,delta=.008)
    def test_window_proportional_resize(self):
        hit=find_button(fake_game(size=(640,880)),self.pat)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.x,.25,delta=.008)
    def test_different_aspect_ratio_disallowed(self):
        self.assertIsNone(find_button(fake_game(size=(1100,800)),self.pat))
    def test_blank_no_hit(self):
        self.assertIsNone(find_button(fake_game(blank=True),self.pat))
    def test_duplicate_location_rejected(self):
        self.assertIsNone(find_button(fake_game(duplicate=True),self.pat))
    def test_temporal_confirmation_and_clear(self):
        t=StableButtons()
        self.assertEqual(t.observe(self.original,[self.pat],'훈련'),[])
        self.assertEqual(len(t.observe(self.original,[self.pat],'훈련')),1)
        self.assertEqual(t.observe(self.original,[self.pat],'스킬'),[])
        self.assertEqual(t.observe(self.original,[self.pat],'훈련'),[])
    def test_disappearance_invalidates_immediately(self):
        t=StableButtons()
        t.observe(self.original,[self.pat],'훈련')
        self.assertTrue(t.observe(self.original,[self.pat],'훈련'))
        self.assertFalse(t.observe(fake_game(blank=True),[self.pat],'훈련'))
        self.assertFalse(t.observe(self.original,[self.pat],'훈련'))
    def test_never_cross_between_scenarios(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'button.json'
            save_patterns(path,[self.pat])
            saved=load_patterns(path)
            self.assertEqual(saved[0].sha256,self.pat.sha256)
            self.assertEqual(len(saved),1)
    def test_competing_labels_same_position_rejected(self):
        a=ButtonHit('스피드',.25,.77,.95,76,48)
        b=ButtonHit('지능',.251,.772,.97,76,48)
        scanner=StableButtons()
        self.assertEqual(scanner.observe_hits([a,b],'훈련'),[])
        self.assertEqual(scanner.observe_hits([a],'훈련'),[])
        self.assertEqual(len(scanner.observe_hits([a],'훈련')),1)

    def test_r6_verified_choice_required_for_overlay(self):
        h=ButtonHit('스피드',.25,.77,.96,76,48)
        self.assertEqual(recommended_training_marks([h],{},800,1100),[])
        self.assertEqual(recommended_training_marks([h],{'training_rankings':[{'name':'스피드'}]},800,1100),[])
        checked={'training_checked':True,'training_rankings':[{'name':'스피드'}]}
        self.assertEqual(recommended_training_marks([h],checked,800,1100)[0].name,'스피드')
        self.assertEqual(recommended_training_marks([h],{'training_checked':True,'training_rankings':[{'name':'파워'}]},800,1100),[])
        self.assertEqual(recommended_training_marks([h,h],checked,800,1100),[])

    def test_unconfirmed_hits_are_not_misused(self):
        unchecked=ButtonHit('스피드',.25,.77,.50,76,48)
        self.assertEqual(recommended_training_marks([unchecked],{'training_checked':True,'training_rankings':[{'name':'스피드'}]},800,1100),[])

    def test_file_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'button.json';save_patterns(path,[self.pat])
            s=path.read_text(encoding='utf8');path.write_text(s.replace(self.pat.sha256,'0'*64),encoding='utf8')
            with self.assertRaises(DetectionError):load_patterns(path)
    def test_duplicate_labels_are_invalid(self):
        with self.assertRaises(DetectionError):save_patterns(Path('not_written.json'),[self.pat,self.pat])
    def test_flat_calibration_rejected(self):
        with self.assertRaises(DetectionError):make_pattern(fake_game(blank=True),'스피드',.25,.77)
    def test_wrong_label_rejected(self):
        with self.assertRaises(DetectionError):make_pattern(self.original,'구매',.25,.77)


if __name__=='__main__':unittest.main()
