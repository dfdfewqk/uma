import unittest
from caption_audit_r27 import parse_captions, audit

class CaptionAuditR27Tests(unittest.TestCase):
    def test_srt_keeps_times_and_cues(self):
        s='1\n00:00:01,200 --> 00:00:03,900\n처음 섬 트레이닝은 인연도를 보세요.\n\n2\n00:00:04,000 --> 00:00:06,000\n트레이너님!\n'
        d=audit(s)
        self.assertEqual(d['segment_count'],2)
        self.assertEqual(d['segments'][0]['start_sec'],1.2)
        self.assertEqual(d['segments'][1]['speaker_hypothesis'],'possible_game_dialogue')
        self.assertTrue(all(not c['training_eligible'] for c in d['segments']))
    def test_youtube_pasted_timestamps(self):
        d=audit('0:02 초반 인연도 중요해요\n0:14 와 감사합니다')
        self.assertEqual(d['segment_count'],2)
        self.assertEqual(d['segments'][0]['start_sec'],2)
    def test_webvtt(self):
        d=audit('WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n티켓을 확인해요\n')
        self.assertEqual(d['segment_count'],1)
    def test_pasted_plain_transcript(self):
        d=audit('우정 훈련을 확인하세요\n야호')
        self.assertEqual(d['segment_count'],2)
        self.assertEqual(d['approved_training_labels'],0)
    def test_patch_and_absolute_claim_flagged(self):
        d=audit('0:09 스피드 5장만 무조건 좋아요')
        self.assertIn('absolute_strategy_claim_needs_counterexamples',d['segments'][0]['review_flags'])
        self.assertIn('support_composition_patch_dependency_check',d['segments'][0]['review_flags'])
    def test_no_source_no_claim(self):
        with self.assertRaises(ValueError):audit(' ')
    def test_no_automatic_speaker_certainty(self):
        d=audit('0:05 초반 시설을 보세요\n0:08 트레이너님 힘내자')
        self.assertEqual(d['verified_creator_explanations'],0)
        self.assertTrue(all(not s['speaker_verified'] for s in d['segments']))
if __name__=='__main__':unittest.main()
