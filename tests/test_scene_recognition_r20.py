import unittest, tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from scene_recognition_r20 import make_anchor,save_library,load_library,detect_scene,StableScene,SceneError,SCENES_R20


def synthetic(scene='훈련',size=(800,1100)):
    im=Image.new('RGB',size,'#193b79')
    d=ImageDraw.Draw(im)
    features={'훈련':('#2ab48e','#fbc04b'), '스킬':('#e06b65','#aaf1dc'),
              '시설':('#b86dd0','#76edb2'), '이벤트':('#f7a34b','#d1aaff')}
    c1,c2=features[scene]
    # Anchor 1 and 2 are visually distinct, and both contain structural contrast.
    for x,y,color in ((80,170,c1),(500,860,c2)):
        d.rounded_rectangle((x,y,x+100,y+65),radius=15,fill=color,outline='white',width=5)
        for j in range(4):d.line((x+12,y+10+j*11,x+87,y+10+j*11),fill='black',width=3)
    return im

class SceneR20(unittest.TestCase):
    def anchors(self,kind):
        im=synthetic(kind)
        return [make_anchor(im,kind,80/800,170/1100,100/800,65/1100),
                make_anchor(im,kind,500/800,860/1100,100/800,65/1100)]
    def test_scene_confirmed_only_after_two_frames(self):
        anchors=self.anchors('훈련')+self.anchors('스킬')
        engine=StableScene()
        im=synthetic('훈련')
        self.assertIsNone(engine.observe(im,anchors).scene)
        self.assertEqual(engine.observe(im,anchors).scene,'훈련')
        self.assertIsNone(engine.observe(synthetic('스킬'),anchors).scene)
        self.assertEqual(engine.observe(synthetic('스킬'),anchors).scene,'스킬')
    def test_scene_not_guessed_with_one_landmark(self):
        self.assertIsNone(detect_scene(synthetic(),self.anchors('훈련')[:1]).scene)
    def test_scene_dropped_immediately_on_unknown(self):
        a=self.anchors('훈련');e=StableScene()
        e.observe(synthetic(),a);e.observe(synthetic(),a)
        self.assertEqual(e.confirmed,'훈련')
        self.assertIsNone(e.observe(Image.new('RGB',(800,1100),'#ffffff'),a).scene)
        self.assertIsNone(e.confirmed)
    def test_aspect_ratio_not_guessed(self):
        self.assertIsNone(detect_scene(synthetic().resize((1280,800)),self.anchors('훈련')).scene)
    def test_different_resolution_same_layout_matches(self):
        im=synthetic()
        a=self.anchors('훈련')
        self.assertEqual(detect_scene(im.resize((640,880)),a).scene,'훈련')
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'anchor.json';save_library(path,self.anchors('시설'))
            self.assertEqual(detect_scene(synthetic('시설'),load_library(path)).scene,'시설')
    def test_blank_anchor_rejected(self):
        with self.assertRaises(SceneError):make_anchor(Image.new('RGB',(800,1100),'#111111'),'훈련',.1,.2,.12,.07)
    def test_invalid_scene_rejected(self):
        with self.assertRaises(SceneError):make_anchor(synthetic(),'전투',.1,.2,.12,.07)
    def test_truncated_json_fails(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.json';path.write_text('{}')
            with self.assertRaises(SceneError):load_library(path)

if __name__=='__main__':unittest.main()
