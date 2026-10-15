"""Export *untrained* decision records for later offline research.

A chosen human action is a behavioral label, NOT proof it was optimal.
This deliberately does not fit, load or claim any ML model.
"""
import csv
import json
from pathlib import Path
from storage import list_runs, list_turns
from uma_core import Action, action_is_observed

STAT_NAMES = ('스피드', '스태미나', '파워', '근성', '지능')
COLUMNS = ['run_id', 'turn_id', 'scenario', 'event', 'distance', 'style', 'course',
           'remaining_turns', 'energy', 'mood', 'island_tickets',
           'development_points', 'skill_points', *('stat_' + n for n in STAT_NAMES),
           'observed_actions_json', 'human_chosen_action', 'outcome_status_for_audit_only',
           'abandon_reason_for_audit_only', 'origin', 'quality_warning']


def export_decisions_csv(conn, output: Path) -> dict:
    exported, skipped = 0, 0
    with output.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=COLUMNS)
        writer.writeheader()
        for run in reversed(list_runs(conn)):
            p = run['profile']
            outcome = run.get('outcome', {})
            for t in list_turns(conn, run['id']):
                chosen = t.get('chosen_action', '')
                observed = {k: a for k, a in t['options'].items()
                            if action_is_observed(Action(**a))}
                if chosen in ('', '미선택') or chosen not in observed:
                    skipped += 1
                    continue
                state = t['state']
                warn = 'one_option_only' if len(observed) < 2 else 'manual_observation_unverified'
                row = {
                    'run_id': run['id'], 'turn_id': t['id'], 'scenario': p.get('scenario', ''),
                    'event': p.get('event', ''), 'distance': p.get('distance', ''),
                    'style': p.get('style', ''), 'course': p.get('course', ''),
                    'remaining_turns': state.get('remaining_turns', ''), 'energy': state.get('energy', ''),
                    'mood': state.get('mood', ''), 'island_tickets': state.get('island_tickets', ''),
                    'development_points': state.get('development_points', ''),
                    'skill_points': state.get('skill_points', ''),
                    'observed_actions_json': json.dumps(observed, ensure_ascii=False),
                    'human_chosen_action': chosen,
                    'outcome_status_for_audit_only': outcome.get('status', '진행중'),
                    'abandon_reason_for_audit_only': outcome.get('reason', ''),
                    'origin': 'app_manual_input', 'quality_warning': warn,
                }
                row.update({f'stat_{n}': state.get('stats', {}).get(n, '') for n in STAT_NAMES})
                writer.writerow(row)
                exported += 1
    return {'exported': exported, 'skipped': skipped}
