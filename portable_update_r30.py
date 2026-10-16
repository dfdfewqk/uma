"""Opt-in, fail-closed GitHub Release updater for the Windows portable build.

This module does NOT update itself or silently control a game. A verified new
portable version is extracted into a *sibling* directory, leaving the running
version and the user's LOCALAPPDATA records untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

CURRENT_VERSION = '0.31.3'
REPOSITORY = 'dfdfewqk/uma'
RELEASES_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
VERSION_PATTERN = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
EXE_FILES = frozenset(('UmaTrainerKR.exe', 'UmaTrainerKR_Companion.exe',
                      'UmaTrainerKR_GameTest.exe', 'UmaTrainerKR_Preflight.exe'))
OPTIONAL_FILES = frozenset(('PORTABLE_README.txt', 'PORTABLE_VERSION.txt'))
MAX_DOWNLOAD = 600 * 1024 * 1024
MAX_UNPACKED = 1100 * 1024 * 1024
MAX_METADATA = 1024 * 1024


class UpdateError(RuntimeError):
    """Keep the current running version on any failure."""


def parse_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(value):
        raise UpdateError('올바르지 않은 버전 정보입니다.')
    return tuple(int(part) for part in value.split('.'))


@dataclass(frozen=True)
class Release:
    version: str
    archive_url: str
    checksum_url: str
    published_at: str

    @property
    def archive_name(self) -> str:
        return f'UmaTrainerKR-Portable-v{self.version}.zip'


def _asset_url(version: str, name: str) -> str:
    return f'https://github.com/{REPOSITORY}/releases/download/v{version}/{name}'


def parse_release(payload: object, current: str = CURRENT_VERSION) -> Release | None:
    """Require official, stable, newer release and exactly named assets."""
    if not isinstance(payload, dict):
        raise UpdateError('GitHub 응답 형식이 올바르지 않습니다.')
    if payload.get('draft') or payload.get('prerelease'):
        return None
    tag = payload.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise UpdateError('릴리스 버전 태그가 올바르지 않습니다.')
    version = tag[1:]
    if parse_version(version) <= parse_version(current):
        return None
    if payload.get('target_commitish') is not None and not isinstance(payload['target_commitish'], str):
        raise UpdateError('릴리스 정보가 손상되었습니다.')
    assets = payload.get('assets')
    if not isinstance(assets, list):
        raise UpdateError('다운로드 파일 목록이 없습니다.')
    archive = f'UmaTrainerKR-Portable-v{version}.zip'
    checksum = archive + '.sha256'
    matches = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get('name')
        if name in (archive, checksum):
            if name in matches:
                raise UpdateError('중복된 릴리스 파일이 있습니다.')
            url = asset.get('browser_download_url')
            if url != _asset_url(version, name):
                raise UpdateError('공식 저장소의 릴리스 주소가 아닙니다.')
            matches[name] = url
    if set(matches) != {archive, checksum}:
        raise UpdateError('포터블 ZIP 또는 SHA-256 파일이 없습니다.')
    return Release(version, matches[archive], matches[checksum], str(payload.get('published_at') or ''))


def _request(url: str, *, timeout: int = 15):
    # All input URLs are constructed or matched against exact pinned GitHub paths.
    req = Request(url, headers={
        'User-Agent': 'UmaTrainerKR-PortableUpdater/0.31',
        'Accept': 'application/vnd.github+json' if url == RELEASES_API else 'application/octet-stream',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    return urlopen(req, timeout=timeout)


def check_latest(fetch_json: Callable[[], object] | None = None, *, current: str = CURRENT_VERSION) -> Release | None:
    """Network read-only. No downloading of EXEs without the user's click."""
    if fetch_json is None:
        def fetch_json():
            with _request(RELEASES_API) as stream:
                payload = stream.read(MAX_METADATA + 1)
            if len(payload) > MAX_METADATA:
                raise UpdateError('릴리스 정보가 너무 큽니다.')
            return json.loads(payload.decode('utf-8'))
    try:
        return parse_release(fetch_json(), current)
    except HTTPError as exc:
        if exc.code == 404:
            return None  # Repository has no public Release yet; keep current version.
        raise UpdateError('GitHub 릴리스 서버에 접근할 수 없습니다.') from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise UpdateError('업데이트 서버 확인에 실패했습니다. 기존 버전을 계속 사용하세요.') from exc


def parse_checksum(payload: bytes, archive_name: str) -> str:
    if len(payload) > 512:
        raise UpdateError('SHA-256 파일 크기가 올바르지 않습니다.')
    try:
        line = payload.decode('ascii').strip()
    except UnicodeError as exc:
        raise UpdateError('SHA-256 파일을 읽을 수 없습니다.') from exc
    match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?([A-Za-z0-9_.-]+)', line)
    if not match or match.group(2) != archive_name:
        raise UpdateError('SHA-256 파일 내용이 일치하지 않습니다.')
    return match.group(1).lower()


