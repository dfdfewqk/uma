"""Synthetic fixtures only: real JP gameplay claims are never fabricated."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research' / 'jp_post_patch_2025'))

from validate_research import TURN_COLUMNS, validate_turn_annotations, verify, TABLES


class ResearchR32Tests(unittest.TestCase):
    def setUp(self):
        self.record = dict.fromkeys(TURN_COLUMNS, '')
        self.record.update(
            turn_id='T_TEST', case_id='C001', source_id='S010',
            video_timestamp_seconds='180', school_year='junior', period='7월 전반',
            remaining_turns='60', speed='300', stamina='300', power='300',
            guts='300', wisdom='300', energy='80', motivation='normal',
            friendship_positions='1', support_bonds_json='{}',
            island_tickets='1', next_ticket_turn='2',
            construction_levels_json='{}',
            available_actions_json='["스피드", "외출"]',
            chosen_action='외출', post_action_delta_json='{}',
            action_success_verified='not_observed',
            observation_method='human_video_frame', confidence='human_confirmed',
            server='JP', patch_version='JP-2025-06-30-post',
            source_group='youtube:S010', evidence_before_sha256='a'*64,
            evidence_after_sha256='b'*64, review_status='human_verified')

    def check(self, row):
        return validate_turn_annotations([row], {'S010'}, {'C001': 'S010'})

    def test_valid_synthetic_structure_is_not_real_record(self):
        self.check(self.record)

    def test_fail_closed_missing_patches_evidence_and_choices(self):
        errors = {'server': 'KR', 'patch_version': 'unknown',
                  'source_group': '', 'review_status': 'description_only',
                  'observation_method': 'video_metadata',
                  'evidence_after_sha256': 'a'*64,
                  'available_actions_json': '[]',
                  'chosen_action': '레이스', 'remaining_turns': '-1',
                  'support_bonds_json': '{bad'}
        for field, val in errors.items():
            with self.subTest(field=field):
                row = dict(self.record)
                row[field] = val
                with self.assertRaises(ValueError):
                    self.check(row)

    def test_wrong_source_or_duplicate_turns_rejected(self):
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            validate_turn_annotations([self.record], {'S010'}, {'C001': 'S005'})
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            validate_turn_annotations([self.record, self.record], {'S010'}, {'C001': 'S010'})


if __name__ == '__main__':
    unittest.main()
