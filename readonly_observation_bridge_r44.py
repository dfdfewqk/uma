"""R44 typed read-only adapter for future reviewed KR screenshot observations.

No OCR interpretation is invented here. This accepts already reviewed action
options only, and it cannot click the game or create verified learning labels.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json

from intent_gate_r42 import IntentGate, ObservedFrame
from target_selector_r39 import Target
from turn_policy_r40 import TurnEvidence, TurnOption, suggest_turn

VALID_SOURCES = frozenset(("reviewed_game_screenshot", "reviewed_game_video",
                           "screen_candidate", "synthetic_test"))
SCENES = frozenset(("훈련", "레이스", "시설", "스킬", "이벤트", "외출",
                    "휴식", "육성완료", "TP회복"))


@dataclass(frozen=True)
class ReviewedTurnSnapshot:
    window_id: int
    run_id: str
    turn_id: str
    frame_number: int
    scene: str
    source: str
    active: bool
    reviewed: bool
    target: Target
    stats: dict[str, int]
    goals: dict[str, int]
    energy: int
    next_mandatory_race: bool | None
    all_options_visible: bool
    options: tuple[TurnOption, ...]

    def validate(self):
        self.target.validate()
        if (self.scene not in SCENES or self.source not in VALID_SOURCES or
                type(self.active) is not bool or type(self.reviewed) is not bool or
                type(self.all_options_visible) is not bool):
            raise ValueError("화면 유형/검증 상태 오류")
        if not isinstance(self.options, tuple) or len(self.options) > 25:
            raise ValueError("선택지 형식/수량 오류")
        if len({o.name for o in self.options}) != len(self.options):
            raise ValueError("중복 선택지")
        for option in self.options:
            if not isinstance(option, TurnOption):
                raise ValueError("행동 자료가 없습니다.")
            option.validate()
        # Delegates all numeric/race-condition validation to R40.
        TurnEvidence(self.stats, self.goals, self.energy,
                     self.next_mandatory_race,
                     self.all_options_visible, self.reviewed,
                     self.source).validate()
        self.as_frame().validate()
        return self

    def as_frame(self):
        return ObservedFrame(
            window_id=self.window_id, run_id=self.run_id,
            turn_id=self.turn_id, scene=self.scene,
            frame_number=self.frame_number,
            action_labels=tuple(o.name for o in self.options),
            source=self.source, active=self.active, reviewed=self.reviewed)

    def fingerprint(self):
        self.validate()
        normalized = {
            "window":self.window_id, "run":self.run_id, "turn":self.turn_id,
            "scene":self.scene, "source":self.source, "target":asdict(self.target),
            "stats":self.stats, "goals":self.goals, "energy":self.energy,
            "mandatory_race":self.next_mandatory_race,
            "complete":self.all_options_visible,
            "options":[asdict(o) for o in self.options],
        }
        raw=json.dumps(normalized,sort_keys=True,ensure_ascii=False,
                       separators=(',',':'),allow_nan=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReadOnlyAdvice:
    action: str | None
    reason: str
    proposal_ticket: str | None = None
    game_input_allowed: bool = False
    verified_optimal: bool = False


class ReadOnlyTurnAdvisor:
    """Requires TWO stable reviewed snapshots; no actual game controls."""
    def __init__(self):
        self.gate = IntentGate()
        self.last_signature = None

    def observe(self, snapshot: ReviewedTurnSnapshot) -> ReadOnlyAdvice:
        snapshot.validate()
        if (snapshot.source not in ("reviewed_game_screenshot","reviewed_game_video") or
                not snapshot.reviewed or not snapshot.active):
            self.gate.stop()
            self.last_signature = None
            return ReadOnlyAdvice(None,"게임 화면 원본/활성 상태 검수 전 · 추천 보류")
        if snapshot.scene != "훈련":
            self.gate.stop()
            self.last_signature = None
            return ReadOnlyAdvice(None,"해당 장면의 행동 효과 카탈로그 검수 전 · 추천 보류")
        signature = snapshot.fingerprint()
        if signature != self.last_signature:
            self.gate.stop()
            self.last_signature = signature
        ctx=TurnEvidence(snapshot.stats,snapshot.goals,snapshot.energy,
                         snapshot.next_mandatory_race,
                         snapshot.all_options_visible, snapshot.reviewed,
                         snapshot.source)
        suggestion=suggest_turn(ctx,list(snapshot.options))
        if suggestion.action is None:
            self.gate.stop()
            return ReadOnlyAdvice(None,suggestion.reason)
        proposal,reason=self.gate.propose(snapshot.as_frame(),suggestion.action)
        if proposal is None:
            return ReadOnlyAdvice(None,reason)
        return ReadOnlyAdvice(suggestion.action,suggestion.reason,
                              proposal_ticket=proposal.ticket)

    def observe_transition(self, frame: ObservedFrame, ticket: str) -> bool:
        """Accept any next verified scene, without requiring training-screen stats."""
        frame.validate()
        if frame.source not in ("reviewed_game_screenshot","reviewed_game_video"):
            return False
        acknowledged=self.gate.acknowledge(frame,ticket)
        if acknowledged:
            self.last_signature=None
        return acknowledged

    def suspend(self):
        self.gate.stop()
        self.last_signature=None
