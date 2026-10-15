"""R7 regression tests: sourced constraints plus synthetic *unvalidated* preferences."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from uma_core import RunProfile, STATS, TurnState
from island_planner_r7 import (
    FACILITIES, SCHEMA, SLOTS_BY_TUCKER, upgrade_cost, validate_levels,
    legal_upgrades, plan_island, exam_progress, ticket_review, export_plan)


def sample(levels=None):
    profile = RunProfile()
    state = TurnState(island_tickets=1, turns_until_next_ticket=1,
                      development_points=110)
    state.building_levels = {s:0 for s in FACILITIES}
    if levels:
        state.building_levels.update(levels)
    routes = {s:'미선택' for s in FACILITIES}
    return profile, state, routes


class R7PlannerTests(unittest.TestCase):
    def test_sourced_budget_tiers(self):
        self.assertEqual(SLOTS_BY_TUCKER['미편성'], (3,3,4,4,6))
        self.assertEqual(SLOTS_BY_TUCKER['Lv1~40'], (3,4,5,5,7))
        self.assertEqual(SLOTS_BY_TUCKER['Lv41~50'], (4,5,6,6,8))

    def test_stat_facility_cost_per_route(self):
        for s in STATS:
            self.assertEqual([upgrade_cost(s,n,'미선택' if n<=2 else '본능') for n in range(1,6)], [1,1,2,2,3])
            self.assertEqual([upgrade_cost(s,n,'미선택' if n<=2 else '기교') for n in range(1,6)], [1,1,1,1,2])

    def test_beach_house_costs_and_cap(self):
        self.assertEqual([upgrade_cost('해변의 집', n) for n in (1,2,3)], [2,3,3])
        for x in (0,4):
            with self.assertRaises(ValueError):
                upgrade_cost('해변의 집',x)

    def test_max_level_and_invalid_route(self):
        with self.assertRaises(ValueError):
            upgrade_cost('스피드',6,'본능')
        with self.assertRaises(ValueError):
            upgrade_cost('스피드',3,'미선택')
        with self.assertRaises(ValueError):
            upgrade_cost('스피드',1,'본능')

    def test_branch_at_level_three(self):
        _, st, r = sample({'스피드':2})
        ups = legal_upgrades(st.building_levels, r, facility='스피드')
        self.assertEqual({u.route for u in ups}, {'본능','기교'})
        self.assertEqual({u.cost for u in ups}, {1,2})

    def test_existing_branch_is_locked(self):
        _, st, r = sample({'스피드':3})
        r['스피드'] = '본능'
        ups = legal_upgrades(st.building_levels, r, facility='스피드')
        self.assertEqual(len(ups),1)
        self.assertEqual(ups[0].route,'본능')

    def test_missing_existing_branch_blocks(self):
        p, s, r = sample({'스피드':3})
        result = plan_island(p,s,phase=3,tucker='Lv41~50',routes=r)
        self.assertEqual(result.status,'추천 보류')
        self.assertTrue(any('스피드' in error for error in result.errors))

    def test_maxed_facility_has_no_upgrades(self):
        _, s, r = sample({'스피드':5,'해변의 집':3})
        r['스피드']='기교'
        self.assertEqual(legal_upgrades(s.building_levels,r,facility='스피드'), ())
        self.assertEqual(legal_upgrades(s.building_levels,r,facility='해변의 집'), ())

    def test_do_not_omit_facility(self):
        p,s,r = sample()
        del s.building_levels['지능']
        self.assertIn('6개 시설', ' '.join(plan_island(p,s,phase=1,tucker='Lv41~50',routes=r).errors))

    def test_no_junior_more_than_four_slots(self):
        p,s,r = sample()
        out = plan_island(p,s,phase=1,tucker='Lv41~50',routes=r)
        self.assertTrue(out.candidates)
        for c in out.candidates:
            self.assertEqual(len(c.phases),5)
            for ph in c.phases:
                self.assertLessEqual(ph.used,ph.capacity)
            self.assertEqual(c.phases[0].capacity,4)
            self.assertEqual(c.phases[4].capacity,8)

    def test_lower_tucker_has_lower_phase_caps(self):
        p,s,r = sample()
        out = plan_island(p,s,phase=4,tucker='미편성',routes=r)
        self.assertTrue(out.candidates)
        self.assertEqual([ph.capacity for ph in out.candidates[0].phases],[4,6])

    def test_progress_missing_never_invents_targets(self):
        self.assertIn('보류', ''.join(exam_progress(development_points=40,target_points=None,
            remaining_turns=3,expected_points_per_turn=20)))

    def test_exam_progress_shortfall(self):
        out = exam_progress(development_points=100,target_points=500,
                            remaining_turns=2,expected_points_per_turn=70)
        self.assertIn('부족할', out[0])
        out = exam_progress(development_points=500,target_points=500,
                            remaining_turns=0,expected_points_per_turn=70)
        self.assertIn('도달',out[0])

    def test_ticket_cap_senior_changes(self):
        with self.assertRaises(ValueError):
            ticket_review(tickets=2,senior_september_or_later=False,
                next_ticket_turns=1,friendship_locations=3)
        out = ticket_review(tickets=3,senior_september_or_later=True,
            next_ticket_turns=None,friendship_locations=4)
        self.assertIn('3장',out[0])

    def test_ticket_upcoming_warning(self):
        out=ticket_review(tickets=1,senior_september_or_later=False,
                next_ticket_turns=0,friendship_locations=0)
        self.assertTrue(any('손실' in part for part in out))

    def test_unspecified_friendship_does_not_recommend_use(self):
        out=ticket_review(tickets=1,senior_september_or_later=False,
                next_ticket_turns=None,friendship_locations=None)
        self.assertTrue(any('보류' in part for part in out))

    def test_support_count_limit(self):
        p,s,r=sample()
        out=plan_island(p,s,phase=2,tucker='Lv41~50',routes=r,
                        support_counts={x:2 for x in STATS})
        self.assertEqual(out.status,'추천 보류')

    def test_profile_reject_other_event(self):
        p,s,r=sample()
        p.event='평가점'
        out=plan_island(p,s,phase=2,tucker='Lv41~50',routes=r)
        self.assertTrue(out.errors)

    def test_phase_after_final_evaluation(self):
        p,s,r=sample()
        out=plan_island(p,s,phase=5,tucker='Lv41~50',routes=r,
                        senior_september_or_later=True)
        self.assertTrue(out.errors)

    def test_preserves_existing_levels_and_routes(self):
        p,s,r=sample({'스피드':4,'해변의 집':1})
        r['스피드']='본능'
        before=copy.deepcopy(s.building_levels)
        out=plan_island(p,s,phase=5,tucker='Lv41~50',routes=r)
        self.assertTrue(out.candidates)
        self.assertEqual(s.building_levels,before)
        for c in out.candidates:
            self.assertEqual(c.final_routes['스피드'],'본능')
            self.assertGreaterEqual(c.final_levels['스피드'],4)

    def test_fails_closed_on_bad_facility_level(self):
        p,s,r=sample({'해변의 집':4})
        out=plan_island(p,s,phase=5,tucker='Lv41~50',routes=r)
        self.assertEqual(out.status,'추천 보류')
        self.assertFalse(out.candidates)

    def test_snapshot_detects_changed_state(self):
        p,s,r=sample()
        kw={'phase':5,'tucker':'Lv41~50','routes':r,
            'support_counts':{},'growth_bonus_stat':'없음',
            'exam_target':None,'exam_turns':None,'expected_dp_per_turn':None,
            'senior_september_or_later':False,'friendship_locations':None}
        out=plan_island(p,s,**kw)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r7.json'
            export_plan(path,p,s,out,kw)
            doc=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(doc['schema'],SCHEMA)
            self.assertFalse(doc['ml_training_label_verified'])
            self.assertTrue(doc['experimental_only'])
            s.development_points+=1
            with self.assertRaises(ValueError):
                export_plan(path,p,s,out,kw)

    def test_plan_candidates_are_reproducible(self):
        p,s,r=sample()
        a=plan_island(p,s,phase=3,tucker='Lv41~50',routes=r)
        b=plan_island(p,s,phase=3,tucker='Lv41~50',routes=r)
        self.assertEqual([x.score_proxy for x in a.candidates], [x.score_proxy for x in b.candidates])
        self.assertFalse(a.verified_optimal)


if __name__=='__main__':
    unittest.main()
