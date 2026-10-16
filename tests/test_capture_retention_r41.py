"""R41 temporary image retention: never touch original or unreviewed images."""
from pathlib import Path
import tempfile
import unittest
from capture_retention_r41 import (
    initialize_cache,register_capture,prune_reviewed_captures)

class SafeRetentionTests(unittest.TestCase):
    def setup_cache(self,tmp):
        root=Path(tmp)/'r41_temp_captures'
        root.mkdir()
        initialize_cache(root)
        return root

    def test_dry_run_and_verified_text_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.setup_cache(tmp)
            for name in ('frame-reviewed.png','frame-pending.png','frame-exception.png'):
                (root/name).write_bytes(b'synthetic-image-placeholder-not-for-real-OCR')
            register_capture(root,'frame-reviewed.png','reviewed_discardable',True)
            register_capture(root,'frame-pending.png','pending',True)
            register_capture(root,'frame-exception.png','exception_keep',True)
            self.assertEqual(prune_reviewed_captures(root),('frame-reviewed.png',))
            self.assertTrue((root/'frame-reviewed.png').exists())
            self.assertEqual(prune_reviewed_captures(root,dry_run=False),
                             ('frame-reviewed.png',))
            self.assertFalse((root/'frame-reviewed.png').exists())
            self.assertTrue((root/'frame-pending.png').exists())
            self.assertTrue((root/'frame-exception.png').exists())

    def test_changed_file_and_no_text_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.setup_cache(tmp)
            altered=root/'frame-altered.webp'
            no_text=root/'frame-no-text.png'
            altered.write_bytes(b'old-image')
            no_text.write_bytes(b'candidate')
            register_capture(root,altered.name,'reviewed_discardable',True)
            register_capture(root,no_text.name,'reviewed_discardable',False)
            altered.write_bytes(b'new-image')
            self.assertFalse(prune_reviewed_captures(root,dry_run=False))
            self.assertTrue(altered.exists())
            self.assertTrue(no_text.exists())

    def test_never_initialize_or_prune_user_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):initialize_cache(tmp)
            with self.assertRaises(ValueError):prune_reviewed_captures(tmp)
            root=self.setup_cache(tmp)
            with self.assertRaises(ValueError):
                register_capture(root,'../../photo.png','reviewed_discardable',True)

if __name__=='__main__':
    unittest.main()
