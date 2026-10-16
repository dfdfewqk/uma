"""Uma Trainer KR V0.11 R11: evidence-gated competition goal tracking."""
from __future__ import annotations

# Validate a packaged EXE before importing tkinter or any GUI-heavy modules.
import sys as _uma_startup_sys
if __name__ == '__main__' and '--self-check-report' in _uma_startup_sys.argv[1:]:
    from package_selftest_r25 import maybe_run_cli as _uma_early_selfcheck
    _uma_early_selfcheck('UmaTrainerKR')

import json
import os
import shutil
import sys
import traceback
import webbrowser
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from uma_core import (STATS, SCENARIOS, EVENTS, DISTANCES, STYLES, TRAININGS,
                      DEFAULT_TARGETS, Action, RunProfile, TurnState, default_actions,
                      rank_actions, input_coverage, assess_run)
from storage import (connect, db_path, create_run, add_turn, list_runs, list_turns,
                     export_csv, export_json, save_run_outcome, backup_database)
from dataset import export_decisions_csv
from analytics_r3 import (run_audit, corpus_audit, audit_verified_video_turns,
                          export_r3_report, export_verified_candidates_csv)
from screen_ui_r4 import ScreenPanel
from training_ui_r5 import TrainingPanel
from decision_ui_r6 import DecisionPanel
from island_context_ui_r34 import IslandContextPanel
from island_ui_r7 import IslandPlannerPanel
from island_ui_r8 import IslandImpactPanel
from calibration_ui_r9 import CalibrationPanel
from review_ui_r10 import ReviewQueuePanel
from goal_ui_r11 import GoalPanel
from course_ui_r12 import CourseSkillPanel
from plan_ui_r13 import EventPlanPanel
from lineage_ui_r14 import LineageCalendarPanel
from learning_ui_r15 import LearningPanel
from learning_ui_r16 import MLResearchPanel
from learning_ui_r17 import R17ResearchPanel
from live_ui_r18 import LivePanel

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DARK = '#111827'
PANEL = '#192438'
FIELD = '#233047'
TEXT = '#F3F6FB'
MUTED = '#B6C2D2'
ACCENT = '#68B7FF'
GREEN = '#86E1AA'


def int_safe(v, label, lo=0, hi=100000):
    try:
        number = int(str(v).strip())
        if number < lo or number > hi:
            raise ValueError('range')
        return number
    except (ValueError, TypeError):
        raise ValueError(f'{label} 입력값을 확인하세요 ({lo}~{hi}).')


def float_safe(v, label, lo=0, hi=100):
    try:
        number = float(str(v).strip())
        if number < lo or number > hi:
            raise ValueError('range')
        return number
    except (ValueError, TypeError):
        raise ValueError(f'{label} 입력값을 확인하세요 ({lo}~{hi}).')


class UmaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Uma Trainer KR V0.21 R21 — 훈련 버튼 위치 자동 인식')
        self.geometry('1280x830')
        self.minsize(1040, 720)
        self.configure(bg=DARK)
        self._set_styles()
        self.conn = connect()
        self.run_id = None
        self.run_profile = None
        self.actions = default_actions()
        self.selected_action = TRAININGS[0]
        self.last_rankings = []
        self._build()
        self._load_actions_into_editor(self.selected_action)
        self._load_library()
        self.refresh_runs()
        self.protocol('WM_DELETE_WINDOW', self._quit)

    def _set_styles(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        font_name = '맑은 고딕' if sys.platform == 'win32' else 'DejaVu Sans'
        self.option_add('*Font', (font_name, 10))
        s.configure('.', background=DARK, foreground=TEXT, font=(font_name, 10))
        s.configure('TFrame', background=DARK)
        s.configure('Panel.TFrame', background=PANEL)
        s.configure('TLabel', background=DARK, foreground=TEXT)
        s.configure('Muted.TLabel', background=DARK, foreground=MUTED)
        s.configure('Panel.TLabel', background=PANEL, foreground=TEXT)
        s.configure('Section.TLabel', background=DARK, foreground=ACCENT, font=(font_name, 11, 'bold'))
        s.configure('Title.TLabel', background=DARK, foreground=TEXT, font=(font_name, 19, 'bold'))
        s.configure('TButton', background=FIELD, foreground=TEXT, padding=(12, 8))
        s.map('TButton', background=[('active', '#334968')], foreground=[('disabled', '#8A96A9')])
        s.configure('Accent.TButton', background='#2167AD', foreground='#FFFFFF', padding=(12, 9))
        s.map('Accent.TButton', background=[('active', '#297ECF')])
        s.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=5)
        s.configure('TCombobox', fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=TEXT, padding=5)
        s.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT)])
        s.configure('TNotebook', background=DARK, borderwidth=0)
        s.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(7, 9))
        s.map('TNotebook.Tab', background=[('selected', '#23537F')], foreground=[('selected', TEXT)])
        s.configure('Treeview', background=PANEL, foreground=TEXT, fieldbackground=PANEL,
                    borderwidth=0, rowheight=32, font=(font_name, 10))
        s.configure('Treeview.Heading', background=FIELD, foreground=TEXT, font=(font_name, 10, 'bold'))
        s.map('Treeview', background=[('selected', '#2A6A9F')], foreground=[('selected', 'white')])
        s.configure('TLabelframe', background=DARK, bordercolor='#3B4B64')
        s.configure('TLabelframe.Label', background=DARK, foreground=ACCENT, font=(font_name, 10, 'bold'))
        s.configure('Vertical.TScrollbar', background=FIELD)

    def _heading(self, parent, title):
        ttk.Label(parent, text=title, style='Section.TLabel').pack(anchor='w', pady=(12, 7))

    def _entry(self, parent, label, variable, width=12):
        group = ttk.Frame(parent)
        ttk.Label(group, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
        ttk.Entry(group, textvariable=variable, width=width).pack(fill='x')
        return group

    def _combo(self, parent, label, variable, values, width=15, on_change=None):
        group = ttk.Frame(parent)
        ttk.Label(group, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
        box = ttk.Combobox(group, textvariable=variable, values=values, width=width, state='readonly')
        box.pack(fill='x')
        if on_change:
            box.bind('<<ComboboxSelected>>', on_change)
        return group

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=20, pady=(16, 5))
        ttk.Label(top, text='Uma Trainer KR', style='Title.TLabel').pack(side='left')
        ttk.Label(top, text=' V0.21 R21  |  훈련 버튼 자동 위치 탐지',
                  style='Muted.TLabel').pack(side='left', padx=20, pady=10)
        self.show_details=tk.BooleanVar(value=False)
        ttk.Button(top,text='연구·상세 설정 보기 / 숨기기',command=self._toggle_details).pack(side='right',padx=(16,0))
        ttk.Label(self, text='R21: 화면 분류 + 훈련 버튼 특징 자동 재탐색 · 옆 정보창. 실제 한국 서버 인식·자동 육성은 아직 미검증입니다.',
                  style='Muted.TLabel').pack(anchor='w', padx=21, pady=(0, 12))
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=16, pady=(0, 12))
        self.page_live_r18 = ttk.Frame(self.notebook)
        self.page_setup = ttk.Frame(self.notebook)
        self.page_turn = ttk.Frame(self.notebook)
        self.page_records = ttk.Frame(self.notebook)
        self.page_analytics = ttk.Frame(self.notebook)
        self.page_screen = ttk.Frame(self.notebook)
        self.page_training_r5 = ttk.Frame(self.notebook)
        self.page_decision_r6 = ttk.Frame(self.notebook)
        self.page_context_r34 = ttk.Frame(self.notebook)
        self.page_island_r7 = ttk.Frame(self.notebook)
        self.page_island_r8 = ttk.Frame(self.notebook)
        self.page_calibration_r9 = ttk.Frame(self.notebook)
        self.page_review_r10 = ttk.Frame(self.notebook)
        self.page_goal_r11 = ttk.Frame(self.notebook)
        self.page_course_r12 = ttk.Frame(self.notebook)
        self.page_event_r13 = ttk.Frame(self.notebook)
        self.page_lineage_r14 = ttk.Frame(self.notebook)
        self.page_learning_r15 = ttk.Frame(self.notebook)
        self.page_ml_r16 = ttk.Frame(self.notebook)
        self.page_ml_r17 = ttk.Frame(self.notebook)
        self.page_sources = ttk.Frame(self.notebook)
        for page, title in ((self.page_live_r18, '게임 동반자 R20'), (self.page_setup, '① 목표'), (self.page_turn, '② 턴'),
                            (self.page_records, '③ 기록'), (self.page_analytics, '④ R3'),
                            (self.page_screen, '⑤ R4'), (self.page_training_r5, '⑥ R5'), (self.page_decision_r6, '⑦ R6'), (self.page_context_r34, 'R34 무인도 조건'), (self.page_island_r7, '⑧ R7'), (self.page_island_r8, '⑨ R8'), (self.page_calibration_r9, '⑩ R9'), (self.page_review_r10, '⑪ R10'), (self.page_goal_r11, '⑫ R11'), (self.page_course_r12, '⑬ 코스·스킬'), (self.page_event_r13, '⑭ 대회·인자'), (self.page_lineage_r14, '⑮ 계승·미래시'), (self.page_learning_r15, '⑯ R15 학습자료'), (self.page_ml_r16, '⑰ R16 ML 연구'), (self.page_ml_r17, '⑱ R17 모델·결과'), (self.page_sources, '⑲ 자료')):
            self.notebook.add(page, text=title)
        self.extra_pages=list(self.notebook.tabs())[1:]
        for page in self.extra_pages:self.notebook.hide(page)
        self.live_panel = LivePanel(self.page_live_r18, context_provider=self._r19_context)
        self.live_panel.pack(fill='both',expand=True)
        self._build_setup()
        self._build_turn()
        self._build_records()
        self._build_analytics()
        self._build_screen()
        self._build_training_r5()
        self._build_decision_r6()
        self._build_context_r34()
        self._build_island_r7()
        self._build_island_r8()
        self._build_calibration_r9()
        self._build_review_r10()
        self._build_goal_r11()
        self._build_course_r12()
        self._build_event_r13()
        self._build_lineage_r14()
        self._build_learning_r15()
        self._build_ml_r16()
        self._build_ml_r17()
        self._build_sources()
        bottom = ttk.Frame(self)
        bottom.pack(fill='x', padx=20, pady=(0, 12))
        self.footer = tk.StringVar(value=f'데이터 저장: {db_path()}')
        ttk.Label(bottom, textvariable=self.footer, style='Muted.TLabel').pack(side='left')

    def _toggle_details(self):
        if self.show_details.get():
            for tab in self.extra_pages:self.notebook.hide(tab)
            self.notebook.select(self.page_live_r18)
            self.show_details.set(False)
        else:
            for tab in self.extra_pages:self.notebook.add(tab)
            self.show_details.set(True)

    def _r19_context(self):
        """Read only CURRENT user-reviewed R6/R11/R12 context. No guessed recognition."""
        out={'course':'','event':'미설정','style':'미설정','targets':{},'stats':{},
             'required_skills':[], 'training_checked':False,
             'training_rankings':[], 'skill_checked':False, 'skill_advice':{}}
        try:
            p=self._profile()
            state=self._state()
            out.update(course=p.course, event=p.event, style=p.style,
                       targets=p.target_stats.copy(),stats=state.stats.copy())
        except (ValueError,TypeError,AttributeError):return out
        if hasattr(self,'goal_r11_panel'):
            raw=self.goal_r11_panel.skills_editor.get('1.0','end')
            for row in raw.splitlines():
                parts=[p.strip() for p in row.split('|')]
                if len(parts)>=2 and parts[0]:
                    out['required_skills'].append({'name':parts[0], 'status':parts[1]})
        if hasattr(self,'r6_panel'):
            try:
                checked=self.r6_panel.current_review(p,state,self.actions)
                if checked and checked['status'] != '추천 보류':
                    out['training_checked']=True
                    out['training_rankings']=[{'name':a['name']} for a in checked['ranked']]
            except (ValueError,TypeError,AttributeError):pass
        if hasattr(self,'course_r12_panel'):
            record=self.course_r12_panel.last_result
            if record:
                course, candidates, advices=record
                # Course advisor results for a DIFFERENT event/style are not current.
                if course.style==p.style and course.event==p.event and p.course and (
                    course.venue in p.course and str(course.meters) in p.course):
                    out['skill_checked']=True
                    out['skill_advice']={a.name:{'verdict':a.verdict,'note':a.note} for a in advices}
        return out

    def _build_setup(self):
        frame = ttk.Frame(self.page_setup)
        frame.pack(fill='both', expand=True, padx=22, pady=18)
        self._heading(frame, '육성 목표 및 시나리오')
        ttk.Label(frame, text='추가 시나리오는 별도 엔진을 등록하는 구조입니다. 현재는 무인도 시나리오만 분석합니다.',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 15))
        self.var_scenario = tk.StringVar(value=next(iter(SCENARIOS.values())))
        self.var_event = tk.StringVar(value=EVENTS[0])
        self.var_distance = tk.StringVar(value='중거리')
        self.var_style = tk.StringVar(value='선행')
        self.var_character = tk.StringVar()
        self.var_course = tk.StringVar()
        self.var_surface = tk.StringVar(value='잔디')
        self.var_direction = tk.StringVar(value='미정')
        self.var_race_conditions = tk.StringVar()
        self.var_support_deck = tk.StringVar()
        self.var_inheritance = tk.StringVar()
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=7)
        for child in (
            self._combo(row, '시나리오', self.var_scenario, list(SCENARIOS.values()), 35),
            self._combo(row, '대회', self.var_event, EVENTS, 18),
            self._combo(row, '거리', self.var_distance, DISTANCES, 12, self._distance_changed),
            self._combo(row, '각질', self.var_style, STYLES, 12),
            self._entry(row, '캐릭터 이름 (선택)', self.var_character, 20)):
            child.pack(side='left', padx=(0, 15))
        self._heading(frame, '대회 코스 · 편성 (향후 데이터 분석용 기록)')
        race_row = ttk.Frame(frame)
        race_row.pack(fill='x', pady=5)
        for child in (self._entry(race_row, '경기장/코스 (선택)', self.var_course, 20),
                      self._combo(race_row, '마장', self.var_surface, ('잔디', '더트', '미정'), 10),
                      self._combo(race_row, '방향', self.var_direction, ('우회전', '좌회전', '직선', '미정'), 10),
                      self._entry(race_row, '마장상태·계절 등', self.var_race_conditions, 24)):
            child.pack(side='left', padx=(0, 12))
        deck_row = ttk.Frame(frame)
        deck_row.pack(fill='x', pady=4)
        for child in (self._entry(deck_row, '서포트 편성 메모', self.var_support_deck, 52),
                      self._entry(deck_row, '계승 인자 메모', self.var_inheritance, 42)):
            child.pack(side='left', padx=(0, 12))
        self._heading(frame, '목표 스탯 — 직접 수정 가능')
        ttk.Label(frame, text='처음 표시되는 수치는 입력 편의를 위한 예시이며, 챔미/리오히 권장 스탯으로 검증된 값이 아닙니다.',
                  style='Muted.TLabel').pack(anchor='w')
        targets = DEFAULT_TARGETS['중거리']
        self.var_targets = {name: tk.StringVar(value=str(value)) for name, value in zip(STATS, targets)}
        row2 = ttk.Frame(frame)
        row2.pack(fill='x', pady=12)
        for name in STATS:
            self._entry(row2, name, self.var_targets[name], 11).pack(side='left', padx=(0, 13))
        self.var_target_sp = tk.StringVar(value='2500')
        self._entry(row2, '목표 스킬 Pt (참고용)', self.var_target_sp, 14).pack(side='left')
        nav=ttk.Frame(frame);nav.pack(anchor='w',pady=(4,3))
        ttk.Button(nav, text='코스별 목표·추천 스킬', command=lambda: self.notebook.select(self.page_course_r12)).pack(side='left',padx=(0,9))
        ttk.Button(nav, text='부모·조부모·대회 미래시 (R14)', command=lambda: self.notebook.select(self.page_lineage_r14)).pack(side='left')
        ttk.Label(frame, text='⑬ 코스·스킬에서 효과 검토, ⑮ 계승·미래시에서 부모·조부모와 준비 일정 확인',style='Muted.TLabel').pack(anchor='w')
        self._heading(frame, '육성 운영')
        ttk.Label(frame, text='지원 기능: 수동 입력 → 행동별 점수와 근거 표시 → SQLite 기록 → JSON/CSV 내보내기',
                  style='Muted.TLabel').pack(anchor='w', pady=4)
        ttk.Label(frame, text='R4: 스크린샷 숫자 영역 OCR(별도 Tesseract 필요) / 예정: 게임 실시간 연동, 자동 클릭, ML',
                  style='Muted.TLabel').pack(anchor='w', pady=4)
        row3 = ttk.Frame(frame)
        row3.pack(anchor='w', pady=19)
        ttk.Button(row3, text='새 육성 기록 시작', style='Accent.TButton', command=self.start_run).pack(side='left')
        ttk.Button(row3, text='턴 분석 화면으로 이동', command=lambda: self.notebook.select(self.page_turn)).pack(side='left', padx=12)
        self.session_text = tk.StringVar(value='현재 육성 세션: 없음 (추천 계산은 가능, 저장하려면 세션 시작)')
        ttk.Label(frame, textvariable=self.session_text, style='Muted.TLabel').pack(anchor='w')

    def _distance_changed(self, _):
        value = DEFAULT_TARGETS.get(self.var_distance.get(), DEFAULT_TARGETS['중거리'])
        for name, v in zip(STATS, value):
            self.var_targets[name].set(str(v))

    def _build_turn(self):
        root = ttk.Frame(self.page_turn)
        root.pack(fill='both', expand=True, padx=14, pady=10)
        root.columnconfigure(0, weight=2)
        root.columnconfigure(1, weight=3)
        root.rowconfigure(0, weight=1)
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky='nsew')
        self._heading(left, '현재 턴 상태')
        self.var_turn_label = tk.StringVar(value='주니어급 7월 전반')
        self.var_remaining = tk.StringVar(value='48')
        self.var_energy = tk.StringVar(value='80')
        self.var_mood = tk.StringVar(value='보통')
        self.var_sp = tk.StringVar(value='200')
        self.var_tickets = tk.StringVar(value='0')
        self.var_ticket_wait = tk.StringVar(value='-1')
        self.var_development = tk.StringVar(value='0')
        self.var_skill = tk.StringVar(value='미확인')
        self.var_screenshot = tk.StringVar(value='')
        row = ttk.Frame(left)
        row.pack(fill='x', pady=4)
        self._entry(row, '턴 (직접 입력)', self.var_turn_label, 22).pack(side='left', fill='x', expand=True, padx=(0, 8))
        self._entry(row, '남은 턴', self.var_remaining, 9).pack(side='left')
        row = ttk.Frame(left)
        row.pack(fill='x', pady=4)
        for child in (self._entry(row, '체력 (0~100)', self.var_energy, 10),
                      self._combo(row, '의욕', self.var_mood, ('최상', '양호', '보통', '저조', '최저'), 10),
                      self._entry(row, '보유 스킬 Pt', self.var_sp, 12)):
            child.pack(side='left', padx=(0, 9))
        self.var_stats = {s: tk.StringVar(value='300') for s in STATS}
        self._heading(left, '현재 스탯')
        row = ttk.Frame(left)
        row.pack(fill='x')
        for s in STATS:
            self._entry(row, s, self.var_stats[s], 8).pack(side='left', padx=(0, 6))
        self._heading(left, '무인도 전용 상태')
        row = ttk.Frame(left)
        row.pack(fill='x', pady=5)
        for child in (self._entry(row, '섬 티켓', self.var_tickets, 8),
                      self._entry(row, '다음 티켓까지 턴 (-1: 미상)', self.var_ticket_wait, 12),
                      self._entry(row, '발전 Pt', self.var_development, 12)):
            child.pack(side='left', padx=(0, 10))
        row = ttk.Frame(left)
        row.pack(fill='x', pady=4)
        self._combo(row, '핵심 스킬 확보 상태', self.var_skill, ('미확인', '확보', '미확보'), 15).pack(side='left')
        ttk.Label(left, text='시설 레벨 (기록 전용: 미검증 수치는 계산식에 직접 반영하지 않음)',
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 5))
        self.var_buildings = {s: tk.StringVar(value='0') for s in STATS + ('해변의 집',)}
        row = ttk.Frame(left)
        row.pack(fill='x')
        for s in self.var_buildings:
            self._entry(row, s, self.var_buildings[s], 7).pack(side='left', padx=(0, 6))
        self._heading(left, '게임 화면 자료 (수동 첨부)')
        ttk.Button(left, text='스크린샷 선택', command=self.choose_screenshot).pack(anchor='w', pady=4)
        ttk.Label(left, textvariable=self.var_screenshot, style='Muted.TLabel', wraplength=460).pack(anchor='w')
        ttk.Label(left, text='⑤ R4 화면 인식 탭에서 OCR 후보 검수 후 스탯 등 일부 항목을 가져올 수 있습니다.',
                  style='Muted.TLabel').pack(anchor='w')

        self._heading(right, '행동별 훈련 결과 입력')
        self.action_tabs = ttk.Notebook(right)
        self.action_tabs.pack(fill='both', expand=True, pady=(8, 2))
        edit_tab = ttk.Frame(self.action_tabs)
        result_tab = ttk.Frame(self.action_tabs)
        self.action_tabs.add(edit_tab, text='훈련 수치 입력')
        self.action_tabs.add(result_tab, text='추천 비교 / 근거')
        ttk.Label(edit_tab, text='게임에 표시된 상승량을 입력해야 점수 비교가 의미 있습니다. 초기 값은 비어 있습니다.',
                  style='Muted.TLabel').pack(anchor='w')
        selrow = ttk.Frame(edit_tab)
        selrow.pack(fill='x', pady=9)
        ttk.Label(selrow, text='편집할 행동:').pack(side='left')
        self.var_selected_action = tk.StringVar(value=self.selected_action)
        self.action_combo = ttk.Combobox(selrow, textvariable=self.var_selected_action,
                                         values=TRAININGS, state='readonly', width=16)
        self.action_combo.pack(side='left', padx=10)
        self.action_combo.bind('<<ComboboxSelected>>', self.action_changed)
        self.var_gains = {s: tk.StringVar(value='0') for s in STATS}
        row = ttk.Frame(edit_tab)
        row.pack(fill='x', pady=4)
        for s in STATS:
            self._entry(row, s + ' 상승', self.var_gains[s], 8).pack(side='left', padx=(0, 6))
        self.var_gain_sp = tk.StringVar(value='0')
        self.var_delta_energy = tk.StringVar(value='0')
        self.var_friend = tk.StringVar(value='0')
        self.var_bond = tk.StringVar(value='0')
        self.var_failure = tk.StringVar(value='0')
        self.var_gain_dp = tk.StringVar(value='0')
        self.var_observed = tk.BooleanVar(value=False)
        row = ttk.Frame(edit_tab)
        row.pack(fill='x', pady=5)
        for child in (self._entry(row, '스킬 Pt 상승', self.var_gain_sp, 9),
                      self._entry(row, '체력 변화 (+/-)', self.var_delta_energy, 11),
                      self._entry(row, '우정 발동 시설 수', self.var_friend, 10)):
            child.pack(side='left', padx=(0, 8))
        row = ttk.Frame(edit_tab)
        row.pack(fill='x', pady=5)
        for child in (self._entry(row, '인연도 상승 추정', self.var_bond, 11),
                      self._entry(row, '실패 확률 %', self.var_failure, 9),
                      self._entry(row, '발전 Pt 증가', self.var_gain_dp, 10)):
            child.pack(side='left', padx=(0, 8))
        ttk.Checkbutton(edit_tab, text='이 행동의 결과를 확인함 (0 상승도 실제 확인한 값이면 체크)', variable=self.var_observed).pack(anchor='w', pady=(5, 0))
        row = ttk.Frame(edit_tab)
        row.pack(fill='x', pady=10)
        ttk.Button(row, text='현재 행동 값 적용', command=self.apply_action).pack(side='left')
        ttk.Button(row, text='가상 예제 불러오기', command=self.load_demo).pack(side='left', padx=9)
        ttk.Button(row, text='입력값 초기화', command=self.reset_actions).pack(side='left')
        self._heading(result_tab, '행동 점수 비교')
        bar = ttk.Frame(result_tab)
        bar.pack(fill='x', pady=4)
        ttk.Button(bar, text='추천 계산', style='Accent.TButton', command=self.calculate).pack(side='left')
        ttk.Button(bar, text='현 턴 기록 저장', command=self.save_turn).pack(side='left', padx=7)
        ttk.Button(bar, text='스킬 구매 추천', command=lambda: self.notebook.select(self.page_course_r12)).pack(side='left',padx=6)
        ttk.Label(bar, text='실제 선택:').pack(side='left', padx=(8, 3))
        self.var_action_choice = tk.StringVar(value='미선택')
        ttk.Combobox(bar, textvariable=self.var_action_choice, values=('미선택',) + TRAININGS, state='readonly', width=13).pack(side='left', padx=4)
        self.results = ttk.Treeview(result_tab, columns=('rank', 'action', 'score'), show='headings', height=7)
        for key, title, width in (('rank', '#', 38), ('action', '선택 행동', 115), ('score', '상대 점수*', 105)):
            self.results.heading(key, text=title)
            self.results.column(key, width=width, anchor='center')
        self.results.pack(fill='both', expand=True, pady=(6, 4))
        self.results.bind('<<TreeviewSelect>>', self.show_reason)
        self.result_status = tk.StringVar(value='훈련별 상승량을 입력하고 「추천 계산」을 누르세요.')
        ttk.Label(result_tab, textvariable=self.result_status, style='Muted.TLabel', wraplength=620).pack(anchor='w')
        self.reason = tk.Text(result_tab, height=5, wrap='word', bg=PANEL, fg=TEXT, insertbackground=TEXT,
                              bd=0, highlightthickness=0, padx=12, pady=9, font=('맑은 고딕' if os.name == 'nt' else 'DejaVu Sans', 10))
        self.reason.pack(fill='x', pady=(7, 0))
        self._text(self.reason, '선택 행동을 클릭하면 추천 근거를 확인할 수 있습니다.\n*상대 점수는 실험용 자체 점수이며, 게임의 공식 수치가 아닙니다.')

    @staticmethod
    def _text(widget, value):
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.config(state='disabled')

    def _profile(self):
        inverse = {v: k for k, v in SCENARIOS.items()}
        return RunProfile(scenario=inverse[self.var_scenario.get()],
                          event=self.var_event.get(), distance=self.var_distance.get(),
                          style=self.var_style.get(), character=self.var_character.get().strip(),
                          target_stats={s: int_safe(self.var_targets[s].get(), '목표 '+s, 0, 5000) for s in STATS},
                          target_skill_points=int_safe(self.var_target_sp.get(), '목표 스킬 Pt', 0, 20000),
                          course=self.var_course.get().strip(), surface=self.var_surface.get(),
                          course_direction=self.var_direction.get(), race_conditions=self.var_race_conditions.get().strip(),
                          support_deck=self.var_support_deck.get().strip(), inheritance_notes=self.var_inheritance.get().strip())

    def _state(self):
        return TurnState(turn_label=self.var_turn_label.get().strip(),
                         remaining_turns=int_safe(self.var_remaining.get(), '남은 턴', 0, 150),
                         energy=int_safe(self.var_energy.get(), '체력', 0, 100), mood=self.var_mood.get(),
                         stats={s: int_safe(self.var_stats[s].get(), '현재 '+s, 0, 5000) for s in STATS},
                         skill_points=int_safe(self.var_sp.get(), '스킬 Pt', 0, 20000),
                         island_tickets=int_safe(self.var_tickets.get(), '섬 티켓', 0, 99),
                         turns_until_next_ticket=int_safe(self.var_ticket_wait.get(), '다음 티켓까지 턴', -1, 150),
                         development_points=int_safe(self.var_development.get(), '발전 Pt', 0, 30000),
                         building_levels={s: int_safe(self.var_buildings[s].get(), '시설 '+s, 0, 9) for s in self.var_buildings},
                         core_skill_status=self.var_skill.get(), screenshot=self.var_screenshot.get())

    def _save_action_editor(self):
        a = self.actions[self.selected_action]
        a.gains = {s: int_safe(self.var_gains[s].get(), '상승량 '+s, 0, 999) for s in STATS}
        a.skill_points = int_safe(self.var_gain_sp.get(), '스킬 Pt 상승', 0, 9999)
        a.energy_delta = int_safe(self.var_delta_energy.get(), '체력 변화', -100, 100)
        a.friend_types = int_safe(self.var_friend.get(), '우정 발동 시설 수', 0, 5)
        a.bond_gain = int_safe(self.var_bond.get(), '인연도 상승', 0, 100)
        a.failure_percent = float_safe(self.var_failure.get(), '실패 확률', 0, 100)
        a.development_points = int_safe(self.var_gain_dp.get(), '발전 Pt', 0, 9999)
        a.observed = self.var_observed.get()

    def _load_actions_into_editor(self, name):
        a = self.actions[name]
        for s in STATS:
            self.var_gains[s].set(str(a.gains[s]))
        self.var_gain_sp.set(str(a.skill_points))
        self.var_delta_energy.set(str(a.energy_delta))
        self.var_friend.set(str(a.friend_types))
        self.var_bond.set(str(a.bond_gain))
        self.var_failure.set(str(a.failure_percent))
        self.var_gain_dp.set(str(a.development_points))
        self.var_observed.set(a.observed)

    def action_changed(self, _=None):
        new = self.var_selected_action.get()
        if new == self.selected_action:
            return
        try:
            self._save_action_editor()
        except ValueError as e:
            messagebox.showerror('입력 오류', str(e))
            self.var_selected_action.set(self.selected_action)
            return
        self.selected_action = new
        self._load_actions_into_editor(new)

    def apply_action(self):
        try:
            self._save_action_editor()
            self.r6_panel._invalidate_result()
            self.footer.set(f'{self.selected_action} 입력값을 적용했습니다. 추천을 다시 계산하세요.')
        except ValueError as e:
            messagebox.showerror('입력 오류', str(e))

    def reset_actions(self):
        self.actions = default_actions()
        self._load_actions_into_editor(self.selected_action)
        self.r6_panel.reset_turn()
        self.r7_panel.clear_review()
        self.r8_panel.clear_review()
        self.goal_r11_panel.clear()
        self.last_rankings.clear()
        self.results.delete(*self.results.get_children())
        self.result_status.set('입력값 초기화 완료. 게임의 실제 상승량을 다시 입력하세요.')

    def load_demo(self):
        if not messagebox.askyesno('가상 예제', '가상의 임의 수치를 불러옵니다. 실제 게임 추천 근거로 사용하면 안 됩니다. 계속할까요?'):
            return
        self.actions = default_actions()
        self.r6_panel.reset_turn()
        values = {
            '스피드': ([70, 3, 20, 0, 0], 40, -21, 1, 8, 3),
            '스태미나': ([10, 54, 10, 6, 0], 34, -22, 1, 8, 3),
            '파워': ([5, 7, 60, 10, 0], 42, -24, 1, 6, 3),
            '근성': ([10, 12, 16, 48, 0], 30, -22, 1, 6, 3),
            '지능': ([14, 0, 0, 0, 45], 36, 5, 1, 6, 3),
            '섬 트레이닝': ([65, 75, 70, 58, 50], 170, -18, 3, 0, 0),
            '휴식': ([0, 0, 0, 0, 0], 0, 45, 0, 0, 0),
            '외출': ([0, 0, 0, 0, 0], 0, 25, 0, 0, 0),
            '레이스': ([0, 0, 0, 0, 0], 60, -10, 0, 0, 0),
        }
        for name, (gains, sp, energy, friends, bond, fail) in values.items():
            a = self.actions[name]
            a.gains = dict(zip(STATS, gains))
            a.skill_points, a.energy_delta, a.friend_types = sp, energy, friends
            a.bond_gain, a.failure_percent = bond, fail
            a.development_points = 10 if name not in ('휴식', '외출') else 0
            a.observed = True
        self.var_tickets.set('1')
        self._load_actions_into_editor(self.selected_action)
        self.calculate()
        self.result_status.set('※ 가상 예제값입니다. 실제 게임 값으로 수정하기 전에는 추천을 사용하지 마세요.')

    def calculate(self):
        try:
            self._save_action_editor()
            profile = self._profile()
            if self.run_profile is not None and asdict(profile) != asdict(self.run_profile):
                messagebox.showwarning('육성 조건 변경', '기록 시작 후 육성 목표·경기 조건이 바뀌었습니다.\n기존 기록을 보호하기 위해 이 턴은 저장하지 않습니다.\n원래 조건으로 되돌리거나 새 육성을 시작하세요.')
                return False
            state = self._state()
            coverage = input_coverage(self.actions)
            if coverage == 0:
                messagebox.showwarning('입력 필요', '입력된 행동이 없습니다. 값을 입력하거나 확인 여부를 체크하세요.')
                return False
            self.last_rankings = rank_actions(profile, state, self.actions)
            if not self.last_rankings:
                messagebox.showwarning('추천 불가', '확인한 선택지가 모두 현재 상태에서 불가능합니다. 티켓이나 체력을 확인하세요.')
                return False
            self.action_tabs.select(1)
            self.results.delete(*self.results.get_children())
            for idx, item in enumerate(self.last_rankings, 1):
                self.results.insert('', 'end', iid=item.name, values=(idx, item.name, f'{item.score:,.1f}'))
            status, warnings = assess_run(profile, state)
            top = self.last_rankings[0].name
            confidence = '비교 제한: 입력 1개' if len(self.last_rankings) < 2 else ('자료 부족' if len(self.last_rankings) < 4 else '입력한 항목만 비교')
            self.result_status.set(f'{top} 우선 검토 | 실제 입력 {coverage}/{len(self.actions)}개 | {confidence} | {status} (ML 아님)')
            self.results.selection_set(top)
            self.show_reason()
            self.footer.set('계산 완료 · 이 점수는 게임 공식을 재현한 수치가 아니며 검증이 필요합니다.')
            return True
        except ValueError as e:
            messagebox.showerror('입력 오류', str(e))
            return False

    def show_reason(self, _=None):
        names = self.results.selection()
        if not names:
            return
        name = names[0]
        item = next((r for r in self.last_rankings if r.name == name), None)
        if not item:
            return
        text = f'[{name}] 실험용 상대 점수 {item.score:,.1f}\n'
        text += '\n'.join('• ' + explanation for explanation in item.reasons)
        text += '\n계산 요소: ' + ', '.join(f'{key} {num:+.1f}' for key, num in item.breakdown.items())
        self._text(self.reason, text)

    def choose_screenshot(self):
        path = filedialog.askopenfilename(title='우마무스메 스크린샷',
                filetypes=[('이미지', '*.png *.jpg *.jpeg *.webp'), ('모든 파일', '*.*')])
        if path:
            self.var_screenshot.set(path)

    def start_run(self):
        try:
            profile = self._profile()
            self.run_id = create_run(self.conn, asdict(profile))
            self.run_profile = profile
            self.session_text.set(f'현재 육성 세션: #{self.run_id} · {profile.character or "이름 미입력"} / {profile.event}')
            self.r6_panel.reset_turn()
            self.r7_panel.clear_review()
            self.r8_panel.clear_review()
            self.goal_r11_panel.clear()
            self.footer.set(f'육성 #{self.run_id} 시작. 턴 분석 화면에서 데이터 저장 가능.')
            self.refresh_runs()
            self.notebook.select(self.page_turn)
        except ValueError as e:
            messagebox.showerror('입력 오류', str(e))

    def _persistent_screenshot(self, state):
        if not state.screenshot:
            return
        src = Path(state.screenshot)
        if not src.is_file():
            state.screenshot = ''
            return
        dst_dir = db_path().parent / 'screenshots'
        dst_dir.mkdir(parents=True, exist_ok=True)
        dest = dst_dir / f'run{self.run_id}_{datetime.now():%Y%m%d_%H%M%S_%f}{src.suffix.lower()}'
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        state.screenshot = str(dest)

    def save_turn(self):
        if not self.run_id:
            messagebox.showwarning('세션 시작', '「육성 목표」 탭에서 새 육성 기록을 먼저 시작해 주세요.')
            self.notebook.select(self.page_setup)
            return
        if not self.calculate():
            return
        try:
            state = self._state()
            chosen = self.var_action_choice.get()
            self._persistent_screenshot(state)
            r6_review = self.r6_panel.current_review(self._profile(), state, self.actions)
            add_turn(self.conn, self.run_id, asdict(state),
                     {n: asdict(a) for n,a in self.actions.items()},
                     [asdict(r) for r in self.last_rankings], chosen,
                     r6_review=r6_review)
            self.footer.set(f'육성 #{self.run_id} · {state.turn_label} 저장 완료 · R6 검수: {"포함" if r6_review else "미완료"} · 실제 선택: {chosen}')
            self.var_action_choice.set('미선택')
            # A saved turn must not silently reuse prior choices in R6 or R5.
            self.actions = default_actions()
            self._load_actions_into_editor(self.selected_action)
            self.r6_panel.reset_turn()
            self.r7_panel.clear_review()
            self.r8_panel.clear_review()
            self.goal_r11_panel.clear()
            self.refresh_runs()
        except (ValueError, OSError) as e:
            messagebox.showerror('저장 오류', str(e))

    def _build_screen(self):
        self.screen_panel = ScreenPanel(self.page_screen, self._apply_screen_values)
        self.screen_panel.pack(fill='both', expand=True)

    def _apply_screen_values(self, values: dict, screenshot_path: str):
        mapping = {'체력': self.var_energy, '스킬 Pt': self.var_sp,
                   '섬 티켓': self.var_tickets, '발전 Pt': self.var_development}
        mapping.update(self.var_stats)
        for name, value in values.items():
            if name not in mapping:
                raise ValueError(f'지원하지 않는 필드: {name}')
            mapping[name].set(str(value))
        self.var_screenshot.set(screenshot_path)
        self.footer.set(f'화면 수치 {len(values)}개 검수 반영 · 추천 결과는 직접 다시 계산해야 합니다.')
        self.notebook.select(self.page_turn)

    def _build_training_r5(self):
        self.r5_panel = TrainingPanel(self.page_training_r5, self._profile, self._state,
                                      self._apply_r5_actions)
        self.r5_panel.pack(fill='both', expand=True)

    def _apply_r5_actions(self, actions):
        # Reset previously observed options. Old actions belong to a different inspection cycle.
        self.actions = default_actions()
        self.actions.update(actions)
        self.r6_panel.reset_turn()
        self._load_actions_into_editor(self.selected_action)
        self.last_rankings = []
        self.results.delete(*self.results.get_children())
        self.notebook.select(self.page_turn)
        self.footer.set(f'R5에서 확인된 훈련 {len(actions)}개를 전달했습니다. 휴식·외출·레이스는 별도 확인이 필요합니다.')

    def _build_decision_r6(self):
        self.r6_panel = DecisionPanel(self.page_decision_r6, self._profile, self._state,
                                      self._read_current_actions)
        self.r6_panel.pack(fill='both', expand=True)

    def _build_context_r34(self):
        self.r34_panel = IslandContextPanel(self.page_context_r34, self._profile, self._state,
                                           comparison_getter=self._read_r6_for_r8)
        self.r34_panel.pack(fill='both', expand=True)
        self.notebook.bind('<<NotebookTabChanged>>',
                           lambda _event: self.r34_panel.invalidate_external(), add='+')

    def _build_island_r7(self):
        self.r7_panel = IslandPlannerPanel(self.page_island_r7, self._profile, self._state)
        self.r7_panel.pack(fill='both', expand=True)

    def _read_r6_for_r8(self, profile, state):
        """Return only a current-turn verified R6 review with its evidence."""
        try:
            actions = self._read_current_actions()
            review = self.r6_panel.current_review(profile, state, actions)
        except (ValueError, TypeError):
            return None
        if review is None:
            return None
        return review, actions, dict(self.r6_panel.availability)

    def _build_calibration_r9(self):
        self.r9_panel = CalibrationPanel(self.page_calibration_r9)
        self.r9_panel.pack(fill="both", expand=True)

    def _build_island_r8(self):
        self.r8_panel = IslandImpactPanel(self.page_island_r8, self._profile, self._state,
                                          self.r7_panel.current_plan, self._read_r6_for_r8)
        self.r8_panel.pack(fill='both', expand=True)

    def _read_current_actions(self):
        # Transfer unsaved editor values to the comparison, including rest/race/outing.
        self._save_action_editor()
        return self.actions

    def _build_records(self):
        page = ttk.Frame(self.page_records)
        page.pack(fill='both', expand=True, padx=20, pady=16)
        self._heading(page, '로컬 육성 기록')
        ttk.Label(page, text='데이터는 이 PC의 로컬 SQLite에만 저장됩니다. 서버 전송이나 AI 자동 학습은 없습니다.',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 12))
        self.runs_tree = ttk.Treeview(page, columns=('id', 'created', 'event', 'distance', 'character', 'turns', 'outcome'), show='headings', height=5)
        for key, title, width in (('id', '#', 55), ('created', '시작 시각', 180), ('event', '대회', 150),
                                  ('distance', '거리', 80), ('character', '캐릭터', 150), ('turns', '기록 턴 수', 110), ('outcome', '결과', 100)):
            self.runs_tree.heading(key, text=title)
            self.runs_tree.column(key, width=width, anchor='center')
        self.runs_tree.pack(fill='x')
        row = ttk.Frame(page)
        row.pack(fill='x', pady=12)
        for label, command in (('새로고침', self.refresh_runs), ('선택 기록 이어쓰기', self.resume_run),
                               ('전체 CSV 내보내기', self.do_csv), ('전체 JSON 내보내기', self.do_json),
                               ('연구용 CSV', self.do_dataset), ('SQLite 백업', self.do_backup), ('저장 폴더 열기', self.open_folder)):
            ttk.Button(row, text=label, command=command).pack(side='left', padx=(0, 9))
        self._heading(page, '완주 / 중단(도축) 결과 등록 — 선택한 세션에 저장')
        outrow = ttk.Frame(page)
        outrow.pack(fill='x', pady=4)
        self.var_outcome_status = tk.StringVar(value='진행중')
        self.var_outcome_reason = tk.StringVar()
        self.var_outcome_final = tk.StringVar()
        self.var_outcome_notes = tk.StringVar()
        for child in (self._combo(outrow, '결과 상태', self.var_outcome_status, ('진행중', '육성 완료', '도축/중단'), 13),
                      self._entry(outrow, '도축 사유 (미상 입력 가능)', self.var_outcome_reason, 28),
                      self._entry(outrow, '최종 스탯 메모', self.var_outcome_final, 30)):
            child.pack(side='left', padx=(0, 10))
        outrow2 = ttk.Frame(page)
        outrow2.pack(fill='x', pady=4)
        self._entry(outrow2, '스킬/성과/중단 이유 추가 메모', self.var_outcome_notes, 60).pack(side='left')
        ttk.Button(outrow2, text='선택 세션 결과 저장', style='Accent.TButton', command=self.save_outcome).pack(side='left', padx=10, pady=13)
        self._heading(page, '선택 세션의 저장 턴')
        self.turn_list = tk.Text(page, height=5, wrap='word', bg=PANEL, fg=TEXT,
                                 highlightthickness=0, bd=0, padx=14, pady=12)
        self.turn_list.pack(fill='both', expand=True)
        self.runs_tree.bind('<<TreeviewSelect>>', self.show_turns)

    def _build_analytics(self):
        page = ttk.Frame(self.page_analytics)
        page.pack(fill='both', expand=True, padx=22, pady=17)
        self._heading(page, 'R3 · 실제 기록과 연구 데이터 품질 검증')
        ttk.Label(page, text='추천 점수와 실제 선택의 일치 여부를 감사합니다. 일치율은 정확도·승률이 아니며 도축 자동 추천도 하지 않습니다.',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        row = ttk.Frame(page)
        row.pack(fill='x', pady=8)
        ttk.Button(row, text='선택한 세션 분석', style='Accent.TButton', command=self.analyze_selected).pack(side='left')
        ttk.Button(row, text='모든 기록·연구 자료 감사', command=self.analyze_corpus).pack(side='left', padx=8)
        ttk.Button(row, text='분석 내용 JSON 저장', command=self.export_analysis).pack(side='left')
        ttk.Button(row, text='검증 영상 후보 CSV', command=self.export_verified).pack(side='left', padx=8)
        self.analytics_status = tk.StringVar(value='③ 기록 탭에서 육성 세션을 선택한 뒤 분석하세요. 기록이 없으면 전체 감사부터 확인할 수 있습니다.')
        ttk.Label(page, textvariable=self.analytics_status, style='Muted.TLabel', wraplength=980).pack(anchor='w', pady=(4, 8))
        self.analytics_text = tk.Text(page, wrap='word', bg=PANEL, fg=TEXT, bd=0,
                                      highlightthickness=0, padx=18, pady=15)
        self.analytics_text.pack(fill='both', expand=True)
        self._text(self.analytics_text, 'R3은 관측 기록의 목표 부담, 연속 턴 상승 추세, 수동 선택-추천 일치율을 설명합니다.\n\n'
                   '최소 5쌍의 연속 스탯 기록이 있어야 과거 상승 추세를 표시합니다.\n'
                   '목표 부담은 미래 성장 예측이나 최적 행동의 증거가 아닙니다.\n'
                   '수정 후 일본 영상에서 실제 검수한 턴이 0건이면 학습 가능 자료 0건으로 표시합니다.')
        self.latest_r3_report = None

    def analyze_selected(self):
        selected = self.runs_tree.selection()
        rid = int(selected[0]) if selected else self.run_id
        if rid is None:
            messagebox.showinfo('선택 필요', '③ 기록에서 육성 세션을 선택하거나 새 육성을 기록해 주세요.')
            return
        try:
            report = run_audit(self.conn, rid)
        except (ValueError, KeyError) as err:
            messagebox.showerror('분석 실패', str(err))
            return
        self.latest_r3_report = report
        lines = [f"육성 #{rid} | {report['event']} | 저장 턴 {report['total_recorded_turns']}개",
                 f"연속 턴 관측 구간 {report['consecutive_observed_intervals']}개 (인과관계 미확인)",
                 f"비교 가능한 선택 {report['comparison_turns']}개 / 추천과 일치 {report['heuristic_agreement_turns']}개",
                 f"육성 결과: {(report['outcome'] or {}).get('status','진행중')}",
                 f"분석 상태: {report['status']}", '',
                 '목표까지 남은 상승량 | 남은 턴당 필요 증가량 | 과거 턴 상승 분포']
        for g in report['targets']:
            need = f"{g['required_per_turn']:.1f}" if g['required_per_turn'] is not None else '자료 없음'
            historical = (f"중앙값 {g['observed_median']:.1f}, 상위25% 경계 {g['observed_p75']:.1f}"
                          if g['observed_median'] is not None else '연속 관측 5개 미만')
            lines.append(f"• {g['stat']}: 부족 {g['gap']} / 필요 {need} / {historical} / {g['flag']}")
        lines += ['', '검증상 주의', report['interpretation'], report['model_status']]
        if report['warnings']:
            lines += ['', '제외·경고 로그'] + report['warnings']
        self._text(self.analytics_text, '\n'.join(lines))
        self.analytics_status.set(f'육성 #{rid} 기록 감사 완료 · ML 예측 아님')
        self.notebook.select(self.page_analytics)

    def _r3_video_path(self):
        return ROOT / 'research' / 'video_reviews' / 'verified_turns.csv'

    def analyze_corpus(self):
        corpus = corpus_audit(self.conn)
        video = audit_verified_video_turns(self._r3_video_path())
        self.latest_r3_report = {'report_version': 'R3-corpus-v1',
                                  'local_corpus': corpus, 'jp_video_audit':
                                  {k: v for k, v in video.items() if k != 'candidates'},
                                  'ml_status': 'NO_MODEL_TRAINED'}
        lines = ['R3 · 전체 연구 품질 감사',
                 f"로컬 육성 세션 {corpus['runs']}건 / 저장된 턴 {corpus['recorded_turns']}개",
                 f"완주 기록(턴 포함) {corpus['completed_with_turns']}건 / 중단 기록(턴 포함) {corpus['abandoned_with_turns']}건",
                 f"최종 결과 유형: {corpus['outcomes']}", '',
                 f"일본 영상 검수 파일: {'존재' if video['found'] else '없음'}",
                 f"영상 기록 총 {video['total']}건 / 실전 본육성 검증 후보 {video['qualified_main_run_turns']}건",
                 f"제외 사유: {video['excluded']}", '',
                 '모델 학습 상태: 아직 학습하지 않음',
                 '검수된 사람의 선택도 최적 선택의 정답을 의미하지 않습니다.',
                 '영상·육성 세션 단위로 데이터를 분리해 편향 없이 검증해야 합니다.']
        self._text(self.analytics_text, '\n'.join(lines))
        self.analytics_status.set('전체 데이터 감사 완료 · 검증되지 않은 자료는 학습 후보에서 제외')
        self.notebook.select(self.page_analytics)

    def export_analysis(self):
        if self.latest_r3_report is None:
            messagebox.showinfo('분석 필요', '먼저 세션 분석 또는 전체 자료 감사를 실행하세요.')
            return
        filename = filedialog.asksaveasfilename(defaultextension='.json',
                initialfile='UmaTrainerKR_R3_감사보고서.json', filetypes=[('JSON 파일','*.json')])
        if filename:
            try:
                export_r3_report(self.latest_r3_report, Path(filename))
                messagebox.showinfo('저장 완료', '관측 자료 감사 보고서가 저장되었습니다.')
            except OSError as err:
                messagebox.showerror('저장 실패', str(err))

    def export_verified(self):
        filename = filedialog.asksaveasfilename(defaultextension='.csv',
                initialfile='UmaTrainerKR_R3_검증영상후보.csv', filetypes=[('CSV 파일','*.csv')])
        if filename:
            try:
                audit = audit_verified_video_turns(self._r3_video_path())
                export_verified_candidates_csv(audit, Path(filename))
                messagebox.showinfo('저장 완료', f"자료 검증을 통과한 턴 {audit['qualified_main_run_turns']}개만 저장했습니다. 모델 학습은 하지 않았습니다.")
            except (OSError, ValueError) as err:
                messagebox.showerror('저장 실패', str(err))

    def refresh_runs(self):
        self.runs_tree.delete(*self.runs_tree.get_children())
        for r in list_runs(self.conn):
            p = r['profile']
            self.runs_tree.insert('', 'end', iid=str(r['id']),
                values=(r['id'], r['created_at'][:19], p.get('event', ''),
                        p.get('distance', ''), p.get('character', ''), r['turn_count'],
                        r.get('outcome', {}).get('status', '진행중')))

    def show_turns(self, _=None):
        sel = self.runs_tree.selection()
        if not sel:
            return
        run_info = next((r for r in list_runs(self.conn) if r['id'] == int(sel[0])), None)
        if run_info:
            outcome = run_info.get('outcome', {})
            self.var_outcome_status.set(outcome.get('status', '진행중'))
            self.var_outcome_reason.set(outcome.get('reason', ''))
            self.var_outcome_final.set(outcome.get('final_stats', ''))
            self.var_outcome_notes.set(outcome.get('notes', ''))
        lines = []
        for turn in list_turns(self.conn, int(sel[0])):
            state = turn['state']
            top = turn['rankings'][0] if turn['rankings'] else {}
            lines.append(f"[{turn['created_at'][:19]}] {state['turn_label']} | "+
                         f"추천: {top.get('name','-')} ({top.get('score','-')}) | "+
                         f"실제 선택: {turn['chosen_action']} | 스탯: {state['stats']}")
        self._text(self.turn_list, '\n\n'.join(lines) if lines else '아직 저장된 턴이 없습니다.')

    def resume_run(self):
        sel = self.runs_tree.selection()
        if not sel:
            messagebox.showinfo('선택 필요', '먼저 육성 세션을 선택하세요.')
            return
        rid = int(sel[0])
        p = next(r['profile'] for r in list_runs(self.conn) if r['id'] == rid)
        self.run_id = rid
        self.run_profile = RunProfile(**p)
        self.var_scenario.set(SCENARIOS.get(p.get('scenario', ''), next(iter(SCENARIOS.values()))))
        self.var_event.set(p['event'])
        self.var_distance.set(p['distance'])
        self.var_style.set(p['style'])
        self.var_character.set(p.get('character', ''))
        self.var_course.set(p.get('course', ''))
        self.var_surface.set(p.get('surface', '잔디'))
        self.var_direction.set(p.get('course_direction', '미정'))
        self.var_race_conditions.set(p.get('race_conditions', ''))
        self.var_support_deck.set(p.get('support_deck', ''))
        self.var_inheritance.set(p.get('inheritance_notes', ''))
        for s in STATS:
            self.var_targets[s].set(str(p.get('target_stats', {}).get(s, 0)))
        self.var_target_sp.set(str(p.get('target_skill_points', 0)))
        self.session_text.set(f'현재 육성 세션: #{rid} · 이전 기록 이어쓰기')
        turns = list_turns(self.conn, rid)
        if turns:
            state = turns[-1]['state']
            self.var_turn_label.set(state.get('turn_label',''))
            for attr, var in (('remaining_turns', self.var_remaining), ('energy', self.var_energy),
                              ('skill_points', self.var_sp), ('island_tickets', self.var_tickets),
                              ('turns_until_next_ticket', self.var_ticket_wait),
                              ('development_points', self.var_development)):
                var.set(str(state.get(attr, '0')))
            self.var_mood.set(state.get('mood', '보통'))
            self.var_skill.set(state.get('core_skill_status', '미확인'))
            self.var_screenshot.set(state.get('screenshot', ''))
            for s in STATS:
                self.var_stats[s].set(str(state.get('stats', {}).get(s, '0')))
            for s in self.var_buildings:
                self.var_buildings[s].set(str(state.get('building_levels', {}).get(s, '0')))
            self.actions = {n: Action(**a) for n,a in turns[-1]['options'].items()}
            self._load_actions_into_editor(self.selected_action)
        self.notebook.select(self.page_turn)
        self.footer.set(f'육성 #{rid} 이어쓰기 선택. 저장 전에 다음 턴 입력값을 확인하세요.')

    def save_outcome(self):
        sel = self.runs_tree.selection()
        if not sel:
            messagebox.showwarning('세션 선택', '결과를 저장할 육성 세션을 먼저 선택하세요.')
            return
        try:
            save_run_outcome(self.conn, int(sel[0]), {
                'status': self.var_outcome_status.get(),
                'reason': self.var_outcome_reason.get().strip(),
                'final_stats': self.var_outcome_final.get().strip(),
                'notes': self.var_outcome_notes.get().strip(),
            })
            rid = int(sel[0])
            self.refresh_runs()
            self.runs_tree.selection_set(str(rid))
            self.footer.set(f'육성 #{rid} 실제 완료/중단 결과 저장됨')
        except ValueError as error:
            messagebox.showerror('결과 저장 오류', str(error))

    def do_backup(self):
        path = filedialog.asksaveasfilename(defaultextension='.sqlite3',
            initialfile='UmaTrainerKR_백업.sqlite3', filetypes=[('SQLite DB', '*.sqlite3')])
        if path:
            try:
                backup_database(self.conn, Path(path))
                messagebox.showinfo('백업 완료', f'현재 데이터베이스 백업 완료\n{path}')
            except OSError as e:
                messagebox.showerror('백업 오류', str(e))

    def do_json(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='UmaTrainerKR_runs.json',
                                            filetypes=[('JSON 파일', '*.json')])
        if path:
            export_json(self.conn, Path(path))
            messagebox.showinfo('완료', f'JSON 저장 완료\n{path}')

    def do_dataset(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv',
            initialfile='UmaTrainerKR_연구용_행동기록.csv', filetypes=[('CSV 파일', '*.csv')])
        if path:
            result = export_decisions_csv(self.conn, Path(path))
            messagebox.showinfo('내보내기',
                f'기록된 선택 {result["exported"]}개 내보냄 / 불완전 기록 {result["skipped"]}개 제외.\n'
                '사람이 선택한 행동은 최적 행동의 정답이 아닙니다. ML은 학습하지 않았습니다.')

    def do_csv(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='UmaTrainerKR_turns.csv',
                                            filetypes=[('CSV 파일', '*.csv')])
        if path:
            export_csv(self.conn, Path(path))
            messagebox.showinfo('완료', f'CSV 저장 완료\n{path}')

    def open_folder(self):
        directory = str(db_path().parent)
        if os.name == 'nt':
            os.startfile(directory)
        else:
            messagebox.showinfo('저장 위치', directory)

    def _build_review_r10(self):
        self.review_r10_panel = ReviewQueuePanel(self.page_review_r10)
        self.review_r10_panel.pack(fill='both', expand=True)

    def _build_goal_r11(self):
        self.goal_r11_panel = GoalPanel(self.page_goal_r11, self._profile, self._state,
                                      lambda: (self.conn, self.run_id))
        self.goal_r11_panel.pack(fill='both', expand=True)

    def _apply_course_from_r12(self,c):
        self.var_course.set(f'{c.venue} {c.meters}m')
        self.var_surface.set(c.surface)
        self.var_direction.set({'좌회전':'좌회전','우회전':'우회전','직선':'직선','미정':'미정'}[c.direction])
        self.var_distance.set('단거리' if c.meters <= 1400 else '마일' if c.meters <= 1800 else '중거리' if c.meters <= 2400 else '장거리')
        self.var_style.set(c.style)
        self.var_event.set(c.event)
        self.var_race_conditions.set(f'{c.season}/{c.weather}/{c.ground}')

    def _build_course_r12(self):
        self.course_r12_panel=CourseSkillPanel(self.page_course_r12,self._profile,self._apply_course_from_r12)
        self.course_r12_panel.pack(fill='both',expand=True)

    def _build_sources(self):
        page = ttk.Frame(self.page_sources)
        page.pack(fill='both', expand=True, padx=20, pady=18)
        self._heading(page, '일본 무인도 수정 후 자료 목록')
        ttk.Label(page, text='자료 목록을 등록한 상태입니다. 영상을 대규모 수집하거나 모델을 학습한 상태는 아닙니다.',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        self.library_tree = ttk.Treeview(page, columns=('type', 'title', 'verified'), show='headings', height=7)
        for k,t,w in (('type','분류',160), ('title','자료명',480), ('verified','검증 상태',300)):
            self.library_tree.heading(k, text=t)
            self.library_tree.column(k, width=w, anchor='w')
        self.library_tree.pack(fill='x')
        self.library_tree.bind('<Double-1>', self.open_source)
        ttk.Label(page, text='자료를 더블클릭하면 원본 링크를 브라우저로 엽니다.', style='Muted.TLabel').pack(anchor='w', pady=9)
        self._heading(page, '현재 구현·검증 상태')
        details = (
            '구현됨: 무인도 시나리오 플러그인 / 챔미·리오히 프로필 / 입력된 선택지끼리만 비교 / 추천 근거 표시 / 실제 완료·중단 기록 / SQLite 백업·CSV·JSON 내보내기\n\n'
            'R4/R5 추가: 숫자 OCR 후보 검수, 훈련별 확인 필드 검사, 모든 훈련 필수값이 확인되기 전에는 추천 보류.\n\n'
            '부분 구현: R3 관측 기반 목표 부담/연속 턴 추세/선택 일치율 감사, 실제 중단 사유 기록. 자동 포기 권유 및 성공확률 예측 없음.\n\n'
            '미구현: 한국 서버 실화면 자동 인식 / 게임 자동 조작 / 시설별 정확한 공식 / 이벤트 분기 / 스킬 자동 OCR / 실측 기반 발동률 모델 / 승률·고점·도축 확률 ML (R16 행동 모방 연구 ML 코드만 구현)\n\n'
            '수치 검증 미완료: 일본 2025-06-30 조정 이후 자료에 근거한 방향성만 참조. 한국 서버 게임 내 실제 상승량을 수집해서 계산식 검증 필요.\n\n'
            '행동 점수는 임의의 실험용 가중치이므로 승률·최종 점수·게임 공식과 같지 않습니다.\n\n'
            '실전 데이터를 분석할 때는 성공 사례 외에 실패·도축 기록을 함께 확보해야 선택 편향을 줄일 수 있습니다.'
        )
        box = tk.Text(page, height=15, wrap='word', bg=PANEL, fg=TEXT,
                      highlightthickness=0, bd=0, padx=16, pady=12)
        box.pack(fill='both', expand=True)
        self._text(box, details)

    def _load_library(self):
        self.sources = []
        file = ROOT / 'research' / 'sources.json'
        if file.is_file():
            self.sources = json.loads(file.read_text('utf-8'))['sources']
        for idx, item in enumerate(self.sources):
            self.library_tree.insert('', 'end', iid=str(idx),
                values=(item['category'], item['name'], item['verified_as']))

    def open_source(self, _=None):
        sel = self.library_tree.selection()
        if sel:
            webbrowser.open(self.sources[int(sel[0])]['url'])


    def _build_learning_r15(self):
        self.learning_r15_panel = LearningPanel(self.page_learning_r15, self.conn)
        self.learning_r15_panel.pack(fill="both", expand=True)

    def _build_ml_r16(self):
        self.ml_r16_panel = MLResearchPanel(self.page_ml_r16)
        self.ml_r16_panel.pack(fill="both", expand=True)

    def _build_ml_r17(self):
        self.ml_r17_panel = R17ResearchPanel(self.page_ml_r17, self.conn)
        self.ml_r17_panel.pack(fill="both", expand=True)

    def _build_lineage_r14(self):
        self.lineage_r14_panel=LineageCalendarPanel(self.page_lineage_r14)
        self.lineage_r14_panel.pack(fill="both",expand=True)

    def _build_event_r13(self):
        self.event_r13_panel=EventPlanPanel(self.page_event_r13,self._apply_r13_event_to_course)
        self.event_r13_panel.pack(fill='both',expand=True)

    def _apply_r13_event_to_course(self,event_id,style):
        from plan_r13 import load_pack
        ev=next(x for x in load_pack()['events'] if x['id']==event_id)
        panel=self.course_r12_panel
        key=f"{ev['venue']} 잔디 {ev['meters']}m"
        panel.preset.set(key if key in __import__('course_advisor_r12').COURSES else '직접 입력')
        for k,v in {'venue':ev['venue'],'meters':str(ev['meters']),
                    'surface':ev['surface'],'direction':ev['direction'],
                    'season':ev['season'],'weather':ev['weather'],
                    'ground':ev['ground'],'style':style,'event':ev['kind']}.items():
            getattr(panel,k).set(v)
        panel.end.set(ev['end'] if panel.preset.get()!='직접 입력' else '미검증')
        panel.clear_results()
        # Transfer the R13 shortlist only when the user has not typed purchase candidates.
        # Names remain candidates with UNKNOWN ownership/Pt, never auto-purchased.
        if not panel.skilltext.get('1.0','end').strip():
            targets=self.event_r13_panel.last.target_skills if self.event_r13_panel.last else []
            panel.skilltext.insert('1.0','\n'.join(dict.fromkeys(targets)))
        self.notebook.select(self.page_course_r12)

    def _quit(self):
        self.conn.close()
        self.destroy()


def main():
    app = UmaApp()
    app.mainloop()


if __name__ == '__main__':
    from package_selftest_r25 import maybe_run_cli
    maybe_run_cli("UmaTrainerKR")
    from package_selftest_r25 import maybe_run_startup_cli
    maybe_run_startup_cli("UmaTrainerKR")
    try:
        main()
    except Exception:
        path = db_path().parent / 'last_crash.log'
        path.write_text(traceback.format_exc(), encoding='utf-8')
        raise
