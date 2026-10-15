"""R29: opt-in, local-only game screenshot evidence packs.

No game input, no network, no automatic collection. User must initiate each
capture. Manually selected screen category is *not* a detected scene label.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'uma_r29_local_capture_pack_v1'
SCENES = ('훈련', '스킬', '시설', '이벤트', '기타/미확인')
MAX_CAPTURES = 12
MAX_PNG_BYTES = 18 * 1024 * 1024


class CaptureError(ValueError):
    pass


def check_capture_target(expected, current, foreground_hwnd, panel_rect):
    """Accept only an unchanged, active game window outside the companion UI."""
    from live_state_r24 import rectangles_overlap
    if expected is None or current is None:
        raise CaptureError('게임 창을 찾을 수 없습니다.')
    if expected.hwnd != current.hwnd or expected.rect != current.rect:
        raise CaptureError('캡처 도중 게임 창이나 크기가 바뀌었습니다.')
    if current.hwnd != foreground_hwnd:
        raise CaptureError('게임 창이 활성화되지 않았습니다. 게임을 클릭한 뒤 다시 시도하세요.')
    if rectangles_overlap(current.rect, panel_rect):
        raise CaptureError('도우미 창이 게임을 가리고 있습니다. 창을 분리하세요.')
    if current.width < 500 or current.height < 320 or current.width * current.height > 24_000_000:
        raise CaptureError('게임 창 크기를 확인하세요.')
    return current.rect


def new_pack(root: Path, when=None) -> Path:
    when = when or datetime.now(timezone.utc)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    folder = root / ('uma_r29_' + when.strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:10])
    folder.mkdir()
    _atomic_json(folder / 'manifest.json', {'schema': SCHEMA, 'created_at': when.isoformat(),
                                             'captures': [], 'notice': '실제 게임 인식 검증 전 · 사용자가 직접 저장한 로컬 화면'})
    return folder


def _atomic_json(path: Path, value):
    fd, tmp = tempfile.mkstemp(prefix='r29_', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def load_pack(folder: Path, check_images=True) -> dict:
    folder = Path(folder)
    path = folder / 'manifest.json'
    if not path.is_file() or path.stat().st_size > 40_000:
        raise CaptureError('캡처 목록이 없거나 손상됐습니다.')
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise CaptureError('캡처 목록을 읽지 못했습니다.') from exc
    if obj.get('schema') != SCHEMA or not isinstance(obj.get('captures'), list):
        raise CaptureError('지원하지 않는 캡처 목록입니다.')
    captures = obj['captures']
    if len(captures) > MAX_CAPTURES: raise CaptureError('캡처 수가 제한을 초과했습니다.')
    seen_names, seen_hashes = set(), set()
    for row in captures:
        if not isinstance(row, dict) or row.get('scene_label') not in SCENES or row.get('detected_scene') is not None:
            raise CaptureError('캡처 정보가 잘못됐습니다.')
        name, digest = row.get('file'), row.get('sha256')
        if not isinstance(name, str) or not name.startswith('frame_') or not name.endswith('.png') or '/' in name or '\\' in name or '..' in name:
            raise CaptureError('캡처 파일 이름이 잘못됐습니다.')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise CaptureError('캡처 체크섬이 잘못됐습니다.')
        if name in seen_names or digest in seen_hashes: raise CaptureError('중복 캡처가 포함됐습니다.')
        seen_names.add(name); seen_hashes.add(digest)
        if check_images:
            image = folder / name
            if image.is_symlink() or not image.is_file() or image.stat().st_size > MAX_PNG_BYTES:
                raise CaptureError('캡처 원본을 찾지 못했습니다.')
            if hashlib.sha256(image.read_bytes()).hexdigest() != digest:
                raise CaptureError('저장 후 이미지가 변경됐습니다.')
    return obj


def store_capture(folder: Path, image, *, scene_label: str, window_size: tuple[int, int]):
    if scene_label not in SCENES: raise CaptureError('알 수 없는 화면 종류입니다.')
    folder = Path(folder)
    manifest = load_pack(folder)
    if len(manifest['captures']) >= MAX_CAPTURES: raise CaptureError('한 묶음에 최대 12장만 저장할 수 있습니다.')
    width, height = window_size
    if not (isinstance(width, int) and isinstance(height, int) and 500 <= width and 320 <= height and width * height <= 24_000_000):
        raise CaptureError('화면 해상도가 유효하지 않습니다.')
    if image.size != (width, height): raise CaptureError('캡처 크기가 게임 창 크기와 다릅니다.')
    raw = io.BytesIO()
    image.convert('RGB').save(raw, format='PNG', optimize=True)
    data = raw.getvalue()
    if not data or len(data) > MAX_PNG_BYTES: raise CaptureError('이미지 용량이 너무 큽니다.')
    digest = hashlib.sha256(data).hexdigest()
    if any(row['sha256'] == digest for row in manifest['captures']):
        raise CaptureError('같은 화면이 이미 저장됐습니다.')
    filename = f"frame_{len(manifest['captures'])+1:02d}.png"
    target = folder / filename
    with target.open('xb') as stream: stream.write(data)
    row = {'file': filename, 'sha256': digest, 'scene_label': scene_label, 'detected_scene': None,
           'size': [width, height], 'source': 'manual_delayed_game_capture',
           'captured_at': datetime.now(timezone.utc).isoformat(), 'review_state': 'unverified'}
    manifest['captures'].append(row)
    try:
        _atomic_json(folder / 'manifest.json', manifest)
    except OSError:
        target.unlink(missing_ok=True)
        raise
    return row


def export_pack(folder: Path, destination: Path) -> Path:
    """Export only on explicit user action. Never share or upload automatically."""
    folder, destination = Path(folder), Path(destination)
    manifest = load_pack(folder)
    if destination.suffix.lower() != '.zip': raise CaptureError('ZIP 파일로만 내보낼 수 있습니다.')
    if destination.resolve().is_relative_to(folder.resolve()):
        raise CaptureError('캡처 폴더 안으로 내보낼 수 없습니다.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists(): raise CaptureError('이미 있는 파일을 덮어쓰지 않습니다.')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        z.write(folder / 'manifest.json', arcname='manifest.json')
        for row in manifest['captures']:
            z.write(folder / row['file'], arcname=row['file'])
    return destination
