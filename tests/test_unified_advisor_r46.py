"""R46 source-only contract tests; no game window, no AI training, no click."""
from __future__ import annotations
from dataclasses import asdict, replace
import unittest

from decision_contract_r39 import SkillCondition
from intent_gate_r42 import ObservedFrame
from race_outing_r38 import CharacterCalendar, RaceGoal, ScreenTurn
from skill_budget_r42 import SkillOffer
from support_events_r40 import EventEvidence
from target_selector_r39 import Target, kind_for_round
from turn_policy_r40 import TurnEvidence, TurnOption
from unified_advisor_r46 import (
    DecisionInput, EventRequest, SkillRequest, UnifiedAdvisor, companion_readiness,
)


def goal():
    return Target(kind_for_round(2),2,"추입")


def frame(n=1,scene="훈련",labels=("스피드 훈련","일반 레이스","휴식"),
          source="reviewed_game_screenshot",turn_id="junior-1"):
    return ObservedFrame(42,"r46-run1",turn_id,scene,n,labels,source,True,True)


def context(next_race=False,verified=True):
    stats={s:150 for s in ("스피드","스태미나","파워","근성","지능")}
    targets={s:1000 for s in stats}
    return TurnEvidence(stats,targets,75,next_race,True,verified,
                        "reviewed_game_screenshot")


def options():
    return (TurnOption("스피드 훈련","training",{"스피드":80},verified=True),
            TurnOption("일반 레이스","race",skill_pt=20,verified=True),
            TurnOption("휴식","rest",energy_delta=15,verified=True))


def training(n=1,*,screen=None,calendar=None,ctx=None,opts=None):
    return DecisionInput(goal(),frame(n),
                         turn=context() if ctx is None else ctx,
                         options=options() if opts is None else opts,
                         screen_turn=screen,calendar=calendar)


def calendar_at(year="주니어",month=7,half="전반"):
    return CharacterCalendar("uma","uniform","KR","KR-2026",
                             "island_post_patch_v1","character_goal_curated",
                             (RaceGoal(year,month,half,"검증된 목표","race"),),True)


def screen_now(**kwargs):
    data=dict(character_id="uma",variant_id="uniform",server="KR",
              patch_version="KR-2026",scenario="island_post_patch_v1",
              year="주니어",month=7,half="전반",goal_screen_verified=True)
    data.update(kwargs)
    return ScreenTurn(**data)


