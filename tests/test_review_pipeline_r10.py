"""R10 tests: synthetic frame bytes exist only under TemporaryDirectory, never study data."""
import csv
import json
import base64
import tempfile
import unittest
from pathlib import Path

from research.review_tools.annotation_core import add_annotation, read_sources
from review_pipeline_r10 import (build_worklist, apply_progress, update_progress,
    read_progress, audit_worklist, _atomic_csv, export_r9_verified, create_r9_template)
from calibration_r9 import audit_csv, STATS, FACILITIES

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==')

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.progress=self.folder/'progress.json'
        self.annotation_file=self.folder/'annotations.csv'
        self.before=self.folder/'before.png'; self.before.write_bytes(PNG)
        self.after=self.folder/'after.png'; self.after.write_bytes(PNG+b'test-only-after')
        self.worklist=build_worklist()
        self.task=next(t for t in self.worklist if t['source_id']=='S011')
        self.source=read_sources()['S011']
        self.raw={
            'source_id':'S011','case_id':'run_001','video_seconds':'300',
            'server':'JP','patch_status':'post_2025_06_30_confirmed',
            'patch_evidence':'수정 이후의 시설 보정을 확인한 근거가 있는 실제 영상',
            'competition':'챔피언스 미팅','run_purpose':'champ_main','school_year':'클래식',
            'turn_label':'6월 전반','reviewer':'test','energy':'70',
            'speed':'800','stamina':'600','power':'650','guts':'550','wisdom':'590',
            'skill_points':'950','island_tickets':'1','development_points':'20',
            'facilities_json':'{"speed":2}',
            'alternatives_json':'{"스피드":{"speed":55},"지능":{"wisdom":25}}',
            'chosen_action':'스피드','post_action_json':'{"speed":55}',
            'frame_before_path':str(self.before),'frame_after_path':str(self.after),
            'observed_choice':'true','observed_result':'true','character':'검수테스트캐릭터'
        }

    def _save_annotation(self):
        return add_annotation(self.raw,self.annotation_file,read_sources())

    def _bundle(self, aid):
        return dict(annotation_id=aid, source_url=self.source['url'],
            reviewer_confirmed_preview=True,synthetic=False,
            visual_evidence_note='테스트용 화면의 표시 수치를 수작업 검수함 - 실전 입력 데이터 아님',
            training='스피드',preview_frame_path=str(self.before),
            displayed_gains={k:2 for k in ('g_speed','g_stamina','g_power','g_guts','g_wisdom','skill_points')},
            capture_date='2025-07-23',phase='클래식 6월 전반',
            support_deck_key='test_all6_known',context_key='test_fixed_context',
            facility_levels={name:0 for name in FACILITIES},
            facility_routes={name:'미선택' for name in FACILITIES},
            friendship_counts={name:0 for name in STATS})

    def test_worklist_video_only_and_stable_ids(self):
        self.assertGreaterEqual(len(self.worklist),17)
        self.assertEqual(len({r['task_id'] for r in self.worklist}),len(self.worklist))
        self.assertTrue(all(r['source_id'].startswith('S0') for r in self.worklist))
        self.assertEqual(len([r for r in self.worklist if r['source_id']=='S010']),12)

    def test_no_automatic_main_label_for_factor_video(self):
        task=next(r for r in self.worklist if r['source_id']=='S012')
        self.assertEqual(task['suggested_purpose'],'not_assumed')
        self.assertEqual(self.task['suggested_purpose'],'champ_main')

    def test_progress_initial_empty_and_no_real_verified(self):
        p=apply_progress(self.worklist,self.progress,self.annotation_file)
        self.assertTrue(all(r['status']=='pending' for r in p))
        s=audit_worklist(p)
        self.assertEqual(s['reviewed_with_before_after'],0)

    def test_mark_in_review_and_blocked(self):
        for state in ('in_review','blocked'):
            update_progress(self.task['task_id'],state,note='검수 필요',
                  progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)
            self.assertEqual(read_progress(self.progress)[self.task['task_id']]['status'],state)
        self.assertEqual(apply_progress(self.worklist,self.progress,self.annotation_file)[0]['status'],'blocked')

    def test_unknown_task_and_state_rejected(self):
        with self.assertRaises(ValueError):
            update_progress('fake','pending',progress_path=self.progress,worklist=self.worklist)
        with self.assertRaises(ValueError):
            update_progress(self.task['task_id'],'done',progress_path=self.progress,worklist=self.worklist)

    def test_verified_requires_annotation(self):
        with self.assertRaises(ValueError):
            update_progress(self.task['task_id'],'verified',annotation_id='not-existing',
                progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)

    def test_complete_verified_check_and_hash_revoke(self):
        a=self._save_annotation()
        update_progress(self.task['task_id'],'verified',annotation_id=a['annotation_id'],
            progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)
        p=apply_progress(self.worklist,self.progress,self.annotation_file)
        self.assertEqual(next(r for r in p if r['task_id']==self.task['task_id'])['status'],'verified')
        self.before.write_bytes(PNG+b'changed')
        p=apply_progress(self.worklist,self.progress,self.annotation_file)
        self.assertEqual(next(r for r in p if r['task_id']==self.task['task_id'])['status'],'blocked')

    def test_cross_source_annotation_is_rejected(self):
        a=self._save_annotation()
        other=next(x for x in self.worklist if x['source_id']=='S010')
        with self.assertRaises(ValueError):
            update_progress(other['task_id'],'verified',annotation_id=a['annotation_id'],
                progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)

    def test_chapter_distance_check(self):
        a=self._save_annotation()
        far=next(x for x in self.worklist if x['source_id']=='S010' and x['video_seconds']==0)
        with self.assertRaises(ValueError):
            update_progress(far['task_id'],'verified',annotation_id=a['annotation_id'],
                progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)

    def test_partial_cannot_be_verified(self):
        self.raw['observed_result']='false';self.raw['frame_after_path']=''
        a=self._save_annotation()
        with self.assertRaises(ValueError):
            update_progress(self.task['task_id'],'verified',annotation_id=a['annotation_id'],
                progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)

    def test_progress_file_invalid(self):
        self.progress.write_text('{"version":900,"tasks":{}}',encoding='utf8')
        with self.assertRaises(ValueError):read_progress(self.progress)

    def test_queue_export_utf8(self):
        dst=self.folder/'tasks.csv'
        _atomic_csv(dst,tuple(self.worklist[0]),self.worklist)
        with dst.open('r',encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),len(self.worklist))

    def test_r9_export_empty_has_header(self):
        dst=self.folder/'r9.csv'
        create_r9_template(dst)
        self.assertEqual(audit_csv(dst).total_rows,0)

    def test_no_bundle_keeps_r9_empty(self):
        bundles=self.folder/'bundles.json'; bundles.write_text('[]',encoding='utf8')
        dst=self.folder/'r9.csv'
        result=export_r9_verified(self.annotation_file,bundles,dst)
        self.assertEqual(result['accepted'],0)
        self.assertEqual(audit_csv(dst).total_rows,0)

    def test_unverified_bundle_rejected(self):
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([self._bundle('missing')]),encoding='utf8')
        dst=self.folder/'r9.csv'
        result=export_r9_verified(self.annotation_file,bundles,dst)
        self.assertEqual(result['accepted'],0)
        self.assertEqual(len(result['rejected']),1)

    def test_reviewed_preview_can_be_exported_to_r9(self):
        a=self._save_annotation(); bundles=self.folder/'bundles.json'
        bundles.write_text(json.dumps([self._bundle(a['annotation_id'])],ensure_ascii=False),encoding='utf8')
        dst=self.folder/'r9.csv'
        result=export_r9_verified(self.annotation_file,bundles,dst)
        self.assertEqual(result['accepted'],1,result)
        self.assertEqual(audit_csv(dst).accepted,1)

    def test_bad_bundle_not_silently_accepted(self):
        a=self._save_annotation();bundle=self._bundle(a['annotation_id'])
        bundle['reviewer_confirmed_preview']=False
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9.csv')
        self.assertEqual(result['accepted'],0)

    def test_incomplete_gain_fields_rejected(self):
        a=self._save_annotation();bundle=self._bundle(a['annotation_id'])
        bundle['displayed_gains'].pop('g_power')
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9.csv')
        self.assertEqual(result['accepted'],0)

    def test_duplicate_preview_rejected(self):
        a=self._save_annotation();bundle=self._bundle(a['annotation_id'])
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([bundle,bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9.csv')
        self.assertEqual(result['accepted'],1)
        self.assertEqual(len(result['rejected']),1)

    def test_unknown_source_and_hash_prevents_export(self):
        a=self._save_annotation();bundle=self._bundle(a['annotation_id'])
        bundle['source_url']='https://wrong.example.com'
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9.csv')
        self.assertEqual(result['accepted'],0)
        bundle['source_url']=self.source['url'];self.before.write_bytes(PNG+b'changed')
        bundles.write_text(json.dumps([bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9_second.csv')
        self.assertEqual(result['accepted'],0)

    def test_r9_export_refuses_existing_file(self):
        self._save_annotation()
        bundles=self.folder/'bundles.json';bundles.write_text('[]',encoding='utf8')
        out=self.folder/'r9.csv';out.write_text('original user data',encoding='utf8')
        with self.assertRaises(ValueError):
            export_r9_verified(self.annotation_file,bundles,out)
        self.assertEqual(out.read_text(encoding='utf8'),'original user data')

    def test_r9_export_never_overwrites_original_annotation(self):
        bundles=self.folder/'bundles.json';bundles.write_text('[]',encoding='utf8')
        with self.assertRaises(ValueError):
            export_r9_verified(self.annotation_file,bundles,self.annotation_file)

    def test_identical_before_after_is_not_strong_result_evidence(self):
        self.after.write_bytes(PNG)
        a=self._save_annotation()
        with self.assertRaises(ValueError):
            update_progress(self.task['task_id'],'verified',annotation_id=a['annotation_id'],
                progress_path=self.progress,annotation_path=self.annotation_file,worklist=self.worklist)

    def test_score_farming_not_exported_as_champ(self):
        self.raw.update(source_id='S010',run_purpose='evaluation_score',competition='미확인')
        a=self._save_annotation();bundle=self._bundle(a['annotation_id'])
        bundle['source_url']=read_sources()['S010']['url']
        bundles=self.folder/'bundles.json';bundles.write_text(json.dumps([bundle]),encoding='utf8')
        result=export_r9_verified(self.annotation_file,bundles,self.folder/'r9.csv')
        self.assertEqual(result['accepted'],0)

if __name__=='__main__':unittest.main()
