"""Tests use fake screenshots only in temporary test folders, never research rows."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.review_tools.annotation_core import (
    validate_annotation, add_annotation, read_annotations, audit_annotations, AnnotationError, check_media,
    read_sources, STATS
)
from research.review_tools.frame_sampler import read_chapters, sample_local_video

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==')


class ReviewR2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.pre=self.folder/'pre.png'
        self.post=self.folder/'post.png'
        self.pre.write_bytes(PNG)
        self.post.write_bytes(PNG)
        self.csv=self.folder/'reviews.csv'
        self.sources=read_sources()
        self.raw={
            'source_id':'S011','case_id':'champ_001','video_seconds':'300',
            'server':'JP','patch_status':'post_2025_06_30_confirmed',
            'patch_evidence':'실제 영상 설명/게임 기믹에서 수정 후 환경임을 교차 확인',
            'competition':'챔피언스 미팅','run_purpose':'champ_main','school_year':'클래식','turn_label':'6월 전반',
            'reviewer':'QA1','energy':'75', 'speed':'800','stamina':'600','power':'650',
            'guts':'550','wisdom':'590', 'skill_points':'950','island_tickets':'1',
            'development_points':'20','facilities_json':'{"speed":2}',
            'alternatives_json':'{"스피드":{"speed":55},"지능":{"wisdom":25}}',
            'chosen_action':'스피드','post_action_json':'{"speed":55}',
            'frame_before_path':str(self.pre),'frame_after_path':str(self.post),
            'observed_choice':'true','observed_result':'true','character':'검수예시'
        }

    def test_rejects_without_real_image(self):
        self.raw['frame_before_path']=str(self.folder/'missing.png')
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)

    def test_rejects_untrusted_metadata_without_patch_evidence(self):
        self.raw['patch_evidence']=''
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)

    def test_rejects_bad_source_id_and_pre_patch(self):
        self.raw['source_id']='no_such_video'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)
        self.raw['source_id']='S001'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)

    def test_keeps_score_runs_out_of_champ_supervision(self):
        self.raw['source_id']='S010'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)
        self.raw['run_purpose']='evaluation_score'
        self.raw['competition']='미확인'
        self.assertEqual(validate_annotation(self.raw,self.sources)['run_purpose'],'evaluation_score')

    def test_rejects_invalid_stats_or_json(self):
        self.raw['energy']='-10'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)
        self.raw['energy']='20'
        self.raw['alternatives_json']='{"broken":'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)

    def test_rejects_mismatched_action(self):
        self.raw['chosen_action']='레이스'
        with self.assertRaises(AnnotationError): validate_annotation(self.raw,self.sources)

    def test_verifies_complete_and_atomic_write(self):
        r=add_annotation(self.raw, self.csv,self.sources)
        self.assertEqual(r['review_grade'],'complete')
        self.assertEqual(r['frame_before_sha256'],check_media(self.pre)[1])
        self.assertEqual(len(read_annotations(self.csv)),1)
        self.assertEqual(audit_annotations(self.csv)['full_before_and_after'],1)
        with self.assertRaises(AnnotationError): add_annotation(self.raw,self.csv,self.sources)
        self.assertEqual(len(read_annotations(self.csv)),1)

    def test_missing_optional_is_partial(self):
        self.raw['frame_after_path']=''
        self.raw['observed_result']='false'
        self.raw['stamina']=''
        result=add_annotation(self.raw,self.csv,self.sources)
        self.assertEqual(result['review_grade'],'partial')
        self.assertEqual(audit_annotations(self.csv)['partial_rows'],1)

    def test_changed_image_hash_detected(self):
        add_annotation(self.raw,self.csv,self.sources)
        self.pre.write_bytes(PNG+b'changed')
        self.assertTrue(audit_annotations(self.csv)['errors'])

    def test_source_chapters_exist(self):
        p=Path(__file__).resolve().parents[1]/'research/jp_post_patch_2025/video_chapters.csv'
        self.assertGreater(len(read_chapters(p,'S010')),5)
        self.assertEqual(read_chapters(p,'S011'),[])

    def test_local_video_only(self):
        with self.assertRaises(FileNotFoundError):
            sample_local_video(self.folder/'missing.mp4',self.folder/'out',[15])

if __name__=='__main__': unittest.main()
