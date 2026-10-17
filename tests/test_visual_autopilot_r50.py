"""R50 end-to-end synthetic/contract regression; no actual game or input."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PIL import Image, ImageDraw
from auto_core_r40 import TPView
from autopilot_bridge_r50 import LiveBatchSupervisor,VisualStageAdapter
from numeric_observer_r50 import NumberROI,StableNumberReader,save_roi,load_rois
from registered_pointer_r50 import SceneTicket,RegisteredScenePointer,SceneClickBlocked
from target_selector_r39 import Target,kind_for_round
from visual_controls_r50 import (
    ControlProfile,register,recognize,unique_scene,
    load_profiles,save_profile,allowed_action,
)


def target():
    return Target(kind_for_round(2),2,"추입")


def picture():
    w,h=384,740
    img=Image.new("RGB",(w,h),(30,36,48))
    d=ImageDraw.Draw(img)
    for x in range(0,w,9):
        color=(35+x%93,45+x%64,75+x%115)
        d.rectangle((x,0,x+4,h),fill=color)
    d.rectangle((w*.1,h*.1,w*.34,h*.23),fill=(62,136,210))
    d.text((w*.12,h*.13),"SCENE TP OK",fill=(250,230,170))
    d.rectangle((w*.60,h*.65,w*.85,h*.75),fill=(219,116,46))
    d.text((w*.62,h*.68),"FREE ITEM",fill=(250,240,218))
    d.rectangle((w*.60,h*.78,w*.85,h*.87),fill=(80,181,112))
    d.text((w*.62,h*.79),"START",fill=(230,240,210))
    return img


SCENE=(.1,.1,.34,.23)
FREE=(.60,.65,.85,.75)
START=(.60,.78,.85,.87)


def profile(action="free_tp:verified_item",stage="tp",box=FREE,scope=""):
    return register(picture(),stage=stage,action=action,scene_box=SCENE,
                    button_box=box,click=((box[0]+box[2])/2,
                                          (box[1]+box[3])/2),
                    reviewed=True,free_only=action.startswith("free_tp:"),
                    target_scope=scope)


def fields():
    return tuple(NumberROI("tp",n,(.1,.29,.36,.33),True)
                 for n in ("tp","tp_cost","tp_cap",
                           "free_item_count","free_item_recovery"))


class VisualProfileTests(unittest.TestCase):
    def test_registered_buttons_need_distinct_scene_and_button(self):
        p=profile()
        self.assertEqual(p.stage,"tp")
        match=recognize(picture(),p)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score,.94)
        self.assertEqual(unique_scene(picture(),(p,))[0],"tp")

    def test_bad_scene_or_changed_client_fails(self):
        p=profile()
        self.assertIsNone(recognize(Image.new("RGB",(384,740),(0,0,0)),p))
        self.assertIsNone(recognize(picture().resize((390,740)),p))

    def test_never_allow_premium_or_unknown_actions(self):
        self.assertFalse(allowed_action("tp","free_tp:premium_jewel"))
        self.assertFalse(allowed_action("tp","buy_jewel"))
        self.assertFalse(allowed_action("unknown","start_run"))
        with self.assertRaises(ValueError):
            profile("skill:추입 금색","skill",scope="")
        with self.assertRaises(ValueError):
            register(picture(),stage="tp",action="free_tp:a",
                     scene_box=SCENE,button_box=SCENE,click=(.18,.16),
                     reviewed=True,free_only=True)

    def test_target_scoped_skill_cannot_be_generic(self):
        p=profile("skill:추입 금색","skill",scope="loh-2:추입")
        self.assertEqual(p.target_scope,"loh-2:추입")
        self.assertIsNotNone(recognize(picture(),p))

    def test_storage_preserves_original_profile_and_refuses_links(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"controls.json"
            p=profile()
            save_profile(path,p)
            original=path.read_bytes()
            self.assertEqual(load_profiles(path),(p,))
            with self.assertRaises(ValueError):save_profile(path,p)
            self.assertEqual(path.read_bytes(),original)
            link=Path(td)/"linked"
            try:link.symlink_to(path)
            except (OSError,NotImplementedError):return
            with self.assertRaises(ValueError):load_profiles(link)

    def test_numeric_roi_storage_is_validated(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"numeric.json"
            save_roi(path,fields()[0])
            self.assertEqual(len(load_rois(path)),1)
            with self.assertRaises(ValueError):save_roi(path,fields()[0])
            with self.assertRaises(ValueError):
                NumberROI("result","tp",(.1,.3,.2,.4),True).validate()


class NumericAndAdapterTests(unittest.TestCase):
    def test_two_matching_ocr_frames_needed(self):
        reader=StableNumberReader()
        roi=fields()[0]
        im=picture()
        with patch("numeric_observer_r50.read_one_number",return_value=50):
            self.assertEqual(reader.observe("tp",im,(roi,),"mock",11),{})
            self.assertEqual(reader.observe("tp",im,(roi,),"mock",11),{"tp":50})
        with patch("numeric_observer_r50.read_one_number",return_value=15):
            self.assertEqual(reader.observe("tp",im,(roi,),"mock",11),{})
            self.assertEqual(reader.observe("tp",im,(roi,),"mock",11),{"tp":15})

    def test_adapter_reports_verified_free_item_only_after_stability(self):
        adapter=VisualStageAdapter()
        vals={"tp":0,"tp_cost":30,"tp_cap":80,
              "free_item_count":1,"free_item_recovery":30}
        prof=(profile(),profile("start_run",box=START))
        with patch("numeric_observer_r50.read_one_number",
                   side_effect=lambda img,r,ocr:vals[r.field]):
            packets=[adapter.observe(picture(),101,prof,fields(),"mock")
                     for _ in range(3)]
        self.assertFalse(packets[0].observation.reviewed)
        self.assertTrue(packets[-1].observation.reviewed)
        self.assertEqual(packets[-1].stage,"tp")
        self.assertEqual(packets[-1].observation.tp.tp,0)
        self.assertEqual(packets[-1].observation.items[0].item_id,"verified_item")
        runner=LiveBatchSupervisor(target(),3,dry_run=True)
        runner.arm(setup_reviewed=True,character_deck_inheritance_reviewed=True)
        advice=runner.decision(packets[-1],style="추입")
        self.assertEqual(advice.action,"free_tp_item")
        self.assertTrue(advice.input_ready)
        self.assertFalse(runner.click(advice,packets[-1],picture(),prof,
                                      hwnd=101,rect=(0,0,384,740),approved=True))
        self.assertEqual(runner.planner.remaining,3)

    def test_missing_numeric_evidence_blocks_tp_click(self):
        adapter=VisualStageAdapter()
        out=adapter.observe(picture(),101,(profile(),),fields(),None)
        self.assertFalse(out.observation.reviewed)
        self.assertIsNone(out.observation.tp)


class PointerAndResultTests(unittest.TestCase):
    def test_pointer_requires_approval_and_matching_visible_profile(self):
        p=profile()
        ticket=SceneTicket(101,(0,0,384,740),p.identity,p.stage,p.action,
                           100.,"evidence-123456",True,True,True)
        pointer=RegisteredScenePointer(dry_run=True,clock=lambda:101)
        self.assertFalse(pointer.click(ticket,picture(),(p,)))
        with self.assertRaises(SceneClickBlocked):
            pointer.click(replace(ticket,approved=False),picture(),(p,))
        with self.assertRaises(SceneClickBlocked):
            pointer.click(replace(ticket,issued_at=90),picture(),(p,))
        with self.assertRaises(SceneClickBlocked):
            pointer.click(ticket,Image.new("RGB",(384,740),(0,0,0)),(p,))

    def test_result_can_only_identify_explicit_profiled_outcome(self):
        outcome=profile("finish_run:ordinary",stage="result")
        adapter=VisualStageAdapter()
        result=None
        for _ in range(2):
            result=adapter.observe(picture(),88,(outcome,),(),None,
                                   run_id="already-observed-run")
        self.assertEqual(result.observation.completed_outcome,"ordinary")
        self.assertEqual(result.observation.completed_run_id,"already-observed-run")
        self.assertFalse(result.observation.reviewed is False)

    def test_dry_run_never_completes_or_trains_game_run(self):
        batch=LiveBatchSupervisor(target(),20,dry_run=True)
        batch.arm(setup_reviewed=True,character_deck_inheritance_reviewed=True)
        self.assertIsNone(batch.active_run_id)
        self.assertEqual(batch.planner.remaining,20)
        self.assertEqual(batch.event_log,[])


class R50IntegrationWiringTests(unittest.TestCase):
    def test_companion_contains_calibration_start_and_emergency_stop(self):
        path=Path(__file__).resolve().parents[1]/"companion.py"
        src=path.read_text(encoding="utf-8")
        for needle in ("def _open_r50_calibration","def _start_full_batch",
                       "def _stop_all_automation","def _run_r50_on_frame",
                       "self.full_batch.adapter.observe","self._run_r50_on_frame(packet",
                       "command=self._stop_all_automation"):
            self.assertIn(needle,src)
        self.assertNotIn("tk.Entry(",src)

    def test_auto_source_does_not_claim_unreviewed_ocr_is_learned(self):
        src=(Path(__file__).resolve().parents[1]/"autopilot_bridge_r50.py").read_text(encoding="utf-8")
        self.assertNotIn("append_reviewed(",src)
        self.assertNotIn("mouse_event(",src)


if __name__=="__main__":
    unittest.main()
