"""R51 regression: actual repeated runs, skill authorization and post-click proof.

No game, input, premium currency, synthetic ML labels or Windows needed.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import unittest

from PIL import Image
from autopilot_bridge_r50 import (
    LivePacket, LiveBatchSupervisor, VisualStageAdapter,
)
from batch_planner_r49 import StageObservation,StageAdvice,VerifiedOffer
from registered_pointer_r50 import SceneClickBlocked
from skill_authorizations_r51 import (
    SkillAuthorization, approved_skill_labels, load_authorizations,save_authorization
)
from target_selector_r39 import Target,kind_for_round


def goal():
    return Target(kind_for_round(2),2,"추입")


def authorization(skill="추입 확인 스킬",scope="loh-2:추입"):
    return SkillAuthorization(scope,skill,True,True,True,True)


def skill_fixture():
    label="추입 확인 스킬"
    ref=NS(stage="skill",action="skill:"+label,
           target_scope="loh-2:추입",identity="profile-r51",free_only=False)
    hit=NS(action="skill:"+label,profile_identity="profile-r51")
    return label,ref,hit


class ReviewAndProvenanceTests(unittest.TestCase):
    def test_skills_require_all_four_reviewed_conditions(self):
        with self.assertRaises(ValueError):
            SkillAuthorization("loh-2:추입","예시",True,False,True,True).validate()
        with self.assertRaises(ValueError):
            authorization(skill="premium").validate()

    def test_file_is_monotonic_and_target_scoped(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"skills.json"
            save_authorization(p,authorization())
            self.assertEqual(approved_skill_labels(load_authorizations(p),"loh-2:추입"),
                             frozenset({"추입 확인 스킬"}))
            self.assertEqual(approved_skill_labels(load_authorizations(p),"cm-1:추입"),
                             frozenset())
            before=p.read_bytes()
            with self.assertRaises(ValueError):
                save_authorization(p,authorization())
            self.assertEqual(p.read_bytes(),before)

    def test_same_tp_values_in_next_run_have_new_evidence(self):
        adapter=VisualStageAdapter()
        im=Image.new("RGB",(384,740),(0,0,0))
        ctl=NS(action="start_run",profile_identity="some-control")
        with patch("autopilot_bridge_r50.unique_scene",
                   return_value=("tp",(ctl,))):
            adapter.reader.observe=lambda *a:{"tp":30,"tp_cost":30,"tp_cap":80}
            def observed(run,cycle):
                return adapter.observe(im,191,(),(),None,run_id=run,cycle=cycle)
            first=observed(None,0)
            second=observed(None,0)
            self.assertTrue(second.observation.reviewed)
            again=observed(None,1)
            self.assertNotEqual(first.observation.evidence_id,again.observation.evidence_id)
            self.assertFalse(again.observation.reviewed)
            self.assertTrue(observed(None,1).observation.reviewed)

    def test_skill_approval_does_not_follow_other_style_or_patch_by_default(self):
        adapter=VisualStageAdapter()
        label,ref,hit=skill_fixture()
        image=Image.new("RGB",(384,740))
        with patch("autopilot_bridge_r50.unique_scene",
                   return_value=("skill",(hit,))):
            adapter.reader.observe=lambda *a:{"skill_points":100,"skill_price":25}
            def pkt(scope,approvals):
                return adapter.observe(image,191,(ref,),(),None,
                                       skill_scope_reviewed=True,
                                       goal_scope=scope,skill_approvals=approvals)
            self.assertFalse(pkt("loh-2:추입",()).observation.skill_offers)
            self.assertFalse(pkt("cm-1:추입",(label,)).observation.skill_offers)
            self.assertEqual(pkt("loh-2:추입",(label,)).observation.skill_offers[0].label,label)


class ExactClickWitnessTests(unittest.TestCase):
    def setUp(self):
        self.runner=LiveBatchSupervisor(goal(),3,dry_run=True,clock=lambda:100)
        self.runner.arm(setup_reviewed=True,character_deck_inheritance_reviewed=True,
                        skill_scope_reviewed=True)
        self.runner.active_run_id="kr-run1"
        self.runner.skill_approvals=frozenset({"추입 확인 스킬"})
        self.runner.pointer.click=Mock(return_value=True)
        self.label,self.ref,self.hit=skill_fixture()
        self.advice=StageAdvice("purchase_skill","skill:"+self.label,"verified",True)
        self.before=StageObservation("skill","before-a1bc2d3e4",True,2,
                        ("skill:"+self.label,),skill_offers=(
                        VerifiedOffer(self.label,25,100,True,True,False),),
                        skill_points=100)
        self.packet=LivePacket("skill",self.before,(self.hit,),
                               {"skill_points":100,"skill_price":25},"verified")
        self.after=StageObservation("skill","after-112233445566",True,2,
                         ("skill:"+self.label,),skill_points=75)

    def test_wrong_skill_price_change_does_not_count_success(self):
        self.assertTrue(self.runner.click(self.advice,self.packet,None,(self.ref,),
                           hwnd=191,rect=(0,0,384,740),approved=True))
        wrong=LivePacket("skill",self.after,(),{"skill_points":78},"wrong price")
        self.assertFalse(self.runner._witness_after_click(wrong))
        self.assertEqual(self.runner.purchased_skills,set())
        self.assertIsNotNone(self.runner.awaiting)
        correct=LivePacket("skill",self.after,(),{"skill_points":75},"matching price")
        self.assertTrue(self.runner._witness_after_click(correct))
        self.assertEqual(self.runner.purchased_skills,{self.label})
        with self.assertRaises(SceneClickBlocked):
            self.runner.click(self.advice,self.packet,None,(self.ref,),
                              hwnd=191,rect=(0,0,384,740),approved=True)

    def test_game_run_id_is_needed_for_skill_purchase(self):
        self.runner.active_run_id=None
        with self.assertRaises(SceneClickBlocked):
            self.runner.click(self.advice,self.packet,None,(self.ref,),
                              hwnd=191,rect=(0,0,384,740),approved=True)
        self.runner.pointer.click.assert_not_called()

    def test_final_result_can_be_confirmed_by_next_verified_setup(self):
        self.runner.planner.pending=("finish_run","result-a1bc2d3e","result")
        result=StageObservation("result","result-a1bc2d3e",True,2,(),
                   completed_run_id="kr-run1",completed_outcome="ordinary")
        self.runner.awaiting={"action":"finish_run","evidence":"result-a1bc2d3e",
                 "when":100,"numbers":{},"run_id":"kr-run1",
                 "result_observation":result}
        after=LivePacket("setup",StageObservation("setup","new-scene-12345",True,2),
                          (),{},"verified")
        self.assertTrue(self.runner._witness_after_click(after))
        self.assertEqual(self.runner.planner.remaining,2)
        self.assertIn("kr-run1",self.runner.planner.completed_ids)
        self.assertIsNone(self.runner.active_run_id)
        self.assertFalse(self.runner._witness_after_click(after))


class R51WiringTests(unittest.TestCase):
    def test_companion_uses_scoped_authorization_and_per_cycle_proof(self):
        src=(Path(__file__).resolve().parents[1]/"companion.py").read_text("utf-8")
        for anchor in ("load_authorizations(","approved_skill_labels(",
                       "self.full_batch.skill_approvals=",
                       "skill_approvals=self.r51_skill_approvals",
                       "cycle=len(self.full_batch.planner.completed_ids)",
                       "batch.planner.goal!=self.current_target"):
            self.assertIn(anchor,src)


if __name__=="__main__":
    unittest.main()
