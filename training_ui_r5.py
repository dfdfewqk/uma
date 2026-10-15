"""R5 desktop: screenshot-aided, explicitly reviewed per-training data.

No automatic game control. Never treats OCR candidates as accepted game data.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from uma_core import STATS
from screen_r4 import load_image
from training_r5 import (FIELDS, TRAINING_CHOICES, OptionEvidence, EvidenceError,
                         compare_options, export_evidence, ocr_candidate)


class TrainingPanel(ttk.Frame):
    def __init__(self, parent, profile_callback, state_callback, apply_callback):
        super().__init__(parent)
        self.profile_callback=profile_callback
        self.state_callback=state_callback
        self.apply_callback=apply_callback
        self.evidence={name:OptionEvidence(name=name) for name in TRAINING_CHOICES}
        self.action=tk.StringVar(value=TRAINING_CHOICES[0])
        self.field=tk.StringVar(value=FIELDS[0])
        self.values={field: tk.StringVar(value='') for field in FIELDS}
        self.markers={}
        self.status=tk.StringVar(value='훈련별 수치를 확인하세요. 0도 확인 후 기록해야 합니다.')
        self.summary=tk.StringVar(value='모든 선택지의 필수값 검수 전에는 훈련 추천을 표시하지 않습니다.')
        self._pending={}
        self._switching=False
        self._image=None
        self._photo=None
        self._box=None
        self._draw=(0,0,1.0)
        self._start=None
        self._comparison=None
        self._context=None
        self._build()
        self._show_action()

    def _build(self):
        # Entire R5 page scrolls: normal 1366x768 laptop screens must not hide controls.
        self.viewport=tk.Canvas(self,bg='#111827',highlightthickness=0)
        scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.viewport.yview)
        self.viewport.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        self.viewport.pack(side='left',fill='both',expand=True)
        content=ttk.Frame(self.viewport)
        win=self.viewport.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda _:self.viewport.configure(scrollregion=self.viewport.bbox('all')))
        self.viewport.bind('<Configure>',lambda e:self.viewport.itemconfigure(win,width=e.width))
        toolbar=ttk.Frame(content)
        toolbar.pack(fill='x', padx=12, pady=(10,6))
        ttk.Label(toolbar, text='훈련:').pack(side='left')
        combo=ttk.Combobox(toolbar, textvariable=self.action, values=TRAINING_CHOICES, state='readonly', width=16)
        combo.pack(side='left', padx=(6,12))
        combo.bind('<<ComboboxSelected>>', lambda _:self._show_action())
        ttk.Button(toolbar, text='새 턴 검수 시작', command=self.new_turn).pack(side='left', padx=3)
        ttk.Button(toolbar, text='이 훈련 스크린샷', command=self.load_screenshot).pack(side='left', padx=3)
        ttk.Button(toolbar, text='훈련 간 비교', command=self.compare).pack(side='left', padx=3)
        ttk.Button(toolbar, text='검수 기록 JSON 저장', command=self.export).pack(side='left', padx=3)
        ttk.Label(content,text='※ 한 화면에 모든 훈련 수치가 나오지 않을 수 있어 각 훈련 화면을 따로 불러올 수 있습니다. 스크린샷 OCR은 후보만 제시합니다.',
                  style='Muted.TLabel').pack(anchor='w',padx=13,pady=(0,8))
        body=ttk.Frame(content)
        body.pack(fill='both',expand=True,padx=12)
        body.columnconfigure(0,weight=5)
        body.columnconfigure(1,weight=4)
        body.rowconfigure(0,weight=1)
        left=ttk.Frame(body)
        left.grid(row=0,column=0,sticky='nsew',padx=(0,12))
        toolbar2=ttk.Frame(left)
        toolbar2.pack(fill='x',pady=(0,6))
        ttk.Label(toolbar2, text='OCR로 읽을 필드:').pack(side='left')
        ttk.Combobox(toolbar2, textvariable=self.field, values=FIELDS, state='readonly', width=19).pack(side='left',padx=5)
        ttk.Button(toolbar2,text='드래그한 영역 OCR 후보',command=self.ocr).pack(side='left',padx=4)
        self.canvas=tk.Canvas(left, bg='#0d1624', highlightthickness=1, highlightbackground='#40506d',height=340,cursor='crosshair')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self._down)
        self.canvas.bind('<B1-Motion>',self._move)
        self.canvas.bind('<ButtonRelease-1>',self._up)
        self.canvas.bind('<Configure>',lambda _:self._render())
        ttk.Label(left,text='스크린샷에서 숫자만 포함하는 영역을 드래그하세요. 체력 변화(+/-)는 반드시 직접 확인하세요.',
                  style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(6,0))
        right=ttk.Frame(body)
        right.grid(row=0,column=1,sticky='nsew')
        ttk.Label(right,text='선택한 훈련의 상승량·위험 수치',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        fields=ttk.Frame(right)
        fields.pack(fill='x')
        for index,field in enumerate(FIELDS):
            ttk.Label(fields,text=field,width=18).grid(row=index,column=0,sticky='w',pady=2)
            entry=ttk.Entry(fields,textvariable=self.values[field],width=10)
            entry.grid(row=index,column=1,sticky='ew',padx=(4,5),pady=2)
            entry.bind('<KeyRelease>',lambda _,f=field:self._changed(f))
            ttk.Button(fields,text='이 값 확인',command=lambda f=field:self.confirm(f)).grid(row=index,column=2,padx=(0,5),pady=2)
            marker=ttk.Label(fields,text='미확인',style='Muted.TLabel')
            marker.grid(row=index,column=3,sticky='w',pady=2)
            self.markers[field]=marker
        fields.columnconfigure(1,weight=1)
        ttk.Label(right,text='우정 발동 시설 수는 섬 트레이닝에서 필수. 발전 Pt·인연도는 추가 정보(선택).',style='Muted.TLabel',wraplength=430).pack(anchor='w',pady=(6,2))
        ttk.Label(content,textvariable=self.status,style='Muted.TLabel',wraplength=1180).pack(anchor='w',padx=13,pady=(4,3))
        bottom=ttk.Frame(content)
        bottom.pack(fill='x',padx=12,pady=(3,10))
        ttk.Label(bottom,textvariable=self.summary,style='Muted.TLabel',wraplength=1160).pack(anchor='w')
        self.result=ttk.Treeview(bottom,columns=('name','score','notes'),show='headings',height=4)
        for key,title,width in (('name','훈련',130),('score','상대 점수 (실험값)',160),('notes','확인 사항',700)):
            self.result.heading(key,text=title)
            self.result.column(key,width=width,anchor='w')
        self.result.pack(fill='x',pady=(5,5))
        self.apply_btn=ttk.Button(bottom,text='확인된 훈련 수치 → ② 턴 분석으로 전달',state='disabled',command=self.apply)
        self.apply_btn.pack(anchor='e')

    def _signature(self):
        # A training screenshot from an older turn must never silently be reused.
        p=asdict(self.profile_callback())
        state=asdict(self.state_callback())
        state.pop('screenshot',None)  # screenshot may change via R4 without moving turns
        return json.dumps([p,state],sort_keys=True,ensure_ascii=False)

    def _check_context(self):
        key=self._signature()
        if self._context is None:
            self._context=key
        elif self._context!=key:
            raise EvidenceError('육성 목표 또는 현재 턴 상태가 바뀌었습니다. 「새 턴 검수 시작」으로 이전 훈련 수치를 초기화하세요.')

    def new_turn(self):
        if any(r.confirmed for r in self.evidence.values()):
            if not messagebox.askyesno('새 턴', '이전 훈련 검수 기록을 초기화할까요? 기존 SQLite 육성 기록은 유지됩니다.'):
                return
        self.evidence={name:OptionEvidence(name=name) for name in TRAINING_CHOICES}
        self._context=None
        self._comparison=None
        self.apply_btn.configure(state='disabled')
        self.result.delete(*self.result.get_children())
        self.summary.set('새 턴을 시작했습니다. 모든 훈련 결과를 다시 확인하세요.')
        self._show_action()

    def _current(self):
        return self.evidence[self.action.get()]

    def _show_action(self):
        self._switching=True
        rec=self._current()
        for f in FIELDS:
            self.values[f].set(str(rec.values[f]) if f in rec.confirmed else '')
            self.markers[f].configure(text='확인됨' if f in rec.confirmed else '미확인')
        self._pending={}
        self._image=None
        if rec.screenshot_file and Path(rec.screenshot_file).is_file():
            try: self._image=load_image(Path(rec.screenshot_file))
            except Exception: pass
        self._box=None
        self._switching=False
        self.status.set(f'{rec.name}: 필수 누락 {len(rec.missing())}개 | 이미지: {"있음" if self._image else "없음"}')
        self._render()

    def _changed(self, field):
        if self._switching:return
        rec=self._current()
        rec.invalidate(field)
        self._pending.pop(field,None)
        self.markers[field].configure(text='미확인')
        self.apply_btn.configure(state='disabled')
        self.result.delete(*self.result.get_children())
        self._comparison=None
        self.summary.set('값을 변경했습니다. 다시 확인 후 전체 비교하세요.')

    def confirm(self, field):
        try:
            self._check_context()
            raw=self.values[field].get()
            src='ocr_reviewed' if self._pending.get(field)==raw else 'manual'
            val=self._current().confirm(field,raw,src)
            self.markers[field].configure(text='확인됨')
            self._pending.pop(field,None)
            self.apply_btn.configure(state='disabled')
            self._comparison=None
            self.status.set(f'{self.action.get()}: {field}={val} 검수 완료 ({src}). 변경 시 검수 해제됩니다.')
        except EvidenceError as exc:
            messagebox.showerror('검수 실패',str(exc))

    def load_screenshot(self):
        path=filedialog.askopenfilename(filetypes=[('이미지','*.png *.jpg *.jpeg *.webp')])
        if not path:return
        try:
            self._check_context()
            self._current().attach_screenshot(Path(path))
            self.apply_btn.configure(state='disabled')
            self._comparison=None
            self.result.delete(*self.result.get_children())
            self._show_action()
            self.status.set('화면 이미지가 변경되어 기존 훈련 검수를 해제했습니다. 새 이미지 기준으로 재확인하세요.')
        except (ValueError,OSError) as exc:
            messagebox.showerror('스크린샷 오류',str(exc))

    def _render(self):
        c=self.canvas
        c.delete('all')
        if self._image is None:
            c.create_text(max(150,c.winfo_width()/2),max(130,c.winfo_height()/2),
                          text='훈련 화면의 스크린샷을 불러오세요.\n실제 화면 OCR 정확도는 검증되지 않았습니다.',fill='#c6d4e8',justify='center')
            return
        from PIL import ImageTk
        w,h=max(200,c.winfo_width()),max(180,c.winfo_height())
        scale=min((w-14)/self._image.width,(h-14)/self._image.height)
        iw,ih=max(1,round(self._image.width*scale)),max(1,round(self._image.height*scale))
        x,y=(w-iw)//2,(h-ih)//2
        self._photo=ImageTk.PhotoImage(self._image.resize((iw,ih)))
        c.create_image(x,y,anchor='nw',image=self._photo)
        self._draw=(x,y,scale)
        if self._box is not None:
            x1,y1,x2,y2=self._box
            c.create_rectangle(x+int(x1*iw),y+int(y1*ih),x+int(x2*iw),y+int(y2*ih),outline='#68b7ff',width=3)

    def _norm(self,x,y):
        left,top,scale=self._draw
        if not self._image or scale<=0:return (0,0)
        return (max(0,min(1,(x-left)/(self._image.width*scale))),
                max(0,min(1,(y-top)/(self._image.height*scale))))

    def _down(self, event):
        if self._image:self._start=self._norm(event.x,event.y)

    def _move(self,event):
        if not self._start:return
        a,b=self._start
        x,y=self._norm(event.x,event.y)
        self._box=min(a,x),min(b,y),max(a,x),max(b,y)
        self._render()

    def _up(self,event):
        self._move(event)
        self._start=None

    def ocr(self):
        if not self._image or not self._box:
            messagebox.showwarning('영역 필요','스크린샷에서 읽을 영역을 드래그하세요.')
            return
        try:
            field=self.field.get()
            self._check_context()
            result=ocr_candidate(Path(self._current().screenshot_file),self._box,field)
            if result['candidate'] is not None:
                self._switching=True
                self.values[field].set(str(result['candidate']))
                self._switching=False
                self._current().invalidate(field)
                self.markers[field].configure(text='OCR 후보')
                self._pending[field]=str(result['candidate'])
                self.status.set(f'OCR 후보: {field}={result["candidate"]}, 신뢰도={result["confidence"]}. 화면과 비교 후 「이 값 확인」을 누르세요.')
            else:
                self._pending.pop(field,None)
                self.status.set(f'OCR 불확실: {result["raw_text"]!r}. 수동으로 입력해서 확인하세요.')
        except (EvidenceError,OSError,ValueError) as exc:
            messagebox.showwarning('OCR 사용 불가',str(exc))

    def compare(self):
        try:
            self._check_context()
            result=compare_options(self.profile_callback(),self.state_callback(),self.evidence)
            self.result.delete(*self.result.get_children())
            self._comparison=result
            if result.status=='추천 보류':
                short=' | '.join(f'{name}: {len(missing)}개 누락' for name,missing in result.missing.items())
                self.summary.set(f'추천 보류 — {short or result.explanation}')
                self.apply_btn.configure(state='disabled')
                return
            self.summary.set(result.explanation)
            for entry in result.ranked:
                self.result.insert('', 'end', values=(entry.name,f'{entry.score:.1f}', ' / '.join(entry.reasons[:2])))
            self.apply_btn.configure(state='normal')
        except (ValueError,KeyError) as exc:
            messagebox.showerror('비교 오류',str(exc))

    def apply(self):
        # Revalidate because the user may have changed other controls after ranking.
        try:
            self._check_context()
            result=compare_options(self.profile_callback(),self.state_callback(),self.evidence)
            if result.status == '추천 보류':
                self.apply_btn.configure(state='disabled')
                self.summary.set('입력 조건이 바뀌어 전달을 중단했습니다. 다시 비교하세요.')
                return
            names=list(STATS)+(['섬 트레이닝'] if self.state_callback().island_tickets>0 else [])
            self.apply_callback({name:self.evidence[name].to_action() for name in names})
        except (ValueError,KeyError) as exc:
            messagebox.showerror('전달 오류',str(exc))

    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='UmaTrainerKR_R5_훈련검수.json',filetypes=[('JSON','*.json')])
        if not path:return
        try:
            self._check_context()
            export_evidence(Path(path),self.evidence,self.profile_callback(),self.state_callback())
            messagebox.showinfo('저장 완료','검수된 필드만 기록했습니다. 이 자료는 ML 정답 데이터가 아닙니다.')
        except (ValueError,OSError) as exc:
            messagebox.showerror('저장 오류',str(exc))
