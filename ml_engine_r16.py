"""R16: local, dependency-free contextual softmax learner for *human behavior*.

This NEVER claims to predict the best move, winning probability or final score.
Models and metrics are partitioned by (scenario, server, patch, event).
Pure JSON model artifacts; no pickle or executable model loading.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from learning_data_r15 import MIN_TRAIN_GROUPS, MIN_TRAIN_TURNS, SCHEMA
from uma_core import STATS, TRAININGS
from scenario_ml_features_r16 import extract_ml_signals

MODEL_SCHEMA = 'uma-r16-human-behavior-softmax-v1'
FEATURE_SCHEMA = 'uma-r16-pre-action-option-v1'
SPLITS = ('train', 'validation', 'test')
MIN_EVAL_GROUPS = 2
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_ROWS = 100_000
STYLES = ('도주', '선행', '선입', '추입')
DISTANCES = ('단거리', '마일', '중거리', '장거리')
MOODS = ('최악', '나쁨', '보통', '좋음', '최상')
# fixed vocabulary; unknown actions rejected, never silently trained as zero features
FEATURES = (('bias', 'energy', 'remaining_turns', 'skill_points', 'scenario_signal_1',
             'scenario_signal_2', 'friend_types', 'bond_gain', 'failure_percent',
             'energy_delta', 'option_skill_points', 'option_development_points',
             'current_deficit_mean', 'target_gap_for_action', 'scenario_signal_3',
             'scenario_signal_4')
            + tuple('act_' + s for s in TRAININGS)
            + tuple('gain_' + s for s in STATS)
            + tuple('gap_' + s for s in STATS)
            + tuple('style_' + s for s in STYLES)
            + tuple('distance_' + s for s in DISTANCES)
            + tuple('mood_' + s for s in MOODS))


def _number(value, lo, hi, field, *, default=None):
    if value is None and default is not None:
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'비정상/누락 값: {field} (허용 {lo}~{hi})')
    return float(value)


def cohort_key(rec):
    f = rec['features']
    return (rec['scenario_id'], rec['server'], rec['patch_version'], f['event'])


def _vec(rec, name):
    f = rec['features']
    opt = rec['observed_options'][name]
    sf = rec['scenario_features']
    remaining = _number(f.get('remaining_turns'), 0, 150, 'remaining_turns')
    energy = _number(f.get('energy'), 0, 200, 'energy')
    sp = _number(f.get('skill_points'), 0, 100000, 'skill_points', default=0)
    sig = extract_ml_signals(rec['scenario_id'], sf)
    current = f.get('stats') or {}
    target = f.get('target_stats') or {}
    gaps = {}
    for s in STATS:
        value = _number(current.get(s), 0, 10000, 'stats.'+s)
        t = _number(target.get(s), 1, 10000, 'target_stats.'+s)
        gaps[s] = max(-1., min(1., (t-value)/t))
    gains = opt.get('gains') or {}
    vals = dict.fromkeys(FEATURES, 0.0)
    vals.update(bias=1., energy=energy/100, remaining_turns=remaining/100,
                skill_points=min(sp/3000, 3.), scenario_signal_1=sig[0],
                scenario_signal_2=sig[1],
                friend_types=_number(opt.get('friend_types'), 0, 6, 'friend_types', default=0)/5,
                bond_gain=_number(opt.get('bond_gain'), 0, 500, 'bond_gain', default=0)/100,
                failure_percent=_number(opt.get('failure_percent'), 0, 100, 'failure_percent', default=0)/100,
                energy_delta=_number(opt.get('energy_delta'), -150, 150, 'energy_delta', default=0)/100,
                option_skill_points=_number(opt.get('skill_points'), 0, 10000, 'option_skill_points', default=0)/150,
                option_development_points=_number(opt.get('development_points'), 0, 10000, 'option_development_points', default=0)/150,
                current_deficit_mean=sum(gaps.values())/5,
                target_gap_for_action=gaps.get(name, 0.0),
                scenario_signal_3=sig[2],
                scenario_signal_4=sig[3])
    vals['act_'+name] = 1.
    for s in STATS:
        vals['gain_'+s] = _number(gains.get(s), 0, 1000, 'gains.'+s, default=0)/100
        vals['gap_'+s] = gaps[s]
    for prefix, value, choices in (('style_', f.get('style'), STYLES),
                                   ('distance_', f.get('distance'), DISTANCES),
                                   ('mood_', f.get('mood'), MOODS)):
        if value is not None and value not in choices:
            raise ValueError('미지원 범주형 입력값: '+str(value))
        if value in choices:
            vals[prefix+value] = 1.
    return [vals[x] for x in FEATURES]


def _validate_row(rec, partition):
    if not isinstance(rec, dict) or rec.get('schema') != SCHEMA or rec.get('split') != partition:
        raise ValueError('R15 스키마/분할 불일치')
    if rec.get('origin') not in ('game_screenshot', 'reviewed_game_video'):
        raise ValueError('미검수 출처')
    label = rec.get('label') or {}
    if label.get('meaning') != 'human_behavior_not_optimality':
        raise ValueError('최적 행동/보상 라벨로 오용된 자료')
    opts = rec.get('observed_options')
    if not isinstance(opts, dict) or len(opts) < 2 or len(opts) > len(TRAININGS):
        raise ValueError('관측 선택지는 최소 두 개 필요')
    if not set(opts).issubset(TRAININGS) or label.get('chosen_action') not in opts:
        raise ValueError('모르는 행동 또는 실제 행동 미관측')
    if not all(isinstance(v, dict) for v in opts.values()):
        raise ValueError('선택지 형식 오류')
    for field in ('example_id', 'provenance_group_hash'):
        v = rec.get(field)
        if not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
            raise ValueError(field+' 해시 누락/형식 오류')
    e = rec.get('evidence') or {}
    for field in ('before_sha256', 'after_sha256'):
        h = e.get(field)
        if not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise ValueError('증거 해시 형식 오류')
    if e['before_sha256'] == e['after_sha256']:
        raise ValueError('전후 증거 동일')
    if not all(isinstance(rec.get(k), str) and 1 <= len(rec[k]) <= 100 for k in ('scenario_id', 'server', 'patch_version')):
        raise ValueError('시나리오·서버·패치 정보 누락')
    if rec['server'] not in ('KR', 'JP') or any(t in rec['patch_version'].lower() for t in ('test', 'synthetic', 'unknown', '미확인')):
        raise ValueError('검증 불가 서버/패치')
    if not isinstance(rec.get('features'), dict) or rec['features'].get('event') not in ('챔피언스 미팅', '리그 오브 히어로즈'):
        raise ValueError('대회 정보 누락')
    if not isinstance(rec.get('scenario_features'), dict):
        raise ValueError('시나리오 특징 누락')
    for option in opts:
        _vec(rec, option)  # eager feature validation on every observed action


def load_r15_exports(folder):
    folder = Path(folder)
    audit_file = folder/'uma_r15_audit.json'
    if not audit_file.is_file() or audit_file.stat().st_size > 4*1024*1024:
        raise ValueError('R15 감사 보고서가 없습니다.')
    audit = json.loads(audit_file.read_text(encoding='utf-8'))
    if audit.get('schema') != SCHEMA:
        raise ValueError('R15 감사 보고서 스키마가 다릅니다.')
    rows, groups, evidence, ids, group_scopes, proof_pairs = [], {}, {}, set(), {}, set()
    for split in SPLITS:
        path = folder/f'uma_r15_{split}.jsonl'
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('분할 파일 누락/크기 초과: '+split)
        with path.open(encoding='utf-8') as stream:
            for line_no, line in enumerate(stream, 1):
                if len(line) > 150000 or len(rows) >= MAX_ROWS:
                    raise ValueError('자료 행 수 또는 행 길이 초과')
                try:
                    rec = json.loads(line)
                    _validate_row(rec, split)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise ValueError(f'{split}:{line_no} 오류: {exc}') from exc
                ex_id = rec['example_id']
                if ex_id in ids: raise ValueError('동일 학습 레코드 중복')
                ids.add(ex_id)
                group = rec['provenance_group_hash']
                if group in groups and groups[group] != split:
                    raise ValueError('같은 육성·원본 영상이 서로 다른 분할에 존재합니다.')
                groups[group] = split
                scope = cohort_key(rec)
                if group in group_scopes and group_scopes[group] != scope:
                    raise ValueError('동일 출처 그룹에 서버·시나리오·패치·대회 혼합')
                group_scopes[group] = scope
                pair = (rec['evidence']['before_sha256'], rec['evidence']['after_sha256'])
                if pair in proof_pairs:
                    raise ValueError('동일 전후 이미지가 중복 등록됐습니다.')
                proof_pairs.add(pair)
                # Duplicate source images across splits indicate group identity corruption.
                for sha in (rec['evidence']['before_sha256'], rec['evidence']['after_sha256']):
                    if sha in evidence and evidence[sha] != group:
                        raise ValueError('동일 프레임이 다른 출처 그룹으로 기록됐습니다.')
                    evidence[sha] = group
                rows.append(rec)
    if audit.get('exportable_rows') != len(rows):
        raise ValueError('R15 감사 보고서와 JSONL의 레코드 수가 다릅니다.')
    return rows


def cohort_summary(rows):
    by = defaultdict(list)
    for r in rows: by[cohort_key(r)].append(r)
    out = []
    for k, recs in sorted(by.items()):
        groups = {s: {r['provenance_group_hash'] for r in recs if r['split'] == s} for s in SPLITS}
        eligible = (len(recs) >= MIN_TRAIN_TURNS and
                    len(set.union(*groups.values())) >= MIN_TRAIN_GROUPS and
                    all(len(groups[s]) >= (MIN_EVAL_GROUPS if s != 'train' else 1) for s in SPLITS) and
                    all(sum(r['split'] == s for r in recs) >= 5 for s in SPLITS))
        out.append({'key': list(k), 'rows': len(recs),
                    'groups': {s: len(groups[s]) for s in SPLITS}, 'eligible': eligible})
    return out


def _dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def _softmax(vals):
    top = max(vals)
    exp = [math.exp(min(0.0, x-top)) for x in vals]
    denom = sum(exp)
    return [v/denom for v in exp]


def _predict(record, weights):
    names = sorted(record['observed_options'])
    vectors = [_vec(record, n) for n in names]
    probs = _softmax([_dot(weights,v) for v in vectors])
    return names, vectors, probs


def _metrics(rows, weights, majority):
    correct, loss, baseline_correct = 0, 0., 0
    per_class = defaultdict(lambda: [0, 0, 0])  # TP, predicted, actual
    for rec in rows:
        names, _, probs = _predict(rec, weights)
        actual = rec['label']['chosen_action']
        guess = names[max(range(len(names)), key=lambda i: (probs[i], -i))]
        if guess == actual: correct += 1
        for c in names:
            if c == guess: per_class[c][1] += 1
            if c == actual: per_class[c][2] += 1
            if c == actual and c == guess: per_class[c][0] += 1
        # baseline chooses train's most-frequent action IF AVAILABLE
        baseline = majority if majority in names else names[0]
        baseline_correct += (baseline == actual)
        loss -= math.log(max(1e-12, probs[names.index(actual)]))
    n = len(rows)
    f1 = []
    for tp, pred, actual in per_class.values():
        if actual:
            precision = tp / pred if pred else 0
            recall = tp / actual
            f1.append(2*precision*recall/(precision+recall) if precision+recall else 0)
    return {'rows': n, 'accuracy': round(correct/n, 5),
            'macro_f1': round(sum(f1)/len(f1), 5) if f1 else 0,
            'log_loss': round(loss/n, 5),
            'majority_baseline_accuracy': round(baseline_correct/n, 5)}


def train_behavior(rows, key, *, epochs=65, learning_rate=0.06, seed=20261015):
    """Fit only on train; validation selects fixed stopping; test stays untouched until final."""
    key = tuple(key)
    if key not in {tuple(x['key']) for x in cohort_summary(rows) if x['eligible']}:
        raise ValueError('검수한 독립 육성 수와 train/validation/test 조건이 부족합니다. 실제 자료를 더 수집하세요.')
    partitions = {p: [r for r in rows if cohort_key(r)==key and r['split']==p] for p in SPLITS}
    # train/val/test group separation must hold even with callers bypassing loader
    gs = [{r['provenance_group_hash'] for r in partitions[p]} for p in SPLITS]
    if any(gs[i] & gs[j] for i,j in ((0,1),(0,2),(1,2))):
        raise ValueError('데이터 누출: 같은 출처가 복수 분할에 있음')
    train = partitions['train']
    counts = Counter(x['label']['chosen_action'] for x in train)
    majority = sorted(counts, key=lambda n:(-counts[n],n))[0]
    rng = random.Random(seed)
    weights = [0.] * len(FEATURES)
    best, best_loss, best_epoch = None, float('inf'), 0
    wait = 0
    for epoch in range(1,epochs+1):
        shuffled = list(train)
        rng.shuffle(shuffled)
        for rec in shuffled:
            names, vectors, probs = _predict(rec, weights)
            wanted = rec['label']['chosen_action']
            gradient = [0.] * len(weights)
            for name, v, p in zip(names, vectors, probs):
                e = p - (1.0 if name == wanted else 0.0)
                for i,value in enumerate(v): gradient[i] += e*value
            for i in range(len(weights)):
                weights[i] -= learning_rate*(gradient[i] + 0.0002*weights[i])
                weights[i] = max(-15., min(15., weights[i]))
        m = _metrics(partitions['validation'], weights, majority)
        if m['log_loss'] < best_loss - 0.00001:
            best, best_loss, best_epoch, wait = list(weights), m['log_loss'], epoch, 0
        else:
            wait += 1
        if wait >= 12: break
    if best is None: raise ValueError('학습 결과가 없습니다.')
    # Never use test to pick hyperparameters, thresholds, or epochs.
    dataset_hash = hashlib.sha256('\n'.join(sorted(r['example_id'] for r in sum(partitions.values(), []))).encode()).hexdigest()
    model = {'schema': MODEL_SCHEMA, 'feature_schema': FEATURE_SCHEMA,
             'learning_task': 'human_choice_imitation_NOT_optimal_action',
             'scope': dict(zip(('scenario_id','server','patch_version','event'),key)),
             'feature_names': list(FEATURES), 'weights': [round(w, 10) for w in best],
             'dataset_id_sha256': dataset_hash,
             'partitions': {s: {'rows':len(partitions[s]),'source_groups':len(gs[i])} for i,s in enumerate(SPLITS)},
             'training': {'algorithm':'conditional_linear_softmax_SGD', 'seed':seed,
                          'chosen_epoch':best_epoch, 'learning_rate':learning_rate},
             'metrics': {s:_metrics(partitions[s],best,majority) for s in SPLITS},
             'majority_action':majority,
             'created_at_utc':datetime.now(timezone.utc).isoformat(),
             'deployment_state':'research_only_NEVER_auto_apply',
             'warning':'행동 모방 모델은 최적 선택/승률/고점/도축 확률 예측 모델이 아닙니다.'}
    model['model_sha256'] = hashlib.sha256(json.dumps(model,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return model


def save_model(model, path):
    path = Path(path)
    validate_model(model)
    path.parent.mkdir(parents=True,exist_ok=True)
    payload = json.dumps(model,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
    fd,tmp = tempfile.mkstemp(dir=str(path.parent),prefix='.r16_',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(payload)
            out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path


def validate_model(model):
    if not isinstance(model,dict) or model.get('schema')!=MODEL_SCHEMA or model.get('feature_schema')!=FEATURE_SCHEMA:
        raise ValueError('지원하지 않는 모델')
    if model.get('deployment_state')!='research_only_NEVER_auto_apply':
        raise ValueError('검증되지 않은 모델은 자동 추천에 적용할 수 없습니다.')
    w=model.get('weights')
    if model.get('feature_names')!=list(FEATURES) or not isinstance(w,list) or len(w)!=len(FEATURES):
        raise ValueError('모델 특성 구성 불일치')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>15 for x in w):
        raise ValueError('모델 파라미터 변조')
    h=model.get('model_sha256')
    check = hashlib.sha256(json.dumps({k:v for k,v in model.items() if k!='model_sha256'},ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    if h!=check:raise ValueError('모델 무결성 해시 오류')


def read_model(path):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>300000:raise ValueError('모델 파일 없음 또는 크기 초과')
    data=json.loads(p.read_text(encoding='utf-8'))
    validate_model(data)
    return data


def behavior_preview(model, row):
    """Separate research preview; NOT used by game action recommendations."""
    validate_model(model)
    if cohort_key(row)!=tuple(model['scope'][k] for k in ('scenario_id','server','patch_version','event')):
        raise ValueError('시나리오·서버·패치·대회가 다른 모델')
    names,_,probs=_predict(row,model['weights'])
    return [{'action':n,'behavior_similarity':round(float(p),5)} for n,p in sorted(zip(names,probs),key=lambda x:-x[1])]
