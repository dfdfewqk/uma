"""R11 Tk review: explicit requirements; no ML model and no automated quit decision."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import asdict

from goal_tracker_r11 import (RequiredSkill, SKILL_STATUSES, assess_goals,
                              context_fingerprint, export_goal_report,
                              verified_current_run_trend, save_goal_template, load_goal_template)
from island_planner_r7 import FACILITIES


class GoalPanel(ttk.Frame):
    def __init__(self, parent, get_profile, get_state, get_run_context):
        super().__init__(parent)
        self.get_profile = get_profile
        self.get_state = get_state
        self.get_run_context = get_run_context
        self.last_result = None
        self._last_args = None
        self._build()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True)
        canvas = tk.Canvas(wrap, bg='#111827', highlightthickness=0)
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas)
        item = canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item,width=e.width))
        self.canvas = canvas
        box = ttk.Frame(content)
        box.pack(fill='both',expand=True,padx=20,pady=12)
        ttk.Label(box,text='R11 · 챔미/리오히 목표 격차 분석',style='Section.TLabel').pack(anchor='w')
        ttk.Label(box,text='현재 턴의 스탯·스킬·시설·평가회 격차만 산술 비교합니다. 성공 확률·도축 판단·ML이 아닙니다.',
                  style='Muted.TLabel',wraplength=1100).pack(anchor='w',pady=(2,11))
        self.status=tk.StringVar(value='필수 스킬·시설 목표를 확인한 뒤 분석하세요.')
        ttk.Label(box,textvariable=self.status,style='Muted.TLabel',wraplength=1100).pack(anchor='w',pady=(0,8))
        ttk.Label(box,text='필수 실전 스킬  (한 줄씩: 스킬명 | 상태 | 실제 확인한 유효 Pt 비용)',
                  style='Section.TLabel').pack(anchor='w',pady=(8,4))
        ttk.Label(box,text='상태: 미확인 / 미확보 / 힌트확보 / 획득완료 · 비용을 모르면 세 번째 칸은 비워두세요.',
                  style='Muted.TLabel').pack(anchor='w')
        ttk.Label(box,text='예: 임의스킬A | 힌트확보 | 180 (예시이며 현재 표에는 입력되지 않음)',
                  style='Muted.TLabel').pack(anchor='w')
        self.skills_editor=tk.Text(box,height=5,bg='#233047',fg='#F3F6FB',insertbackground='white',
                                   relief='flat',wrap='none')
        self.skills_editor.pack(fill='x',pady=(4,5))
        self.confirm_skills=tk.BooleanVar(value=False)
        ttk.Checkbutton(box,variable=self.confirm_skills,text='필수 스킬 목록을 직접 검토했음 (필수 스킬이 없다면 빈 목록을 확인)')\
            .pack(anchor='w',pady=(0,9))
        ttk.Label(box,text='시설 목표 Lv (빈칸 = 미확인/미설정)',style='Section.TLabel').pack(anchor='w')
        levels=ttk.Frame(box);levels.pack(fill='x',pady=(4,10))
        self.facility_vars={}
        for facility in FACILITIES:
            block=ttk.Frame(levels);block.pack(side='left',padx=(0,17))
            ttk.Label(block,text=facility,style='Muted.TLabel').pack(anchor='w')
            var=tk.StringVar(value='')
            self.facility_vars[facility]=var
            ttk.Entry(block,textvariable=var,width=7).pack(anchor='w')
        ttk.Label(box,text='다음 평가회 목표 (모르면 빈칸)',style='Section.TLabel').pack(anchor='w')
        frame=ttk.Frame(box);frame.pack(fill='x',pady=(5,10))
        self.exam_target=tk.StringVar()
        self.exam_remaining=tk.StringVar()
        for label,var in (('목표 발전 Pt',self.exam_target),('평가회까지 남은 턴',self.exam_remaining)):
            block=ttk.Frame(frame);block.pack(side='left',padx=(0,20))
            ttk.Label(block,text=label,style='Muted.TLabel').pack(anchor='w')
            ttk.Entry(block,textvariable=var,width=17).pack(anchor='w')
        cmds=ttk.Frame(box);cmds.pack(fill='x',pady=(6,9))
        for title,fn in (('현재 상태 분석',self.analyze),('R3 기록 추세 포함',self.analyze_with_history),
                         ('결과 JSON 저장',self.save),('목표 저장',self.save_template),('목표 불러오기',self.load_template),('검수 초기화',self.clear)):
            ttk.Button(cmds,text=title,command=fn).pack(side='left',padx=(0,9))
        self.summary=tk.Text(box,height=23,bg='#192438',fg='#F3F6FB',wrap='word',
                             highlightthickness=0,relief='flat',padx=12,pady=10)
        self.summary.pack(fill='both',expand=True)
        self._show('먼저 ① 육성 목표와 ② 턴 분석의 현재 값을 확인하세요.\n\n'
                   '필수 스킬과 시설 목표를 지정해 두면 누적 목표 격차를 확인할 수 있습니다.\n'
                   '미입력 정보는 추정해 채우지 않습니다.')

    def _show(self, message):
        self.summary.configure(state='normal')
        self.summary.delete('1.0','end')
        self.summary.insert('1.0',message)
        self.summary.configure(state='disabled')

    @staticmethod
    def _optional_int(raw,label,maximum):
        raw=raw.strip()
        if not raw:return None
        if not raw.isascii() or not raw.isdecimal() or int(raw)>maximum:
            raise ValueError(f'{label}은(는) 0~{maximum} 사이 정수 또는 빈칸이어야 합니다.')
        return int(raw)

    def _collect(self):
        skills=[]
        for i,row in enumerate(self.skills_editor.get('1.0','end').splitlines(),1):
            if not row.strip():continue
            parts=[x.strip() for x in row.split('|')]
            if len(parts) not in (2,3):
                raise ValueError(f'스킬 {i}행: 스킬명 | 상태 | 비용(선택) 형식으로 입력하세요.')
            name,status=parts[:2]
            if status not in SKILL_STATUSES:
                raise ValueError(f'스킬 {i}행: 스킬 상태를 확인하세요.')
            cost=self._optional_int(parts[2],f'스킬 {i}행 비용',9999) if len(parts)==3 else None
            skills.append(RequiredSkill(name,status,cost))
        facilities={}
        for name,var in self.facility_vars.items():
            level=self._optional_int(var.get(),name+' 시설 레벨',3 if name=='해변의 집' else 5)
            if level is not None:facilities[name]=level
        return {'skills':skills,'facility_targets':facilities,
                'skills_confirmed':self.confirm_skills.get(),
                'evaluation_target':self._optional_int(self.exam_target.get(),'목표 발전 Pt',30000),
                'turns_until_evaluation':self._optional_int(self.exam_remaining.get(),'평가회 남은 턴',150)}

    def _compute(self,with_history=False):
        profile=self.get_profile()
        state=self.get_state()
        kwargs=self._collect()
        trend=None
        if with_history:
            conn,rid=self.get_run_context()
            trend=verified_current_run_trend(conn,rid,profile,state,**kwargs)
        result=assess_goals(profile,state,**kwargs,observed_trend=trend)
        self._last_args=kwargs
        self.last_result=result
        return result, trend

    def analyze(self):self._analyze(False)
    def analyze_with_history(self):self._analyze(True)

    def _analyze(self,history):
        try:
            result,trend=self._compute(history)
            if result.errors:
                self.status.set('검수 오류 · 다시 입력')
                self._show('\n'.join('• '+e for e in result.errors))
                return
            lines=['[R11 · 목표 격차]',result.status,'',
                   '목표 수치는 사용자가 입력한 예시/개인 목표입니다. 최적 승률 목표가 아닙니다.','',
                   '[스탯 부족량]']
            for g in result.stats:
                v='기준 도달' if g['gap']==0 else f"+{g['gap']} 필요"
                avg='계산 불가' if g['required_per_remaining_turn'] is None else f"남은 턴 평균 {g['required_per_remaining_turn']}"
                lines.append(f"• {g['name']}: {g['current']} / {g['target']} · {v} · {avg}")
            skill=result.skills
            lines.extend(['','[필수 스킬]',f"목록 검토 여부: {'예' if skill['list_confirmed'] else '아니요'}",
                          f"획득 완료: {', '.join(skill['acquired']) or '없음'}",
                          f"미획득: {', '.join(skill['missing']) or '없음'}",
                          f"상태 불명: {', '.join(skill['unknown_status']) or '없음'}",
                          f"유효 비용 불명: {', '.join(skill['unknown_effective_cost']) or '없음'}",
                          f"현재 Pt: {skill['current_skill_points']}"])
            if skill['budget_complete']:
                lines.append(f"미획득 스킬 확인 비용 합계: {skill['known_unpurchased_effective_cost']} Pt")
                lines.append(f"지금 즉시 구매 가정 Pt 부족: {skill['point_shortfall_if_buy_now']} Pt")
            else:
                lines.append('미획득 스킬 총 비용: 계산 보류 (상태/비용/목록 미확인)')
            lines.extend(['','[시설 목표]'])
            for f in result.facilities:
                lines.append(f"• {f['name']}: 현재 Lv{f['current']} / 목표 {('미입력' if f['target'] is None else 'Lv'+str(f['target']))} · {f['flag']}")
            ex=result.evaluation
            lines.extend(['','[평가회 / 섬 티켓]',
                          f"평가회: {ex['status']}",
                          f"발전 Pt 부족량: {ex['gap'] if ex['gap'] is not None else '미확인'}",
                          f"보유 티켓: {result.island_tickets['held']}장 · {result.island_tickets['status']}"])
            if trend:
                lines.extend(['','[같은 육성의 과거 관측 추세 · 미래 성장 예측 아님]',
                              f"인접 턴 관찰 구간: {trend['intervals']}개"])
                for name,v in trend['medians'].items():lines.append(f'• {name}: 턴간 관측 중앙값 {v}')
            elif history:
                lines.append('과거 추세: 현재와 정확히 일치하는 충분한 기록 없음 · 반영하지 않음')
            lines.extend(['','[주의 / 미검증 항목]']+['• '+x for x in result.cautions])
            self._show('\n'.join(lines))
            self.status.set(result.status + (' · 현재 기록 추세 연결' if trend else ''))
        except (ValueError,TypeError,KeyError) as err:
            self.last_result=self._last_args=None
            self.status.set('분석 보류 · 잘못된 입력')
            self._show(str(err))

    def clear(self):
        self.last_result=None
        self._last_args=None
        self.status.set('이전 턴 분석 무효화 · 목표 입력은 유지')
        self._show('현재 턴 목표를 다시 분석하세요. 이전 결과는 재사용하지 않습니다.')

    def save(self):
        if self.last_result is None or self._last_args is None:
            messagebox.showwarning('분석 필요','먼저 현재 상태를 분석하세요.')
            return
        try:
            p=self.get_profile();s=self.get_state();now=self._collect()
            if context_fingerprint(p,s,**now)!=self.last_result.context_hash:
                raise ValueError('목표·턴 상태 또는 검수 입력이 바뀌었습니다. 다시 분석하세요.')
            path=filedialog.asksaveasfilename(defaultextension='.json',
                initialfile='UmaR11_goal_audit.json',filetypes=[('JSON','*.json')])
            if path:
                export_goal_report(path,p,s,now['skills'],now['facility_targets'],self.last_result,
                                   skills_confirmed=now['skills_confirmed'],
                                   evaluation_target=now['evaluation_target'],
                                   turns_until_evaluation=now['turns_until_evaluation'])
                self.status.set('현재 턴 R11 목표 격차 기록 저장: '+path)
        except (ValueError,OSError,TypeError) as err:
            messagebox.showerror('저장 불가',str(err))

    def save_template(self):
        try:
            profile=self.get_profile()
            current=self._collect()
            path=filedialog.asksaveasfilename(defaultextension='.json',
                initialfile='UmaR11_goal_template.json',filetypes=[('JSON','*.json')])
            if path:
                save_goal_template(path,profile,current['skills'],current['facility_targets'],
                                   current['evaluation_target'])
                self.status.set('목표 설정 템플릿 저장 · 새 육성에서는 다시 검수하세요: '+path)
        except (ValueError,TypeError,OSError) as err:
            messagebox.showerror('목표 설정 저장 실패',str(err))

    def load_template(self):
        path=filedialog.askopenfilename(title='R11 목표 설정 불러오기',filetypes=[('JSON','*.json')])
        if not path:return
        try:
            # Verify all data BEFORE updating any input controls.
            loaded=load_goal_template(path,self.get_profile())
            text='\n'.join(f"{x.name} | {x.status}" +
                            (f" | {x.effective_cost}" if x.effective_cost is not None else '')
                            for x in loaded['skills'])
            self.skills_editor.delete('1.0','end')
            self.skills_editor.insert('1.0',text)
            for key,var in self.facility_vars.items():
                value=loaded['facility_targets'].get(key)
                var.set(str(value) if value is not None else '')
            self.exam_target.set(str(loaded['evaluation_target']) if loaded['evaluation_target'] is not None else '')
            self.exam_remaining.set('')  # Deadlines must always be confirmed on a new run.
            self.confirm_skills.set(False)
            self.clear()
            self.status.set('목표 설정 불러옴 · 필수 스킬 재검수 및 평가회 남은 턴 재입력 필요')
        except (ValueError,TypeError,OSError,KeyError) as err:
            messagebox.showerror('목표 설정 불러오기 실패',str(err))
