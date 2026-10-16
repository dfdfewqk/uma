"""R46 combined, strictly read-only turn recommendation orchestration.

Reuse R38 calendar/Tucker (JP reference only), R40 turn utility/event policy,
R42 skill cost and stable-frame gate, R44 observation adapter. No mouse input,
no model training, no simulated data promoted to reviewed Korean screenshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json

from intent_gate_r42 import IntentGate, ObservedFrame
from race_outing_r38 import CharacterCalendar, ScreenTurn, assess_turn, next_goal, RaceGoal
from skill_budget_r42 import SkillOffer, plan_retry_purchase
from target_selector_r39 import Target
from turn_policy_r40 import TurnEvidence, TurnOption, suggest_turn, score_option

TRUSTED = ("reviewed_game_screenshot", "reviewed_game_video")
TRAINABLE_KINDS = ("training", "race", "rest", "outing", "facility", "island")
SCHEMA = "uma_r46_readonly_decision_v1"


@dataclass(frozen=True)
class EventRequest:
    server: str
    patch: str
    card_id: str
    card_variant: str
    event_id: str
    stage: int
    choice_ids: tuple[str, ...]
    desired_gold_skill: str | None
    catalog: dict

    def validate(self, visible: tuple[str, ...]):
        if (self.server != "KR" or not all(isinstance(v, str) and v
                 for v in (self.patch, self.card_id, self.card_variant, self.event_id))):
            raise ValueError("이벤트 카드/서버/패치 확인 필요")
        if type(self.stage) is not int or not 1 <= self.stage <= 20:
            raise ValueError("서포트 연속 이벤트 단계 오류")
        if (not isinstance(self.choice_ids, tuple) or not self.choice_ids
                or self.choice_ids != visible or len(set(self.choice_ids)) != len(self.choice_ids)):
            raise ValueError("보이는 이벤트 선택지와 검수 목록이 불일치합니다.")
        if not isinstance(self.catalog, dict):
            raise ValueError("이벤트 카탈로그 형식 오류")
        if self.desired_gold_skill is not None and (not isinstance(self.desired_gold_skill, str)
                                                   or not self.desired_gold_skill.strip()):
            raise ValueError("목표 금색 스킬 ID 오류")
        return self


@dataclass(frozen=True)
class SkillRequest:
    offers: tuple[SkillOffer, ...]
    style: str
    distance: str | None
    surface: str | None
    skill_points: int | None
    consecutive_losses: int
    remaining_retries: int
    race_verified: bool
    page_verified: bool

    def validate(self):
        if not isinstance(self.offers, tuple) or len(self.offers) > 200:
            raise ValueError("스킬 목록 오류")
        for offer in self.offers:
            if not isinstance(offer, SkillOffer):
                raise ValueError("스킬 자료 형식 오류")
            offer.validate()
        return self


@dataclass(frozen=True)
class DecisionInput:
    goal: Target
    frame: ObservedFrame
    turn: TurnEvidence | None = None
    options: tuple[TurnOption, ...] = ()
    screen_turn: ScreenTurn | None = None
    calendar: CharacterCalendar | None = None
    event: EventRequest | None = None
    skill: SkillRequest | None = None

    def validate(self):
        self.goal.validate()
        self.frame.validate()
        if not isinstance(self.options, tuple) or len(self.options) > 25:
            raise ValueError("행동 목록 오류")
        for opt in self.options:
            if not isinstance(opt, TurnOption):
                raise ValueError("현재 행동 인식 자료 오류")
            opt.validate()
        if self.turn is not None:
            self.turn.validate()
        if self.screen_turn is not None:
            self.screen_turn.validate()
            if (self.screen_turn.server != "KR" or
                    self.screen_turn.scenario != self.goal.scenario):
                raise ValueError("일본/다른 시나리오 화면으로 한국 대회 판단 불가")
        if self.calendar is not None:
            self.calendar.validate()
            if self.calendar.server != "KR" or self.calendar.scenario != self.goal.scenario:
                raise ValueError("일본/다른 시나리오 달력은 한국 육성 판단에 사용할 수 없습니다.")
        if self.event is not None:
            self.event.validate(self.frame.action_labels)
        if self.skill is not None:
            self.skill.validate()
            if self.skill.style != self.goal.style:
                raise ValueError("선택 각질과 레이스 스킬 각질이 다릅니다.")
        if self.frame.scene == "훈련":
            if (self.turn is None or not self.options or self.event is not None
                    or self.skill is not None):
                raise ValueError("훈련 장면 자료가 누락/혼합됐습니다.")
            if (tuple(opt.name for opt in self.options) != self.frame.action_labels or
                    any(opt.kind not in TRAINABLE_KINDS for opt in self.options)):
                raise ValueError("화면의 모든 훈련·휴식·레이스·외출·시설 후보가 일치해야 합니다.")
        elif self.frame.scene == "이벤트":
            if self.event is None or self.options or self.skill is not None:
                raise ValueError("이벤트 화면 자료 누락/혼합")
        elif self.frame.scene == "스킬":
            if self.skill is None or self.options or self.event is not None:
                raise ValueError("스킬 화면 자료 누락/혼합")
        elif self.options or self.event is not None or self.skill is not None:
            raise ValueError("다른 장면에 잘못된 선택지를 연결했습니다.")
        return self


@dataclass(frozen=True)
class Decision:
    action: str | None
    reason: str
    notes: tuple[str, ...] = ()
    ranked: tuple[tuple[str, float], ...] = ()
    ticket: str | None = None
    game_input_allowed: bool = False
    optimality_verified: bool = False
    source: str = "reviewed_screen_only"


def _matched_calendar(data: DecisionInput):
    """Return only a calendar whose exact character, variant, patch match a KR frame."""
    view, cal = data.screen_turn, data.calendar
    if (view is None or cal is None or not view.goal_screen_verified or
            view.year is None or not cal.complete or not cal.goals or
            view.character_id != cal.character_id or
            view.variant_id != cal.variant_id or view.patch_version != cal.patch_version or
            view.server != cal.server or view.scenario != cal.scenario):
        return None, None, None
    observed = RaceGoal(view.year, view.month, view.half, "현재 위치", "other")
    goal, delta = next_goal(observed, cal)
    return cal, goal, delta


def _calendar_notes(data: DecisionInput):
    if data.screen_turn is None:
        return ("캐릭터별 실제 한국 서버 목표 레이스/터커 단계 확인 전",), None
    cal, goal, delta = _matched_calendar(data)
    # R38 only adds JP Tucker figures as non-authoritative reference notes.
    advisory = assess_turn(data.screen_turn, cal)
    return advisory.messages, delta if goal is not None and goal.kind == "race" else None


def _event_action(request: EventRequest):
    """All on-screen choices need exact previously reviewed KR catalogue entries.

    The gold target must identify ONE verified continuing or awarded branch.
    Conflicting/missing support events cannot produce a suggestion.
    """
    from support_events_r40 import EventEvidence
    if request.desired_gold_skill is None:
        return None, "목표 금색 스킬/이벤트 보상이 확정되지 않아 선택 보류"
    eligible = []
    for choice_id in request.choice_ids:
        key = "|".join((request.server, request.patch, request.card_id,
                        request.card_variant, request.event_id, str(request.stage), choice_id))
        row = request.catalog.get(key)
        if not isinstance(row, dict):
            return None, "해당 카드·패치·연속 이벤트의 선택지가 모두 검수되지 않았습니다."
        try:
            ev = EventEvidence(**row).validate()
        except (ValueError, TypeError, KeyError):
            return None, "이벤트 증거 구조가 손상됐습니다."
        if ev.key != key or not ev.reviewed or ev.server != "KR":
            return None, "실제 한국 서버 보상 결과까지 검수된 선택지가 아닙니다."
        if ev.gold_skill_path != request.desired_gold_skill:
            continue
        if not ev.chain_ends or ev.effects.get("gold_skill_awarded") is True:
            eligible.append(choice_id)
    if len(eligible) != 1:
        return None, "목표 금색 스킬로 이어지는 고유한 검수 선택지가 없습니다."
    return eligible[0], "한국 서버 카드 이벤트 연속/금색 스킬 경로의 검수 기록에 근거"


class UnifiedAdvisor:
    """Read-only dispatcher, one proposed action per sufficiently reviewed scene."""
    def __init__(self):
        self.gate = IntentGate()
        self.last_content_fingerprint = None

    def suspend(self):
        self.gate.stop()
        self.last_content_fingerprint = None

    def acknowledge(self, frame: ObservedFrame, ticket: str) -> bool:
        frame.validate()
        if frame.source not in TRUSTED:
            return False
        ok = self.gate.acknowledge(frame, ticket)
        if ok:
            self.last_content_fingerprint = None
        return ok

    def evaluate(self, data: DecisionInput) -> Decision:
        data.validate()
        frame = data.frame
        # A proposed action must remain pending until a reviewed scene
        # transition is acknowledged (or the user explicitly suspends).
        if self.gate.pending is not None:
            return Decision(None, "이전 행동의 실제 화면 전환 확인 대기 · 중복 제안 보류")
        if frame.source not in TRUSTED or not frame.reviewed or not frame.active:
            self.suspend()
            return Decision(None, "한국 서버 활성 게임 화면에서 검수한 자료가 아닙니다.")
        if data.screen_turn is not None and data.screen_turn.server != "KR":
            self.suspend()
            return Decision(None, "한국 서버 자료가 아닙니다.")
        notes, next_race_delta = _calendar_notes(data)
        action, reason, ranked = None, "", ()
        if frame.scene == "훈련":
            turn = data.turn
            if (not turn.verified or turn.source != frame.source or
                    not turn.all_actions_visible or any(not x.verified for x in data.options)):
                self.suspend()
                return Decision(None, "화면의 모든 행동 효과/보상 검수 전 · 추천 보류", tuple(notes))
            # Island/facility choices can consume development points or tickets;
            # R40 TurnOption does not yet model these costs. Do not compare them
            # as if resource spending were free, even with verified stat gains.
            if any(o.kind in ("facility", "island") for o in data.options):
                self.suspend()
                return Decision(None, "시설/섬 행동의 발전 Pt·티켓 소모 및 기회비용 검증 전 · 통합 순위 보류",
                                tuple(notes))
            if next_race_delta in (0, 1):
                if next_race_delta == 1 and turn.next_turn_mandatory_race is False:
                    self.suspend()
                    return Decision(None, "다음 턴 필수 레이스와 달력 관측값이 충돌합니다.", tuple(notes))
                if next_race_delta == 0 and turn.next_turn_mandatory_race is True:
                    self.suspend()
                    return Decision(None, "현재/다음 턴 레이스 인식이 불일치합니다.", tuple(notes))
            if next_race_delta is None and turn.next_turn_mandatory_race is None:
                if any(x.next_turn_training_bonus > 0 for x in data.options):
                    self.suspend()
                    return Decision(None, "필수 레이스 일정 확인 전 · 1턴 특기율 가치를 비교하지 않습니다.", tuple(notes))
            if next_race_delta == 0:
                matches = [o for o in data.options if o.kind == "race" and o.name == "목표 레이스"]
                if len(matches) != 1:
                    self.suspend()
                    return Decision(None, "현재 필수 목표 레이스 버튼을 유일하게 확인하지 못했습니다.", tuple(notes))
                action, reason = matches[0].name, "실제 한국 서버에서 검수된 이번 턴 필수 레이스 우선"
            else:
                if next_race_delta == 1 and turn.next_turn_mandatory_race is None:
                    turn = replace(turn, next_turn_mandatory_race=True)
                suggestion = suggest_turn(turn, list(data.options))
                action, reason, ranked = suggestion.action, suggestion.reason, suggestion.scores
        elif frame.scene == "이벤트":
            action, reason = _event_action(data.event)
        elif frame.scene == "스킬":
            req = data.skill
            plan = plan_retry_purchase(
                list(req.offers), style=req.style, distance=req.distance,
                surface=req.surface, skill_points=req.skill_points,
                consecutive_losses=req.consecutive_losses,
                remaining_retries=req.remaining_retries, current_race_verified=req.race_verified,
                skill_page_verified=req.page_verified)
            if plan.skills:
                action = plan.skills[0]
                reason = "재도전용 스킬 후보 · 총 {}Pt 이내에서 최대 {}개: {}".format(
                    plan.total_sp, len(plan.skills), ", ".join(plan.skills))
            else:
                reason = plan.reason
        else:
            reason = "해당 장면의 보상/선택지 판단은 아직 검수되지 않았습니다."
        if action is None:
            self.suspend()
            return Decision(None, reason, tuple(notes), ranked)
        if action not in frame.action_labels:
            self.suspend()
            return Decision(None, "추천 후보가 현재 화면 선택지에 없습니다.", tuple(notes), ranked)
        # Avoid reusing a stable-frame count if scoring/schedule or target changes
        # despite identical labels. The signature excludes frame_number.
        content = {
            "target":(data.goal.scenario, data.goal.round, data.goal.style),
            "run":frame.run_id, "turn":frame.turn_id, "scene":frame.scene,
            "labels":frame.action_labels, "source":frame.source,
            "action":action, "note":reason, "scores":ranked,
            "stats":data.turn.stats if data.turn is not None else None,
            "energy":data.turn.energy if data.turn is not None else None,
            "next_race":next_race_delta,
        }
        signature = hashlib.sha256(json.dumps(content,ensure_ascii=False,
                 sort_keys=True,default=str).encode("utf-8")).hexdigest()
        if self.last_content_fingerprint != signature:
            self.suspend()
            self.last_content_fingerprint = signature
        proposal, wait_reason = self.gate.propose(frame, action)
        if proposal is None:
            return Decision(None, wait_reason, tuple(notes), ranked)
        return Decision(action, reason + " · 게임에서는 직접 확인/선택",
                        tuple(notes), ranked, ticket=proposal.ticket)


def companion_readiness(scene: str, *, goal_selected: bool,
                        ocr_candidate_count: int = 0) -> str:
    """Read-only status for the CURRENT R37 OCR pipeline.

    Existing OCR stats are candidates, not reviewed per-action rewards.
    This function NEVER upgrades them to a UnifiedAdvisor decision.
    """
    if not goal_selected:
        return "R46: 대회·각질 목표를 선택해야 턴별 추천을 준비할 수 있습니다."
    if scene == "훈련":
        if ocr_candidate_count:
            return "R46: 현재 스탯은 OCR 후보 · 훈련/외출/시설/레이스의 개별 보상 검수 전"
        return "R46: 훈련·레이스·외출·시설 효과를 비교할 검수된 관측값 대기"
    if scene == "이벤트":
        return "R46: 카드 ID·패치·선택지 결과를 검수한 뒤 금색 스킬 경로 비교"
    if scene == "스킬":
        return "R46: 코스·각질·가격·보유 스킬을 검수하기 전 구매 추천 보류"
    if scene in ("레이스", "외출", "시설", "휴식"):
        return "R46: 캐릭터 일정·터커 단계·현재 선택지 보상 검수 전"
    return "R46: 현재 장면과 행동 후보가 확인되지 않아 통합 추천 보류"
