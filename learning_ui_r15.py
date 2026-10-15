"""R15 evidence-review tab. Local only; there is no online training service."""
from __future__ import annotations
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from learning_data_r15 import (audit_and_collect, connect_reviews, export_training_pack,
                                review_db_path, verify_turn)
from storage import list_runs, list_turns


class LearningPanel(ttk.Frame):
    def __init__(self, master, runs_db):
        super().__init__(master)
        self.runs_db = runs_db
        self.reviews_db = connect_reviews()
        self.run_map = {}
        self.turn_map = {}
        canvas = tk.Canvas(self, bg='#111827', highlightthickness=0)
        sb = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        body = ttk.Frame(canvas)
        slot = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(slot, width=e.width))
        ttk.Label(body, text='R15 · 학습 데이터 검수 (ML 학습은 아직 하지 않음)', style='Section.TLabel').pack(anchor='w', padx=18, pady=(14, 6))
        ttk.Label(body, text='검수 전후 화면을 직접 확인한 턴만 학습 후보로 내보냅니다. 사용자가 고른 행동은 정답이 아닌 행동 기록입니다.',
                  style='Muted.TLabel', wraplength=880).pack(anchor='w', padx=18, pady=(0, 12))
        self.var_run = tk.StringVar()
        self.var_turn = tk.StringVar()
        top = ttk.Frame(body); top.pack(fill='x', padx=18, pady=4)
        ttk.Button(top, text='저장된 육성 새로고침', command=self.reload_runs).pack(side='left', padx=(0, 9))
        self.run_cb = ttk.Combobox(top, textvariable=self.var_run, state='readonly', width=52)
        self.run_cb.pack(side='left', padx=5)
        self.run_cb.bind('<<ComboboxSelected>>', lambda _: self.reload_turns())
        self.turn_cb = ttk.Combobox(top, textvariable=self.var_turn, state='readonly', width=44)
        self.turn_cb.pack(side='left', padx=5)
        self.turn_cb.bind('<<ComboboxSelected>>', lambda _: self.preview_turn())
        self.preview_var = tk.StringVar(value='육성과 턴을 선택하세요.')
        ttk.Label(body, textvariable=self.preview_var, style='Muted.TLabel', wraplength=1000).pack(anchor='w', padx=18, pady=8)
        ttk.Separator(body).pack(fill='x', padx=18, pady=10)
        ttk.Label(body, text='검수 증거 및 적용 환경', style='Section.TLabel').pack(anchor='w', padx=18)
        self.before = tk.StringVar(); self.after = tk.StringVar()
        for label, v in (('선택 전 게임 화면', self.before), ('선택 후 게임 화면', self.after)):
            row = ttk.Frame(body); row.pack(fill='x', padx=18, pady=5)
            ttk.Label(row, text=label, width=23).pack(side='left')
            ttk.Entry(row, textvariable=v).pack(side='left', fill='x', expand=True, padx=5)
            ttk.Button(row, text='파일 찾기', command=lambda value=v: self.select_file(value)).pack(side='left')
        self.origin = tk.StringVar(value='game_screenshot')
        self.server = tk.StringVar(value='KR')
        self.patch = tk.StringVar(value='')
        self.group = tk.StringVar(value='')
        self.review_note = tk.StringVar(value='')
        row = ttk.Frame(body); row.pack(fill='x', padx=18, pady=7)
        for label, var, choices, w in (
            ('출처', self.origin, ('game_screenshot', 'reviewed_game_video'), 24),
            ('서버', self.server, ('KR', 'JP'), 6)):
            ttk.Label(row, text=label).pack(side='left', padx=(5,3))
            ttk.Combobox(row, textvariable=var, values=choices, state='readonly', width=w).pack(side='left', padx=(0, 16))
        ttk.Label(row, text='패치 버전 (필수)').pack(side='left', padx=5)
        ttk.Entry(row, textvariable=self.patch, width=30).pack(side='left', padx=5)
        row2 = ttk.Frame(body); row2.pack(fill='x', padx=18, pady=7)
        ttk.Label(row2, text='같은 영상·출처 그룹 ID', width=26).pack(side='left')
        ttk.Entry(row2, textvariable=self.group, width=35).pack(side='left', padx=5)
        ttk.Label(row2, text='검수 사유', width=10).pack(side='left')
        ttk.Entry(row2, textvariable=self.review_note, width=52).pack(side='left', fill='x', expand=True, padx=5)
        ttk.Label(body, text='동일 영상은 같은 그룹 ID를 사용하세요. 서버·패치가 다른 기록을 섞거나 증거 이미지를 수정하면 내보내기에서 제외합니다.',
                  style='Muted.TLabel', wraplength=950).pack(anchor='w', padx=18, pady=(4, 9))
        row3 = ttk.Frame(body);row3.pack(fill='x', padx=18, pady=8)
        ttk.Button(row3, text='선택한 턴 검수 등록', style='Accent.TButton', command=self.verify).pack(side='left', padx=(0,9))
        ttk.Button(row3, text='전체 자료 감사', command=self.audit).pack(side='left', padx=9)
        ttk.Button(row3, text='학습 후보 JSONL 내보내기', command=self.export).pack(side='left', padx=9)
        self.log = tk.Text(body, height=16, bg='#192438', fg='#F3F6FB', insertbackground='white', wrap='word', relief='flat')
        self.log.pack(fill='both', expand=True, padx=18, pady=12)
        self._set_log(f'검수 데이터베이스: {review_db_path()}\n실제 게임 검수 전에는 학습 후보 수 0건이 정상입니다.')
        self.reload_runs()

    def select_file(self, var):
        path = filedialog.askopenfilename(filetypes=[('Screenshots','*.png *.jpg *.jpeg *.webp')])
        if path: var.set(path)

    def reload_runs(self):
        self.run_map = {}
        for r in list_runs(self.runs_db):
            p = r['profile']
            label = f"#{r['id']} | {p.get('character') or '캐릭터 미입력'} | {p.get('scenario','')} | {r['turn_count']}턴"
            self.run_map[label] = r['id']
        self.run_cb['values'] = list(self.run_map)
        if self.run_map:
            self.var_run.set(next(iter(self.run_map)))
        else:
            self.var_run.set('')
        self.reload_turns()

    def reload_turns(self):
        run_id = self.run_map.get(self.var_run.get())
        self.turn_map = {}
        if run_id is not None:
            for t in list_turns(self.runs_db, run_id):
                label = f"#{t['id']} | {t['state'].get('turn_label','미확인')} | 선택: {t['chosen_action']}"
                self.turn_map[label] = t['id']
        self.turn_cb['values'] = list(self.turn_map)
        self.var_turn.set(next(iter(self.turn_map), ''))
        self.preview_turn()

    def preview_turn(self):
        run_id, turn_id = self.run_map.get(self.var_run.get()), self.turn_map.get(self.var_turn.get())
        if run_id is None or turn_id is None:
            self.preview_var.set('저장된 턴이 없습니다. 먼저 ② 턴에서 실제 행동을 기록하세요.')
            return
        turn = next(x for x in list_turns(self.runs_db, run_id) if x['id']==turn_id)
        self.preview_var.set(f"선택: {turn['chosen_action']} | 턴: {turn['state'].get('turn_label')} | 표시된 수치가 실제 게임 화면과 같은지 증거와 비교해야 합니다.")

    def _current_ids(self):
        a, b = self.run_map.get(self.var_run.get()), self.turn_map.get(self.var_turn.get())
        if a is None or b is None: raise ValueError('검수할 육성과 턴을 선택하세요.')
        return a, b

    def verify(self):
        try:
            a, b = self._current_ids()
            verify_turn(self.runs_db, self.reviews_db,
                        run_id=a, turn_id=b, before=self.before.get(), after=self.after.get(),
                        origin=self.origin.get(), server=self.server.get(), patch_version=self.patch.get(),
                        provenance_group=self.group.get(), reviewer_note=self.review_note.get())
            self.audit()
            messagebox.showinfo('R15', '검수 등록 완료. 학습 후보는 전체 자료 감사 후 확정됩니다.')
        except Exception as exc: messagebox.showerror('R15 검수 실패', str(exc))

    def _set_log(self, message):
        self.log.delete('1.0', 'end')
        self.log.insert('1.0', message)

    def audit(self):
        try:
            result = audit_and_collect(self.runs_db, self.reviews_db)
            s = result['summary']
            lines = [f"검수 등록: {s['reviewed_rows']}건", f"내보내기 가능: {s['exportable_rows']}턴",
                     f"증거 변경·데이터 오류로 제외: {s['excluded_rows']}건", f"독립 출처 그룹: {s['independent_source_groups']}개",
                     f"학습 준비 통과: {'예' if s['training_ready_gate'] else '아니오'}", s['gate_note'],
                     '실제 ML 학습: 수행하지 않음', '', '분할 결과 (육성·영상 출처별 완전 분리):']
            lines += [f"  {k}: {v['rows']}턴 / {v['groups']}그룹" for k,v in s['splits'].items()]
            lines += ['', '제외 사유:']
            lines += [f"  육성 {x.get('run_id','?')}, 턴 {x.get('turn_id','?')}: {x['reason']}" for x in result['excluded'][:30]] or ['  없음']
            self._set_log('\n'.join(lines))
        except Exception as exc: messagebox.showerror('R15 감사 실패', str(exc))

    def export(self):
        location = filedialog.askdirectory(title='R15 검수된 학습 후보 자료를 저장할 폴더')
        if not location: return
        try:
            summary = export_training_pack(self.runs_db, self.reviews_db, Path(location))
            self.audit()
            messagebox.showinfo('R15', f"JSONL 내보내기 완료: {summary['exportable_rows']}턴\n학습 모델은 생성되지 않았습니다.")
        except Exception as exc: messagebox.showerror('R15 내보내기 실패', str(exc))

    def destroy(self):
        self.reviews_db.close()
        super().destroy()
