import tempfile, unittest
from pathlib import Path
from PIL import Image
from skill_ocr_r20 import SkillListRegion,save_skill_region,load_skill_region,skill_hits_from_tsv

class TestRegion(unittest.TestCase):
    def test_region_round_trip_and_rescale(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'roi.json'
            roi=SkillListRegion(.08,.18,.82,.68,600,1000)
            save_skill_region(p,roi)
            got=load_skill_region(p)
            self.assertEqual(got,roi)
            self.assertEqual(got.pixel_box(Image.new('RGB',(900,1500))), (72,270,810,1290))
    def test_mismatched_aspect_fails_closed(self):
        roi=SkillListRegion(.08,.18,.82,.68,600,1000)
        self.assertIsNone(roi.pixel_box(Image.new('RGB',(1000,600))))
    def test_invalid_roi_rejected(self):
        with self.assertRaises(ValueError):SkillListRegion(.1,.1,.03,.6,600,1000).validate()

if __name__=='__main__':unittest.main()

class TestMarkerRemap(unittest.TestCase):
    def test_only_proportional_resize_after_two_anchors(self):
        from hud_r19 import Mark
        from scene_recognition_r20 import remap_marked_locations,make_anchor
        from PIL import Image,ImageDraw
        im=Image.new('RGB',(800,1200),'#000040');d=ImageDraw.Draw(im)
        d.rectangle((80,180,184,250),fill='#00cc88');d.line((80,180,184,250),fill='white',width=6)
        d.rectangle((470,880,574,950),fill='#ccaa00');d.line((470,950,574,880),fill='white',width=6)
        aa=[make_anchor(im,'훈련',.1,.15,.13,.06),make_anchor(im,'훈련',470/800,880/1200,.13,.06)]
        m=Mark('훈련','스피드',.35,.8,800,1200)
        self.assertEqual(remap_marked_locations([m],'훈련',600,900,aa)[0].width,600)
        self.assertEqual(remap_marked_locations([m],'훈련',900,600,aa),[])
        self.assertEqual(remap_marked_locations([m],'스킬',600,900,aa),[])
