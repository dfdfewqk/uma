"""Optional R34 Tk review of confirmed island context; does not change R6."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from island_context_r34 import (STATS, TICKET_PHASES, BOND_PHASES,
                                PlanningInputs, assess_island_context)

class IslandContextPanel(ttk.Frame):
    def __init__(self, parent, profile_getter, state_getter):
        super().__init__(parent)
        self.profile_getter, self.state_getter = profile_getter, state_getter
        self.phase=tk.StringVar(value='미확인')
        self.bonds=tk.StringVar(value='미확인')
        self.confirmed=tk.BooleanVar(value=False)
        self.values={k:tk.StringVar(value='') for k in
                     ('friendship','races','next_race','outings',*STATS)}
        self.summary=tk.StringVar(value='① 목표 및 ② 턴에 입력된 값은 자동으로 읽습니다. 나머지는 확인한 값만 입력하세요.')
        self._build()

    @staticmethod
    def _optional_number(raw: str, label: str) -> int | None:
        raw=raw.strip()
        if not raw:return None
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError(f'{label}: 음수가 아닌 정수 또는 빈칸을 입력하세요.')
        return int(raw)

    def _build(self):
        root=ttk.Frame(self,padding=12)
        root.pack(fill='both',expand=True)
        ttk.Label(root,text='R34 · 무인도 장기 조건 검토 (연구용)',
                  style='Section.TLabel').pack(anchor='w',pady=(0,5))
        ttk.Label(root,text='인연도·티켓·필수 레이스·남은 외출·시설을 함께 검토합니다. '
                  '빈칸은 미확인으로 유지하고, R6 실험 점수와 학습 모델은 변경하지 않습니다.',
                  wraplength=1100,style='Muted.TLabel').pack(anchor='w',pady=5)
        first=ttk.LabelFrame(root,text='섬 훈련 조건 (자동 인식 아님)',padding=8)
        first.pack(fill='x',pady=4)
        for i,(label,var,opts) in enumerate((
              ('섬 티켓 사용 단계',self.phase,TICKET_PHASES),
              ('서포트 인연 상태',self.bonds,BOND_PHASES))):
            ttk.Label(first,text=label).grid(row=0,column=i,padx=6,sticky='w')
            ttk.Combobox(first,values=opts,textvariable=var,width=19,
                         state='readonly').grid(row=1,column=i,padx=6,pady=5,sticky='w')
        ttk.Label(first,text='우정 발생 시설 수 (0~5)').grid(row=0,column=2,padx=6,sticky='w')
        ttk.Entry(first,textvariable=self.values['friendship'],width=19).grid(row=1,column=2,padx=6,pady=5)
        second=ttk.LabelFrame(root,text='남은 목표 레이스 / 외출 (모르면 빈칸)',padding=8)
        second.pack(fill='x',pady=4)
        for i,(label,key) in enumerate((
              ('남은 필수 목표 레이스 수','races'),
              ('다음 필수 레이스까지 턴 (0=현재)','next_race'),
              ('남은 계획 외출 횟수','outings'))):
            ttk.Label(second,text=label).grid(row=0,column=i,sticky='w',padx=6)
            ttk.Entry(second,textvariable=self.values[key],width=20).grid(row=1,column=i,padx=6,pady=5)
        third=ttk.LabelFrame(root,text='캐릭터 성장률 / 현재 시설 (선택)',padding=8)
        third.pack(fill='x',pady=4)
        ttk.Label(third,text='성장률은 다섯 항목 모두 직접 확인했을 때만 입력하세요.',
                  style='Muted.TLabel').pack(anchor='w')
        growthrow=ttk.Frame(third)
        growthrow.pack(anchor='w')
        for i,stat in enumerate(STATS):
            cell=ttk.Frame(growthrow)
            cell.grid(row=0,column=i,padx=6,pady=4)
            ttk.Label(cell,text=stat+' 성장률(%)').pack(anchor='w')
            ttk.Entry(cell,textvariable=self.values[stat],width=13).pack(anchor='w')
        ttk.Checkbutton(third,text='② 턴에 입력한 시설 여섯 곳의 레벨을 실제로 확인함',
                        variable=self.confirmed).pack(anchor='w',pady=4)
        controls=ttk.Frame(root);controls.pack(fill='x',pady=6)
        ttk.Button(controls,text='R34 조건별 검토',command=self.calculate,
                   style='Accent.TButton').pack(side='left',padx=(0,8))
        ttk.Button(controls,text='수동 입력 초기화',command=self.reset).pack(side='left')
        ttk.Label(root,textvariable=self.summary,style='Muted.TLabel',
                  wraplength=1050).pack(anchor='w',pady=5)
        frame=ttk.Frame(root)
        frame.pack(fill='both',expand=True)
        self.detail=tk.Text(frame,height=12,wrap='word',bg='#192438',fg='#F3F6FB',
                            insertbackground='white',relief='flat',padx=10,pady=8,
                            font=('맑은 고딕',9))
        self.detail.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(frame,command=self.detail.yview)
        scrollbar.pack(side='right',fill='y')
        self.detail.configure(yscrollcommand=scrollbar.set)
        self._display('게임 없는 상태에서는 검증 질문을 준비할 수 있습니다. '
                      '확인되지 않은 입력으로 추천 점수를 만들지 않습니다.')

    def _inputs(self):
        raw={s:self.values[s].get().strip() for s in STATS}
        if any(raw.values()) and not all(raw.values()):
            raise ValueError('성장률은 모두 입력하거나 모두 미확인으로 두세요.')
        growth=({s:self._optional_number(raw[s],s) for s in STATS}
                if any(raw.values()) else None)
        return PlanningInputs(
            ticket_phase=self.phase.get(),bond_phase=self.bonds.get(),
            friendship_locations=self._optional_number(self.values['friendship'].get(),'우정 시설 수'),
            mandatory_races_remaining=self._optional_number(self.values['races'].get(),'필수 레이스'),
            turns_to_next_mandatory_race=self._optional_number(self.values['next_race'].get(),'다음 레이스'),
            planned_outings_remaining=self._optional_number(self.values['outings'].get(),'외출 계획'),
            growth_rates=growth,facility_levels_confirmed=self.confirmed.get())

    def _display(self, content):
        self.detail.config(state='normal')
        self.detail.delete('1.0','end')
        self.detail.insert('1.0',content)
        self.detail.config(state='disabled')

    def calculate(self):
        try:
            audit=assess_island_context(self.profile_getter(),self.state_getter(),self._inputs())
        except (ValueError,TypeError,KeyError) as error:
            self.summary.set('조건 검토 보류: 입력값을 확인하세요.')
            messagebox.showwarning('R34 확인 필요',str(error))
            return None
        self.summary.set(f'{audit.status} · 미확인 {len(audit.missing)}개 · R6 점수 유지')
        lines=['[조건별 검토 · 최적 행동 미확정]']
        lines.extend('• '+x for x in audit.checks)
        lines.extend(['','[미확인 항목]'])
        lines.extend('• '+x for x in audit.missing or ['없음'])
        lines.extend(['','[주의]'])
        lines.extend('• '+x for x in audit.cautions)
        self._display('\n'.join(lines))
        return audit

    def reset(self):
        self.phase.set('미확인');self.bonds.set('미확인')
        self.confirmed.set(False)
        for var in self.values.values():var.set('')
        self.summary.set('수동 입력을 초기화했습니다.')
        self._display('현재 게임 조건을 확인한 뒤 다시 검토하세요.')
