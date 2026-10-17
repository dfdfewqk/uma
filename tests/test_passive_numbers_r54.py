"""R54 passive OCR contract. Synthetic images; no game input or live OCR."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from passive_numbers_r54 import (
    LiveNumberRegion, StableLiveNumberReader, read_regions, save_region,
    parse_live_number, read_candidate,
)


def roi(field="스피드",scene="훈련"):
    return LiveNumberRegion(scene,field,(.1,.10,.31,.17),384,740,True)


class NumberR54Tests(unittest.TestCase):
    def setUp(self):
        self.image=Image.new("RGB",(384,740),"white")

    def test_parse_explicit_and_strict(self):
        self.assertEqual(parse_live_number("1,230","스피드"),1230)
        self.assertEqual(parse_live_number("42/100","체력"),42)
        self.assertEqual(parse_live_number("17%","실패율"),17)
        self.assertIsNone(parse_live_number("105%","실패율"))
        self.assertIsNone(parse_live_number("17.5%","실패율"))
        self.assertIsNone(parse_live_number("1O0","파워"))
        with self.assertRaises(ValueError):
            parse_live_number("10","우정 훈련")

    def test_training_effects_are_separate_from_current_balance(self):
        from passive_numbers_r54 import parse_live_number
        self.assertEqual(parse_live_number("+15","스킬 Pt 증가"),15)
        self.assertEqual(parse_live_number("8","체력 소모"),8)
        self.assertIsNone(parse_live_number("-8","체력 소모"))
        self.assertIsNone(parse_live_number("250","스킬 Pt 증가"))
        with self.assertRaises(ValueError):
            roi("체력 소모","스킬").validate()

    def test_storage_does_not_overwrite_or_modify_r50(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"r54.json"
            save_region(path,roi())
            self.assertEqual(read_regions(path),(roi(),))
            initial=path.read_bytes()
            with self.assertRaises(ValueError):save_region(path,roi())
            self.assertEqual(initial,path.read_bytes())

    def test_missing_engine_low_confidence_and_invalid_layout(self):
        self.assertIsNone(read_candidate(self.image,roi(),None))
        with patch("passive_numbers_r54._recognize_one",return_value=("1300",79)):
            self.assertIsNone(read_candidate(self.image,roi(),"mock"))
        with patch("passive_numbers_r54._recognize_one",return_value=("1300",93)):
            self.assertIsNone(read_candidate(self.image.resize((520,740)),roi(),"mock"))

    def test_repeat_twice_is_candidate_not_verified(self):
        reader=StableLiveNumberReader()
        with patch("passive_numbers_r54._recognize_one",return_value=("1542",95)):
            first=reader.observe(self.image,"훈련",(roi(),),"mock",15,(0,0,384,740),"turn1")
            second=reader.observe(self.image,"훈련",(roi(),),"mock",15,(0,0,384,740),"turn1")
        self.assertEqual(first.numbers,{})
        self.assertEqual(second.numbers,{"스피드":1542})
        self.assertFalse(second.reviewed_outcome)
        self.assertFalse(second.authorized_for_click)
        self.assertFalse(second.ml_training_label)

    def test_scene_turn_geometry_and_ocr_failure_revoke(self):
        reader=StableLiveNumberReader()
        with patch("passive_numbers_r54._recognize_one",return_value=("42",95)):
            reader.observe(self.image,"훈련",(roi(),),"mock",15,(0,0,384,740),"t1")
            self.assertEqual(reader.observe(self.image,"훈련",(roi(),),"mock",15,(0,0,384,740),"t1").numbers,{"스피드":42})
            self.assertEqual(reader.observe(self.image,"훈련",(roi(),),"mock",15,(0,0,384,740),"t2").numbers,{})
            self.assertEqual(reader.observe(self.image,"훈련",(roi(),),"mock",16,(0,0,384,740),"t2").numbers,{})
        self.assertEqual(reader.observe(self.image,None,(roi(),),"mock",16).numbers,{})
        with patch("passive_numbers_r54._recognize_one",return_value=("42",95)):
            self.assertEqual(reader.observe(self.image,"훈련",(roi(),),"mock",16,(0,0,384,740),"t2").numbers,{})
        with patch("passive_numbers_r54._recognize_one",return_value=("43",95)):
            self.assertEqual(reader.observe(self.image,"훈련",(roi(),),"mock",16,(0,0,384,740),"t2").numbers,{})

    def test_companion_integration_is_readonly_and_separate(self):
        src=(Path(__file__).resolve().parents[1]/"companion.py").read_text("utf-8")
        for fragment in ("StableLiveNumberReader()", "read_passive_numbers(",
                         "self.numeric_reader.observe(", "PassiveNumberRegistration",
                         "r54_numeric_regions.json"):
            self.assertIn(fragment,src)


if __name__=="__main__":unittest.main()
