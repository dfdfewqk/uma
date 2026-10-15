"""Regression tests for V0.2 integrity and learnable outcome records."""
import json
import sqlite3
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from uma_core import Action, RunProfile, TurnState, STATS, default_actions, rank_actions, input_coverage
from scenario_policies import POLICIES, SCENARIOS
from storage import connect, add_turn, create_run, save_run_outcome, list_runs, export_csv, export_json, backup_database


class V02Tests(unittest.TestCase):
    def test_scenario_registry_loads_independent_config(self):
        self.assertEqual(SCENARIOS['island_post_patch_v1'], POLICIES['island_post_patch_v1'].name)
        self.assertEqual(POLICIES['island_post_patch_v1'].config['data_status'], 'experimental_unvalidated')
        self.assertFalse(POLICIES['island_post_patch_v1'].config['korean_server_numbers_verified'])

    def test_unentered_actions_are_never_ranked(self):
        actions = default_actions()
        actions['스피드'].gains['스피드'] = 43
        self.assertEqual([item.name for item in rank_actions(RunProfile(), TurnState(), actions)], ['스피드'])

    def test_confirmed_real_zero_is_compared(self):
        actions = default_actions()
        actions['휴식'].observed = True
        self.assertEqual(input_coverage(actions), 1)
        self.assertEqual([item.name for item in rank_actions(RunProfile(), TurnState(), actions)], ['휴식'])

    def test_unavailable_island_does_not_get_recommended(self):
        actions = default_actions()
        actions['섬 트레이닝'].observed = True
        actions['섬 트레이닝'].gains['스피드'] = 700
        self.assertEqual(rank_actions(RunProfile(), TurnState(island_tickets=0), actions), [])

    def test_hard_energy_filter(self):
        actions = default_actions()
        actions['스피드'].observed = True
        actions['스피드'].energy_delta = -80
        self.assertEqual(rank_actions(RunProfile(), TurnState(energy=10), actions), [])

    def test_loh_risk_penalty_higher_than_champ(self):
        actions = {'스피드': Action(name='스피드', gains={**dict.fromkeys(STATS, 0), '스피드': 70},
                                   failure_percent=28, observed=True)}
        state = TurnState()
        champ = rank_actions(RunProfile(event='챔피언스 미팅'), state, actions)[0]
        loh = rank_actions(RunProfile(event='리그 오브 히어로즈'), state, actions)[0]
        self.assertLess(loh.score, champ.score)

    def test_old_v01_database_migrates_without_record_loss(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,profile_json TEXT NOT NULL,memo TEXT NOT NULL DEFAULT '')")
            db.execute("INSERT INTO runs (created_at, profile_json) VALUES (?, ?)", ('2026-10-15', '{"character":"테스트"}'))
            db.commit()
            db.close()
            conn = connect(path)
            runs = list_runs(conn)
            self.assertEqual(runs[0]['profile']['character'], '테스트')
            self.assertEqual(runs[0]['outcome'], {})
            self.assertIn('outcome_json', [row[1] for row in conn.execute('PRAGMA table_info(runs)')])
            conn.close()

    def test_completed_and_abandoned_export_and_backup(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite3'
            conn = connect(path)
            good = create_run(conn, asdict(RunProfile(character='완주 캐릭터')))
            quit_run = create_run(conn, asdict(RunProfile(character='중단 캐릭터')))
            state = asdict(TurnState())
            add_turn(conn, good, state, {'휴식': asdict(Action('휴식', observed=True))},
                     [{'name': '휴식', 'score': 1.0}], '휴식')
            save_run_outcome(conn, good, {'status': '육성 완료', 'reason': '', 'final_stats': '1500/1200/1000', 'notes': '실전 시험 전'})
            save_run_outcome(conn, quit_run, {'status': '도축/중단', 'reason': '우정훈련 확보 실패', 'notes': '기록만'})
            result_json = Path(tmp)/'export.json'
            result_csv = Path(tmp)/'export.csv'
            backup = Path(tmp)/'copy.sqlite3'
            export_json(conn, result_json)
            export_csv(conn, result_csv)
            backup_database(conn, backup)
            self.assertEqual(len(json.loads(result_json.read_text('utf-8'))['runs']), 2)
            self.assertIn('우정훈련 확보 실패', result_json.read_text('utf-8'))
            self.assertIn('outcome_status', result_csv.read_text('utf-8-sig'))
            other = connect(backup)
            self.assertEqual(len(list_runs(other)), 2)
            other.close(); conn.close()

    def test_sqlite_backup_releases_windows_file_handle(self):
        # A leaked SQLite backup connection prevents rename and deletion on Windows.
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / 'source.sqlite3')
            try:
                backup = Path(tmp) / 'backup.sqlite3'
                backup_database(conn, backup)
                moved = Path(tmp) / 'renamed.sqlite3'
                backup.rename(moved)
                self.assertTrue(moved.is_file())
                moved.unlink()
            finally:
                conn.close()

    def test_abandon_reason_required(self):
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp)/'x.sqlite3')
            rid = create_run(conn, asdict(RunProfile()))
            with self.assertRaisesRegex(ValueError, '이유'):
                save_run_outcome(conn, rid, {'status': '도축/중단', 'reason': ''})
            conn.close()


if __name__ == '__main__':
    unittest.main()
