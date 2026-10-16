"""Validate the post-patch JP research pack without treating guides as ML labels.

This is a structural/provenance audit only: hashes, tags and reviewer claims do
not prove the captured footage or that a chosen action was optimal.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

P = Path(__file__).resolve().parent
TABLES = (
    ('sources.csv', 'source_id'),
    ('evidence.csv', 'evidence_id'),
    ('player_cases.csv', 'case_id'),
    ('hypotheses.csv', 'hypothesis_id'),
    ('video_chapters.csv', 'chapter_id'),
    ('turn_annotations.csv', 'turn_id'),
)
TURN_COLUMNS = (
    'turn_id', 'case_id', 'source_id', 'video_timestamp_seconds',
    'school_year', 'period', 'remaining_turns', 'speed', 'stamina',
    'power', 'guts', 'wisdom', 'energy', 'motivation',
    'friendship_positions', 'support_bonds_json', 'island_tickets',
    'next_ticket_turn', 'construction_levels_json',
    'available_actions_json', 'chosen_action', 'post_action_delta_json',
    'action_success_verified', 'observation_method', 'confidence',
    'server', 'patch_version', 'source_group',
    'evidence_before_sha256', 'evidence_after_sha256', 'review_status',
)
DIGEST = re.compile(r'[0-9a-fA-F]{64}\Z')


def require(condition: bool, description: str) -> None:
    if not condition:
        raise ValueError(description)


def read(name: str, root: Path = P) -> list[dict[str, str]]:
    with (Path(root) / name).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        names = reader.fieldnames or []
        require(len(names) == len(set(names)), f'{name}: duplicate columns')
        if name == 'turn_annotations.csv':
            require(tuple(names) == TURN_COLUMNS, 'turn_annotations.csv: wrong header/schema')
        rows = list(reader)
        for i, row in enumerate(rows, 2):
            require(None not in row and all(value is not None for value in row.values()),
                    f'{name}:{i} broken CSV field count')
        return rows


def _unique(rows: list[dict[str, str]], key: str) -> None:
    ids = [r.get(key, '').strip() for r in rows]
    require(all(ids) and len(ids) == len(set(ids)), f'{key}: duplicated or blank')


def validate_turn_annotations(rows: list[dict[str, str]], sources: set[str],
                              cases: dict[str, str]) -> None:
    """Allow only manually reviewed JP post-patch observations, not synthetic labels."""
    _unique(rows, 'turn_id')
    for row in rows:
        tid = row['turn_id']
        context = f'turn {tid}'
        require(row['source_id'] in sources, f'{context}: unknown source')
        require(row['case_id'] in cases, f'{context}: unknown case')
        require(cases[row['case_id']] == row['source_id'],
                f'{context}: case/source mismatch')
        require(row['server'] == 'JP' and row['patch_version'] == 'JP-2025-06-30-post',
                f'{context}: patch/server mismatch; KR needs a separate research pack')
        require(bool(row['source_group'].strip()), f'{context}: missing source group')
        require(row['review_status'] == 'human_verified',
                f'{context}: unverified footage cannot enter this table')
        require(row['observation_method'] == 'human_video_frame',
                f'{context}: source frame review required')
        require(row['confidence'] == 'human_confirmed',
                f'{context}: uncertain observation')
        for field in ('evidence_before_sha256', 'evidence_after_sha256'):
            require(DIGEST.fullmatch(row[field]) is not None,
                    f'{context}: invalid {field}')
        require(row['evidence_before_sha256'] != row['evidence_after_sha256'],
                f'{context}: before/after evidence identical')
        numeric = {'video_timestamp_seconds': (0, 1000000),
                   'remaining_turns': (0, 100), 'speed': (0, 5000),
                   'stamina': (0, 5000), 'power': (0, 5000),
                   'guts': (0, 5000), 'wisdom': (0, 5000),
                   'energy': (0, 100), 'island_tickets': (0, 99)}
        for field, (low, high) in numeric.items():
            value = row[field]
            require(value.isdecimal() and low <= int(value) <= high,
                    f'{context}: invalid {field}')
        for field in ('support_bonds_json', 'construction_levels_json',
                      'post_action_delta_json'):
            try:
                val = json.loads(row[field])
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{context}: invalid {field}') from exc
            require(isinstance(val, dict), f'{context}: {field} must be a JSON object')
        try:
            actions = json.loads(row['available_actions_json'])
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{context}: invalid available_actions_json') from exc
        require(isinstance(actions, list) and bool(actions),
                f'{context}: missing reviewed available actions')
        choices = [a if isinstance(a, str) else a.get('name') if isinstance(a, dict)
                   else None for a in actions]
        require(all(isinstance(x, str) and x.strip() for x in choices),
                f'{context}: invalid action names')
        require(row['chosen_action'] in choices,
                f'{context}: chosen action absent from observed choices')
        require(row['action_success_verified'] in {'verified', 'not_observed'},
                f'{context}: ambiguous action outcome verification')
        require(bool(row['school_year'].strip()) and bool(row['period'].strip()),
                f'{context}: missing turn context')


def verify(root: Path = P) -> dict[str, int]:
    root = Path(root)
    datasets = {name: read(name, root) for name, _ in TABLES}
    for name, key in TABLES:
        _unique(datasets[name], key)
    ss, ee, cc, hh, vv, tt = [datasets[name] for name, _ in TABLES]
    sources = {r['source_id'] for r in ss}
    evidence_ids = {r['evidence_id'] for r in ee}
    require(all(r['source_id'] in sources for r in ee + cc + vv),
            'missing source reference')
    require(all(set(filter(None, r['supporting_evidence_ids'].split('|')))
                <= evidence_ids for r in hh), 'missing hypothesis evidence')
    require(all(r['url'].startswith('https://') for r in ss), 'bad source URL')
    require(all(r['start_second'].isdecimal() for r in vv), 'bad chapter time')
    validate_turn_annotations(tt, sources,
                              {r['case_id']: r['source_id'] for r in cc})
    expected = {'sources': len(ss), 'evidence_items': len(ee),
                'player_cases': len(cc), 'video_chapters': len(vv),
                'verified_frame_or_turn_annotations': len(tt),
                'hypotheses': len(hh)}
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest['counts'] == expected, 'research manifest counts differ from CSV')
    require(manifest.get('training_readiness', '').startswith('NOT_TRAINABLE'),
            'source notes or observed behavior are not ML optimality labels')
    require(any(c['result_label'] == 'discarded_after_completion' for c in cc),
            'missing after-completion discard example')
    require(any(c['result_label'] == 'restarted' for c in cc),
            'missing restart example')
    require(all(h['status'] != 'verified_for_engine' for h in hh),
            'uncalibrated research claim promoted to engine')
    return expected


if __name__ == '__main__':
    result = verify()
    print('PASS — JP research provenance/schema audit:', result)
    print('Model training readiness remains NOT_TRAINABLE until independent R15/R16 validation')
