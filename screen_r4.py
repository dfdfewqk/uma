"""R4: manual screenshot/ROI inspection plus optional, local Tesseract numeric OCR.

Never calls the game process, network, or input automation. OCR output is untrusted
and MUST be manually confirmed in UI before populating a turn-state field.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FIELD_LIMITS = {
    '스피드': (0, 5000), '스태미나': (0, 5000), '파워': (0, 5000),
    '근성': (0, 5000), '지능': (0, 5000), '체력': (0, 100),
    '스킬 Pt': (0, 20000), '섬 티켓': (0, 99), '발전 Pt': (0, 30000),
}
FIELDS = tuple(FIELD_LIMITS)
PROFILE_SCHEMA_VERSION = 1
MAX_IMAGE_PIXELS = 24_000_000
MAX_IMAGE_BYTES = 24 * 1024 * 1024


class ScreenError(ValueError):
    pass


def user_dir() -> Path:
    base = Path(os.getenv('LOCALAPPDATA') or (Path.home() / '.uma_trainer_kr'))
    out = base / 'UmaTrainerKR' if os.getenv('LOCALAPPDATA') else base
    out.mkdir(parents=True, exist_ok=True)
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def load_image(path: Path):
    """Validate real image content and avoid decompression bombs and huge files."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise ScreenError('이미지를 읽으려면 Pillow가 필요합니다. 배포 EXE에 포함하도록 설정했습니다.') from exc
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ScreenError('PNG/JPG/WebP 파일만 열 수 있습니다.')
    if not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > MAX_IMAGE_BYTES:
        raise ScreenError('이미지 파일이 없거나 용량이 제한(24MB)을 초과했습니다.')
    try:
        with Image.open(path) as source:
            w, h = source.size
            if w*h > MAX_IMAGE_PIXELS or w < 200 or h < 100:
                raise ScreenError('이미지 해상도가 지원 범위(최대 2,400만 픽셀)를 벗어납니다.')
            source.load()
            result = ImageOps.exif_transpose(source).convert('RGB')
        return result
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
        raise ScreenError('정상적인 이미지로 읽을 수 없습니다.') from exc


@dataclass(frozen=True)
class Region:
    field: str
    x1: float
    y1: float
    x2: float
    y2: float

    def validate(self) -> None:
        if self.field not in FIELD_LIMITS:
            raise ScreenError(f'지원하지 않는 화면 영역: {self.field}')
        values = (self.x1, self.y1, self.x2, self.y2)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ScreenError('영역 좌표는 유한한 숫자여야 합니다.')
        if not (0 <= self.x1 < self.x2 <= 1 and 0 <= self.y1 < self.y2 <= 1):
            raise ScreenError('선택 영역은 이미지 범위(0~1) 안이어야 합니다.')
        if self.x2-self.x1 < 0.003 or self.y2-self.y1 < 0.003:
            raise ScreenError('영역이 너무 작습니다. 숫자가 보이는 범위를 다시 지정하세요.')

    def pixel_box(self, width: int, height: int) -> tuple[int,int,int,int]:
        self.validate()
        l, t = int(self.x1 * width), int(self.y1 * height)
        r, b = math.ceil(self.x2 * width), math.ceil(self.y2 * height)
        return max(0,l), max(0,t), min(width,r), min(height,b)


@dataclass
class ScreenProfile:
    name: str
    scenario: str
    aspect_ratio: float
    regions: dict[str, Region]
    version: int = PROFILE_SCHEMA_VERSION

    def validate(self):
        if not self.name or len(self.name) > 100:
            raise ScreenError('프로필 이름은 1~100자여야 합니다.')
        if self.scenario not in ('island_post_patch_v1',):
            raise ScreenError('현재 R4는 무인도 시나리오만 지원합니다.')
        if not isinstance(self.aspect_ratio, (int, float)) or not (0.2 <= self.aspect_ratio <= 6):
            raise ScreenError('화면 비율이 올바르지 않습니다.')
        if self.version != PROFILE_SCHEMA_VERSION:
            raise ScreenError('지원하지 않는 ROI 설정 버전입니다.')
        for key, value in self.regions.items():
            if key != value.field:
                raise ScreenError('영역 이름이 일치하지 않습니다.')
            value.validate()

    def matches_image(self, image) -> bool:
        return abs(image.width / image.height - self.aspect_ratio) / self.aspect_ratio <= .06


