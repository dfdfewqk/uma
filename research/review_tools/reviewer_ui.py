"""Manual evidence-first video turn reviewer. Tkinter, standard library only.

Run from source: python research/review_tools/reviewer_ui.py
Video/screenshot files remain at their original local locations.
"""
from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser
from pathlib import Path
from annotation_core import (read_sources, add_annotation, read_annotations,
                             audit_annotations, AnnotationError, DEFAULT_OUTPUT)


class Reviewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Uma Trainer KR - 일본 무인도 영상 검수 R2')
        self.geometry('1060x830')
        self.minsize(850, 650)
        self.sources = {k:v for k,v in read_sources().items() if v['source_kind'].startswith('video_')}
        self.fields = {}
        self.images = {}
        self.preview = None
        self._build()
        self.set_defaults()

    def add_line(self, parent, label, key, default='', row=0, width=50, choices=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=3, padx=8)
        var = tk.StringVar(value=default)
        if choices:
            widget = ttk.Combobox(parent, textvariable=var, values=choices, width=width, state='readonly')
        else:
            widget = ttk.Entry(parent, textvariable=var, width=width)
        widget.grid(row=row, column=1, columnspan=3, sticky='ew', padx=(2,8), pady=3)
        self.fields[key] = var
        return widget

    def _build(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill='x')
        ttk.Label(top, text='영상 턴 검수 — 실제 프레임에 보이는 값만 기록', font=('Malgun Gothic', 15, 'bold')).pack(anchor='w')
        ttk.Label(top, text='상태+행동+결과를 구분하고, 불확실한 값은 비워 둡니다. 모든 기록은 “실제 플레이어 선택”이며 최적 행동 정답은 아닙니다.').pack(anchor='w', pady=5)
        outer = ttk.Frame(self)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas, padding=12)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        item = canvas.create_window((0,0), window=body, anchor='nw')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))

        media = ttk.LabelFrame(body, text='1. 출처와 시간', padding=8)
        media.pack(fill='x', pady=5)
        choices = [f"{id} — {v['title_ko'][:38]}" for id,v in self.sources.items()]
        self.add_line(media,'영상 출처','source_id',row=0,choices=choices)
        ttk.Button(media,text='원본 영상 열기',command=self.open_source).grid(row=0,column=4,padx=6)
        self.add_line(media,'육성 식별자 (예: sample001)','case_id',row=1)
        self.add_line(media,'영상 시점 (초)','video_seconds',row=2)
        self.add_line(media,'육성 연도','school_year',row=3,choices=['주니어','클래식','시니어','파이널즈'])
        self.add_line(media,'날짜/턴 표기','turn_label',row=4)
        self.add_line(media,'대회 구분','competition',row=5,choices=['챔피언스 미팅','리그 오브 히어로즈','미확인'])
        self.add_line(media,'캐릭터 이름','character',row=6)
        self.add_line(media,'육성 목적','run_purpose',row=7,choices=['champ_main','loh_main','factor_farming','evaluation_score','unknown'])
        self.add_line(media,'검수자 이름','reviewer',row=8)
        self.add_line(media,'패치 이후 플레이 근거','patch_evidence',row=9,width=85)

        state = ttk.LabelFrame(body, text='2. 프레임에서 읽은 게임 상태 (모르면 공란)', padding=8)
        state.pack(fill='x', pady=5)
        for i, (text,key) in enumerate([('체력','energy'),('스피드','speed'),('스태미나','stamina'),('파워','power'),('근성','guts'),('지능','wisdom'),('스킬 Pt','skill_points'),('섬 티켓','island_tickets'),('발전 Pt','development_points')]):
            self.add_line(state,text,key,row=i)
        self.add_line(state,'시설 레벨 JSON','facilities_json',row=9,width=85)

        choice = ttk.LabelFrame(body, text='3. 실제 행동/다음 결과', padding=8)
        choice.pack(fill='x', pady=5)
        self.add_line(choice,'확인한 선택지 JSON','alternatives_json',row=0,width=85)
        self.add_line(choice,'실제로 누른 행동','chosen_action',row=1)
        self.add_line(choice,'다음 결과 JSON','post_action_json',row=2,width=85)
        self.choice_var = tk.BooleanVar(value=False)
        self.result_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(choice, text='영상에서 실제 클릭 확인',variable=self.choice_var).grid(row=3,column=1,sticky='w')
        ttk.Checkbutton(choice, text='선택 후 결과 화면 확인',variable=self.result_var).grid(row=4,column=1,sticky='w')

        shots = ttk.LabelFrame(body, text='4. 증거 프레임 (로컬 PNG/JPG/WebP, 원본 이미지 복사/배포하지 않음)', padding=8)
        shots.pack(fill='x', pady=5)
        for j,(label,key) in enumerate([('선택 전 화면','frame_before_path'),('선택 후 화면','frame_after_path')]):
            self.add_line(shots,label,key,row=j,width=84)
            ttk.Button(shots,text='찾기',command=lambda k=key:self.select_image(k)).grid(row=j,column=4,padx=4)
        self.preview_label = ttk.Label(shots,text='선택한 화면 미리보기 (이미지 선택 후 표시)')
        self.preview_label.grid(row=2,column=0,columnspan=5,pady=12)
        self.add_line(shots,'검수 메모','notes',row=3,width=85)
        shots.columnconfigure(1,weight=1)

        bottom = ttk.Frame(body)
        bottom.pack(fill='x', pady=15)
        ttk.Button(bottom,text='검증 후 턴 저장',command=self.save).pack(side='left',padx=5)
        ttk.Button(bottom,text='검수 요약',command=self.summary).pack(side='left',padx=5)
        ttk.Button(bottom,text='새 턴 입력',command=self.reset_turn).pack(side='left',padx=5)
        self.status=tk.StringVar(value='아직 실제 검수 턴 0건 — 이미지를 선택하고 검증해 저장하세요.')
        ttk.Label(bottom,textvariable=self.status).pack(side='left',padx=18)

    def set_defaults(self):
        self.fields['source_id'].set(next(iter(self.sources)) + ' — ' + next(iter(self.sources.values()))['title_ko'][:38])
        self.fields['school_year'].set('주니어')
        self.fields['competition'].set('미확인')
        self.fields['run_purpose'].set('unknown')
        self.fields['facilities_json'].set('{}')
        self.fields['alternatives_json'].set('{}')
        self.fields['post_action_json'].set('{}')
        self.fields['reviewer'].set('local_review')

    def reset_turn(self):
        saved_src=self.fields['source_id'].get()
        saved_case=self.fields['case_id'].get()
        saved_reviewer=self.fields['reviewer'].get()
        saved_purpose=self.fields['run_purpose'].get()
        for var in self.fields.values():
            var.set('')
        self.set_defaults()
        self.fields['source_id'].set(saved_src)
        self.fields['case_id'].set(saved_case)
        self.fields['reviewer'].set(saved_reviewer)
        self.fields['run_purpose'].set(saved_purpose)
        self.choice_var.set(False)
        self.result_var.set(False)
        self.preview_label.configure(image='',text='새 턴 입력')
        self.preview=None

    def open_source(self):
        source_id=self.fields['source_id'].get().split(' — ',1)[0]
        if source_id in self.sources:
            webbrowser.open(self.sources[source_id]['url'])

    def select_image(self, key):
        img=filedialog.askopenfilename(filetypes=[('이미지','*.png *.jpg *.jpeg *.webp'),('모든 파일','*.*')])
        if img:
            self.fields[key].set(img)
            try:
                self.preview=tk.PhotoImage(file=img)
                w,h=self.preview.width(),self.preview.height()
                factor=max(1,(w+680-1)//680,(h+260-1)//260)
                if factor>1:
                    self.preview=self.preview.subsample(factor,factor)
                self.preview_label.configure(image=self.preview,text='')
            except tk.TclError:
                self.preview_label.configure(image='',text='이 이미지 형식은 미리보기를 지원하지 않습니다. 파일은 검증 후 저장할 수 있습니다.')

    def save(self):
        raw={k:v.get() for k,v in self.fields.items()}
        raw['source_id']=raw['source_id'].split(' — ',1)[0]
        raw.update({'server':'JP','patch_status':'post_2025_06_30_confirmed',
                    'observed_choice':str(self.choice_var.get()).lower(),
                    'observed_result':str(self.result_var.get()).lower()})
        try:
            row=add_annotation(raw)
        except (AnnotationError, OSError, ValueError) as exc:
            messagebox.showerror('저장 불가',str(exc))
            return
        self.status.set(f"저장: {row['annotation_id']} | 검수 등급: {row['review_grade']}")
        messagebox.showinfo('저장 완료','검수된 프레임의 SHA-256이 함께 저장되었습니다.\n실제 선택은 최적 행동 라벨이 아닙니다.')

    def summary(self):
        a=audit_annotations()
        messagebox.showinfo('검수 현황',
            f"저장된 턴: {a['rows']}\n선택+결과 검증: {a['full_before_and_after']}\n"
            f"일부 관찰: {a['partial_rows']}\n오류: {len(a['errors'])}\n"
            f"기록 위치: {DEFAULT_OUTPUT}\n\n{a['ml_training_status']}")


if __name__=='__main__':
    Reviewer().mainloop()
