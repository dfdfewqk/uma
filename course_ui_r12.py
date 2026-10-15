"""R12 pre-run racecourse/skill planner; manual purchase screen helper (not game overlay)."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from course_advisor_r12 import (COURSES, Course, Candidate, STYLES, EVENTS, advise,
                                 default_candidates, parse_candidate_lines, save_report,
                                 distance_type)

class CourseSkillPanel(ttk.Frame):
    def __init__(self,parent,get_profile,apply_course):
        super().__init__(parent)
        self.get_profile=get_profile
        self.apply_course=apply_course
        self.last_result=None
        self._build()
        self.refresh_profile()

    def _entry(self,parent,label,var,width=13):
        box=ttk.Frame(parent)
        ttk.Label(box,text=label,style='Muted.TLabel').pack(anchor='w')
        ttk.Entry(box,textvariable=var,width=width).pack(fill='x',pady=(3,0))
        return box

    def _combo(self,parent,label,var,options,width=12):
        box=ttk.Frame(parent)
        ttk.Label(box,text=label,style='Muted.TLabel').pack(anchor='w')
        ttk.Combobox(box,textvariable=var,state='readonly',values=options,width=width).pack(fill='x',pady=(3,0))
        return box

    def _build(self):
        outer=ttk.Frame(self);outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,bg='#111827',highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        root=ttk.Frame(canvas,padding=(12,9,12,9))
        window=canvas.create_window((0,0),window=root,anchor='nw')
        root.bind('<Configure>',lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e: canvas.itemconfigure(window,width=e.width))
        self.scroll_canvas=canvas

        top=ttk.Frame(root);top.pack(fill='x')
        ttk.Label(top,text='R12 · 코스별 실전 스탯·추천 스킬',style='Section.TLabel').pack(side='left')
        ttk.Label(top,text='챔미 / 리오히 · 육성 시작 전 사용 가능 · 구매 화면 수동 검수',style='Muted.TLabel').pack(side='left',padx=14)
        ttk.Label(root,text='발동 조건 · 유효 타이밍 · 관측 발동률 · Pt 효율을 분리합니다. 실전 확률/승률은 검증된 표본 없이는 산출하지 않습니다.',
                  style='Muted.TLabel').pack(anchor='w',pady=(3,7))
        config=ttk.Frame(root);config.pack(fill='x')
        self.preset=tk.StringVar(value=next(iter(COURSES)))
        self.venue=tk.StringVar(value='도쿄')
        self.meters=tk.StringVar(value='2400')
        self.surface=tk.StringVar(value='잔디')
        self.direction=tk.StringVar(value='좌회전')
        self.end=tk.StringVar(value='코너')
        self.season=tk.StringVar(value='미정')
        self.weather=tk.StringVar(value='미정')
        self.ground=tk.StringVar(value='미정')
        self.style=tk.StringVar(value='선행')
        self.event=tk.StringVar(value=EVENTS[0])
        self.presetbox=ttk.Combobox(config,textvariable=self.preset,state='readonly',values=tuple(COURSES)+('직접 입력',),width=24)
        self.presetbox.grid(row=0,column=0,padx=(0,10),pady=6,sticky='w')
        self.presetbox.bind('<<ComboboxSelected>>',self.preset_changed)
        ttk.Button(config,text='R11 목표와 각질 가져오기',command=self.refresh_profile).grid(row=0,column=1,sticky='w',padx=5)
        ttk.Button(config,text='코스를 육성 목표에 적용',command=self.apply_to_profile).grid(row=0,column=2,sticky='w',padx=5)
        opts=[('경기장',self.venue,None),('거리(m)',self.meters,None),('마장',self.surface,['잔디','더트','미정']),
              ('방향',self.direction,['좌회전','우회전','직선','미정']),('종반 시작',self.end,['코너','직선','미검증']),
              ('각질',self.style,STYLES),('대회',self.event,EVENTS)]
        for col,(label,var,values) in enumerate(opts):
            w=self._combo(config,label,var,values,16 if label=='대회' else 11) if values else self._entry(config,label,var,10)
            w.grid(row=1,column=col,sticky='w',padx=(0,10),pady=(3,6))
        conditions=[('계절',self.season,('미정','봄','여름','가을','겨울')),
                    ('날씨',self.weather,('미정','맑음','흐림','비','눈')),
                    ('마장 상태',self.ground,('미정','양호','다습','포화','불량'))]
        for col,(label,var,opts) in enumerate(conditions):
            self._combo(config,label,var,opts,12).grid(row=2,column=col,padx=(0,11),pady=4,sticky='w')
        ttk.Label(config,text='날씨·계절·마장 상태는 대회 공지 확인 후 직접 선택. 프리셋은 코스 구조만 제공합니다.',style='Muted.TLabel').grid(row=2,column=3,columnspan=4,sticky='w',padx=9)
        self.statnote=tk.StringVar(value='코스·스킬을 선택하세요.')
        ttk.Label(root,textvariable=self.statnote,style='Muted.TLabel',wraplength=1220).pack(anchor='w',pady=(5,8))
        buttons=ttk.Frame(root);buttons.pack(fill='x',pady=3)
        ttk.Button(buttons,text='경기장 조건 추천 미리보기',command=self.preview).pack(side='left')
        ttk.Button(buttons,text='스킬 구매 목록 분석',command=self.analyze).pack(side='left',padx=7)
        ttk.Button(buttons,text='결과 JSON 저장',command=self.save).pack(side='left',padx=7)
        ttk.Button(buttons,text='목록 초기화',command=self.clear).pack(side='left',padx=7)
        ttk.Label(buttons,text='항목을 클릭하면 근거·실측 여부가 표시됩니다.',style='Muted.TLabel').pack(side='left',padx=15)
        ttk.Label(root,text='현재 게임 스킬창에서 보이는 후보 입력:  스킬명 | 실제 Pt | 구매가능/보유/미확인 | 검수 경기수 | 발동수 | 유효발동수',style='Section.TLabel').pack(anchor='w',pady=(4,3))
        self.skilltext=tk.Text(root,height=3,bg='#233047',fg='#F3F6FB',insertbackground='#F3F6FB',relief='flat',font=('맑은 고딕',10))
        self.skilltext.pack(fill='x')
        ttk.Label(root,text='입력 예: 왕수 | 160 | 구매가능  /  실제 관측이 있을 때만: 왕수 | 160 | 구매가능 | 20 | 15 | 13   (숫자·가격은 예시, 게임 수치 아님)',style='Muted.TLabel').pack(anchor='w',pady=4)
        resultframe=ttk.Frame(root);resultframe.pack(fill='both',expand=True,pady=(6,2))
        cols=('priority','name','status','activation','timing','pt')
        tree=ttk.Treeview(resultframe,columns=cols,show='headings',height=5,selectmode='browse')
        self.tree=tree
        for key,label,width in (('priority','추천 상태',120),('name','스킬',195),('status','조건 검토',90),
                                 ('activation','발동률 / 발동 가능성',260),('timing','유효 시점 / 실측',240),('pt','Pt 효율',290)):
            tree.heading(key,text=label);tree.column(key,width=width,anchor='w',stretch=(key not in ('priority','status')))
        sy=ttk.Scrollbar(resultframe,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=sy.set)
        sy.pack(side='right',fill='y');tree.pack(side='left',fill='both',expand=True)
        tree.tag_configure('good',background='#184238',foreground='#EAFFF5')
        tree.tag_configure('caution',background='#403421',foreground='#FFF0D5')
        tree.tag_configure('bad',background='#4A2530',foreground='#FFECED')
        tree.bind('<<TreeviewSelect>>',self.detail)
        self.info=tk.Text(root,height=4,bg='#192438',fg='#F3F6FB',wrap='word',relief='flat',padx=11,pady=8)
        self.info.pack(fill='x',pady=(4,0))
        self._info('① 프리셋 선택 → ② 날씨·각질 확인 → ③ 육성 전 추천 미리보기.\n스킬 구매 시에는 게임 화면의 스킬명과 힌트 적용된 실제 Pt를 입력하고 ‘스킬 구매 목록 분석’을 누르세요.')
        self.preset_changed()

    def _info(self,text):
        self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('1.0',text);self.info.configure(state='disabled')

    def preset_changed(self,_event=None):
        data=COURSES.get(self.preset.get())
        if data:
            for key in ('venue','meters','surface','direction','end'):
                getattr(self,key).set(str(data[key]))
        self.clear_results()

    def refresh_profile(self):
        try:
            p=self.get_profile()
            self.style.set(p.style);self.event.set(p.event)
        except Exception:
            pass

    def course(self):
        raw=self.meters.get().strip()
        if not raw.isascii() or not raw.isdecimal():raise ValueError('거리(m)는 양의 정수로 입력하세요.')
        preset=COURSES.get(self.preset.get(),{})
        matches=bool(preset and all(str(preset[k])==str(getattr(self,k).get()) for k in ('venue','meters','surface','direction','end')))
        obj=Course(venue=self.venue.get().strip(),meters=int(raw),surface=self.surface.get(),
                   direction=self.direction.get(),season=self.season.get(),weather=self.weather.get(),
                   ground=self.ground.get(),end=self.end.get() if matches else '미검증',
                   style=self.style.get(),event=self.event.get(),
                   source=preset['source'] if matches else '')
        obj.validate()
        return obj

    def _stats(self,course):
        preset=COURSES.get(self.preset.get(),{})
        matching=(preset.get('venue')==course.venue and preset.get('meters')==course.meters)
        advice=preset.get('stamina_guidance') if matching else '코스별 검증된 목표 스태미나 수치 없음'
        try:
            p=self.get_profile(); stats=' / '.join(f'{s} {n}' for s,n in p.target_stats.items())
        except Exception:
            stats='목표 수치를 불러올 수 없음'
        self.statnote.set(f'[육성 전 목표] {course.venue} {course.meters}m · {distance_type(course.meters)} · {course.style} · {course.event}\n'
                          f'현재 사용자 목표(공식 권장치 아님): {stats}  |  근거: {advice}')

    def clear_results(self):
        if hasattr(self,'tree'):
            for i in self.tree.get_children():self.tree.delete(i)
        self.last_result=None

    def _calculate(self,manual):
        try:
            course=self.course()
            candidates=parse_candidate_lines(self.skilltext.get('1.0','end')) if manual else default_candidates(course)
            if not candidates:
                raise ValueError('분석할 구매 후보가 없습니다. 스킬명을 입력하거나 미리보기를 선택하세요.')
            ranked=advise(course,candidates)
            self.clear_results();self.last_result=(course,candidates,ranked)
            self._stats(course)
            for i,a in enumerate(ranked):
                category='good' if a.order<=2 else ('bad' if a.order==6 else 'caution')
                self.tree.insert('','end',iid=str(i),values=(a.verdict,a.name,a.condition,a.activation,a.timing,a.efficiency),tags=(category,))
            self._info(('구매 후보 비교: ' if manual else '육성 전 전략 미리보기: ')+str(len(ranked))+'건.\n'
                '녹색 스킬의 코스 조건 일치와 실제 경기 발동 표본은 다릅니다. 실측 표본 없이 표시하는 우선순위는 가이드 후보일 뿐 확률 예측이 아닙니다.')
        except (ValueError,TypeError) as err:
            self.clear_results();self._info('분석 보류: '+str(err))

    def preview(self):self._calculate(False)
    def analyze(self):self._calculate(True)

    def detail(self,_event=None):
        if not self.last_result:return
        selected=self.tree.selection()
        if not selected:return
        obj=self.last_result[2][int(selected[0])]
        interval= '' if obj.wilson_range is None else f'\n실측 유효 발동 비율 95% Wilson 구간: {obj.wilson_range[0]*100:.1f}~{obj.wilson_range[1]*100:.1f}% (표본의 불확실성 표시, 다음 경기 확률 아님)'
        self._info(f'[{obj.name}] {obj.verdict}\n발동: {obj.activation}\n유효 구간: {obj.timing}\nPt: {obj.cost} / {obj.efficiency}\n근거: {obj.note}{interval}\n출처: {obj.source}')

    def apply_to_profile(self):
        try:
            c=self.course()
            self.apply_course(c)
            self._info('경기장/거리/각질/대회 정보를 기본 목표에 적용했습니다. 스탯 목표값은 임의로 덮어쓰지 않았습니다.')
        except ValueError as e:messagebox.showerror('적용 불가',str(e))

    def save(self):
        if not self.last_result:messagebox.showwarning('분석 필요','먼저 미리보기 또는 구매 목록 분석을 실행하세요.');return
        f=filedialog.asksaveasfilename(defaultextension='.json',initialfile='UmaR12_course_skills.json',filetypes=[('JSON','*.json')])
        if f:
            try:save_report(f,*self.last_result);self._info('R12 코스·스킬 검수 결과 저장 완료: '+f)
            except OSError as e:messagebox.showerror('저장 실패',str(e))

    def clear(self):
        self.skilltext.delete('1.0','end');self.clear_results();self._info('스킬 후보 목록과 분석을 초기화했습니다. 코스 입력은 유지됩니다.')
