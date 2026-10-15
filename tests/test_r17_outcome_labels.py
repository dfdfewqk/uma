"""Synthetic-only tests for R17 outcome evidence and censoring semantics."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from result_labels_r17 import connect_reviews, review_run, collect_results, export_results
from storage import connect, create_run, add_turn, save_run_outcome


class R17OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.root=root
        self.db=connect(root/'runs.sqlite3')
        self.reviews=connect_reviews(root/'reviews.sqlite3')
        self.img=root/'finish.png'
        Image.new('RGB',(80,80),'red').save(self.img)
        self.rid=create_run(self.db,{'scenario':'island_post_patch_v1','event':'챔피언스 미팅',
                                    'character':'테스트 캐릭터'})
        self.tid=add_turn(self.db,self.rid,{'energy':80},{'스피드':{}},[],'스피드')
        save_run_outcome(self.db,self.rid,{'status':'육성 완료','final_stats':'1500 1200'})
    def tearDown(self):
        self.db.close();self.reviews.close();self.temp.cleanup()
    def record(self, **kwargs):
        args=dict(server='KR',patch_version='KR-2026-10-16',provenance_group='device1-run1',
                  reviewer_note='테스트용 이미지 검수',race_matches=None,race_wins=None,loh_points=None)
        args.update(kwargs)
        return review_run(self.db,self.reviews,self.rid,self.img,**args)
    def test_verified_completed_record(self):
        self.record()
        a=collect_results(self.db,self.reviews)
        self.assertEqual(len(a['kept']),1)
        self.assertEqual(a['kept'][0]['status'],'completed')
        self.assertFalse(a['kept'][0]['direct_ml_training_allowed'])
        self.assertNotIn('테스트 캐릭터',str(a['kept'][0]))
    def test_censored_not_failure(self):
        save_run_outcome(self.db,self.rid,{'status':'도축/중단','reason':'목표 스킬 미획득'})
        self.record()
        data=collect_results(self.db,self.reviews)['kept'][0]
        self.assertEqual(data['status'],'censored_abandoned')
        self.assertTrue(data['censored'])
        self.assertIsNone(data['race_results']['wins'])
    def test_no_race_results_on_abandoned(self):
        save_run_outcome(self.db,self.rid,{'status':'도축/중단','reason':'인연도 부족'})
        with self.assertRaises(ValueError):self.record(race_matches=5,race_wins=2)
    def test_race_wins_bound(self):
        with self.assertRaises(ValueError):self.record(race_matches=3,race_wins=4)
    def test_race_pairs(self):
        with self.assertRaises(ValueError):self.record(race_matches=10)
    def test_race_invalid_bool(self):
        with self.assertRaises(ValueError):self.record(race_matches=True,race_wins=1)
    def test_no_ongoing(self):
        save_run_outcome(self.db,self.rid,{'status':'진행중'})
        with self.assertRaises(ValueError):self.record()
    def test_missing_patch(self):
        with self.assertRaises(ValueError):self.record(patch_version='')
    def test_missing_source(self):
        with self.assertRaises(ValueError):self.record(provenance_group='')
    def test_invalid_image(self):
        self.img.write_bytes(b'bad image')
        with self.assertRaises(Exception):self.record()
    def test_modified_outcome_invalidates_review(self):
        self.record()
        save_run_outcome(self.db,self.rid,{'status':'도축/중단','reason':'설정 변경'})
        audit=collect_results(self.db,self.reviews)
        self.assertFalse(audit['kept']);self.assertEqual(len(audit['excluded']),1)
    def test_modified_image_invalidates_review(self):
        self.record()
        Image.new('RGB',(80,80),'blue').save(self.img)
        self.assertEqual(len(collect_results(self.db,self.reviews)['excluded']),1)
    def test_more_turns_invalidates_review(self):
        self.record()
        add_turn(self.db,self.rid,{'energy':80},{'지능':{}},[],'지능')
        self.assertEqual(len(collect_results(self.db,self.reviews)['excluded']),1)
    def test_export_only_reviewed(self):
        self.record(race_matches=10,race_wins=6)
        target=self.root/'export.jsonl'
        info=export_results(self.db,self.reviews,target)
        self.assertEqual(info['exported'],1)
        content=target.read_text('utf-8')
        self.assertIn('"wins": 6',content)
        self.assertNotIn('device1-run1',content)
    def test_unsupported_loh_on_champ(self):
        self.record(loh_points=1234)
        self.assertEqual(len(collect_results(self.db,self.reviews)['excluded']),1)
    def test_valid_loh_record(self):
        r=create_run(self.db,{'scenario':'island_post_patch_v1','event':'리그 오브 히어로즈'})
        add_turn(self.db,r,{'energy':80},{'지능':{}},[],'지능')
        save_run_outcome(self.db,r,{'status':'육성 완료'})
        review_run(self.db,self.reviews,r,self.img,server='KR',patch_version='KR-2026-10-16',
                   provenance_group='another',reviewer_note='가상 검수',loh_points=12000)
        self.assertEqual(collect_results(self.db,self.reviews)['kept'][0]['race_results']['loh_points'],12000)

if __name__=='__main__':unittest.main()
