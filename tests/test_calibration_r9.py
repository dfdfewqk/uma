"""R9 safeguards: exclusion, leakage prevention, patch boundaries, uncertainty."""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict

from calibration_r9 import (
    FIELDS, FACILITIES, STATS, NUMERIC, audit_csv, atomic_export_json,
    empty_template, estimate_from_samples, group_key, validate_row,
)


def row(i=1, **kwargs):
    base = dict(sample_id=f's{i}', run_id=f'run{i}', source_type='reviewed_video_frame',
                source_url=f'https://example.com/video/{i}',
                frame_sha256=hashlib.sha256(f'image{i}'.encode()).hexdigest(),
                captured_date='2025-07-03', server='JP', patch_status='JP_after_2025_06_30_2320',
                scenario='island_post_patch_v1', purpose='챔피언스 미팅',
                phase='클래식 7월', training='스피드', character='테스트 캐릭터',
                support_deck_key='카드6장-고정', context_key='의욕/버프/트레Lv/배치-검수키',
                facility_levels_json=json.dumps({s:1 for s in FACILITIES}, ensure_ascii=False),
                facility_routes_json=json.dumps({s:'미선택' for s in FACILITIES}, ensure_ascii=False),
                friendship_counts_json=json.dumps({s:1 for s in STATS}, ensure_ascii=False),
                verified='true', synthetic='false', g_speed='80', g_stamina='15',
                g_power='15', g_guts='10', g_wisdom='10', skill_points='20', reviewer_note='test')
    base.update(kwargs)
    return base


