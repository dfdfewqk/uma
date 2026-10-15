"""Synthetic-only R11 regression suite; no purported Japanese video samples."""
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from uma_core import STATS, RunProfile, TurnState
from island_planner_r7 import FACILITIES
from goal_tracker_r11 import (RequiredSkill, assess_goals, export_goal_report,
                              context_fingerprint, verified_current_run_trend,
                              SCHEMA)
from storage import add_turn, connect, create_run


class R11Tests(unittest.TestCase):
    def setUp(self):
        self.p=RunProfile()
        self.s=TurnState(remaining_turns=20,island_tickets=1,turns_until_next_ticket=-1)
        self.skills=[RequiredSkill('필수A','미확보',140),RequiredSkill('필수B','획득완료',None)]
        self.facilities={'스피드':3,'해변의 집':2}

    def evaluate(self,**kwargs):
        arguments={'skills':self.skills,'facility_targets':self.facilities,
                   'skills_confirmed':True, 'evaluation_target':500,
                   'turns_until_evaluation':5}
        arguments.update(kwargs)
        return assess_goals(self.p,self.s,**arguments)

    def test_core_stat_arithmetic(self):
        r=self.evaluate()
        a=r.stats[0]
        self.assertEqual(a['gap'],1400)
        self.assertEqual(a['required_per_remaining_turn'],70)
        self.assertIsNone(r.completion_probability)
        self.assertFalse(r.verified_optimal)
        self.assertFalse(r.trained_model)

    def test_spending_budget_no_unknown(self):
        r=self.evaluate()
        self.assertTrue(r.skills['budget_complete'])
        self.assertEqual(r.skills['known_unpurchased_effective_cost'],140)
        self.assertEqual(r.skills['point_shortfall_if_buy_now'],0)
        self.assertEqual(r.skills['acquired'],['필수B'])

    def test_skill_missing_cost_blocks_total(self):
        r=self.evaluate(skills=[RequiredSkill('필수A','미확보')])
        self.assertIsNone(r.skills['point_shortfall_if_buy_now'])
        self.assertFalse(r.skills['budget_complete'])

    def test_unknown_status_blocks_total(self):
        r=self.evaluate(skills=[RequiredSkill('필수A','미확인',120)])
        self.assertIsNone(r.skills['point_shortfall_if_buy_now'])
        self.assertIn('필수A',r.skills['unknown_status'])

    def test_skills_not_confirmed_blocks_total(self):
        r=self.evaluate(skills_confirmed=False)
        self.assertIsNone(r.skills['point_shortfall_if_buy_now'])
        self.assertIn('정보 부족',r.status)

    def test_empty_confirmed_skills_explicit(self):
        r=self.evaluate(skills=[],skills_confirmed=True)
        self.assertTrue(r.skills['budget_complete'])
        self.assertEqual(r.skills['known_unpurchased_effective_cost'],0)

    def test_achieved_only_if_all_goals_explicit(self):
        self.s.stats=dict(self.p.target_stats)
        self.s.development_points=500
        self.s.building_levels.update({'스피드':3,'해변의 집':2})
        r=self.evaluate(skills=[],skills_confirmed=True)
        self.assertFalse(r.achieved_requirements)  # remaining 4 facility goals unknown
        r=self.evaluate(skills=[],skills_confirmed=True,facility_targets=dict(self.s.building_levels))
        self.assertTrue(r.achieved_requirements)
        self.assertIn('실전 성능 미검증',r.status)

    def test_required_gain_zero_remaining(self):
        self.s.remaining_turns=0
        r=self.evaluate()
        self.assertIsNone(r.stats[0]['required_per_remaining_turn'])
        self.assertIn('남은 턴 없음',r.stats[0]['flag'])

    def test_met_target_zero_remaining(self):
        self.s.remaining_turns=0
        self.s.stats=dict(self.p.target_stats)
        r=self.evaluate()
        self.assertEqual(r.stats[0]['required_per_remaining_turn'],0)

    def test_exam_arithmetic_and_exact_deadline(self):
        r=self.evaluate()
        self.assertEqual(r.evaluation['gap'],500)
        self.assertEqual(r.evaluation['required_per_turn'],100)
        r=self.evaluate(turns_until_evaluation=0)
        self.assertEqual(r.evaluation['status'],'기한 도달/미달')
        self.assertIsNone(r.evaluation['required_per_turn'])

    def test_partial_exam_rejected(self):
        r=self.evaluate(evaluation_target=None,turns_until_evaluation=5)
        self.assertTrue(r.errors)
        self.assertEqual(r.status,'분석 보류')

    def test_no_facility_target_does_not_imply_zero(self):
        r=self.evaluate(facility_targets={})
        self.assertTrue(all(x['levels_needed'] is None for x in r.facilities))

    def test_invalid_facility_or_levels_rejected(self):
        self.assertTrue(self.evaluate(facility_targets={'가짜':2}).errors)
        self.assertTrue(self.evaluate(facility_targets={'해변의 집':4}).errors)
        self.s.building_levels['스피드']=7
        self.assertTrue(self.evaluate().errors)

    def test_invalid_stat_raises_warning_not_crash(self):
        self.s.stats['스피드']=-2
        self.assertTrue(self.evaluate().errors)

    def test_invalid_event_scenario(self):
        self.p.event='평가점'
        self.assertTrue(self.evaluate().errors)
        self.p.event='챔피언스 미팅'
        self.p.scenario='missing'
        self.assertTrue(self.evaluate().errors)

    def test_reject_duplicate_skill(self):
        x=[RequiredSkill('필수A','미확보',100),RequiredSkill('필수A','획득완료',0)]
        self.assertTrue(self.evaluate(skills=x).errors)

    def test_reject_bad_cost_bool_nan(self):
        for value in (True,-1,float('nan'),10000):
            self.assertTrue(self.evaluate(skills=[RequiredSkill('A','미확보',value)]).errors)

    def test_skill_status_invalid(self):
        self.assertTrue(self.evaluate(skills=[RequiredSkill('A','예정',100)]).errors)

    def test_ticket_unknown_stays_unknown(self):
        r=self.evaluate()
        self.assertIsNone(r.island_tickets['until_next'])
        self.assertIn('미확인',r.island_tickets['status'])

    def test_current_snapshot_hash_stable_for_screenshot_paths(self):
        original=self.evaluate().context_hash
        self.s.screenshot='another.png'
        self.assertEqual(self.evaluate().context_hash,original)
        self.s.remaining_turns+=1
        self.assertNotEqual(self.evaluate().context_hash,original)

    def test_skills_changed_invalidates_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.evaluate()
            with self.assertRaises(ValueError):
                export_goal_report(Path(tmp)/'r.json',self.p,self.s,
                                   [RequiredSkill('A','미확보',999)],self.facilities,result,
                                   skills_confirmed=True,evaluation_target=500,
                                   turns_until_evaluation=5)
            self.assertFalse((Path(tmp)/'r.json').exists())

    def test_export_clean_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'goals.json'
            result=self.evaluate()
            export_goal_report(out,self.p,self.s,self.skills,self.facilities,result,
                               skills_confirmed=True,evaluation_target=500,turns_until_evaluation=5)
            obj=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(obj['schema'],SCHEMA)
            self.assertIsNone(obj['completion_probability'])
            self.assertFalse(obj['result']['trained_model'])
            self.assertNotIn('screenshot',obj['state'])

    def test_missing_run_trend_does_not_invent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'r.sqlite3')
            self.assertIsNone(verified_current_run_trend(conn,None,self.p,self.s,self.skills,self.facilities,
                skills_confirmed=True,evaluation_target=500,turns_until_evaluation=5))
            conn.close()

    def test_saved_run_trend_must_be_same_run_and_exact_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'r.sqlite3')
            rid=create_run(conn,asdict(self.p))
            for i in range(6):
                state=asdict(TurnState(remaining_turns=25-i, stats={s:300+i*8 for s in STATS}))
                if i==5:
                    self.s=TurnState(**state)
                add_turn(conn,rid,state,{},[],'미선택')
            args=dict(skills_confirmed=True,evaluation_target=500,turns_until_evaluation=5)
            record=verified_current_run_trend(conn,rid,self.p,self.s,self.skills,self.facilities,**args)
            self.assertIsNotNone(record)
            self.assertEqual(record['intervals'],5)
            r=self.evaluate(observed_trend=record)
            self.assertEqual(r.evidence['past_median_per_stat']['스피드'],8)
            self.s.remaining_turns-=1
            self.assertIsNone(verified_current_run_trend(conn,rid,self.p,self.s,self.skills,self.facilities,**args))
            self.assertFalse(self.evaluate(observed_trend=record).evidence)
            conn.close()

    def test_saved_profile_changed_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connect(Path(tmp)/'r.sqlite3')
            rid=create_run(conn,asdict(self.p))
            add_turn(conn,rid,asdict(self.s),{},[],'미선택')
            self.p.character='changed'
            self.assertIsNone(verified_current_run_trend(conn,rid,self.p,self.s,self.skills,self.facilities,
                skills_confirmed=True,evaluation_target=500,turns_until_evaluation=5))
            conn.close()

    def test_no_fraudulent_win_rate_or_quit(self):
        result=self.evaluate()
        obj=json.dumps(asdict(result),ensure_ascii=False)
        self.assertNotIn('승률 80',obj)
        self.assertNotEqual(result.status,'도축 추천')
        self.assertIsNone(result.completion_probability)


