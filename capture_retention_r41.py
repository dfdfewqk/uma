"""R41 safe cleanup of *application-owned temporary screenshots only*.

No existing user photos/screenshots are claimed by this module. Unreviewed or
error examples remain untouched. Default action is dry-run.
"""
from __future__ import annotations
import hashlib,json,os,re,tempfile
from pathlib import Path

SCHEMA='uma_r41_owned_temp_capture_v1'
MARKER='.uma-r41-owned-cache.json'
FILENAME=re.compile(r'^frame-[a-zA-Z0-9_-]{1,64}\.(?:png|jpg|webp)$')
STATES=('pending','reviewed_discardable','exception_keep')


def _digest(path):
    hash=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            hash.update(block)
    return hash.hexdigest()


def _write_manifest(path,manifest):
    fd,tmp=tempfile.mkstemp(prefix='.uma_r41_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(manifest,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def initialize_cache(root):
    root=Path(root)
    if root.name!='r41_temp_captures' or root.is_symlink() or not root.is_dir():
        raise ValueError('전용 r41_temp_captures 임시 폴더만 초기화합니다.')
    marker=root/MARKER
    if marker.exists() or marker.is_symlink():
        raise ValueError('이미 초기화된 폴더입니다.')
    _write_manifest(marker,{'schema':SCHEMA,'owner':'UmaTrainerKR',
                            'entries':{}})
    return marker


def _manifest(root):
    root=Path(root)
    marker=root/MARKER
    if (root.name!='r41_temp_captures' or root.is_symlink() or not root.is_dir()
            or marker.is_symlink() or not marker.is_file()):
        raise ValueError('앱 소유가 확인된 임시 폴더만 관리합니다.')
    if marker.stat().st_size>1024*1024:
        raise ValueError('임시 이미지 목록 크기 초과')
    record=json.loads(marker.read_text(encoding='utf-8'))
    if (record.get('schema')!=SCHEMA or record.get('owner')!='UmaTrainerKR'
            or not isinstance(record.get('entries'),dict)):
        raise ValueError('앱 소유 임시 폴더 목록 오류')
    return marker,record


def register_capture(root,filename,state='pending',text_record_saved=False):
    marker,record=_manifest(root)
    if not FILENAME.fullmatch(filename) or state not in STATES:
        raise ValueError('앱 임시 이미지 파일명 또는 검수 상태 오류')
    img=Path(root)/filename
    if img.is_symlink() or not img.is_file():
        raise ValueError('프로그램 임시 이미지 파일이 없습니다.')
    if img.stat().st_size<=0 or img.stat().st_size>25*1024*1024:
        raise ValueError('임시 이미지 파일 크기 오류')
    if type(text_record_saved) is not bool:
        raise ValueError('텍스트 기록 검증 상태 오류')
    record['entries'][filename]={
        'sha256':_digest(img),'state':state,
        'text_record_saved':text_record_saved}
    _write_manifest(marker,record)


def prune_reviewed_captures(root,*,dry_run=True):
    """Only own, reviewed, text-backed, byte-unchanged images; no recursion."""
    if type(dry_run) is not bool:
        raise ValueError('dry_run 값 오류')
    marker,record=_manifest(root)
    selected=[]
    for name,meta in record['entries'].items():
        if not FILENAME.fullmatch(name) or not isinstance(meta,dict):
            raise ValueError('손상된 임시 이미지 목록')
        if meta.get('state')!='reviewed_discardable' or meta.get('text_record_saved') is not True:
            continue
        img=Path(root)/name
        if img.is_symlink() or not img.is_file():
            continue
        if _digest(img)!=meta.get('sha256'):
            continue
        selected.append(name)
    if not dry_run:
        for name in selected:
            (Path(root)/name).unlink()
            del record['entries'][name]
        if selected:
            _write_manifest(marker,record)
    return tuple(sorted(selected))