class R9DataSafety(unittest.TestCase):
    def test_valid(self):
        r=validate_row(row())
        self.assertEqual(r['g_speed'], 80)
        self.assertEqual(r['server'], 'JP')

    def test_reject_unverified(self):
        with self.assertRaisesRegex(ValueError, '검수'):
            validate_row(row(verified='false'))

    def test_reject_synthetic(self):
        with self.assertRaises(ValueError):
            validate_row(row(synthetic='true'))

    def test_reject_pre_patch(self):
        with self.assertRaises(ValueError):
            validate_row(row(captured_date='2025-06-29'))

    def test_jp_kr_not_mixed(self):
        with self.assertRaises(ValueError):
            validate_row(row(server='KR'))
        kr=validate_row(row(server='KR', patch_status='KR_post_patch_confirmed'))
        self.assertNotEqual(group_key(kr), group_key(validate_row(row())))

    def test_bad_source_url(self):
        with self.assertRaises(ValueError):
            validate_row(row(source_url=''))
        self.assertEqual(validate_row(row(source_type='original_capture',source_url=''))['source_type'],
                         'original_capture')

    def test_bad_hash(self):
        with self.assertRaises(ValueError):
            validate_row(row(frame_sha256='0'*63))

    def test_disallow_purpose_outside_competition(self):
        with self.assertRaises(ValueError):
            validate_row(row(purpose='평가점'))

    def test_disallow_missing_facility(self):
        with self.assertRaises(ValueError):
            validate_row(row(facility_levels_json='{}'))

    def test_disallow_invalid_routes(self):
        facility={s:3 for s in FACILITIES}; facility['해변의 집']=1
        with self.assertRaises(ValueError):
            validate_row(row(facility_levels_json=json.dumps(facility)))

    def test_disallow_invalid_numeric(self):
        for bad in ('-1','501','nan','1.5',''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_row(row(g_speed=bad))

    def test_miss_required_column(self):
        a=row(); a.pop('phase')
        with self.assertRaises(ValueError):
            validate_row(a)

    def test_grouped_conservatively(self):
        origin=validate_row(row())
        for key, value in (
            ('purpose','리그 오브 히어로즈'),('phase','시니어 8월'),
            ('character','다른 캐릭터'),('context_key','버프 추가'),
            ('support_deck_key','다른 카드'),('training','파워')):
            with self.subTest(key=key):
                altered=validate_row(row(**{key:value}))
                self.assertNotEqual(group_key(origin), group_key(altered))

    def test_duplicate_frame_and_sample(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'example.csv'
            with file.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS)
                w.writeheader()
                w.writerow(row())
                w.writerow(row(2, run_id='run1', frame_sha256=row()['frame_sha256'],
                              source_url=row()['source_url']))
                w.writerow(row(3, sample_id='s1'))
                w.writerow(row(4, verified='false'))
            out=audit_csv(file)
            self.assertEqual((out.total_rows,out.accepted,out.rejected,out.duplicate),(4,1,3,2))

    def test_empty_template_only_header(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'empty.csv'
            empty_template(p)
            audit=audit_csv(p)
            self.assertEqual((audit.total_rows,audit.accepted),(0,0))

    def test_invalid_header_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bad.csv'
            p.write_text('id,title\n1,2',encoding='utf8')
            with self.assertRaises(ValueError):
                audit_csv(p)

    def test_abstain_no_data(self):
        est=estimate_from_samples([],row())
        self.assertIn('보류',est.status)
        self.assertFalse(est.stat_intervals)

    def test_abstain_same_run_many_turns(self):
        values=[validate_row(row(i,run_id='run1')) for i in range(20)]
        est=estimate_from_samples(values,row(999))
        self.assertEqual(est.distinct_runs,1)
        self.assertFalse(est.stat_intervals)

    def test_abstain_less_than_10(self):
        values=[validate_row(row(i)) for i in range(1,10)]
        self.assertFalse(estimate_from_samples(values,row(999)).stat_intervals)

    def test_estimate_when_10_independent_observations(self):
        values=[validate_row(row(i,g_speed=str(50+i))) for i in range(1,13)]
        result=estimate_from_samples(values,row(999))
        self.assertEqual(result.status,'유사 조건 관찰 범위 제공 (실험)')
        self.assertEqual(result.compared_samples,12)
        self.assertLess(result.stat_intervals['g_speed']['p10'], result.stat_intervals['g_speed']['p90'])
        self.assertGreaterEqual(result.leave_one_run_out_mae['g_speed'],0)
        self.assertFalse(result.trained_ml_model)
        self.assertFalse(result.verified_optimal)

    def test_leave_out_selected_run(self):
        values=[validate_row(row(i,g_speed=str(i*3))) for i in range(1,13)]
        target=row(1)
        result=estimate_from_samples(values,target)
        self.assertEqual(result.compared_samples,11)
        self.assertEqual(result.distinct_runs,11)

    def test_no_cross_patch_or_deck_or_scenario(self):
        values=[validate_row(row(i)) for i in range(1,16)]
        self.assertFalse(estimate_from_samples(values,row(888,support_deck_key='new-deck')).stat_intervals)
        self.assertFalse(estimate_from_samples(values,row(888,server='KR',patch_status='KR_post_patch_confirmed')).stat_intervals)

    def test_atomic_export_minimized_private_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'audit.json'
            source=Path(temp)/'observations.csv'
            with source.open('w',newline='',encoding='utf8') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerow(row())
            audit=audit_csv(source)
            atomic_export_json(path,audit,[])
            summary=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(summary['audit']['accepted'],1)
            self.assertNotIn('observations',summary['audit'])
            self.assertFalse(summary['trained_ml_model'])
            self.assertFalse(summary['verified_optimal'])
            self.assertNotIn('example.com',path.read_text(encoding='utf8'))


if __name__=='__main__':
    unittest.main()

class R9IntegrityExtra(unittest.TestCase):
    def test_same_frame_cross_run_is_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fake.csv'
            with path.open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader()
                w.writerow(row(1))
                w.writerow(row(2,frame_sha256=row(1)['frame_sha256']))
            a=audit_csv(path)
            self.assertEqual((a.accepted,a.duplicate),(1,1))

    def test_direct_estimate_cannot_include_unverified(self):
        rows=[row(i) for i in range(1,15)]
        for r in rows:
            r['verified']='false'
        out=estimate_from_samples(rows,row(999))
        self.assertFalse(out.stat_intervals)
        self.assertEqual(out.compared_samples,0)

class R9MissingFileSafety(unittest.TestCase):
    def test_missing_csv_not_silently_zero_records(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                audit_csv(Path(temp)/'missing.csv')