def save_profile(profile: ScreenProfile, path: Path):
    profile.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = { 'version': profile.version, 'name': profile.name,
            'scenario': profile.scenario, 'aspect_ratio': profile.aspect_ratio,
            'regions': {key: asdict(r) for key, r in profile.regions.items()} }
    # Atomic replace avoids losing existing calibration when a write is interrupted.
    fd, temp = tempfile.mkstemp(prefix='roi_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_profile(path: Path) -> ScreenProfile:
    path=Path(path)
    if not path.is_file() or path.stat().st_size > 100_000:
        raise ScreenError('저장된 ROI 프로필이 없거나 너무 큽니다.')
    try:
        doc=json.loads(path.read_text(encoding='utf-8'))
        regs={key:Region(**value) for key,value in doc['regions'].items()}
        p=ScreenProfile(name=doc['name'],scenario=doc['scenario'],
                        aspect_ratio=doc['aspect_ratio'], regions=regs,version=doc['version'])
        p.validate()
        return p
    except (KeyError, TypeError, ValueError) as exc:
        raise ScreenError('ROI 설정 파일 형식이 잘못되었습니다.') from exc


def profile_path() -> Path:
    return user_dir() / 'screen_regions_r4.json'


def parse_numeric(raw: str, field: str) -> Optional[int]:
    """Refuse guessed digits, signs, decimals or concatenated values.

    '45/100' is accepted only for the energy display; never repair O->0 etc.
    """
    if field not in FIELD_LIMITS:
        raise ScreenError('지원하지 않는 인식 필드입니다.')
    s=str(raw).strip().replace(' ', '')
    if field == '체력' and re.fullmatch(r'\d{1,3}/100', s):
        s=s.split('/')[0]
    if not re.fullmatch(r'\d{1,3}(?:,\d{3})*|\d{1,5}', s):
        return None
    val=int(s.replace(',',''))
    lo,hi=FIELD_LIMITS[field]
    return val if lo<=val<=hi else None


@dataclass
class ReadResult:
    field: str
    raw_text: str
    value: Optional[int]
    confidence: Optional[float]
    status: str
    source_hash: str


def tesseract_executable(custom: str = '') -> Optional[str]:
    if custom:
        p=Path(custom)
        return str(p) if p.is_file() and p.name.lower() in ('tesseract.exe','tesseract') else None
    # The v0.31.8 game-test portable has OCR packaged inside PyInstaller.
    # Look there first so the player never needs to locate an OCR installer.
    if getattr(sys,'frozen',False) and hasattr(sys,'_MEIPASS'):
        bundled=Path(sys._MEIPASS)/'ocr'/'tesseract.exe'
        if bundled.is_file() and (bundled.parent/'tessdata'/'eng.traineddata').is_file():
            return str(bundled)
    direct=shutil.which('tesseract')
    if direct:
        return direct
    # Optional user-provided portable OCR installation adjacent to packaged EXE.
    # We do not ship third-party binaries in the source bundle.
    if sys.platform == 'win32':
        base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        portable = base / 'ocr' / 'tesseract.exe'
        if portable.is_file():
            return str(portable)
    if sys.platform=='win32':
        for prefix in (os.getenv('ProgramFiles',''), os.getenv('ProgramFiles(x86)','')):
            if not prefix:
                continue
            exe=Path(prefix)/'Tesseract-OCR'/'tesseract.exe'
            if exe.is_file():
                return str(exe)
    return None


def _recognize_one(image, binary: str, timeout=12) -> tuple[str,Optional[float]]:
    """Invoke local Tesseract with fixed flags; no shell and no network."""
    from PIL import ImageOps, ImageEnhance, ImageFilter
    cropped = ImageOps.grayscale(image)
    scale=min(4, max(2, int(90 / max(1, cropped.height))))
    cropped=cropped.resize((cropped.width*scale,cropped.height*scale))
    cropped=ImageOps.autocontrast(cropped)
    # Let OCR engine see monochrome-ish but preserve anti-aliasing for small UI text.
    cropped=ImageEnhance.Contrast(cropped).enhance(1.45)
    with tempfile.TemporaryDirectory(prefix='uma_ocr_') as td:
        path=Path(td)/'digits.png'
        cropped.save(path)
        args=[binary,str(path),'stdout','--psm','7','-l','eng',
              '-c','tessedit_char_whitelist=0123456789,/', 'tsv']
        try:
            done=subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                encoding='utf-8', errors='replace', shell=False)
        except subprocess.TimeoutExpired as exc:
            raise ScreenError('OCR 엔진 시간이 초과됐습니다.') from exc
        except OSError as exc:
            raise ScreenError('Tesseract 실행 실패. 경로 또는 설치 상태를 확인하세요.') from exc
        if done.returncode:
            raise ScreenError('OCR 엔진 실행 오류. 숫자 영역이나 Tesseract 설치를 확인하세요.')
    rows=list(csv.DictReader(io.StringIO(done.stdout),delimiter='\t'))
    words=[]
    confs=[]
    for r in rows:
        txt=str(r.get('text','')).strip()
        if not txt:
            continue
        try:
            conf=float(r.get('conf','-1'))
        except (TypeError,ValueError):
            conf=-1
        if conf>=0:
            words.append(txt)
            confs.append(conf)
    return ''.join(words).strip(), (round(min(confs),1) if confs else None)


