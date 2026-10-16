"""R41 fixture replay and R40 guard regression tests; game always closed."""
from __future__ import annotations
import json
from pathlib import Path
import unittest
from auto_core_r40 import AutomationProgress,AutomationConfig,TPView,advise_tp
from target_selector_r39 import Target,KINDS
from offline_replay_r41 import replay_case,SCHEMA
from turn_policy_r40 import TurnEvidence,TurnOption,suggest_turn

FIXTURE=Path(__file__).resolve().parents[1]/'research'/'r41_synthetic_replay.json'

class OfflineReplayR41Tests(unittest.TestCase):
    def case(self):
        return json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_four_turns_and_three_complete_runs_are_synthetic(self):
        report=replay_case(self.case())
        self.assertEqual(report['turn_count'],4)
        self.assertEqual(report['simulated_repetitions'],3)
        self.assertEqual(report['remaining'],0)
        self.assertTrue(report['synthetic_only'])
        self.assertFalse(report['game_opened'])
        self.assertFalse(report['game_clicked'])
        self.assertFalse(report['trained_model'])
        self.assertEqual(report['real_training_samples'],0)
        self.assertEqual(list(report['simulated_outcomes'].values()),['good','disposed','failed'])
        self.assertEqual([t['hypothetical_top'] for t in report['turns']],
                         ['일반 레이스','스킬 Pt 레이스','외출','휴식'])
        self.assertTrue(all(t['real_game_action'] is None for t in report['turns']))

    def test_mock_must_not_be_deemed_live_verified(self):
        mock=self.case()
        mock['origin']='reviewed_game_screenshot'
        with self.assertRaises(ValueError):replay_case(mock)
        mock=self.case()
        mock['target']={'round':2,'style':'도주','kind':'리그 오브 히어로즈'}
        with self.assertRaises(ValueError):replay_case(mock)

    def test_stale_action_and_bad_simulation_rejected(self):
        for mistake in ('bad-outcome','bad-round','bad-turn'):
            mock=self.case()
            if mistake=='bad-outcome':
                mock['simulated_outcomes']=['good','disposed','unknown']
            elif mistake=='bad-round':
                mock['target']['round']=5
            else:
                mock['turns'][0]['options']=[{'name':'훈련','kind':'training','verified':True}]
            with self.subTest(mistake=mistake),self.assertRaises(ValueError):
                replay_case(mock)

    def test_tp_unknown_item_remains_unverified(self):
        self.assertEqual(advise_tp(TPView(5,30,None,None,True)).action,'wait_verification')
        self.assertEqual(advise_tp(TPView(5,30,1,20,True)).action,'use_tp_item')
        with self.assertRaises(ValueError):advise_tp(TPView(40,30,1,10,True,tp_cap=30))

    def test_automation_progress_invalid_phase_does_not_resume(self):
        cfg=AutomationConfig(Target(KINDS[0],1,'선입'),1,
                             'character','deck','inheritance')
        corrupted=AutomationProgress(cfg,phase='setup',pending_run_id='run1')
        with self.assertRaises(ValueError):corrupted.validate()
        corrupted=AutomationProgress(cfg,phase='finished')
        with self.assertRaises(ValueError):corrupted.validate()

    def test_simulated_screen_cannot_bypass_live_gate(self):
        ctx=TurnEvidence({x:900 for x in ('스피드','스태미나','파워','근성','지능')},
            {x:1000 for x in ('스피드','스태미나','파워','근성','지능')},
            energy=80,next_turn_mandatory_race=False,all_actions_visible=True,
            verified=False,source='synthetic_test')
        options=[TurnOption('훈련','training',skill_pt=25,verified=True),
                 TurnOption('레이스','race',skill_pt=22,verified=True)]
        self.assertIsNone(suggest_turn(ctx,options).action)

if __name__=='__main__':
    unittest.main()
