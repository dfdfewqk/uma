import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from live_training_r22 import (TrainingCaptureSession, NumericProfile,FieldBox,
                               CaptureError,save_profile,load_profile,ocr_candidates)
from uma_core import RunProfile,TurnState,STATS
from training_r5 import MANDATORY


def picture(color=(30,45,70)):
    pic=Image.new('RGB',(900,650),color)
    ImageDraw.Draw(pic).text((25,25),str(color),fill=(250,250,250))
    return pic


def values():
    out={f:'10' for f in MANDATORY}
    out['실패 확률']='2'
    out['체력 변화']='-17'
    return out


class TestR22(unittest.TestCase):
    def test_profile_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'roi.json'
            p=NumericProfile(width=900,height=650,boxes={'스피드 상승':FieldBox(.15,.2,.2,.24)})
            save_profile(f,p)
            q=load_profile(f)
            self.assertEqual(q.boxes['스피드 상승'].x1,.15)
            self.assertTrue(q.matches(picture()))
            self.assertFalse(q.matches(Image.new('RGB',(900,900))))

    def test_bad_region(self):
        with self.assertRaises(CaptureError):FieldBox(.2,.3,.1,.4).validate()
        with self.assertRaises(CaptureError):FieldBox(float('nan'),.1,.3,.4).validate()

    def test_wrong_scenario(self):
        with self.assertRaises(CaptureError):NumericProfile('another',900,650).validate()

    def test_capture_duplicates_block(self):
        s=TrainingCaptureSession('클래식 1월')
        img=picture()
        s.register_capture('스피드',img,111)
        with self.assertRaisesRegex(CaptureError,'중복'):
            s.register_capture('스태미나',img,111)
        with self.assertRaises(CaptureError):s.register_capture('파워',picture((40,40,80)),222)

    def test_recapture_invalidates(self):
        s=TrainingCaptureSession('클래식 1월')
        h=s.register_capture('스피드',picture(),3)
        s.confirm('스피드',values(),h)
        self.assertIn('스피드',s.options)
        s.register_capture('스피드',picture((40,50,80)),3)
        self.assertNotIn('스피드',s.options)
        with self.assertRaises(CaptureError):s.confirm('스피드',values(),h)

    def test_missing_blocks(self):
        s=TrainingCaptureSession('주니어')
        h=s.register_capture('스피드',picture())
        with self.assertRaisesRegex(CaptureError,'누락'):
            s.confirm('스피드',{'스피드 상승':'99'},h)

    def test_five_options_compared(self):
        s=TrainingCaptureSession('주니어')
        for i,n in enumerate(STATS):
            im=picture((30+i*20,45,70))
            h=s.register_capture(n,im)
            v=values();v[f'{n} 상승']='50'
            s.confirm(n,v,h)
        r=s.compare(RunProfile(),TurnState(turn_label='주니어'))
        self.assertEqual(len(r.ranked),5)
        self.assertFalse(r.missing)

    def test_turn_change_blocked(self):
        s=TrainingCaptureSession('주니어')
        with self.assertRaisesRegex(CaptureError,'턴'):
            s.compare(RunProfile(),TurnState(turn_label='클래식'))

    def test_island_requires_extra(self):
        s=TrainingCaptureSession('주니어')
        h=s.register_capture('섬 트레이닝',picture())
        with self.assertRaisesRegex(CaptureError,'우정 발동 시설 수'):
            s.confirm('섬 트레이닝',values(),h)

    def test_island_requires_ticket(self):
        s=TrainingCaptureSession('주니어')
        for i,n in enumerate(STATS):
            h=s.register_capture(n,picture((30+i*20,45,70)))
            s.confirm(n,values(),h)
        r=s.compare(RunProfile(),TurnState(turn_label='주니어',island_tickets=1))
        self.assertIn('섬 트레이닝',r.missing)

    def test_reset_clears(self):
        s=TrainingCaptureSession('A');s.register_capture('스피드',picture())
        s.reset('B');self.assertFalse(s.frames);self.assertEqual(s.turn_id,'B')

    def test_report_safe_and_local(self):
        with tempfile.TemporaryDirectory() as td:
            s=TrainingCaptureSession('A',42)
            s.register_capture('스피드',picture(),42)
            p=s.export(Path(td)/'report.json')
            data=json.loads(p.read_text(encoding='utf8'))
            self.assertFalse(data['game_verified'])
            self.assertTrue(data['not_training_labels'])
            self.assertNotIn('image_base64',data)

    def test_ocr_no_profile_or_binary(self):
        p=NumericProfile(width=900,height=650,boxes={'스피드 상승':FieldBox(.1,.1,.2,.2)})
        with self.assertRaises(CaptureError):ocr_candidates(picture(),p,'/definitely/missing/tesseract')

    def test_unmatched_dimensions(self):
        s=TrainingCaptureSession('A')
        s.register_capture('스피드',picture())
        with self.assertRaises(CaptureError):s.register_capture('파워',Image.new('RGB',(600,900)))

    def test_invalid_numbers(self):
        s=TrainingCaptureSession('A');h=s.register_capture('파워',picture())
        v=values();v['실패 확률']='200'
        with self.assertRaises(CaptureError):s.confirm('파워',v,h)

if __name__=='__main__':unittest.main()
