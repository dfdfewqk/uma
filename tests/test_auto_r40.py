"""R40 synthetic contract tests only; never imply a live Korean game test."""
import tempfile
import unittest
from pathlib import Path
from target_selector_r39 import Target,KINDS,STYLES,round_label,kind_for_round,load_courses
from auto_core_r40 import (AutomationConfig,AutomationProgress,TPView,
    advise_tp,save_progress,load_progress,actuate_game)
from turn_policy_r40 import (TurnOption,TurnEvidence,suggest_turn,score_option,
    EventOption,choose_event,retry_skill_options)
from decision_contract_r39 import SkillCondition
from evidence_store_r40 import TurnObservation,append_turn,read_turns

def stats(n):
    return {k:n for k in ('스피드','스태미나','파워','근성','지능')}

class FourCombinedEvents(unittest.TestCase):
    def test_exact_one_event_per_round(self):
        self.assertEqual([kind_for_round(i) for i in range(1,5)],
                         [KINDS[0],KINDS[1],KINDS[0],KINDS[0]])
        self.assertEqual([round_label(i).split(' · ')[1] for i in range(1,5)],
                         ['챔미','리오히','챔미','챔미'])
        with self.assertRaises(ValueError):Target(KINDS[0],2,'선입').validate()

    def test_first_kr_course_secondary_two_sources(self):
        data=load_courses()
        self.assertEqual(list(data),['cm-1'])
        self.assertEqual(data['cm-1']['meters'],2200)
        self.assertFalse(data['cm-1']['official_confirmed'])
        self.assertEqual(data['cm-1']['evidence_level'],'secondary_two_sources')

class RepeatAutomationTests(unittest.TestCase):
    def cfg(self,num=3):
        return AutomationConfig(Target(KINDS[1],2,'추입'),num,
                                'uma-original','deck-six-cards','parent-set')

    def test_same_setup_and_outcome_counts(self):
        state=AutomationProgress(self.cfg()).arm()
        for i,outcome in enumerate(('disposed','good','failed')):
            self.assertEqual(advise_tp(TPView(30,30,0,0,True)).action,'start_run')
            state.begin(f'run-{i}',TPView(30,30,0,0,True))
            with self.assertRaises(ValueError):
                state.finish(f'run-{i}',outcome,False)
            state.finish(f'run-{i}',outcome,True)
        self.assertEqual(state.phase,'finished')
        self.assertEqual(state.remaining,0)
        self.assertEqual(list(state.outcomes.values()),['disposed','good','failed'])
        with self.assertRaises(ValueError):
            state.begin('extra',TPView(30,30,0,0,True))

    def test_journal_roundtrip_and_no_duplicate_id(self):
        state=AutomationProgress(self.cfg(1)).arm()
        state.begin('run-1',TPView(30,30,0,0,True))
        state.finish('run-1','ordinary',True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            save_progress(path,state)
            clone=load_progress(path)
            self.assertEqual(clone.as_json(),state.as_json())

    def test_tp_free_item_and_wait_policy(self):
        self.assertEqual(advise_tp(TPView(None,30,1,30,False)).action,'wait_verification')
        self.assertEqual(advise_tp(TPView(3,30,1,30,True)).action,'use_tp_item')
        self.assertEqual(advise_tp(TPView(3,30,0,30,True)).action,'wait_tp')
        self.assertEqual(advise_tp(TPView(30,30,1,30,True)).action,'start_run')

    def test_never_click_real_game_before_verification(self):
        with self.assertRaises(RuntimeError):
            actuate_game('training','unverified_coords')

class TurnDecisionTests(unittest.TestCase):
    def ctx(self,near=False,mandatory=False):
        return TurnEvidence(stats(950 if near else 100),stats(1000),75,
                            mandatory,True,True,'reviewed_game_screenshot')

    def test_verified_training_vs_race_and_next_turn_race(self):
        training=TurnOption('훈련','training',skill_pt=5,
            next_turn_training_bonus=100,verified=True)
        race=TurnOption('레이스','race',skill_pt=8,verified=True)
        self.assertGreater(score_option(self.ctx(mandatory=False),training),
                           score_option(self.ctx(mandatory=False),race))
        self.assertLess(score_option(self.ctx(mandatory=True),training),
                        score_option(self.ctx(mandatory=True),race))
        self.assertEqual(suggest_turn(self.ctx(mandatory=False),[training,race]).action,'훈련')
        self.assertEqual(suggest_turn(self.ctx(mandatory=True),[training,race]).action,'레이스')

    def test_unknown_action_abstains(self):
        one=TurnOption('스피드','training',skill_pt=90,verified=True)
        two=TurnOption('레이스','race',skill_pt=10,verified=False)
        self.assertIsNone(suggest_turn(self.ctx(),[one,two]).action)
        unverified=TurnEvidence(stats(100),stats(1000),50,False,True,False)
        self.assertIsNone(suggest_turn(unverified,[one,one]).action)

    def test_gold_chain_and_terminal_award(self):
        options=[EventOption('조기 종료','support-A',True,False,'different',9),
                 EventOption('연속 진행','support-A',True,True,'goldA',4)]
        self.assertEqual(choose_event(options,'goldA')[0],'연속 진행')
        last=[EventOption('스킬 획득','support-B',True,False,'goldA',2,True),
              EventOption('다른 스킬','support-B',True,False,'goldB',9,True)]
        self.assertEqual(choose_event(last,'goldA')[0],'스킬 획득')

    def test_retry_skill_distance_and_style(self):
        skills=[(SkillCondition('마일 추입',distance='마일',style='추입',verified=True),7),
                (SkillCondition('중거리 추입',distance='중거리',style='추입',verified=True),15),
                (SkillCondition('마일 도주',distance='마일',style='도주',verified=True),25),
                (SkillCondition('미검증',verified=False),99)]
        self.assertEqual(retry_skill_options(skills,style='추입',distance='마일',
                                             surface='잔디',consecutive_losses=2,
                                             remaining_retries=3),('마일 추입',))
        self.assertEqual(retry_skill_options(skills,style='추입',distance='마일',
                                             surface='잔디',consecutive_losses=1,
                                             remaining_retries=3),())

class EvidenceTests(unittest.TestCase):
    def test_unreviewed_record_never_trains(self):
        row=TurnObservation('run1','turn1','island_post_patch_v1','KR-patch',
                             'screen_candidate',False,'훈련',False)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'turns.jsonl'
            result=append_turn(p,row)
            self.assertFalse(result['training_ready'])
            self.assertFalse(result['review_candidate'])
            self.assertEqual(len(read_turns(p)),1)

if __name__=='__main__':
    unittest.main()
