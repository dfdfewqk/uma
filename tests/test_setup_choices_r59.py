"""R59 synthetic choice recognition. No actual game inputs or video claims."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image, ImageDraw

from setup_choices_r59 import (
    register_choice, save_choice, load_choices, visible_choice, StableSetupChoices,
)

A=(.08,.08,.34,.22)
B=(.57,.72,.88,.83)


def frame(button_color="#eda93c"):
    im=Image.new("RGB",(384,740),"#182740")
    d=ImageDraw.Draw(im)
    d.rectangle((31,60,130,163),fill="#35a0bd")
    d.text((37,76),"NORMAL START",fill="white")
    d.rectangle((219,533,338,615),fill=button_color)
    d.text((233,552),"NEXT",fill="white")
    return im


def record(branch="normal",step="character",choice="choice A"):
    return register_choice(frame(),branch=branch,step=step,choice=choice,
                           scene_box=A,button_box=B,reviewed=True)


class ChoicesR59Tests(unittest.TestCase):
    def observe(self,tracker,im,profs,**kw):
        data=dict(hwnd=21,rect=(0,0,384,740),active=True,
                  scene="육성 준비",profiles=profs)
        data.update(kw)
        return tracker.observe(im,**data)

    def test_registered_choice_is_visible_but_not_approved(self):
        p=record()
        self.assertTrue(visible_choice(frame(),p))
        s=StableSetupChoices()
        self.assertIsNone(self.observe(s,frame(),(p,)).branch)
        v=self.observe(s,frame(),(p,))
        self.assertEqual(v.branch,"normal")
        self.assertEqual(v.choices,("choice A",))
        self.assertFalse(v.game_input_allowed)
        self.assertIsNone(v.selected_choice)
        self.assertFalse(v.ml_training_label)

    def test_event_branch_is_separate_from_normal(self):
        p=record(branch="event")
        s=StableSetupChoices()
        self.observe(s,frame(),(p,))
        v=self.observe(s,frame(),(p,))
        self.assertEqual(v.branch,"event")

    def test_two_routes_matching_same_pixels_must_not_guess(self):
        s=StableSetupChoices()
        p=record()
        e=record(branch="event")
        self.assertFalse(self.observe(s,frame(),(p,e)).game_input_allowed)
        self.assertIsNone(self.observe(s,frame(),(p,e)).branch)

    def test_step_ambiguity_never_picks_one(self):
        s=StableSetupChoices()
        p=record(step="scenario")
        e=record(step="support")
        self.assertIsNone(self.observe(s,frame(),(p,e)).step)

    def test_window_switch_and_inactive_revoke(self):
        s=StableSetupChoices()
        p=record()
        self.observe(s,frame(),(p,))
        self.assertTrue(self.observe(s,frame(),(p,)).choices)
        self.assertFalse(self.observe(s,frame(),(p,),hwnd=22).choices)
        self.assertFalse(self.observe(s,frame(),(p,),active=False).choices)

    def test_changed_button_and_resolution_rejected(self):
        p=record()
        self.assertFalse(visible_choice(frame("#245b80"),p))
        self.assertFalse(visible_choice(frame().resize((450,740)),p))

    def test_atomic_storage_duplicate_protection(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"setup.json"
            p=record()
            save_choice(path,p)
            self.assertEqual(load_choices(path),(p,))
            original=path.read_bytes()
            with self.assertRaises(ValueError):
                save_choice(path,p)
            self.assertEqual(path.read_bytes(),original)

    def test_rejects_invalid_and_unreviewed_registration(self):
        with self.assertRaises(ValueError):
            register_choice(frame(),branch="unknown",step="a",choice="x",
                            scene_box=A,button_box=B,reviewed=True)
        with self.assertRaises(ValueError):
            register_choice(frame(),branch="normal",step="a",choice="x",
                            scene_box=A,button_box=B,reviewed=False)
        with self.assertRaises(ValueError):
            register_choice(frame(),branch="normal",step="a",choice="x",
                            scene_box=A,button_box=A,reviewed=True)

    def test_companion_wiring_is_read_only(self):
        text=(Path(__file__).resolve().parents[1]/"companion.py").read_text(encoding="utf-8")
        for needle in ("StableSetupChoices()", "load_choices(",
                       "self.setup_choice_tracker.observe(", "SetupChoiceRegistration"):
            self.assertIn(needle,text)


if __name__=="__main__":
    unittest.main()
