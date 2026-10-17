"""R50 visual-to-R49 stage adapter and fail-closed batch execution supervisor.

The adapter is only useful after the user has calibrated actual Korean client
templates and numeric ROIs. It never fakes missing TP prices, skill cost, turn
results, or learning outcomes. Unknown scenes stop the supervised run.

Click approval is not granted by a screenshot alone: R49 BatchPlanner must
return input_ready for the exact UI control and numeric evidence. Every click
sets a pending transition; item use, skill Pt and completed run counts are
only committed after a distinct stable observed result.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import time
import uuid

from auto_core_r40 import TPView
from batch_planner_r49 import BatchPlanner,StageObservation,StageAdvice,VerifiedOffer
from numeric_observer_r50 import StableNumberReader
from registered_pointer_r50 import SceneTicket,RegisteredScenePointer,SceneClickBlocked
from tp_strategy_r44 import FreeTPItem
from visual_controls_r50 import unique_scene


@dataclass(frozen=True)
class LivePacket:
    stage: str | None
    observation: StageObservation | None
    controls: tuple
    numbers: dict
    note: str
    confidence: int = 0


class VisualStageAdapter:
    def __init__(self):
        self.reader=StableNumberReader()
        self.last=None
        self.count=0

    def reset(self):
        self.reader.reset()
        self.last=None
        self.count=0

    def observe(self,image,window_key,profiles,rois,ocr_binary,
                *, run_id=None,skill_scope_reviewed=False,goal_scope="",skill_approvals=(),cycle=0):
        stage,controls=unique_scene(image,profiles)
        if stage is None:
            self.reset()
            return LivePacket(None,None,(),{},"장면 표식·버튼 등록 부족 또는 장면 중복",0)
        from visual_controls_r50 import recognize
        names=tuple(sorted(c.action for c in controls))
        nums=self.reader.observe(stage,image,rois,ocr_binary,window_key)
        # Same TP/skill pixels recur between separate cultivations. Bind
        # reviewed evidence to the batch cycle and active run, so the second
        # run cannot replay the first run's evidence or be rejected as a
        # duplicate solely because numeric values happen to match.
        if type(cycle) is not int or cycle<0 or cycle>10000:
            raise ValueError("육성 회차 컨텍스트 오류")
        key=(stage,window_key,image.size,names,tuple(sorted(nums.items())),
             cycle,run_id or "before-start")
        if key==self.last:
            self.count=min(self.count+1,20)
        else:
            self.last=key
            self.count=1
        e=hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
        reviewed=self.count>=2
        tp=None
        items=None
        offers=()
        sp=None
        outcome=None
        if stage=="tp":
            required=("tp","tp_cost","tp_cap")
            if all(k in nums for k in required):
                tp=TPView(nums["tp"],nums["tp_cost"],
                          nums.get("free_item_count"),nums.get("free_item_recovery"),
                          reviewed,nums["tp_cap"])
                item_profiles=[p for p in profiles if p.stage=="tp" and
                               p.action in names and p.action.startswith("free_tp:")]
                # More than one potential free item needs a separate per-item
                # quantity/recovery observation; don't silently reuse same OCR.
                if len(item_profiles)==1 and item_profiles[0].free_only and all(
                    k in nums for k in ("free_item_count","free_item_recovery")):
                    it=item_profiles[0]
                    items=(FreeTPItem(it.action[len("free_tp:"):],
                                    nums["free_item_count"],nums["free_item_recovery"],
                                    True,reviewed),)
                elif not item_profiles:
                    items=()
        if stage=="skill":
            if skill_scope_reviewed and all(k in nums for k in
                     ("skill_points","skill_price")):
                sp=nums["skill_points"]
                visible=[c for c in controls if c.action.startswith("skill:")]
                matching=[c for c in visible if any(
                          p.identity==c.profile_identity and
                          p.target_scope==goal_scope and goal_scope
                          for p in profiles)]
                if (len(visible)==1 and len(matching)==1 and
                    matching[0].action[len("skill:"):] in skill_approvals):
                    label=matching[0].action[len("skill:"):]
                    offers=(VerifiedOffer(label,nums["skill_price"],100,
                                          True,reviewed,False),)
        if stage=="result":
            distinct={c.action.removeprefix("finish_run:") for c in controls
                      if c.action.startswith("finish_run:")}
            if len(distinct)==1 and run_id:
                outcome=next(iter(distinct))
        # result/run identity requires a previously observed actual run start,
        # not a fresh UUID made from a detected completion screen.
        obs=StageObservation(stage,e,reviewed,self.count,names,tp,items,
                             offers,sp,run_id if outcome else None,outcome)
        return LivePacket(stage,obs,controls,nums,
              "등록된 화면/버튼 확인 · 실제 값 OCR "+str(len(nums))+"개"
              +(" · 안정화 완료" if reviewed else " · 연속 프레임 재확인 중"),
              self.count)


class LiveBatchSupervisor:
    """No background control thread. Caller drives it on reviewed GUI frames."""
    def __init__(self,goal,repeats,*,dry_run=True,clock=time.monotonic):
        self.planner=BatchPlanner(goal,repeats)
        self.pointer=RegisteredScenePointer(dry_run=dry_run,clock=clock)
        self.clock=clock
        self.adapter=VisualStageAdapter()
        self.active_run_id=None
        self.awaiting=None
        self.last_frame_key=None
        self.event_log=[]
        self.skill_scope_reviewed=False
        self.skill_approvals=frozenset()
        self.purchased_skills=set()  # No repeated same-skill purchase per actual run.
        self.character_setup_reviewed=False

    @property
    def armed(self):
        return not self.planner.paused

    def arm(self,*,setup_reviewed,character_deck_inheritance_reviewed,
            skill_scope_reviewed=False):
        self.planner.arm(setup_reviewed=setup_reviewed,
                         confirmed_run_setup=character_deck_inheritance_reviewed)
        self.character_setup_reviewed=True
        self.skill_scope_reviewed=(skill_scope_reviewed is True)

    def halt(self,reason):
        self.planner.halt(reason)
        self.awaiting=None
        self.adapter.reset()

    def _log(self,event):
        self.event_log.append(str(event)[:170])
        if len(self.event_log)>100:
            self.event_log=self.event_log[-50:]

    def confirm_training_start(self):
        """Call only after TWO actual stable training scenes following start click."""
        p=self.awaiting
        if p is None or p["action"]!="start_run":
            return False
        if self.clock()-p["when"]>45:
            self.halt("육성 시작 후 훈련 화면 확인 시간 초과")
            return False
        self.active_run_id="kr-"+uuid.uuid4().hex
        self.awaiting=None
        self.planner.pending=None
        self.purchased_skills.clear()
        self._log("새 육성의 훈련 화면 재확인 · 진행 ID 생성")
        return True

    def _witness_after_click(self, packet:LivePacket):
        pending=self.awaiting
        if pending is None:
            return False
        if self.clock()-pending["when"]>45:
            self.halt("클릭 후 새 화면/수치 확인 제한시간 초과")
            return False
        obs=packet.observation
        if obs is None or not obs.reviewed:
            return False
        after=packet.numbers
        before=pending["numbers"]
        action=pending["action"]
        changed=False
        if action=="free_tp_item":
            changed=(packet.stage=="tp" and
                     after.get("tp",-1)>before.get("tp",100000) and
                     after.get("free_item_count",100000)<before.get("free_item_count",-1))
        elif action=="purchase_skill":
            price=pending.get("expected_skill_price")
            changed=(packet.stage=="skill" and type(price) is int and
                     price>0 and "skill_points" in after and
                     "skill_points" in before and
                     before["skill_points"]-after["skill_points"]==price)
        elif action=="finish_run":
            changed=(packet.stage in ("repeat","setup","tp") and
                     pending.get("run_id") is not None)
        elif action=="repeat_run":
            changed=packet.stage in ("setup","tp") and obs.evidence_id!=pending["evidence"]
        elif action=="start_run":
            return False
        if not changed:
            return False
        # The R49 pending state is only cleared upon verified distinct evidence.
        if obs.evidence_id==pending["evidence"]:
            return False
        self.planner.confirmed_transition(pending["evidence"],obs)
        if action=="finish_run":
            origin=pending["result_observation"]
            self.planner.record_finished(origin)
            self.active_run_id=None
            self._log("검수한 결과+다음 화면 확인 후 완료 1회 반영")
        elif action=="repeat_run":
            self._log("반복 버튼 클릭 후 시작 화면 확인")
        elif action=="purchase_skill":
            self.purchased_skills.add(pending["skill_label"])
            self._log("검수된 스킬 Pt 정확 감소 · 같은 스킬 반복 구매 차단")
        else:
            self._log(action+" 이후 실제 수치/장면 변화 확인")
        self.awaiting=None
        return True

    def decision(self,packet,*,style,distance=None,surface=None):
        if not self.armed:
            return StageAdvice("stop",None,"자동 실행이 활성화되지 않았습니다.")
        if self.awaiting is not None:
            if self._witness_after_click(packet):
                if self.planner.remaining<=0:
                    self.halt("설정한 육성 횟수 완료")
                    return StageAdvice("stop",None,"모든 육성 완료")
            else:
                return StageAdvice("verify",None,"직전 조작 후 화면/수치 변화 확인 대기")
        obs=packet.observation
        if obs is None:
            return StageAdvice("verify",None,packet.note)
        return self.planner.plan(obs,style=style,distance=distance,surface=surface)

    def click(self,advice,packet,image,profiles,*,hwnd,rect,approved):
        obs=packet.observation
        if not self.armed or self.awaiting is not None or obs is None:
            raise SceneClickBlocked("자동 실행/이전 전환 확인 상태 오류")
        if advice.action not in ("free_tp_item","purchase_skill",
                                 "start_run","repeat_run","finish_run"):
            raise SceneClickBlocked("실제 클릭할 수 없는 계획 결과")
        if advice.action=="finish_run":
            if (packet.stage!="result" or not obs.reviewed or
                    obs.completed_run_id!=self.active_run_id or
                    obs.completed_outcome is None):
                raise SceneClickBlocked("종료한 실제 육성 ID/결과 검수 필요")
            target="finish_run:"+obs.completed_outcome
        else:
            if not advice.input_ready:
                raise SceneClickBlocked("숫자/조작 준비 상태 불충분")
            target=advice.target
        matches=[c for c in packet.controls if c.action==target]
        if len(matches)!=1:
            raise SceneClickBlocked("화면에서 등록된 버튼을 한 개로 확인할 수 없습니다.")
        if advice.action=="purchase_skill":
            if not self.active_run_id:
                raise SceneClickBlocked("현재 육성 ID가 확인되지 않아 스킬 구매 금지")
            skill_name=target.removeprefix("skill:")
            if (not self.skill_scope_reviewed or
                skill_name not in self.skill_approvals):
                raise SceneClickBlocked("해당 스킬의 한국 서버 적성 검수/대회 승인 누락")
            if skill_name in self.purchased_skills:
                raise SceneClickBlocked("이미 구매한 스킬의 반복 구매 차단")
            eligible=[x for x in obs.skill_offers if x.label==skill_name and
                       x.reviewed and x.eligible and not x.owned and
                       x.price<=obs.skill_points]
            if len(eligible)!=1:
                raise SceneClickBlocked("현재 스킬 가격/잔여 Pt/적성 재확인 필요")
        if advice.action=="start_run" and self.active_run_id is not None:
            raise SceneClickBlocked("이전 육성 종료 결과를 확인하기 전 시작 금지")
        if advice.action=="repeat_run" and (not self.character_setup_reviewed or
                                             self.planner.remaining<=0):
            raise SceneClickBlocked("이전 캐릭터·덱·계승/반복 횟수 검증 필요")
        profile=next((p for p in profiles if p.identity==matches[0].profile_identity),None)
        if profile is None:
            raise SceneClickBlocked("등록된 화면 템플릿 누락")
        per_run_token=obs.evidence_id+"|run-"+str(len(self.planner.completed_ids))+"|"+str(self.active_run_id or "setup")
        ticket=SceneTicket(hwnd,rect,profile.identity,obs.stage,target,
            self.clock(),per_run_token,approved,obs.reviewed,
            free_confirmed=profile.free_only)
        sent=self.pointer.click(ticket,image,profiles)
        if sent:
            if advice.action=="finish_run":
                if self.planner.pending is not None:
                    raise SceneClickBlocked("기존 대기 중인 입력이 있습니다.")
                self.planner.pending=("finish_run",obs.evidence_id,obs.stage)
            else:
                self.planner.record_click(advice,obs)
            self.awaiting=dict(action=advice.action,evidence=obs.evidence_id,
                  numbers=dict(packet.numbers),when=self.clock(),
                  result_observation=obs,run_id=self.active_run_id,
                  skill_label=(skill_name if advice.action=="purchase_skill" else None),
                  expected_skill_price=(eligible[0].price if advice.action=="purchase_skill" else None))
            self._log("실제 클릭: "+advice.action+" · 결과 확인 전 대기")
        return sent
