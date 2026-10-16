"""R48 screenshot-only preview recommendation regression tests, NOT real-game proof."""
from __future__ import annotations

from unittest.mock import patch
import unittest

from PIL import Image, ImageDraw

from training_preview_r48 import (
    NAMES, PreviewCollector, selected_training, read_training_gains,
    portrait_supported, _gain_crops,
)


def frame(chosen=0, *, gold_regions=(0,1),w=384,h=740):
    image=Image.new("RGB",(w,h),(54,61,80))
    draw=ImageDraw.Draw(image)
    # Stable baseline stats row; it does not change as previews change.
    draw.rectangle((round(w*.02),round(h*.67),round(w*.98),round(h*.73)),
                   fill=(150,165,221))
    # Exactly one golden selected-training ribbon underneath the icon.
    x=(.099,.282,.467,.649,.83)[chosen]
    draw.rectangle((round((x-.045)*w),round(h*.86),
                    round((x+.045)*w),round(h*.92)),fill=(250,186,25))
    for j in gold_regions:
        x=(.099,.282,.467,.649,.83)[j]
        draw.rectangle((round((x-.045)*w),round(h*.621),
                        round((x+.045)*w),round(h*.652)),fill=(251,167,43))
    return image


class PreviewReaderTests(unittest.TestCase):
    def test_selection_requires_one_unique_gold_marker(self):
        for i,name in enumerate(NAMES):
            with self.subTest(i=i):
                self.assertEqual(selected_training(frame(i)),name)
        blank=Image.new("RGB",(384,740),(54,61,80))
        self.assertIsNone(selected_training(blank))

    def test_non_portrait_rejected(self):
        self.assertTrue(portrait_supported(frame()))
        self.assertFalse(portrait_supported(Image.new("RGB",(900,600))))
        self.assertFalse(portrait_supported(Image.new("RGB",(250,700))))

    def test_gain_ocr_failure_does_not_invent_zero(self):
        with patch("training_preview_r48._run_digit_ocr",return_value=None):
            self.assertIsNone(read_training_gains(frame(0),"/mock/tesseract"))
        self.assertIsNone(read_training_gains(frame(0),None))

    def test_collector_requires_two_same_observations_for_each_preview(self):
        collector=PreviewCollector()
        with patch("training_preview_r48.read_training_gains",
                   return_value=(12,0,0,0,0)):
            first=collector.observe(frame(0),42,"/mock/tesseract")
            self.assertEqual(first.collected,0)
            second=collector.observe(frame(0),42,"/mock/tesseract")
            self.assertEqual(second.collected,1)
            third=collector.observe(frame(1),42,"/mock/tesseract")
            self.assertEqual(third.collected,1)

    def test_five_confirmed_preview_candidates_return_ranked_ocr_only(self):
        collector=PreviewCollector()
        with patch("training_preview_r48.read_training_gains") as detector:
            for i in range(5):
                detector.return_value=(10+i*6,0,0,0,0)
                collector.observe(frame(i),42,"/mock/tesseract")
                output=collector.observe(frame(i),42,"/mock/tesseract")
            self.assertEqual(output.collected,5)
            self.assertEqual(output.recommendation,"지능")
            self.assertFalse(output.actual_game_verified)
            self.assertFalse(output.optimality_verified)
            self.assertIn("임시 1순위",output.explanation)
            self.assertIn("인연",output.explanation)

    def test_uncertain_tie_defers_and_window_switch_resets(self):
        collector=PreviewCollector()
        with patch("training_preview_r48.read_training_gains",return_value=(10,0,0,0,0)):
            for i in range(5):
                collector.observe(frame(i),42,"/mock/tesseract")
                output=collector.observe(frame(i),42,"/mock/tesseract")
            self.assertIsNone(output.recommendation)
            self.assertIn("비슷",output.explanation)
            switched=collector.observe(frame(0),43,"/mock/tesseract")
            self.assertEqual(switched.collected,0)

    def test_unreadable_second_frame_does_not_confirm(self):
        collector=PreviewCollector()
        with patch("training_preview_r48.read_training_gains",side_effect=[
            (9,0,0,0,0),None,(9,0,0,0,0)]):
            collector.observe(frame(0),42,"/mock/tesseract")
            collector.observe(frame(0),42,"/mock/tesseract")
            last=collector.observe(frame(0),42,"/mock/tesseract")
        self.assertEqual(last.collected,0)


if __name__=="__main__":
    unittest.main()