def _read_bounded(url: str, bound: int) -> bytes:
    with _request(url) as stream:
        data = stream.read(bound + 1)
    if len(data) > bound:
        raise UpdateError('다운로드 파일 크기가 제한을 초과했습니다.')
    return data


def _download_to(url: str, target: Path) -> str:
    h = hashlib.sha256()
    total = 0
    with _request(url, timeout=30) as src, target.open('xb') as dest:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_DOWNLOAD:
                raise UpdateError('업데이트 파일 크기가 제한을 초과했습니다.')
            h.update(block)
            dest.write(block)
    return h.hexdigest()


def _check_zip(zip_path: Path, version: str) -> list[zipfile.ZipInfo]:
    """Only six fixed root-level files, no traversal/symlinks/zip bombs."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            entries = zf.infolist()
            names: set[str] = set()
            total = 0
            for ent in entries:
                name = ent.filename
                if name in names or name not in EXE_FILES | OPTIONAL_FILES:
                    raise UpdateError('압축파일에 허용되지 않은 항목이 있습니다.')
                names.add(name)
                if ent.is_dir() or ((ent.external_attr >> 16) & 0o170000) == stat.S_IFLNK:
                    raise UpdateError('압축파일에 폴더 또는 링크가 포함되어 있습니다.')
                if ent.file_size < 1 or ent.file_size > MAX_UNPACKED:
                    raise UpdateError('압축파일 크기 정보가 올바르지 않습니다.')
                total += ent.file_size
                if total > MAX_UNPACKED:
                    raise UpdateError('압축 해제 크기 제한을 초과했습니다.')
            if not EXE_FILES.issubset(names) or 'PORTABLE_VERSION.txt' not in names:
                raise UpdateError('실행파일 또는 버전 정보가 누락되었습니다.')
            if zf.read('PORTABLE_VERSION.txt').decode('ascii').strip() != version:
                raise UpdateError('ZIP의 버전이 릴리스 버전과 다릅니다.')
            if zf.testzip() is not None:
                raise UpdateError('ZIP 압축파일이 손상되었습니다.')
            return entries
    except (zipfile.BadZipFile, OSError, UnicodeError) as exc:
        raise UpdateError('ZIP 검증 중 오류가 발생했습니다.') from exc


def deploy_verified_archive(zip_path: Path, release: Release, current_exe: Path,
                            *, expected_sha256: str) -> Path:
    """Extract side-by-side, atomically rename when complete. Never touch old EXEs."""
    if not re.fullmatch('[0-9a-fA-F]{64}', expected_sha256):
        raise UpdateError('유효한 SHA-256 검증값이 없습니다.')
    h = hashlib.sha256()
    with Path(zip_path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    if h.hexdigest() != expected_sha256.lower():
        raise UpdateError('업데이트 ZIP 무결성 검증에 실패했습니다.')
    _check_zip(Path(zip_path), release.version)
    current_dir = Path(current_exe).resolve().parent
    parent = current_dir.parent
    final = parent / f'UmaTrainerKR_Portable_v{release.version}'
    if final.exists() or final.is_symlink():
        raise UpdateError('같은 버전 폴더가 이미 있습니다. 기존 폴더를 확인하세요.')
    try:
        with tempfile.TemporaryDirectory(prefix='.uma_update_', dir=parent) as staging:
            tmp = Path(staging) / 'portable'
            tmp.mkdir()
            with zipfile.ZipFile(zip_path) as zf:
                for name in sorted(EXE_FILES | OPTIONAL_FILES):
                    if name in zf.namelist():
                        with zf.open(name) as source, (tmp / name).open('xb') as destination:
                            shutil.copyfileobj(source, destination, length=1024 * 1024)
            # Atomic on the same volume; a crash cannot leave a half-updated final dir.
            tmp.rename(final)
    except OSError as exc:
        raise UpdateError('새 버전 설치 공간에 쓸 수 없습니다. 이전 버전은 유지됩니다.') from exc
    return final / 'UmaTrainerKR_Companion.exe'


def download_portable(release: Release, current_exe: Path) -> Path:
    """Runs on a worker thread after a user's explicit click."""
    with tempfile.TemporaryDirectory(prefix='uma_release_') as temporary:
        checksum = parse_checksum(_read_bounded(release.checksum_url, 512), release.archive_name)
        archive = Path(temporary) / release.archive_name
        actual = _download_to(release.archive_url, archive)
        if actual != checksum:
            raise UpdateError('다운로드 파일의 SHA-256이 일치하지 않습니다.')
        return deploy_verified_archive(archive, release, current_exe, expected_sha256=checksum)
