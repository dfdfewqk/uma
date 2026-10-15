"""R8 Island R7/R6 evidence bridge, with deliberately conservative abstention."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from uma_core import STATS
from island_impact_r8 import inspect_island_impact, export_impact, context_hash


class IslandImpactPanel(ttk.Frame):
    def __init__(self, parent, profile_getter, state_getter, r7_getter, r6_getter):
        super().__init__(parent)
        self.get_profile = profile_getter
        self.get_state = state_getter
        self.get_r7 = r7_getter
        self.get_r6 = r6_getter
        self._result = None
        self._build()

    def _build(self):
        canvas = tk.Canvas(self, bg='#111827', highlightthickness=0)
        bar = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        body = ttk.Frame(canvas)
        handle = canvas.create_window((0,0), window=body, anchor='nw')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(handle, width=e.width))

        ttk.Label(body, text='R8 · 무인도 시설 계획 × 훈련 효과 검수', style='Section.TLabel').pack(anchor='w', padx=20, pady=(18, 5))
        ttk.Label(body, text='실제 훈련 배치를 기준으로 시설 건설 전후 적용 여부만 비교합니다. 게임 내 성장 배율·미래 우정 배치는 미확인입니다.',
                  style='Muted.TLabel', wraplength=980).pack(anchor='w', padx=20, pady=(0, 13))
        ttk.Label(body, text='이번 턴 실제 우정 훈련 인원 · 각 시설별 확인 (모르면 미확인 유지)', style='Section.TLabel').pack(anchor='w', padx=20, pady=(7, 5))
        row = ttk.Frame(body)
        row.pack(fill='x', padx=20)
        self.friends = {}
        for name in STATS:
            g = ttk.Frame(row)
            g.pack(side='left', padx=(0, 20))
            ttk.Label(g, text=name, style='Muted.TLabel').pack(anchor='w')
            self.friends[name] = tk.StringVar(value='미확인')
            ttk.Combobox(g, textvariable=self.friends[name], state='readonly', width=11,
                         values=['미확인'] + [str(i) for i in range(7)]).pack(anchor='w')
        ttk.Label(body, text='R7 탭에서 시설 경로를 계산하면 각 경로의 효과 활성 조건을 함께 비교합니다. '
                             'R6의 모든 선택지를 검수했다면 사용자가 확인한 섬 훈련 입력값도 연결합니다.',
                  style='Muted.TLabel', wraplength=970).pack(anchor='w', padx=20, pady=(12, 11))
        tools = ttk.Frame(body)
        tools.pack(fill='x', padx=20, pady=(0, 8))
        ttk.Button(tools, text='R8 시설 효과 연계 분석', style='Accent.TButton', command=self.calculate).pack(side='left')
        ttk.Button(tools, text='현재 분석 JSON 저장', command=self.save).pack(side='left', padx=12)
        ttk.Button(tools, text='R8 결과 초기화', command=self.clear_review).pack(side='left')
        self.status = tk.StringVar(value='우정 훈련 위치 5종을 확인한 뒤 비교해 주세요.')
        ttk.Label(body, textvariable=self.status, style='Muted.TLabel', wraplength=1020).pack(anchor='w', padx=20, pady=(3, 9))
        self.tree = ttk.Treeview(body, columns=('path','phase','built','ignored','beach','added'), show='headings', height=13)
        for key, title, width in (
            ('path','경로',83),('phase','시설 단계',145),('built','섬 훈련 우정 적용 시설',320),
            ('ignored','미건설로 제외된 시설',260), ('beach','해변의 집 다중 조건',180),('added','현재 대비 신규 적용',230)):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width, anchor='w')
        self.tree.pack(fill='x', padx=20)
        ttk.Label(body, text='해석 및 확인할 점', style='Section.TLabel').pack(anchor='w', padx=20, pady=(14, 5))
        self.detail = tk.Text(body, bg='#192438', fg='#F3F6FB', height=13, wrap='word',
                              font=('맑은 고딕',10), padx=12, pady=10, relief='flat')
        self.detail.pack(fill='x', padx=20, pady=(0, 18))
        self._set_detail('R7 시설 건설 계획과 R6 실측 행동 기록을 연결하는 연구 단계입니다.\n'
                         '건설로 실제 몇 점이 증가하는지는 한국 서버 공식 수치·실측 데이터가 없으므로 예측하지 않습니다.')

    def _set_detail(self, msg):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', msg)
        self.detail.configure(state='disabled')

    def clear_review(self):
        self._result = None
        self.tree.delete(*self.tree.get_children())
        self.status.set('새 턴/육성에서는 이전 R8 분석을 재사용하지 않습니다.')
        self._set_detail('이번 턴 우정 배치 및 시설 정보를 다시 검수하세요.')
        for var in self.friends.values():
            var.set('미확인')

    def _read_friends(self):
        out = {}
        for stat in STATS:
            value = self.friends[stat].get()
            if value == '미확인':
                raise ValueError(f'{stat} 우정 훈련 인원을 이번 턴 화면에서 확인하세요. 우정 훈련이 없으면 0을 선택하세요.')
            out[stat] = int(value)
        return out

    def _context(self):
        profile, state = self.get_profile(), self.get_state()
        plan = self.get_r7(profile, state)
        r7result, r7options = plan if plan is not None else (None, None)
        review = self.get_r6(profile, state)
        r6result, actions, availability = review if review is not None else (None, None, None)
        return profile, state, r7result, r7options, r6result, actions, availability

    def calculate(self):
        self._result = None
        self.tree.delete(*self.tree.get_children())
        try:
            friends = self._read_friends()
            profile, state, r7, options, r6, actions, availability = self._context()
            result = inspect_island_impact(profile, state, friendship_counts=friends,
                                           r7_result=r7, r7_options=options,
                                           r6_review=r6, actions=actions, availability=availability)
        except (ValueError, TypeError) as e:
            self.status.set('분석 보류 · 확인되지 않은 입력')
            self._set_detail(str(e))
            return
        if result.errors:
            self.status.set('분석 보류 · 입력/경로 상태 불일치')
            self._set_detail('\n'.join('• '+x for x in result.errors))
            return
        self._result = result
        for c in [result.current] + result.projections:
            self.tree.insert('', 'end', values=(c.candidate, c.phase,
                  ', '.join(c.built_friendship_facilities) or '없음',
                  ', '.join(c.missing_facilities) or '없음',
                  '조건 있음' if c.beach_multi_friendship_condition else '조건 없음',
                  ', '.join(c.new_enabled_facilities) or '-'))
        lines = [f'현재 건설된 시설의 우정 훈련 적용: {result.current.distinct_facilities}종 / {result.current.participating_friendships}명',
                 f'해변의 집 복수 시설 효과 조건: {"현재 배치 기준 충족" if result.current.beach_multi_friendship_condition else "현재 배치 기준 불충족"}',
                 '※ 효과가 실제로 몇 %/몇 점인지 계산한 것이 아닙니다.', '']
        if result.measured_island_action:
            a = result.measured_island_action
            lines += [f'R6 검수 섬 훈련 상대 순위: {result.r6_rank}/{result.r6_total_compared} · 실험 점수 {result.r6_experimental_score}',
                      '이번 턴에 입력해 확인한 상승량: ' + ', '.join(f'{s} +{a["stats"][s]}' for s in STATS),
                      f'스킬 Pt +{a["skill_points"]}, 체력 {a["energy_delta"]:+d}', '']
        else:
            lines += ['R6 검수된 섬 훈련 입력값: 없음 (성장량 추정 금지)', '']
        lines += ['[건설 후보 비교]']
        if r7:
            for idx, candidate in enumerate(r7.candidates, 1):
                last = [x for x in result.projections if x.candidate == f'경로 {idx}'][-1]
                lines.append(f'경로 {idx}: 같은 배치 가정 · 최종 우정 적용 시설 {last.distinct_facilities}종 · 미건설 제외 {len(last.missing_facilities)}종')
        else:
            lines.append('R7의 현재 턴 시설 계획이 없으므로 미래 경로 비교를 생략합니다.')
        lines += ['', '[주의 · 근거]', *('• '+x for x in result.cautions),
                  '• 향후 서포트 배치, 경기 승률, 시설별 실제 스탯 증가량은 미예측. 자동 조작 없음.']
        self._set_detail('\n'.join(lines))
        self.status.set(f'{result.status} · 비교된 단계 {len(result.projections)}개 · 미래 성장량 예측 아님')

    def save(self):
        if self._result is None:
            messagebox.showwarning('R8 검수 필요', '먼저 현재 턴의 R8 분석을 실행하세요.')
            return
        try:
            friends = self._read_friends()
            profile, state, r7, options, r6, _actions, _availability = self._context()
            if self._result.context_hash != context_hash(profile, state, friends, r7, options, r6):
                raise ValueError('분석 후 턴 상태·선택지·시설 계획이 바뀌었습니다. 다시 분석하세요.')
            path = filedialog.asksaveasfilename(title='R8 실험용 건설/훈련 연계 분석 저장',
                    defaultextension='.json', filetypes=[('JSON', '*.json')])
            if path:
                export_impact(Path(path), profile, state, self._result, friendship_counts=friends,
                              r7_result=r7, r7_options=options, r6_review=r6,
                              actions=_actions, availability=_availability)
                self.status.set(f'R8 분석 저장 완료: {path}')
        except (ValueError, OSError) as e:
            messagebox.showerror('분석 저장 불가', str(e))
