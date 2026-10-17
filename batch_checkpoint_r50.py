"""R50 immutable-input, atomic progress checkpoint for verified KR batch runs.

Existing user R40/R44 and prior training labels are untouched. On restart a
session with an active run or pending click is *not* silently resumed; user must
finish reviewing that in-game transition. Only the live supervisor can mark
completed IDs after a registered result and a distinct follow-on scene.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json
import os
import tempfile

SCHEMA="uma_r50_batch_checkpoint_v1"
OUTCOMES=frozenset(("good","ordinary","disposed","failed"))


@dataclass(frozen=True)
class BatchCheckpoint:
    target_key: str
    target_style: str
    scenario: str
    repeats: int
    completed_ids: tuple[str,...]
    outcomes: dict[str,str]
    active_run_id: str|None
    pending_action: str|None
    schema: str=SCHEMA

    def validate(self):
        if self.schema!=SCHEMA:
            raise ValueError("육성 기록 버전 오류")
        if (not isinstance(self.target_key,str) or not self.target_key.strip()
                or not isinstance(self.target_style,str) or not self.target_style.strip()
                or not isinstance(self.scenario,str) or not self.scenario.strip()):
            raise ValueError("대회/각질/시나리오 기록 오류")
        if type(self.repeats) is not int or not 1<=self.repeats<=10000:
            raise ValueError("반복 목표 횟수 오류")
        if (not isinstance(self.completed_ids,tuple) or
                len(self.completed_ids)!=len(set(self.completed_ids)) or
                len(self.completed_ids)>self.repeats or
                any(not isinstance(k,str) or not 1<=len(k)<=128 for k in self.completed_ids)):
            raise ValueError("완료 육성 기록 중복/범위 오류")
        if (not isinstance(self.outcomes,dict) or
                set(self.outcomes)!=set(self.completed_ids) or
                any(k not in OUTCOMES for k in self.outcomes.values())):
            raise ValueError("육성 결과·완료 ID 불일치")
        if (self.active_run_id is not None and
                (not isinstance(self.active_run_id,str) or
                 not self.active_run_id or len(self.active_run_id)>128 or
                 self.active_run_id in self.outcomes)):
            raise ValueError("진행 중 육성 식별자 오류")
        if self.pending_action is not None and self.pending_action not in (
            "start_run","free_tp_item","purchase_skill","finish_run","repeat_run"):
            raise ValueError("대기 중 클릭 작업 불일치")
        return self

    @property
    def needs_user_review(self):
        return self.active_run_id is not None or self.pending_action is not None


def current_snapshot(supervisor):
    goal=supervisor.planner.goal.validate()
    pending=supervisor.awaiting
    return BatchCheckpoint(
        goal.key,goal.style,goal.scenario,supervisor.planner.repeats,
        tuple(sorted(supervisor.planner.completed_ids)),
        dict(supervisor.planner.outcomes),supervisor.active_run_id,
        pending["action"] if pending else None).validate()


def load_checkpoint(path,goal,repeats):
    goal.validate()
    path=Path(path)
    if path.is_symlink():
        raise ValueError("연결된 육성 기록 파일은 불러올 수 없습니다.")
    if not path.exists():
        return None
    if path.stat().st_size>2_000_000:
        raise ValueError("육성 기록 파일 크기 오류")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("schema")!=SCHEMA:
        raise ValueError("기존 육성 기록 버전 오류 · 원본 보존")
    data["completed_ids"]=tuple(data["completed_ids"])
    snapshot=BatchCheckpoint(**data).validate()
    if (snapshot.target_key!=goal.key or snapshot.target_style!=goal.style
            or snapshot.scenario!=goal.scenario or snapshot.repeats!=repeats):
        raise ValueError("기존 육성 기록은 다른 대회/각질/반복 횟수용 · 병합 금지")
    return snapshot


def save_checkpoint(path,snapshot):
    snapshot.validate()
    path=Path(path)
    if path.is_symlink():
        raise ValueError("외부 경로로 연결된 육성 기록은 수정할 수 없습니다.")
    # Never overwrite a different goal/session even if the current client
    # settings have changed in between the queued click and the callback.
    if path.exists():
        old=json.loads(path.read_text(encoding="utf-8"))
        if (old.get("schema")!=SCHEMA or
             (old.get("target_key"),old.get("target_style"),old.get("scenario"),old.get("repeats"))
             !=(snapshot.target_key,snapshot.target_style,snapshot.scenario,snapshot.repeats)):
            raise ValueError("기존 육성 기록과 다른 계획 · 원본 유지")
        previous=set(old.get("completed_ids",()))
        if (not previous.issubset(snapshot.completed_ids) or
            any(old.get("outcomes",{}).get(k)!=snapshot.outcomes[k] for k in previous)):
            raise ValueError("이전 육성 결과 감소/변경 불가")
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(asdict(snapshot),ensure_ascii=False,allow_nan=False,separators=(",",":"))
    fd,tmp=tempfile.mkstemp(prefix=".uma_r50_checkpoint_",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path


def restore_finished_only(supervisor,snapshot):
    snapshot.validate()
    goal=supervisor.planner.goal
    if (goal.key!=snapshot.target_key or goal.style!=snapshot.target_style or
        goal.scenario!=snapshot.scenario or
        supervisor.planner.repeats!=snapshot.repeats):
        raise ValueError("현재 자동 육성 설정과 기존 기록 불일치")
    if snapshot.needs_user_review:
        raise ValueError("이전 육성/클릭이 완료 확인 전 종료됨 · 자동 이어하기 차단")
    supervisor.planner.completed_ids=set(snapshot.completed_ids)
    supervisor.planner.outcomes=dict(snapshot.outcomes)
    if supervisor.planner.remaining<=0:
        supervisor.halt("설정한 육성 횟수 이미 완료")
    return supervisor
