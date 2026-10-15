import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from offline_replay_r23 import (
    SCHEMA, ReplayError, demo_manifest, load_manifest, replay,
    create_manifest, local_file, file_sha256)
from uma_core import STATS

EXAMPLES = Path(__file__).resolve().parent.parent/'examples'

class TestR23OfflineReplay(unittest.TestCase):
    def sample(self):
        return json.loads(demo_manifest().read_text(encoding='utf8'))

    def test_demo_integrity(self):
        doc=load_manifest(demo_manifest())
        self.assertEqual(len(doc['captures']),5)
        self.assertEqual([x[0] for x in doc['captures']],list(STATS))

    def test_no_ocr_never_confirms(self):
        report=replay(demo_manifest(),use_ocr=False)
        self.assertEqual(report.verified_turns,0)
        self.assertEqual(report.eligible_ml_labels,0)
        self.assertEqual(report.auto_clicks,0)
        self.assertEqual(len(report.findings),5)
        self.assertIn('OCR',report.status)
        self.assertEqual(set(report.public_json()),
                         {'scenario','source_type','turn','status','findings','warnings',
                          'verified_turns','eligible_ml_labels','auto_clicks'})

    def test_invalid_source_type(self):
        with tempfile.TemporaryDirectory() as temp:
            obj=self.sample();obj['source_type']='verified_training'
            fp=Path(temp)/'manifest.json';fp.write_text(json.dumps(obj))
            with self.assertRaises(ReplayError):load_manifest(fp)

    def test_wrong_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            obj=self.sample();obj['schema']='r2'
            fp=Path(temp)/'manifest.json';fp.write_text(json.dumps(obj))
            with self.assertRaises(ReplayError):load_manifest(fp)

    def test_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            for name in ('../secret.png','/etc/passwd','sub/a.png','..',r'C:\\foo.png'):
                with self.subTest(name=name),self.assertRaises(ReplayError):local_file(base,name)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);target=base/'image.png';target.write_bytes(b'x')
            link=base/'link.png'
            try:link.symlink_to(target)
            except (OSError,NotImplementedError):self.skipTest('Symlinks unavailable')
            with self.assertRaises(ReplayError):local_file(base,link.name)

    def test_tampered_image_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            (base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            (base/'image.png').write_bytes((EXAMPLES/'r22_mock_1.png').read_bytes())
            manifest=create_manifest(base,source_type='local_unverified',turn='주니어',
                                     roi_profile='roi.json',captures={'스피드':'image.png'})
            (base/'image.png').write_bytes(b'not-an-image')
            with self.assertRaisesRegex(ReplayError,'달라졌'):load_manifest(manifest)

    def test_duplicate_capture_hash_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            (base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            data=(EXAMPLES/'r22_mock_1.png').read_bytes()
            (base/'one.png').write_bytes(data);(base/'two.png').write_bytes(data)
            with self.assertRaisesRegex(ReplayError,'같은 이미지'):
                create_manifest(base,source_type='local_unverified',turn='주니어',
                    roi_profile='roi.json',captures={'스피드':'one.png','스태미나':'two.png'})

    def test_duplicate_choice_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            for i in (1,2):(base/f'{i}.png').write_bytes((EXAMPLES/f'r22_mock_{i}.png').read_bytes())
            obj=self.sample()
            obj['roi_profile']='roi.json'
            obj['captures']=[{'choice':'스피드','image':f'{i}.png','sha256':file_sha256(base/f'{i}.png')} for i in (1,2)]
            fp=base/'doc.json';fp.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ReplayError,'중복'):load_manifest(fp)

    def test_manifest_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            (base/'1.png').write_bytes((EXAMPLES/'r22_mock_1.png').read_bytes())
            def make():return create_manifest(base,source_type='local_unverified',turn='주니어',
                                   roi_profile='roi.json',captures={'스피드':'1.png'})
            make()
            with self.assertRaisesRegex(ReplayError,'덮어쓰지'):make()

    def test_incomplete_captures_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            (base/'1.png').write_bytes((EXAMPLES/'r22_mock_1.png').read_bytes())
            doc=create_manifest(base,source_type='local_unverified',turn='주니어',
                                roi_profile='roi.json',captures={'스피드':'1.png'})
            result=replay(doc,use_ocr=False)
            self.assertTrue(any('훈련 5종' in w for w in result.warnings))
            self.assertEqual(result.eligible_ml_labels,0)

    def test_roi_ratio_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'roi.json').write_bytes((EXAMPLES/'r22_mock_roi.json').read_bytes())
            im=Image.new('RGB',(900,1300));im.save(base/'1.png')
            doc=create_manifest(base,source_type='local_unverified',turn='주니어',
                                roi_profile='roi.json',captures={'스피드':'1.png'})
            result=replay(doc,use_ocr=False)
            self.assertIn('비율',result.findings[0].warnings[0])

    def test_invalid_scenario(self):
        with tempfile.TemporaryDirectory() as temp:
            obj=self.sample();obj['scenario']='new_unknown'
            fp=Path(temp)/'manifest.json';fp.write_text(json.dumps(obj))
            with self.assertRaises(ReplayError):load_manifest(fp)

if __name__=='__main__':unittest.main()
