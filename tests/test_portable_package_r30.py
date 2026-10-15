import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from scripts.build_portable_r30 import package
from portable_update_r30 import EXE_FILES, _check_zip, parse_checksum


class PortablePackageTests(unittest.TestCase):
    def test_build_archive_and_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            dist=Path(td)
            for filename in EXE_FILES:
                (dist/filename).write_bytes(b'MZ' + bytes(filename,'ascii'))
            archive, checksum = package(dist,'0.30.0')
            self.assertTrue(archive.exists())
            self.assertEqual(len(_check_zip(archive,'0.30.0')),6)
            self.assertEqual(parse_checksum(checksum.read_bytes(),archive.name),
                             hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_missing_binary_blocks_package(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                package(Path(td),'0.30.0')

    def test_manual_release_requires_explicit_opt_in(self):
        yaml_text=(Path(__file__).resolve().parents[1]/'.github/workflows/windows-exe.yml').read_text('utf8')
        self.assertIn('default: false',yaml_text)
        self.assertIn('needs: windows-package',yaml_text)
        self.assertIn('if: ${{ inputs.publish_release == true }}',yaml_text)
        self.assertIn('permissions:\n  contents: read',yaml_text)
        self.assertIn('    permissions:\n      contents: write',yaml_text)
        self.assertNotIn('  push:',yaml_text)
        self.assertNotIn('  schedule:',yaml_text)


if __name__=='__main__': unittest.main()
