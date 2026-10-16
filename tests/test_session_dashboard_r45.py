"""R45 read-only UI/session projection tests. No game, EXE, CI or click."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auto_core_r40 import AutomationConfig, AutomationProgress
from cultivation_session_r44 import CultivationSession, save_session
from planning_prefs_r44 import Preferences
from session_dashboard_r45 import read_dashboard
from target_selector_r39 import Target, kind_for_round


def target(round_number=2, style="추입"):
    return Target(kind_for_round(round_number), round_number, style)


def session(repetitions=20, round_number=2, *, phase="need_tp",
            completed_ids=("run-1", "run-2"), pending_run_id=None):
    config = AutomationConfig(
        target(round_number), repetitions, "umamusume-verified",
        "support-deck-verified", "inheritance-verified", "KR-2026",
    )
    outcomes = {
        "run-1":"good",
        "run-2":"disposed",
    }
    ids = list(completed_ids)
    assert all(i in outcomes for i in ids)
    return CultivationSession(
        progress=AutomationProgress(
            config, phase=phase, completed_ids=ids,
            outcomes={k:outcomes[k] for k in ids},
            pending_run_id=pending_run_id,
        ),
        paused=False,
        pause_reason="",
    ).validate()


class R45DashboardTests(unittest.TestCase):
    def test_plan_without_record_does_not_fake_zero_completed(self):
        with tempfile.TemporaryDirectory() as td:
            view = read_dashboard(target(), Preferences(20), Path(td)/"not_found.json")
            self.assertFalse(view.recorded)
            self.assertIsNone(view.completed)
            self.assertIsNone(view.fraction)
            self.assertIn("기록된 진행 없음", view.progress)
            self.assertFalse(view.permits_game_input)

    def test_no_target_is_still_plan_only(self):
        with tempfile.TemporaryDirectory() as td:
            view = read_dashboard(None, Preferences(20), Path(td)/"not_found.json")
            self.assertFalse(view.recorded)
            self.assertIn("목표 선택", view.status)

    def test_existing_record_is_read_only_and_paused_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            save_session(path, session())
            original = path.read_bytes()
            view = read_dashboard(target(), Preferences(20), path)
            self.assertTrue(view.recorded)
            self.assertTrue(view.compatible)
            self.assertEqual(view.completed, 2)
            self.assertEqual(view.requested, 20)
            self.assertAlmostEqual(view.fraction, .1)
            self.assertIn("18회", view.progress)
            self.assertIn("일시 정지", view.status)
            self.assertIn("고점 1", view.breakdown)
            self.assertIn("도축 1", view.breakdown)
            self.assertEqual(original, path.read_bytes())
            self.assertFalse(view.permits_game_input)

    def test_changed_round_does_not_reuse_previous_progress(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            save_session(path, session())
            view = read_dashboard(target(1), Preferences(20), path)
            self.assertTrue(view.recorded)
            self.assertFalse(view.compatible)
            self.assertIn("이전 육성 계획", view.status)
            self.assertIn("덮어쓰거나", view.detail)

    def test_changed_run_count_is_not_merged(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            save_session(path, session())
            view = read_dashboard(target(), Preferences(30), path)
            self.assertTrue(view.recorded)
            self.assertFalse(view.compatible)
            self.assertEqual(view.requested, 20)

    def test_in_progress_run_never_counts_as_completed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            save_session(path, session(phase="in_run", pending_run_id="run-3"))
            view = read_dashboard(target(), Preferences(20), path)
            self.assertEqual(view.completed, 2)
            self.assertEqual(view.requested, 20)
            self.assertIn("진행 중이던", view.status)
            self.assertTrue(view.needs_review)

    def test_corrupt_file_kept_and_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            path.write_text("{not-json", encoding="utf-8")
            before = path.read_bytes()
            view = read_dashboard(target(), Preferences(20), path)
            self.assertIn("검토 필요", view.status)
            self.assertFalse(view.recorded)
            self.assertEqual(path.read_bytes(), before)

    def test_finished_record_shows_saved_completed_count(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            save_session(path, session(
                repetitions=2, phase="finished"))
            view = read_dashboard(target(), Preferences(2), path)
            self.assertEqual(view.completed, 2)
            self.assertAlmostEqual(view.fraction, 1.0)
            self.assertIn("완료", view.status)
            self.assertFalse(view.permits_game_input)

    def test_broken_symlink_not_mistaken_for_missing_data(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"cultivation_session_r44.json"
            try:
                path.symlink_to(Path(td)/"not-there.json")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            view = read_dashboard(target(), Preferences(20), path)
            self.assertIn("검토 필요", view.status)


if __name__ == "__main__":
    unittest.main()
