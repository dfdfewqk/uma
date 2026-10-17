"""R49 fail-closed multi-run planner. Planning != game control.

Supports the requested entire phase sequence, but no action can become a game
click without an actual verified KR UI control + fresh post-action observation.
No premium TP/currency spending. Skill prices and conditions must be verified.
"""
from __future__ import annotations
from dataclasses import dataclass
from auto_core_r40 import TPView
from tp_strategy_r44 import FreeTPItem, plan_tp_step
from target_selector_r39 import STYLES

STAGES=("setup","tp","training","skill","result","repeat","unknown")
PLAN_ACTIONS=("verify","select_training","start_run","free_tp_item","wait_tp",
              "purchase_skill","finish_run","repeat_run","stop")


@dataclass(frozen=True)
class VerifiedOffer:
    label: str
    price: int
    priority: int
    eligible: bool
    reviewed: bool
    owned: bool = False

    def validate(self):
        if (not isinstance(self.label,str) or not self.label.strip() or
                type(self.price) is not int or not 1<=self.price<=10000 or
                type(self.priority) is not int or not 0<=self.priority<=1000 or
                any(type(x) is not bool for x in (self.eligible,self.reviewed,self.owned))):
            raise ValueError("스킬 가격/자격 검수 자료 오류")
        return self


@dataclass(frozen=True)
class StageObservation:
    stage: str
    evidence_id: str
    reviewed: bool
    stable_frames: int
    ui_actions: tuple[str,...] = ()
    tp: TPView | None = None
    items: tuple[FreeTPItem,...] | None = None
    skill_offers: tuple[VerifiedOffer,...] = ()
    skill_points: int | None = None
    completed_run_id: str | None = None
    completed_outcome: str | None = None

    def validate(self):
        if self.stage not in STAGES or not isinstance(self.evidence_id,str) or len(self.evidence_id)<8:
            raise ValueError("화면 상태/증거 식별값 오류")
        if type(self.reviewed) is not bool or type(self.stable_frames) is not int or self.stable_frames<0:
            raise ValueError("장면 검수 상태 오류")
        if (not isinstance(self.ui_actions,tuple) or len(set(self.ui_actions))!=len(self.ui_actions)
                or any(not isinstance(x,str) or not x for x in self.ui_actions)):
            raise ValueError("검수된 버튼 목록 오류")
        for offer in self.skill_offers: offer.validate()
        if (self.skill_points is not None and
                (type(self.skill_points) is not int or not 0<=self.skill_points<=100000)):
            raise ValueError("보유 스킬 Pt 오류")
        return self


@dataclass(frozen=True)
class StageAdvice:
    action: str
    target: str | None
    reason: str
    input_ready: bool = False
    automatic_clicked: bool = False


