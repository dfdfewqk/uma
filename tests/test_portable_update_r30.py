import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from portable_update_r30 import (
    Release, UpdateError, check_latest, deploy_verified_archive, parse_release,
    parse_checksum, parse_version, _check_zip, EXE_FILES,
)


class PortableUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.version='0.31.0'
        self.asset=f'UmaTrainerKR-Portable-v{self.version}.zip'
        self.url=f'https://github.com/dfdfewqk/uma/releases/download/v{self.version}/'
        self.meta={'tag_name':'v'+self.version,'draft':False,'prerelease':False,
                   'assets':[{'name':n,'browser_download_url':self.url+n}
                   for n in (self.asset,self.asset+'.sha256')]}
        self.release=Release(self.version,self.url+self.asset,self.url+self.asset+'.sha256','')

    def test_parse_versions(self):
        self.assertTrue(parse_version('0.31.0') > parse_version('0.30.0'))
        for version in ('v0.31.0','0.31','0.031.0','../../../x','0.31.0-rc1',''):
            with self.assertRaises(UpdateError):parse_version(version)

    def test_release_exact_assets(self):
        self.assertEqual(parse_release(self.meta).version,self.version)

    def test_same_old_release(self):
        self.assertIsNone(parse_release(self.meta,current='0.31.0'))
        self.assertIsNone(parse_release(self.meta,current='0.32.0'))

    def test_draft_or_prerelease_not_offered(self):
        for value in ('draft','prerelease'):
            m=dict(self.meta);m[value]=True
            self.assertIsNone(parse_release(m))

    def test_unsafe_asset_refused(self):
        m=json.loads(json.dumps(self.meta))
        m['assets'][0]['browser_download_url']='https://evil.invalid/update.zip'
        with self.assertRaises(UpdateError):parse_release(m)

    def test_no_sha_file_refused(self):
        m=dict(self.meta,assets=self.meta['assets'][:1])
        with self.assertRaises(UpdateError):parse_release(m)

    def test_duplicate_assets_refused(self):
        m=dict(self.meta,assets=self.meta['assets']+[self.meta['assets'][0]])
        with self.assertRaises(UpdateError):parse_release(m)

    def test_checksum_exact_name_and_hash(self):
        digest='f'*64
        self.assertEqual(parse_checksum((digest+'  '+self.asset+'\n').encode(),self.asset),digest)
        with self.assertRaises(UpdateError):parse_checksum((digest+'  other.zip').encode(),self.asset)

    def _create_zip(self,folder,*,evil=None,skip=None,version=None):
        archive=folder/'test.zip'
        with zipfile.ZipFile(archive,'w') as zf:
            for n in EXE_FILES:
                if n!=skip:zf.writestr(n,b'demo binary content for '+n.encode())
            zf.writestr('PORTABLE_VERSION.txt',(version or self.version)+'\n')
            if evil:zf.writestr(evil,'not allowed')
        return archive

    def test_zip_valid_mock(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(_check_zip(self._create_zip(Path(td)),self.version)),5)

    def test_zip_traversal_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateError):_check_zip(self._create_zip(Path(td),evil='../secret.txt'),self.version)

    def test_zip_missing_exe_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateError):_check_zip(self._create_zip(Path(td),skip='UmaTrainerKR.exe'),self.version)

    def test_zip_different_version_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateError):_check_zip(self._create_zip(Path(td),version='0.32.0'),self.version)

    def test_deploy_side_by_side_and_preserve_old(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'UmaTrainerKR_Portable_v0.30.0';old.mkdir()
            current=old/'UmaTrainerKR_Companion.exe';current.write_bytes(b'ORIGINAL STAYS')
            old_data=old/'prefs.txt';old_data.write_text('unchanged')
            archive=self._create_zip(root)
            sha=hashlib.sha256(archive.read_bytes()).hexdigest()
            updated=deploy_verified_archive(archive,self.release,current,expected_sha256=sha)
            self.assertEqual(updated.parent,root/'UmaTrainerKR_Portable_v0.31.0')
            self.assertTrue(updated.exists())
            self.assertEqual(current.read_bytes(),b'ORIGINAL STAYS')
            self.assertEqual(old_data.read_text(),'unchanged')

    def test_deploy_bad_hash_keeps_existing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'v0.30.0';old.mkdir()
            current=old/'UmaTrainerKR_Companion.exe';current.write_bytes(b'original')
            archive=self._create_zip(root)
            with self.assertRaises(UpdateError):
                deploy_verified_archive(archive,self.release,current,expected_sha256='a'*64)
            self.assertEqual(list(root.glob('UmaTrainerKR_Portable_v*')),[])
            self.assertEqual(current.read_bytes(),b'original')

    def test_deploy_existing_target_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'old';old.mkdir()
            current=old/'UmaTrainerKR_Companion.exe';current.write_bytes(b'old')
            (root/'UmaTrainerKR_Portable_v0.31.0').mkdir()
            archive=self._create_zip(root)
            with self.assertRaises(UpdateError):
                deploy_verified_archive(archive,self.release,current,expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_check_latest_mock_not_network(self):
        self.assertEqual(check_latest(lambda:self.meta).version,self.version)
        self.assertIsNone(check_latest(lambda:dict(self.meta,prerelease=True)))


if __name__=='__main__':unittest.main()
