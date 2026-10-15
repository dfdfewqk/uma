"""R23 read-only offline capture replay and provenance audit.

Never infer a label from a video frame, never send files to a network,
never auto-accept OCR as verified training data, and never click a game.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from live_training_r22 import (CaptureError, NumericProfile, SCREEN_FIELDS,
                               load_profile, ocr_candidates, screenshot_digest)
from screen_r4 import tesseract_executable
from capture_integrity_r24 import read_pinned_image, ChangedCaptureError
from training_r5 import TRAINING_CHOICES
from uma_core import STATS

SCHEMA = 'uma_training_replay_r23_v1'
MAX_MANIFEST_BYTES = 30000
MAX_CAPTURE_BYTES = 24_000_000

class ReplayError(ValueError):
    pass


def local_file(root: Path, filename: str) -> Path:
    """Disallow absolute paths, nested paths, traversal, symlinks and off-folder inputs."""
    if not isinstance(filename, str) or not filename or len(filename) > 180:
        raise ReplayError('파일명 형식이 올바르지 않습니다.')
    if filename != Path(filename).name or filename in ('.', '..') or '\\' in filename or '/' in filename:
        raise ReplayError('매니페스트의 파일은 같은 폴더의 파일명만 허용합니다.')
    base = root.resolve(strict=True)
    entry = base / filename
    if entry.is_symlink() or not entry.is_file() or entry.resolve() != base / filename:
        raise ReplayError('파일이 없거나 외부 파일을 참조하고 있습니다.')
    return entry


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ReplayError('매니페스트 파일이 없거나 크기가 잘못되었습니다.')
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ReplayError('매니페스트 JSON을 읽을 수 없습니다.') from exc
    if not isinstance(obj, dict) or obj.get('schema') != SCHEMA:
        raise ReplayError('R23 매니페스트 형식이 아닙니다.')
    if obj.get('scenario') != 'island_post_patch_v1':
        raise ReplayError('현재 R23은 무인도 설정의 이미지 재생만 지원합니다.')
    if obj.get('source_type') not in ('synthetic_test', 'local_unverified'):
        raise ReplayError('출처 유형을 선택해야 합니다.')
    if not isinstance(obj.get('turn'),str) or not 1 <= len(obj['turn'].strip()) <= 100:
        raise ReplayError('육성 턴 이름이 누락됐습니다.')
    root = path.parent
    roi_path = local_file(root, obj.get('roi_profile'))
    roi_digest = file_sha256(roi_path)
    if obj.get('roi_sha256') is not None:
        if obj['roi_sha256'] != roi_digest:
            raise ReplayError('검수 중 OCR 영역 설정이 바뀌었습니다. 다시 목록을 만드세요.')
    profile = load_profile(roi_path)
    if not isinstance(profile, NumericProfile):
        raise ReplayError('OCR 영역 설정을 찾을 수 없습니다.')
    captures = obj.get('captures')
    if not isinstance(captures, list) or not 1 <= len(captures) <= len(TRAINING_CHOICES):
        raise ReplayError('캡처는 1~6개만 허용합니다.')
    seen_choices, seen_hashes, checked = set(), set(), []
    for row in captures:
        if not isinstance(row, dict) or row.get('choice') not in TRAINING_CHOICES:
            raise ReplayError('훈련 이름이 잘못되었습니다.')
        if row['choice'] in seen_choices:
            raise ReplayError('같은 훈련 이름이 중복되었습니다.')
        seen_choices.add(row['choice'])
        fp = local_file(root, row.get('image'))
        if fp.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or fp.stat().st_size > MAX_CAPTURE_BYTES:
            raise ReplayError('이미지 형식/크기 제한을 초과했습니다.')
        expected = row.get('sha256')
        if not isinstance(expected,str) or len(expected) != 64 or not all(c in '0123456789abcdef' for c in expected):
            raise ReplayError('이미지 SHA-256을 정확히 등록해야 합니다.')
        if file_sha256(fp) != expected:
            raise ReplayError(f'{row["choice"]}: 이미지가 원본과 달라졌습니다.')
        if expected in seen_hashes:
            raise ReplayError('같은 이미지가 서로 다른 훈련에 등록됐습니다.')
        seen_hashes.add(expected)
        checked.append((row['choice'],fp,expected))
    return {'metadata':{'schema':SCHEMA,'scenario':obj['scenario'],
                         'source_type':obj['source_type'],'turn':obj['turn'].strip()},
            'profile':profile,'captures':checked,
            'roi_path':roi_path,'roi_sha256':roi_digest,
            'manifest_path':path,'manifest_sha256':file_sha256(path)}


@dataclass
class ReplayFinding:
    choice: str
    sha256: str
    candidates: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReplayReport:
    scenario: str
    source_type: str
    turn: str
    status: str
    findings: list[ReplayFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verified_turns: int = 0
    eligible_ml_labels: int = 0
    auto_clicks: int = 0

    def public_json(self) -> dict:
        # No raw images, paths, Windows titles or automatic training labels.
        return asdict(self)


def replay(path: Path, *, use_ocr: bool = True, binary: str = '') -> ReplayReport:
    doc = load_manifest(path)
    meta = doc['metadata']
    report=ReplayReport(meta['scenario'],meta['source_type'],meta['turn'],'검수 필요')
    if meta['source_type'] == 'synthetic_test':
        report.warnings.append('합성 테스트 화면: 실제 게임 인식 정확도 및 ML 학습 근거가 아닙니다.')
    executable = tesseract_executable(binary) if use_ocr else None
    if not executable:
        report.warnings.append('OCR 실행 불가/사용 안 함: 이미지 무결성만 검사했습니다.')
    for choice,fp,digest in doc['captures']:
        # Fail closed if configuration or manifest changed after initial validation.
        if file_sha256(doc['roi_path']) != doc['roi_sha256'] or file_sha256(doc['manifest_path']) != doc['manifest_sha256']:
            raise ReplayError('검수 중 목록 또는 OCR 영역 설정이 바뀌었습니다. 재검수하세요.')
        try:
            img = read_pinned_image(fp, digest)
            finding=ReplayFinding(choice,digest)
            if not doc['profile'].matches(img):
                finding.warnings.append('이미지 비율이 등록된 ROI와 다릅니다.')
                finding.missing.extend(SCREEN_FIELDS)
            elif executable:
                findings=ocr_candidates(img,doc['profile'],executable)
                finding.candidates=findings
                finding.missing=[name for name in SCREEN_FIELDS if findings.get(name,{}).get('candidate') is None]
            else:
                finding.missing.extend(SCREEN_FIELDS)
            finding.warnings.append('OCR 후보는 검수 전이며 추천 또는 정답으로 사용하지 않습니다.')
            report.findings.append(finding)
        except (OSError, ValueError, CaptureError, ChangedCaptureError) as exc:
            finding=ReplayFinding(choice,digest,missing=list(SCREEN_FIELDS),warnings=[str(exc)])
            report.findings.append(finding)
    needed=set(STATS)
    present={f.choice for f in report.findings}
    if present != needed and present != needed|{'섬 트레이닝'}:
        report.warnings.append('일반 훈련 5종이 전부 수집되지 않았습니다.')
    if any(f.missing for f in report.findings):
        report.status='OCR 후보 누락 · 수동 검수 필요'
    elif executable:
        report.status='OCR 후보 수집 · 모두 수동 검수 필요'
    return report


def create_manifest(folder: Path, *, source_type: str, turn: str,
                    captures: dict[str, str], roi_profile: str) -> Path:
    """Create local manifest, never claim that images are authentic game data."""
    folder=Path(folder).resolve()
    if source_type not in ('synthetic_test','local_unverified'):
        raise ReplayError('출처 유형이 잘못되었습니다.')
    if not captures or len(captures)>len(TRAINING_CHOICES):
        raise ReplayError('훈련 이미지가 없습니다.')
    local_file(folder,roi_profile)
    rows=[]
    for choice,name in captures.items():
        if choice not in TRAINING_CHOICES:raise ReplayError('지원하지 않는 훈련입니다.')
        p=local_file(folder,name)
        rows.append({'choice':choice,'image':name,'sha256':file_sha256(p)})
    obj={'schema':SCHEMA,'scenario':'island_post_patch_v1',
         'source_type':source_type,'turn':turn,'roi_profile':roi_profile,
         'roi_sha256':file_sha256(local_file(folder,roi_profile)), 'captures':rows}
    path=folder/'R23_검수목록.json'
    if path.exists(): raise ReplayError('이미 검수목록 파일이 있습니다. 덮어쓰지 않습니다.')
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
    load_manifest(path)
    return path


def demo_manifest() -> Path:
    """Self-contained packaged demo assets, never automatic external downloads."""
    import sys
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    return root/'examples'/'r23_demo_manifest.json'


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Read-only R23 replay audit')
    parser.add_argument('manifest',nargs='?',default=str(demo_manifest()))
    parser.add_argument('--no-ocr',action='store_true')
    args=parser.parse_args()
    print(json.dumps(replay(Path(args.manifest),use_ocr=not args.no_ocr).public_json(),ensure_ascii=False,indent=2))
