"""R38: JP Tucker outing reference and character-specific race-goal safeguards.

Synthetic test cases only. No claimed KR screenshots or ML labels.
"""
from __future__ import annotations
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from race_outing_r38 import (RaceGoal, CharacterCalendar, ScreenTurn,
                            load_tucker, next_goal, assess_turn)


def observation(**change):
    item=ScreenTurn(character_id='sample:character',variant_id='base',
        server='JP',patch_version='2025-06-30',scenario='island_post_patch_v1',
        year='클래식',month=5,half='전반',energy=30,energy_cap=100,
        tucker_outing_stage=3,tucker_4lb_confirmed=True,
        tucker_outing_unlocked=True,goal_screen_verified=True,
        outing_screen_verified=True)
    return replace(item,**change)


def calendar(*goals,complete=True):
    return CharacterCalendar(character_id='sample:character',variant_id='base',
        server='JP',patch_version='2025-06-30',scenario='island_post_patch_v1',
        source='character_screen_review',goals=tuple(goals),complete=complete)


class R38CalendarAndFriendTests(unittest.TestCase):
    def test_5_stages_with_full_limit_break_reference_only(self):
        data=load_tucker()
        self.assertFalse(data['kr_verified'])
        self.assertFalse(data['auto_applied_score_weights'])
        self.assertEqual([[a['energy_recovery'] for a in data['effects'][str(n)]]
                          for n in range(1,6)],[[32],[32],[80,0],[40],[48]])

    def test_base_turn_coordinates(self):
        self.assertEqual(RaceGoal('주니어',7,'전반','start').position(),0)
        self.assertEqual(RaceGoal('주니어',12,'후반','end').position(),11)
        self.assertEqual(RaceGoal('클래식',1,'전반','start').position(),12)
        self.assertEqual(RaceGoal('시니어',12,'후반','end').position(),59)

    def test_current_mandatory_race_from_character_specific_screen(self):
        goal=RaceGoal('클래식',5,'전반','Test Mandatory Race')
        result=assess_turn(observation(),calendar(goal),tucker_data=load_tucker())
        self.assertEqual(result.immediate_action,'목표 레이스')
        self.assertFalse(result.optimal_action_verified)
        self.assertFalse(result.requires_typed_input)

    def test_next_turn_mandatory_race_caution(self):
        goal=RaceGoal('클래식',5,'후반','Next Race')
        result=assess_turn(observation(),calendar(goal))
        self.assertIsNone(result.immediate_action)
        self.assertTrue(any('다음 턴' in text for text in result.messages))
        self.assertTrue(any('충돌' in text for text in result.messages))

    def test_other_goal_is_not_claimed_race(self):
        goal=RaceGoal('클래식',5,'전반','Fan gate','fans')
        result=assess_turn(observation(),calendar(goal))
        self.assertIsNone(result.immediate_action)
        self.assertTrue(any('출전과 다릅니다' in s for s in result.messages))

    def test_calendar_missing_does_not_make_up_race(self):
        result=assess_turn(observation(),None)
        self.assertIsNone(result.immediate_action)
        self.assertTrue(any('달력' in s for s in result.messages))

    def test_wrong_character_variant_server_patch_refused(self):
        goal=RaceGoal('클래식',5,'전반','Wrong Scope')
        for item in (
            observation(character_id='another'),
            observation(variant_id='costume'),
            observation(server='KR'),
            observation(patch_version='2026-01-01')
        ):
            with self.subTest(item=item):
                result=assess_turn(item,calendar(goal))
                self.assertIsNone(result.immediate_action)

    def test_calendar_requires_source_and_no_duplicate_goals(self):
        goal=RaceGoal('클래식',5,'전반','Goal')
        with self.assertRaises(ValueError):
            calendar(goal,goal).validate()
        with self.assertRaises(ValueError):
            replace(calendar(goal),source='guessed_from_race_list').validate()
        with self.assertRaises(ValueError):
            calendar(complete=True).validate()

    def test_unverified_screen_blocks_specific_recommendation(self):
        goal=RaceGoal('클래식',5,'전반','Race')
        result=assess_turn(observation(goal_screen_verified=False),calendar(goal))
        self.assertIsNone(result.immediate_action)

    def test_tucker_phase_unknown_does_not_infer_recovery(self):
        for item in (observation(tucker_outing_stage=None),
                     observation(tucker_4lb_confirmed=False),
                     observation(outing_screen_verified=False),
                     observation(tucker_outing_unlocked=None)):
            with self.subTest(item=item):
                result=assess_turn(item)
                self.assertFalse(any('회복 0/80' in t for t in result.messages))
                self.assertTrue(any('터커 외출 단계' in t for t in result.messages))

    def test_tucker_third_stage_has_two_choices_no_made_up_best(self):
        result=assess_turn(observation())
        self.assertTrue(any('회복 0/80' in t for t in result.messages))
        self.assertIsNone(result.immediate_action)
        self.assertFalse(result.optimal_action_verified)

    def test_recovery_is_capped_by_screen_energy_cap(self):
        result=assess_turn(observation(energy=92,energy_cap=100))
        self.assertTrue(any('회복 상한: 0/8' in t for t in result.messages))

    def test_invalid_energy_stage_and_flags_refused(self):
        for item in (observation(energy=True),observation(energy=151),
                     observation(energy=101,energy_cap=100),
                     observation(tucker_outing_stage=6),
                     observation(tucker_4lb_confirmed=1),
                     observation(year='주니어',month=1)):
            with self.subTest(item=item), self.assertRaises(ValueError):
                item.validate()

    def test_incomplete_calendar_keeps_warning(self):
        goal=RaceGoal('시니어',12,'후반','Late')
        result=assess_turn(observation(),calendar(goal,complete=False))
        self.assertTrue(any('일부만' in m for m in result.messages))

    def test_source_conflicts_are_explicit_not_formulas(self):
        pack=load_tucker()
        self.assertTrue(any('Source conflict' in s for s in pack['caveats']))
        self.assertGreaterEqual(len(pack['source_references']),3)


if __name__=='__main__':
    unittest.main()