if __name__=='__main__':unittest.main()

# Separate template handling regressions (do not treat reloaded rules as reviewed observations)
class R11TemplateTests(unittest.TestCase):
    def setUp(self):
        from goal_tracker_r11 import save_goal_template, load_goal_template
        self.save=save_goal_template
        self.load=load_goal_template
        self.p=RunProfile()
        self.skills=[RequiredSkill('필수A','미확보',180)]

    def test_template_roundtrip_requires_reconfirmation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scope.json'
            self.save(path,self.p,self.skills,{'스피드':4},evaluation_target=700)
            r=self.load(path,self.p)
            self.assertEqual(r['skills'],self.skills)
            self.assertFalse(r['skills_confirmed'])
            self.assertIsNone(r['turns_until_evaluation'])
            self.assertEqual(r['evaluation_target'],700)

    def test_template_scope_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scope.json'
            self.save(path,self.p,self.skills,{'스피드':4})
            self.p.event='리그 오브 히어로즈'
            with self.assertRaises(ValueError):self.load(path,self.p)
            self.p.event='챔피언스 미팅'
            self.p.target_stats['스피드']+=1
            with self.assertRaises(ValueError):self.load(path,self.p)

    def test_invalid_saved_skill_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scope.json'
            self.save(path,self.p,self.skills,{})
            raw=json.loads(path.read_text(encoding='utf-8'))
            raw['skills'][0]['status']='획득될듯'
            path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):self.load(path,self.p)

    def test_reject_oversized_untrusted_template(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'too_big.json'
            path.write_text('x'*130_000,encoding='utf-8')
            with self.assertRaises(ValueError):self.load(path,self.p)

    def test_template_does_not_contain_screenshot_or_confirmed_flag(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scope.json'
            self.save(path,self.p,self.skills,{'스피드':3})
            obj=json.loads(path.read_text(encoding='utf-8'))
            self.assertNotIn('screenshots',obj)
            self.assertNotIn('skills_confirmed',obj)
