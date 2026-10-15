import csv
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from uma_core import Action, RunProfile, TurnState
from dataset import export_decisions_csv
from storage import connect, create_run, add_turn, save_run_outcome


class DatasetTests(unittest.TestCase):
    def test_skip_missing_label_preserve_only_observed_chosen(self):
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp)/'test.sqlite3')
            rid = create_run(conn, asdict(RunProfile()))
            opts = {'스피드': asdict(Action('스피드', observed=True)),
                    '지능': asdict(Action('지능', observed=True))}
            for choice in ('미선택', '스피드', '외출'):
                add_turn(conn, rid, asdict(TurnState()), opts, [], choice)
            save_run_outcome(conn, rid, {'status':'도축/중단', 'reason':'샘플 기록'})
            csv_path = Path(tmp)/'out.csv'
            result = export_decisions_csv(conn, csv_path)
            self.assertEqual(result, {'exported': 1, 'skipped': 2})
            with csv_path.open('r', encoding='utf-8-sig', newline='') as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(rows[0]['human_chosen_action'], '스피드')
            self.assertEqual(rows[0]['outcome_status_for_audit_only'], '도축/중단')
            self.assertEqual(rows[0]['quality_warning'], 'manual_observation_unverified')
            conn.close()


if __name__ == '__main__':
    unittest.main()
