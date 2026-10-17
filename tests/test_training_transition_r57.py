"""R57 offline transition guard regression: no real game input."""
import unittest
from training_transition_r57 import TrainingClickGuard


class FakeIntent:
    def __init__(self,kind="preview_training",target="스태미나"):
        self.kind=kind
        self.target_label=target
        self.expected_scene="훈련"
        self.hwnd=4
        self.rect=(0,0,384,740)
    def validate(self):
        pass


SIG="a"*64


class GuardTests(unittest.TestCase):
    def setup_observation(self,**kw):
        result=dict(scene="훈련",selected="스태미나",
                    preview_selected="스태미나",
                    collected_names=("스태미나",),
                    signature=SIG,hwnd=4,rect=(0,0,384,740),now=101)
        result.update(kw)
        return result

    def test_preview_requires_two_matching_postclick_ocr_frames(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent(),SIG)
        self.assertEqual(g.observe(**self.setup_observation(preview_selected=None)).code,"waiting")
        self.assertEqual(g.observe(**self.setup_observation()).code,"waiting")
        out=g.observe(**self.setup_observation(now=102))
        self.assertEqual(out.code,"preview_confirmed")
        self.assertTrue(out.preview_observed)
        self.assertFalse(out.game_input_allowed)
        self.assertFalse(out.game_turn_verified)

    def test_preview_other_scene_blocks(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent(),SIG)
        self.assertEqual(g.observe(**self.setup_observation(scene="스킬")).code,"blocked")
        self.assertFalse(g.armed)

    def test_changed_window_blocks(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent(),SIG)
        self.assertEqual(g.observe(**self.setup_observation(hwnd=9)).code,"blocked")

    def test_timeout_blocks(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent(),SIG)
        self.assertEqual(g.observe(**self.setup_observation(now=113)).code,"blocked")
        self.assertFalse(g.armed)

    def test_confirmation_never_authorizes_next_click(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent("confirm_training","스피드"),SIG)
        self.assertEqual(g.observe(**self.setup_observation(selected="스피드",signature="b"*64)).code,"waiting")
        out=g.observe(**self.setup_observation(selected="스피드",signature="b"*64,now=102))
        self.assertEqual(out.code,"review_required")
        self.assertFalse(out.game_turn_verified)
        self.assertFalse(out.game_input_allowed)

    def test_confirmation_stale_frames_not_success(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent("confirm_training","스피드"),SIG)
        for tick in (101,102):
            self.assertEqual(g.observe(**self.setup_observation(now=tick,selected="스피드")).code,"waiting")

    def test_new_scene_twice_needs_review(self):
        g=TrainingClickGuard(clock=lambda:100)
        g.arm(FakeIntent("confirm_training","스피드"),SIG)
        self.assertEqual(g.observe(**self.setup_observation(scene="이벤트")).code,"waiting")
        self.assertEqual(g.observe(**self.setup_observation(scene="이벤트",now=102)).code,"review_required")

    def test_no_double_arm_and_inactive(self):
        g=TrainingClickGuard(clock=lambda:100)
        self.assertEqual(g.observe(**self.setup_observation()).code,"idle")
        g.arm(FakeIntent(),SIG)
        with self.assertRaises(ValueError):
            g.arm(FakeIntent(),SIG)


if __name__ == "__main__":
    unittest.main()
