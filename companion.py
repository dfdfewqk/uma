"""Uma Trainer KR companion: read-only preview plus opt-in registered-scene experiments.
Run 'python companion.py --demo' to see layout without the game.
"""
from __future__ import annotations

# Validate a packaged EXE before importing tkinter or any GUI-heavy modules.
import sys as _uma_startup_sys
if __name__ == '__main__' and '--self-check-report' in _uma_startup_sys.argv[1:]:
    from package_selftest_r25 import maybe_run_cli as _uma_early_selfcheck
    _uma_early_selfcheck('UmaTrainerKR_Companion')
if __name__ == '__main__' and '--first-run-report' in _uma_startup_sys.argv[1:]:
    from runtime_probe_r26 import maybe_run_cli as _uma_early_first_run
    _uma_early_first_run()
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from companion_core import choose_window, usable_ocr_values
from helper_view_r37 import view_from_frame, paused_view, StableLowEnergy
from target_selector_r39 import (Target, STYLES, round_label, kind_for_round,
                                 read_target, save_target, load_courses, course_for)
from planning_prefs_r44 import (Preferences, REPEAT_CHOICES,
                                load_preferences, save_preferences, describe_plan)
from session_dashboard_r45 import read_dashboard
from unified_advisor_r46 import UnifiedAdvisor, companion_readiness
from training_preview_r48 import PreviewCollector, selected_training, portrait_supported, _turn_signature
from training_evidence_r55 import TrainingEvidenceCollector
from ranker_strategy_r56 import StrategyContext
from training_tour_r49 import TrainingTour
from training_transition_r57 import TrainingClickGuard
from foreground_click_r49 import ForegroundWindowsPointer, AutoInputBlocked
from batch_planner_r49 import BatchPlanner
from setup_preflight_r58 import audit_setup
from setup_choices_r59 import StableSetupChoices, SetupChoiceView, load_choices
from outcome_learning_r49 import inspect_record_counts
from autopilot_bridge_r50 import LiveBatchSupervisor
from visual_controls_r50 import load_profiles
from numeric_observer_r50 import load_rois
from skill_authorizations_r51 import load_authorizations,approved_skill_labels
from batch_checkpoint_r50 import (
    current_snapshot,save_checkpoint,load_checkpoint,restore_finished_only,
)
from capture_pack_r29 import (CaptureError, SCENES, MAX_CAPTURES, check_capture_target, new_pack,
                              store_capture, load_pack, export_pack)
from screen_r4 import user_dir
from live_state_r24 import FreshnessGate, rectangles_overlap
from companion_window import discover_windows
from recommendation_bridge_r28 import load_handoff, HintGate, HandoffError
from game_overlay_r28 import TrainingOverlay
from portable_update_r30 import check_latest, download_portable, UpdateError, CURRENT_VERSION
from scene_recognition_r20 import StableScene, load_library, profile_path as scene_profile_path
from scene_fusion_r53 import StableScreenFusion, STAGE_SCENES
from passive_numbers_r54 import StableLiveNumberReader, read_regions as read_passive_numbers
from visual_controls_r50 import unique_scene
from button_detection_r21 import StableButtons, load_patterns, path_default as button_pattern_path, DetectionError, DetectorUnavailable

BG='#0D1524'; CARD='#17243B'; TEXT='#EFF6FF'; MUTED='#9DAFC5'; AQUA='#6DDCCB'; YELLOW='#F9C56B'
STATS=('스피드','스태미나','파워','근성','지능')

