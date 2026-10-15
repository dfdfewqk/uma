import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict, replace

from uma_core import Action, RunProfile, TurnState, STATS, TRAININGS, default_actions
from island_planner_r7 import plan_island, fingerprint
from decision_r6 import compare_turn, state_fingerprint, evidence_fingerprint
from island_impact_r8 import coverage, inspect_island_impact, export_impact, context_hash


class IslandImpactTests(unittest.TestCase):
    def setUp(self):
        self.profile = RunProfile()
        self.state = TurnState(island_tickets=1, turns_until_next_ticket=2)
        self.friends = dict(zip(STATS, [2, 1, 0, 0, 0]))

    def analyze(self, **kwargs):
        return inspect_island_impact(self.profile, self.state, friendship_counts=self.friends, **kwargs)

    def test_no_facilities_exclude_friendship(self):
        out = self.analyze()
        self.assertFalse(out.errors)
        self.assertEqual(out.current.distinct_facilities, 0)
        self.assertEqual(set(out.current.missing_facilities), {'스피드', '스태미나'})
        self.assertIsNone(out.measured_island_action)

    def test_beach_requires_built_distinct_locations(self):
        for s in ('스피드', '스태미나', '해변의 집'):
            self.state.building_levels[s] = 1
        out = self.analyze()
        self.assertTrue(out.current.beach_multi_friendship_condition)
        self.assertEqual(out.current.participating_friendships, 3)
        self.assertEqual(out.current.distinct_facilities, 2)

    def test_beach_alone_does_not_trigger(self):
        self.state.building_levels['해변의 집'] = 1
        self.assertFalse(self.analyze().current.beach_multi_friendship_condition)

    def test_two_friends_one_facility_is_not_multi_location(self):
        self.state.building_levels['스피드'] = 1
        self.state.building_levels['해변의 집'] = 1
        self.friends['스태미나'] = 0
        out = self.analyze()
        self.assertEqual(out.current.participating_friendships, 2)
        self.assertFalse(out.current.beach_multi_friendship_condition)

    def test_missing_friendship_selection_abstains(self):
        self.friends.pop('지능')
        self.assertEqual(self.analyze().status, '판단 보류')

    def test_invalid_friends_boolean_and_negatives(self):
        self.friends['스피드'] = True
        self.assertTrue(self.analyze().errors)
        self.friends['스피드'] = -1
        self.assertTrue(self.analyze().errors)
        self.friends['스피드'] = 7
        self.assertTrue(self.analyze().errors)

    def test_unsupported_event_or_scenario_abstains(self):
        self.profile.scenario = 'other'
        self.assertTrue(self.analyze().errors)
        self.profile.scenario = 'island_post_patch_v1'
        self.profile.event = '평가점'
        self.assertTrue(self.analyze().errors)

    def test_unchecked_high_level_route_abstains(self):
        self.state.building_levels['근성'] = 3
        self.assertTrue(self.analyze().errors)

    def test_stale_r7_plan_does_not_carry_forward(self):
        opts = self._r7_options()
        plan = plan_island(self.profile, self.state, **opts)
        self.assertTrue(plan.candidates)
        self.state.energy = 22
        self.assertTrue(self.analyze(r7_result=plan, r7_options=opts).errors)

    def _r7_options(self):
        return {'phase': 5, 'tucker': '미편성', 'routes': {s:'미선택' for s in (*STATS,'해변의 집')},
                'support_counts': {}, 'growth_bonus_stat': '없음', 'exam_target': None,
                'exam_turns': None, 'expected_dp_per_turn': None,
                'senior_september_or_later': False, 'friendship_locations': 2}

    def test_r7_plan_creates_structural_comparison_not_stat_forecast(self):
        options = self._r7_options()
        plan = plan_island(self.profile, self.state, **options)
        out = self.analyze(r7_result=plan, r7_options=options)
        self.assertEqual(out.status, '구조 비교 가능 · 수치 예측 보류')
        self.assertTrue(out.construction_verified_for_current_state)
        self.assertGreater(len(out.projections), 0)
        self.assertIsNone(out.measured_island_action)
        self.assertFalse(out.verified_optimal)
        self.assertFalse(out.ml_training_label_verified)

    def _r6(self):
        actions = default_actions()
        actions['섬 트레이닝'] = Action('섬 트레이닝',
             gains={k:10 for k in STATS}, skill_points=5, observed=True)
        avail = {s:'불가' for s in TRAININGS}
        avail['섬 트레이닝']='가능'
        r6 = compare_turn(self.profile, self.state, actions, avail,
                          confirmed_context_hash=state_fingerprint(self.profile,self.state))
        review = {'schema':'uma_r6_turn_review_v1', 'status': r6.status,
                  'context_hash':r6.context_hash, 'evidence_hash':r6.evidence_hash,
                  'ranked':[{'name':x.name,'score':x.score} for x in r6.ranked]}
        return review, actions, avail

    def test_r6_review_links_only_when_provenance_matches(self):
        r6, acts, avail = self._r6()
        out = self.analyze(r6_review=r6, actions=acts, availability=avail)
        self.assertEqual(out.r6_rank, 1)
        self.assertEqual(out.measured_island_action['skill_points'], 5)
        self.assertEqual(out.status, '구조 비교 가능 · R6 실측 연계')

    def test_r6_export_fails_closed_on_stale_actions(self):
        review, actions, available = self._r6()
        result = self.analyze(r6_review=review, actions=actions, availability=available)
        actions['섬 트레이닝'].skill_points += 1
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                export_impact(Path(folder)/'stale.json', self.profile, self.state, result,
                              friendship_counts=self.friends, r6_review=review,
                              actions=actions, availability=available)

    def test_r6_stale_evidence_dropped(self):
        r6, acts, avail = self._r6()
        acts['섬 트레이닝'].skill_points = 55
        out = self.analyze(r6_review=r6, actions=acts, availability=avail)
        self.assertIsNone(out.measured_island_action)

    def test_r6_data_with_no_ticket_never_links(self):
        r6, acts, avail = self._r6()
        self.state.island_tickets = 0
        out = self.analyze(r6_review=r6, actions=acts, availability=avail)
        self.assertIsNone(out.measured_island_action)
        self.assertTrue(any('0장' in c for c in out.cautions))

    def test_multiple_tickets_without_phase_abstains(self):
        self.state.island_tickets = 2
        self.assertTrue(self.analyze().errors)

    def test_invalid_ticket_rejected(self):
        self.state.island_tickets = 5
        self.assertTrue(self.analyze().errors)

    def test_hash_changes_with_friendship_layout(self):
        a = self.analyze()
        self.friends['스피드'] = 3
        b = self.analyze()
        self.assertNotEqual(a.context_hash,b.context_hash)

    def test_export_atomic_and_unverified(self):
        result = self.analyze()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'folder'/'r8.json'
            export_impact(p, self.profile, self.state, result, friendship_counts=self.friends)
            content=json.loads(p.read_text(encoding='utf8'))
            self.assertEqual(content['schema'], 'uma_r8_island_impact_v1')
            self.assertFalse(content['ml_training_label_verified'])
            self.assertTrue(content['experimental_only'])
            self.friends['스피드'] += 1
            with self.assertRaises(ValueError):
                export_impact(p, self.profile, self.state, result, friendship_counts=self.friends)

    def test_export_rejects_stale_turn(self):
        result = self.analyze()
        self.state.remaining_turns = 2
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                export_impact(Path(d)/'stale.json', self.profile, self.state, result, friendship_counts=self.friends)

    def test_coverage_rejects_current_future_prediction(self):
        # Future projections are a frozen same-layout counterfactual, not a growth forecast.
        allbuilt = {s:1 for s in (*STATS,'해변의 집')}
        start = {s:0 for s in allbuilt}
        covered = coverage('미래(가정)','후보1',allbuilt,self.friends,start)
        self.assertEqual(covered.distinct_facilities,2)
        self.assertEqual(len(covered.new_enabled_facilities),2)


if __name__ == '__main__':
    unittest.main()
