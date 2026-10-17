"""R58 pure preflight contract. No game data, network, mouse, or Tk UI."""
from types import SimpleNamespace
import unittest

from setup_preflight_r58 import audit_setup, TP_FIELDS


def profile(stage, action, *, reviewed=True, free_only=False):
    return SimpleNamespace(stage=stage, action=action, reviewed=reviewed, free_only=free_only)


def roi(field, stage="tp", reviewed=True):
    return SimpleNamespace(stage=stage, field=field, reviewed=reviewed)


def complete():
    return (
        (profile("setup", "start_run"), profile("tp", "start_run"),
         profile("tp", "free_tp:ticket", free_only=True),
         profile("result", "finish_run:good"), profile("repeat", "repeat_run")),
        tuple(roi(f) for f in TP_FIELDS),
    )


class SetupPreflightTests(unittest.TestCase):
    def test_complete_inventory_does_not_assert_live_game_setup(self):
        p,r=complete()
        report=audit_setup(p,r)
        self.assertTrue(report.ready_for_manual_review)
        self.assertFalse(report.missing)
        self.assertIn("사용자 검수 필요",report.summary)
        self.assertTrue(any("자동 선택" in x for x in report.reminders))

    def test_stage_name_alone_is_insufficient(self):
        p,r=complete()
        without_setup=tuple(x for x in p if x.stage!="setup")+(profile("setup","some_other_button"),)
        report=audit_setup(without_setup,r)
        self.assertFalse(report.ready_for_manual_review)
        self.assertIn("육성 준비 화면 시작 버튼",report.summary)
        without_tp_start=tuple(x for x in p if not (x.stage=="tp" and x.action=="start_run"))
        self.assertIn("TP 화면 시작 버튼",audit_setup(without_tp_start,r).summary)

    def test_numeric_roi_requires_every_exact_field_and_manual_review(self):
        p,r=complete()
        rs=tuple(v for v in r if v.field!="tp_cap") + (roi("tp_cap",reviewed=False),)
        self.assertIn("tp_cap",audit_setup(p,rs).summary)
        self.assertFalse(audit_setup(p,rs).ready_for_manual_review)

    def test_premium_tp_is_not_free(self):
        p,r=complete()
        p=p+(profile("tp","free_tp:unverified",free_only=False),)
        self.assertIn("무료로 검수되지",audit_setup(p,r).summary)

    def test_unreviewed_result_and_repeat_are_not_accepted(self):
        p,r=complete()
        p=tuple(profile(x.stage,x.action,reviewed=False,free_only=x.free_only)
                if x.stage in ("result","repeat") else x for x in p)
        report=audit_setup(p,r)
        self.assertIn("육성 종료",report.summary)
        self.assertIn("반복 육성",report.summary)


if __name__=='__main__': unittest.main()
