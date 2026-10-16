"""R35 unit tests use synthetic R6-confirmed choices, never actual player labels."""
from __future__ import annotations
import unittest
from copy import deepcopy
from pathlib import Path
from uma_core import Action, RunProfile, TurnState, TRAININGS, STATS
from decision_r6 import (AVAILABLE, UNAVAILABLE, compare_turn,
                         state_fingerprint, evidence_fingerprint)
from island_context_r34 import PlanningInputs
from island_choices_r35 import compare_checked_choices

ROOT=Path(__file__).resolve().parents[1]


class R35EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.profile=RunProfile()
        self.state=TurnState(remaining_turns=25,energy=60,island_tickets=1,
                             turns_until_next_ticket=2)
        self.state.stats={k:500 for k in STATS}
        self.profile.target_stats={k:1000 for k in STATS}
        self.actions={
            '스피드': Action('스피드',gains={**dict.fromkeys(STATS,0),'스피드':50},
                             energy_delta=-20,skill_points=18,observed=True),
            '섬 트레이닝': Action('섬 트레이닝',gains={k:30 for k in STATS},
                                 energy_delta=-18,friend_types=2,bond_gain=10,
                                 development_points=20,observed=True),
            '휴식': Action('휴식',energy_delta=35,observed=True)
        }
        self.availability={k:(AVAILABLE if k in self.actions else UNAVAILABLE) for k in TRAININGS}
        self.ctx=PlanningInputs(ticket_phase='첫 1~2회',bond_phase='인연 확보 중',
            friendship_locations=2,mandatory_races_remaining=3,
            turns_to_next_mandatory_race=2,planned_outings_remaining=1)
        self.bundle=self.fresh()

    def fresh(self):
        result=compare_turn(self.profile,self.state,self.actions,self.availability,
                            confirmed_context_hash=state_fingerprint(self.profile,self.state))
        self.assertNotEqual(result.status,'추천 보류')
        return ({
            'status':result.status,
            'context_hash':result.context_hash,
            'evidence_hash':result.evidence_hash,
            'availability':dict(self.availability),
            'ranked':[{'name':r.name,'score':r.score} for r in result.ranked],
            'experimental_only':True,'ml_training_label_verified':False
        },self.actions,self.availability)

    def test_no_r6_review_never_recommends(self):
        out=compare_checked_choices(self.profile,self.state,self.ctx,None)
        self.assertFalse(out.actions)
        self.assertIn('검수 필요',out.status)
        self.assertFalse(out.verified_optimal)

    def test_confirmed_candidates_stay_r6_order_and_scores(self):
        before=deepcopy(self.bundle[0]['ranked'])
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.bundle)
        self.assertEqual([a.name for a in out.actions],[r['name'] for r in before])
        self.assertEqual([a.r6_experimental_score for a in out.actions],[r['score'] for r in before])
        self.assertFalse(out.scores_modified)
        self.assertFalse(out.ml_training_label_verified)
        self.assertFalse(out.verified_optimal)
        self.assertEqual(self.bundle[0]['ranked'],before)

    def test_first_ticket_with_less_than_three_friends_has_exception(self):
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.bundle)
        island=next(a for a in out.actions if a.name=='섬 트레이닝')
        self.assertTrue(any('일률적으로' in s or '우정 3곳 고정' in s for s in island.notes))
        self.assertEqual(island.development_points_gain,20)

    def test_later_ticket_3_friends_observed(self):
        self.actions['섬 트레이닝'].friend_types=3
        self.ctx=PlanningInputs(ticket_phase='이후',bond_phase='우정 준비됨',
                                friendship_locations=3)
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.fresh())
        island=next(a for a in out.actions if a.name=='섬 트레이닝')
        self.assertTrue(any('우정 3곳 이상' in x for x in island.notes))

    def test_conflicting_friendship_counts_do_not_claim_ready(self):
        context=PlanningInputs(ticket_phase='이후',friendship_locations=5)
        out=compare_checked_choices(self.profile,self.state,context,self.bundle)
        self.assertTrue(any('불일치' in x for x in out.missing))
        self.assertIn('판단 보류',out.status)

    def test_current_stats_or_goal_change_blocks_old_r6(self):
        self.state.stats['스피드']+=10
        with self.assertRaisesRegex(ValueError,'변경'):
            compare_checked_choices(self.profile,self.state,self.ctx,self.bundle)

    def test_changed_action_breaks_evidence_hash(self):
        self.actions['스피드'].gains['스피드']+=10
        with self.assertRaisesRegex(ValueError,'행동 입력'):
            compare_checked_choices(self.profile,self.state,self.ctx,self.bundle)

    def test_omitted_available_action_cannot_be_silently_dropped(self):
        bundle=(deepcopy(self.bundle[0]),self.actions,self.availability)
        bundle[0]['ranked']=bundle[0]['ranked'][:-1]
        with self.assertRaisesRegex(ValueError,'일치'):
            compare_checked_choices(self.profile,self.state,self.ctx,bundle)

    def test_unknown_availability_must_not_be_assumed_unavailable(self):
        bundle=(deepcopy(self.bundle[0]),self.actions,self.availability)
        self.availability['레이스']='미확인'
        bundle[0]['evidence_hash']=evidence_fingerprint(self.actions,self.availability)
        bundle[0]['availability']=dict(self.availability)
        with self.assertRaisesRegex(ValueError,'미확인'):
            compare_checked_choices(self.profile,self.state,self.ctx,bundle)

    def test_all_flags_read_only_and_unavailable_choices_excluded(self):
        old_state=deepcopy(self.state)
        old_actions=deepcopy(self.actions)
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.bundle)
        self.assertEqual(self.state,old_state)
        self.assertEqual(self.actions,old_actions)
        self.assertNotIn('레이스',[r.name for r in out.actions])
        self.assertTrue(any('시설' in x for x in out.missing))
        self.assertTrue(any('성장률' in x for x in out.missing))
        self.assertTrue(all(isinstance(r.energy_after,int) for r in out.actions))

    def test_ticket_zero_not_exported_as_available(self):
        self.state.island_tickets=0
        self.availability['섬 트레이닝']=UNAVAILABLE
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.fresh())
        self.assertNotIn('섬 트레이닝',[r.name for r in out.actions])

    def test_end_of_run_budget_caution_and_real_gains_only(self):
        self.state.remaining_turns=5
        self.ctx=PlanningInputs(ticket_phase='이후',bond_phase='우정 준비됨',
            friendship_locations=2,mandatory_races_remaining=4,
            turns_to_next_mandatory_race=1,planned_outings_remaining=2)
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.fresh())
        self.assertTrue(any('부족할 수' in s for s in out.cautions))
        island=next(r for r in out.actions if r.name=='섬 트레이닝')
        self.assertTrue(any('목표 레이스' in s for s in island.notes))

    def test_waste_above_user_target_is_not_counted_toward_gap(self):
        self.state.stats['스피드']=980
        self.actions['스피드'].gains['스피드']=50
        out=compare_checked_choices(self.profile,self.state,self.ctx,self.fresh())
        speed=next(x for x in out.actions if x.name=='스피드')
        self.assertEqual(speed.observed_gains['스피드'],50)
        self.assertEqual(speed.gains_toward_user_target['스피드'],20)

    def test_window_wiring_and_no_changes_to_r6_implementation(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        screen=(ROOT/'island_context_ui_r34.py').read_text(encoding='utf-8')
        self.assertIn('comparison_getter=self._read_r6_for_r8',app)
        self.assertIn("text='R35 확인된 행동 비교'",screen)
        self.assertIn('def _invalidate_choices(',screen)
        self.assertIn('def invalidate_external(',screen)
        self.assertIn("'<<NotebookTabChanged>>'",app)
        self.assertNotIn('rank_actions(',screen)
        self.assertNotIn('compare_turn(',screen)


if __name__=='__main__':
    unittest.main()
