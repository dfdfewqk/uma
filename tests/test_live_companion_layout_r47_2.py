"""R47.2: screen-space usability and portrait overlay contract regression tests.

No game input, screenshots, synthetic training labels, network or account data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from companion_core import is_game_capture_size_supported
from recommendation_bridge_r28 import validate_handoff
from uma_core import STATS


ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,16,10,0,tzinfo=timezone.utc)


class PortablePortraitTests(unittest.TestCase):
    def test_game_capture_supports_small_portrait_and_previous_landscape(self):
        for size in ((384,700),(390,805),(300,500),(500,320),(900,600)):
            with self.subTest(size=size):
                self.assertTrue(is_game_capture_size_supported(*size))
        for size in ((299,700),(384,350),(384,319),(384,384),
                     (10000,5000),(0,700),(-2,400),(True,700)):
            with self.subTest(size=size):
                self.assertFalse(is_game_capture_size_supported(*size))

    def test_reviewed_handoff_accepts_portrait_metadata_without_weakening_integrity(self):
        choices=list(STATS)
        record={
            "schema":"uma_training_live_hint_r28_v1",
            "id":"2a0e645d-1526-499c-bd80-b661a7a8ac31",
            "issued_at":NOW.isoformat(),
            "expires_at":(NOW+timedelta(seconds=60)).isoformat(),
            "window_id":1234,"width":384,"height":700,
            "turn":"주니어급 7월 전반",
            "scenario":"island_post_patch_v1",
            "event":"챔피언스 미팅",
            "distance":"중거리",
            "style":"선행",
            "suggestion":"스피드",
            "reviewed_options":choices,
            "frame_hashes":{name:format(i+5,"064x") for i,name in enumerate(choices)},
            "source":"R22_live_capture_user_reviewed",
            "advice_kind":"TRAINING_ONLY_HEURISTIC",
        }
        self.assertEqual(validate_handoff(record,now=NOW)["width"],384)
        record["width"]=299
        with self.assertRaises(ValueError):
            validate_handoff(record,now=NOW)

    def test_helper_does_not_reposition_after_every_scan(self):
        src=(ROOT/"companion.py").read_text(encoding="utf-8")
        scan=src.split("    def _scan(self):",1)[1].split("    def _read_game(self",1)[0]
        self.assertNotIn("self.geometry(",scan)
        self.assertNotIn("overlay_position(",scan)
        self.assertIn("self.winfo_rootx()",scan)
        self.assertIn("self.topmost_var.get()",scan)

    def test_pin_off_by_default_and_optional_pin_control(self):
        src=(ROOT/"companion.py").read_text(encoding="utf-8")
        self.assertIn("self.attributes('-topmost', False)",src)
        self.assertIn("self.topmost_var=tk.BooleanVar(value=False)",src)
        self.assertIn("command=self._toggle_topmost",src)
        self.assertIn("def _toggle_topmost(self):",src)

    def test_live_game_status_and_reason_appear_before_long_settings(self):
        src=(ROOT/"companion.py").read_text(encoding="utf-8")
        self.assertLess(src.index("self._label(c,'게임 연결'"),
                        src.index("self._label(c,'육성 목표 · 처음에 클릭으로 선택'"))
        self.assertLess(src.index("self._label(c,'지금 할 일 · 게임에서 직접 누르세요'"),
                        src.index("self._label(c,'육성 목표 · 처음에 클릭으로 선택'"))
        self.assertIn("실게임 훈련별 보상·인연 데이터 미연결",src)


if __name__=="__main__":
    unittest.main()
