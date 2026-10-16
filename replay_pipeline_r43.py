"""R43 read-only offline end-to-end turn trace and journal.

Synthetic observations are never actual game actions, verified rewards,
training-ready examples, or grounds for input automation. Historical logs are
append-only; a repeated replay does not duplicate identical turn records.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from evidence_store_r40 import TurnObservation, append_turn, read_turns


@dataclass(frozen=True)
class PipelineReport:
    synthetic_only: bool
    real_game_actions: int
    ml_training_samples: int
    turns_in_fixture: int
    appended_records: int
    reused_records: int
    blocked_turns: tuple[int, ...]
    pending_final_turn: int | None
    recorded_hypotheses: tuple[str, ...]


def _record_index(journal: Path, run_id: str) -> dict[str, dict]:
    existing = {}
    for row in read_turns(journal):
        rec = row['record']
        if rec['run_id'] != run_id:
            continue
        key = rec['turn_id']
        if key in existing:
            raise ValueError('기존 기록에 중복된 동일 육성·턴 ID가 있습니다.')
        existing[key] = rec
    return existing


def run_offline_pipeline(fixture: dict, journal: Path, *, run_id: str = 'synthetic-rehearsal',
                         replay: Callable | None = None) -> PipelineReport:
    """Use R41's replay report and persist only transitions backed by the NEXT mock frame.

    A hypothesis is *not* a click. No terminal transition is invented for the
    last frame. Idempotency is based on saved (run_id, turn_id, exact content).
    """
    if replay is None:
        from offline_replay_r41 import replay_case
        replay = replay_case
    if not isinstance(fixture, dict) or fixture.get('origin') != 'synthetic_test':
        raise ValueError('합성 시나리오만 허용합니다.')
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 128:
        raise ValueError('가상 육성 ID 오류')
    journal = Path(journal)
    result = replay(fixture)  # R41 schema, turn comparison and repeat validation
    if (result.get('schema') != 'uma_r41_synthetic_replay_report_v1' or
            result.get('synthetic_only') is not True or
            result.get('game_opened') is not False or result.get('game_clicked') is not False):
        raise ValueError('오프라인 재생 보고서 출처/입력 차단 오류')
    if result.get('trained_model') is not False or result.get('real_training_samples') != 0:
        raise ValueError('합성 결과를 실제 학습 결과로 처리할 수 없습니다.')
    turns = fixture.get('turns')
    trace = result.get('turns')
    if (not isinstance(turns, list) or not isinstance(trace, list) or
            len(turns) != len(trace) or result.get('turn_count') != len(turns) or
            result.get('remaining') != 0):
        raise ValueError('가상 턴 결과 길이 불일치')
    saved = _record_index(journal, run_id)
    additions = 0
    reused = 0
    blocked = []
    hypotheses = []
    new_records = []
    for i, frame in enumerate(turns[:-1]):
        next_frame = turns[i + 1]
        item = trace[i]
        if not isinstance(item, dict) or item.get('turn') != i + 1:
            raise ValueError('턴 순서/재생 결과 불일치')
        if (frame.get('all_actions_visible') is not True or
            not isinstance(frame.get('options'), list) or
            not all(isinstance(o, dict) and o.get('verified') is True
                    for o in frame['options'])):
            blocked.append(i + 1)
            continue
        if not isinstance(next_frame, dict) or 'stats' not in next_frame:
            blocked.append(i + 1)
            continue
        hypothetical = item.get('hypothetical_top')
        if (item.get('real_game_action') is not None or not isinstance(hypothetical, str)
                or hypothetical not in [o.get('name') for o in frame['options']]):
            raise ValueError('가상 판단이 실제 게임 조작으로 오인될 위험이 있습니다.')
        turn_id = str(i + 1)
        # Never fabricate an actual chosen action or an actual outcome.
        record = TurnObservation(
            run_id=run_id, turn_id=turn_id,
            scenario='island_post_patch_v1', patch='synthetic_only',
            origin='synthetic_test', screen_verified=False,
            chosen_action=None, outcome_verified=False,
            before={'stats': frame['stats'], 'energy': frame.get('energy'),
                    'hypothetical_top': hypothetical,
                    'hypothetical_scores': item.get('ranked_hypothesis')},
            after={'next_mock_stats': next_frame['stats'],
                   'no_verified_effect': True},
            evidence_note='다음 가상 프레임 확인 · 실제 행동/보상 아님')
        content = record.__dict__
        if turn_id in saved:
            if saved[turn_id] != content:
                raise ValueError('기존 가상 턴과 다른 기록입니다. 다른 육성 ID로 보존하세요.')
            reused += 1
        else:
            new_records.append(record)
            saved[turn_id] = content
        hypotheses.append(hypothetical)
    # Detect conflicts across the whole replay before mutating an existing journal.
    for record in new_records:
        append_turn(journal, record)
        additions += 1
    last = len(turns) if turns else None
    # The final turn has no following frame, so it must not be logged as completed.
    return PipelineReport(
        synthetic_only=True, real_game_actions=0, ml_training_samples=0,
        turns_in_fixture=len(turns), appended_records=additions,
        reused_records=reused, blocked_turns=tuple(blocked),
        pending_final_turn=last,
        recorded_hypotheses=tuple(hypotheses))


def main(argv=None):
    """Explicit CLI; by default writes no user files and never touches a game."""
    import argparse
    from dataclasses import asdict
    import json
    import tempfile
    parser = argparse.ArgumentParser(description='R43 offline synthetic turn-journal test')
    parser.add_argument('fixture', type=Path)
    parser.add_argument('--journal', type=Path, default=None,
                        help='Optional append-only JSONL path; omitted = temporary test journal')
    parser.add_argument('--run-id', default='synthetic-rehearsal')
    args = parser.parse_args(argv)
    if not args.fixture.is_file() or args.fixture.stat().st_size > 256*1024:
        parser.error('가상 시나리오 파일 누락/크기 초과')
    source = json.loads(args.fixture.read_text(encoding='utf-8'))
    if args.journal is None:
        with tempfile.TemporaryDirectory(prefix='uma_r43_offline_') as td:
            report = run_offline_pipeline(source, Path(td)/'synthetic_turns.jsonl',
                                          run_id=args.run_id)
    else:
        report = run_offline_pipeline(source, args.journal, run_id=args.run_id)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
