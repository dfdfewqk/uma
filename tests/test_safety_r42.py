"""R42 local/synthetic safety tests (no Windows game involved)."""
from __future__ import annotations
import unittest
import random
from decision_contract_r39 import SkillCondition
from skill_budget_r42 import SkillOffer, plan_retry_purchase
from intent_gate_r42 import ObservedFrame, IntentGate, send_game_input
from turn_policy_r40 import TurnEvidence, TurnOption


class TestSkillBudget(unittest.TestCase):
    def test_budget_filters(self):
        offers=[
            SkillOffer(SkillCondition('마일 추입',distance='마일',style='추입',verified=True),140,80,
                       price_verified=True,offered_on_screen=True),
            SkillOffer(SkillCondition('마일 도주',distance='마일',style='도주',verified=True),50,100,
                       price_verified=True,offered_on_screen=True),
            SkillOffer(SkillCondition('미확인',verified=False),20,999,
                       price_verified=True,offered_on_screen=True),
            SkillOffer(SkillCondition('마일 둘째',distance='마일',style='추입',verified=True),120,90,
                       price_verified=True,offered_on_screen=True)]
        plan=plan_retry_purchase(
            offers,style='추입',distance='마일',surface='잔디',skill_points=170,
            consecutive_losses=2,remaining_retries=3,
            current_race_verified=True,skill_page_verified=True)
        self.assertEqual(plan.skills,('마일 둘째',))
        self.assertEqual(plan.remaining_sp,50)
        self.assertTrue(plan.proposal_only)

    def test_unknown_points_blocks(self):
        self.assertFalse(plan_retry_purchase(
            [],style='도주',distance=None,surface=None,skill_points=None,
            consecutive_losses=2,remaining_retries=3,current_race_verified=True,
            skill_page_verified=True).skills)

    def test_not_two_losses_blocks(self):
        self.assertFalse(plan_retry_purchase(
            [],style='도주',distance=None,surface=None,skill_points=300,
            consecutive_losses=1,remaining_retries=3,current_race_verified=True,
            skill_page_verified=True).skills)

    def test_unknown_distance_with_generic_skill_blocks(self):
        offers=[SkillOffer(SkillCondition('범용',verified=True),50,100,
                           price_verified=True,offered_on_screen=True)]
        plan=plan_retry_purchase(
            offers,style='도주',distance=None,surface=None,skill_points=100,
            consecutive_losses=2,remaining_retries=3,
            current_race_verified=True,skill_page_verified=True)
        self.assertFalse(plan.skills)

    def test_random_budgets_never_overflow(self):
        rng=random.Random(42)
        for _ in range(100):
            budget=rng.randrange(0,501)
            offers=[
                SkillOffer(SkillCondition(f'가상 {i}',distance='마일',
                                          style='선입',verified=True),
                           rng.randrange(1,250),rng.randrange(0,101),
                           price_verified=True,offered_on_screen=True)
                for i in range(12)]
            plan=plan_retry_purchase(
                offers,style='선입',distance='마일',surface='잔디',
                skill_points=budget,consecutive_losses=2,
                remaining_retries=3,current_race_verified=True,
                skill_page_verified=True)
            self.assertLessEqual(plan.total_sp,budget)
            self.assertEqual(plan.total_sp+plan.remaining_sp,budget)
            self.assertLessEqual(len(plan.skills),2)
            self.assertEqual(len(plan.skills),len(set(plan.skills)))

    def test_bool_sp_rejected(self):
        with self.assertRaises(ValueError):
            plan_retry_purchase(
                [],style='도주',distance=None,surface=None,skill_points=True,
                consecutive_losses=2,remaining_retries=3,current_race_verified=True,
                skill_page_verified=True)


class TestIntentGate(unittest.TestCase):
    def frame(self,n,scene='훈련',source='reviewed_game_screenshot',turn='1',active=True):
        return ObservedFrame(21,'run1',turn,scene,n,('스피드','휴식'),source,active,True)

    def test_stable_then_ack(self):
        gate=IntentGate()
        self.assertIsNone(gate.propose(self.frame(1),'스피드')[0])
        intent,_=gate.propose(self.frame(2),'스피드')
        self.assertTrue(intent.preview_only)
        self.assertIsNone(gate.propose(self.frame(3),'스피드')[0])
        self.assertFalse(gate.acknowledge(self.frame(4),intent.ticket))
        self.assertTrue(gate.acknowledge(self.frame(5,turn='2'),intent.ticket))
        self.assertIsNone(gate.propose(self.frame(6,turn='1'),'스피드')[0])
        self.assertIsNone(gate.propose(self.frame(7,turn='1'),'스피드')[0])

    def test_old_transition_evidence_rejected(self):
        gate=IntentGate()
        gate.propose(self.frame(1),'스피드')
        intent,_=gate.propose(self.frame(2),'스피드')
        gate.propose(self.frame(8),'스피드')
        self.assertFalse(gate.acknowledge(self.frame(7,turn='2'),intent.ticket))
        self.assertTrue(gate.acknowledge(self.frame(9,turn='2'),intent.ticket))

    def test_synthetic_refused(self):
        gate=IntentGate()
        gate.propose(self.frame(1,source='synthetic_test'),'휴식')
        self.assertIsNone(gate.propose(self.frame(2,source='synthetic_test'),'휴식')[0])

    def test_inactive_refused(self):
        gate=IntentGate()
        gate.propose(self.frame(1,active=False),'휴식')
        self.assertIsNone(gate.propose(self.frame(2,active=False),'휴식')[0])

    def test_input_always_blocked(self):
        with self.assertRaises(RuntimeError):
            send_game_input('스피드')


class TestStrictTurnValidation(unittest.TestCase):
    def sample(self,**kwargs):
        data=dict(stats={s:500 for s in ('스피드','스태미나','파워','근성','지능')},
                  targets={s:1000 for s in ('스피드','스태미나','파워','근성','지능')},
                  energy=60,next_turn_mandatory_race=False,all_actions_visible=True,
                  verified=True,source='reviewed_game_screenshot')
        data.update(kwargs)
        return TurnEvidence(**data)

    def test_next_turn_bool_not_number(self):
        for v in (0,1,'yes'):
            with self.subTest(v=v),self.assertRaises(ValueError):
                self.sample(next_turn_mandatory_race=v).validate()

    def test_stale_flags_not_truthy_strings(self):
        with self.assertRaises(ValueError):
            self.sample(verified='yes').validate()
        with self.assertRaises(ValueError):
            self.sample(all_actions_visible=1).validate()

    def test_invalid_stats_and_option_booleans(self):
        with self.assertRaises(ValueError):
            self.sample(stats=None).validate()
        with self.assertRaises(ValueError):
            TurnOption('훈련','training',stat_gains=None).validate()
        with self.assertRaises(ValueError):
            TurnOption('훈련','training',failure_pct=True).validate()



if __name__=='__main__':
    unittest.main()
