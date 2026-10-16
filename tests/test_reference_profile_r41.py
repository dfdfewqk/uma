"""Research profiles remain explicitly JP references after four-round mapping."""
import unittest
from target_selector_r39 import Target,kind_for_round
from reference_profile_r41 import load_reference,skill_reference_notice

class HistoricalReferenceR41Tests(unittest.TestCase):
    def test_four_rounds_four_styles_have_research_profiles(self):
        for r in range(1,5):
            for style in ('도주','선행','선입','추입'):
                with self.subTest(round=r,style=style):
                    record=load_reference(Target(kind_for_round(r),r,style))
                    self.assertEqual(record.source_region,'JP')
                    self.assertTrue(record.reference_id.startswith('jp-2025-'))
                    self.assertGreater(len(record.source_ids),0)
                    self.assertFalse(record.eligible_for_auto_buy)
                    self.assertFalse(record.eligible_for_ml)

    def test_confirmed_only_first_kr_course_from_secondary_sources(self):
        first=load_reference(Target(kind_for_round(1),1,'선입'))
        self.assertTrue(first.kr_course_verified)
        self.assertIn('일본 공략',skill_reference_notice(first))
        for r in (2,3,4):
            with self.subTest(round=r):
                record=load_reference(Target(kind_for_round(r),r,'추입'))
                self.assertFalse(record.kr_course_verified)
                self.assertIn('한국 서버 코스 미확정',skill_reference_notice(record))

    def test_never_convert_jp_research_to_auto_buy_without_evidence(self):
        ref=load_reference(Target(kind_for_round(4),4,'추입'))
        self.assertTrue(ref.target_skills)
        self.assertFalse(ref.eligible_for_auto_buy)

if __name__=='__main__':
    unittest.main()
