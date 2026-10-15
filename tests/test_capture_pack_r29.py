import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from companion_core import GameWindow
from capture_pack_r29 import (CaptureError, SCHEMA, check_capture_target, new_pack,
                              store_capture, load_pack, export_pack)


class CapturePackTests(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory(); self.addCleanup(self.ctx.cleanup)
        self.root = Path(self.ctx.name)
        self.pack = new_pack(self.root)
        self.game = GameWindow(121, 'Umamusume', (20, 30, 820, 630))
        self.panel = (830, 30, 1180, 630)

    def test_target_requires_foreground_and_same_window(self):
        self.assertEqual(check_capture_target(self.game, self.game, 121, self.panel), self.game.rect)
        with self.assertRaises(CaptureError): check_capture_target(self.game, self.game, 222, self.panel)
        changed = GameWindow(121, 'Umamusume', (20, 30, 920, 630))
        with self.assertRaises(CaptureError): check_capture_target(self.game, changed, 121, self.panel)

    def test_target_rejects_companion_overlap(self):
        with self.assertRaises(CaptureError): check_capture_target(self.game, self.game, 121, (700, 20, 900, 400))

    def test_pack_roundtrip_and_export(self):
        row = store_capture(self.pack, Image.new('RGB', (800, 600), 'white'), scene_label='훈련', window_size=(800, 600))
        self.assertEqual(len(load_pack(self.pack)['captures']), 1)
        self.assertEqual(row['source'], 'manual_delayed_game_capture')
        path = export_pack(self.pack, self.root / 'share.zip')
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()), ['frame_01.png', 'manifest.json'])
        with self.assertRaises(CaptureError): export_pack(self.pack, path)

    def test_pack_deduplicates_frames(self):
        image = Image.new('RGB', (800, 600), 'white')
        store_capture(self.pack, image, scene_label='스킬', window_size=(800,600))
        with self.assertRaises(CaptureError): store_capture(self.pack, image, scene_label='훈련', window_size=(800,600))

    def test_wrong_size_and_label(self):
        im = Image.new('RGB', (800,600), 'white')
        with self.assertRaises(CaptureError): store_capture(self.pack, im, scene_label='훈련', window_size=(801,600))
        with self.assertRaises(CaptureError): store_capture(self.pack, im, scene_label='하우징', window_size=(800,600))

    def test_modified_file_invalidates_pack(self):
        row = store_capture(self.pack, Image.new('RGB', (800,600)), scene_label='시설', window_size=(800,600))
        (self.pack / row['file']).write_bytes(b'not an image')
        with self.assertRaises(CaptureError): load_pack(self.pack)

    def test_rejects_parent_path(self):
        p = self.pack / 'manifest.json'; obj = json.loads(p.read_text())
        obj['captures'] = [{'scene_label':'훈련','detected_scene':None,'file':'../frame_01.png','sha256':'a'*64}]
        p.write_text(json.dumps(obj))
        with self.assertRaises(CaptureError): load_pack(self.pack)

    def test_starts_empty_and_unverified(self):
        obj=load_pack(self.pack)
        self.assertEqual(obj['schema'],SCHEMA)
        self.assertEqual(obj['captures'],[])


if __name__ == '__main__': unittest.main()