class BatchPlanner:
    """One action per observed frame. No unseen-success assumptions on restart."""
    def __init__(self, goal, repeats):
        goal.validate()
        if type(repeats) is not int or not 1<=repeats<=10000:
            raise ValueError("반복 횟수 오류")
        self.goal=goal
        self.repeats=repeats
        self.completed_ids=set()
        self.outcomes={}
        self.last_evidence_ids=set()
        self.pending=None  # (action, evidence_id, expected next stage)
        self.paused=True
        self.reason="실게임 장면/캐릭터/덱/계승 검수 전"

    def arm(self, *, setup_reviewed: bool, confirmed_run_setup: bool):
        if not (setup_reviewed is True and confirmed_run_setup is True):
            raise ValueError("게임 시작 구성 확인 전 자동 실행 불가")
        self.paused=False
        self.reason=""

    def halt(self, reason: str):
        self.paused=True
        self.pending=None
        self.reason=str(reason)[:300]

    def confirmed_transition(self, previous_evidence_id: str, current: StageObservation):
        current.validate()
        if self.pending is None or self.pending[1]!=previous_evidence_id:
            raise ValueError("확인할 자동 입력이 없습니다.")
        if not current.reviewed or current.stable_frames<2:
            raise ValueError("입력 뒤 실제 화면 전환 확인 필요")
        if current.evidence_id==previous_evidence_id:
            raise ValueError("기존 화면을 새 전환 결과로 처리할 수 없습니다.")
        self.pending=None

    @property
    def remaining(self):
        return self.repeats-len(self.completed_ids)

    def plan(self, obs: StageObservation, *, style: str,
             distance: str | None, surface: str | None,
             consecutive_losses: int = 0, remaining_retries: int = 0):
        obs.validate()
        if self.paused:
            return StageAdvice("stop",None,"자동 실행 중지: "+self.reason)
        if self.remaining<=0:
            return StageAdvice("stop",None,"설정한 육성 횟수 모두 완료")
        if not obs.reviewed or obs.stable_frames<2:
            return StageAdvice("verify",None,"현재 한국 서버 화면을 두 번 연속 검수해야 합니다.")
        if self.pending is not None:
            return StageAdvice("verify",None,"이전 게임 입력 후 새 장면 확인 대기")
        if style not in STYLES or style!=self.goal.style:
            return StageAdvice("verify",None,"설정 각질과 실제 육성 각질 재확인 필요")
        if obs.stage=="tp":
            if obs.tp is None:
                return StageAdvice("verify",None,"TP 숫자/무료 아이템 보유량 미확인")
            advice=plan_tp_step(obs.tp,obs.items)
            if advice.action=="use_free_tp_item":
                target="free_tp:"+str(advice.item_id)
                if target not in obs.ui_actions:
                    return StageAdvice("verify",None,"무료 회복 아이템 버튼의 실제 위치/상태 검수 필요")
                return StageAdvice("free_tp_item",target,advice.reason,True)
            if advice.action=="start_run":
                if "start_run" in obs.ui_actions:
                    return StageAdvice("start_run","start_run",advice.reason,True)
                return StageAdvice("verify",None,"육성 시작 버튼 화면 검수 필요")
            if advice.action=="wait_regen":
                return StageAdvice("wait_tp",None,advice.reason)
            return StageAdvice("verify",None,advice.reason)
        if obs.stage=="skill":
            if obs.skill_points is None or not obs.skill_offers:
                return StageAdvice("verify",None,"스킬 이름/가격/보유 Pt 검수 전")
            if not all(s.reviewed for s in obs.skill_offers):
                return StageAdvice("verify",None,"스킬 조건·가격 일부 미검수")
            eligible=[s for s in obs.skill_offers if s.eligible and not s.owned
                      and "skill:"+s.label in obs.ui_actions]
            eligible.sort(key=lambda s:(-s.priority,s.price,s.label))
            for skill in eligible:
                if skill.price<=obs.skill_points:
                    return StageAdvice("purchase_skill","skill:"+skill.label,
                                       "검수된 스킬 구매 후보 · 클릭 뒤 잔여 Pt/보유 여부 재확인",True)
            return StageAdvice("verify",None,"구매 가능한 검수 스킬 없음 · 선택 화면 보류")
        if obs.stage=="result":
            if (obs.completed_run_id is None or obs.completed_outcome not in
                    ("good","ordinary","disposed","failed")):
                return StageAdvice("verify",None,"동일 육성 결과 화면/결과 분류 확인 필요")
            if obs.completed_run_id in self.completed_ids:
                return StageAdvice("verify",None,"이미 종료한 육성을 다시 기록하지 않습니다.")
            return StageAdvice("finish_run",obs.completed_run_id,
                               "검수된 최종 육성 결과 기록 후보")
        if obs.stage=="repeat":
            if "repeat_run" not in obs.ui_actions:
                return StageAdvice("verify",None,"같은 캐릭터·덱·계승 재시작 버튼 화면 검수 전")
            return StageAdvice("repeat_run","repeat_run",
                               "기존 캐릭터·덱·계승을 재확인한 뒤 반복 육성",True)
        if obs.stage=="training":
            return StageAdvice("select_training",None,
                               "R48 훈련별 미리보기 5종을 우선 자동 탐색; 실전 효율 최적화 미검증")
        return StageAdvice("verify",None,"이벤트·시설·레이스·확인 팝업의 한국 화면 규칙 미등록")

    def record_finished(self, obs: StageObservation):
        if (not obs.reviewed or obs.stable_frames<2 or obs.stage!="result" or
                not obs.completed_run_id or obs.completed_outcome not in
                ("good","ordinary","disposed","failed") or
                obs.completed_run_id in self.completed_ids or self.remaining<=0):
            raise ValueError("실제 한국 서버 결과 확인 없이는 완료 횟수 집계 금지")
        self.completed_ids.add(obs.completed_run_id)
        self.outcomes[obs.completed_run_id]=obs.completed_outcome
        return self.remaining

    def record_click(self, proposal: StageAdvice, obs: StageObservation):
        if self.paused or not proposal.input_ready or not proposal.target or self.pending:
            raise ValueError("입력 상태 오류")
        if obs.evidence_id in self.last_evidence_ids:
            raise ValueError("동일 화면 입력 반복 차단")
        self.last_evidence_ids.add(obs.evidence_id)
        self.pending=(proposal.action,obs.evidence_id,obs.stage)
        return self.pending
