"""R9 independent-run evidence audit and conservative empirical estimate UI."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import hashlib
from collections import Counter
from calibration_r9 import audit_csv, empty_template, estimate_from_samples, atomic_export_json


class CalibrationPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.audit = None
        self._last_estimate = None
        self._checksum = None
        self.file_path = tk.StringVar(value='')
        self._build()

    def _build(self):
        container = ttk.Frame(self)
        container.pack(fill='both', expand=True, padx=18, pady=14)
        ttk.Label(container, text='R9 · 수정 후 무인도 실측 근거 감사 / 동일조건 비교',
                  style='Section.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(container, text='원본 프레임 해시·서버·패치·챔미/리오히·시설·우정·서포트 편성을 확인합니다. '
                  '실제 검수된 턴이 충분하지 않으면 추정값을 표시하지 않습니다.',
                  style='Muted.TLabel', wraplength=1040).pack(anchor='w', pady=(0, 12))
        row = ttk.Frame(container)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.file_path).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='검수 CSV 선택', command=self.pick).pack(side='left', padx=4)
        ttk.Button(row, text='빈 입력 양식 저장', command=self.template).pack(side='left')
        row2 = ttk.Frame(container)
        row2.pack(fill='x', pady=(11, 8))
        ttk.Button(row2, text='자료 감사·품질 검사', style='Accent.TButton', command=self.audit_data).pack(side='left')
        ttk.Button(row2, text='선택 표본의 동일조건 비교', command=self.inspect_selected).pack(side='left', padx=8)
        ttk.Button(row2, text='감사 보고 JSON 저장', command=self.save_report).pack(side='left')
        self.status = tk.StringVar(value='아직 실제로 검수된 표본을 불러오지 않았습니다. 학습된 ML 모델 없음.')
        ttk.Label(container, textvariable=self.status, style='Muted.TLabel', wraplength=1020).pack(anchor='w', pady=6)
        grid = ttk.Frame(container)
        grid.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(grid, columns=('sid', 'run', 'server', 'purpose', 'phase', 'train', 'date'),
                                 show='headings', height=8)
        cols = [('sid', '표본 ID', 110), ('run', '육성 ID', 120), ('server', '서버', 65),
                ('purpose', '대회', 130), ('phase', '시기', 125),
                ('train', '훈련', 100), ('date', '검수 날짜', 100)]
        for key, title, width in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key in ('sid', 'run', 'phase'))
        self.tree.pack(side='left', fill='both', expand=True)
        bar = ttk.Scrollbar(grid, orient='vertical', command=self.tree.yview)
        bar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=bar.set)
        self.detail = tk.Text(container, bg='#192438', fg='#F3F6FB', height=15,
                              font=('맑은 고딕',10), wrap='word', padx=12, pady=10, relief='flat')
        self.detail.pack(fill='x', pady=(12, 3))
        self._detail('R2에서 준비한 영상 검수 도구로 원본·패치·턴 근거를 확인한 뒤 '
                     'R9 CSV 양식으로 옮겨야 합니다.\n검수 전 자료·가상 수치·수정 이전 일본 공략은 예측 계산에 쓰지 않습니다.')

    def _detail(self, value):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', value)
        self.detail.configure(state='disabled')

    def pick(self):
        selected = filedialog.askopenfilename(title='R9 실측 데이터 CSV',
                                              filetypes=[('CSV', '*.csv')])
        if selected:
            self.file_path.set(selected)
            self.audit = None
            self._last_estimate = None
            self._checksum = None
            self.tree.delete(*self.tree.get_children())
            self.status.set('새 파일 선택됨: 품질 검사가 필요합니다.')

    def template(self):
        selected = filedialog.asksaveasfilename(title='R9 빈 입력 CSV 양식 저장',
                        defaultextension='.csv', initialfile='r9_verified_turns_blank.csv',
                        filetypes=[('CSV', '*.csv')])
        if selected:
            try:
                if Path(selected).exists() and Path(selected).stat().st_size > 0:
                    if not messagebox.askyesno('덮어쓰기 확인', '기존 자료가 존재합니다. 빈 양식으로 덮어쓸까요?'):
                        return
                empty_template(Path(selected))
                self.status.set(f'빈 양식 저장: {selected}')
            except OSError as exc:
                messagebox.showerror('양식 저장 실패', str(exc))

    def audit_data(self):
        self.audit = None
        self._last_estimate = None
        self._checksum = None
        self.tree.delete(*self.tree.get_children())
        path = Path(self.file_path.get())
        try:
            audit = audit_csv(path)
        except (ValueError, OSError) as exc:
            self.status.set('검수 실패 · 형식이나 파일을 확인하세요.')
            self._detail(str(exc))
            return
        self.audit = audit
        self._checksum = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''
        for i, r in enumerate(audit.observations):
            self.tree.insert('', 'end', iid=str(i), values=(r['sample_id'], r['run_id'],
                r['server'], r['purpose'], r['phase'], r['training'], r['captured_date']))
        grouped = Counter((r['server'], r['purpose']) for r in audit.observations)
        lines = [f'전체 {audit.total_rows}행 / 검수 통과 {audit.accepted}행 / 제외 {audit.rejected}행 / 중복 {audit.duplicate}행',
                 '서버·대회별 독립 표본:']
        lines.extend(f'  {server} / {purpose}: {count}개' for (server, purpose), count in sorted(grouped.items()))
        if not grouped:
            lines.append('  실제 표본 없음: 실험 예측 및 ML 학습 보류')
        if audit.rejected_reasons:
            lines.extend(['', '[오류/불일치 (최대 50행)]', *audit.rejected_reasons])
        self._detail('\n'.join(lines))
        self.status.set(f'자료 감사 완료: 검수 실측 {audit.accepted}건, 제외 {audit.rejected}건 · 모델 학습 없음')

    def inspect_selected(self):
        if self.audit is None or not self.tree.selection():
            self.status.set('자료 감사 후 비교할 실제 검수 표본을 선택하세요.')
            return
        r = self.audit.observations[int(self.tree.selection()[0])]
        est = estimate_from_samples(self.audit.observations, r)
        self._last_estimate = est
        lines = [f'선택: {r["sample_id"]} ({r["run_id"]}) · {r["training"]}',
                 f'판단: {est.status}',
                 f'엄격한 동일조건 비교: {est.compared_samples}건 / 서로 다른 육성 {est.distinct_runs}회',
                 f'최소 기준: 10개 표본, 8개 독립 육성 (선택한 육성의 기록 제외)', '']
        if est.stat_intervals:
            names = dict(zip(('g_speed','g_stamina','g_power','g_guts','g_wisdom'),
                             ('스피드','스태미나','파워','근성','지능')))
            for key, summary in est.stat_intervals.items():
                lines.append(f'{names[key]}: 중앙값 {summary["median"]} / 관측범위 p10 {summary["p10"]}~p90 {summary["p90"]} / 육성단위 검증오차 {est.leave_one_run_out_mae[key]}')
            lines.append('스킬 Pt: ' + str(est.skill_points))
        lines += ['', '※ '+est.caution,
                  '※ 불확실한 보너스 공식·실전 승률·도축 정답을 학습했다고 주장하지 않습니다.']
        self._detail('\n'.join(lines))
        self.status.set(est.status)

    def save_report(self):
        if self.audit is None:
            messagebox.showwarning('분석 없음', '먼저 자료 품질 감사를 실행하세요.')
            return
        path = filedialog.asksaveasfilename(title='R9 품질 감사 보고서 저장',
                    defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                # Reject stale CSV instead of pretending the report matches latest file.
                latest = audit_csv(Path(self.file_path.get()))
                if (latest.observations != self.audit.observations or latest.rejected != self.audit.rejected
                        or hashlib.sha256(Path(self.file_path.get()).read_bytes()).hexdigest() != self._checksum):
                    raise ValueError('CSV가 감사 후 변경됐습니다. 자료 감사를 다시 실행하세요.')
                atomic_export_json(Path(path), self.audit,
                                   [self._last_estimate] if self._last_estimate else [])
                self.status.set(f'감사 보고서 저장: {path}')
            except (ValueError, OSError) as exc:
                messagebox.showerror('저장 불가', str(exc))
