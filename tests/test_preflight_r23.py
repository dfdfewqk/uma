import json
import unittest
from preflight_r23 import inspect_local_environment,explain,PreflightStatus

class TestR23Preflight(unittest.TestCase):
    def test_schema_flags_are_private(self):
        s=inspect_local_environment()
        doc=s.safe_export()
        self.assertFalse(doc['automatic_clicks_enabled'])
        self.assertTrue(doc['manual_review_required'])
        self.assertFalse(doc['actually_tested_on_korean_client'])
        self.assertNotIn('path',json.dumps(doc).lower())
        self.assertNotIn('title',json.dumps(doc).lower())
        self.assertNotIn('ip_address',json.dumps(doc).lower())

    def test_report_explains_unavailable(self):
        s=PreflightStatus(*([False]*8))
        lines=explain(s)
        self.assertTrue(any('미완료' in line for line in lines))
        self.assertTrue(any('자동 클릭' in line for line in lines))

    def test_report_explains_available(self):
        s=PreflightStatus(*([True]*8))
        lines=explain(s)
        self.assertTrue(any('확인' in line for line in lines))
        self.assertFalse(s.automatic_clicks_enabled)

if __name__=='__main__':unittest.main()
