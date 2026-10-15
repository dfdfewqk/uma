"""Local-only SQLite persistence and export. No network access."""
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = 3


def db_path() -> Path:
    base = os.getenv('LOCALAPPDATA')
    if base:
        folder = Path(base) / 'UmaTrainerKR'
    else:
        folder = Path.home() / '.uma_trainer_kr'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'runs.sqlite3'


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        profile_json TEXT NOT NULL,
        memo TEXT NOT NULL DEFAULT '',
        outcome_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        created_at TEXT NOT NULL,
        state_json TEXT NOT NULL,
        options_json TEXT NOT NULL,
        recommendations_json TEXT NOT NULL,
        chosen_action TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        r6_review_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE INDEX IF NOT EXISTS ix_turns_run ON turns(run_id,id);
    ''')
    # Upgrade older V0.1 databases in place without deleting existing runs.
    columns = {row[1] for row in conn.execute('PRAGMA table_info(runs)').fetchall()}
    if 'outcome_json' not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN outcome_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    turn_cols = {row[1] for row in conn.execute('PRAGMA table_info(turns)').fetchall()}
    if 'r6_review_json' not in turn_cols:
        conn.execute("ALTER TABLE turns ADD COLUMN r6_review_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    return conn


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def create_run(conn: sqlite3.Connection, profile: Dict[str, Any]) -> int:
    cur = conn.execute('INSERT INTO runs(created_at,profile_json) VALUES (?,?)',
                       (timestamp(), json.dumps(profile, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def add_turn(conn: sqlite3.Connection, run_id: int, state: dict, options: dict,
             recommendations: list, chosen_action: str, note: str = '',
             r6_review: dict | None = None) -> int:
    if not conn.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
        raise ValueError('저장된 육성 세션을 찾을 수 없습니다.')
    cur = conn.execute('''INSERT INTO turns
      (run_id,created_at,state_json,options_json,recommendations_json,chosen_action,note,r6_review_json)
      VALUES (?,?,?,?,?,?,?,?)''', (run_id, timestamp(), json.dumps(state, ensure_ascii=False),
          json.dumps(options, ensure_ascii=False), json.dumps(recommendations, ensure_ascii=False),
          chosen_action, note, json.dumps(r6_review or {}, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def list_runs(conn: sqlite3.Connection) -> list:
    rows = conn.execute('SELECT id,created_at,profile_json,(SELECT COUNT(*) FROM turns t WHERE t.run_id=r.id),outcome_json FROM runs r ORDER BY id DESC').fetchall()
    output = []
    for run_id, created, profile_str, count, outcome_str in rows:
        profile = json.loads(profile_str)
        output.append({'id': run_id, 'created_at': created,
                       'profile': profile, 'turn_count': count, 'outcome': json.loads(outcome_str or '{}')})
    return output


def save_run_outcome(conn: sqlite3.Connection, run_id: int, outcome: dict) -> None:
    """Save the actual finish/abandon outcome, not a predicted result."""
    valid = ('진행중', '육성 완료', '도축/중단')
    if outcome.get('status') not in valid:
        raise ValueError('육성 결과 상태가 올바르지 않습니다.')
    if outcome['status'] == '도축/중단' and not outcome.get('reason', '').strip():
        raise ValueError('중단 사례는 이유를 입력해 주세요. 모르면 미상으로 입력하세요.')
    if not conn.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
        raise ValueError('육성 세션을 찾을 수 없습니다.')
    conn.execute('UPDATE runs SET outcome_json=? WHERE id=?',
                 (json.dumps(outcome, ensure_ascii=False), run_id))
    conn.commit()


def backup_database(conn: sqlite3.Connection, dest: Path) -> None:
    """Use SQLite's online backup API for a consistent snapshot."""
    with sqlite3.connect(str(dest)) as dst:
        conn.backup(dst)


def list_turns(conn: sqlite3.Connection, run_id: int) -> list:
    rows = conn.execute('''SELECT id,created_at,state_json,options_json,
      recommendations_json,chosen_action,note,r6_review_json FROM turns WHERE run_id=? ORDER BY id''', (run_id,)).fetchall()
    return [{'id': row[0], 'created_at': row[1],
             'state': json.loads(row[2]), 'options': json.loads(row[3]),
             'rankings': json.loads(row[4]), 'chosen_action': row[5], 'note': row[6],
             'r6_review': json.loads(row[7] or '{}')}
            for row in rows]


def export_json(conn: sqlite3.Connection, path: Path) -> None:
    runs = []
    for r in reversed(list_runs(conn)):
        runs.append({**r, 'turns': list_turns(conn, r['id'])})
    doc = {'schema_version': SCHEMA_VERSION, 'disclaimer': '데이터는 사용자가 입력한 관측값과 실험용 추천 결과입니다.',
           'runs': runs}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')


def export_csv(conn: sqlite3.Connection, path: Path) -> None:
    fields = ['run_id', 'created_at', 'event', 'distance', 'style', 'character',
              'turn_label', 'remaining_turns', 'energy', 'island_tickets',
              'development_points', *('current_' + name for name in ('speed', 'stamina', 'power', 'guts', 'wisdom')),
              'recommended', 'chosen', 'recommendation_score', 'note', 'outcome_status', 'outcome_reason']
    korean_stats = ('스피드', '스태미나', '파워', '근성', '지능')
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for run in reversed(list_runs(conn)):
            prof = run['profile']
            for item in list_turns(conn, run['id']):
                state = item['state']
                rankings = item['rankings']
                values = [state.get('stats', {}).get(s, 0) for s in korean_stats]
                w.writerow(dict(zip(fields, [run['id'], item['created_at'],
                    prof.get('event', ''), prof.get('distance', ''), prof.get('style', ''),
                    prof.get('character', ''), state['turn_label'], state['remaining_turns'],
                    state['energy'], state['island_tickets'], state['development_points'],
                    *values, rankings[0]['name'] if rankings else '', item['chosen_action'],
                    rankings[0]['score'] if rankings else '', item['note'],
                    run.get('outcome', {}).get('status', '진행중'), run.get('outcome', {}).get('reason', '')])))
