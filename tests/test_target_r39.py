import json
import tempfile
import unittest
from pathlib import Path
from target_selector_r39 import (Target, KINDS, STYLES, read_target, save_target,
    load_courses, course_for, SCENARIO, COURSE_SCHEMA)
from decision_contract_r39 import SkillCondition, skill_fit, RepeatPlan, next_turn_buff_useful

class R39Tests(unittest.TestCase):
    def test_selectors(self):
        for kind in KINDS:
            for round in range(1,5):
                for style in STYLES:
                    target=Target(kind,round,style).validate()
                    self.assertIn(f'{round}회차',target.label)
        for bad in (0,5,True):
            with self.assertRaises(ValueError):Target(KINDS[0],bad,'선입').validate()

    def test_target_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'target.json'
            target=Target(KINDS[1],4,'추입')
            save_target(path,target)
            self.assertEqual(target,read_target(path))
            self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_no_unknown_jp_courses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json'
            self.assertEqual(load_courses(path),{})
            self.assertIsNone(course_for(Target(KINDS[0],1,'선입'),{}))
            good={'schema':COURSE_SCHEMA,'server':'KR','scenario':SCENARIO,'courses':[
                {'key':'cm-1','distance':'마일','meters':1600,'surface':'잔디','venue':'가상',
                 'source':'synthetic-only','verified_for_kr':True},
                {'key':'loh-1','distance':'중거리','meters':2000,'surface':'잔디',
                 'venue':'가상','source':'synthetic-only','verified_for_kr':False}]}
            path.write_text(json.dumps(good,ensure_ascii=False),encoding='utf-8')
            self.assertEqual(list(load_courses(path)),['cm-1'])
            good['server']='JP'
            path.write_text(json.dumps(good,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):load_courses(path)

    def test_skill_gate(self):
        x=SkillCondition('가상 스킬',distance='마일',style='추입',verified=True)
        self.assertEqual(skill_fit(x,style='추입',distance='마일')[0],'eligible')
        self.assertEqual(skill_fit(x,style='추입',distance='중거리')[0],'ineligible')
        self.assertEqual(skill_fit(x,style='선입',distance='마일')[0],'ineligible')
        self.assertEqual(skill_fit(x,style='추입',distance=None)[0],'unverified')
        self.assertEqual(skill_fit(SkillCondition('모름'),style='추입',distance='마일')[0],'unverified')

    def test_repeat_counts_discarded_and_failures(self):
        plan=RepeatPlan(4)
        for outcome in ('good','disposed','failed','ordinary'):
            plan=plan.finish(outcome)
        self.assertEqual(plan.remaining,0)
        self.assertEqual((plan.good,plan.disposed,plan.failed),(1,1,1))
        with self.assertRaises(ValueError):plan.finish('good')

    def test_next_turn_race(self):
        self.assertFalse(next_turn_buff_useful(True))
        self.assertTrue(next_turn_buff_useful(False))
        self.assertIsNone(next_turn_buff_useful(None))
        with self.assertRaises(ValueError):next_turn_buff_useful(1)

if __name__=='__main__':unittest.main()