class Companion(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.demo=demo
        self.title(f'Uma Trainer KR v{CURRENT_VERSION} · 클릭형 헬퍼')
        self.geometry('344x790+750+75')
        self.minsize(310,680)
        self.configure(bg=BG)
        self.scroll_canvas=tk.Canvas(self,bg=BG,highlightthickness=0,borderwidth=0)
        self.scrollbar=tk.Scrollbar(self,orient='vertical',command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right',fill='y')
        self.scroll_canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.scroll_canvas,bg=BG)
        body_id=self.scroll_canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda event:self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox('all')))
        self.scroll_canvas.bind('<Configure>',lambda event:self.scroll_canvas.itemconfigure(body_id,width=event.width))
        self.attributes('-topmost', False)  # User can move the panel, game stays visible.
        self.game=None
        self.reading=False
        self.last_capture=0
        self.q=queue.Queue()
        self.update_queue=queue.Queue()
        self.update_release=None
        self.update_busy=False
        self.update_status=tk.StringVar(value=f'R50 화면 등록/검증형 자동화 시범 · v{CURRENT_VERSION} · 미등록 화면 중지')
        self.event_var=tk.StringVar(value='')
        self.target_round=tk.StringVar(value='')
        self.target_style=tk.StringVar(value='')
        self.target_status=tk.StringVar(value='통합 대회 1~4회차와 각질을 선택하세요.')
        self.repeat_var=tk.StringVar(value='20회')
        self.session_status=tk.StringVar(value='저장된 육성 기록 확인 전')
        self.session_counts=tk.StringVar(value='진행 횟수 미확인')
        self.session_breakdown=tk.StringVar(value='고점 — · 평범 — · 도축 — · 실패 —')
        self.session_note=tk.StringVar(value='기존 기록을 읽은 뒤 표시합니다.')
        self.session_progress=tk.DoubleVar(value=0)
        self.session_progressbar=None
        self.repeat_preferences=Preferences()
        self.repeat_error=''
        try:
            self.repeat_preferences=load_preferences(user_dir()/'planning_preferences_r44.json')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.repeat_error='반복 설정 확인 필요: '+str(exc)[:50]
        self.repeat_var.set(str(self.repeat_preferences.repeats)+'회')
        self.target_error=''
        self.current_target=None
        try:
            self.known_courses=load_courses()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.known_courses={}
            self.target_error='코스 데이터 오류: '+str(exc)[:60]
        try:
            self.current_target=read_target(user_dir()/'helper_target_r39.json')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.target_error='목표 설정 파일 확인 필요: '+str(exc)[:60]
        if self.current_target is not None:
            self.event_var.set(self.current_target.kind)
            self.target_round.set(round_label(self.current_target.round))
            self.target_style.set(self.current_target.style)
        self.topmost_var=tk.BooleanVar(value=False)
        self.monitoring=True
        self.helper_switch=None
        self.dev_visible=False
        self.dev_panel=None
        self.status=tk.StringVar(value='게임 창 찾는 중…')
        self.detail=tk.StringVar(value='게임을 실행하면 자동으로 창을 찾습니다.')
        self.action=tk.StringVar(value='게임 화면 자동 확인 중')
        self.reason=tk.StringVar(value='육성 중 입력할 필요 없습니다. 확인되지 않은 화면에서는 추천을 보류합니다.')
        self.scene_info=tk.StringVar(value='화면 유형: 확인 전 (R20 기준 화면 필요)')
        self.scene_tracker=StableScene()
        self.scene_fusion=StableScreenFusion()
        self.setup_choice_tracker=StableSetupChoices()
        self.setup_choices_status=tk.StringVar(value='R59 육성 시작 선택지 · 기본/이벤트 등록 대기')
        self.numeric_reader=StableLiveNumberReader()
        self.numeric_status=tk.StringVar(value='R54 숫자 영역 미등록 · 검수 전 OCR 후보만 표시')
        self.failure_rate=tk.StringVar(value='—')
        self.island_tickets=tk.StringVar(value='—')
        self.development_points=tk.StringVar(value='—')
        self.hint_gate=HintGate()
        self.hint_overlay=TrainingOverlay(self)
        self.button_tracker=StableButtons()
        self.button_patterns=[]
        self.button_info=tk.StringVar(value='훈련 버튼 자동 확인 대기')
        self.r28_info=tk.StringVar(value='훈련 추천: 화면 확인·검수 전')
        self.r46_status=tk.StringVar(value='R46 통합 추천: 실제 턴별 보상 검수 전')
        self.unified_advisor=UnifiedAdvisor()
        self.preview_collector=PreviewCollector()
        self.training_evidence=TrainingEvidenceCollector()
        self.training_evidence_info=tk.StringVar(
            value='R55 훈련별 보상 수집 0/5 · 우정/인연 정보 미검수')
        self.ranker_strategy_info=tk.StringVar(
            value='R56 전략 비교 대기 · JP 공략 참고, KR 실제 턴 검수 필요')
        self.autotour=TrainingTour()
        self.training_click_guard=TrainingClickGuard()
        self.autopointer=ForegroundWindowsPointer(dry_run=(os.name!='nt'))
        self.auto_status=tk.StringVar(value='자동 훈련 실험 꺼짐 · TP/스킬/반복 조작 미검증')
        self.learning_status=tk.StringVar(value='실제 턴 전후 검수 기록 확인 전')
        self.batch_coordinator=None
        self.full_batch=None
        self.r50_profiles=()
        self.r50_rois=()
        self.r51_skill_approvals=frozenset()
        self.r50_status=tk.StringVar(value='R50 TP·스킬·종료/반복 버튼 등록 대기 · 실전 검증 전')
        self.r50_training_frames=0
        self.auto_confirmed_risk=False
        self.preview_info=tk.StringVar(value='R48 게임 훈련 미리보기 탐색 대기 · 0/5')
        self.capture_label=tk.StringVar(value='훈련')
        self.capture_pack=None
        self.capture_pending=False
        self.scene_anchors=[]
        self.last_hwnd=None
        self.freshness=FreshnessGate()
        self.low_energy=StableLowEnergy()
        self.statvals={name:tk.StringVar(value='—') for name in STATS}
        self.energy=tk.StringVar(value='—')
        self.skill=tk.StringVar(value='—')
        self._draw()
        self._target_changed(persist=False)
        self._refresh_learning_status()
        self.after(300,self._update_poll)
        if getattr(sys, 'frozen', False) and os.name == 'nt':
            self.after(2600,self._check_updates)
            self.after(24*60*60*1000,self._periodic_update_check)
        else:
            self.update_status.set('소스 실행 · 자동 교체는 Windows 포터블 EXE에서 지원')
        if self.demo:
            self.status.set('시연 화면 · 실제 게임 아님')
            self.detail.set('이 화면은 원하는 사용 방식의 UI 프로토타입입니다.')
            for n,v in zip(STATS,('1,201','873','1,098','777','1,005')):
                self.statvals[n].set(v)
            self.energy.set('62'); self.skill.set('1,245')
            self.scene_info.set('화면 유형: 시연 화면 (실제 감지 아님)')
            self.action.set('스피드 훈련 · 표시 예시')
            self.reason.set('실제 추천 아님 · 게임 연동 후 검증 필요')
        else:
            self.after(350,self._poll)
            self.after(1300,self._scan)

    def _label(self,parent,text,fg=MUTED,size=10,weight='normal'):
        return tk.Label(parent,text=text,bg=parent['bg'],fg=fg,
            font=('Malgun Gothic' if os.name=='nt' else 'DejaVu Sans',size,weight),anchor='w')

    def _card(self):
        f=tk.Frame(self.body,bg=CARD,padx=12,pady=9,highlightthickness=1,highlightbackground='#22334E')
        f.pack(fill='x',padx=12,pady=(0,9))
        return f

    def _draw(self):
        top=tk.Frame(self.body,bg=BG,padx=14,pady=13);top.pack(fill='x')
        self._label(top,'Uma Trainer KR',TEXT,17,'bold').pack(anchor='w')
        self._label(top,'창 제목 표시줄로 이동 가능 · 게임 화면을 가리지 않게 배치',MUTED,9).pack(anchor='w',pady=(2,2))
        tk.Checkbutton(top,text='항상 위에 표시 (선택)',variable=self.topmost_var,
                 command=self._toggle_topmost,selectcolor=CARD,bg=BG,fg=TEXT,
                 activebackground=BG,activeforeground=TEXT,
                 font=('Malgun Gothic',9)).pack(anchor='w')
        c=self._card()
        self._label(c,'게임 연결',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.status,fg=TEXT,bg=CARD,anchor='w',font=('Malgun Gothic',10,'bold'),wraplength=290,justify='left').pack(anchor='w',pady=(5,1))
        tk.Label(c,textvariable=self.detail,fg=MUTED,bg=CARD,anchor='w',font=('Malgun Gothic',8),wraplength=290,justify='left').pack(anchor='w')
        c=self._card()
        self._label(c,'지금 할 일 · 게임에서 직접 누르세요',AQUA,11,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.action,bg=CARD,fg=YELLOW,
                 font=('Malgun Gothic',14,'bold'),anchor='w',
                 wraplength=290,justify='left').pack(anchor='w',pady=(7,4))
        tk.Label(c,textvariable=self.reason,bg=CARD,fg=TEXT,
                 font=('Malgun Gothic',9),wraplength=290,
                 justify='left',anchor='w').pack(anchor='w',pady=(0,4))
        tk.Label(c,textvariable=self.preview_info,bg=CARD,fg=AQUA,
                 font=('Malgun Gothic',9),wraplength=290,
                 justify='left',anchor='w').pack(anchor='w',pady=(0,4))
        tk.Label(c,textvariable=self.training_evidence_info,bg=CARD,fg=MUTED,
                 font=('Malgun Gothic',8),wraplength=290,
                 justify='left',anchor='w').pack(anchor='w',pady=(0,4))
        tk.Label(c,textvariable=self.ranker_strategy_info,bg=CARD,fg=MUTED,
                 font=('Malgun Gothic',8),wraplength=290,
                 justify='left',anchor='w').pack(anchor='w',pady=(0,4))
        self.helper_switch=tk.Button(c,text='화면 분석 일시 정지',command=self._helper,
                 bg='#226F83',fg='white',relief='flat')
        self.helper_switch.pack(fill='x',pady=(8,1))
        self._label(c,'기본은 직접 클릭. 실험 자동화에서는 사용자 등록/검증 화면에서만 입력합니다.',
                    MUTED,8).pack(anchor='w',pady=(5,0))

        c=self._card()
        self._label(c,'자동 훈련 탐색 · 실험 기능',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.auto_status,bg=CARD,fg=YELLOW,
                 wraplength=290,justify='left',anchor='w',
                 font=('Malgun Gothic',9)).pack(anchor='w',pady=(4,6))
        tk.Button(c,text='자동 훈련 탐색 시작 (OCR 잠정 후보 사용)',
                  command=self._start_autotour,bg='#24637D',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,3))
        tk.Button(c,text='자동 조작 즉시 중단',
                  command=self._stop_all_automation,bg='#7D3545',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,3))
        tk.Label(c,textvariable=self.r50_status,bg=CARD,fg=MUTED,
                 wraplength=290,anchor='w',justify='left',
                 font=('Malgun Gothic',8)).pack(anchor='w',pady=(3,4))
        tk.Button(c,text='R50 게임 화면·TP/스킬 숫자 한 번 등록',
                  command=self._open_r50_calibration,
                  bg='#355174',fg=TEXT,relief='flat').pack(fill='x',pady=2)
        tk.Button(c,text='R58 육성 시작 준비 점검 (클릭 없음)',
                  command=self._check_setup_preflight,
                  bg='#355174',fg=TEXT,relief='flat').pack(fill='x',pady=2)
        tk.Button(c,text='등록된 화면만 반복 자동 실행 (실험)',
                  command=self._start_full_batch,
                  bg='#245a54',fg=TEXT,relief='flat').pack(fill='x',pady=2)
        self._label(c,'미등록 이벤트·레이스·시설·결과에서는 안전 중지. '
                  '자동화 신뢰도 실게임 미검증 · 유료 TP/주얼 결제 금지.',
                  MUTED,8).pack(anchor='w')

        c=self._card()
        self._label(c,'실제 결과 기반 학습 · 검수 기록',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.learning_status,bg=CARD,fg=MUTED,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=(4,4))
        tk.Button(c,text='실제 검수 학습 데이터 상태 다시 확인',
                  command=self._refresh_learning_status,bg='#263754',
                  fg=TEXT,relief='flat').pack(fill='x')
        self._label(c,'잠정 OCR 후보·합성자료는 학습 정답이 아닙니다.',
                    MUTED,8).pack(anchor='w',pady=(5,0))

        c=self._card()
        self._label(c,'육성 목표 · 처음에 클릭으로 선택',AQUA,10,'bold').pack(anchor='w')
        self._label(c,'시나리오: 무인도 (6/30 조정 이후)',MUTED,9).pack(anchor='w',pady=(4,4))
        for caption,variable,values in (
            ('통합 대회 회차',self.target_round,tuple(round_label(n) for n in range(1,5))),
            ('각질',self.target_style,STYLES),
            ('반복 육성 횟수',self.repeat_var,tuple(str(n)+'회' for n in REPEAT_CHOICES))):
            self._label(c,caption,MUTED,8).pack(anchor='w',pady=(2,1))
            selector=ttk.Combobox(c,values=values,textvariable=variable,
                                  state='readonly',takefocus=True)
            selector.pack(fill='x',pady=(0,2))
            selector.bind('<<ComboboxSelected>>',self._repeat_changed if variable is self.repeat_var else self._target_changed)
            if variable is self.repeat_var:
                selector.bind('<FocusOut>',self._repeat_changed)
                selector.bind('<Return>',self._repeat_changed)
        tk.Label(c,textvariable=self.target_status,bg=CARD,fg=TEXT,
                 wraplength=290,justify='left',anchor='w').pack(anchor='w',pady=(6,2))
        self._label(c,'회차가 챔미·리오히를 자동 결정합니다. 반복 횟수는 계획만 저장합니다.',
                    MUTED,8).pack(anchor='w')

        c=self._card()
        self._label(c,'자동 육성 현황 · 저장된 기록만',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.session_status,bg=CARD,fg=YELLOW,
                 font=('Malgun Gothic',10,'bold'),anchor='w',wraplength=290,
                 justify='left').pack(anchor='w',pady=(5,3))
        tk.Label(c,textvariable=self.session_counts,bg=CARD,fg=TEXT,
                 font=('Malgun Gothic',10,'bold'),anchor='w',wraplength=290,
                 justify='left').pack(anchor='w',pady=(0,3))
        self.session_progressbar=ttk.Progressbar(c,orient='horizontal',mode='determinate',
                                      maximum=100,variable=self.session_progress)
        self.session_progressbar.pack(fill='x',pady=(1,6))
        self.session_breakdown_label=tk.Label(c,textvariable=self.session_breakdown,
                 bg=CARD,fg=MUTED,font=('Malgun Gothic',8),anchor='w',
                 wraplength=290,justify='left')
        self.session_breakdown_label.pack(anchor='w',pady=(0,3))
        tk.Label(c,textvariable=self.session_note,bg=CARD,fg=MUTED,
                 font=('Malgun Gothic',8),anchor='w',wraplength=290,
                 justify='left').pack(anchor='w',pady=(0,6))
        tk.Button(c,text='저장된 진행 기록 다시 확인',
                  command=self._refresh_session_dashboard,bg='#263754',
                  fg=TEXT,relief='flat').pack(fill='x',pady=(2,2))
        self._label(c,'게임 조작·자동 재개는 아직 미연결이며, 이 화면은 조회 전용입니다.',
                    MUTED,8).pack(anchor='w',pady=(4,0))

        c=self._card()
        self._label(c,'게임 화면 자동 확인',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.scene_info,bg=CARD,fg=TEXT,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=(5,2))
        tk.Label(c,textvariable=self.setup_choices_status,bg=CARD,fg=AQUA,
                 anchor='w',wraplength=290,justify='left',
                 font=('Malgun Gothic',8)).pack(anchor='w',pady=(2,3))
        tk.Label(c,textvariable=self.button_info,bg=CARD,fg=MUTED,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=2)
        tk.Label(c,textvariable=self.r28_info,bg=CARD,fg=MUTED,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=(0,4))
        tk.Label(c,textvariable=self.r46_status,bg=CARD,fg=AQUA,
                 anchor='w',wraplength=290,justify='left',
                 font=('Malgun Gothic',8)).pack(anchor='w',pady=(2,4))

        c=self._card()
        self._label(c,'현재 수치 · 자동 관측 후보',AQUA,10,'bold').pack(anchor='w',pady=(0,6))
        grid=tk.Frame(c,bg=CARD);grid.pack(fill='x')
        for i,k in enumerate(STATS):
            box=tk.Frame(grid,bg=CARD)
            box.grid(row=i//3,column=i%3,sticky='w',padx=(0,17),pady=(0,5))
            self._label(box,k,MUTED,8).pack(anchor='w')
            tk.Label(box,textvariable=self.statvals[k],bg=CARD,fg=TEXT,
                     font=('Malgun Gothic',10,'bold')).pack(anchor='w')
        info=tk.Frame(c,bg=CARD);info.pack(fill='x',pady=(2,0))
        self._label(info,'체력 ',MUTED,9).pack(side='left')
        tk.Label(info,textvariable=self.energy,bg=CARD,fg=TEXT).pack(side='left')
        self._label(info,'      스킬 Pt ',MUTED,9).pack(side='left')
        tk.Label(info,textvariable=self.skill,bg=CARD,fg=TEXT).pack(side='left')
        extra=tk.Frame(c,bg=CARD);extra.pack(fill='x',pady=(3,1))
        for caption,variable in (('실패율 ',self.failure_rate),
                                 ('  섬 티켓 ',self.island_tickets),
                                 ('  발전 Pt ',self.development_points)):
            self._label(extra,caption,MUTED,8).pack(side='left')
            tk.Label(extra,textvariable=variable,bg=CARD,fg=TEXT,
                     font=('Malgun Gothic',8)).pack(side='left')
        tk.Label(c,textvariable=self.numeric_status,bg=CARD,fg=MUTED,
                 wraplength=290,anchor='w',justify='left').pack(anchor='w',pady=(3,2))
        self._label(c,'* 표시는 검수 전 OCR 후보 · 화면 전환 시 자동으로 지움',
                    MUTED,8).pack(anchor='w',pady=(5,0))

        tools=tk.Frame(self.body,bg=BG)
        tools.pack(fill='x',padx=12,pady=(0,9))
        tk.Button(tools,text='설정·개발자 점검 보기 (평소 사용 불필요)',
                  command=self._toggle_dev_tools,bg='#263754',fg=TEXT,
                  relief='flat').pack(fill='x')
        self.dev_panel=tk.Frame(self.body,bg=BG)
        advanced=self.dev_panel
        settings=tk.Frame(advanced,bg=CARD,padx=12,pady=9)
        settings.pack(fill='x',padx=12,pady=(0,9))
        self._label(settings,'육성 목표는 상단의 클릭형 대회·회차·각질 메뉴에서 변경합니다.',
                    MUTED,9).pack(anchor='w')

        row=tk.Frame(advanced,bg=BG)
        row.pack(fill='x',padx=12,pady=(0,5))
        tk.Button(row,text='실게임 훈련 점검 · R22',command=self._launch_game_test,
                  bg='#247368',fg='white',relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='R23 · 게임 없이 사전점검',
                  command=self._launch_preflight,bg='#345778',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,5))
        self._label(row,'2단계 · 실제 화면 자료 수집 (로컬/검수 전)',AQUA,9,'bold').pack(anchor='w',pady=(3,2))
        ttk.Combobox(row,values=SCENES,textvariable=self.capture_label,
                     state='readonly').pack(fill='x',pady=(0,4))
        self._label(row,'훈련·TP·스킬·레이스·이벤트·종료 화면을 선택해 저장합니다. '
                    '화면 종류는 수동 선택이며 AI가 자동 판별한 결과가 아닙니다.',
                    MUTED,8).pack(anchor='w',pady=(0,4))
        tk.Button(row,text='4초 뒤 게임 화면 저장 · 게임 창으로 돌아가기',
                  command=self._schedule_capture,bg='#346075',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,4))
        tk.Button(row,text='저장된 화면 ZIP 내보내기 (직접 선택)',
                  command=self._export_capture_pack,bg='#344766',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='R53 화면 종류 기준 등록 · 고유 영역 2개',
                  command=self._open_r53_passive_scene_registration,bg='#355174',
                  fg=TEXT,relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='R54 숫자 OCR 영역 등록 · 화면별 숫자 하나',
                  command=self._open_r54_numeric_registration,bg='#355174',
                  fg=TEXT,relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='R59 육성 시작 선택지 등록 · 일반/이벤트',
                  command=self._open_r59_setup_registration,bg='#355174',
                  fg=TEXT,relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='상세 설정·자료 관리 열기',
                  command=self._launch_advanced,bg='#263754',fg=TEXT,
                  relief='flat').pack(fill='x')

        u=tk.Frame(advanced,bg=CARD,padx=12,pady=9)
        u.pack(fill='x',padx=12,pady=(0,9))
        self._label(u,'무설치 프로그램 업데이트',AQUA,10,'bold').pack(anchor='w')
        tk.Label(u,textvariable=self.update_status,bg=CARD,fg=TEXT,
                 wraplength=290,justify='left',anchor='w').pack(anchor='w',pady=(5,4))
        self.update_check_button=tk.Button(u,text='GitHub 최신 버전 확인',
                     command=self._check_updates,bg='#345778',fg=TEXT,relief='flat')
        self.update_check_button.pack(fill='x',pady=(0,4))
        self.update_install_button=tk.Button(u,text='새 포터블 버전 받기 및 실행',
                     command=self._download_update,state='disabled',relief='flat')
        self.update_install_button.pack(fill='x')
        self._label(u,'기존 버전·기록 보존',MUTED,8).pack(anchor='w',pady=(5,0))
        self._label(advanced,'고급 점검은 실게임 인식 검증을 위한 개발 도구이며 육성 중 필요하지 않습니다.',
                    MUTED,8).pack(anchor='w',padx=14,pady=(0,8))

    def _refresh_learning_status(self):
        if self.current_target is None:
            self.learning_status.set('대회/각질 목표 미선택 · 학습 상태 보류')
            return
        try:
            groups=inspect_record_counts(user_dir()/'r49_reviewed_turns.json',
                                         self.current_target.scenario)
            total=sum(v['turns'] for v in groups.values())
            runs=sum(v['runs'] for v in groups.values())
            self.learning_status.set('검수된 실게임 '+str(total)+'턴 / '+str(runs)+
                  '회 육성 · 패치 '+str(len(groups))+
                  '종 분리. 검수된 결과가 부족하면 학습 미적용')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.learning_status.set('학습 원본 손상/버전 불일치 · 데이터 보존: '+str(exc)[:90])

    def _open_r50_calibration(self):
        """Explicit user-reviewed Korean game button/number ROI registration."""
        from calibration_ui_r50 import CalibrationWindow
        CalibrationWindow(self)

    def _open_r53_passive_scene_registration(self):
        """User-controlled, passive scene fingerprint calibration only."""
        from passive_scene_ui_r53 import PassiveSceneRegistration
        PassiveSceneRegistration(self)

    def _open_r54_numeric_registration(self):
        from passive_numbers_ui_r54 import PassiveNumberRegistration
        PassiveNumberRegistration(self)

    def _open_r59_setup_registration(self):
        from setup_choices_ui_r59 import SetupChoiceRegistration
        SetupChoiceRegistration(self)

    def _stop_all_automation(self):
        self._stop_autotour()
        if self.full_batch is not None:
            self.full_batch.halt('사용자가 자동 조작을 중단했습니다.')
        self.r50_status.set('R50 중지됨 · 자동 클릭/반복 없음')
        self.r51_skill_approvals=frozenset()

    def _save_r50_progress(self):
        if self.full_batch is not None:
            save_checkpoint(user_dir()/'r50_batch_progress.json',
                            current_snapshot(self.full_batch))

    def _check_setup_preflight(self):
        """Explain missing setup/TP/result registrations; never control game."""
        try:
            profiles=load_profiles(user_dir()/'r50_visual_controls.json')
            rois=load_rois(user_dir()/'r50_numeric_rois.json')
            report=audit_setup(profiles,rois)
            self.r50_status.set(report.summary)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.r50_status.set('R58 사전 점검 오류: '+str(exc)[:170])

    def _start_full_batch(self):
        """Only live, registered and opt-in scenes may be clicked."""
        if self.demo or os.name!='nt' or not self.monitoring or self.current_target is None:
            self.r50_status.set('Windows 게임/목표/감시 상태 확인 전 자동 실행할 수 없습니다.')
            return
        try:
            prof=load_profiles(user_dir()/'r50_visual_controls.json')
            rois=load_rois(user_dir()/'r50_numeric_rois.json')
            auth=load_authorizations(user_dir()/'r51_skill_authorizations.json')
            preflight=audit_setup(prof,rois)
            if not preflight.ready_for_manual_review:
                raise ValueError(preflight.summary)
            stages={x.stage for x in prof}
            course=course_for(self.current_target,self.known_courses)
            scope=self.current_target.key+":"+self.current_target.style
            signed=approved_skill_labels(auth,scope)
            actual_skills={x.action.removeprefix("skill:") for x in prof if
                           x.stage=="skill" and x.target_scope==scope}
            signed=signed.intersection(actual_skills)
            skills_ready=(course is not None and 'skill' in stages and
                          bool(signed) and
                          {'skill_points','skill_price'}.issubset(
                           {x.field for x in rois if x.stage=='skill'}))
            notice=('R58 등록 점검을 통과했지만 실제 게임 설정을 자동 검증한 것은 아닙니다.\n'
                    '현재 게임에서 아래 네 가지를 모두 직접 확인했습니까?\n'
                    '1. 육성 캐릭터·복장\n'
                    '2. 서포트 덱 구성\n'
                    '3. 계승 부모 및 설정\n'
                    '4. 육성 목표 각질\n'
                    '육성 준비 화면 자동 선택은 아직 지원되지 않습니다.\n'
                    '미등록 이벤트·레이스·시설에서 중지합니다. 유료 TP/주얼 결제는 금지합니다.\n'
                    '직접 확인한 경우에만 실험 자동 실행을 시작하시겠습니까?')
            if not messagebox.askyesno('R50 실험적 자동 육성 동의',notice,parent=self):
                return
            self._stop_all_automation()
            self.r50_profiles=prof
            self.r50_rois=rois
            # Reapply authorizations AFTER stop() clears the previous session.
            self.r51_skill_approvals=signed if skills_ready else frozenset()
            new_runner=LiveBatchSupervisor(self.current_target,
                            self.repeat_preferences.repeats,dry_run=False)
            existing=load_checkpoint(user_dir()/'r50_batch_progress.json',
                                      self.current_target,self.repeat_preferences.repeats)
            if existing is not None:
                restore_finished_only(new_runner,existing)
                if new_runner.planner.remaining<=0:
                    self.r50_status.set('R50 저장된 반복 횟수가 이미 완료됐습니다.')
                    return
            self.full_batch=new_runner
            self.full_batch.arm(setup_reviewed=True,
                 character_deck_inheritance_reviewed=True,
                 skill_scope_reviewed=skills_ready)
            self.full_batch.skill_approvals=self.r51_skill_approvals
            self._save_r50_progress()
            self.preview_collector.reset()
            self.r50_training_frames=0
            self.r50_status.set('R50 실험 활성 · 등록된 장면/숫자 검증 중 · 게임 창으로 돌아가세요.')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.r50_status.set('R50 준비 보류: '+str(exc)[:145])

    def _run_r50_on_frame(self,packet,scene,preview,hwnd,rect,screen):
        batch=self.full_batch
        if batch is None or not batch.armed:
            return
        if screen.status == 'conflict':
            batch.halt('R20·R50·R48 장면 인식 결과 충돌')
            self.autotour.stop()
            self.auto_confirmed_risk=False
            self.r50_status.set('R53 안전 중지: 서로 다른 화면으로 인식되어 클릭하지 않습니다.')
            return
        if screen.status == 'waiting':
            return
        if packet is not None and packet.stage is not None and scene != STAGE_SCENES[packet.stage]:
            batch.halt('자동 실행 장면과 화면 인식 결과가 불일치합니다.')
            self.r50_status.set('R53 안전 중지: 장면 불일치')
            return
        if not rect or self.current_target is None or batch.planner.goal!=self.current_target:
            batch.halt('게임 창/육성 목표가 변경돼 자동 실행을 중단했습니다.')
            return
        if batch.planner.repeats!=self.repeat_preferences.repeats:
            batch.halt('반복 목표 횟수가 변경돼 자동 실행을 중단했습니다.')
            return
        if batch.awaiting is not None and batch.awaiting['action']=='start_run':
            if scene=='훈련' and preview is not None and preview.selected:
                self.r50_training_frames+=1
                if self.r50_training_frames>=2 and batch.confirm_training_start():
                    self._save_r50_progress()
                    self.autotour.start()
                    self.auto_confirmed_risk=True
                    self.r50_status.set('R50 실제 훈련 화면 확인 · 자동 미리보기 탐색')
            else:
                self.r50_training_frames=0
            return
        if scene=='훈련':
            if batch.awaiting is not None:
                batch.halt('이전 TP/스킬/종료 버튼의 결과 확인 전 훈련 화면으로 이동')
                self.r50_status.set('R50 안전 중지 · 이전 입력의 결과 재검수 필요')
                return
            if not self.autotour.enabled:
                self.autotour.start()
                self.auto_confirmed_risk=True
            return
        if packet is None or packet.stage is None:
            batch.halt('현재 장면 미등록 · 이벤트/레이스 등 수동 검수 필요')
            self.autotour.stop()
            self.auto_confirmed_risk=False
            self.r50_status.set('R50 안전 정지: 미등록 장면이므로 버튼을 누르지 않습니다.')
            return
        c=course_for(self.current_target,self.known_courses)
        try:
            advice=batch.decision(packet,style=self.current_target.style,
                                  distance=(c['distance'] if c else None),
                                  surface=(c['surface'] if c else None))
            self._save_r50_progress()
            self.r50_status.set('R50 '+packet.stage+' · '+advice.reason[:115])
            if advice.action=='stop':
                batch.halt(advice.reason)
                return
            if advice.action not in ('start_run','free_tp_item',
                     'purchase_skill','finish_run','repeat_run'):
                return
            from PIL import ImageGrab
            import ctypes
            if ctypes.windll.user32.GetForegroundWindow()!=hwnd:
                return
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            sent=batch.click(advice,packet,image,self.r50_profiles,
                              hwnd=hwnd,rect=rect,approved=True)
            if sent:
                self._save_r50_progress()
                self.r50_status.set('R50 '+advice.action+
                    ' 클릭 · 다음 화면/숫자 변화 확인 전 추가 입력 금지')
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            batch.halt(str(exc))
            self.autotour.stop()
            self.auto_confirmed_risk=False
            self.r50_status.set('R50 안전 중지: '+str(exc)[:125])

    def _start_autotour(self):
        """Explicit opt-in. Never continue blindly through modal/other scenes."""
        if self.full_batch is not None and self.full_batch.armed:
            self._stop_all_automation()
        if self.demo or os.name!='nt' or self.current_target is None:
            self.auto_status.set('Windows 실게임 및 대회/각질 목표 확인 후 시작하세요.')
            return
        if not messagebox.askyesno('실험적 자동 훈련',
                '실게임에서 훈련 미리보기 5개를 자동으로 확인한 뒤 '
                '검수 전 OCR 스탯 합계가 가장 높은 훈련의 결정 버튼을 클릭합니다.\n'
                '인연/체력/실패율/스킬 Pt는 반영되지 않으므로 실제 효율을 보장하지 않습니다.\n'
                '훈련 클릭 뒤에는 실제 턴/보상 결과 미검증으로 자동 입력이 중단됩니다.\n'
                'TP 회복·스킬 구매·육성 종료/재시작은 아직 자동으로 진행하지 않습니다.\n'
                '실험을 시작하시겠습니까?',parent=self):
            return
        self.autotour.start()
        self.training_click_guard.reset()
        self.auto_confirmed_risk=True
        self.preview_collector.reset()
        self.auto_status.set('실험적 자동 훈련 활성 · 게임 창을 클릭해 활성화하세요.')

    def _stop_autotour(self):
        self.autotour.stop()
        self.training_click_guard.reset()
        self.auto_confirmed_risk=False
        self.auto_status.set('자동 조작 중지됨 · 클릭하지 않습니다.')
        if self.full_batch is not None and self.full_batch.armed:
            self.full_batch.halt('훈련 자동 탐색 중단 · 반복 조작도 안전 정지')

    def _run_autotour_on_frame(self,scene,preview,hwnd,rect):
        """A frame-based experiment. One foreground click only per verified step."""
        if not self.autotour.enabled or not self.auto_confirmed_risk:
            return
        if self.current_target is None or not self.monitoring or not rect:
            self._stop_autotour()
            return
        if os.name!='nt':
            self._stop_autotour()
            return
        if self.topmost_var.get():
            panel=(self.winfo_rootx(),self.winfo_rooty(),
                   self.winfo_rootx()+self.winfo_width(),
                   self.winfo_rooty()+self.winfo_height())
            if rectangles_overlap(rect,panel):
                self._stop_autotour()
                self.auto_status.set('게임과 도우미가 겹쳐 자동 클릭 정지')
                return
        try:
            from PIL import ImageGrab
            import ctypes
            if ctypes.windll.user32.GetForegroundWindow()!=hwnd:
                # Focus can change whenever the user operates the companion.
                self.auto_status.set('게임 창이 활성화될 때까지 입력 대기')
                return
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            if not portrait_supported(image):
                self._stop_autotour()
                self.auto_status.set('이 게임 화면의 비율은 자동 훈련 실험 미지원')
                return
            # R57: A real Windows click being dispatched does NOT mean that
            # the game received it. Never issue a second click while waiting.
            if self.training_click_guard.armed:
                observed=self.training_click_guard.observe(
                    scene=scene,selected=selected_training(image),
                    preview_selected=(preview.selected if preview else None),
                    collected_names=tuple(self.preview_collector.collected),
                    signature=(_turn_signature(image) if scene=='훈련' else None),
                    hwnd=hwnd,rect=rect)
                if observed.code=='preview_confirmed':
                    self.autotour.state='scanning'
                    self.autotour.awaiting_name=None
                    self.auto_status.set('R57 '+observed.message)
                    return
                if observed.code in ('blocked','review_required'):
                    self._stop_autotour()
                    self.auto_status.set('R57 '+observed.message)
                    return
                self.auto_status.set('R57 '+observed.message)
                return
            proposal=self.autotour.propose(
                image,hwnd,rect,preview,scene=scene,user_armed=True,
                collected_names=tuple(self.preview_collector.collected))
            self.auto_status.set(proposal.explanation)
            if proposal.intent is None:
                if proposal.status=='blocked':
                    self.auto_confirmed_risk=False
                return
            selected=selected_training(image)
            ok=self.autopointer.click(proposal.intent,approved=True,
                                      fresh_image=image,observed_selection=selected)
            self.autotour.on_click_result(ok,proposal.intent.kind,
                  proposal.intent.target_label,__import__('time').monotonic())
            if ok:
                self.training_click_guard.arm(
                    proposal.intent,_turn_signature(image))
                self.auto_status.set('R57 게임 클릭 전송 · 후속 실제 화면 검수 대기'
                    ' · 결과 확인 전 추가 클릭 금지')
        except (AutoInputBlocked,ValueError,OSError,RuntimeError) as exc:
            self._stop_autotour()
            self.auto_status.set('안전 중지: '+str(exc)[:115])

    def _toggle_topmost(self):
        """Optional always-on-top; default is off so the game is unobstructed."""
        self.attributes('-topmost',bool(self.topmost_var.get()))
        self.hint_overlay.hide()
        self.hint_gate.clear()
        self.freshness.update(None)
        self._clear_live_evidence()
        self.reading=False

    def _repeat_changed(self,event=None):
        """Repeat count is only a local plan; it does not activate gameplay."""
        try:
            raw=self.repeat_var.get()
            if not raw.endswith('회'):
                raise ValueError('반복 횟수 선택 오류')
            pref=Preferences(int(raw[:-1])).validate()
            save_preferences(user_dir()/'planning_preferences_r44.json',pref)
            self.repeat_preferences=pref
            self.repeat_error=''
        except (OSError,ValueError,TypeError) as exc:
            self.repeat_var.set(str(self.repeat_preferences.repeats)+'회')
            self.repeat_error='반복 설정 저장 오류: '+str(exc)[:55]
        self._refresh_target_status()

    def _target_changed(self,event=None,persist=True):
        """Only one of the four ordered CM/LOH slots plus a racing style."""
        choices=tuple(round_label(n) for n in range(1,5))
        if self.target_round.get() not in choices or self.target_style.get() not in STYLES:
            self.current_target=None
            self.target_status.set('대회 1~4회차와 각질을 선택하세요. 추천은 보류합니다.')
            self.hint_gate.clear()
            self._clear_live_evidence()
            self._refresh_session_dashboard()
            return
        n=choices.index(self.target_round.get())+1
        target=Target(kind_for_round(n),n,self.target_style.get()).validate()
        self.event_var.set(target.kind)
        if target!=self.current_target:
            self.hint_gate.clear()
            self._clear_live_evidence()
        self.current_target=target
        if persist:
            try:
                save_target(user_dir()/'helper_target_r39.json',target)
                if self.target_error.startswith('목표 설정 파일 확인 필요:'):
                    self.target_error=''
            except (OSError,ValueError) as exc:
                self.target_error='설정 저장 실패: '+str(exc)[:55]
        if self.autotour.enabled:
            self._stop_autotour()
        if self.full_batch is not None and self.full_batch.armed:
            self.full_batch.halt('육성 목표 변경')
        self.batch_coordinator=BatchPlanner(self.current_target,self.repeat_preferences.repeats)
        self._refresh_target_status()
        self._refresh_learning_status()

    def _refresh_target_status(self):
        target=self.current_target
        course=course_for(target,self.known_courses)
        msg=describe_plan(target,self.repeat_preferences,course)
        issues=[x for x in (self.target_error,self.repeat_error) if x]
        if course is not None:
            msg+=' · '+course['venue']+' '+str(course['meters'])+'m'
            if course.get('official_confirmed') is not True:
                msg+=' (2차 출처, 공식 확인 전)'
        if issues:
            msg+=' · '+' · '.join(issues)
        self.target_status.set(msg+' · 자동 조작 미연결')
        self._refresh_session_dashboard()

    def _refresh_session_dashboard(self):
        """Inspect a saved R44 session without creating, resuming or changing it."""
        try:
            snapshot=read_dashboard(
                self.current_target,self.repeat_preferences,
                user_dir()/'cultivation_session_r44.json')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.session_status.set('진행 기록 확인 보류')
            self.session_counts.set('현재 육성 횟수 미확인')
            self.session_breakdown.set('고점 — · 평범 — · 도축 — · 실패 —')
            self.session_note.set('진행 현황 읽기 오류: '+str(exc)[:95])
            self.session_progress.set(0)
            if self.session_progressbar is not None:
                self.session_progressbar.pack_forget()
            return
        self.session_status.set(snapshot.status)
        self.session_counts.set(snapshot.progress)
        self.session_breakdown.set(snapshot.breakdown)
        self.session_note.set(snapshot.detail)
        if self.session_progressbar is not None:
            if snapshot.recorded and snapshot.fraction is not None:
                self.session_progress.set(max(0,min(100,100*snapshot.fraction)))
                if not self.session_progressbar.winfo_manager():
                    self.session_progressbar.pack(fill='x',pady=(1,6),
                                                  before=self.session_breakdown_label)
            else:
                self.session_progress.set(0)
                self.session_progressbar.pack_forget()

    def _toggle_dev_tools(self):
        self.dev_visible=not self.dev_visible
        if self.dev_visible:
            self.dev_panel.pack(fill='x')
        else:
            self.dev_panel.pack_forget()

    def _periodic_update_check(self):
        if not self.update_busy:
            self._check_updates()
        self.after(24*60*60*1000,self._periodic_update_check)

    def _check_updates(self):
        if self.update_busy:
            return
        if os.name != 'nt' or not getattr(sys,'frozen',False):
            self.update_status.set('소스 실행에서는 버전 교체를 지원하지 않습니다.')
            return
        self.update_busy=True
        self.update_check_button.configure(state='disabled')
        self.update_install_button.configure(state='disabled')
        self.update_status.set('GitHub 공개 릴리스 확인 중…')
        def worker():
            try:
                self.update_queue.put(('check_ok',check_latest()))
            except Exception as exc:
                self.update_queue.put(('error',str(exc)[:150]))
        threading.Thread(target=worker,daemon=True).start()

    def _download_update(self):
        release=self.update_release
        if self.update_busy or release is None:
            return
        if not messagebox.askyesno('포터블 업데이트 확인',
            f'v{release.version}을 공식 GitHub에서 내려받아 SHA-256 검증 후 새 폴더에 준비합니다.\n'
            '기존 버전과 육성 기록은 지워지지 않습니다. 진행할까요?',parent=self):
            return
        self.update_busy=True
        self.update_check_button.configure(state='disabled')
        self.update_install_button.configure(state='disabled')
        self.update_status.set(f'v{release.version} 다운로드 및 무결성 검증 중…')
        exe=Path(sys.executable).resolve()
        def worker():
            try:
                self.update_queue.put(('download_ok',download_portable(release,exe)))
            except Exception as exc:
                self.update_queue.put(('error',str(exc)[:150]))
        threading.Thread(target=worker,daemon=True).start()

    def _update_poll(self):
        try:
            while True:
                kind,result=self.update_queue.get_nowait()
                self.update_busy=False
                self.update_check_button.configure(state='normal')
                if kind=='error':
                    self.update_status.set('업데이트 오류 · 기존 버전 유지: '+result)
                    self.update_install_button.configure(state='normal' if self.update_release else 'disabled')
                elif kind=='check_ok':
                    self.update_release=result
                    if result is None:
                        self.update_status.set(f'현재 버전 v{CURRENT_VERSION} · 새 공개 버전 없음')
                    else:
                        self.update_status.set(f'새 공개 버전 v{result.version} · 사용자 확인 후 업데이트')
                        self.update_install_button.configure(state='normal')
                elif kind=='download_ok':
                    new_exe=Path(result)
                    self.update_status.set(f'새 버전 준비 완료: {new_exe.parent.name}')
                    if messagebox.askyesno('새 버전 준비 완료',
                            '검증된 새 버전이 별도 폴더에 준비됐습니다. 지금 새 버전을 실행할까요?\n'
                            '기존 프로그램은 종료되며 저장된 기록은 유지됩니다.',parent=self):
                        try:
                            subprocess.Popen([str(new_exe)],cwd=str(new_exe.parent))
                        except OSError as exc:
                            self.update_status.set('새 프로그램 실행 실패 · 기존 버전 유지: '+str(exc)[:80])
                        else:
                            self.destroy()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(350,self._update_poll)

    def _helper(self):
        """Click-only monitoring control; no game keyboard or pointer events."""
        self.monitoring=not self.monitoring
        if not self.monitoring:
            self._stop_all_automation()
            self.freshness.update(None)
            self.hint_gate.clear()
            self.scene_tracker.reset()
            self.button_tracker.reset()
            self.reading=False
            self._stop_autotour()
            self._clear_live_evidence()
            view=paused_view()
            self.action.set(view.title)
            self.reason.set(view.explanation)
            self.status.set('헬퍼 일시 정지')
            self.helper_switch.configure(text='화면 분석 다시 시작')
        else:
            self.action.set('게임 화면 자동 확인 중')
            self.reason.set('게임 창이 활성화되면 화면을 자동으로 분석합니다.')
            self.status.set('게임 창 연결 대기')
            self.helper_switch.configure(text='화면 분석 일시 정지')

    def _schedule_capture(self):
        """Button is clicked on the companion; user has 4 seconds to refocus game."""
        if self.capture_pending or self.demo:
            self.reason.set('시연 모드에서는 게임 화면을 저장할 수 없습니다.')
            return
        if self.game is None or os.name != 'nt':
            self.reason.set('Windows에서 실제 게임 창을 찾은 뒤 사용하세요.')
            return
        self.capture_pending=True
        target=self.game
        scene=self.capture_label.get()
        self.hint_overlay.hide()
        self.reason.set('4초 뒤 캡처: 게임 창으로 돌아가고 다른 창으로 가리지 마세요.')
        self.after(4000,lambda:self._capture_r29(target,scene))

    def _capture_r29(self,expected,scene):
        try:
            if os.name!='nt':raise CaptureError('Windows PC에서만 사용할 수 있습니다.')
            import ctypes
            from PIL import ImageGrab
            current, _=choose_window(discover_windows())
            panel=(self.winfo_rootx(),self.winfo_rooty(),
                   self.winfo_rootx()+self.winfo_width(),self.winfo_rooty()+self.winfo_height())
            rect=check_capture_target(expected,current,ctypes.windll.user32.GetForegroundWindow(),panel)
            if not self.capture_pack:
                self.capture_pack=new_pack(user_dir()/'r29_local_captures')
            self.hint_overlay.hide()
            # No game clicks or keyboard events are sent.
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            store_capture(self.capture_pack,image,scene_label=scene,
                          window_size=(current.width,current.height))
            self.reason.set(f'로컬 화면 저장 완료 · {scene} · {len(load_pack(self.capture_pack, check_images=False)["captures"])}/{MAX_CAPTURES}장'
                            ' · r29_local_captures (외부 전송 없음)')
        except (CaptureError,OSError,ValueError) as error:
            self.reason.set('R29 캡처 보류 · '+str(error)[:100])
        finally:
            self.capture_pending=False

    def _export_capture_pack(self):
        if not self.capture_pack:
            self.reason.set('R29 캡처를 먼저 저장하세요.')
            return
        location=filedialog.asksaveasfilename(title='본인이 확인한 화면만 공유하세요',
                   defaultextension='.zip',filetypes=[('ZIP archives','*.zip')])
        if not location:return
        try:
            export_pack(self.capture_pack,Path(location))
            self.reason.set('ZIP 저장 완료 · 게임 화면에 개인 정보가 없는지 공유 전 확인하세요.')
        except (CaptureError,OSError,ValueError) as error:
            self.reason.set('R29 ZIP 내보내기 실패 · '+str(error)[:100])

    def _launch_game_test(self):
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        name='UmaTrainerKR_GameTest.exe' if getattr(sys,'frozen',False) else 'live_test_ui_r22.py'
        target=base/name
        if target.is_file():
            args=[str(target)] if getattr(sys,'frozen',False) else [sys.executable,str(target)]
            try:
                subprocess.Popen(args,cwd=str(base))
            except OSError as exc:
                self.reason.set('R22 실행 오류: '+str(exc)[:85])
        else:
            self.reason.set('R22 점검 도구가 없습니다. 전체 설치형 패키지를 확인하세요.')

    def _launch_preflight(self):
        """Launch local read-only test app, never game control."""
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        filename='UmaTrainerKR_Preflight.exe' if getattr(sys,'frozen',False) else 'offline_replay_ui_r23.py'
        target=base/filename
        if not target.is_file():
            self.reason.set('R23 점검 도구가 없습니다. 전체 설치본인지 확인하세요.')
            return
        args=[str(target)] if getattr(sys,'frozen',False) else [sys.executable,str(target)]
        try:subprocess.Popen(args,cwd=str(base))
        except OSError as exc:self.reason.set('R23 점검 도구 실행 오류: '+str(exc)[:85])

    def _launch_advanced(self):
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        path=base/'app.py'
        if getattr(sys,'frozen',False):
            advanced=Path(sys.executable).resolve().parent/'UmaTrainerKR.exe'
            if advanced.is_file():
                try:subprocess.Popen([str(advanced)],cwd=str(base))
                except OSError as exc:self.reason.set('상세 설정 실행 오류: '+str(exc)[:85])
            else:
                self.reason.set('고급 설정 도구가 없습니다. 설치형 패키지를 사용하세요.')
        elif path.is_file():
            try:subprocess.Popen([sys.executable,str(path)],cwd=str(base))
            except OSError as exc:self.reason.set('상세 설정 실행 오류: '+str(exc)[:85])
        else:
            self.reason.set('상세 설정 프로그램을 찾지 못했습니다.')

    def _clear_live_evidence(self):
        """Never display last-turn values after window/layout/scene invalidation."""
        self.scene_fusion.reset()
        self.setup_choice_tracker.reset()
        self.setup_choices_status.set('R59 게임 화면 전환 · 시작 선택지 재확인 필요')
        self.numeric_reader.reset()
        self.training_click_guard.reset()
        self.training_evidence.reset()
        self.training_evidence_info.set('R55 훈련 화면/턴 변경 · 지난 후보 폐기')
        self.ranker_strategy_info.set('R56 이전 전략 후보 폐기 · 한국 게임 화면 대기')
        self.numeric_status.set('R54 인식 보류 · 이전 화면의 수치 후보 폐기')
        self.failure_rate.set('—')
        self.island_tickets.set('—')
        self.development_points.set('—')
        for var in self.statvals.values(): var.set('—')
        self.energy.set('—');self.skill.set('—')
        self.scene_info.set('화면 유형: 미확인 · 검수 대기')
        self.hint_overlay.hide()
        self.low_energy.reset()
        self.r28_info.set('R28: 현재 화면 추천 보류')
        self.button_info.set('훈련 버튼: 현재 화면 미확인')
        self.action.set('추천 보류')
        self.reason.set('이전 화면의 추천과 OCR 수치를 무효화했습니다.')
        self.unified_advisor.suspend()
        if self.autotour.enabled:
            self._stop_autotour()
        self.preview_collector.reset()
        self.preview_info.set('R48: 훈련 5종을 게임에서 확인하면 잠정 비교 · 0/5')
        self.r46_status.set('R46: 이전 화면 추천 폐기 · 새 한국 서버 관측값 확인 대기')

    def _scan(self):
        if not self.monitoring:
            self.status.set('헬퍼 일시 정지')
            self.after(2500,self._scan)
            return
        try:
            game, message=choose_window(discover_windows())
            if self.freshness.update(game.hwnd if game else None,game.rect if game else None):
                self.scene_tracker.reset()
                self.button_tracker.reset()
                self._clear_live_evidence()
                self.reading=False  # pending older worker response is rejected by epoch
                self.hint_gate.clear()
                self.last_hwnd=game.hwnd if game else None
            self.game=game
            self.status.set(message)
            self.detail.set((game.title[:50] if game else '게임을 실행하면 자동으로 연결을 시도합니다.'))
            if game:
                if os.name=='nt':
                    import ctypes
                    if ctypes.windll.user32.GetForegroundWindow()!=game.hwnd:
                        self.hint_overlay.hide()
                        self.hint_gate.clear()
                # Respect the user's window position. Never reposition the
                # Tk root during polling, including when the game is resized.
                # Non-topmost helper behind the focused game cannot obscure
                # the game's pixels, even if their rectangles overlap.
                panel=(self.winfo_rootx(),self.winfo_rooty(),
                       self.winfo_rootx()+self.winfo_width(),
                       self.winfo_rooty()+self.winfo_height())
                if self.topmost_var.get() and rectangles_overlap(game.rect,panel):
                    self._clear_live_evidence()
                    self.reason.set('항상 위에 표시된 도우미가 게임 화면과 겹칩니다 · 창을 옮기거나 항상 위를 해제하세요.')
                elif not self.reading:
                    self.hint_overlay.hide()  # prevent our own overlay being captured as game pixels
                    self._read_game(game)
        except Exception as exc:
            self.game=None
            self.hint_gate.clear()
            self.freshness.update(None)
            self._clear_live_evidence()
            self.status.set('게임 연결 감지 오류')
            self.detail.set(type(exc).__name__)
        # Faster passive screenshot polling while the player previews 5 trainings.
        self.after(1200,self._scan)

    def _read_game(self,game):
        from screen_r4 import profile_path
        self.reading=True
        epoch=self.freshness.ticket()
        def work():
            from PIL import ImageGrab
            from screen_r4 import read_profile,read_regions
            try:
                # A desktop screenshot of a background window can contain another
                # app in the same pixels. Never label such content as game data.
                if os.name == 'nt':
                    import ctypes
                    u=ctypes.windll.user32
                    if u.IsIconic(game.hwnd) or u.GetForegroundWindow()!=game.hwnd:
                        raise RuntimeError('게임 창이 활성화되지 않았습니다 · 추천 보류')
                image=ImageGrab.grab(bbox=game.rect,all_screens=True)
                if image.size!=(game.rect[2]-game.rect[0],game.rect[3]-game.rect[1]):
                    raise RuntimeError('게임 화면 캡처 크기가 일치하지 않습니다.')
                try:anchors=load_library(scene_profile_path())
                except (OSError,ValueError):anchors=[]
                guess=self.scene_tracker.observe(image,anchors)
                # R53 unifies passive R20 two-anchor scene evidence, R50
                # reviewed visual control stage, and provisional R48 training.
                # No scene result alone grants any permission to click.
                portrait_training=selected_training(image)
                try:
                    passive_profiles=(self.r50_profiles
                         if self.full_batch is not None and self.full_batch.armed
                         else load_profiles(user_dir()/'r50_visual_controls.json'))
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    raise RuntimeError('R50 화면 등록 파일을 읽을 수 없어 인식을 중단합니다') from exc
                registered_stage=(unique_scene(image,passive_profiles)[0]
                                  if passive_profiles else None)
                screen=self.scene_fusion.observe(guess.scene,registered_stage,portrait_training)
                scene=screen.scene
                text_scene=f'화면 유형: {scene or "보류"} · {screen.reason}'
                # R59 read-only: never feed visible options to the R50 click
                # supervisor; registered starting paths are not authorizations.
                try:
                    choice_profiles=load_choices(user_dir()/'r59_setup_choices.json')
                    setup_view=self.setup_choice_tracker.observe(
                        image,hwnd=game.hwnd,rect=game.rect,active=True,
                        scene=scene,profiles=choice_profiles)
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    self.setup_choice_tracker.reset()
                    setup_view=SetupChoiceView(
                        None,None,(),'등록한 육성 선택지 인식 보류: '+str(exc)[:95])
                hits=[]
                try:patterns=load_patterns(button_pattern_path())
                except (DetectionError,OSError):patterns=[]
                try:
                    hits=self.button_tracker.observe(image,patterns,scene)
                    buttons=('훈련 버튼: '+', '.join(h.label for h in hits)+' · 위치 확인 (추천 계산 전)'
                             if hits else '훈련 버튼: 미검출 또는 반복 확인 중')
                except (DetectorUnavailable,DetectionError,ValueError) as exc:
                    self.button_tracker.reset()
                    buttons='버튼 인식 보류: '+str(exc)[:70]
                # Passive local preview collection: the player selects
                # five training icons in the game. No game pointer/keyboard.
                preview=None
                ocr_binary=None
                if scene == '훈련' and portrait_training is not None:
                    from screen_r4 import tesseract_executable
                    ocr_binary=tesseract_executable()
                    preview=self.preview_collector.observe(
                        image,game.hwnd,ocr_binary)
                elif scene is not None and scene != '훈련':
                    self.preview_collector.reset()
                values={}
                numeric_note='R54 현재 장면 숫자 영역 미등록 · 검수 전'
                r54_active=False
                passive_rois=read_passive_numbers(user_dir()/'r54_numeric_regions.json')
                active_rois=tuple(r for r in passive_rois if r.scene==scene)
                if active_rois:
                    from screen_r4 import tesseract_executable
                    # Never infer a turn identity from OCR. The training
                    # baseline fingerprint is only a cache-invalidation key.
                    # One selected training's failure rate/cost must not
                    # leak into the next training icon of the same turn.
                    turn_key=(_turn_signature(image), portrait_training) if scene=='훈련' else None
                    number_frame=self.numeric_reader.observe(
                        image,scene,active_rois,(ocr_binary or tesseract_executable()),
                        game.hwnd,game.rect,turn_key)
                    values=number_frame.numbers
                    numeric_note='R54 '+number_frame.status
                    r54_active=True
                else:
                    self.numeric_reader.reset()
                    # Backward compatibility: preserve the user's old R4
                    # training profile until an R54 scene profile is registered.
                    if scene=='훈련' and profile_path().exists():
                        with tempfile.TemporaryDirectory(prefix='uma_companion_') as td:
                            path=Path(td)/'game.png'
                            image.save(path)
                            profile=read_profile(profile_path())
                            results=read_regions(path,profile,min_confidence=80)
                        values=usable_ocr_values(results)
                        numeric_note='기존 R4 OCR 후보 · 직접 검수 전'
                # R55 assembles R48's 2-frame gain readings with selected-
                # training-scoped R54 values, WITHOUT authorizing a click.
                training_state=self.training_evidence.observe(
                    scene=scene,
                    selected=preview.selected if preview else None,
                    window_key=game.hwnd,window_rect=game.rect,image_size=image.size,
                    turn_signature=_turn_signature(image) if scene=='훈련' else None,
                    preview_readings=(dict(self.preview_collector.collected)
                                      if scene=='훈련' and preview is not None and ocr_binary
                                      else {}),
                    numeric_candidates=(values if r54_active else {}))
                packet=None
                if self.full_batch is not None and self.full_batch.armed:
                    from screen_r4 import tesseract_executable
                    packet=self.full_batch.adapter.observe(
                        image,game.hwnd,self.r50_profiles,self.r50_rois,
                        tesseract_executable(),
                        run_id=self.full_batch.active_run_id,
                        skill_scope_reviewed=self.full_batch.skill_scope_reviewed,
                        goal_scope=(self.current_target.key+":"+self.current_target.style
                                    if self.current_target is not None else ""),
                        skill_approvals=self.r51_skill_approvals,
                        cycle=len(self.full_batch.planner.completed_ids))
                self.q.put(('frame',epoch,game.hwnd,
                            (text_scene,buttons,scene,values,hits,preview,packet,screen,r54_active,numeric_note,training_state,setup_view)))
            except Exception as e:
                self.q.put(('error',epoch,game.hwnd,str(e)))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind,epoch,hwnd,data=self.q.get_nowait()
                if not self.freshness.accepts(epoch,hwnd):
                    continue
                self.reading=False
                if kind=='error':
                    self._clear_live_evidence()
                    self.reason.set('화면 인식 보류 · '+data[:85])
                    continue
                scene_text,buttons,scene,values,hits,preview,packet,screen,r54_active,numeric_note,training_state,setup_view=data
                self.scene_info.set(scene_text)
                if setup_view.branch is not None:
                    name='일반' if setup_view.branch=='normal' else '이벤트'
                    chosen=(' · 선택 중: '+setup_view.selected_choice
                            if setup_view.selected_choice else ' · 현재 선택 상태 미확인')
                    self.setup_choices_status.set(
                        'R60 '+name+' · '+setup_view.step+' · 보이는 선택지: '
                        +', '.join(setup_view.choices)+chosen+' (자동 입력 없음)')
                elif scene in ('육성 준비','TP 회복','팝업/기타',None):
                    self.setup_choices_status.set('R59 '+setup_view.status)
                else:
                    self.setup_choices_status.set('R59 육성 시작 전 선택지 · 현재 화면 해당 없음')
                self.button_info.set(buttons)
                # Entire frame replaces, never merges with last frame's values.
                safe=(dict(values) if r54_active and scene is not None
                      else self.freshness.safe_values(scene,values))
                self.numeric_status.set(numeric_note)
                self.training_evidence_info.set(training_state.explanation)
                # Source guides are JP hypotheses. Do not infer verified KR
                # phase, ticket expiry or support friendship from R55 OCR.
                research_view=self.unified_advisor.inspect_training_research(
                    training_state, StrategyContext())
                self.ranker_strategy_info.set('R56 '+research_view.label)
                self.failure_rate.set(str(safe['실패율'])+'% *' if '실패율' in safe else '—')
                self.island_tickets.set(str(safe['섬 티켓'])+' *' if '섬 티켓' in safe else '—')
                self.development_points.set(str(safe['발전 Pt'])+' *' if '발전 Pt' in safe else '—')
                self.r46_status.set(companion_readiness(
                    scene,goal_selected=self.current_target is not None,
                    ocr_candidate_count=len(safe)))
                # OCR candidate values cannot become reviewed R46 actions.
                self.unified_advisor.suspend()
                for k,var in self.statvals.items():
                    var.set(f'{safe[k]:,} *' if k in safe else '—')
                self.energy.set(f'{safe["체력"]} *' if '체력' in safe else '—')
                self.skill.set(f'{safe["스킬 Pt"]:,} *' if '스킬 Pt' in safe else '—')
                self.action.set('화면 분석 중')
                self.reason.set('화면에서 읽은 수치와 선택지를 확인하는 중입니다.')
                try:
                    obj=load_handoff()
                except (HandoffError,OSError) as exc:
                    obj=None
                    self.r28_info.set('R28 전달 오류: '+str(exc)[:75])
                if (obj is not None and (self.current_target is None
                        or obj.get('style')!=self.current_target.style
                        or obj.get('event')!=self.current_target.kind)):
                    obj=None  # Reviewed advice must match the complete selected competition.
                    self.r28_info.set('대회/각질 불일치 · 이전 훈련 추천 차단')
                rect=self.game.rect if self.game and self.game.hwnd==hwnd else None
                active=False
                if rect and os.name=='nt':
                    import ctypes
                    active=ctypes.windll.user32.GetForegroundWindow()==hwnd
                hint=self.hint_gate.observe(obj,hwnd=hwnd,
                        size=((rect[2]-rect[0],rect[3]-rect[1]) if rect else None),
                        scene=scene,hits=hits,active=active)
                view=view_from_frame(
                    scene=scene,active=active,value_count=len(safe),
                    detected_buttons=tuple(h.label for h in hits),
                    reviewed_hint=hint.label if hint is not None else None,
                    low_energy_candidate=self.low_energy.observe(
                        energy=safe.get('체력'),epoch=epoch,scene=scene,active=active))
                self.action.set(view.title)
                detail=view.explanation
                if preview is not None:
                    self.preview_info.set(preview.explanation)
                elif scene not in ('훈련',None):
                    self.preview_info.set('R48: 다른 장면 · 훈련 미리보기 후보 비활성')
                if preview is not None and preview.recommendation is not None:
                    self.action.set(preview.recommendation+' 훈련 · 잠정 후보')
                    detail=preview.explanation
                if scene=='스킬' and (self.current_target is None
                                     or course_for(self.current_target,self.known_courses) is None):
                    detail+=' 목표 코스 미검증 · 스킬 구매 추천은 보류합니다.'
                if not view.verified_training and (preview is None or
                                                   preview.recommendation is None):
                    if scene == '훈련':
                        detail+=' · 실게임 훈련별 보상·인연 데이터 미연결 (R22 점검에서 검수 필요)'
                    elif scene is None:
                        detail+=' · 한국 서버 화면 인식 기준 미등록/미확인 · 장면 점검 필요'
                self.reason.set(detail)
                if self.full_batch is not None and self.full_batch.armed:
                    self._run_r50_on_frame(packet,scene,preview,hwnd,rect,screen)
                if self.autotour.enabled and (self.full_batch is None or
                       not self.full_batch.armed or scene=='훈련'):
                    self._run_autotour_on_frame(scene,preview,hwnd,rect)
                if view.verified_training and hint and rect:
                    self.r28_info.set('확인된 훈련 후보: '+hint.label)
                    if not self.hint_overlay.show(rect,hint):
                        self.r28_info.set('훈련 후보 확인 · 게임 위 표시 실패 (옆 창에서 확인)')
                else:
                    self.hint_overlay.hide()
                    if obj is None:
                        self.r28_info.set('자동 판단 준비 중 · 현재 훈련 추천 없음')
                    elif obj['id'] in self.hint_gate.revoked:
                        self.r28_info.set('이전 추천 폐기 · 화면 재확인 중')
                    else:
                        self.r28_info.set('화면의 훈련 후보 검수 중')
        except queue.Empty:pass
        self.after(250,self._poll)


if __name__=='__main__':
    from package_selftest_r25 import maybe_run_cli
    maybe_run_cli("UmaTrainerKR_Companion")
    from package_selftest_r25 import maybe_run_startup_cli
    maybe_run_startup_cli("UmaTrainerKR_Companion")
    from runtime_probe_r26 import maybe_run_cli as r26_first_run
    r26_first_run()
    from helper_smoke_r37 import maybe_run_cli as r37_helper_smoke
    r37_helper_smoke(lambda: Companion(demo=True))
    app=Companion('--demo' in sys.argv)
    if '--screenshot' in sys.argv:
        idx=sys.argv.index('--screenshot')
        dest=sys.argv[idx+1]
        def capture():
            from PIL import ImageGrab
            app.update()
            box=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())
            ImageGrab.grab(bbox=box).save(dest)
            app.destroy()
        app.after(900,capture)
    app.mainloop()
