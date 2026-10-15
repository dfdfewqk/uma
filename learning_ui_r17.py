"""R17 research-only version registry and evidence-gated result annotation panel."""
from __future__ import annotations
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from ml_engine_r16 import load_r15_exports, read_model
from model_registry_r17 import (default_registry_root, read_registry, register_model,
                                compare_candidate, promote_model, rollback_model)
from result_labels_r17 import connect_reviews, collect_results, review_run, export_results
from storage import list_runs


class R17ResearchPanel(ttk.Frame):
    def __init__(self, master, runs_db):
        super().__init__(master)
        self.runs_db = runs_db
        self.reviews_db = connect_reviews()
        self.root = default_registry_root()
        self.data_folder = None
        self.rows = []
        self.candidate_id = None
        self.selected_scope = None
        canvas = tk.Canvas(self, bg='#111827', highlightthickness=0)
        bar = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        body = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        ttk.Label(body, text='R17 · 연구 모델 버전 관리 / 실전 결과 검수', style='Section.TLabel').pack(anchor='w', padx=16, pady=(14, 7))
        ttk.Label(body, text='R16 모델은 사람 행동 모방 연구용입니다. 연구 챔피언으로 지정해도 실제 육성 추천에 적용되지 않습니다.\n검증 성능의 비교는 같은 R15 자료의 validation 분할에서만 진행하며 test 데이터는 모델 선정에 사용하지 않습니다.',
                  style='Muted.TLabel', wraplength=900).pack(anchor='w', padx=16, pady=4)
        row = ttk.Frame(body);row.pack(fill='x', padx=16, pady=8)
        ttk.Button(row, text='R15 검수 데이터 폴더', command=self.load_folder).pack(side='left', padx=3)
        ttk.Button(row, text='R16 모델 JSON 등록', command=self.register).pack(side='left', padx=3)
        ttk.Button(row, text='검증 자료로 모델 비교', command=self.compare).pack(side='left', padx=3)
        ttk.Button(row, text='연구 기준 모델 지정', command=self.promote).pack(side='left', padx=3)
        ttk.Button(row, text='이전 모델 복원', command=self.rollback).pack(side='left', padx=3)
        self.model_log = tk.Text(body, height=11, bg='#192438', fg='#F3F6FB', wrap='word', relief='flat')
        self.model_log.pack(fill='both', padx=16, pady=6)
        ttk.Label(body, text='완주·도축 결과 검수 — 육성 기록에 결과를 먼저 입력해야 합니다.', style='Section.TLabel').pack(anchor='w',padx=16,pady=(14,6))
        row2 = ttk.Frame(body);row2.pack(fill='x', padx=16, pady=5)
        ttk.Label(row2, text='육성 번호').pack(side='left')
        self.run_id = tk.StringVar(); self.combo = ttk.Combobox(row2, width=30, textvariable=self.run_id, state='readonly')
        self.combo.pack(side='left', padx=8)
        ttk.Button(row2, text='육성 목록 새로고침', command=self.refresh_runs).pack(side='left')
        self.evidence = tk.StringVar()
        row3 = ttk.Frame(body);row3.pack(fill='x', padx=16, pady=6)
        ttk.Label(row3, text='결과 화면').pack(side='left');ttk.Entry(row3,textvariable=self.evidence).pack(side='left', fill='x',expand=True,padx=8)
        ttk.Button(row3,text='이미지 선택',command=self.choose_evidence).pack(side='left')
        line = ttk.Frame(body);line.pack(fill='x',padx=16,pady=6)
        self.server=tk.StringVar(value='KR');self.patch=tk.StringVar();self.source=tk.StringVar();self.note=tk.StringVar()
        for label,var,w in [('서버',self.server,6),('패치',self.patch,22),('출처ID',self.source,20),('검수 메모',self.note,34)]:
            ttk.Label(line,text=label).pack(side='left',padx=4)
            ttk.Entry(line,textvariable=var,width=w).pack(side='left',padx=3)
        line2=ttk.Frame(body);line2.pack(fill='x',padx=16,pady=6)
        self.matches=tk.StringVar();self.wins=tk.StringVar();self.points=tk.StringVar()
        for label,var in [('경기수(선택)',self.matches),('승리수(선택)',self.wins),('리오히점수(선택)',self.points)]:
            ttk.Label(line2,text=label).pack(side='left',padx=6)
            ttk.Entry(line2,textvariable=var,width=10).pack(side='left',padx=3)
        ttk.Button(line2,text='결과 검수 등록',command=self.save_review).pack(side='left',padx=12)
        ttk.Button(line2,text='연구 자료 JSONL 저장',command=self.export).pack(side='left',padx=4)
        self.result_log=tk.Text(body,height=9,bg='#192438',fg='#F3F6FB',wrap='word',relief='flat')
        self.result_log.pack(fill='both',padx=16,pady=(6,16))
        self.refresh_runs()
        self._model_message('모델 파일과 R15 검수 자료가 준비되면 등록·비교할 수 있습니다.\n기존 ML은 자동 추천과 연결하지 않습니다.')
        self.inspect_results()

    def _model_message(self,msg):
        self.model_log.delete('1.0','end'); self.model_log.insert('end',msg)

    def _result_message(self,msg):
        self.result_log.delete('1.0','end'); self.result_log.insert('end',msg)

    def _guard(self, fn):
        try:return fn()
        except Exception as exc:
            self._model_message(str(exc))
            messagebox.showwarning('R17 보류',str(exc))

    def load_folder(self):
        f = filedialog.askdirectory(title='R15 JSONL 검수 자료 선택')
        if not f:return
        def job():
            self.rows = load_r15_exports(Path(f))
            self.data_folder=f
            self._model_message(f'검수 자료 {len(self.rows)}턴 로드 완료\n시나리오·패치별 모델 검증만 허용됩니다.')
        self._guard(job)

    def register(self):
        f=filedialog.askopenfilename(filetypes=[('R16 JSON','*.json')])
        if not f:return
        def job():
            model=read_model(Path(f))
            self.candidate_id=register_model(self.root,model)
            self.selected_scope=model['scope']
            self._model_message('연구용 모델 등록 완료\nID: '+self.candidate_id+'\n실전 자동 추천에 적용되지 않습니다.')
        self._guard(job)

    def compare(self):
        def job():
            if not self.candidate_id or not self.rows:raise ValueError('모델 등록과 R15 자료 불러오기를 먼저 해주세요.')
            rep=compare_candidate(self.root,self.candidate_id,self.rows)
            self._model_message('연구 모델 비교 결과\n'+str(rep)+'\n시험(test) 분할은 모델 선정에 사용하지 않음.')
        self._guard(job)

    def promote(self):
        if not messagebox.askyesno('R17 연구용 기준 모델','같은 검증 자료에서 기준을 통과한 경우에만 연구용 기준 모델로 지정합니다. 게임 추천에는 적용되지 않습니다. 진행할까요?'):
            return
        def job():
            if not self.candidate_id or not self.rows:raise ValueError('등록 모델과 R15 자료가 필요합니다.')
            rev=read_registry(self.root)['revision']
            rep=promote_model(self.root,self.candidate_id,self.rows,expected_revision=rev)
            self._model_message('연구용 기준 모델 지정 완료: '+rep['candidate_id']+'\n실전 추천 시스템은 변경하지 않았습니다.')
        self._guard(job)

    def rollback(self):
        if not messagebox.askyesno('R17 연구용 복원','이전 연구용 기준 모델로 복원합니다. 계속할까요?'):
            return
        def job():
            if not self.selected_scope:raise ValueError('복원 범위가 선택되지 않았습니다.')
            revision=read_registry(self.root)['revision']
            mid=rollback_model(self.root,self.selected_scope,expected_revision=revision)
            self.candidate_id=mid
            self._model_message('이전 연구 모델 복원: '+mid+'\n실전 추천은 변경하지 않았습니다.')
        self._guard(job)

    def refresh_runs(self):
        self.available={}
        for r in list_runs(self.runs_db):
            if r['outcome'].get('status') in ('육성 완료','도축/중단'):
                label=f"{r['id']} · {r['profile'].get('character','?')} · {r['outcome'].get('status')}"
                self.available[label]=r['id']
        self.combo['values']=list(self.available)
        if self.available and self.run_id.get() not in self.available:self.run_id.set(next(iter(self.available)))

    def choose_evidence(self):
        f=filedialog.askopenfilename(filetypes=[('이미지','*.png *.jpg *.jpeg *.webp')])
        if f:self.evidence.set(f)

    def save_review(self):
        try:
            if self.run_id.get() not in self.available:raise ValueError('완주·도축 육성을 선택하세요.')
            integer=lambda s: None if not s.strip() else int(s.strip())
            review_run(self.runs_db,self.reviews_db,self.available[self.run_id.get()],Path(self.evidence.get()),
                       server=self.server.get(),patch_version=self.patch.get(),
                       provenance_group=self.source.get(),reviewer_note=self.note.get(),
                       race_matches=integer(self.matches.get()),race_wins=integer(self.wins.get()),
                       loh_points=integer(self.points.get()))
            self.inspect_results()
        except Exception as exc: messagebox.showwarning('R17 결과 검수 보류',str(exc))

    def inspect_results(self):
        r=collect_results(self.runs_db,self.reviews_db)
        self._result_message(f"결과 화면 검수: 유효 {len(r['kept'])}건 / 제외 {len(r['excluded'])}건\n"
                             '도축은 중도 검열 자료로 관리하며 완주 실패로 학습하지 않습니다.\n'
                             '현재 결과 자료는 관찰 기록일 뿐 ML 학습 자동 투입 대상이 아닙니다.\n'+str(r['excluded'][:8]))

    def export(self):
        f=filedialog.asksaveasfilename(defaultextension='.jsonl',initialfile='uma_r17_observed_outcomes.jsonl',filetypes=[('JSONL','*.jsonl')])
        if not f:return
        try:
            result=export_results(self.runs_db,self.reviews_db,Path(f))
            self.inspect_results()
            messagebox.showinfo('R17 내보내기',f"검수 {result['exported']}건, 제외 {len(result['excluded'])}건 저장.")
        except Exception as exc:messagebox.showwarning('R17 내보내기 실패',str(exc))
