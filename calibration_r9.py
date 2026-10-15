"""R9: evidence-gated empirical comparison of *displayed* training bonuses.

Not an official Umamusume game formula, ML win-rate model or future-roll
simulator. No distribution or fitted number is provided without enough
independent, manually verified post-patch game observations.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

STATS = ('스피드', '스태미나', '파워', '근성', '지능')
FACILITIES = STATS + ('해변의 집',)
PURPOSES = ('챔피언스 미팅', '리그 오브 히어로즈')
SERVERS = {'JP': 'JP_after_2025_06_30_2320', 'KR': 'KR_post_patch_confirmed'}
SOURCES = ('original_capture', 'reviewed_video_frame')
TRAININGS = STATS + ('섬 트레이닝',)
CSV_SCHEMA = 'uma_r9_empirical_observations_v1'
FIELDS = ('sample_id', 'run_id', 'source_type', 'source_url', 'frame_sha256',
          'captured_date', 'server', 'patch_status', 'scenario', 'purpose',
          'phase', 'training', 'character', 'support_deck_key', 'context_key',
          'facility_levels_json', 'facility_routes_json', 'friendship_counts_json',
          'verified', 'synthetic', 'g_speed', 'g_stamina', 'g_power', 'g_guts',
          'g_wisdom', 'skill_points', 'reviewer_note')
NUMERIC = ('g_speed', 'g_stamina', 'g_power', 'g_guts', 'g_wisdom', 'skill_points')
MIN_RUNS = 8
MIN_SAMPLES = 10


def empty_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as out:
        csv.DictWriter(out, fieldnames=FIELDS).writeheader()


def _exact_json_dict(value, expected_names, lo, hi):
    try:
        obj = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise ValueError('JSON 객체 형식이 올바르지 않습니다.') from None
    if not isinstance(obj, dict) or set(obj) != set(expected_names):
        raise ValueError('JSON 객체에는 해당 항목 전체가 필요합니다.')
    if any(type(v) is not int or v < lo or v > hi for v in obj.values()):
        raise ValueError('JSON 시설/우정 수치 범위를 확인하세요.')
    return obj


def validate_row(row: Mapping) -> dict:
    """Reject unsigned, pre-patch, demo, incomplete and mixed-purpose labels."""
    if not isinstance(row, Mapping):
        raise ValueError('행의 객체 형식이 올바르지 않습니다.')
    errors = []
    if any(key not in row for key in FIELDS):
        raise ValueError('필수 데이터 열이 빠져 있습니다: ' + ', '.join(k for k in FIELDS if k not in row))
    data = {key: str(row.get(key, '')).strip() for key in FIELDS}
    for key in ('sample_id', 'run_id', 'source_type', 'frame_sha256', 'captured_date',
                'server', 'patch_status', 'scenario', 'purpose', 'phase', 'training',
                'character', 'support_deck_key', 'context_key'):
        if not data[key]:
            errors.append(f'{key} 비어 있음')
    if data['server'] not in SERVERS or SERVERS.get(data['server']) != data['patch_status']:
        errors.append('서버별 패치 확인 상태가 잘못되었음')
    if data['source_type'] not in SOURCES:
        errors.append('원본 캡처 또는 검수 영상 프레임이어야 함')
    if data['source_type'] == 'reviewed_video_frame' and not data['source_url'].startswith(('https://', 'http://')):
        errors.append('영상 프레임은 출처 URL 필수')
    if len(data['frame_sha256']) != 64 or any(ch not in '0123456789abcdef' for ch in data['frame_sha256'].lower()):
        errors.append('검수한 원본 프레임 SHA256 해시 필수')
    if data['verified'].lower() != 'true' or data['synthetic'].lower() != 'false':
        errors.append('검수 완료 실측만 허용 (synthetic=false, verified=true)')
    if data['scenario'] != 'island_post_patch_v1' or data['purpose'] not in PURPOSES:
        errors.append('수정 후 무인도 챔미/리오히 목적만 허용')
    if data['training'] not in TRAININGS:
        errors.append('인식할 수 없는 훈련 종류')
    try:
        day = date.fromisoformat(data['captured_date'])
        if data['server'] == 'JP' and day < date(2025, 7, 1):
            errors.append('일본 서버 2025-07-01 이후 날짜만 허용 (수정 당일 혼동 방지)')
        if day > date.today():
            errors.append('미래 날짜 불가')
    except ValueError:
        errors.append('날짜는 YYYY-MM-DD 형식')
    try:
        levels = _exact_json_dict(data['facility_levels_json'], FACILITIES, 0, 5)
        if levels['해변의 집'] > 3:
            errors.append('해변의 집 최대 3레벨')
        friends = _exact_json_dict(data['friendship_counts_json'], STATS, 0, 6)
        routes = json.loads(data['facility_routes_json'])
        if not isinstance(routes, dict) or set(routes) != set(FACILITIES):
            errors.append('분기 JSON에 6개 시설 모두 필요')
        elif any(routes[s] != ('미선택' if levels[s] < 3 or s == '해변의 집' else routes[s])
                 or routes[s] not in (('본능', '기교') if levels[s] >= 3 and s != '해변의 집' else ('미선택',))
                 for s in FACILITIES):
            errors.append('시설 Lv3 이상 분기 선택과 실제 수준이 일치하지 않음')
    except (ValueError, TypeError) as ex:
        errors.append('시설·우정·분기 데이터 형식 오류: '+str(ex))
        levels = friends = routes = None
    for key in NUMERIC:
        try:
            value = int(data[key])
            if not 0 <= value <= 500:
                raise ValueError
            data[key] = value
        except (TypeError, ValueError):
            errors.append(f'{key}는 0~500 정수')
    if errors:
        raise ValueError('; '.join(errors))
    data['facility_levels_json'] = json.dumps(levels, sort_keys=True, ensure_ascii=False)
    data['facility_routes_json'] = json.dumps(routes, sort_keys=True, ensure_ascii=False)
    data['friendship_counts_json'] = json.dumps(friends, sort_keys=True, ensure_ascii=False)
    data['frame_sha256'] = data['frame_sha256'].lower()
    data['verified'] = 'true'
    data['synthetic'] = 'false'
    return data


def group_key(row: Mapping) -> str:
    """Strictly identical contexts; prevents training across servers/decks/phases."""
    names = ('server', 'patch_status', 'scenario', 'purpose', 'phase', 'training',
             'character', 'support_deck_key', 'context_key',
             'facility_levels_json', 'facility_routes_json', 'friendship_counts_json')
    return hashlib.sha256(json.dumps([row[k] for k in names], ensure_ascii=False,
                        separators=(',', ':')).encode('utf-8')).hexdigest()


@dataclass
class Audit:
    total_rows: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicate: int = 0
    rejected_reasons: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list, repr=False)


def audit_csv(path: Path) -> Audit:
    output = Audit()
    if not Path(path).is_file():
        raise FileNotFoundError('검수 CSV 파일을 찾을 수 없습니다: ' + str(path))
    with Path(path).open('r', newline='', encoding='utf-8-sig') as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None or set(FIELDS) - set(reader.fieldnames):
            raise ValueError('R9 자료 CSV 헤더가 누락되었거나 올바르지 않습니다.')
        seen_ids, seen_frames = set(), set()
        for idx, raw in enumerate(reader, 2):
            output.total_rows += 1
            try:
                clean = validate_row(raw)
                # Multiple training choices in one screenshot are possible; training is part of key.
                identity = (clean['server'], clean['frame_sha256'], clean['training'])
                if clean['sample_id'] in seen_ids or identity in seen_frames:
                    output.duplicate += 1
                    output.rejected += 1
                    continue
                seen_ids.add(clean['sample_id'])
                seen_frames.add(identity)
                output.observations.append(clean)
                output.accepted += 1
            except ValueError as exc:
                output.rejected += 1
                if len(output.rejected_reasons) < 50:
                    output.rejected_reasons.append(f'{idx}행: {str(exc)[:250]}')
    return output


def _percentile(values: list[int], fraction: float) -> float:
    vals = sorted(values)
    pos = (len(vals)-1)*fraction
    a, b = math.floor(pos), math.ceil(pos)
    return vals[a] + (vals[b]-vals[a])*(pos-a)


@dataclass
class Estimate:
    status: str
    compared_samples: int
    distinct_runs: int
    source: str
    context_id: str
    stat_intervals: dict[str, dict] = field(default_factory=dict)
    skill_points: dict = field(default_factory=dict)
    leave_one_run_out_mae: dict[str, float] = field(default_factory=dict)
    caution: str = ''
    verified_optimal: bool = False
    trained_ml_model: bool = False


def estimate_from_samples(rows: list[dict], target: Mapping) -> Estimate:
    target = validate_row(target)
    group = group_key(target)
    matches = []
    seen_source_training = set()
    for raw in rows:
        try:
            r = validate_row(raw)
        except ValueError:
            continue  # Never permit unreviewed/synthetic observations into a numerical comparison.
        identity = (r['server'], r['frame_sha256'], r['training'])
        if identity in seen_source_training:
            continue
        seen_source_training.add(identity)
        if group_key(r) == group and r['run_id'] != target['run_id']:
            matches.append(r)
    runs = {r['run_id'] for r in matches}
    result = Estimate('표본 부족 · 예측 보류', len(matches), len(runs),
                      '독립 육성 기록 · 엄격한 동일조건 비교', group,
                      caution='일본/한국 서버, 대회, 카드 편성, 시설/우정 상태 등 다른 데이터는 섞지 않습니다.')
    if len(matches) < MIN_SAMPLES or len(runs) < MIN_RUNS:
        return result
    # Distinct-run holdout: group leave-one-run-out, not random turn split.
    for col in NUMERIC:
        series = [r[col] for r in matches]
        by_run = defaultdict(list)
        for r in matches:
            by_run[r['run_id']].append(r[col])
        errors = []
        for run, held in by_run.items():
            others = [v for other, values in by_run.items() if other != run for v in values]
            if others:
                errors += [abs(statistics.mean(others)-v) for v in held]
        if not errors:
            return result
        result.leave_one_run_out_mae[col] = round(statistics.mean(errors), 2)
        estimate = {'median': round(statistics.median(series), 1),
                    'p10': round(_percentile(series, .10), 1),
                    'p90': round(_percentile(series, .90), 1)}
        if col == 'skill_points':
            result.skill_points = estimate
        else:
            result.stat_intervals[col] = estimate
    # P10-P90 are *observed* ranges, not confidence intervals or probabilities.
    result.status = '유사 조건 관찰 범위 제공 (실험)'
    result.caution = ('관찰 표본의 중앙값과 10~90백분위 범위입니다. 미래 훈련값·보너스 공식·'
                      '고점 달성률·승률에 대한 보증 또는 검증된 ML 예측이 아닙니다.')
    return result


def atomic_export_json(path: Path, audit: Audit, estimates: list[Estimate]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {'schema': CSV_SCHEMA, 'verified_optimal': False, 'trained_ml_model': False,
               'generated_utc': datetime.now().astimezone().isoformat(),
               'audit': {key: value for key, value in asdict(audit).items() if key != 'observations'},
               'estimates': [asdict(x) for x in estimates]}
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', prefix='.uma_r9_',
                                         encoding='utf8', dir=dest.parent, delete=False) as fp:
            name = fp.name
            json.dump(payload, fp, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(name, dest)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
