"""R13 pre-run JP 2025 race/style support + factor preparation screen."""
from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from plan_r13 import load_pack,recommend,export_plan,STYLES

class EventPlanPanel(ttk.Frame):
    def __init__(self,parent,on_open_course=None):
        super().__init__(parent)
        self.data=load_pack();self.on_open_course=on_open_course
        self.last=None
        self.event=tk.StringVar(value=self.data['events'][0]['id'])
        self.style=tk.StringVar(value='선행')
        self.mode=tk.StringVar(value='본육성')
        self.owned_enabled=tk.BooleanVar(value=False)
        self._make()
        self.analyze()

    def _make(self):
        main=ttk.Frame(self,padding=8);main.pack(fill='both',expand=True)
        ttk.Label(main,text='R13 · 챔미/리오히별 육성 준비 · 서포트·인자작·계승',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Label(main,text='2025년 일본 무인도 수정 후 대회 4개: 한국 서버 개최 예정표가 아닙니다. 공략 후보와 실측 승률을 구분합니다.',style='Muted.TLabel').pack(anchor='w',pady=(0,5))
        options=ttk.Frame(main);options.pack(fill='x',pady=4)
        ttk.Label(options,text='대회').pack(side='left')
        labels={e['id']:e['label'] for e in self.data['events']}
        self.event_id_by_label={v:k for k,v in labels.items()}
        self.event_label=tk.StringVar(value=labels[self.event.get()])
        ttk.Combobox(options,textvariable=self.event_label,values=list(labels.values()),state='readonly',width=43).pack(side='left',padx=7)
        ttk.Label(options,text='각질').pack(side='left',padx=(12,3))
        ttk.Combobox(options,textvariable=self.style,values=STYLES,state='readonly',width=7).pack(side='left')
        ttk.Label(options,text='종류').pack(side='left',padx=(12,3))
        ttk.Combobox(options,textvariable=self.mode,values=('본육성','인자작'),state='readonly',width=9).pack(side='left')
        ttk.Button(options,text='추천 분석',command=self.analyze).pack(side='left',padx=(12,2))
        ttk.Button(options,text='코스·스킬 탭으로 전달',command=self.open_course).pack(side='left',padx=2)
        ttk.Button(options,text='결과 JSON 저장',command=self.save).pack(side='left',padx=2)
        self.summary=tk.StringVar()
        ttk.Label(main,textvariable=self.summary,style='Muted.TLabel',wraplength=1300).pack(anchor='w',pady=4)
        owned_frame=ttk.LabelFrame(main,text='보유한 카드 (선택 사항) · 목록에서 여러 개 선택 가능',padding=8)
        owned_frame.pack(fill='x',pady=6)
        ttk.Checkbutton(owned_frame,text='선택한 카드만 보유한 것으로 간주',variable=self.owned_enabled,command=self.analyze).pack(anchor='w')
        ttk.Label(owned_frame,text='카드 이름이 같아도 지원 타입이 다르면 별도 카드입니다. 카드 돌파·한국 출시 여부는 아직 자동 판별하지 않습니다.',style='Muted.TLabel').pack(anchor='w')
        available=sorted({(c['id'],c['name_jp'],c['type']) for c in self.data['cards']},key=lambda x:(x[2],x[1]))
        self.card_ids=[x[0] for x in available]
        box=ttk.Frame(owned_frame);box.pack(fill='x',pady=3)
        self.ownedlist=tk.Listbox(box,selectmode='multiple',height=4,exportselection=False,
                   bg='#233047',fg='#F3F6FB',selectbackground='#365F8C',font=('맑은 고딕',9))
        for cid,name,typ in available:self.ownedlist.insert('end',f'{name} [{typ}]')
        self.ownedlist.pack(side='left',fill='x',expand=True)
        y=ttk.Scrollbar(box,orient='vertical',command=self.ownedlist.yview);y.pack(side='right',fill='y')
        self.ownedlist.configure(yscrollcommand=y.set)
        ttk.Label(main,text='추천 6장 기본 구성은 공략 적합성/타입별 후보 순서이며 승률 순위가 아닙니다. 본육성/인자작 카드는 별도 판단합니다.',style='Muted.TLabel').pack(anchor='w',pady=(5,2))
        split=ttk.Panedwindow(main,orient='vertical');split.pack(fill='both',expand=True)
        frame=ttk.Frame(split);split.add(frame,weight=3)
        cols=('priority','name','type','hints','reason')
        self.table=ttk.Treeview(frame,columns=cols,show='headings',height=7)
        for col,title,width in (('priority','종류',85),('name','카드 (일본 명칭/버전)',230),('type','타입',80),('hints','주요 스킬',260),('reason','선택 이유',435)):
            self.table.heading(col,text=title);self.table.column(col,width=width,stretch=True)
        self.table.pack(fill='both',expand=True,side='left')
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview);sy.pack(side='right',fill='y');self.table.configure(yscrollcommand=sy.set)
        infoframe=ttk.Frame(split);split.add(infoframe,weight=2)
        self.info=tk.Text(infoframe,height=10,wrap='word',bg='#192438',fg='#F3F6FB',insertbackground='#F3F6FB',padx=9,pady=7,relief='flat',font=('맑은 고딕',9))
        self.info.pack(fill='both',expand=True)

    def analyze(self):
        self.event.set(self.event_id_by_label[self.event_label.get()])
        owned={self.card_ids[i] for i in self.ownedlist.curselection()} if self.owned_enabled.get() else None
        try:
            r=recommend(self.event.get(),self.style.get(),self.mode.get(),owned,self.data)
            self.last=r
            self.table.delete(*self.table.get_children())
            for tag,group in [('후보',r.selections),('대체',r.alternatives)]:
                for c in group:
                    self.table.insert('','end',values=(tag,c['name_jp'],c['type'],', '.join(c['target_skills']) or '공용 훈련',c['note']))
            event=next(e for e in self.data['events'] if e['id']==r.event_id)
            self.summary.set(f"{event['venue']} {event['meters']}m · {event['kind']} · {r.style} · {r.mode} · 선택 후보 {len(r.selections)}장 / 대체 후보 {len(r.alternatives)}장")
            text=[f"[코스 특징] {event['course_note']}",
                  f"[우선 확인 스킬] {', '.join(r.target_skills) if r.target_skills else '추가 검수 필요'}"]
            if r.stats_reference:text.append('[참고 스탯 · 특정 공략 작성자의 목표, 최적치 아님] '+', '.join(f'{k} {v}+' for k,v in r.stats_reference.items()))
            else:text.append('[스탯] 각질별 검증된 목표 수치 부족: R11의 사용자 목표를 사용하고 계산 공식 추가 검증 필요')
            text.append('[부모/계승 고유기 후보]')
            text.extend(f"- {a['name']} : {a['unique_skill']} ({a['priority']})" for a in r.ancestors)
            if not r.ancestors:text.append('- 출처에서 검수된 부모 후보 미등록: 코스·각질에 맞춰 직접 확인 필요')
            if r.missing_types:text.append('[누락된 지원 타입] '+', '.join(r.missing_types))
            if r.unowned:text.append(f'[미보유 후보] {len(r.unowned)}종 (보유 설정 기준)')
            text.append('[한계 및 검수 안내]');text.extend('- '+x for x in r.caveats)
            text.append('[자료 출처]');text.extend(f'{k}: {v}' for k,v in r.provenance.items())
            self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('1.0','\n'.join(text));self.info.configure(state='disabled')
        except (ValueError,TypeError,KeyError) as ex:
            self.last=None;self.summary.set('추천 보류: '+str(ex))

    def open_course(self):
        if self.last and self.on_open_course:self.on_open_course(self.last.event_id,self.last.style)

    def save(self):
        if not self.last:return
        path=filedialog.asksaveasfilename(title='추천 결과 저장',defaultextension='.json',filetypes=[('JSON','*.json')],initialfile='R13_대회_육성준비.json')
        if not path:return
        try:export_plan(path,self.last)
        except (OSError,ValueError) as ex:
            self.summary.set('저장하지 못했습니다: '+str(ex))
