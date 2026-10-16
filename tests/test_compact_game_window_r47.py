"""R47.1 regression: DMM Korean game uses a compact portrait client.

Pure source tests (no Windows handle, screenshot, game input or process launch).
"""
from __future__ import annotations
import unittest

from companion_core import (
    GameWindow, choose_window, is_compact_game_window,
    is_game_window_size_supported,
)


def window(title, width, height, *, cls="UnityWndClass", hwnd=42):
    return GameWindow(hwnd, title, (100, 90, 100 + width, 90 + height), cls)


class CompactGameWindowRegression(unittest.TestCase):
    def test_user_visible_384_by_700_game_is_detected(self):
        game=window("umamusume",384,700)
        found, message=choose_window([game])
        self.assertEqual(found, game)
        self.assertIn("감지됨",message)
        self.assertTrue(is_compact_game_window(game))

    def test_other_official_compact_titles(self):
        for title in ("umamusume", "Umamusume", "우마무스메",
                      "ウマ娘", "umamusume pretty derby"):
            with self.subTest(title=title):
                found,_=choose_window([window(title,390,690)])
                self.assertIsNotNone(found)

    def test_previous_full_size_game_remains_supported(self):
        found,_=choose_window([window("umamusume",540,680)])
        self.assertIsNotNone(found)

    def test_compact_browser_and_title_matches_are_rejected(self):
        for item in (
            window("umamusume",384,700,cls="Chrome_WidgetWin_1"),
            window("umamusume wiki",384,700),
            window("Umamusume guide",384,700),
            window("Uma Trainer KR - umamusume",384,700),
            window("umamusume",260,700),
            window("umamusume",384,290),
            window("umamusume",384,350),
        ):
            with self.subTest(window=item):
                self.assertIsNone(choose_window([item])[0])

    def test_compact_and_full_size_duplicate_candidates_are_ambiguous(self):
        compact=window("umamusume",384,700,hwnd=51)
        normal=window("umamusume",530,750,hwnd=52)
        found,why=choose_window([compact, normal])
        self.assertIsNone(found)
        self.assertIn("여러 개",why)

    def test_manual_selector_uses_same_size_policy(self):
        self.assertTrue(is_game_window_size_supported(window("umamusume",384,700)))
        self.assertFalse(is_game_window_size_supported(window("umamusume",384,350)))
        self.assertTrue(is_game_window_size_supported(window("other program",530,720)))


if __name__=="__main__":
    unittest.main()
