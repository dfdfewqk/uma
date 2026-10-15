"""R16 local research ML: inspect exported R15 data and explicitly train."""
from __future__ import annotations
import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from ml_engine_r16 import (load_r15_exports, cohort_summary,
                            train_behavior, save_model)


class MLResearchPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.rows = []
        self.cohorts = []
        self.selected = {}
        self.model = None
        canvas = tk.Canvas(self, bg='#111827', highlightthickness=0)
        bar = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        body = ttk.Frame(canvas)
        slot = canvas.create_window((0,0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(slot, width=e.width))
        ttk.Label(body, text='R16 · 로컬 ML 학습·평가 (연구용)', style='Section.TLabel').pack(anchor='w',padx=18,pady=(15,7))
        ttk.Label(body, text='사람의 선택 패턴을 학습합니다. 추천의 최적성, 실전 승률, 고점 달성 가능성 및 도축 확률을 예측하는 모델이 아닙니다.\n모델은 기존 육성 추천에 자동 적용되지 않습니다.',
                  style='Muted.TLabel',wraplength=920).pack(anchor='w',padx=18,pady=(0,10))
        row=ttk.Frame(body);row.pack(fill='x',padx=18,pady=8)
        self.folder=tk.StringVar(value='R15에서 내보낸 JSONL 폴더를 선택하세요.')
        ttk.Label(row,textvariable=self.folder,style='Muted.TLabel',wraplength=650).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='R15 자료 폴더',command=self.select_folder).pack(side='right',padx=8)
        ttk.Button(row,text='검수·목록 새로고침',command=self.load_data).pack(side='right',padx=8)
        row2=ttk.Frame(body);row2.pack(fill='x',padx=18,pady=8)
        ttk.Label(row2,text='학습할 시나리오/서버/패치/대회').pack(side='left',padx=(0,10))
        self.cohort_var=tk.StringVar()
        cb=self.combo=ttk.Combobox(row2,textvariable=self.cohort_var,state='readonly',width=88)
        cb.pack(side='left',fill='x',expand=True)
        cb.bind('<<ComboboxSelected>>',lambda _:self.describe())
        row3=ttk.Frame(body);row3.pack(fill='x',padx=18,pady=6)
        ttk.Button(row3,text='R16 로컬 학습 및 홀드아웃 평가',style='Accent.TButton',command=self.train).pack(side='left',padx=(0,12))
        ttk.Button(row3,text='모델 JSON 파일 저장',command=self.save).pack(side='left')
        ttk.Label(body,text='최소: 동일 코호트 200턴, 독립 출처 30개, 검증·시험 각각 2개 이상 출처. 세 분할 모두 필요.\n공개용 배포나 기존 추천 기능 교체는 하지 않습니다.',
                  style='Muted.TLabel',wraplength=950).pack(anchor='w',padx=18,pady=12)
        self.log=tk.Text(body,height=23,bg='#192438',fg='#F3F6FB',insertbackground='white',relief='flat',wrap='word')
        self.log.pack(fill='both',expand=True,padx=18,pady=12)
        self.display('R15에서 실제 검수 데이터를 내보낸 후 그 폴더를 지정하세요.\n현재 학습된 모델 없음.')

    def display(self, s):
        self.log.delete('1.0','end');self.log.insert('1.0',s)

    def select_folder(self):
        path=filedialog.askdirectory(title='R15 JSONL 내보내기 폴더 선택')
        if path:
            self.folder.set(path)
            self.load_data()

    def load_data(self):
        self.model=None
        self.rows=[];self.cohorts=[];self.selected={}
        self.combo['values']=[];self.cohort_var.set('')
        try:
            self.rows=load_r15_exports(Path(self.folder.get()))
            self.cohorts=cohort_summary(self.rows)
            for c in self.cohorts:
                status='학습 조건 충족' if c['eligible'] else '자료 부족 · 보류'
                name=' | '.join(c['key']) + f"  | {c['rows']}턴 | {status}"
                self.selected[name]=c
            self.combo['values']=list(self.selected)
            if self.selected:self.cohort_var.set(next(iter(self.selected)))
            self.describe()
        except Exception as exc:
            self.display('R15 자료 검증 실패 또는 자료 없음:\n'+str(exc)+'\n\n가상·미검수 자료는 등록하지 마세요.')

    def describe(self):
        c=self.selected.get(self.cohort_var.get())
        if c:
            msg=[f"전체 검수 자료 {len(self.rows)}턴",'선택 코호트: '+' / '.join(c['key']),f"턴: {c['rows']}",
                 '분할별 독립 출처: '+str(c['groups']),
                 '학습 가능: '+('조건 충족(정확도 보증 아님)' if c['eligible'] else '보류 (자료 부족)'),
                 '주의: 사람의 행동을 따라하는 연구 모델이며 게임 내 최선의 선택을 뜻하지 않음.']
            self.display('\n'.join(msg))
        else:self.display(f'검증된 코호트 없음 · 학습 데이터 {len(self.rows)}건 · 모델 미생성')

    def train(self):
        item=self.selected.get(self.cohort_var.get())
        if not item:
            messagebox.showwarning('R16 학습 보류','학습할 코호트가 없습니다.');return
        try:
            self.model=train_behavior(self.rows,item['key'])
            m=self.model['metrics']
            lines=['R16 행동 모방 연구 모델 학습 완료 (실전 추천에는 사용하지 않음)',
                   '범위: '+' / '.join(item['key']),
                   '학습 알고리즘: conditional softmax SGD',
                   '기본 비교 행동: '+self.model['majority_action'],
                   f"검증에서 선택한 학습 epoch: {self.model['training']['chosen_epoch']}"]
            for split in ('train','validation','test'):
                v=m[split]
                lines += [f"{split}: {v['rows']}턴 | 행동 일치율 {v['accuracy']:.1%} | 다수행동 기준 {v['majority_baseline_accuracy']:.1%} | Macro F1 {v['macro_f1']:.3f} | log loss {v['log_loss']:.3f}"]
            lines += ['',self.model['warning'],'성능이 좋아도 승률이나 최적 행동이 입증된 것은 아닙니다.']
            self.display('\n'.join(lines))
        except Exception as exc:
            self.model=None
            self.display('학습 보류: '+str(exc))
            messagebox.showwarning('R16 학습 보류',str(exc))

    def save(self):
        if not self.model:
            messagebox.showwarning('R16','학습된 모델이 없습니다.');return
        path=filedialog.asksaveasfilename(title='연구용 R16 모델 JSON 저장',defaultextension='.json',
                initialfile='uma_r16_behavior_model.json',filetypes=[('JSON','*.json')])
        if path:
            try:
                save_model(self.model,Path(path))
                messagebox.showinfo('R16','연구용 모델 저장 완료. 기존 자동 추천에는 적용되지 않습니다.')
            except Exception as exc: messagebox.showerror('R16',str(exc))
