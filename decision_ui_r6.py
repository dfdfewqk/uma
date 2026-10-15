"""R6 Tkinter panel: explicit availability/evidence gates and explainable scoring."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from uma_core import TRAININGS
from decision_r6 import (UNKNOWN, AVAILABLE, UNAVAILABLE, STATUSES,
                         compare_turn, state_fingerprint, export_comparison, evidence_fingerprint)


class DecisionPanel(ttk.Frame):
    def __init__(self, parent, profile_getter, state_getter, actions_getter):
        super().__init__(parent)
        self.profile_getter, self.state_getter, self.actions_getter = profile_getter, state_getter, actions_getter
        self.context = None
        self.availability = {name: UNKNOWN for name in TRAININGS}
        self.last_result = None
        self.last_evidence_hash = None
        self._make_ui()

    def _make_ui(self):
        ttk.Label(self, text='R6 · 전체 행동 판단 (게임에서 확인한 선택지에만 적용)',
                  style='Section.TLabel').pack(anchor='w', padx=16, pady=(14, 7))
        ttk.Label(self, text='② 턴 분석 탭에서 5개 훈련·휴식·외출·레이스의 수치를 확인하고, 각 행동을 이번 턴에 가능한지 명시하세요. '
                  '섬 티켓이 0개라면 섬 훈련은 제외합니다.',
                  style='Muted.TLabel', wraplength=1080, justify='left').pack(anchor='w', padx=16, pady=(0, 8))
        content = ttk.Frame(self)
        content.pack(fill='both', expand=True, padx=16)
        left = ttk.Frame(content)
        left.pack(side='left', fill='both', padx=(0, 14))
        right = ttk.Frame(content)
        right.pack(side='left', fill='both', expand=True)
        self.tree = ttk.Treeview(left, columns=('name', 'status'), show='headings', height=10)
        self.tree.heading('name', text='행동')
        self.tree.heading('status', text='이번 턴 가능 여부')
        self.tree.column('name', width=138, anchor='center')
        self.tree.column('status', width=135, anchor='center')
        for name in TRAININGS:
            self.tree.insert('', 'end', iid=name, values=(name, UNKNOWN))
        self.tree.pack(fill='x')
        self.tree.selection_set(TRAININGS[0])
        self.tree.bind('<<TreeviewSelect>>', self._selected)
        statusrow = ttk.Frame(left)
        statusrow.pack(fill='x', pady=(8, 3))
        self.selected_status = tk.StringVar(value=UNKNOWN)
        ttk.Combobox(statusrow, textvariable=self.selected_status,
                     values=STATUSES, width=11, state='readonly').pack(side='left')
        ttk.Button(statusrow, text='상태 적용', command=self.apply_status).pack(side='left', padx=6)
        ttk.Button(left, text='확인된 수치가 있는 행동 → 가능 지정',
                   command=self.from_confirmed).pack(fill='x', pady=(4, 4))
        ttk.Button(left, text='이번 턴 상태 초기화', command=self.reset_turn).pack(fill='x', pady=(2, 4))
        ttk.Label(left, text='가능 = 게임에서 현재 선택 가능하고 수치를 확인함\n불가 = 현재 선택할 수 없음\n미확인 = 추천 보류',
                  style='Muted.TLabel', justify='left').pack(anchor='w', pady=(5, 0))

        row = ttk.Frame(right)
        row.pack(fill='x')
        ttk.Button(row, text='R6 전체 행동 비교', style='Accent.TButton',
                   command=self.calculate).pack(side='left', padx=(0, 7))
        ttk.Button(row, text='검수된 분석 JSON 저장', command=self.export).pack(side='left')
        self.status_text = tk.StringVar(value='미확인 선택지가 있으면 전체 행동 추천을 보류합니다.')
        ttk.Label(right, textvariable=self.status_text, wraplength=660,
                  style='Muted.TLabel').pack(anchor='w', pady=(8, 8))
        self.ranked = ttk.Treeview(right, columns=('rank', 'name', 'score'), show='headings', height=7)
        for c, title, width in (('rank', '#', 46), ('name', '행동', 143), ('score', '실험 상대점수', 144)):
            self.ranked.heading(c, text=title)
            self.ranked.column(c, width=width, anchor='center')
        self.ranked.pack(fill='both', expand=True)
        self.ranked.bind('<<TreeviewSelect>>', self._show_reason)
        self.detail = tk.Text(right, height=10, wrap='word', padx=9, pady=8,
                              bg='#192438', fg='#F3F6FB', insertbackground='white',
                              relief='flat', font=('맑은 고딕', 10))
        self.detail.pack(fill='both', expand=True, pady=(8, 5))
        self._set_text('해당 시점의 훈련 결과, 휴식, 외출, 레이스 등 모든 가능한 선택지를 확인하세요.\n'
                       '데이터 부족 시 최적 행동이나 도축 여부를 예측하지 않습니다.')
        ttk.Label(self, text='모든 가중치·점수는 미검증 실험값 | 챔미·리오히 전용 | 자동 조작/도축 기능 없음',
                  style='Muted.TLabel').pack(anchor='w', padx=16, pady=(3, 12))

    def _set_text(self, text):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', text)
        self.detail.configure(state='disabled')

    def _selected(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self.selected_status.set(self.availability[selected[0]])

    def _invalidate_result(self):
        self.last_result = None
        self.last_evidence_hash = None
        self.ranked.delete(*self.ranked.get_children())
        self._set_text('선택지 상태를 변경했습니다. 분석을 다시 실행하세요.')

    def reset_turn(self):
        self.context = None
        self.availability = {name: UNKNOWN for name in TRAININGS}
        self._invalidate_result()
        self._refresh_list()
        self.status_text.set('현재 턴의 선택지를 처음부터 확인해야 합니다.')

    def _refresh_list(self):
        for name in TRAININGS:
            self.tree.item(name, values=(name, self.availability[name]))
        self._selected()

    def _ensure_context(self, profile, state) -> bool:
        key = state_fingerprint(profile, state)
        if key != self.context:
            was_set = self.context is not None
            self.context = key
            self.availability = {name: UNKNOWN for name in TRAININGS}
            self._invalidate_result()
            self._refresh_list()
            if was_set:
                self.status_text.set('목표 또는 현재 턴 수치가 달라져 검수 상태를 초기화했습니다. 다시 확인하세요.')
                return False
        return True

    def apply_status(self):
        try:
            profile, state = self.profile_getter(), self.state_getter()
        except ValueError as err:
            messagebox.showerror('현재 턴 상태 오류', str(err)); return
        if not self._ensure_context(profile, state):
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning('행동 선택', '왼쪽에서 행동을 고르세요.'); return
        name = selected[0]
        value = self.selected_status.get()
        if name == '섬 트레이닝' and state.island_tickets <= 0 and value == AVAILABLE:
            messagebox.showwarning('티켓 부족', '섬 티켓이 0개면 섬 훈련을 가능한 행동으로 표시할 수 없습니다.'); return
        self.availability[name] = value
        self._invalidate_result()
        self._refresh_list()
        self.status_text.set(f'{name}: {value}로 기록했습니다. 아직 추천은 계산하지 않았습니다.')

    def from_confirmed(self):
        try:
            profile, state = self.profile_getter(), self.state_getter()
            actions = self.actions_getter()
        except ValueError as err:
            messagebox.showerror('입력 오류', str(err)); return
        if not self._ensure_context(profile, state):
            return
        count = 0
        for name, act in actions.items():
            if name in self.availability and getattr(act, 'observed', False):
                if name == '섬 트레이닝' and state.island_tickets <= 0:
                    continue
                self.availability[name] = AVAILABLE
                count += 1
        self._invalidate_result()
        self._refresh_list()
        self.status_text.set(f'직접 확인 체크한 {count}개를 가능으로 표시했습니다. 나머지 행동의 가능/불가도 확인해야 합니다.')

    def calculate(self):
        try:
            profile, state = self.profile_getter(), self.state_getter()
            actions = self.actions_getter()
        except ValueError as err:
            messagebox.showerror('입력 오류', str(err)); return None
        if not self._ensure_context(profile, state):
            return None
        result = compare_turn(profile, state, actions, self.availability,
                              confirmed_context_hash=self.context)
        self.last_result = result
        self.last_evidence_hash = evidence_fingerprint(actions, self.availability)
        self.ranked.delete(*self.ranked.get_children())
        if result.status == '추천 보류':
            self.status_text.set(f'추천 보류 · 확인이 필요한 항목 {len(result.missing)}개')
            self._set_text('\n'.join(f'• {n}: {why}' for n, why in result.missing.items()))
        else:
            self.status_text.set(f'{result.status} · 검수된 선택 {len(result.ranked)}개'
                                 ' · 점수는 실험용이며 게임의 최적 행동을 보장하지 않음')
            for ix, item in enumerate(result.ranked, 1):
                self.ranked.insert('', 'end', iid=item.name,
                                   values=(ix, item.name, f'{item.score:.1f}'))
            first = result.ranked[0].name
            self.ranked.selection_set(first)
            self._show_reason()
        return result

    def _show_reason(self, _event=None):
        if self.last_result is None:
            return
        choice = self.ranked.selection()
        if not choice:
            return
        item = next((x for x in self.last_result.ranked if x.name == choice[0]), None)
        if item is None:
            return
        self._set_text(f'{item.name} · 실험 상대점수 {item.score:.1f}\n\n'
                       + '\n'.join('• ' + line for line in item.reasons)
                       + '\n\n' + '\n'.join('주의: ' + x for x in self.last_result.cautions)
                       + '\n\n점수 내역: ' + ', '.join(f'{name}: {score:+.1f}'
                                      for name, score in item.breakdown.items()))

    def current_review(self, profile, state, actions):
        """Return review metadata only when all evidence still matches this turn."""
        out = self.last_result
        if out is None or out.status == '추천 보류':
            return None
        if (out.context_hash != state_fingerprint(profile, state) or
                out.evidence_hash != evidence_fingerprint(actions, self.availability)):
            return None
        return {
            'schema': 'uma_r6_turn_review_v1', 'status': out.status,
            'context_hash': out.context_hash, 'evidence_hash': out.evidence_hash,
            'availability': dict(self.availability),
            'ranked': [{'name': r.name, 'score': r.score, 'reasons': list(r.reasons),
                        'breakdown': dict(r.breakdown)} for r in out.ranked],
            'cautions': list(out.cautions), 'experimental_only': True,
            'ml_training_label_verified': False,
        }

    def export(self):
        try:
            profile, state, actions = self.profile_getter(), self.state_getter(), self.actions_getter()
        except ValueError as err:
            messagebox.showerror('입력 오류', str(err)); return
        if not self.last_result or self.last_result.status == '추천 보류':
            messagebox.showwarning('추천 보류', '전체 행동 비교가 완료된 경우에만 저장할 수 있습니다.'); return
        if self.last_result.context_hash != state_fingerprint(profile, state) or evidence_fingerprint(actions, self.availability) != self.last_evidence_hash:
            self._invalidate_result()
            messagebox.showwarning('수치 변경', '분석 후 입력값이 변경됐습니다. 다시 비교해 주세요.'); return
        filename = f'uma_r6_{datetime.now():%Y%m%d_%H%M%S}.json'
        filepath = filedialog.asksaveasfilename(defaultextension='.json', initialfile=filename,
                                                filetypes=[('JSON', '*.json')])
        if not filepath:
            return
        try:
            export_comparison(Path(filepath), profile, state, actions, self.availability, self.last_result)
            self.status_text.set(f'R6 실험용 분석 저장: {filepath}')
        except (OSError, ValueError) as err:
            messagebox.showerror('저장 오류', str(err))
