"""R7 island-specific construction planner panel; no gameplay control."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from uma_core import STATS
from island_planner_r7 import (FACILITIES, ROUTES, PHASE_NAMES, SLOTS_BY_TUCKER,
                               plan_island, export_plan, fingerprint)


class IslandPlannerPanel(ttk.Frame):
    def __init__(self, parent, profile_getter, state_getter):
        super().__init__(parent)
        self.get_profile, self.get_state = profile_getter, state_getter
        self._result = None
        self._snapshot = None
        self._plan_options = None
        self._build()

    def _build(self):
        canvas = tk.Canvas(self, bg='#111827', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        parent = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=parent, anchor='nw')
        parent.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))

        ttk.Label(parent, text='R7 · 무인도 시설 건설 / 평가회 / 섬 트레이닝 계획',
                  style='Section.TLabel').pack(anchor='w', padx=20, pady=(16, 4))
        ttk.Label(parent, text='일본 2025-06-30 수정 후 참고 · 실제 한국 서버 수치 미검증 · 시설 상태는 ② 턴 분석의 값 사용',
                  style='Muted.TLabel').pack(anchor='w', padx=20, pady=(0, 12))
        field = ttk.Frame(parent)
        field.pack(fill='x', padx=20)
        self.phase = tk.StringVar(value='1')
        self.tucker = tk.StringVar(value='Lv41~50')
        self.growth = tk.StringVar(value='없음')
        for title, var, options, width in (
            ('현재 건설 회차', self.phase, [str(n) for n in range(1, 6)], 12),
            ('터커 브라인 레벨', self.tucker, list(SLOTS_BY_TUCKER), 15),
            ('캐릭터 성장 보정이 높은 스탯', self.growth, ['없음', *STATS], 18)):
            group = ttk.Frame(field)
            group.pack(side='left', padx=(0, 15))
            ttk.Label(group, text=title, style='Muted.TLabel').pack(anchor='w')
            ttk.Combobox(group, textvariable=var, values=options, state='readonly', width=width).pack()
        ttk.Label(parent, text='서포트 카드 타입별 개수 (모르면 0으로 둠 · 총 6장 이하)',
                  style='Section.TLabel').pack(anchor='w', padx=20, pady=(14, 4))
        support_row = ttk.Frame(parent)
        support_row.pack(fill='x', padx=20)
        self.support_counts = {}
        for stat in STATS:
            group = ttk.Frame(support_row)
            group.pack(side='left', padx=(0, 15))
            ttk.Label(group, text=stat, style='Muted.TLabel').pack(anchor='w')
            self.support_counts[stat] = tk.StringVar(value='0')
            ttk.Combobox(group, width=7, textvariable=self.support_counts[stat],
                         values=[str(i) for i in range(7)], state='readonly').pack()
        ttk.Label(parent, text='현재 시설 강화 분기 (Lv3 이상 시설은 반드시 선택)',
                  style='Section.TLabel').pack(anchor='w', padx=20, pady=(14, 4))
        route_row = ttk.Frame(parent)
        route_row.pack(fill='x', padx=20)
        self.route_vars = {}
        for stat in STATS:
            group = ttk.Frame(route_row)
            group.pack(side='left', padx=(0, 15))
            ttk.Label(group, text=stat, style='Muted.TLabel').pack(anchor='w')
            self.route_vars[stat] = tk.StringVar(value='미선택')
            ttk.Combobox(group, textvariable=self.route_vars[stat], values=ROUTES,
                         width=9, state='readonly').pack()
        ttk.Label(parent, text='평가회 진척 확인 (실제 화면 수치만 입력 · 모르면 빈칸)',
                  style='Section.TLabel').pack(anchor='w', padx=20, pady=(14, 4))
        progress_row = ttk.Frame(parent)
        progress_row.pack(fill='x', padx=20)
        self.exam_target = tk.StringVar()
        self.exam_turns = tk.StringVar()
        self.dp_per_turn = tk.StringVar()
        for title, var in (('이번 평가회 목표 발전 Pt', self.exam_target),
                           ('평가회까지 남은 턴', self.exam_turns),
                           ('턴당 예상 발전 Pt(가정)', self.dp_per_turn)):
            group = ttk.Frame(progress_row)
            group.pack(side='left', padx=(0, 18))
            ttk.Label(group, text=title, style='Muted.TLabel').pack(anchor='w')
            ttk.Entry(group, textvariable=var, width=17).pack()
        ttk.Label(parent, text='섬 티켓 안내 (현재 티켓 수·다음 지급 시점은 ② 턴 분석 값 사용)',
                  style='Section.TLabel').pack(anchor='w', padx=20, pady=(14, 4))
        ticket_row = ttk.Frame(parent)
        ticket_row.pack(fill='x', padx=20)
        self.after_sep = tk.BooleanVar(value=False)
        ttk.Checkbutton(ticket_row, text='시니어 9월 전반 이후 (티켓 상한 3장)',
                        variable=self.after_sep).pack(side='left')
        ttk.Label(ticket_row, text='우정 훈련 시설 수', style='Muted.TLabel').pack(side='left', padx=(22, 5))
        self.friends = tk.StringVar(value='미확인')
        ttk.Combobox(ticket_row, textvariable=self.friends, values=['미확인', *[str(i) for i in range(6)]],
                     state='readonly', width=10).pack(side='left')
        button_row = ttk.Frame(parent)
        button_row.pack(fill='x', padx=20, pady=(15, 7))
        ttk.Button(button_row, text='시설 건설 경로 비교', style='Accent.TButton',
                   command=self.calculate).pack(side='left')
        ttk.Button(button_row, text='현재 분석 JSON 저장', command=self.save_json).pack(side='left', padx=10)
        self.status = tk.StringVar(value='시설 레벨은 ② 턴 분석에서 입력해야 합니다. 데이터 검증 전 임시 추천 모델입니다.')
        ttk.Label(parent, textvariable=self.status, style='Muted.TLabel', wraplength=1030).pack(anchor='w', padx=20, pady=(4, 6))
        self.paths = ttk.Treeview(parent, columns=('candidate','phase','budget','steps'), show='headings', height=13)
        for col,title,width in (('candidate','경로',75), ('phase','건설 회차',175),
                                ('budget','사용/최대',110), ('steps','강화 계획',650)):
            self.paths.heading(col, text=title)
            self.paths.column(col,width=width,anchor='w' if col == 'steps' else 'center')
        self.paths.pack(fill='x', padx=20)
        self.detail = tk.Text(parent, bg='#192438', fg='#F3F6FB', wrap='word', height=12,
                              font=('맑은 고딕',10), padx=12, pady=10, relief='flat')
        self.detail.pack(fill='x', padx=20, pady=(10,15))
        self._detail('구조 규칙은 참고 자료로 검증했지만 건설 우선순위 점수는 독자적인 가정입니다.\n'
                     '이 화면은 실제 게임 결과를 학습한 ML이 아니며, 건설·도축·클릭을 자동 실행하지 않습니다.')
        ttk.Label(parent, text='정확한 시설 건설 순서와 발전 Pt의 실전 수익성은 추후 한국 서버 화면으로 검증해야 합니다.',
                  style='Muted.TLabel').pack(anchor='w', padx=20, pady=(0,15))

    def clear_review(self):
        """Invalidate R7 analysis when a new run/turn is started or saved."""
        self._result = self._snapshot = self._plan_options = None
        self.paths.delete(*self.paths.get_children())
        self.status.set('새 육성 또는 새 턴입니다. 시설 계획을 다시 확인해야 합니다.')
        self._detail('이전 턴의 계획과 근거는 새 턴에 자동 재사용하지 않습니다.')

    def current_plan(self, profile, state):
        """Allow R8 to reuse only a CURRENT-TURN successfully reviewed R7 plan."""
        if self._result is None or self._plan_options is None:
            return None
        if self._result.errors or not self._result.candidates:
            return None
        try:
            options = self._options_from_ui()
        except (ValueError, TypeError):
            return None
        if fingerprint(profile, state, options) != self._result.context_hash:
            return None
        return self._result, options

    def _detail(self, text):
        self.detail.config(state='normal')
        self.detail.delete('1.0','end')
        self.detail.insert('1.0',text)
        self.detail.config(state='disabled')

    def _options_from_ui(self):
        def optional(name, var):
            raw = var.get().strip()
            if not raw: return None
            if not raw.isascii() or not raw.isdecimal():
                raise ValueError(f'{name}에는 0 이상의 정수를 입력하세요.')
            return int(raw)
        return {
            'phase': int(self.phase.get()), 'tucker': self.tucker.get(),
            'routes': {**{s: self.route_vars[s].get() for s in STATS}, '해변의 집': '미선택'},
            'support_counts': {s: int(self.support_counts[s].get()) for s in STATS},
            'growth_bonus_stat': self.growth.get(), 'exam_target': optional('목표 발전 Pt', self.exam_target),
            'exam_turns': optional('평가회까지 남은 턴', self.exam_turns),
            'expected_dp_per_turn': optional('턴당 예상 발전 Pt', self.dp_per_turn),
            'senior_september_or_later': self.after_sep.get(),
            'friendship_locations': None if self.friends.get() == '미확인' else int(self.friends.get())}

    def calculate(self):
        self._result = self._snapshot = self._plan_options = None
        self.paths.delete(*self.paths.get_children())
        try:
            profile, state = self.get_profile(), self.get_state()
            options = self._options_from_ui()
            result = plan_island(profile, state, **options)
        except (ValueError, TypeError) as e:
            self.status.set(f'입력 확인 필요: {e}')
            self._detail(str(e))
            return
        if result.errors:
            self.status.set(f'추천 보류 · 확인할 항목 {len(result.errors)}개')
            self._detail('\n'.join('• '+msg for msg in result.errors))
            return
        self._result, self._plan_options, self._snapshot = result, options, (profile, state)
        for index, candidate in enumerate(result.candidates,1):
            for stage in candidate.phases:
                upgrades = ', '.join(f'{up.facility} Lv{up.new_level}' +
                                     (f'({up.route})' if up.route!='미선택' else '')
                                     for up in stage.upgrades) or '강화 없음'
                self.paths.insert('', 'end', values=(f'후보 {index}',
                    f'{stage.phase}회차 · {stage.title}', f'{stage.used}/{stage.capacity}',upgrades))
        self.status.set(f'{result.status} · {len(result.candidates)}개 후보 경로 · 실제 최적 성장을 검증한 결과가 아님')
        summaries = []
        for i, c in enumerate(result.candidates,1):
            levels = ', '.join(f'{s} {v}' for s,v in c.final_levels.items())
            summaries.append(f'후보 {i} (실험 상대점수 {c.score_proxy:.1f}) · 최종 예상 시설: {levels}')
        self._detail('\n'.join(summaries + ['','[평가회 진행 상황]'] + result.progress +
                               ['','[섬 티켓 안내]'] + result.ticket_advice +
                               ['','[한계 및 주의]'] + result.warnings))

    def save_json(self):
        if self._result is None or self._plan_options is None or self._snapshot is None:
            messagebox.showwarning('계획 확인', '먼저 현재 상태의 시설 계획을 계산하세요.')
            return
        try:
            profile, state = self.get_profile(), self.get_state()
            now_options = self._options_from_ui()
            if fingerprint(profile, state, now_options) != self._result.context_hash:
                messagebox.showwarning('입력 변경', '상태나 설정이 변경되어 계획을 다시 계산해야 합니다.')
                return
            path = filedialog.asksaveasfilename(title='실험용 시설 계획 저장',
                defaultextension='.json', filetypes=[('JSON','*.json')])
            if not path:
                return
            export_plan(path, profile, state, self._result, now_options)
            self.status.set(f'실험용 R7 시설 계획 저장 완료: {path}')
        except (ValueError, OSError) as e:
            messagebox.showerror('저장 오류',str(e))
