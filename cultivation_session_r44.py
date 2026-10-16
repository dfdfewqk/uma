"""R44 recoverable read-only cultivation session coordinator.

Prepares the 20-run (or user-selected N-run) workflow without driving the
game. Every transition that claims a real start, item use or completion
requires a separately verified KR screen observation from a future adapter.
No game-input or background-loop function is present.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
import tempfile
from pathlib import Path

from auto_core_r40 import (AutomationConfig, AutomationProgress, TPView,
                           restore_progress)
from tp_strategy_r44 import FreeTPItem, TPAdvice, plan_tp_step

SCHEMA = "uma_r44_session_v1"
TRUSTED_ORIGINS = frozenset(("reviewed_game_screenshot", "reviewed_game_video"))
EVIDENCE_KINDS = frozenset(("resume", "start", "finish", "item_used", "tp_refresh"))
MAX_FILE_BYTES = 2*1024*1024


@dataclass(frozen=True)
class SessionEvidence:
    evidence_id: str
    origin: str
    kind: str
    run_id: str | None
    character_id: str
    deck_id: str
    inheritance_id: str
    scenario: str
    patch: str
    reviewed: bool

    def validate(self, config: AutomationConfig):
        config.validate()
        if (self.origin not in TRUSTED_ORIGINS or
                self.kind not in EVIDENCE_KINDS or
                self.reviewed is not True):
            raise ValueError("실제 게임에서 검수된 상태가 아닙니다.")
        if (not isinstance(self.evidence_id, str) or
                not 8 <= len(self.evidence_id) <= 128):
            raise ValueError("검증된 증거 식별자가 필요합니다.")
        if (self.run_id is not None and
                (not isinstance(self.run_id, str) or
                 not 1 <= len(self.run_id) <= 128)):
            raise ValueError("육성 식별자 오류")
        if (self.character_id != config.character_id or
                self.deck_id != config.deck_id or
                self.inheritance_id != config.inheritance_id or
                self.scenario != config.target.scenario or
                self.patch != config.game_patch):
            raise ValueError("시작 시 지정한 캐릭터·덱·계승·패치 정보가 다릅니다.")
        return self


@dataclass
class CultivationSession:
    progress: AutomationProgress
    paused: bool = True
    pause_reason: str = "실게임 검수 전 · 실행 금지"
    tp_refresh_required: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    last_free_item_id: str | None = None
    pending_free_item_id: str | None = None

    def validate(self):
        self.progress.validate()
        if (type(self.paused) is not bool or
                type(self.tp_refresh_required) is not bool or
                not isinstance(self.pause_reason, str) or
                len(self.pause_reason) > 500):
            raise ValueError("세션 일시 정지 상태 오류")
        if (not isinstance(self.evidence_ids, list) or
                len(self.evidence_ids) > 256 or
                any(not isinstance(x, str) or len(x) < 8 or len(x) > 128
                    for x in self.evidence_ids) or
                len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("중복/손상된 게임 증거 목록")
        if self.pending_free_item_id is not None and (
                not isinstance(self.pending_free_item_id, str) or
                not 1 <= len(self.pending_free_item_id) <= 100):
            raise ValueError("무료 회복 아이템 선택 후보 ID 오류")
        if self.last_free_item_id is not None and (
                not isinstance(self.last_free_item_id, str) or
                not 1 <= len(self.last_free_item_id) <= 100):
            raise ValueError("마지막 사용 아이템 ID 오류")
        return self

    @classmethod
    def plan(cls, config: AutomationConfig):
        return cls(AutomationProgress(config.validate())).validate()

    @property
    def summary(self):
        self.validate()
        return {
            "requested": self.progress.config.repetitions,
            "completed": len(self.progress.completed_ids),
            "remaining": self.progress.remaining,
            "good": sum(v == "good" for v in self.progress.outcomes.values()),
            "ordinary": sum(v == "ordinary" for v in self.progress.outcomes.values()),
            "disposed": sum(v == "disposed" for v in self.progress.outcomes.values()),
            "failed": sum(v == "failed" for v in self.progress.outcomes.values()),
            "phase": self.progress.phase,
            "paused": self.paused,
            "game_input_allowed": False,
        }

    def _accept(self, evidence: SessionEvidence, kind: str):
        evidence.validate(self.progress.config)
        if evidence.kind != kind:
            raise ValueError("예상한 게임 검증 단계가 아닙니다.")
        if evidence.evidence_id in self.evidence_ids:
            raise ValueError("동일한 화면 증거를 다시 처리할 수 없습니다.")
        # Bounded duplicate-fingerprint history. Run-ID uniqueness remains
        # enforced by AutomationProgress throughout the complete batch.
        self.evidence_ids.append(evidence.evidence_id)
        self.evidence_ids = self.evidence_ids[-256:]

    def arm_after_setup_review(self, evidence: SessionEvidence):
        self.validate()
        if self.progress.phase != "setup" or evidence.run_id is not None:
            raise ValueError("새 육성 계획/초기 화면 상태가 아닙니다.")
        self._accept(evidence, "resume")
        self.progress.arm()
        self.paused = False
        self.pause_reason = ""
        return self.validate()

    def next_tp_advice(self, tp: TPView | None,
                       items: tuple[FreeTPItem, ...] | None) -> TPAdvice:
        self.validate()
        if self.paused:
            return TPAdvice("stop", "세션 일시 정지 · 수동 검수 후 재개")
        if self.progress.phase == "finished":
            return TPAdvice("stop", "요청한 육성 횟수 완료")
        if self.progress.phase not in ("need_tp", "waiting_tp"):
            return TPAdvice("verify", "진행 중 육성의 실제 화면 확인이 먼저 필요합니다.")
        if self.tp_refresh_required or tp is None:
            return TPAdvice("verify", "아이템 사용 후 새로운 TP 관측값 확인 필요")
        advice = plan_tp_step(tp, items)
        self.pending_free_item_id = advice.item_id if advice.action == "use_free_tp_item" else None
        if advice.action == "wait_regen" and self.progress.phase == "need_tp":
            self.progress.wait()
        return advice

    def confirm_item_use(self, evidence: SessionEvidence, item_id: str):
        self.validate()
        if self.paused or self.tp_refresh_required or self.progress.phase not in ("need_tp", "waiting_tp"):
            raise ValueError("이미 아이템 사용 대기/검수 중이거나 세션 정지 상태입니다.")
        if (evidence.run_id is not None or self.pending_free_item_id is None
                or item_id != self.pending_free_item_id):
            raise ValueError("직전에 검토한 무료 TP 아이템이 아닙니다.")
        self._accept(evidence, "item_used")
        self.last_free_item_id = item_id
        self.pending_free_item_id = None
        self.tp_refresh_required = True
        return self.validate()

    def confirm_tp_refresh(self, evidence: SessionEvidence, tp: TPView):
        self.validate()
        if self.paused or not self.tp_refresh_required or evidence.run_id is not None:
            raise ValueError("TP 재검사 대기 상태가 아닙니다.")
        tp.validate()
        if not tp.verified or tp.tp is None or tp.cost is None:
            raise ValueError("최신 TP 재검증이 필요합니다.")
        self._accept(evidence, "tp_refresh")
        self.tp_refresh_required = False
        return self.validate()

    def confirm_run_started(self, evidence: SessionEvidence, tp_before: TPView):
        self.validate()
        if self.paused or self.tp_refresh_required or evidence.run_id is None:
            raise ValueError("게임 실행 준비/확인이 필요합니다.")
        # Require the unique game evidence before accepting this run, without
        # mutating if TP observation is stale or insufficient.
        evidence.validate(self.progress.config)
        if evidence.kind != "start" or evidence.evidence_id in self.evidence_ids:
            raise ValueError("실제 육성 시작 증거가 없습니다.")
        self.progress.begin(evidence.run_id, tp_before)
        self.pending_free_item_id = None
        self._accept(evidence, "start")
        return self.validate()

    def confirm_run_finished(self, evidence: SessionEvidence, outcome: str):
        self.validate()
        if (self.paused or self.progress.phase != "in_run" or
                evidence.run_id != self.progress.pending_run_id):
            raise ValueError("동일 육성의 완료 화면이 필요합니다.")
        evidence.validate(self.progress.config)
        if evidence.kind != "finish" or evidence.evidence_id in self.evidence_ids:
            raise ValueError("실제 종료 화면 검증이 필요합니다.")
        self.progress.finish(evidence.run_id, outcome, verified=True)
        self._accept(evidence, "finish")
        return self.validate()

    def halt(self, reason: str):
        self.validate()
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("중단 사유가 필요합니다.")
        self.paused = True
        self.pending_free_item_id = None
        self.pause_reason = reason[:500]
        return self.validate()

    def resume_after_review(self, evidence: SessionEvidence):
        self.validate()
        if not self.paused or self.progress.phase in ("setup", "finished"):
            raise ValueError("재개할 수 있는 상태가 아닙니다.")
        if self.progress.phase == "in_run":
            if evidence.run_id != self.progress.pending_run_id:
                raise ValueError("진행 중이던 육성과 화면 ID가 다릅니다.")
        elif evidence.run_id is not None:
            raise ValueError("다음 육성을 시작하기 전 게임 초기 화면 확인 필요")
        self._accept(evidence, "resume")
        self.paused = False
        self.pause_reason = ""
        return self.validate()

    def as_json(self):
        self.validate()
        return {
            "schema": SCHEMA, "progress": self.progress.as_json(),
            "paused": self.paused, "pause_reason": self.pause_reason,
            "tp_refresh_required": self.tp_refresh_required,
            "evidence_ids": list(self.evidence_ids),
            "last_free_item_id": self.last_free_item_id,
            "pending_free_item_id": self.pending_free_item_id,
            "game_input_allowed": False,
        }


def save_session(path, session: CultivationSession):
    """A new R44 file; never overwrites legacy R40 progress or old user data."""
    data = session.as_json()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".uma_r44_session_", suffix=".tmp",
                                dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_session(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("R44 세션 파일 크기/경로 확인 필요")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("R44 세션 버전 불일치")
    if data.get("game_input_allowed") is not False:
        raise ValueError("게임 자동 실행 상태는 허용되지 않습니다.")
    session = CultivationSession(
        progress=restore_progress(data["progress"]),
        paused=data["paused"], pause_reason=data["pause_reason"],
        tp_refresh_required=data["tp_refresh_required"],
        evidence_ids=data["evidence_ids"],
        last_free_item_id=data["last_free_item_id"],
        pending_free_item_id=data.get("pending_free_item_id"),
    ).validate()
    # Restart ALWAYS halts. It is never safe to assume that a previously
    # active game/window/batch is still in the same state after a crash.
    session.halt("재시작 후 게임 상태/선택한 캐릭터·덱·계승/진행 중 ID 재검증 필요")
    return session
