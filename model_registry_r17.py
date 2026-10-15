"""R17 offline research model registry.

R16 predicts *human behavior*, not best actions. A champion is a research
comparison baseline only; it is NEVER connected to game recommendations.
Model promotion uses a shared VALIDATION set, never TEST.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml_engine_r16 import (_metrics, cohort_key, read_model, save_model,
                           validate_model, _validate_row, SPLITS)

SCHEMA = 'uma-r17-research-registry-v1'
SCOPE_FIELDS = ('scenario_id', 'server', 'patch_version', 'event')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _utc():
    return datetime.now(timezone.utc).isoformat()


def default_registry_root():
    home = os.environ.get('LOCALAPPDATA')
    return (Path(home) / 'UmaTrainerKR' if home else Path.home() / '.uma_trainer_kr') / 'r17_models'


def _key(scope):
    if not isinstance(scope, dict) or any(not isinstance(scope.get(k), str) or not scope[k]
                                           for k in SCOPE_FIELDS):
        raise ValueError('서버/시나리오/패치/대회 범위가 누락됐습니다.')
    return _digest([scope[k] for k in SCOPE_FIELDS])


def _write_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(prefix='.r17_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _empty():
    return {'schema': SCHEMA, 'revision': 0, 'entries': {}, 'scopes': {}, 'events': []}


def read_registry(root):
    root = Path(root)
    file = root / 'registry.json'
    if not file.exists():
        return _empty()
    if file.stat().st_size > 4_000_000:
        raise ValueError('모델 등록부 크기 초과')
    data = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('R17 등록부 형식 오류')
    if not isinstance(data.get('entries'), dict) or not isinstance(data.get('scopes'), dict):
        raise ValueError('R17 등록부가 손상됐습니다.')
    check = _digest({k: v for k, v in data.items() if k != 'sha256'})
    if data.get('sha256') != check:
        raise ValueError('R17 등록부 무결성 오류')
    if len(data['entries']) > 2000:
        raise ValueError('등록 가능한 모델 수를 초과했습니다.')
    for model_id, meta in data['entries'].items():
        if not isinstance(model_id, str) or len(model_id) != 64 or not all(c in '0123456789abcdef' for c in model_id):
            raise ValueError('부적절한 모델 ID')
        # Validate every immutable snapshot, including champions referenced by rollbacks.
        model = read_model(root / 'models' / (model_id + '.json'))
        if model['model_sha256'] != model_id or model['scope'] != meta['scope'] or model['dataset_id_sha256'] != meta['dataset_id_sha256']:
            raise ValueError('등록된 모델 스냅샷이 훼손됐습니다.')
    for sid, state in data['scopes'].items():
        if sid != _key(state['scope']):
            raise ValueError('모델 범위 키 오류')
        if any(mid not in data['entries'] or _key(data['entries'][mid]['scope']) != sid for mid in state['history']):
            raise ValueError('다른 시나리오 모델이 이력에 혼입됐습니다.')
        if state['history'] and state['champion'] != state['history'][-1]:
            raise ValueError('챔피언 및 복원 이력 충돌')
    return data


def _store(root, data):
    data['revision'] += 1
    data['sha256'] = _digest({k: v for k, v in data.items() if k != 'sha256'})
    _write_atomic(Path(root) / 'registry.json', data)


def register_model(root, model):
    validate_model(model)
    root = Path(root)
    mid = model['model_sha256']
    data = read_registry(root)
    if mid in data['entries']:
        return mid
    path = root / 'models' / (mid + '.json')
    if path.exists():
        old = read_model(path)
        if old != model:
            raise ValueError('동일 ID의 모델 파일 충돌')
    else:
        save_model(model, path)
    data['entries'][mid] = {'scope': model['scope'], 'dataset_id_sha256': model['dataset_id_sha256'],
                             'feature_schema': model['feature_schema'], 'registered_at': _utc(),
                             'task': model['learning_task']}
    sid = _key(model['scope'])
    data['scopes'].setdefault(sid, {'scope': model['scope'], 'champion': None, 'history': []})
    data['events'].append({'event': 'register', 'model_id': mid, 'timestamp': _utc()})
    _store(root, data)
    return mid


def _validation_rows(rows, candidate):
    scope = tuple(candidate['scope'][k] for k in SCOPE_FIELDS)
    subset = [r for r in rows if cohort_key(r) == scope]
    if not subset or {r['split'] for r in subset} != set(SPLITS):
        raise ValueError('동일 코호트의 학습·검증·시험 구분 자료가 모두 필요합니다.')
    ids = set()
    groups_by_split = {}
    for r in subset:
        _validate_row(r, r['split'])
        if r['example_id'] in ids:
            raise ValueError('동일 학습 예제 중복')
        ids.add(r['example_id'])
        group = r['provenance_group_hash']
        if group in groups_by_split and groups_by_split[group] != r['split']:
            raise ValueError('출처 그룹이 학습/검증/시험에 중복됨')
        groups_by_split[group] = r['split']
    dataset_id = hashlib.sha256('\n'.join(sorted(r['example_id'] for r in subset)).encode()).hexdigest()
    if dataset_id != candidate['dataset_id_sha256']:
        raise ValueError('학습 당시 자료 ID와 현재 검수 자료가 다릅니다.')
    splits = {s: {r['provenance_group_hash'] for r in subset if r['split'] == s} for s in SPLITS}
    if any(splits[a] & splits[b] for a, b in (('train','validation'),('train','test'),('validation','test'))):
        raise ValueError('출처 그룹이 학습·검증·시험에 중복됐습니다.')
    val = [r for r in subset if r['split'] == 'validation']
    if len(val) < 5 or len(splits['validation']) < 2:
        raise ValueError('독립 검증 자료가 부족합니다.')
    return val, _digest([{k: r[k] for k in ('example_id', 'features', 'observed_options', 'label', 'split')}
                         for r in sorted(val, key=lambda r: r['example_id'])])


def compare_candidate(root, candidate_id, reviewed_rows):
    """Evaluate on SAME validation data. Test is never used for selection."""
    data = read_registry(root)
    if candidate_id not in data['entries']:
        raise ValueError('등록되지 않은 모델')
    new = read_model(Path(root) / 'models' / (candidate_id + '.json'))
    val, eval_hash = _validation_rows(reviewed_rows, new)
    sid = _key(new['scope'])
    cur_id = data['scopes'][sid]['champion']
    champion = read_model(Path(root) / 'models' / (cur_id + '.json')) if cur_id else None
    if champion and (champion['dataset_id_sha256'] != new['dataset_id_sha256'] or
                     champion['feature_schema'] != new['feature_schema']):
        return {'eligible': False, 'reason': '서로 다른 데이터셋/특징 버전은 공통 독립 홀드아웃이 없어 비교 보류',
                'candidate_id': candidate_id, 'champion_id': cur_id, 'validation_sha256': eval_hash}
    cand = _metrics(val, new['weights'], new['majority_action'])
    old = _metrics(val, champion['weights'], champion['majority_action']) if champion else None
    # No promotion if below human-action majority baseline. Never confuse this with optimal behavior.
    acceptable = (cand['accuracy'] >= cand['majority_baseline_accuracy'] and
                  cand['log_loss'] < 2.5)
    if old:
        acceptable = (acceptable and cand['log_loss'] < old['log_loss'] - 0.005 and
                      cand['accuracy'] >= old['accuracy'] - 0.01 and
                      cand['macro_f1'] >= old['macro_f1'] - 0.01)
    if cur_id == candidate_id:
        acceptable = False
    return {'eligible': acceptable,
            'reason': ('검증 기준 충족(연구용 등록만 가능)' if acceptable else '검증 성능 기준 미달 또는 이미 기준 모델'),
            'candidate_id': candidate_id, 'champion_id': cur_id,
            'validation_sha256': eval_hash, 'candidate': cand, 'champion': old,
            'warning': '사람 행동의 모방 지표이며 최적 행동·승률·도축 확률을 뜻하지 않습니다.'}


def promote_model(root, candidate_id, rows, *, expected_revision=None):
    # Explicit user action only; caller must use a UI button or intentional CLI command.
    root = Path(root)
    data = read_registry(root)
    if expected_revision is not None and data['revision'] != expected_revision:
        raise ValueError('등록부가 변경됐습니다. 다시 검토하세요.')
    report = compare_candidate(root, candidate_id, rows)
    if not report['eligible']:
        raise ValueError('모델 승격 보류: ' + report['reason'])
    latest = read_registry(root)
    if latest['revision'] != data['revision']:
        raise ValueError('모델 비교 도중 등록부가 변경됐습니다. 다시 검토하세요.')
    data = latest
    sid = _key(data['entries'][candidate_id]['scope'])
    state = data['scopes'][sid]
    previous = state['champion']
    state['history'].append(candidate_id)
    state['champion'] = candidate_id
    data['events'].append({'event': 'promote_research_champion', 'model_id': candidate_id,
                           'previous_model_id': previous, 'validation_sha256': report['validation_sha256'],
                           'timestamp': _utc()})
    _store(root, data)
    return report


def rollback_model(root, scope, *, expected_revision=None):
    data = read_registry(root)
    if expected_revision is not None and data['revision'] != expected_revision:
        raise ValueError('등록부가 변경됐습니다. 다시 검토하세요.')
    sid = _key(scope)
    state = data['scopes'].get(sid)
    if not state or len(state['history']) < 2:
        raise ValueError('복원할 이전 연구용 모델이 없습니다.')
    old = state['history'].pop()
    restored = state['history'][-1]
    state['champion'] = restored
    data['events'].append({'event': 'rollback_research_champion', 'previous_model_id': old,
                           'model_id': restored, 'timestamp': _utc()})
    _store(root, data)
    return restored
