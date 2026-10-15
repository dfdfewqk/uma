import json
import tempfile
import unittest
from pathlib import Path
from hud_r19 import Mark,load_marks,save_marks,visible_marks,marker_label,side_summary


class R19Tests(unittest.TestCase):
    def setUp(self):
        self.mark=Mark('훈련','스피드',.2,.7,800,600)

    def test_no_automatic_highlight_without_scene_confirmation(self):
        c={'training_checked':True,'training_rankings':[{'name':'스피드'}]}
        self.assertEqual(visible_marks([self.mark],'훈련',(800,600),c),[])

    def test_no_other_scene_or_scaled_position(self):
        c={'manual_scene_confirmed':True,'training_checked':True,'training_rankings':[{'name':'스피드'}]}
        self.assertEqual(visible_marks([self.mark],'스킬',(800,600),c),[])
        self.assertEqual(visible_marks([self.mark],'훈련',(801,600),c),[])

    def test_training_rank_only_when_current_validated(self):
        self.assertEqual(marker_label(self.mark, {})[0],'추천 보류')
        self.assertEqual(marker_label(self.mark,{'training_checked':True,'training_rankings':[{'name':'스피드'}]})[0],'추천 후보')

    def test_skill_priority_needs_r12_current(self):
        skill=Mark('스킬','왕수',.5,.5,800,600)
        self.assertEqual(marker_label(skill,{'skill_advice':{'왕수':{'verdict':'우선 검토'}}})[0],'추천 보류')
        self.assertEqual(marker_label(skill,{'skill_checked':True,'skill_advice':{'왕수':{'verdict':'우선 검토'}}})[0],'우선 검토')
        self.assertEqual(marker_label(skill,{'skill_checked':True,'skill_advice':{'왕수':{'verdict':'조건 불일치'}}})[0],'주의')

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'positions.json'
            save_marks(path,[self.mark])
            self.assertEqual(load_marks(path),[self.mark])
            self.assertIn('자동',json.loads(path.read_text(encoding='utf-8'))['warning'])

    def test_invalid_mark_rejected(self):
        with self.assertRaises(ValueError):Mark('훈련','스피드',1.4,.5,800,600).validate()
        with self.assertRaises(ValueError):Mark('스킬','',.3,.3,800,600).validate()
        with self.assertRaises(ValueError):Mark('이벤트','선택',.3,.3,800,600).validate()

    def test_side_uses_only_supplied_inputs(self):
        result=side_summary({'targets':{'스피드':1700},'required_skills':[{'name':'왕수','status':'미획득'}]})
        self.assertEqual(result['stats'][0],('스피드',None,1700))
        self.assertEqual(result['required_skills'][0]['status'],'미획득')

if __name__=='__main__':unittest.main()
