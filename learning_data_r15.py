"""R15 evidence-gated OFFLINE learning-data preparation (NOT model training).

Never infer that a player's chosen action was optimal. All accepted examples
carry a behavioral label and are separated by provenance group before export.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scenario_features_r15 import extract_scenario_features
from storage import list_runs, list_turns
from uma_core import Action, STATS, action_is_observed

SCHEMA = 'uma-learning-turn-v1'
MIN_TRAIN_GROUPS = 30  # conservative readiness gate, NOT an accuracy guarantee
MIN_TRAIN_TURNS = 200
VALID_ORIGINS = frozenset({'game_screenshot', 'reviewed_game_video'})
VALID_SERVERS = frozenset({'KR', 'JP'})


def digest_file(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise ValueError('증거 이미지가 존재하지 않습니다.')
    if p.stat().st_size <= 0 or p.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('증거 이미지 크기를 확인하세요 (최대 25MB).')
    # Decode and validate genuine image files, not just renamed text files.
    if p.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('증거 파일은 PNG/JPG/WEBP 이미지만 허용합니다.')
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(p) as im:
            w, hpx = im.size
            if w < 10 or hpx < 10 or w * hpx > 40_000_000:
                raise ValueError('증거 이미지 해상도가 허용 범위를 벗어났습니다.')
            im.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError('이미지 파일을 정상적으로 해석할 수 없습니다.') from exc
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def source_snapshot(profile: dict, turn: dict) -> dict:
    return {'profile': profile, 'state': turn.get('state'), 'options': turn.get('options'),
            'chosen_action': turn.get('chosen_action')}


def review_db_path() -> Path:
    import os
    folder = (Path(os.environ['LOCALAPPDATA']) / 'UmaTrainerKR') if os.environ.get('LOCALAPPDATA') else Path.home() / '.uma_trainer_kr'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'r15_learning_reviews.sqlite3'


def connect_reviews(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path or review_db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p))
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS verified_turns (
        run_id INTEGER NOT NULL,
        turn_id INTEGER NOT NULL,
        source_hash TEXT NOT NULL,
        evidence_before_path TEXT NOT NULL,
        evidence_before_sha256 TEXT NOT NULL,
        evidence_after_path TEXT NOT NULL,
        evidence_after_sha256 TEXT NOT NULL,
        origin TEXT NOT NULL,
        server TEXT NOT NULL,
        patch_version TEXT NOT NULL,
        provenance_group TEXT NOT NULL,
        reviewer_note TEXT NOT NULL,
        verified_at TEXT NOT NULL,
        PRIMARY KEY(run_id, turn_id)
      );
    ''')
    if not db.execute("SELECT 1 FROM metadata WHERE name='installation_id'").fetchone():
        db.execute("INSERT INTO metadata VALUES ('installation_id', ?)", (str(uuid.uuid4()),))
    db.commit()
    return db


def _find_pair(runs_db: sqlite3.Connection, run_id: int, turn_id: int) -> tuple[dict, dict]:
    r = next((x for x in list_runs(runs_db) if x['id'] == run_id), None)
    if r is None:
        raise ValueError('육성 기록을 찾을 수 없습니다.')
    t = next((x for x in list_turns(runs_db, run_id) if x['id'] == turn_id), None)
    if t is None:
        raise ValueError('턴 기록을 찾을 수 없습니다.')
    return r, t


def _observed(turn: dict) -> dict[str, dict]:
    result = {}
    for name, values in (turn.get('options') or {}).items():
        if not isinstance(values, dict):
            continue
        try:
            if action_is_observed(Action(**values)):
                result[name] = values
        except (TypeError, ValueError):
            continue
    return result


def validate_candidate(run: dict, turn: dict) -> None:
    profile = run['profile']
    if not isinstance(profile, dict) or not profile.get('scenario'):
        raise ValueError('시나리오 ID가 없어 검수할 수 없습니다.')
    extract_scenario_features(profile['scenario'], turn['state'], profile)
    observed = _observed(turn)
    if len(observed) < 2:
        raise ValueError('실제로 관측된 선택지가 두 개 이상 필요합니다.')
    if turn.get('chosen_action') not in observed:
        raise ValueError('실제 선택한 행동이 관측 선택지에 없습니다.')
    if not isinstance(turn.get('state'), dict) or not isinstance(turn['state'].get('stats'), dict):
        raise ValueError('선택 전 상태가 부족합니다.')
    for field in ('remaining_turns', 'energy'):
        if not isinstance(turn['state'].get(field), int) or isinstance(turn['state'][field], bool):
            raise ValueError(f'선택 전 {field} 값을 확인하세요.')


def verify_turn(runs_db: sqlite3.Connection, reviews_db: sqlite3.Connection, *, run_id: int,
                turn_id: int, before: str | Path, after: str | Path, origin: str,
                server: str, patch_version: str, provenance_group: str,
                reviewer_note: str) -> None:
    run, turn = _find_pair(runs_db, run_id, turn_id)
    validate_candidate(run, turn)
    if origin not in VALID_ORIGINS or server not in VALID_SERVERS:
        raise ValueError('출처 또는 서버를 명확히 선택하세요.')
    if not patch_version.strip() or patch_version.strip().lower() in {'unknown', '미확인', 'test', 'synthetic'}:
        raise ValueError('패치 버전을 확인해서 입력해 주세요.')
    if not reviewer_note.strip():
        raise ValueError('검수 내용과 확인 근거를 적어 주세요.')
    if origin == 'reviewed_game_video' and not provenance_group.strip():
        raise ValueError('영상 출처 ID가 필요합니다. 동일 영상의 모든 육성에는 동일 ID를 사용하세요.')
    a, b = digest_file(before), digest_file(after)
    if a == b:
        raise ValueError('선택 전과 후의 증거 이미지가 같습니다.')
    snap = canonical_hash(source_snapshot(run['profile'], turn))
    reviews_db.execute('''INSERT OR REPLACE INTO verified_turns
        (run_id,turn_id,source_hash,evidence_before_path,evidence_before_sha256,
        evidence_after_path,evidence_after_sha256,origin,server,patch_version,
        provenance_group,reviewer_note,verified_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (run_id, turn_id, snap, str(Path(before).resolve()), a,
           str(Path(after).resolve()), b, origin, server, patch_version.strip(),
           provenance_group.strip(), reviewer_note.strip(), datetime.now(timezone.utc).isoformat()))
    reviews_db.commit()


def _component_groups(reviews: list[dict], install_id: str) -> dict[tuple[int, int], str]:
    """Connected components across BOTH run-id and provenance source-id.

    A run may appear in multiple video sources, and one video may include
    multiple runs. Neither side can cross train/validation/test boundaries.
    """
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    def union(a: str, b: str) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for rev in reviews:
        run = f"run:{install_id}:{rev['run_id']}"
        find(run)
        source = str(rev.get('provenance_group', '')).strip().casefold()
        if source:
            union(run, f"source:{source}")

    return {(rev['run_id'], rev['turn_id']): find(f"run:{install_id}:{rev['run_id']}") for rev in reviews}


def _split(group_key: str) -> str:
    bucket = int(hashlib.sha256(('uma-r15-split-v1|' + group_key).encode()).hexdigest()[:12], 16) % 100
    return 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test'


def _load_reviews(db: sqlite3.Connection) -> list[dict]:
    db.row_factory = sqlite3.Row
    result = [dict(x) for x in db.execute('SELECT * FROM verified_turns ORDER BY run_id,turn_id')]
    db.row_factory = None
    return result


def _sanitize_common(profile: dict, turn: dict) -> dict:
    state = turn['state']
    # Only fields available BEFORE the action. No outcome, next-state, analysis
    # recommendation, note, screenshot filepath or user identifiers.
    features = {
        'distance': profile.get('distance'), 'style': profile.get('style'),
        'event': profile.get('event'), 'course': profile.get('course'),
        'surface': profile.get('surface'),
        'target_stats': {s: profile.get('target_stats', {}).get(s) for s in STATS},
        'turn_label': state.get('turn_label'),
        'remaining_turns': state.get('remaining_turns'), 'energy': state.get('energy'),
        'mood': state.get('mood'), 'skill_points': state.get('skill_points'),
        'stats': {s: state.get('stats', {}).get(s) for s in STATS},
        'core_skill_status': state.get('core_skill_status'),
    }
    return features


def audit_and_collect(runs_db: sqlite3.Connection, reviews_db: sqlite3.Connection) -> dict:
    runs = {r['id']: r for r in list_runs(runs_db)}
    turns_by_run = {k: {t['id']: t for t in list_turns(runs_db, k)} for k in runs}
    install_id = reviews_db.execute("SELECT value FROM metadata WHERE name='installation_id'").fetchone()[0]
    kept, excluded, seen_pair, evidence_first = [], [], set(), {}
    reviews = _load_reviews(reviews_db)
    components = _component_groups(reviews, install_id)
    for rev in reviews:
        try:
            run = runs.get(rev['run_id'])
            turn = turns_by_run.get(rev['run_id'], {}).get(rev['turn_id'])
            if run is None or turn is None:
                raise ValueError('원본 육성 또는 턴 기록이 없습니다.')
            validate_candidate(run, turn)
            if canonical_hash(source_snapshot(run['profile'], turn)) != rev['source_hash']:
                raise ValueError('검수 이후 원본 턴/목표 기록이 변경됐습니다.')
            a = digest_file(rev['evidence_before_path'])
            b = digest_file(rev['evidence_after_path'])
            if a != rev['evidence_before_sha256'] or b != rev['evidence_after_sha256'] or a == b:
                raise ValueError('이미지 해시 변경 또는 전후 동일 이미지')
            if (a, b) in seen_pair:
                raise ValueError('동일 전후 증거를 중복 등록했습니다.')
            group = components[(rev['run_id'], rev['turn_id'])]
            if a in evidence_first and evidence_first[a] != group:
                raise ValueError('같은 게임 화면이 서로 다른 출처 그룹에 등록됐습니다.')
            seen_pair.add((a, b))
            evidence_first[a] = group
            profile = run['profile']
            record = {
                'schema': SCHEMA, 'scenario_id': profile['scenario'],
                'server': rev['server'], 'patch_version': rev['patch_version'],
                'origin': rev['origin'], 'provenance_group_hash': canonical_hash(group),
                'example_id': canonical_hash({'group': group, 'run': rev['run_id'], 'turn': rev['turn_id']}),
                'features': _sanitize_common(profile, turn),
                'scenario_features': extract_scenario_features(profile['scenario'], turn['state'], profile),
                'observed_options': {name: {k: v for k, v in val.items() if k in
                   ('gains', 'skill_points', 'energy_delta', 'friend_types', 'bond_gain',
                    'failure_percent', 'development_points')}
                   for name, val in _observed(turn).items()},
                'label': {'chosen_action': turn['chosen_action'], 'meaning': 'human_behavior_not_optimality'},
                'evidence': {'before_sha256': a, 'after_sha256': b,
                             'reviewed_at': rev['verified_at']},
                'split': _split(group),
            }
            kept.append(record)
        except (ValueError, TypeError, KeyError) as exc:
            excluded.append({'run_id': rev['run_id'], 'turn_id': rev['turn_id'], 'reason': str(exc)})
    # Refuse inconsistent patch/server metadata within a single provenance group.
    group_versions: dict[str, set] = {}
    for rec in kept:
        group_versions.setdefault(rec['provenance_group_hash'], set()).add((rec['server'], rec['patch_version'], rec['scenario_id']))
    if any(len(v) > 1 for v in group_versions.values()):
        valid = []
        for rec in kept:
            if len(group_versions[rec['provenance_group_hash']]) > 1:
                excluded.append({'example_id': rec['example_id'], 'reason': '하나의 출처 그룹에서 서버/패치/시나리오 충돌'})
            else:
                valid.append(rec)
        kept = valid
    groups = {part: set(r['provenance_group_hash'] for r in kept if r['split'] == part) for part in ('train', 'validation', 'test')}
    unique_groups = len(set().union(*groups.values()))
    # Training readiness is evaluated PER cohort, never by pooling different
    # scenarios/servers/patches/competition modes into a misleading big sample.
    cohorts: dict[str, dict] = {}
    for rec in kept:
        cohort = '|'.join([rec['scenario_id'], rec['server'], rec['patch_version'],
                           str(rec['features']['event'])])
        cohorts.setdefault(cohort, {'rows': 0, 'splits': {s: set() for s in groups}})
        cohorts[cohort]['rows'] += 1
        cohorts[cohort]['splits'][rec['split']].add(rec['provenance_group_hash'])
    cohort_report = {}
    for cohort, info in sorted(cohorts.items()):
        count = len(set().union(*info['splits'].values()))
        eligible = (info['rows'] >= MIN_TRAIN_TURNS and count >= MIN_TRAIN_GROUPS and
                    all(info['splits'][s] for s in groups))
        cohort_report[cohort] = {'rows': info['rows'], 'source_groups': count,
                                  'splits': {k: len(v) for k, v in info['splits'].items()},
                                  'training_ready_gate': eligible}
    ready = any(v['training_ready_gate'] for v in cohort_report.values())
    return {
        'records': kept, 'excluded': excluded,
        'summary': {
            'reviewed_rows': len(reviews),
            'exportable_rows': len(kept), 'excluded_rows': len(excluded),
            'independent_source_groups': unique_groups,
            'cohorts': cohort_report,
            'splits': {k: {'rows': sum(r['split'] == k for r in kept), 'groups': len(groups[k])} for k in groups},
            'training_ready_gate': ready,
            'gate_note': '학습 가능성에 대한 최소 검토 조건이며 정확도 보증이 아닙니다.' if ready
                         else f'보류: 동일 시나리오·서버·패치·대회 내 최소 {MIN_TRAIN_TURNS}턴·{MIN_TRAIN_GROUPS}개 독립 출처·세 분할 모두 필요',
            'model_trained': False,
        }
    }


def export_training_pack(runs_db: sqlite3.Connection, reviews_db: sqlite3.Connection, folder: Path) -> dict:
    audit = audit_and_collect(runs_db, reviews_db)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for partition in ('train', 'validation', 'test'):
        data = [x for x in audit['records'] if x['split'] == partition]
        path = folder / f'uma_r15_{partition}.jsonl'
        with path.open('w', encoding='utf-8') as fp:
            for record in data:
                fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
    report = {'schema': SCHEMA, **audit['summary'], 'excluded': audit['excluded'],
              'privacy': 'local-only; exports contain no source file paths or player names',
              'label_warning': 'chosen_action is an observed HUMAN decision, never a ground-truth optimal action',
              'model_artifact': None}
    (folder / 'uma_r15_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
