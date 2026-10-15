"""Offline R16 CLI: `python ml_cli_r16.py inspect <R15-export-folder>`.

Training is explicit and cannot happen without R15 quality gates.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from ml_engine_r16 import load_r15_exports, cohort_summary, train_behavior, save_model


def main(argv=None):
    parser=argparse.ArgumentParser(description='R16 research-only human-choice imitation ML')
    subs=parser.add_subparsers(dest='command',required=True)
    inspect=subs.add_parser('inspect',help='List cohort quality gates')
    inspect.add_argument('folder',type=Path)
    fit=subs.add_parser('train',help='Train only a ready cohort; no auto deployment')
    fit.add_argument('folder',type=Path)
    fit.add_argument('--cohort',type=int,required=True,help='Index from inspect, starting at 0')
    fit.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    rows=load_r15_exports(args.folder)
    cohorts=cohort_summary(rows)
    if args.command=='inspect':
        print(json.dumps({'total_rows':len(rows),'cohorts':[{'index':i,**c} for i,c in enumerate(cohorts)]},ensure_ascii=False,indent=2))
        return 0
    if args.cohort < 0 or args.cohort >= len(cohorts):
        parser.error('잘못된 코호트 번호')
    model=train_behavior(rows,cohorts[args.cohort]['key'])
    save_model(model,args.output)
    print(json.dumps({'scope':model['scope'],'metrics':model['metrics'],
                      'deployment_state':model['deployment_state'],
                      'model_path':str(args.output)},ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError) as e:
        print('R16 학습 보류 / 파일 오류:',e)
        raise SystemExit(2)
