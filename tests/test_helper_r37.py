"""R37 zero-typing helper behavior (synthetic, not KR game validation)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helper_view_r37 import view_from_frame, paused_view, TRAININGS, StableLowEnergy
from helper_smoke_r37 import maybe_run_cli, SCHEMA

ROOT=Path(__file__).resolve().parents[1]


class R37HelperPolicyTests(unittest.TestCase):
    def test_inactive_requires_no_typing(self):
        info=view_from_frame(scene='훈련', active=False, detected_buttons=('스피드',))
        self.assertFalse(info.verified_training)
        self.assertIn('입력은 필요 없습니다',info.explanation)

    def test_unknown_scene_does_not_recommend(self):
        for scene in (None,'스킬','시설','이벤트'):
            with self.subTest(scene=scene):
                info=view_from_frame(scene=scene,active=True,value_count=0)
                self.assertFalse(info.verified_training)
                self.assertTrue('보류' in info.title or '인식 중' in info.title)

    def test_detected_button_and_ocr_candidate_not_treated_as_recommendation(self):
        info=view_from_frame(scene='훈련',active=True,value_count=5,
                             detected_buttons=('스피드','지능'))
        self.assertFalse(info.verified_training)
        self.assertIn('훈련 비교 준비 중',info.title)
        self.assertIn('후보',info.explanation)

    def test_verified_handoff_requires_exact_current_visible_button(self):
        view=view_from_frame(scene='훈련',active=True,
                             detected_buttons=('스피드','파워'),reviewed_hint='파워')
        self.assertTrue(view.verified_training)
        self.assertIn('파워',view.title)
        self.assertIn('직접',view.explanation)
        stale=view_from_frame(scene='훈련',active=True,
                              detected_buttons=('스피드',),reviewed_hint='파워')
        self.assertFalse(stale.verified_training)
        self.assertIn('보류',stale.title)

    def test_repeated_matching_hint_refused(self):
        info=view_from_frame(scene='훈련',active=True,reviewed_hint='스피드',
                             detected_buttons=('스피드','스피드'))
        self.assertFalse(info.verified_training)

    def test_invalid_detection_provenance_refused(self):
        errors=(
            {'scene':'알 수 없는 화면'},
            {'active':None},
            {'value_count':True},
            {'value_count':-1},
            {'detected_buttons':['스피드']},
            {'detected_buttons':('임의 행동',)},
            {'reviewed_hint':'휴식'},
        )
        for kwargs in errors:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                given=dict(scene='훈련',active=True)
                given.update(kwargs)
                view_from_frame(**given)

    def test_low_energy_requires_two_same_fresh_observations(self):
        gate=StableLowEnergy()
        self.assertFalse(gate.observe(energy=24,epoch=4,scene='훈련',active=True))
        self.assertTrue(gate.observe(energy=24,epoch=4,scene='훈련',active=True))
        gate.reset()
        self.assertFalse(gate.observe(energy=20,epoch=5,scene='훈련',active=True))
        self.assertFalse(gate.observe(energy=20,epoch=6,scene='훈련',active=True))
        self.assertFalse(gate.observe(energy=20,epoch=6,scene='이벤트',active=True))
        self.assertFalse(gate.observe(energy=10,epoch=6,scene='훈련',active=False))
        self.assertFalse(gate.observe(energy=None,epoch=6,scene='훈련',active=True))
        self.assertFalse(gate.observe(energy=True,epoch=6,scene='훈련',active=True))
        self.assertFalse(gate.observe(energy=35,epoch=6,scene='훈련',active=True))

    def test_low_energy_is_warning_not_verified_optimal_action(self):
        caution=view_from_frame(scene='훈련',active=True,value_count=1,
                detected_buttons=('스피드',),reviewed_hint='스피드',
                low_energy_candidate=True)
        self.assertFalse(caution.verified_training)
        self.assertIn('휴식·외출 검토',caution.title)
        self.assertIn('OCR',caution.explanation)
        with self.assertRaises(ValueError):
            view_from_frame(scene='훈련',active=True,low_energy_candidate=1)

    def test_no_live_game_manual_automation(self):
        self.assertFalse(paused_view().verified_training)
        self.assertNotIn('자동 클릭',view_from_frame(scene='훈련',active=True).title)
        self.assertNotIn('휴식',TRAININGS)

    def test_companion_main_is_entry_free_and_auto_polling(self):
        src=(ROOT/'companion.py').read_text(encoding='utf-8')
        self.assertNotIn('tk.Entry(',src)
        self.assertIn('self.monitoring=True',src)
        self.assertIn('view_from_frame(',src)
        self.assertIn('if not self.monitoring:',src)
        self.assertIn("self._toggle_dev_tools",src)
        self.assertIn('r37_helper_smoke(lambda: Companion(demo=True))',src)
        self.assertNotIn('recommendation_status(False,False)',src)

    def test_smoke_cli_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json';path.write_text('old')
            with self.assertRaises(SystemExit):
                maybe_run_cli(lambda: None,['--helper-smoke-report',str(path)])
            self.assertEqual(path.read_text(),'old')

    def test_smoke_cli_writes_failure_without_sensitive_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json'
            with patch('helper_smoke_r37.inspect_helper',
                       side_effect=RuntimeError('local private username')):
                with self.assertRaises(SystemExit) as status:
                    maybe_run_cli(lambda: None,['--helper-smoke-report',str(path)])
            self.assertEqual(status.exception.code,1)
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['schema'],SCHEMA)
            self.assertEqual(data['result'],'FAIL')
            self.assertNotIn('username',json.dumps(data))
            self.assertFalse(data['game_client_tested'])

    def test_cli_no_argument_no_interception(self):
        self.assertFalse(maybe_run_cli(lambda: None,[]))


if __name__=='__main__':
    unittest.main()
