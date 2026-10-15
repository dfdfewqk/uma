import unittest
from PIL import Image,ImageDraw
from skill_ocr_r20 import skill_hits_from_tsv,evidence_crop,same_visible_text

HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\ttext\tconf\tleft\ttop\twidth\theight\n'
def row(text,x=80,y=150,conf=96,line=1,block=1):
    return f'5\t1\t{block}\t1\t{line}\t{text}\t{conf}\t{x}\t{y}\t130\t22\n'
class TestSkillOCR(unittest.TestCase):
    def test_exact_visible_name(self):
        got=skill_hits_from_tsv(HEADER+row('왕수')+row('원호의',line=2,y=200)+row('마에스트로',x=211,y=200,line=2),['왕수','원호의 마에스트로','없는스킬'])
        self.assertEqual({x.name for x in got},{'왕수','원호의 마에스트로'})
    def test_short_text_must_be_high_confidence(self):
        self.assertFalse(skill_hits_from_tsv(HEADER+row('왕수',conf=85),['왕수']))
    def test_duplicate_is_ambiguous(self):
        self.assertFalse(skill_hits_from_tsv(HEADER+row('왕수')+row('왕수',line=2,y=250),['왕수']))
    def test_only_exact_or_long_contains(self):
        self.assertFalse(skill_hits_from_tsv(HEADER+row('왕수왕수'),['왕수']))
    def test_stale_crop_after_scroll_is_rejected(self):
        im=Image.new('RGB',(500,500),'white');d=ImageDraw.Draw(im)
        d.rectangle((80,150,210,172),fill='#9c3b3b')
        hit=skill_hits_from_tsv(HEADER+row('왕수'),['왕수'])[0]
        orig=evidence_crop(im,hit)
        self.assertTrue(same_visible_text(orig,im,hit))
        changed=im.copy();ImageDraw.Draw(changed).rectangle((80,150,210,172),fill='#3062bf')
        self.assertFalse(same_visible_text(orig,changed,hit))

if __name__=='__main__':unittest.main()