def read_regions(image_path: Path, profile: ScreenProfile, executable: str = '', min_confidence=65) -> list[ReadResult]:
    image=load_image(image_path)
    profile.validate()
    if not profile.matches_image(image):
        raise ScreenError('이미지 화면 비율이 저장된 ROI 프로필과 다릅니다. 영역을 다시 지정하세요.')
    binary=tesseract_executable(executable)
    if not binary:
        raise ScreenError('OCR 엔진(Tesseract)이 없습니다. 화면 영역 지정 및 수동 검수는 사용할 수 있습니다.\nWindows에서는 Tesseract를 별도로 설치하고 경로를 지정해야 합니다.')
    digest=sha256_file(image_path)
    results=[]
    for field in FIELDS:
        region=profile.regions.get(field)
        if region is None:
            results.append(ReadResult(field,'',None,None,'영역 미지정',digest))
            continue
        text,conf=_recognize_one(image.crop(region.pixel_box(image.width,image.height)),binary)
        number=parse_numeric(text,field)
        status=('후보 · 사용자 확인 필요' if number is not None and conf is not None and conf >= min_confidence
                else '인식 불확실 · 수동 확인 필요')
        results.append(ReadResult(field,text,number,conf,status,digest))
    return results


def save_review(image_path: Path, profile: ScreenProfile, candidates: list[ReadResult],
                confirmed: dict[str, int], dest: Path, manual: bool = False):
    """Persist reviewed values separately from game run data; never auto-confirm.

    The caller must explicitly decide confirmed values; no ML label is fabricated.
    """
    image=load_image(image_path)
    profile.validate()
    if not profile.matches_image(image):
        raise ScreenError('이미지 비율과 프로필이 다릅니다.')
    validated={}
    for field,value in confirmed.items():
        if field not in profile.regions or field not in FIELD_LIMITS or type(value) is not int:
            raise ScreenError('검수 항목이 영역 또는 필드 정의와 맞지 않습니다.')
        lo,hi=FIELD_LIMITS[field]
        if not lo<=value<=hi:
            raise ScreenError(f'{field} 검수 값이 허용 범위를 벗어났습니다.')
        validated[field]=value
    document={
        'format':'uma_screen_review_r4', 'version':1,
        'source':'local_screenshot_user_reviewed', 'not_ml_training_label':True,
        'reviewed_at':datetime.now(timezone.utc).isoformat(),
        'source_sha256':sha256_file(image_path), 'image_size':[image.width,image.height],
        'scenario':profile.scenario, 'profile_name':profile.name,
        'regions':{field:asdict(reg) for field,reg in profile.regions.items()},
        'raw_ocr':[asdict(r) for r in candidates],
        'confirmed_values':validated,
        'verification':'user_manually_confirmed' if validated else 'unconfirmed',
        'ocr_engine':('manual_only' if manual else 'tesseract_optional')
    }
    dest=Path(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    return document
