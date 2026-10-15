"""R3 audit of *observations*, not a win predictor or a learned model.

The saved snapshot is taken before the player's action. Difference to the next
snapshot is observational and may include races, events and other changes.
Never use such a difference as a causal effect or a learned optimal label.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from storage import list_runs, list_turns
from uma_core import STATS, Action, action_is_observed

MIN_TREND_SAMPLES = 5
VALID_EVENTS = {'챔피언스 미팅', '리그 오브 히어로즈'}
VALID_PURPOSES = {'champ_main': '챔피언스 미팅', 'loh_main': '리그 오브 히어로즈'}


def _number(v, lower=0, upper=1000000):
    if isinstance(v, bool):
        return None
    try:
        val = float(v)
    except (ValueError, TypeError, OverflowError):
        return None
    return val if math.isfinite(val) and lower <= val <= upper else None


def _int(v):
    n = _number(v)
    if n is None or not n.is_integer():
        return None
    return int(n)


def _percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    idx = (len(values) - 1) * q
    lo = math.floor(idx)
    hi = math.ceil(idx)
    return values[lo] + (values[hi] - values[lo]) * (idx - lo)


def run_audit(conn, run_id: int) -> dict:
    """Describe past decisions and goal gap without asserting optimality."""
    run = next((r for r in list_runs(conn) if r['id'] == run_id), None)
    if run is None:
        raise ValueError('육성 기록을 찾지 못했습니다.')
    records = list_turns(conn, run_id)
    prof = run['profile']
    contrasts = []
    comparable = 0
    agreeing = 0
    errors = []
    seen_states = []
    increments = {name: [] for name in STATS}
    stats_transitions = []
    for t in records:
        state = t.get('state', {})
        if not isinstance(state, dict):
            errors.append(f"턴 #{t['id']}: 저장된 상태 자료가 잘못되었습니다.")
            continue
        remaining = _int(state.get('remaining_turns'))
        vals = {s: _int((state.get('stats') or {}).get(s)) for s in STATS}
        if remaining is None or any(v is None for v in vals.values()):
            errors.append(f"턴 #{t['id']}: 남은 턴/현재 스탯 자료가 불완전합니다.")
            continue
        seen_states.append((t['id'], remaining, vals, state))
        chosen = t.get('chosen_action', '')
        opts = t.get('options', {})
        if not isinstance(opts, dict):
            continue
        observed = {}
        for name, raw in opts.items():
            try:
                obj = Action(**raw)
                if action_is_observed(obj):
                    observed[name] = obj
            except (TypeError, ValueError):
                continue
        # Compare with *saved* recommendation snapshot, so changes to weight
        # formulas do not retroactively redefine what user saw at that time.
        candidates = t.get('rankings', [])
        names = {c.get('name') for c in candidates if isinstance(c, dict)}
        if len(observed) < 2 or chosen not in observed or not candidates or chosen not in names:
            continue
        top = candidates[0].get('name')
        if top not in observed:
            continue
        comparable += 1
        if chosen == top:
            agreeing += 1
        contrasts.append({'turn_id': t['id'], 'turn_label': state.get('turn_label', ''),
                          'model_suggestion': top, 'human_chosen': chosen,
                          'agreed': chosen == top})
    # Only consecutive snapshots that are one turn apart. Even these deltas are
    # observational: they cannot be attributed to the preceding chosen action.
    for first, second in zip(seen_states, seen_states[1:]):
        first_id, prev_remaining, prev_stats, _ = first
        next_id, next_remaining, next_stats, _ = second
        if prev_remaining - next_remaining != 1:
            continue
        diff = {s: next_stats[s] - prev_stats[s] for s in STATS}
        # A negative jump can be a transcription error, skill conversion, etc.
        # Do not use this snapshot for a positive growth benchmark.
        if any(n < 0 or n > 1000 for n in diff.values()):
            errors.append(f'턴 #{first_id}→#{next_id}: 스탯 급변/감소로 추세 통계 제외')
            continue
        for s, value in diff.items():
            increments[s].append(value)
        stats_transitions.append({'from_turn_id': first_id, 'to_turn_id': next_id,
                                  'delta_stats': diff,
                                  'quality': 'manual_snapshots_noncausal'})
    last = seen_states[-1] if seen_states else None
    goals = []
    for s in STATS:
        target = _int((prof.get('target_stats') or {}).get(s))
        current = last[2][s] if last else None
        remaining = last[1] if last else None
        if target is None or current is None or remaining is None:
            goals.append({'stat': s, 'target': target, 'current': current,
                          'gap': None, 'required_per_turn': None, 'observed_median': None,
                          'observed_p75': None, 'sample_count': len(increments[s]), 'flag': '입력 부족'})
            continue
        gap = max(0, target - current)
        need = round(gap / remaining, 2) if remaining > 0 else (0.0 if gap == 0 else None)
        n = len(increments[s])
        base = round(median(increments[s]), 2) if n >= MIN_TREND_SAMPLES else None
        p75 = round(_percentile(increments[s], .75), 2) if n >= MIN_TREND_SAMPLES else None
        flag = ('달성' if gap == 0 else
                '종료·미달' if remaining == 0 else
                '기록 부족' if n < MIN_TREND_SAMPLES else
                '추격 부담 점검' if need > max(1, p75) * 1.5 else '진행 확인')
        goals.append({'stat': s, 'target': target, 'current': current,
                      'gap': gap, 'required_per_turn': need, 'observed_median': base,
                      'observed_p75': p75, 'sample_count': n, 'flag': flag})
    if not last:
        status = '기록 부족'
    elif len(stats_transitions) < MIN_TREND_SAMPLES:
        status = '도축 판단 보류 · 연속 턴 자료 부족'
    elif any(g['flag'] == '추격 부담 점검' for g in goals):
        status = '목표 추격 부담 점검 · 포기 근거 아님'
    else:
        status = '추가 기록 권장 · 실전 성능 미확인'
    return {
        'report_version': 'R3-observational-v1', 'run_id': run_id,
        'event': prof.get('event', ''), 'scenario': prof.get('scenario', ''),
        'total_recorded_turns': len(records), 'consecutive_observed_intervals': len(stats_transitions),
        'comparison_turns': comparable, 'heuristic_agreement_turns': agreeing,
        'heuristic_agreement_ratio': (round(agreeing / comparable, 3) if comparable else None),
        'outcome': run.get('outcome', {}), 'status': status, 'targets': goals,
        'decision_comparisons': contrasts, 'snapshot_deltas': stats_transitions,
        'warnings': errors,
        'interpretation': ('추천 일치율은 정답률·승률이 아닙니다. 연속 턴 사이 상승량은 단순 관측치이며 '
                           '선택의 인과효과가 아닙니다. 도축을 자동 권유하지 않습니다.'),
        'model_status': 'RULE_BASED_UNVALIDATED / ML_NOT_TRAINED',
    }


def corpus_audit(conn) -> dict:
    """Describe how many recorded runs are available by actual outcome."""
    runs = list_runs(conn)
    statuses = Counter((r.get('outcome', {}) or {}).get('status', '진행중') for r in runs)
    events = Counter((r['profile'].get('event', '미확인')) for r in runs)
    completed_with_turns = sum(1 for r in runs if r['turn_count'] and (r.get('outcome') or {}).get('status') == '육성 완료')
    abandoned_with_turns = sum(1 for r in runs if r['turn_count'] and (r.get('outcome') or {}).get('status') == '도축/중단')
    return {'runs': len(runs), 'recorded_turns': sum(r['turn_count'] for r in runs),
            'outcomes': dict(statuses), 'events': dict(events),
            'completed_with_turns': completed_with_turns,
            'abandoned_with_turns': abandoned_with_turns,
            'warning': '중도 중단한 육성의 미관측 미래 결과는 알 수 없습니다. 성공/실패 원인을 단정하지 마세요.'}


def _hash_ok(path, digest):
    try:
        p = Path(path)
        return p.is_file() and bool(digest) and hashlib.sha256(p.read_bytes()).hexdigest() == digest
    except (ValueError, TypeError, OSError):
        return False


def _known_video_sources(source_file: Path | None = None) -> dict:
    source_file = source_file or (Path(__file__).resolve().parent / 'research' / 'jp_post_patch_2025' / 'sources.csv')
    if not source_file.is_file():
        return {}
    with source_file.open('r', newline='', encoding='utf-8-sig') as f:
        return {row['source_id']: row for row in csv.DictReader(f)
                if row.get('source_kind', '').startswith('video_')}


def audit_verified_video_turns(path: Path, validate_media=True, source_file: Path | None = None) -> dict:
    """Strict R2 audit; complete flags alone are NOT sufficient evidence."""
    path = Path(path)
    if not path.is_file():
        return {'found': False, 'total': 0, 'qualified_main_run_turns': 0,
                'excluded': {}, 'candidates': [], 'ml_ready': False}
    total = 0
    excluded = Counter()
    sources = _known_video_sources(source_file)
    candidates = []
    seen = set()
    with path.open('r', newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            total += 1
            key = row.get('annotation_id', '')
            if not key or key in seen:
                excluded['duplicate_or_missing_id'] += 1
                continue
            seen.add(key)
            source = sources.get(row.get('source_id', ''))
            if (not source or not source.get('published_date') or source['published_date'] < '2025-07-01' or
                source.get('url') != row.get('source_url') or
                len(row.get('patch_evidence', '').strip()) < 12):
                excluded['unverified_source_or_patch_evidence'] += 1
                continue
            purpose = row.get('run_purpose', '')
            if (purpose not in VALID_PURPOSES or row.get('competition') != VALID_PURPOSES[purpose] or
                source.get('scope') in ('general_score', 'loh_factor', 'team_stadium_only')):
                excluded['not_champ_or_loh_main'] += 1
                continue
            if (row.get('scenario_id') != 'island_post_patch_v1' or row.get('server') != 'JP' or
                row.get('patch_status') != 'post_2025_06_30_confirmed'):
                excluded['unconfirmed_patch'] += 1
                continue
            if (row.get('review_grade') != 'complete' or row.get('observed_choice') != 'true' or
                row.get('observed_result') != 'true'):
                excluded['not_complete'] += 1
                continue
            vals = [_int(row.get(k)) for k in ('energy','speed','stamina','power','guts','wisdom')]
            if any(v is None for v in vals):
                excluded['missing_stats'] += 1
                continue
            try:
                options = json.loads(row.get('alternatives_json', ''))
                result = json.loads(row.get('post_action_json', ''))
                if not isinstance(options, dict) or len(options) < 2 or not isinstance(result, dict):
                    raise ValueError('bad options')
                if row.get('chosen_action') not in options:
                    raise ValueError('action not in options')
            except (TypeError, ValueError):
                excluded['invalid_options'] += 1
                continue
            if validate_media and not (_hash_ok(row.get('frame_before_path'), row.get('frame_before_sha256')) and
                                       _hash_ok(row.get('frame_after_path'), row.get('frame_after_sha256'))):
                excluded['missing_or_changed_frame'] += 1
                continue
            # Do not put raw local image paths or source video frames into export.
            candidates.append({'annotation_id': key, 'source_id': row.get('source_id',''),
                               'case_id': row.get('case_id',''),
                               'run_purpose': purpose, 'competition': row['competition'],
                               'character': row.get('character',''),
                               'turn_label': row.get('turn_label',''),
                               'stats': dict(zip(('energy','speed','stamina','power','guts','wisdom'), vals)),
                               'alternatives': options, 'human_action': row.get('chosen_action'),
                               'observed_outcome': result,
                               'quality': 'verified_human_choice_not_optimal_label'})
    return {'found': True, 'total': total, 'qualified_main_run_turns': len(candidates),
            'excluded': dict(excluded), 'candidates': candidates, 'ml_ready': False,
            'warning': ('실제 플레이어 선택과 그 후 결과만으로 최적 행동의 정답을 만들 수 없습니다. '
                        '같은 육성/영상 그룹을 나누어 평가해야 합니다.')}


def export_r3_report(report: dict, target: Path):
    Path(target).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def export_verified_candidates_csv(audit: dict, target: Path):
    """No unverified video rows. Empty corpus -> header-only CSV."""
    fields = ['annotation_id','source_id','case_id','run_purpose','competition',
              'character','turn_label','stats_json','alternatives_json','human_action',
              'observed_outcome_json','quality']
    with Path(target).open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for item in audit['candidates']:
            writer.writerow({'annotation_id':item['annotation_id'], 'source_id':item['source_id'],
                             'case_id':item['case_id'], 'run_purpose':item['run_purpose'],
                             'competition':item['competition'],'character':item['character'],
                             'turn_label':item['turn_label'],
                             'stats_json':json.dumps(item['stats'],ensure_ascii=False),
                             'alternatives_json':json.dumps(item['alternatives'],ensure_ascii=False),
                             'human_action':item['human_action'],
                             'observed_outcome_json':json.dumps(item['observed_outcome'],ensure_ascii=False),
                             'quality':item['quality']})
