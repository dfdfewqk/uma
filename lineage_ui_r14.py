"""R14 integrated ancestry/pedigree and KR preparation forecast UI."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk,filedialog
from lineage_r14 import recommend_lineage,event_calendar,export_r14_json,load_r14
from plan_r13 import load_pack,STYLES


class LineageCalendarPanel(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.r13=load_pack();self.r14=load_r14(r13=self.r13)
        self.last=None
        events={x['id']:x['label'] for x in self.r13['events']}
        self.events=events
        self.event_label=tk.StringVar(value=next(iter(events.values())))
        self.style=tk.StringVar(value='선입')
        self.trainee=tk.StringVar()
        self.owned=tk.StringVar()
        self.summary=tk.StringVar()
        self._build()
        self.analyze()

    def _build(self):
        wrapper=ttk.Frame(self,padding=10);wrapper.pack(fill='both',expand=True)
        ttk.Label(wrapper,text='R14 · 부모 2명 + 조부모 4명 추천 · 대회 준비 일정',style='Section.TLabel').pack(anchor='w',pady=(0,5))
        ttk.Label(wrapper,text='출처 확인된 후보를 자동 배치하며, 상성/실제 보유 인자/승률은 아직 계산하지 않습니다.',style='Muted.TLabel').pack(anchor='w')
        config=ttk.Frame(wrapper);config.pack(fill='x',pady=6)
        ttk.Label(config,text='대회').pack(side='left')
        ttk.Combobox(config,textvariable=self.event_label,values=list(self.events.values()),state='readonly',width=36).pack(side='left',padx=5)
        ttk.Label(config,text='각질').pack(side='left',padx=(10,0))
        ttk.Combobox(config,textvariable=self.style,values=STYLES,state='readonly',width=6).pack(side='left',padx=5)
        ttk.Label(config,text='육성 캐릭터').pack(side='left',padx=(10,0))
        ttk.Entry(config,textvariable=self.trainee,width=19).pack(side='left',padx=5)
        config2=ttk.Frame(wrapper);config2.pack(fill='x',pady=(0,7))
        ttk.Label(config2,text='보유 육성마 (선택, 쉼표로 구분)').pack(side='left')
        ttk.Entry(config2,textvariable=self.owned,width=48).pack(side='left',padx=5)
        ttk.Button(config2,text='부모·조부모 자동 추천',command=self.analyze).pack(side='left',padx=6)
        ttk.Button(config2,text='분석 결과 JSON 저장',command=self.save).pack(side='left')
        ttk.Label(wrapper,textvariable=self.summary,style='Muted.TLabel',wraplength=1250).pack(anchor='w',pady=3)
        split=ttk.Panedwindow(wrapper,orient='vertical');split.pack(fill='both',expand=True,pady=(7,0))
        top=ttk.Frame(split);split.add(top,weight=3)
        cols=('branch','role','name','skill','basis')
        self.table=ttk.Treeview(top,columns=cols,show='headings',height=7)
        for col,label,w in [('branch','계통',60),('role','세대',85),('name','캐릭터 후보',195),('skill','계승 스킬/인자 점검',350),('basis','추천 근거 상태',330)]:
            self.table.heading(col,text=label);self.table.column(col,width=w,stretch=True)
        self.table.pack(side='left',fill='both',expand=True)
        sc=ttk.Scrollbar(top,command=self.table.yview);sc.pack(side='right',fill='y');self.table.configure(yscrollcommand=sc.set)
        lower=ttk.Frame(split);split.add(lower,weight=3)
        self.detail=tk.Text(lower,bg='#192438',fg='#F3F6FB',insertbackground='white',relief='flat',height=14,
                            wrap='word',font=('맑은 고딕',9),padx=12,pady=9)
        self.detail.pack(side='left',fill='both',expand=True)
        sd=ttk.Scrollbar(lower,command=self.detail.yview);sd.pack(side='right',fill='y');self.detail.configure(yscrollcommand=sd.set)

    def analyze(self):
        try:
            event_id=next(k for k,v in self.events.items() if v==self.event_label.get())
            owned=[x.strip() for x in self.owned.get().split(',') if x.strip()] if self.owned.get().strip() else None
            lineage=recommend_lineage(event_id,self.style.get(),self.trainee.get(),owned,self.r13,self.r14)
            sched=event_calendar(event_id,r13=self.r13,r14=self.r14)
            self.last=(lineage,sched)
            self.table.delete(*self.table.get_children())
            for index,b in enumerate(lineage['branches'],1):
                for role,c in [('부모',b['parent'])]+[(f'조부모 {i}',grand) for i,grand in enumerate(b['grandparents'],1)]:
                    if c:self.table.insert('','end',values=(f'{index}번',role,c['name'],c['skill'],f"{c['priority']} · {c['compatibility']}"))
                    else:self.table.insert('','end',values=(f'{index}번',role,'후보 부족','수동 선택 필요','데이터 미확인'))
            line=[f"[일본 개최 이력] {sched['jp_period']}",f"[한국 서버] {sched['kr_status']}"]
            if sched['kr_period']:
                line.append(f"[한국 대회 기간] {sched['kr_period']} (시작까지 {sched['days_left']}일)")
            else:
                line.extend([f"[한국 예상 개최 월] {sched['kr_month_estimate']} (일자 미확인)",
                             f"[준비 권장 월] {sched['approx_prep_month']}부터 단계별 준비 검토 (구체적인 날짜 아님)"])
            line.append('[준비 마일스톤: 개발상 권장값, 실제 확정 일정 아님]')
            for m in sched['milestones']:
                line.append(f"  · {m['phase']} : {m['start'] or '정확한 일자 미정'} / {m['status']}")
            line.append('[우선 검토할 인자]')
            for kind,desc in lineage['factor_targets'].items():line.append(f'  · {kind}: {desc}')
            line.append('[주의 및 증거 수준]');line.extend('  · '+x for x in lineage['warnings'])
            line.append('[일정 및 인자작 공략 출처]')
            urls=dict(lineage['sources']);urls.update(sched['sources'])
            line.extend(f'  · {k}: {v}' for k,v in urls.items())
            self.detail.config(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0','\n'.join(line));self.detail.config(state='disabled')
            self.summary.set(f"{sched['course']} · {self.style.get()} · 부모 2자리·조부모 4자리 추천 초안 / 날짜 확인 수준: {sched['kr_status']}")
        except (ValueError,KeyError,TypeError) as exc:
            self.last=None;self.summary.set(f'분석 보류: {exc}')

    def save(self):
        if not self.last:return
        file=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],initialfile='R14_부모조부모_대회일정.json')
        if not file:return
        try:
            export_r14_json(file,*self.last)
            self.summary.set('일정·계승 계획이 새 JSON 파일에 저장됐습니다.')
        except (OSError,ValueError) as ex:self.summary.set('저장 실패: '+str(ex))
