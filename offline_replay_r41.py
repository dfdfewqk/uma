"""R41 synthetic-only scenario replay of R40 decisions (no game / no ML labels).

Fixture files cannot be used as proof of real screen recognition. Every report is
explicitly labelled synthetic and contains no control command for a game client.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from auto_core_r40 import AutomationConfig,AutomationProgress,TPView,advise_tp
from target_selector_r39 import Target,kind_for_round
from turn_policy_r40 import TurnEvidence,TurnOption,score_option,suggest_turn

SCHEMA='uma_r41_synthetic_replay_v1'
MAX_FILE_BYTES=256*1024
STAT_NAMES=('스피드','스태미나','파워','근성','지능')


def replay_case(fixture:dict)->dict:
    if not isinstance(fixture,dict) or fixture.get('schema')!=SCHEMA:
        raise ValueError('가상 시나리오 파일 형식 오류')
    if fixture.get('origin')!='synthetic_test':
        raise ValueError('R41은 합성 시나리오만 재생합니다.')
    t=fixture.get('target')
    if not isinstance(t,dict) or set(t)!={'round','style'}:
        raise ValueError('회차·각질 설정 오류')
    target=Target(kind_for_round(t['round']),t['round'],t['style']).validate()
    turns=fixture.get('turns')
    if not isinstance(turns,list) or not 1<=len(turns)<=200:
        raise ValueError('재생 턴 수는 1~200 사이여야 합니다.')
    trace=[]
    for number,frame in enumerate(turns,1):
        if not isinstance(frame,dict):
            raise ValueError('턴 데이터 오류')
        options=frame.get('options')
        if not isinstance(options,list) or not 2<=len(options)<=15:
            raise ValueError('턴마다 선택지 2~15개가 필요합니다.')
        if not isinstance(frame.get('stats'),dict) or not isinstance(frame.get('targets'),dict):
            raise ValueError('턴 스탯/목표 오류')
        state=TurnEvidence(frame['stats'],frame['targets'],frame.get('energy'),
                           frame.get('next_turn_mandatory_race'),
                           frame.get('all_actions_visible',False),
                           verified=False,source='synthetic_test')
        state.validate()
        all_opts=[TurnOption(**opt).validate() for opt in options]
        names=[opt.name for opt in all_opts]
        if len(set(names))!=len(names):
            raise ValueError('중복 선택지')
        # score_option performs arithmetic on a synthetic fixture, but does not
        # endorse the action; suggest_turn refuses unreviewed synthetic evidence.
        scores=tuple(sorted(((opt.name,score_option(state,opt)) for opt in all_opts),
                            key=lambda x:(-x[1],x[0])))
        guard=suggest_turn(state,all_opts)
        if guard.action is not None:
            raise AssertionError('합성 데이터에서 실제 게임 추천이 활성화됐습니다.')
        trace.append({
            'turn':number,'ranked_hypothesis':list(scores),
            'hypothetical_top':scores[0][0],
            'real_game_action':None,
            'blocked_reason':guard.reason,
            'next_turn_race':frame.get('next_turn_mandatory_race'),
            'diff_from_runner_up':round(scores[0][1]-scores[1][1],3)
        })
    repeats=fixture.get('repetitions',1)
    if type(repeats) is not int or not 1<=repeats<=100:
        raise ValueError('가상 반복 횟수 오류')
    outcomes=fixture.get('simulated_outcomes',['ordinary']*repeats)
    if not isinstance(outcomes,list) or len(outcomes)!=repeats:
        raise ValueError('가상 육성 결과 수와 반복 횟수 불일치')
    conf=AutomationConfig(target,repeats,'synthetic-character',
                          'synthetic-deck','synthetic-inheritance')
    progress=AutomationProgress(conf).arm()
    for idx,outcome in enumerate(outcomes,1):
        mock_tp=TPView(30,30,0,0,verified=True)
        if advise_tp(mock_tp).action!='start_run':
            raise AssertionError('합성 TP 모형에서 시작할 수 없습니다.')
        run_id=f'synthetic-{idx}'
        progress.begin(run_id,mock_tp)
        progress.finish(run_id,outcome,verified=True)
    return {
        'schema':'uma_r41_synthetic_replay_report_v1',
        'synthetic_only':True,'game_opened':False,'game_clicked':False,
        'trained_model':False,'real_training_samples':0,
        'target':target.label,'turn_count':len(turns),
        'turns':trace,
        'simulated_repetitions':repeats,
        'simulated_outcomes':dict(progress.outcomes),
        'remaining':progress.remaining
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description='R41 synthetic replay; never opens a game')
    parser.add_argument('fixture',type=Path)
    args=parser.parse_args(argv)
    if not args.fixture.is_file() or args.fixture.stat().st_size>MAX_FILE_BYTES:
        parser.error('파일 누락 또는 크기 제한 초과')
    payload=json.loads(args.fixture.read_text(encoding='utf-8'))
    result=replay_case(payload)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
