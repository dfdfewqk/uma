"""Auditable, offline annotation store for actual post-patch video frames.

Reviewed play is *behavioral data*, not proof of an optimal action.
Only manually inspected frames can be marked frame_verified.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
from datetime import datetime, timezone

if getattr(sys, 'frozen', False):
    # Research EXE keeps user annotations outside the temporary onefile extraction folder.
    ROOT = Path(sys._MEIPASS) / 'research'
    DATA_DIR = Path.home() / 'Documents' / 'UmaTrainerKR_Research' / 'video_reviews'
else:
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / 'video_reviews'
RESEARCH_DIR = ROOT / 'jp_post_patch_2025'
DEFAULT_OUTPUT = DATA_DIR / 'verified_turns.csv'
MEDIA_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
YEARS = {'주니어', '클래식', '시니어', '파이널즈'}
EVENTS = {'챔피언스 미팅', '리그 오브 히어로즈', '미확인'}
RUN_PURPOSES = {'champ_main', 'loh_main', 'factor_farming', 'evaluation_score', 'unknown'}
STATS = ('speed', 'stamina', 'power', 'guts', 'wisdom')
FIELDS = (
    'annotation_id','source_id','case_id','scenario_id','server','patch_status',
    'competition','run_purpose','character','video_seconds','school_year','turn_label','patch_evidence',
    'energy','speed','stamina','power','guts','wisdom','skill_points',
    'island_tickets','development_points','facilities_json',
    'alternatives_json','chosen_action','post_action_json',
    'frame_before_path','frame_before_sha256','frame_after_path','frame_after_sha256',
    'observed_choice','observed_result','review_grade','reviewer','notes',
    'created_utc','source_url'
)


class AnnotationError(ValueError):
    pass


def read_sources(path=RESEARCH_DIR / 'sources.csv'):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return {r['source_id']: r for r in csv.DictReader(f)}


def check_media(path):
    if not path:
        raise AnnotationError('화면 이미지 경로가 지정되지 않았습니다.')
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.suffix.lower() not in MEDIA_EXT:
        raise AnnotationError('실제 PNG/JPG/WebP 프레임 파일을 선택해야 합니다.')
    if p.stat().st_size == 0:
        raise AnnotationError('빈 이미지입니다.')
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _integer(text, label, lo=0, hi=100000, allow_blank=True):
    if (text is None or str(text).strip() == '') and allow_blank:
        return ''
    if isinstance(text, bool):
        raise AnnotationError(f'{label}: 정수만 허용')
    try:
        val = int(str(text))
    except (ValueError, TypeError):
        raise AnnotationError(f'{label}: 정수만 허용') from None
    if not lo <= val <= hi:
        raise AnnotationError(f'{label}: {lo}~{hi} 범위를 확인하세요.')
    return str(val)


def _json_obj(text, name, required=False):
    try:
        obj = json.loads(text if isinstance(text, str) else json.dumps(text))
    except (TypeError, ValueError) as e:
        raise AnnotationError(f'{name}: JSON 오류: {e}') from None
    if not isinstance(obj, dict) or (required and not obj):
        raise AnnotationError(f'{name}: 내용이 있는 JSON 객체여야 합니다.')
    return obj


def validate_annotation(raw: dict, sources=None):
    sources = sources if sources is not None else read_sources()
    source_id = str(raw.get('source_id', '')).strip()
    source = sources.get(source_id)
    if not source:
        raise AnnotationError('기존 연구팩의 source_id가 필요합니다.')
    if not source['source_kind'].startswith('video_'):
        raise AnnotationError('이 도구는 영상 출처만 받아들입니다.')
    if source.get('published_date') and source['published_date'] < '2025-07-01':
        raise AnnotationError('패치 이전 영상은 R2 검수 대상이 아닙니다.')
    if raw.get('server', 'JP') != 'JP':
        raise AnnotationError('R2는 일본 서버 검증 영상에 한정합니다.')
    if raw.get('patch_status') != 'post_2025_06_30_confirmed':
        raise AnnotationError('패치 후 버전임을 확인한 경우만 기록합니다.')
    if len(str(raw.get('patch_evidence', '')).strip()) < 12:
        raise AnnotationError('해당 플레이가 패치 이후임을 확인한 근거를 12자 이상 적으세요.')
    if raw.get('competition', '미확인') not in EVENTS:
        raise AnnotationError('챔미/리오히/미확인 중에서 선택하세요.')
    purpose = raw.get('run_purpose','unknown')
    if purpose not in RUN_PURPOSES:
        raise AnnotationError('육성 목적을 정확히 구분하세요.')
    if purpose == 'champ_main' and raw.get('competition') != '챔피언스 미팅':
        raise AnnotationError('챔미 본육성은 챔피언스 미팅으로 분류해야 합니다.')
    if purpose == 'loh_main' and raw.get('competition') != '리그 오브 히어로즈':
        raise AnnotationError('리오히 본육성은 리그 오브 히어로즈로 분류해야 합니다.')
    if source.get('scope') == 'general_score' and purpose in {'champ_main','loh_main'}:
        raise AnnotationError('일반 평가점 영상은 실전 본육성 영상으로 잘못 분류할 수 없습니다.')
    if source.get('scope') == 'loh_factor' and purpose in {'champ_main','loh_main'}:
        raise AnnotationError('인자작 영상은 본육성으로 잘못 분류할 수 없습니다.')
    if raw.get('school_year') not in YEARS:
        raise AnnotationError('육성 연도를 정확히 선택하세요.')
    video_seconds = _integer(raw.get('video_seconds'), '영상 초', 0, 9999999, False)
    case_id = str(raw.get('case_id', '')).strip()
    if not case_id or not all(c.isalnum() or c in '-_' for c in case_id):
        raise AnnotationError('case_id는 영문/숫자/_/-만 허용합니다.')
    if len(case_id) > 80:
        raise AnnotationError('case_id 길이가 너무 깁니다.')
    reviewer = str(raw.get('reviewer','')).strip()
    if not reviewer:
        raise AnnotationError('검수자 식별명을 입력하세요.')
    before, before_hash = check_media(raw.get('frame_before_path',''))
    after_path = str(raw.get('frame_after_path', '')).strip()
    after, after_hash = check_media(after_path) if after_path else ('', '')
    observed_choice = str(raw.get('observed_choice','')).lower() == 'true'
    observed_result = str(raw.get('observed_result','')).lower() == 'true'
    if observed_result and not after:
        raise AnnotationError('실행 결과 검증에는 선택 후 프레임이 필요합니다.')
    chosen = str(raw.get('chosen_action', '')).strip()
    if observed_choice and not chosen:
        raise AnnotationError('실제 선택을 확인했다면 선택 행동을 적으세요.')
    alternatives = _json_obj(raw.get('alternatives_json','{}'), '행동 후보')
    facilities = _json_obj(raw.get('facilities_json','{}'), '시설')
    post_action = _json_obj(raw.get('post_action_json','{}'), '실행 결과')
    if observed_choice and alternatives and chosen not in alternatives:
        raise AnnotationError('선택 행동이 확인한 후보 행동 안에 없습니다.')
    if observed_result and not observed_choice:
        raise AnnotationError('선택을 확인하지 않고 결과를 확인했다고 표시할 수 없습니다.')
    observed_fields = sum(str(raw.get(s,'')).strip() != '' for s in (*STATS, 'energy'))
    valid_choices = len(alternatives) >= 2 and all(isinstance(v,dict) and bool(v) for v in alternatives.values())
    grade = 'complete' if (observed_choice and observed_result and valid_choices and observed_fields == 6) else 'partial'
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    row = {k:'' for k in FIELDS}
    row.update({
        'annotation_id': f'{source_id}-{case_id}-{video_seconds}',
        'source_id': source_id,
        'case_id': case_id,
        'scenario_id': 'island_post_patch_v1',
        'server': 'JP',
        'patch_status': 'post_2025_06_30_confirmed',
        'competition': raw.get('competition','미확인'),
        'run_purpose': purpose,
        'character': str(raw.get('character', '')).strip(),
        'video_seconds': video_seconds,
        'school_year': raw['school_year'],
        'turn_label': str(raw.get('turn_label','')).strip(),
        'patch_evidence': str(raw.get('patch_evidence','')).strip(),
        'facilities_json': json.dumps(facilities, ensure_ascii=False, sort_keys=True),
        'alternatives_json': json.dumps(alternatives, ensure_ascii=False, sort_keys=True),
        'chosen_action': chosen,
        'post_action_json': json.dumps(post_action, ensure_ascii=False, sort_keys=True),
        'frame_before_path': str(before),
        'frame_before_sha256': before_hash,
        'frame_after_path': str(after) if after else '',
        'frame_after_sha256': after_hash,
        'observed_choice': str(observed_choice).lower(),
        'observed_result': str(observed_result).lower(),
        'review_grade': grade,
        'reviewer': reviewer,
        'notes': str(raw.get('notes','')).strip(),
        'created_utc': timestamp,
        'source_url': source['url'],
    })
    for s in STATS:
        row[s] = _integer(raw.get(s), s, 0, 99999)
    for name, hi in [('energy', 1000), ('skill_points',100000),('island_tickets',99),('development_points',100000)]:
        row[name] = _integer(raw.get(name), name, 0, hi)
    return row


def read_annotations(path=DEFAULT_OUTPUT):
    if not Path(path).is_file():
        return []
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def add_annotation(raw: dict, path=DEFAULT_OUTPUT, sources=None):
    path = Path(path)
    new_row = validate_annotation(raw, sources)
    old = read_annotations(path)
    if new_row['annotation_id'] in {r['annotation_id'] for r in old}:
        raise AnnotationError('같은 영상·사례·타임스탬프는 중복 저장할 수 없습니다.')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write prevents partially written CSV if app closes mid-save.
    fd, temporary = tempfile.mkstemp(prefix='.annotations-', suffix='.csv', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, FIELDS)
            writer.writeheader()
            for row in old:
                writer.writerow({k:row.get(k,'') for k in FIELDS})
            writer.writerow(new_row)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return new_row


def audit_annotations(path=DEFAULT_OUTPUT, verify_images=True):
    rows = read_annotations(path)
    ids = set()
    errors = []
    grades = {'complete':0, 'partial':0}
    main_run_turns = 0
    for idx, row in enumerate(rows,2):
        key = row.get('annotation_id','')
        if not key or key in ids:
            errors.append(f'{idx}행: 누락되거나 중복된 id')
        ids.add(key)
        grades[row.get('review_grade','partial')] = grades.get(row.get('review_grade','partial'),0)+1
        if row.get('run_purpose') in {'champ_main','loh_main'}:
            main_run_turns += 1
        if row.get('observed_result') == 'true' and not row.get('frame_after_sha256'):
            errors.append(f'{idx}행: 결과 근거 이미지 없음')
        if row.get('observed_choice') == 'true' and not row.get('chosen_action'):
            errors.append(f'{idx}행: 행동 근거 누락')
        for field in ('frame_before','frame_after'):
            p = row.get(field+'_path','')
            h = row.get(field+'_sha256','')
            if verify_images and p:
                try:
                    _, current_hash = check_media(p)
                    if current_hash != h:
                        errors.append(f'{idx}행: {field} 원본이 변경됨')
                except AnnotationError:
                    errors.append(f'{idx}행: {field} 원본을 찾을 수 없음')
    # A few observed human choices are not enough to claim a trained predictor.
    return {'rows':len(rows), 'full_before_and_after':grades.get('complete',0),
            'partial_rows':grades.get('partial',0), 'main_run_observed_turns':main_run_turns, 'errors':errors,
            'ml_training_status':'NOT_TRAINABLE: 실전의 최적 행동 정답·반사실적 결과·다양한 실전 표본 부족'}


def export_reviewer_summary(output, path=DEFAULT_OUTPUT):
    summary = audit_annotations(path)
    Path(output).write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return summary