class R46IntegrationTests(unittest.TestCase):
    def test_r56_provisional_research_does_not_set_r46_decision_or_click(self):
        from training_evidence_r55 import TrainingEvidenceView, TrainingOptionEvidence
        from ranker_strategy_r56 import StrategyContext
        from pathlib import Path
        opts=(TrainingOptionEvidence("스피드",(15,5,0,0,0)),)
        draft=TrainingEvidenceView("스피드",opts,1,0,"OCR 후보")
        engine=UnifiedAdvisor()
        out=engine.inspect_training_research(draft,StrategyContext())
        self.assertIsNone(engine.gate.pending)
        self.assertIsNone(engine.last_content_fingerprint)
        self.assertFalse(out.game_input_allowed)
        self.assertFalse(out.decision_ready)
        self.assertIn("1/5",out.label)

    def test_training_needs_two_stable_reviewed_frames(self):
        engine=UnifiedAdvisor()
        self.assertIsNone(engine.evaluate(training()).action)
        result=engine.evaluate(training(2))
        self.assertEqual(result.action,"스피드 훈련")
        self.assertTrue(result.ticket)
        self.assertFalse(result.game_input_allowed)
        self.assertFalse(result.optimality_verified)

    def test_pending_requires_reviewed_transition_and_blocks_new_proposal(self):
        engine=UnifiedAdvisor()
        engine.evaluate(training())
        ticket=engine.evaluate(training(2)).ticket
        self.assertIsNone(engine.evaluate(training(3)).action)
        after=frame(4,scene="훈련",labels=("다른 화면",),turn_id="junior-1")
        self.assertFalse(engine.acknowledge(after,ticket))
        after=frame(5,scene="이벤트",labels=("상","하"),turn_id="junior-1")
        self.assertTrue(engine.acknowledge(after,ticket))
        self.assertFalse(engine.acknowledge(after,ticket))

    def test_synthetic_candidate_never_recommended(self):
        source="synthetic_test"
        data=replace(training(),frame=frame(source=source))
        engine=UnifiedAdvisor()
        self.assertIsNone(engine.evaluate(data).action)
        self.assertIsNone(engine.evaluate(replace(data,frame=frame(2,source=source))).action)

    def test_missing_next_race_blocks_speculative_specialty_buff(self):
        special=(TurnOption("스피드 훈련","training",next_turn_training_bonus=70,verified=True),
                 TurnOption("일반 레이스","race",skill_pt=20,verified=True),
                 TurnOption("휴식","rest",verified=True))
        data=training(ctx=context(next_race=None),opts=special)
        result=UnifiedAdvisor().evaluate(data)
        self.assertIsNone(result.action)
        self.assertIn("특기율",result.reason)

    def test_current_mandatory_race_priority_requires_exact_button(self):
        opts=(TurnOption("스피드 훈련","training",{"스피드":120},verified=True),
              TurnOption("목표 레이스","race",verified=True),
              TurnOption("휴식","rest",energy_delta=60,verified=True))
        def data(n):
            return DecisionInput(goal(),frame(n,labels=tuple(o.name for o in opts)),
                                 turn=context(),options=opts,screen_turn=screen_now(),
                                 calendar=calendar_at())
        engine=UnifiedAdvisor()
        self.assertIsNone(engine.evaluate(data(1)).action)
        result=engine.evaluate(data(2))
        self.assertEqual(result.action,"목표 레이스")
        self.assertIn("필수 레이스",result.reason)

    def test_mandatory_race_missing_button_abstains(self):
        result=UnifiedAdvisor().evaluate(training(
            screen=screen_now(),calendar=calendar_at()))
        self.assertIsNone(result.action)
        self.assertIn("필수 목표 레이스 버튼",result.reason)

    def test_next_turn_race_conflict_abstains(self):
        data=training(screen=screen_now(),calendar=calendar_at(half="후반"),
                      ctx=context(next_race=False))
        result=UnifiedAdvisor().evaluate(data)
        self.assertIsNone(result.action)
        self.assertIn("충돌",result.reason)

    def test_island_facility_cost_not_silently_ignored(self):
        opts=(TurnOption("스피드 훈련","training",{"스피드":40},verified=True),
              TurnOption("섬 시설 강화","facility",{"스피드":100},verified=True),
              TurnOption("일반 레이스","race",skill_pt=10,verified=True))
        snap=DecisionInput(goal(),frame(labels=tuple(x.name for x in opts)),
                           turn=context(),options=opts)
        result=UnifiedAdvisor().evaluate(snap)
        self.assertIsNone(result.action)
        self.assertIn("발전 Pt",result.reason)

    def test_unverified_and_incomplete_actions_abstain(self):
        incomplete=replace(context(),all_actions_visible=False)
        self.assertIsNone(UnifiedAdvisor().evaluate(training(ctx=incomplete)).action)
        opt=list(options())
        opt[1]=replace(opt[1],verified=False)
        self.assertIsNone(UnifiedAdvisor().evaluate(training(opts=tuple(opt))).action)

    def event_case(self,n=1, missing=False):
        catalog={}
        for cid,path,ends,effects in (
            ("choiceA","GOLD",False,{"stamina":5}),
            ("choiceB","OTHER",False,{"energy":5}),
        ):
            ev=EventEvidence("KR","KR-2026","supportA","SSR",
                             "event1",2,cid,effects,ends,path,
                             True,True,"reviewed test fixture")
            catalog[ev.key]=asdict(ev)
        if missing:
            catalog.pop(next(iter(catalog)))
        event=EventRequest("KR","KR-2026","supportA","SSR","event1",2,
                           ("choiceA","choiceB"),"GOLD",catalog)
        return DecisionInput(goal(),frame(n,"이벤트",("choiceA","choiceB")),event=event)

    def test_reviewed_event_chain_unique_selection(self):
        engine=UnifiedAdvisor()
        self.assertIsNone(engine.evaluate(self.event_case()).action)
        res=engine.evaluate(self.event_case(2))
        self.assertEqual(res.action,"choiceA")
        self.assertFalse(res.game_input_allowed)

    def test_missing_catalog_branch_abstains(self):
        res=UnifiedAdvisor().evaluate(self.event_case(missing=True))
        self.assertIsNone(res.action)
        self.assertIn("모두 검수",res.reason)

    def skill_case(self,n=1, losses=2, budget=100):
        offers=(SkillOffer(SkillCondition("마일 추입",distance="마일",
                                         style="추입",verified=True),
                           80,50,price_verified=True,offered_on_screen=True),
                SkillOffer(SkillCondition("마일 도주",distance="마일",
                                         style="도주",verified=True),
                           40,100,price_verified=True,offered_on_screen=True))
        state=SkillRequest(offers,"추입","마일","잔디",budget,
                           losses,2,True,True)
        return DecisionInput(goal(),frame(n,"스킬",("마일 추입","마일 도주")),skill=state)

    def test_retry_skill_respects_budget_and_style(self):
        engine=UnifiedAdvisor()
        self.assertIsNone(engine.evaluate(self.skill_case()).action)
        res=engine.evaluate(self.skill_case(2))
        self.assertEqual(res.action,"마일 추입")
        self.assertIn("80Pt",res.reason)

    def test_midrun_skill_not_purchased_before_two_losses(self):
        self.assertIsNone(UnifiedAdvisor().evaluate(self.skill_case(losses=1)).action)
        self.assertIsNone(UnifiedAdvisor().evaluate(self.skill_case(budget=10)).action)

    def test_jp_tucker_reference_never_upgrades_to_kr_reward(self):
        view=screen_now(tucker_outing_unlocked=True,tucker_outing_stage=5,
                        tucker_4lb_confirmed=True,outing_screen_verified=True,
                        energy=60,energy_cap=100)
        data=training(screen=view,ctx=context())
        result=UnifiedAdvisor().evaluate(data)
        self.assertIsNone(result.action)
        self.assertTrue(any("일본" in x and "미검증" in x
                            for x in result.notes))
        self.assertFalse(result.optimality_verified)

    def test_scene_mismatch_and_jp_calendar_rejected(self):
        data=training()
        with self.assertRaises(ValueError):
            replace(data,frame=frame(scene="이벤트")).validate()
        jp=replace(calendar_at(),server="JP")
        with self.assertRaises(ValueError):
            replace(data,calendar=jp).validate()

    def test_r37_ocr_readiness_is_not_a_real_decision(self):
        msg=companion_readiness("훈련",goal_selected=True,ocr_candidate_count=4)
        self.assertIn("OCR 후보",msg)
        self.assertIn("검수 전",msg)


if __name__ == "__main__":
    unittest.main()
