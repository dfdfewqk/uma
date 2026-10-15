"""R10: local, provenance-gated review worklist and R2 -> R9 evidence bridge.

Public video URLs provide navigation only. No video downloads or automatic labels.
'Human chose X' never means X was optimal.  No synthetic R9 observations.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from research.review_tools.annotation_core import (read_sources, read_annotations,
    check_media, AnnotationError)
from calibration_r9 import FIELDS as R9_FIELDS, STATS as FACILITY_STATS, FACILITIES, validate_row as validate_r9

BASE = Path(__file__).resolve().parent
RESEARCH = BASE / 'research'
SOURCES_CSV = RESEARCH / 'jp_post_patch_2025' / 'sources.csv'
CHAPTERS_CSV = RESEARCH / 'jp_post_patch_2025' / 'video_chapters.csv'
PRIORITIES_CSV = RESEARCH / 'video_reviews' / 'review_queue.csv'
ANNOTATIONS_CSV = RESEARCH / 'video_reviews' / 'verified_turns.csv'
# A frozen application must never write into its onefile extraction directory.
if getattr(__import__('sys'), 'frozen', False):
    USER_DIR = Path.home() / 'Documents' / 'UmaTrainerKR_Research' / 'r10'
else:
    USER_DIR = BASE / 'research' / 'r10_local'
PROGRESS_JSON = USER_DIR / 'review_progress.json'

STAT_KEYS = ('speed', 'stamina', 'power', 'guts', 'wisdom')
GAIN_KEYS = ('g_speed', 'g_stamina', 'g_power', 'g_guts', 'g_wisdom', 'skill_points')
PURPOSE_MAP = {'champ_main': '챔피언스 미팅', 'loh_main': '리그 오브 히어로즈'}
STATES = ('pending', 'in_review', 'blocked', 'verified')


def _csv_rows(path: Path) -> list[dict]:
    with Path(path).open('r', encoding='utf-8-sig', newline='') as fp:
        return list(csv.DictReader(fp))


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.r10-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_csv(path: Path, fields: tuple | list, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.r10-', suffix='.csv', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows([{k: r.get(k, '') for k in fields} for r in rows])
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_worklist(sources_csv=SOURCES_CSV, chapters_csv=CHAPTERS_CSV,
                   priorities_csv=PRIORITIES_CSV):
    sources = read_sources(sources_csv)
    chapters = _csv_rows(chapters_csv)
    priorities = {r['source_id']: r for r in _csv_rows(priorities_csv)}
    by_source = {}
    for c in chapters:
        by_source.setdefault(c['source_id'], []).append(c)
    worklist = []
    for sid, s in sources.items():
        if not s.get('source_kind', '').startswith('video_'):
            continue
        # Source metadata cannot establish a real post-patch frame. Flag, never infer.
        published = s.get('published_date', '')
        if published and published < '2025-07-01':
            continue
        p = priorities.get(sid, {})
        raw_prio = p.get('priority', '8')
        priority = int(raw_prio) if str(raw_prio).isdigit() else 8
        times = by_source.get(sid) or [None]
        for c in times:
            seconds = int(c['start_second']) if c else -1
            tid = f'{sid}-C{seconds:06d}' if c else f'{sid}-UNSCOPED'
            scope = s.get('scope', '')
            allowed = ('champ_main' if scope == 'champ' else
                       'loh_main' if scope == 'loh' else 'not_assumed')
            url = s['url'] + (f'&t={seconds}s' if seconds >= 0 and 'youtube.com/watch?' in s['url'] else '')
            worklist.append({
                'task_id': tid, 'source_id': sid, 'source_title': s['title_ko'],
                'source_url': url, 'published_date': published,
                'scope': scope, 'suggested_purpose': allowed,
                'review_topic': c['topic_ko'] if c else p.get('review_target', '실제 육성 턴 구간 직접 확인'),
                'video_seconds': seconds, 'priority': priority,
                'metadata_only': p.get('allowed_label') == 'metadata_only',
                'source_checked_depth': s.get('checked_depth', ''),
                'status': 'pending', 'annotation_id': '',
                'note': '원본 프레임 확인 전; 실제 육성 목적도 영상에서 확인 필요',
            })
    return sorted(worklist, key=lambda r: (r['priority'], r['source_id'], r['video_seconds']))


def read_progress(path=PROGRESS_JSON):
    path = Path(path)
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict) or obj.get('version') != 1 or not isinstance(obj.get('tasks'), dict):
        raise ValueError('R10 진행 상황 파일 형식이 맞지 않습니다.')
    return obj['tasks']


def _valid_evidence(annotation: Mapping) -> tuple[bool, str]:
    """A 'complete' flag alone is not evidence if the files changed or went missing."""
    if not annotation or annotation.get('review_grade') != 'complete':
        return False, '선택 전후가 검수된 complete 기록이 필요합니다.'
    if annotation.get('patch_status') != 'post_2025_06_30_confirmed' or annotation.get('server') != 'JP':
        return False, '일본 수정 후 근거가 확인되지 않았습니다.'
    if annotation.get('observed_choice') != 'true' or annotation.get('observed_result') != 'true':
        return False, '선택과 실제 결과가 모두 확인되어야 합니다.'
    for key in ('frame_before', 'frame_after'):
        try:
            _, digest = check_media(annotation.get(f'{key}_path', ''))
        except (AnnotationError, OSError):
            return False, f'{key} 근거 이미지를 열 수 없습니다.'
        if digest != annotation.get(f'{key}_sha256', ''):
            return False, f'{key} 근거 이미지 해시가 다릅니다.'
    if annotation.get('frame_before_sha256') == annotation.get('frame_after_sha256'):
        return False, '선택 전후가 동일한 이미지입니다. 결과 확인 시점을 다시 검토하세요.'
    return True, '검수 이미지 근거 확인'


def apply_progress(worklist: list[dict], progress_path=PROGRESS_JSON, annotation_path=ANNOTATIONS_CSV):
    progress = read_progress(progress_path)
    annotations = {r['annotation_id']: r for r in read_annotations(annotation_path)}
    output = []
    for task in worklist:
        row = dict(task)
        info = progress.get(task['task_id'], {})
        status = info.get('status', 'pending')
        if status not in STATES:
            status = 'pending'
        annotation_id = info.get('annotation_id', '')
        if status == 'verified':
            matched = annotations.get(annotation_id)
            okay, reason = _valid_evidence(matched)
            if matched and matched.get('source_id') != task['source_id']:
                okay, reason = False, '연결한 출처 ID가 다릅니다.'
            if okay and task['video_seconds'] >= 0:
                if abs(int(matched['video_seconds']) - int(task['video_seconds'])) > 120:
                    okay, reason = False, '원본 챕터에서 120초보다 멀리 떨어진 근거입니다.'
            if not okay:
                status = 'blocked'
                info = {**info, 'note': reason}
        row.update({'status': status, 'annotation_id': annotation_id,
                    'note': info.get('note', row['note']),
                    'reviewer': info.get('reviewer', '')})
        output.append(row)
    return output


def update_progress(task_id: str, status: str, *, annotation_id='', reviewer='', note='',
                    progress_path=PROGRESS_JSON, annotation_path=ANNOTATIONS_CSV,
                    worklist=None):
    if status not in STATES:
        raise ValueError('알 수 없는 검수 상태')
    tasks = worklist if worklist is not None else build_worklist()
    current = next((r for r in tasks if r['task_id'] == task_id), None)
    if current is None:
        raise ValueError('실제 작업 목록에 존재하지 않는 ID')
    if status == 'verified':
        match = next((r for r in read_annotations(annotation_path)
                      if r.get('annotation_id') == annotation_id), None)
        okay, reason = _valid_evidence(match)
        if not okay:
            raise ValueError('검수 완료 불가: ' + reason)
        if match['source_id'] != current['source_id']:
            raise ValueError('출처 불일치')
        if current['video_seconds'] >= 0 and abs(int(match['video_seconds'])-current['video_seconds']) > 120:
            raise ValueError('챕터 시점과 검수 기록의 차이가 120초를 초과합니다.')
    if len(note) > 2000 or len(reviewer) > 120:
        raise ValueError('메모 또는 검수자 이름이 너무 깁니다.')
    previous = read_progress(progress_path)
    previous[task_id] = {'status': status, 'annotation_id': annotation_id,
                          'reviewer': reviewer, 'note': note,
                          'updated_utc': datetime.now(timezone.utc).isoformat()}
    _atomic_json(Path(progress_path), {'version': 1, 'tasks': previous})
    return previous[task_id]


def audit_worklist(worklist: list[dict]):
    counts = Counter(t['status'] for t in worklist)
    main = sum(t['suggested_purpose'] in PURPOSE_MAP for t in worklist)
    return {'tasks': len(worklist), 'by_status': dict(counts), 'candidate_main_run_tasks': main,
            'reviewed_with_before_after': counts.get('verified',0),
            'verified_annotation_links': len({t['annotation_id'] for t in worklist if t['status']=='verified' and t.get('annotation_id')}),
            'trained_model': False, 'automatically_downloaded_videos': 0}


def create_r9_template(out_path):
    _atomic_csv(Path(out_path), R9_FIELDS, [])


def export_r9_verified(annotation_path: Path, manual_bundles_path: Path, out_path: Path):
    """Export ONLY manually verified displayed training gains (not observed choice quality).

    A reviewer must explicitly affirm each screenshot's displayed values and all
    conditioning metadata. Neither a timestamp nor a chosen action suffices.
    """
    out_path, annotation_path, manual_bundles_path = map(Path, (out_path, annotation_path, manual_bundles_path))
    if out_path.resolve() in {annotation_path.resolve(), manual_bundles_path.resolve()}:
        raise ValueError('원본 검수 기록이나 JSON을 결과 파일로 덮어쓸 수 없습니다.')
    if out_path.is_file() and out_path.stat().st_size:
        raise ValueError('기존 R9 CSV를 덮어쓰지 않습니다. 새 파일 이름을 선택하세요.')
    entries = json.loads(manual_bundles_path.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise ValueError('수동 검수 증거 파일은 JSON 배열이어야 합니다.')
    annotated = {r['annotation_id']:r for r in read_annotations(annotation_path)}
    out, rejected, identities = [], [], set()
    for index, b in enumerate(entries, 1):
        try:
            if not isinstance(b, dict):
                raise ValueError('검수 JSON 객체가 아닙니다.')
            aid = b.get('annotation_id', '')
            a = annotated.get(aid)
            valid, reason = _valid_evidence(a)
            if not valid:
                raise ValueError(reason)
            purpose = PURPOSE_MAP.get(a['run_purpose'])
            if not purpose:
                raise ValueError('챔미/리오히 실전 본육성 자료가 아닙니다.')
            if b.get('reviewer_confirmed_preview') is not True or b.get('synthetic') is not False:
                raise ValueError('훈련 프리뷰 수치를 실물 화면에서 수동 확인해야 합니다.')
            if len(str(b.get('visual_evidence_note','')).strip()) < 15:
                raise ValueError('화면 수치 확인 근거를 15자 이상 기재하세요.')
            if a.get('source_url','') != b.get('source_url'):
                raise ValueError('R2 출처 URL 불일치')
            training = b['training']
            if training not in (*FACILITY_STATS, '섬 트레이닝'):
                raise ValueError('훈련 종류 오류')
            frame_path = Path(b['preview_frame_path'])
            _, digest = check_media(frame_path)
            # Only the R2 before-frame is accepted. No side image without provenance.
            if digest != a['frame_before_sha256']:
                raise ValueError('훈련 수치 프리뷰 이미지가 검수된 선택 전 프레임과 다릅니다.')
            gains = b['displayed_gains']
            if not isinstance(gains, dict) or set(gains) != set(GAIN_KEYS):
                raise ValueError('스탯 5개 + 스킬 Pt 표시 수치 6개 모두 있어야 합니다.')
            if any(type(gains[k]) is not int for k in GAIN_KEYS):
                raise ValueError('표시된 상승량은 정수여야 합니다.')
            run_id = a['source_id'] + '-' + a['case_id']
            row = {key: '' for key in R9_FIELDS}
            row.update({
                'sample_id': aid + '-' + training, 'run_id':run_id,
                'source_type':'reviewed_video_frame','source_url':a['source_url'],
                'frame_sha256':digest,'captured_date':b['capture_date'],
                'server':'JP','patch_status':'JP_after_2025_06_30_2320',
                'scenario':'island_post_patch_v1','purpose':purpose,'phase':b['phase'],
                'training':training,'character':a['character'],
                'support_deck_key':b['support_deck_key'],'context_key':b['context_key'],
                'facility_levels_json':json.dumps(b['facility_levels'],ensure_ascii=False),
                'facility_routes_json':json.dumps(b['facility_routes'],ensure_ascii=False),
                'friendship_counts_json':json.dumps(b['friendship_counts'],ensure_ascii=False),
                'verified':'true','synthetic':'false',
                'reviewer_note':str(b['visual_evidence_note']).strip(), **gains
            })
            clean = validate_r9(row)
            identity = ('JP', digest, training)
            if identity in identities:
                raise ValueError('동일 프레임·훈련 중복')
            identities.add(identity)
            out.append(clean)
        except (ValueError, KeyError, TypeError, OSError, AnnotationError) as e:
            rejected.append({'item':index, 'annotation_id':b.get('annotation_id','') if isinstance(b,dict) else '',
                             'reason':str(e)[:450]})
    # Do not silently mix accepted records with rejected records.
    _atomic_csv(Path(out_path), R9_FIELDS, out)
    return {'submitted':len(entries),'accepted':len(out),'rejected':rejected,
            'output':str(out_path),'numerical_estimation_ready':False,
            'note':'수동 검수된 화면 상승량만 R9 데이터로 전달합니다. 최적 행동 정답이나 학습 완료 모델이 아닙니다.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='R10 로컬 영상 검수 작업 관리 / 근거 CSV 변환')
    sub = parser.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('queue'); q.add_argument('--out',type=Path,required=True)
    a = sub.add_parser('audit'); a.add_argument('--progress',type=Path,default=PROGRESS_JSON)
    e = sub.add_parser('export-r9');e.add_argument('--annotations',type=Path,default=ANNOTATIONS_CSV)
    e.add_argument('--bundles',type=Path,required=True); e.add_argument('--out',type=Path,required=True)
    args = parser.parse_args(argv)
    if args.cmd == 'queue':
        rows=apply_progress(build_worklist())
        _atomic_csv(args.out, tuple(rows[0]) if rows else (), rows)
        print(f'검수 작업 {len(rows)}건 (미확인 프레임은 완료 처리 불가): {args.out}')
    elif args.cmd == 'audit':
        rows=apply_progress(build_worklist(),args.progress)
        print(json.dumps(audit_worklist(rows),ensure_ascii=False,indent=2))
    else:
        print(json.dumps(export_r9_verified(args.annotations,args.bundles,args.out),ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
