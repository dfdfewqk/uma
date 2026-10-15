"""R24 verified local image reader.

Read file bytes exactly once, authenticate those bytes before decode, and never
silently use different pixels after a review manifest was opened. This is a
provenance safeguard, not evidence the screenshot is a real game frame.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_CAPTURE_BYTES = 24_000_000
MAX_PIXELS = 24_000_000
ACCEPTED_SUFFIXES = {'.png', '.jpeg', '.jpg', '.webp'}

class ChangedCaptureError(ValueError):
    pass


def read_pinned_image(path: Path, expected_sha256: str) -> Image.Image:
    path = Path(path)
    if path.is_symlink() or path.suffix.lower() not in ACCEPTED_SUFFIXES:
        raise ChangedCaptureError('지원하지 않는 캡처 경로나 파일 형식입니다.')
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ChangedCaptureError('캡처 식별자가 올바르지 않습니다.')
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_CAPTURE_BYTES:
            raise ChangedCaptureError('캡처 파일이 없거나 크기 제한을 초과했습니다.')
        with path.open('rb') as f:
            # Bounded read, including guard for file growth during reading.
            raw = f.read(MAX_CAPTURE_BYTES + 1)
        if len(raw) != size or len(raw) > MAX_CAPTURE_BYTES:
            raise ChangedCaptureError('검수 중 캡처 파일 크기가 변경되었습니다.')
    except OSError as exc:
        raise ChangedCaptureError('캡처 파일을 읽을 수 없습니다.') from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ChangedCaptureError('검수 중 캡처 내용이 바뀌었습니다. 다시 불러오세요.')
    try:
        with Image.open(BytesIO(raw)) as image:
            w, h = image.size
            if w < 200 or h < 100 or w * h > MAX_PIXELS:
                raise ChangedCaptureError('캡처 해상도가 허용 범위를 벗어납니다.')
            image.load()
            return ImageOps.exif_transpose(image).convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, ChangedCaptureError):
            raise
        raise ChangedCaptureError('캡처 파일이 올바른 이미지가 아닙니다.') from exc
