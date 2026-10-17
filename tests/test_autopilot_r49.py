"""R49 architecture regression: no actual game actions in these tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PIL import Image,ImageDraw
from auto_core_r40 import TPView
from batch_planner_r49 import BatchPlanner,StageObservation,VerifiedOffer
from foreground_click_r49 import ClickIntent,AutoInputBlocked,ForegroundWindowsPointer
from outcome_learning_r49 import (
    ReviewedTurnOutcome,append_reviewed,derive_model,save_model_version,
    load_model_version,partition,
)
from target_selector_r39 import Target,kind_for_round
from tp_strategy_r44 import FreeTPItem
from training_preview_r48 import PreviewState,_turn_signature
from training_tour_r49 import TrainingTour


def goal():
    return Target(kind_for_round(2),2,"추입")


def pframe(selected=0):
    w,h=384,740
    im=Image.new("RGB",(w,h),(54,61,80))
    d=ImageDraw.Draw(im)
    d.rectangle((round(w*.02),round(h*.67),round(w*.98),round(h*.73)),
                fill=(150,165,221))
    x=(.099,.282,.467,.649,.83)[selected]
    d.rectangle((round((x-.045)*w),round(h*.86),
                 round((x+.045)*w),round(h*.92)),fill=(250,186,25))
    return im


def preview(index,count,recommend=None):
    labels=("스피드","스태미나","파워","근성","지능")
    return PreviewState(labels[index],count,5,recommend,"OCR 테스트")


def evidence(stage="training",**kwargs):
    args=dict(stage=stage,evidence_id="unique-frame-proof-001",
              reviewed=True,stable_frames=2,ui_actions=())
    args.update(kwargs)
    return StageObservation(**args)


def reviewed(run_id="run-A",turn_id="turn-1",confirmed=True):
    a={n:110 for n in ("스피드","스태미나","파워","근성","지능")}
    b=dict(a);b["스피드"]+=15
    return ReviewedTurnOutcome(run_id,turn_id,"island_post_patch_v1","KR-patch-A",
         "스피드",a,b,"a"*64,"b"*64,"reviewed_kr_game_screens",confirmed,
         energy_before=60,energy_after=44)


class PointerSafetyTests(unittest.TestCase):
    def make_intent(self,im=None,*,target="스태미나",timestamp=100):
        im=im or pframe()
        digest=hashlib.sha256((str(_turn_signature(im))+"|스피드|preview_training|"
                               +target).encode()).hexdigest()
        return ClickIntent(11,(20,40,404,780),.282,.828,
                           "preview_training","훈련","스피드",
                           digest,timestamp,target_label=target)

    def test_requires_actual_user_opt_in_even_dry_run(self):
        pointer=ForegroundWindowsPointer(dry_run=True,clock=lambda:101)
        with self.assertRaises(AutoInputBlocked):
            pointer.click(self.make_intent(),approved=False,fresh_image=pframe(),
                          observed_selection="스피드")

    def test_requires_same_scene_selected_and_fresh_frame(self):
        pointer=ForegroundWindowsPointer(dry_run=True,clock=lambda:101)
        kwargs=dict(approved=True,fresh_image=pframe(),observed_selection="스피드")
        self.assertFalse(pointer.click(self.make_intent(),**kwargs))
        with self.assertRaises(AutoInputBlocked):
            pointer.click(self.make_intent(timestamp=92),**kwargs)
        with self.assertRaises(AutoInputBlocked):
            pointer.click(self.make_intent(),approved=True,
                          fresh_image=pframe(),observed_selection="파워")

    def test_stale_turn_and_changed_image_block(self):
        pointer=ForegroundWindowsPointer(dry_run=True,clock=lambda:101)
        with self.assertRaises(AutoInputBlocked):
            pointer.click(self.make_intent(),approved=True,fresh_image=pframe(1),
                          observed_selection="스피드")
        with self.assertRaises(AutoInputBlocked):
            pointer.click(self.make_intent(),approved=True,fresh_image=None,
                          observed_selection="스피드")

    def test_unknown_stage_never_purchased_by_pointer(self):
        wrong=ClickIntent(11,(20,40,404,780),.4,.8,"buy_premium",
              "TP","스피드","c"*64,100)
        with self.assertRaises(AutoInputBlocked):
            wrong.validate()


class TourTests(unittest.TestCase):
    def test_scan_waits_for_reviewed_same_preview(self):
        tour=TrainingTour();tour.start()
        im=pframe(0)
        result=tour.propose(im,11,(20,40,404,780),preview(0,0),
                            scene="훈련",user_armed=True,collected_names=(),clock=100)
        self.assertIsNone(result.intent)
        result=tour.propose(im,11,(20,40,404,780),preview(0,1),
                            scene="훈련",user_armed=True,
                            collected_names=("스피드",),clock=101)
        self.assertEqual(result.intent.kind,"preview_training")
        self.assertEqual(result.intent.target_label,"스태미나")

    def test_after_click_requires_new_selected_and_ocr_stability(self):
        tour=TrainingTour();tour.start()
        t=tour.propose(pframe(0),11,(20,40,404,780),preview(0,1),
                       scene="훈련",user_armed=True,
                       collected_names=("스피드",),clock=100)
        tour.on_click_result(True,t.intent.kind,t.intent.target_label,100)
        self.assertIsNone(tour.propose(pframe(0),11,(20,40,404,780),preview(0,1),
                       scene="훈련",user_armed=True,
                       collected_names=("스피드",),clock=102).intent)
        self.assertIsNone(tour.propose(pframe(1),11,(20,40,404,780),preview(1,1),
                       scene="훈련",user_armed=True,
                       collected_names=("스피드",),clock=104).intent)
        t=tour.propose(pframe(1),11,(20,40,404,780),preview(1,2),
                       scene="훈련",user_armed=True,
                       collected_names=("스피드","스태미나"),clock=105)
        self.assertEqual(t.intent.target_label,"파워")

    def test_unknown_scene_stops_without_click(self):
        tour=TrainingTour();tour.start()
        value=tour.propose(pframe(),11,(20,40,404,780),None,
                     scene=None,user_armed=True,clock=100)
        self.assertIsNone(value.intent)
        self.assertFalse(tour.enabled)

    def test_complete_preview_commits_only_explicit_user_armed(self):
        tour=TrainingTour();tour.start()
        n=("스피드","스태미나","파워","근성","지능")
        unarmed=tour.propose(pframe(0),11,(20,40,404,780),preview(0,5,"스피드"),
                    scene="훈련",user_armed=False,collected_names=n,clock=100)
        self.assertIsNone(unarmed.intent)
        result=tour.propose(pframe(0),11,(20,40,404,780),preview(0,5,"스피드"),
                    scene="훈련",user_armed=True,collected_names=n,clock=100)
        self.assertEqual(result.intent.kind,"confirm_training")
        self.assertFalse(result.intent.is_free)

    def test_tied_or_missing_ocr_never_commits(self):
        tour=TrainingTour();tour.start()
        names=("스피드","스태미나","파워","근성","지능")
        output=tour.propose(pframe(0),11,(20,40,404,780),preview(0,5,None),
                           scene="훈련",user_armed=True,collected_names=names,clock=100)
        self.assertIsNone(output.intent)
        self.assertFalse(tour.enabled)


class PlannerTests(unittest.TestCase):
    def test_tp_free_only_then_reobserve(self):
        p=BatchPlanner(goal(),20);p.arm(setup_reviewed=True,confirmed_run_setup=True)
        tp=TPView(tp=0,cost=30,item_count=1,item_recovery=30,
                  verified=True,tp_cap=80)
        free=(FreeTPItem("recovery-30",1,30,True,True),
              FreeTPItem("premium",10,100,False,True))
        state=evidence("tp",tp=tp,items=free,ui_actions=("free_tp:recovery-30",))
        suggestion=p.plan(state,style="추입",distance="장거리",surface="잔디")
        self.assertEqual(suggestion.action,"free_tp_item")
        self.assertEqual(suggestion.target,"free_tp:recovery-30")
        p.record_click(suggestion,state)
        self.assertEqual(p.plan(state,style="추입",distance="장거리",surface="잔디").action,"verify")
        with self.assertRaises(ValueError):
            p.confirmed_transition(state.evidence_id,state)
        updated=evidence("tp",evidence_id="different-scene-proof-002",tp=TPView(
                         30,30,0,30,True,80),items=free,
                         ui_actions=("start_run",))
        p.confirmed_transition(state.evidence_id,updated)
        self.assertEqual(p.plan(updated,style="추입",distance="장거리",
                                surface="잔디").action,"start_run")

    def test_free_tp_unavailable_waits_not_premium(self):
        p=BatchPlanner(goal(),2);p.arm(setup_reviewed=True,confirmed_run_setup=True)
        value=p.plan(evidence("tp",tp=TPView(0,30,0,0,True,100),
                            items=(FreeTPItem("premium",8,50,False,True),)),
                     style="추입",distance="장거리",surface="잔디")
        self.assertEqual(value.action,"wait_tp")

    def test_final_skill_needs_reviewed_screen_prices_and_budget(self):
        p=BatchPlanner(goal(),2);p.arm(setup_reviewed=True,confirmed_run_setup=True)
        offers=(VerifiedOffer("추입 금색",150,99,True,True),)
        o=evidence("skill",skill_offers=offers,skill_points=160,
                   ui_actions=("skill:추입 금색",))
        self.assertEqual(p.plan(o,style="추입",distance="장거리",surface="잔디").action,
                         "purchase_skill")
        uncertain=evidence("skill",skill_offers=(VerifiedOffer("미검증",10,50,True,False),),
                            skill_points=160)
        self.assertEqual(p.plan(uncertain,style="추입",distance="장거리",
                                surface="잔디").action,"verify")

    def test_repeat_count_records_only_unique_reviewed_run(self):
        p=BatchPlanner(goal(),1);p.arm(setup_reviewed=True,confirmed_run_setup=True)
        r=evidence("result",completed_run_id="run-r49-1",completed_outcome="failed")
        self.assertEqual(p.plan(r,style="추입",distance=None,surface=None).action,"finish_run")
        self.assertEqual(p.record_finished(r),0)
        with self.assertRaises(ValueError):
            p.record_finished(r)
        self.assertEqual(p.plan(r,style="추입",distance=None,surface=None).action,"stop")


class LearningTests(unittest.TestCase):
    def test_unverified_and_duplicates_cannot_train(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"records.json"
            with self.assertRaises(ValueError):
                append_reviewed(path,reviewed(confirmed=False))
            self.assertFalse(path.exists())
            self.assertEqual(append_reviewed(path,reviewed()),partition("run-A"))
            with self.assertRaises(ValueError):
                append_reviewed(path,reviewed())

    def test_not_ready_until_real_reviewed_independent_runs(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"records.json"
            append_reviewed(path,reviewed())
            model=derive_model(path,"island_post_patch_v1","KR-patch-A")
            self.assertFalse(model.ready)
            self.assertEqual(model.action_rewards,{})
            snapshot=Path(td)/"policy_v1.json"
            save_model_version(snapshot,model)
            self.assertEqual(load_model_version(snapshot),model)
            with self.assertRaises(ValueError):
                save_model_version(snapshot,model)

    def test_provenance_split_preserves_whole_run(self):
        self.assertEqual(partition("run-A"),partition("run-A"))
        self.assertIn(partition("run-B"),("train","holdout"))


if __name__=="__main__":
    unittest.main()
