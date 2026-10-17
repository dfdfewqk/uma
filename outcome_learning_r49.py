"""R49 reviewed before/after learning, safely isolated by scenario and KR patch.

No labels for unchosen actions; no model update from provisional OCR, synthetic
replays or unreviewed outcomes. A run-based holdout prevents leakage.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import os
import tempfile
from pathlib import Path

STATS=("스피드","스태미나","파워","근성","지능")
VALID_ACTIONS=STATS+("휴식","외출","레이스")
SOURCE="reviewed_kr_game_screens"
SCHEMA="uma_r49_reviewed_outcome_v1"
POLICY_VERSION="r49_mean_reward_v1"
MIN_TRAIN_RUNS=30
MIN_TRAIN_TURNS=200


@dataclass(frozen=True)
class ReviewedTurnOutcome:
    run_id: str
    turn_id: str
    scenario: str
    patch: str
    action: str
    before: dict[str,int]
    after: dict[str,int]
    evidence_before_sha256: str
    evidence_after_sha256: str
    origin: str
    reviewer_confirmed: bool
    skill_point_before: int=0
    skill_point_after: int=0
    energy_before: int=0
    energy_after: int=0
    result_kind: str="observed"
    def validate(self):
        if any(not isinstance(v,str) or not v.strip() or len(v)>128
               for v in (self.run_id,self.turn_id,self.scenario,self.patch)):
            raise ValueError("육성/턴/시나리오/서버 버전 정보 오류")
        if self.action not in VALID_ACTIONS or self.origin!=SOURCE or self.reviewer_confirmed is not True:
            raise ValueError("실제 게임 결과 검수 전 학습 금지")
        for sha in (self.evidence_before_sha256,self.evidence_after_sha256):
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
                raise ValueError("게임 결과 캡처 해시 오류")
        if self.evidence_before_sha256==self.evidence_after_sha256:
            raise ValueError("동일한 게임 화면을 결과로 재사용할 수 없습니다.")
        for stats in (self.before,self.after):
            if set(stats)!=set(STATS) or any(type(v) is not int or not 0<=v<=5000 for v in stats.values()):
                raise ValueError("게임 스탯 결과 오류")
        for field in ("skill_point_before","skill_point_after","energy_before","energy_after"):
            v=getattr(self,field)
            if type(v) is not int or v<0 or v>20000:
                raise ValueError("Pt/체력 수치 오류")
        if not (self.energy_before<=100 and self.energy_after<=100):
            raise ValueError("체력 수치 초과")
        if self.result_kind!="observed":
            raise ValueError("관측된 실제 결과만 학습")
        return self


def partition(run_id: str) -> str:
    """All turns from a run must stay on one side of train/holdout."""
    return "holdout" if int(hashlib.sha256(run_id.encode()).hexdigest()[:8],16)%5==0 else "train"


def _key(v: ReviewedTurnOutcome) -> str:
    return hashlib.sha256((v.run_id+"|"+v.turn_id+"|"+v.scenario+"|"+v.patch).encode()).hexdigest()


def _read_file(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("다른 파일로 연결된 학습 기록은 변경할 수 없습니다.")
    if not path.exists():
        return {"schema":SCHEMA,"entries":[]}
    if path.stat().st_size>10_000_000:
        raise ValueError("학습 기록 파일 크기/연결 확인 필요")
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA or not isinstance(raw.get("entries"),list):
        raise ValueError("학습 기록 버전 오류")
    if len(raw["entries"])>15000:
        raise ValueError("학습 기록 수량 제한")
    return raw


def append_reviewed(path: str|Path, entry: ReviewedTurnOutcome):
    entry.validate()
    path=Path(path)
    data=_read_file(path)
    identifier=_key(entry)
    if any(row.get("id")==identifier for row in data["entries"]):
        raise ValueError("같은 턴의 검수 결과를 중복 학습할 수 없습니다.")
    if len(data["entries"])>=15000:
        raise ValueError("학습 기록 한도 초과 · 백업/분할 필요")
    record={"id":identifier,"split":partition(entry.run_id),"data":asdict(entry)}
    data["entries"].append(record)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".uma_r49_data_",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=False,separators=(",",":"),allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return record["split"]


@dataclass(frozen=True)
class LearnedScores:
    version: str
    ready: bool
    action_rewards: dict[str,float]
    train_turns: int
    train_runs: int
    holdout_turns: int
    notes: str


def derive_model(path: str|Path,scenario: str,patch: str):
    """Fit only reviewed, isolated train records. Never modify original data."""
    data=_read_file(Path(path))
    train=[];held=[]
    for row in data["entries"]:
        e=ReviewedTurnOutcome(**row["data"]).validate()
        if e.scenario!=scenario or e.patch!=patch:
            continue
        if row.get("split")!=partition(e.run_id) or row.get("id")!=_key(e):
            raise ValueError("훈련/평가 데이터 분리 또는 원본 해시 손상")
        (train if row["split"]=="train" else held).append(e)
    train_runs={e.run_id for e in train}
    ready=len(train_runs)>=MIN_TRAIN_RUNS and len(train)>=MIN_TRAIN_TURNS
    if not ready:
        return LearnedScores(POLICY_VERSION,False,{},len(train),len(train_runs),len(held),
                             "실제 검수 데이터 부족 · 임의 학습 점수로 자동 행동 선택 금지")
    values={}
    for action in VALID_ACTIONS:
        examples=[e for e in train if e.action==action]
        # Only a REVIEWED chosen action's observed delta; no counterfactuals.
        if len({e.run_id for e in examples}) < 5:
            continue
        rewards=[]
        for e in examples:
            gains=sum(max(-400,min(400,e.after[s]-e.before[s])) for s in STATS)
            skill=max(-1000,min(1000,e.skill_point_after-e.skill_point_before))
            energy=e.energy_after-e.energy_before
            rewards.append(gains + .18*skill + .33*energy)
        values[action]=round(sum(rewards)/len(rewards),3)
    return LearnedScores(POLICY_VERSION,True,values,len(train),len(train_runs),len(held),
                         "동일 서버/패치의 검수 턴만 학습; 선택되지 않은 행동의 결과는 미확인")


def save_model_version(path: str|Path, learned: LearnedScores):
    """Immutable, versioned snapshot: old snapshots never silently overwritten."""
    dest=Path(path)
    if dest.exists() or dest.is_symlink():
        raise ValueError("이미 존재하는 모델 버전을 덮어쓸 수 없습니다.")
    dest.parent.mkdir(parents=True,exist_ok=True)
    payload={"schema":POLICY_VERSION,**asdict(learned)}
    with dest.open("x",encoding="utf-8") as out:
        json.dump(payload,out,ensure_ascii=False,indent=2)
    return dest


def load_model_version(path: str|Path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>200000:
        raise ValueError("모델 파일 크기/경로 오류")
    obj=json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema")!=POLICY_VERSION or obj.get("version")!=POLICY_VERSION:
        raise ValueError("학습 모델 버전 불일치")
    return LearnedScores(**{k:v for k,v in obj.items() if k!="schema"})


def inspect_record_counts(path: str|Path, scenario: str):
    """Count recorded *real reviewed* outcomes without assuming a KR patch."""
    by_patch = {}
    seen = set()
    for row in _read_file(Path(path))["entries"]:
        e=ReviewedTurnOutcome(**row["data"]).validate()
        if row.get("id")!=_key(e) or row.get("split")!=partition(e.run_id):
            raise ValueError("학습 자료 출처/무결성 불일치")
        if e.scenario != scenario:
            continue
        if row["id"] in seen:
            raise ValueError("학습 자료 중복")
        seen.add(row["id"])
        stats=by_patch.setdefault(e.patch,{"turns":0,"runs":set()})
        stats["turns"]+=1
        stats["runs"].add(e.run_id)
    return {patch:{"turns":v["turns"],"runs":len(v["runs"])}
            for patch,v in sorted(by_patch.items())}
