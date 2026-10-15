"""R10 provenance-driven local research work queue. No video downloads."""
from __future__ import annotations
import json
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from research.review_tools.annotation_core import DEFAULT_OUTPUT
from review_pipeline_r10 import (build_worklist, apply_progress, audit_worklist,
    update_progress, export_r9_verified, _atomic_csv, PROGRESS_JSON)


class ReviewQueuePanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows=[]
        self.progress_path=PROGRESS_JSON
        self.annotation_path=DEFAULT_OUTPUT
        self._build()
        self.refresh()

    def _build(self):
        frame=ttk.Frame(self)
        frame.pack(fill='both', expand=True, padx=18, pady=12)
        ttk.Label(frame, text='R10 · 일본 수정 후 영상 검수 작업 관리',style='Section.TLabel').pack(anchor='w', pady=(0,5))
        ttk.Label(frame, text='영상은 직접 확보하거나 허가된 로컬 영상만 검수합니다. 설명·챕터는 실제 육성 턴 근거가 아닙니다.',
                  style='Muted.TLabel', wraplength=1050).pack(anchor='w', pady=(0,8))
        cmds=ttk.Frame(frame); cmds.pack(fill='x',pady=(0,9))
        for title, func in [('작업 목록 새로고침',self.refresh),('출처 영상 열기',self.open_video),
                            ('검수 중으로 표시',self.in_review),('보류 처리',self.block),
                            ('완료 증거 연결',self.mark_verified),('검수 목록 CSV 저장',self.save_queue)]:
            ttk.Button(cmds,text=title,command=func).pack(side='left',padx=(0,5))
        info=ttk.Frame(frame);info.pack(fill='x',pady=(0,7))
        ttk.Label(info,text='R2 검수 턴 CSV:',style='Muted.TLabel').pack(side='left')
        self.annotation_label=tk.StringVar(value=str(self.annotation_path))
        ttk.Label(info,textvariable=self.annotation_label,style='Muted.TLabel').pack(side='left',padx=8)
        ttk.Button(info,text='다른 검수 CSV',command=self.set_annotations).pack(side='left',padx=8)
        self.status=tk.StringVar(value='출처·프레임을 직접 검수한 뒤 완료 처리할 수 있습니다.')
        ttk.Label(frame,textvariable=self.status,style='Muted.TLabel',wraplength=1100).pack(anchor='w',pady=(0,6))
        wrap=ttk.Frame(frame);wrap.pack(fill='both',expand=True)
        keys=('task','priority','source','purpose','timestamp','status')
        self.tree=ttk.Treeview(wrap,columns=keys,show='headings',height=7,selectmode='browse')
        labels=[('task','작업 ID',145),('priority','우선',52),('source','영상 주제',290),
                ('purpose','기본 구분',125),('timestamp','시점',90),('status','상태',115)]
        for k,title,width in labels:
            self.tree.heading(k,text=title)
            self.tree.column(k,width=width,stretch=k in ('task','source'))
        self.tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(wrap,orient='vertical',command=self.tree.yview)
        scroll.pack(side='right',fill='y'); self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>',lambda e:self.show_detail())
        ttk.Label(frame,text='작업 설명 / 증거 연결 정보',style='Section.TLabel').pack(anchor='w',pady=(12,3))
        self.detail=tk.Text(frame,height=5,bg='#192438',fg='#F3F6FB',wrap='word',relief='flat',padx=10,pady=8)
        self.detail.pack(fill='x')
        lower=ttk.Frame(frame);lower.pack(fill='x',pady=7)
        ttk.Button(lower,text='R9 근거 CSV 변환 (수동 검수 JSON 필요)',command=self.convert).pack(side='left')
        ttk.Label(lower,text='미검수·가상·인자작 데이터는 R9로 전송하지 않습니다.',style='Muted.TLabel').pack(side='left',padx=14)

    def refresh(self):
        try:
            self.rows=apply_progress(build_worklist(), self.progress_path,self.annotation_path)
        except (OSError,ValueError,KeyError) as exc:
            self.status.set('검수 자료 로딩 실패: '+str(exc));return
        self.tree.delete(*self.tree.get_children())
        for i,r in enumerate(self.rows):
            stamp='챕터 미지정' if r['video_seconds']==-1 else str(r['video_seconds'])+'초'
            self.tree.insert('','end',iid=str(i),values=(r['task_id'],r['priority'],
                r['source_title'][:26],r['suggested_purpose'],stamp,r['status']))
        audit=audit_worklist(self.rows)
        self.status.set(f"작업 {audit['tasks']}건 / 완료 증거 {audit['reviewed_with_before_after']}건 · 전체 영상 자동 다운로드 0건 · 학습 모델 없음")
        if self.rows:self.tree.selection_set('0');self.show_detail()

    def selected(self):
        selected=self.tree.selection()
        return self.rows[int(selected[0])] if selected else None

    def show_detail(self):
        r=self.selected()
        if not r:return
        lines=[f"출처: {r['source_id']} · {r['source_title']}",
               f"검수 지점: {r['review_topic']}",f"영상: {r['source_url']}",
               f"대회 구분: {r['scope']} → {r['suggested_purpose']} (실제 육성 목적은 화면 확인 필수)",
               f"원본 자료 깊이: {r['source_checked_depth']}",
               f"상태: {r['status']} | 연결된 근거: {r['annotation_id'] or '없음'}",
               f"메모: {r['note']}",
               '※ 업로더의 선택은 최적 행동의 정답이 아닙니다.']
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0','\n'.join(lines));self.detail.configure(state='disabled')

    def open_video(self):
        r=self.selected()
        if r:webbrowser.open(r['source_url'])

    def set_annotations(self):
        p=filedialog.askopenfilename(title='검수된 R2 턴 CSV 선택',filetypes=[('CSV','*.csv')])
        if p:self.annotation_path=Path(p);self.annotation_label.set(p);self.refresh()

    def _mark(self,status):
        r=self.selected()
        if not r:return
        if status=='verified':
            import tkinter.simpledialog as simpledialog
            aid=simpledialog.askstring('검수 증거 연결','R2 verified_turns.csv의 annotation_id를 정확히 입력하세요.',parent=self)
            if not aid:return
        else:aid=''
        import tkinter.simpledialog as simpledialog
        comment=simpledialog.askstring('검수 진행 메모','사유 또는 다음 작업 (선택)',parent=self)
        if comment is None:return
        try:
            update_progress(r['task_id'],status,annotation_id=aid,note=comment,
                progress_path=self.progress_path,annotation_path=self.annotation_path,
                worklist=self.rows)
            self.refresh()
        except (ValueError,OSError,KeyError) as e:
            messagebox.showerror('진행 상태 변경 불가',str(e))

    def in_review(self):self._mark('in_review')
    def block(self):self._mark('blocked')
    def mark_verified(self):self._mark('verified')

    def save_queue(self):
        p=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='R10_영상검수작업표.csv',filetypes=[('CSV','*.csv')])
        if not p:return
        try:
            self.refresh()
            _atomic_csv(Path(p),tuple(self.rows[0]) if self.rows else (),self.rows)
            self.status.set('작업 목록 저장: '+p)
        except (ValueError,OSError) as e:messagebox.showerror('저장 실패',str(e))

    def convert(self):
        source=filedialog.askopenfilename(title='수동 화면 검증 JSON 배열',filetypes=[('JSON','*.json')])
        if not source:return
        out=filedialog.asksaveasfilename(title='R9 검수 상승량 CSV',defaultextension='.csv',
                   initialfile='r10_to_r9_checked.csv',filetypes=[('CSV','*.csv')])
        if not out:return
        try:
            result=export_r9_verified(self.annotation_path,Path(source),Path(out))
            report=Path(out).with_suffix('.audit.json')
            report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            messagebox.showinfo('R9 데이터 변환 결과',f"승인 {result['accepted']}건 / 제외 {len(result['rejected'])}건\n감사기록: {report}")
            self.status.set(f"R9 변환 완료: 검수 {result['accepted']}건, 제외 {len(result['rejected'])}건")
        except (ValueError,OSError,KeyError) as e:messagebox.showerror('변환 불가',str(e))
