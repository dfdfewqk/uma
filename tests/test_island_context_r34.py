"""R34 offline-only synthetic cases; no game footage or ML examples."""
from __future__ import annotations
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from island_context_r34 import PlanningInputs, assess_island_context, STATS

ROOT=Path(__file__).resolve().parents[1]


def sample():
    p=SimpleNamespace(scenario='island_post_patch_v1',event='챔피언스 미팅',
                      target_stats={s:1500 for s in STATS})
    st=SimpleNamespace(remaining_turns=30,stats={s:800 for s in STATS},
        island_tickets=1,turns_until_next_ticket=2,development_points=100,
        core_skill_status='미확인',
        building_levels={**{k:2 for k in STATS},'해변의 집':1})
    return p,st


class R34PlanningTests(unittest.TestCase):
    def audit(self, **options):
        return assess_island_context(*sample(), PlanningInputs(**options))

    def test_unknown_inputs_are_not_inferred(self):
        x=self.audit()
        self.assertIn('판단 보류',x.status)
        self.assertIsNone(x.free_turn_upper_bound)
        self.assertIsNone(x.optimal_action)
        self.assertFalse(x.modifies_r6_scores)
        self.assertFalse(x.trained_model)
        self.assertIn('티켓 사용 단계',' '.join(x.missing))

    def test_initial_ticket_exemption_is_not_suppressed(self):
        x=self.audit(ticket_phase='첫 1~2회',bond_phase='인연 확보 중',friendship_locations=0)
        self.assertIn('우정 3곳 미만을 일률적으로 배제하지 않습니다',' '.join(x.checks))

    def test_later_ticket_checks_friendship_without_optimality_claim(self):
        x=self.audit(ticket_phase='이후',bond_phase='우정 준비됨',friendship_locations=3)
        self.assertIn('비교 후보',' '.join(x.checks))
        self.assertIsNone(x.optimal_action)
        y=self.audit(ticket_phase='이후',friendship_locations=1)
        self.assertIn('만료·중복',' '.join(y.checks))

    def test_races_and_outings_have_resource_conflict(self):
        x=self.audit(mandatory_races_remaining=27,planned_outings_remaining=3,
                     turns_to_next_mandatory_race=1)
        self.assertEqual(x.free_turn_upper_bound,3)
        self.assertIn('일정 충돌 가능',' '.join(x.cautions))
        self.assertIn('다음 턴 필수 레이스',' '.join(x.cautions))

    def test_ticket_zero_excludes_island_without_recommendation(self):
        p,s=sample();s.island_tickets=0
        x=assess_island_context(p,s,PlanningInputs(ticket_phase='이후',friendship_locations=5))
        self.assertIn('섬 티켓 0개',' '.join(x.checks))
        self.assertFalse(any('비교 후보' in v for v in x.checks))

    def test_unconfirmed_facilities_are_not_assumed(self):
        p,s=sample();s.building_levels['해변의 집']=9
        out=assess_island_context(p,s,PlanningInputs())
        self.assertIn('시설 단계 사용자 확인',' '.join(out.missing))
        with self.assertRaises(ValueError):
            assess_island_context(p,s,PlanningInputs(facility_levels_confirmed=True))

    def test_growth_rates_require_complete_data(self):
        x=self.audit(growth_rates={s:20 for s in STATS})
        self.assertNotIn('성장률 5종',' '.join(x.missing))
        with self.assertRaises(ValueError):
            self.audit(growth_rates={'스피드':0})

    def test_bool_and_out_of_range_numbers_do_not_pass(self):
        cases=(('friendship_locations',True),('mandatory_races_remaining',31),
               ('turns_to_next_mandatory_race',-2),('planned_outings_remaining',100))
        for key,value in cases:
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.audit(**{key:value})

    def test_unknown_game_scenario_not_claimed_supported(self):
        p,s=sample();p.scenario='other'
        with self.assertRaises(ValueError):
            assess_island_context(p,s,PlanningInputs())
        p.scenario='island_post_patch_v1';p.event='평가점'
        with self.assertRaises(ValueError):
            assess_island_context(p,s,PlanningInputs())

    def test_full_context_is_advisory_only_and_does_not_mutate(self):
        p,s=sample()
        context=PlanningInputs(ticket_phase='이후',bond_phase='우정 준비됨',
            friendship_locations=3,mandatory_races_remaining=3,
            turns_to_next_mandatory_race=2,planned_outings_remaining=2,
            growth_rates={k:10 for k in STATS},facility_levels_confirmed=True)
        before=json.dumps(asdict(context),sort_keys=True)
        output=assess_island_context(p,s,context)
        self.assertFalse(output.missing)
        self.assertEqual(output.free_turn_upper_bound,27)
        self.assertEqual(json.dumps(asdict(context),sort_keys=True),before)
        self.assertIsNone(output.optimal_action)

    def test_gui_connected_without_touching_legacy_score(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn("IslandContextPanel(self.page_context_r34",app)
        self.assertIn("R34 무인도 조건",app)
        panel=(ROOT/'island_context_ui_r34.py').read_text(encoding='utf-8')
        self.assertNotIn('rank_actions(',panel)
        self.assertNotIn('compare_turn(',panel)
        self.assertNotIn('save_run',panel)


if __name__=='__main__':
    unittest.main()
