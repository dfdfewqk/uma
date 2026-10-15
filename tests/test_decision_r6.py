"""Synthetic, non-gameplay R6 regression checks; no claims of official balance data."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from uma_core import Action, RunProfile, STATS, TRAININGS, TurnState
from decision_r6 import (AVAILABLE, UNAVAILABLE, UNKNOWN, SCHEMA, compare_turn,
                         export_comparison, state_fingerprint)


def evidence(name, **kwargs):
    data = dict(gains=dict.fromkeys(STATS, 0), skill_points=0, energy_delta=0,
                friend_types=0, bond_gain=0, failure_percent=0.0,
                development_points=0, observed=True)
    data.update(kwargs)
    return Action(name=name, **data)


class DecisionR6Tests(unittest.TestCase):
    def setUp(self):
        self.profile = RunProfile()
        self.state = TurnState(energy=50, island_tickets=0, turns_until_next_ticket=-1)
        self.actions = {}
        for name in STATS:
            gains = dict.fromkeys(STATS, 0)
            gains[name] = 40
            self.actions[name] = evidence(name, gains=gains, energy_delta=-13,
                                           skill_points=23, bond_gain=5)
        self.actions['휴식'] = evidence('휴식', energy_delta=48)
        self.actions['외출'] = evidence('외출', energy_delta=30)
        self.actions['레이스'] = evidence('레이스', skill_points=60, development_points=20, energy_delta=-9)
        self.actions['섬 트레이닝'] = evidence('섬 트레이닝', friend_types=3,
                                               gains={s: 60 for s in STATS}, energy_delta=-15)
        self.statuses = {name: (AVAILABLE if name != '섬 트레이닝' else UNKNOWN) for name in TRAININGS}

    def compare(self):
        return compare_turn(self.profile, self.state, self.actions, self.statuses,
                            confirmed_context_hash=state_fingerprint(self.profile, self.state))

    def test_complete_every_available_choice_compared(self):
        out = self.compare()
        self.assertIn(out.status, ('전체 행동 비교 가능 (실험값)', '선택지 경합 · 추가 검토'))
        self.assertEqual({a.name for a in out.ranked}, set(STATS) | {'휴식', '외출', '레이스'})
        self.assertFalse(out.verified_optimal)

    def test_unknown_rest_blocks_even_with_all_training_values(self):
        self.statuses['휴식'] = UNKNOWN
        out = self.compare()
        self.assertEqual(out.status, '추천 보류')
        self.assertIn('휴식', out.missing)
        self.assertFalse(out.ranked)

    def test_explicit_unavailable_race_allows_comparison(self):
        self.statuses['레이스'] = UNAVAILABLE
        out = self.compare()
        self.assertNotEqual(out.status, '추천 보류')
        self.assertNotIn('레이스', [x.name for x in out.ranked])

    def test_ticket_positive_requires_island_review(self):
        self.state.island_tickets = 1
        out = self.compare()
        self.assertIn('섬 트레이닝', out.missing)
        self.statuses['섬 트레이닝'] = AVAILABLE
        out = self.compare()
        self.assertEqual(len(out.ranked), 9)
        self.assertIn('티켓', out.status)
        self.assertTrue(any('티켓' in x for x in out.cautions))

    def test_r27_first_ticket_exception_disclosed(self):
        self.state.island_tickets = 1
        self.state.turns_until_next_ticket = 2
        self.statuses['섬 트레이닝'] = AVAILABLE
        out = self.compare()
        self.assertTrue(any('첫 티켓' in c for c in out.cautions))
        self.assertFalse(out.verified_optimal)

    def test_known_ticket_timing_allows_full_comparison(self):
        self.state.island_tickets = 1
        self.state.turns_until_next_ticket = 2
        self.statuses['섬 트레이닝'] = AVAILABLE
        out = self.compare()
        self.assertNotIn('미확인', out.status)

    def test_island_cannot_be_available_without_ticket(self):
        self.statuses['섬 트레이닝'] = AVAILABLE
        self.assertIn('섬 트레이닝', self.compare().missing)

    def test_unconfirmed_zero_value_does_not_imply_observed(self):
        self.actions['휴식'] = Action(name='휴식')
        self.assertIn('휴식', self.compare().missing)
        self.actions['휴식'].observed = True
        self.assertNotIn('휴식', self.compare().missing)

    def test_changed_turn_requires_reconfirmation(self):
        old = state_fingerprint(self.profile, self.state)
        self.state.energy = 49
        out = compare_turn(self.profile, self.state, self.actions, self.statuses,
                           confirmed_context_hash=old)
        self.assertIn('턴 상태', out.missing)
        self.assertFalse(out.ranked)

    def test_changed_goal_requires_reconfirmation(self):
        old = state_fingerprint(self.profile, self.state)
        self.profile.target_stats['스피드'] += 10
        out = compare_turn(self.profile, self.state, self.actions, self.statuses,
                           confirmed_context_hash=old)
        self.assertIn('턴 상태', out.missing)

    def test_nan_failure_rate_rejected(self):
        self.actions['파워'].failure_percent = float('nan')
        self.assertIn('파워', self.compare().missing)

    def test_invalid_stat_gain_rejected(self):
        self.actions['지능'].gains['지능'] = 9999
        self.assertIn('지능', self.compare().missing)

    def test_wrong_action_identity_rejected(self):
        self.actions['스피드'].name = '파워'
        self.assertIn('스피드', self.compare().missing)

    def test_energy_impossible_flags_error(self):
        self.state.energy = 5
        self.actions['스피드'].energy_delta = -20
        self.assertIn('스피드', self.compare().missing)

    def test_recovery_capped_at_100(self):
        self.state.energy = 95
        self.actions['휴식'].energy_delta = 60
        out = self.compare()
        heal = next(x for x in out.ranked if x.name == '휴식')
        self.assertTrue(any('55' in x for x in heal.reasons))
        self.assertAlmostEqual(heal.breakdown['체력 변화'], 5 * (0.24 + 0.88 * 0.0))

    def test_future_energy_penalty(self):
        self.state.energy = 35
        self.actions['파워'].energy_delta = -15
        out = self.compare()
        power = next(x for x in out.ranked if x.name == '파워')
        self.assertLess(power.breakdown['R6 다음 턴 저체력 위험(가정)'], 0)

    def test_early_bond_future_value(self):
        self.state.remaining_turns = 45
        self.actions['스피드'].bond_gain = 30
        out = self.compare()
        speed = next(x for x in out.ranked if x.name == '스피드')
        self.assertGreater(speed.breakdown['R6 초반 인연도 미래가치(가정)'], 0)
        self.state.remaining_turns = 3
        out = self.compare()
        speed = next(x for x in out.ranked if x.name == '스피드')
        self.assertEqual(speed.breakdown['R6 초반 인연도 미래가치(가정)'], 0)

    def test_loh_failure_risk_penalty_is_more_conservative(self):
        self.actions['스피드'].failure_percent = 30
        a = next(x for x in self.compare().ranked if x.name == '스피드')
        self.profile.event = '리그 오브 히어로즈'
        b = next(x for x in self.compare().ranked if x.name == '스피드')
        self.assertLess(b.score, a.score)

    def test_tie_prompts_review(self):
        for name in self.actions:
            self.actions[name] = evidence(name)
        out = self.compare()
        self.assertEqual(out.status, '선택지 경합 · 추가 검토')
        self.assertTrue(out.cautions)

    def test_invalid_event_blocks(self):
        self.profile.event = '평가점 육성'
        self.assertIn('육성 목적', self.compare().missing)

    def test_export_with_accurate_experimental_labels(self):
        out = self.compare()
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'subdir' / 'r6.json'
            export_comparison(dest, self.profile, self.state, self.actions, self.statuses, out)
            raw = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(raw['schema'], SCHEMA)
            self.assertEqual(raw['availability']['레이스'], AVAILABLE)
            self.assertFalse(raw['ml_training_label_verified'])
            self.assertTrue(raw['experimental_only'])
            self.state.energy = 3
            with self.assertRaises(ValueError):
                export_comparison(dest, self.profile, self.state, self.actions, self.statuses, out)

    def test_export_refuses_changed_action_after_scoring(self):
        result = self.compare()
        self.actions['스피드'].gains['스피드'] += 1
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                export_comparison(Path(d)/'stale.json', self.profile, self.state,
                                  self.actions, self.statuses, result)

    def test_no_options_blocks(self):
        self.statuses = {name: UNAVAILABLE for name in TRAININGS}
        self.assertIn('선택지', self.compare().missing)

    def test_unknown_action_status_rejected(self):
        self.statuses['스피드'] = 'maybe'
        self.assertIn('스피드', self.compare().missing)

    def test_profile_scenario_excluded(self):
        self.profile.scenario = 'unregistered'
        self.assertIn('시나리오', self.compare().missing)


if __name__ == '__main__':
    unittest.main()
