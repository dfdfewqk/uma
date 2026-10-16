"""Synthetic-only R43 pipeline tests; no actual game, EXE, or network."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from evidence_store_r40 import read_turns
from replay_pipeline_r43 import run_offline_pipeline


def fixture():
    turns=[]
    for i in range(4):
        turns.append({
            'stats': {'스피드': 100+i*10,'스태미나':110,
                      '파워':120,'근성':130,'지능':140},
            'energy': 70-i*5, 'all_actions_visible':True,
            'options':[{'name':'훈련','kind':'training','verified':True},
                       {'name':'휴식','kind':'rest','verified':True}],
        })
    return {'schema':'uma_r41_synthetic_replay_v1','origin':'synthetic_test','turns':turns}


def mock_replay(value):
    return {'schema':'uma_r41_synthetic_replay_report_v1',
            'synthetic_only':True,'game_opened':False,'game_clicked':False,
            'trained_model':False,'real_training_samples':0,
            'turn_count':len(value['turns']),'remaining':0,
            'turns':[{'turn':i+1,'hypothetical_top':'훈련',
                      'real_game_action':None,'ranked_hypothesis':[['훈련',10],['휴식',2]]}
                     for i in range(len(value['turns']))]}


class TestR43Pipeline(unittest.TestCase):
    def test_append_only_transitions_and_last_pending(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            report=run_offline_pipeline(fixture(),path,replay=mock_replay)
            self.assertEqual(report.appended_records,3)
            self.assertEqual(report.reused_records,0)
            self.assertEqual(report.pending_final_turn,4)
            self.assertEqual(report.recorded_hypotheses,('훈련',)*3)
            self.assertEqual(report.real_game_actions,0)
            self.assertEqual(report.ml_training_samples,0)
            rows=read_turns(path)
            self.assertEqual(len(rows),3)
            self.assertTrue(all(x['training_ready'] is False for x in rows))
            self.assertTrue(all(x['record']['chosen_action'] is None for x in rows))
            self.assertTrue(all(x['record']['outcome_verified'] is False for x in rows))
            self.assertTrue(all(x['record']['after']['no_verified_effect'] for x in rows))

    def test_repeat_idempotent_no_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            run_offline_pipeline(fixture(),path,replay=mock_replay)
            raw=path.read_bytes()
            second=run_offline_pipeline(fixture(),path,replay=mock_replay)
            self.assertEqual(second.reused_records,3)
            self.assertEqual(second.appended_records,0)
            self.assertEqual(path.read_bytes(),raw)

    def test_changed_existing_turn_refused_without_overwriting(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            run_offline_pipeline(fixture(),path,replay=mock_replay)
            raw=path.read_bytes()
            new=fixture()
            new['turns'][0]['energy']=50
            with self.assertRaises(ValueError):
                run_offline_pipeline(new,path,replay=mock_replay)
            self.assertEqual(path.read_bytes(),raw)

    def test_late_conflict_prevents_partial_new_records(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            run_offline_pipeline(fixture(),path,replay=mock_replay)
            third=path.read_text(encoding='utf-8').splitlines()[2]
            path.write_text(third+'\n',encoding='utf-8')
            before=path.read_bytes()
            new=fixture()
            new['turns'][2]['energy']=9
            with self.assertRaises(ValueError):
                run_offline_pipeline(new,path,replay=mock_replay)
            self.assertEqual(path.read_bytes(),before)

    def test_unverified_option_is_blocked_not_logged(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            sample=fixture()
            sample['turns'][1]['options'][0]['verified']=False
            report=run_offline_pipeline(sample,path,replay=mock_replay)
            self.assertEqual(report.blocked_turns,(2,))
            self.assertEqual(report.appended_records,2)
            self.assertEqual(len(read_turns(path)),2)

    def test_never_promote_fake_game_click_or_training(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            invalid=fixture()
            invalid['origin']='reviewed_game_screenshot'
            with self.assertRaises(ValueError):
                run_offline_pipeline(invalid,path,replay=mock_replay)
            def bad_replay(x):
                out=mock_replay(x)
                out['turns'][0]['real_game_action']='훈련'
                return out
            with self.assertRaises(ValueError):
                run_offline_pipeline(fixture(),path,replay=bad_replay)
            self.assertFalse(path.exists())
            def claimed_training(x):
                out=mock_replay(x)
                out['trained_model']=True
                return out
            with self.assertRaises(ValueError):
                run_offline_pipeline(fixture(),path,replay=claimed_training)

    def test_other_run_id_keeps_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            run_offline_pipeline(fixture(),path,run_id='alpha',replay=mock_replay)
            run_offline_pipeline(fixture(),path,run_id='beta',replay=mock_replay)
            self.assertEqual(len(read_turns(path)),6)

    def test_single_turn_remains_pending_without_log(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            data=fixture()
            data['turns']=data['turns'][:1]
            report=run_offline_pipeline(data,path,replay=mock_replay)
            self.assertEqual(report.appended_records,0)
            self.assertEqual(report.pending_final_turn,1)
            self.assertFalse(path.exists())

    def test_refuses_corrupt_existing_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'turns.jsonl'
            run_offline_pipeline(fixture(),path,replay=mock_replay)
            row=path.read_text(encoding='utf-8').splitlines()[0]
            with path.open('a',encoding='utf-8') as f:
                f.write(row+'\n')
            with self.assertRaises(ValueError):
                run_offline_pipeline(fixture(),path,replay=mock_replay)


class TestActualR41Adapter(unittest.TestCase):
    def test_repo_fixture_connects_without_real_actions(self):
        """Runs against actual R41 implementation in the complete repository."""
        import json
        source_path=Path(__file__).resolve().parents[1]/'research'/'r41_synthetic_replay.json'
        source=json.loads(source_path.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            report=run_offline_pipeline(source,Path(td)/'roundtrip.jsonl')
            self.assertTrue(report.synthetic_only)
            self.assertEqual(report.turns_in_fixture,4)
            self.assertEqual(report.appended_records,3)
            self.assertEqual(report.pending_final_turn,4)
            self.assertEqual(report.real_game_actions,0)
            self.assertEqual(report.ml_training_samples,0)


if __name__=='__main__':
    unittest.main()
