import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from uma_core import (RunProfile, TurnState, Action, STATS, default_actions,
                      rank_actions, input_coverage, assess_run, IslandPostPatchPolicy)
from storage import connect, create_run, add_turn, export_json, export_csv, list_turns


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.p = RunProfile()
        self.s = TurnState()
        self.actions = default_actions()

    def test_empty_options_not_presented_as_valid_confidence(self):
        self.assertEqual(input_coverage(self.actions), 0)

    def test_more_gains_rank_higher(self):
        self.actions['스피드'].gains['스피드'] = 70
        self.actions['파워'].gains['파워'] = 15
        self.assertEqual(rank_actions(self.p, self.s, self.actions)[0].name, '스피드')

    def test_empty_ticket_disables_island_training(self):
        self.actions['섬 트레이닝'].gains['스피드'] = 2000
        ranked = {r.name: r for r in rank_actions(self.p, self.s, self.actions)}
        self.assertNotIn('섬 트레이닝', ranked)

    def test_ticket_and_many_friend_types_improve_island(self):
        self.s.island_tickets = 1
        a = self.actions['섬 트레이닝']
        a.gains = {s: 30 for s in STATS}
        a.friend_types = 1
        before = {r.name: r.score for r in rank_actions(self.p, self.s, self.actions)}['섬 트레이닝']
        a.friend_types = 4
        after = {r.name: r.score for r in rank_actions(self.p, self.s, self.actions)}['섬 트레이닝']
        self.assertGreater(after, before)

    def test_energy_impossible_training_rank_penalty(self):
        self.s.energy = 4
        self.actions['스피드'].gains['스피드'] = 300
        self.actions['스피드'].energy_delta = -40
        ranked = {r.name: r for r in rank_actions(self.p, self.s, self.actions)}
        self.assertNotIn('스피드', ranked)

    def test_assess_does_not_unconditionally_recommend_quitting(self):
        self.s.remaining_turns = 3
        result, reason = assess_run(self.p, self.s)
        self.assertIn('주의', result)
        self.assertTrue(any('도축은 추천하지 않습니다' in x for x in reason))

    def test_scenario_policy_exists(self):
        self.assertIn('JP-after-2025-06-30', IslandPostPatchPolicy.version)

    def test_db_roundtrip_exports(self):
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / 'testing.sqlite3')
            rid = create_run(conn, self.p.__dict__)
            ranked = rank_actions(self.p, self.s, self.actions)
            tid = add_turn(conn, rid, self.s.__dict__, {k: v.__dict__ for k,v in self.actions.items()},
                           [r.__dict__ for r in ranked], '휴식', '테스트')
            self.assertGreater(tid, 0)
            self.assertEqual(list_turns(conn, rid)[0]['chosen_action'], '휴식')
            jp = Path(tmp) / 'data.json'
            cp = Path(tmp) / 'data.csv'
            export_json(conn, jp)
            export_csv(conn, cp)
            self.assertIn('휴식', jp.read_text('utf-8'))
            self.assertIn('run_id', cp.read_text('utf-8-sig'))
            conn.close()


if __name__ == '__main__':
    unittest.main()
