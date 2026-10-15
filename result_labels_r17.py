"""R17 local, evidence-gated outcome research labels (NOT ML targets yet).

Abandoned runs are RIGHT-CENSORED: their hypothetical final results are unknown.
A completed training run is not the same as a won Champions Meeting race.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from learning_data_r15 import canonical_hash, digest_file
from storage import list_runs, list_turns

SCHEMA = 'uma-r17-outcome-review-v1'
EXPORT_SCHEMA = 'uma-r17-result-observation-v1'


def default_review_path():
    base = os.getenv('LOCALAPPDATA')
    return (Path(base) / 'UmaTrainerKR' if base else Path.home() / '.uma_trainer_kr') / 'r17_outcome_reviews.sqlite3'


def connect_reviews(path=None):
    p = Path(path or default_review_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p))
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''CREATE TABLE IF NOT EXISTS reviews(
      run_id INTEGER PRIMARY KEY, snapshot_sha256 TEXT NOT NULL,
      screenshot_path TEXT NOT NULL, screenshot_sha256 TEXT NOT NULL,
      server TEXT NOT NULL, patch_version TEXT NOT NULL,
      provenance_group TEXT NOT NULL, reviewer_note TEXT NOT NULL,
      race_matches INTEGER, race_wins INTEGER, loh_points INTEGER,
      verified_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS metadata(name TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    row = db.execute("SELECT value FROM metadata WHERE name='installation_id'").fetchone()
    if row is None:
        import uuid
        db.execute("INSERT INTO metadata(name,value) VALUES('installation_id',?)", (uuid.uuid4().hex,))
    db.commit()
    return db


def _snapshot(profile, outcome, turns):
    return canonical_hash({'profile': profile, 'outcome': outcome,
                           'last_turn_id': turns[-1]['id'] if turns else None,
                           'turn_count': len(turns)})


def _lookup(conn, run_id):
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError('육성 기록 번호 오류')
    run = next((x for x in list_runs(conn) if x['id'] == run_id), None)
    if run is None:
        raise ValueError('해당 육성 기록이 없습니다.')
    turns = list_turns(conn, run_id)
    if not turns:
        raise ValueError('턴 기록이 없는 육성은 결과 검수할 수 없습니다.')
    if run['outcome'].get('status') not in ('육성 완료', '도축/중단'):
        raise ValueError('완주 또는 도축/중단 상태를 먼저 기록해야 합니다.')
    if run['outcome']['status'] == '도축/중단' and not str(run['outcome'].get('reason', '')).strip():
        raise ValueError('중단 원인 누락')
    p = run['profile']
    for field in ('scenario', 'event'):
        if not isinstance(p.get(field), str) or not p[field]:
            raise ValueError('육성 시나리오/대회 유형 누락')
    return run, turns


def _optional_count(value, maximum, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= maximum):
        raise ValueError(label + ' 범위 오류')
    return value


def review_run(runs_db, reviews_db, run_id, evidence_path, *, server, patch_version,
               provenance_group, reviewer_note, race_matches=None, race_wins=None,
               loh_points=None):
    run, turns = _lookup(runs_db, run_id)
    if server not in ('KR', 'JP') or not isinstance(patch_version, str) or len(patch_version.strip()) < 5:
        raise ValueError('서버/패치 버전 확인 필요')
    if not str(provenance_group).strip() or not str(reviewer_note).strip():
        raise ValueError('원본 출처 ID 및 검수 근거를 입력해야 합니다.')
    matches = _optional_count(race_matches, 100000, '경기 수')
    wins = _optional_count(race_wins, 100000, '승리 수')
    points = _optional_count(loh_points, 10000000, '리오히 점수')
    if (matches is None) != (wins is None):
        raise ValueError('경기 횟수와 승리 횟수를 함께 입력하세요.')
    if matches is not None and (matches < 1 or wins > matches):
        raise ValueError('경기/승리 횟수 불일치')
    if (matches is not None or points is not None) and run['outcome']['status'] != '육성 완료':
        raise ValueError('도축한 육성에는 참가하지 않은 경기를 연결할 수 없습니다.')
    e = digest_file(evidence_path)
    snapshot = _snapshot(run['profile'], run['outcome'], turns)
    reviews_db.execute('''INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(run_id) DO UPDATE SET snapshot_sha256=excluded.snapshot_sha256,
      screenshot_path=excluded.screenshot_path,screenshot_sha256=excluded.screenshot_sha256,
      server=excluded.server,patch_version=excluded.patch_version,
      provenance_group=excluded.provenance_group,reviewer_note=excluded.reviewer_note,
      race_matches=excluded.race_matches,race_wins=excluded.race_wins,
      loh_points=excluded.loh_points, verified_at=excluded.verified_at''',
      (run_id, snapshot, str(Path(evidence_path).resolve()), e, server,
       patch_version.strip(), str(provenance_group).strip(), str(reviewer_note).strip(),
       matches, wins, points, datetime.now(timezone.utc).isoformat()))
    reviews_db.commit()


def collect_results(runs_db, reviews_db):
    reviews_db.row_factory = sqlite3.Row
    reviews = [dict(x) for x in reviews_db.execute('SELECT * FROM reviews ORDER BY run_id')]
    reviews_db.row_factory = None
    iid = reviews_db.execute("SELECT value FROM metadata WHERE name='installation_id'").fetchone()[0]
    kept, excluded = [], []
    for rev in reviews:
        try:
            run, turns = _lookup(runs_db, rev['run_id'])
            if rev['snapshot_sha256'] != _snapshot(run['profile'], run['outcome'], turns):
                raise ValueError('검수 후 원본 세션/최종 결과가 변경됨')
            if digest_file(rev['screenshot_path']) != rev['screenshot_sha256']:
                raise ValueError('결과 증거 이미지 변경됨')
            event = run['profile']['event']
            if rev['loh_points'] is not None and '리오히' not in event and '히어로' not in event:
                raise ValueError('리오히가 아닌 대회에 리오히 점수 등록')
            status = run['outcome']['status']
            obj = {'schema': EXPORT_SCHEMA, 'scenario_id': run['profile']['scenario'],
                   'server': rev['server'], 'patch_version': rev['patch_version'],
                   'event': event,
                   'provenance_group_hash': canonical_hash({'install_id':iid,'source':rev['provenance_group']}),
                   'run_hash':canonical_hash({'install_id':iid,'run_id':rev['run_id']}),
                   'status': 'completed' if status == '육성 완료' else 'censored_abandoned',
                   'censored': status == '도축/중단',
                   'abandon_reason': run['outcome'].get('reason', '') if status == '도축/중단' else None,
                   'race_results': {'matches':rev['race_matches'], 'wins':rev['race_wins'],
                                    'loh_points':rev['loh_points']},
                   'evidence_sha256':rev['screenshot_sha256'],
                   'verified_at':rev['verified_at'],
                   'review_status':'human_reviewed_image_NOT_independently_proven',
                   'direct_ml_training_allowed': False,
                   'warning':'중도 포기 사례는 최종 성능을 관측하지 못한 검열 데이터입니다.'}
            kept.append(obj)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            excluded.append({'run_id':rev['run_id'], 'reason':str(exc)})
    return {'kept':kept, 'excluded':excluded}


def export_results(runs_db, reviews_db, dest):
    result = collect_results(runs_db, reviews_db)
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        for rec in result['kept']:
            stream.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, allow_nan=False)+'\n')
    return {'exported':len(result['kept']), 'excluded':result['excluded']}
