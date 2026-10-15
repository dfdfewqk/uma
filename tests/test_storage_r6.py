"""Checks old v0.5 databases migrate without losing existing runs."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict

from uma_core import RunProfile, TurnState
from storage import connect, create_run, add_turn, list_turns, export_json, SCHEMA_VERSION


class R6DatabaseTests(unittest.TestCase):
    def test_r6_payload_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'runs.sqlite3'
            conn = connect(path)
            rid = create_run(conn, asdict(RunProfile()))
            r6 = {'schema': 'uma_r6_turn_review_v1', 'availability': {'스피드': '가능'},
                  'experimental_only': True, 'ml_training_label_verified': False}
            add_turn(conn, rid, asdict(TurnState()), {}, [], '스피드', r6_review=r6)
            self.assertEqual(list_turns(conn, rid)[0]['r6_review'], r6)
            report = Path(td) / 'runs.json'
            export_json(conn, report)
            doc = json.loads(report.read_text(encoding='utf8'))
            self.assertEqual(doc['schema_version'], SCHEMA_VERSION)
            self.assertEqual(doc['runs'][0]['turns'][0]['r6_review'], r6)
            conn.close()

    def test_upgrade_from_legacy_turn_table_keeps_data(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'old.sqlite3'
            c = sqlite3.connect(path)
            c.executescript('''
              CREATE TABLE runs (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                profile_json TEXT NOT NULL, memo TEXT NOT NULL DEFAULT '',
                outcome_json TEXT NOT NULL DEFAULT '{}');
              CREATE TABLE turns (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
                created_at TEXT NOT NULL, state_json TEXT NOT NULL, options_json TEXT NOT NULL,
                recommendations_json TEXT NOT NULL, chosen_action TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '');
              INSERT INTO runs VALUES (1, 'date', '{}', '', '{}');
              INSERT INTO turns VALUES (1, 1, 'date', '{}', '{}', '[]', '휴식', 'old');
            ''')
            c.commit()
            c.close()
            c = connect(path)
            rows = list_turns(c, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['chosen_action'], '휴식')
            self.assertEqual(rows[0]['note'], 'old')
            self.assertEqual(rows[0]['r6_review'], {})
            self.assertIn('r6_review_json', [x[1] for x in c.execute('PRAGMA table_info(turns)')])
            c.close()

if __name__ == '__main__':
    unittest.main()
