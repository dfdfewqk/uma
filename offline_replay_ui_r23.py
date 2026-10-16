"""R23 offline testing window. All screenshots stay on device; no game input."""
from __future__ import annotations

# Validate a packaged EXE before importing tkinter or any GUI-heavy modules.
import sys as _uma_startup_sys
if __name__ == '__main__' and '--self-check-report' in _uma_startup_sys.argv[1:]:
    from package_selftest_r25 import maybe_run_cli as _uma_early_selfcheck
    _uma_early_selfcheck('UmaTrainerKR_Preflight')
import json
import os
import sys
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

from offline_replay_r23 import demo_manifest, load_manifest, replay, ReplayError, create_manifest, file_sha256
from capture_integrity_r24 import read_pinned_image
from screen_r4 import load_image, user_dir
from preflight_r23 import inspect_local_environment, explain
from live_training_r22 import TrainingCaptureSession, CaptureError
from training_r5 import FIELDS
from uma_core import RunProfile,TurnState,STATS

BG='#101827';PANEL='#1B2C44';FG='#EFF5FF';MUTED='#ABBDD2';TEAL='#75E1C6';YELLOW='#FFE0A2'

class OfflineReplayApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Uma Trainer KR · R23 오프라인 실게임 사전점검')
        self.geometry('1190x815');self.minsize(1060,670)
        self.configure(bg=BG)
        self.manifest=None;self.result=None;self.metadata=None
        self.images={};self.pinned={};self.manifest_proof=None;self.session=None;self.selected_choice=None;self.photo=None
        self.running=False
        self.current_status=tk.StringVar(value='게임 없이 합성 샘플을 검사하거나, 실제 캡처의 R23 목록을 선택하세요.')
        self.energy=tk.StringVar(value='');self.tickets=tk.StringVar(value='0')
        self.distance=tk.StringVar(value='중거리');self.style=tk.StringVar(value='선행')
        self.choice=tk.StringVar(value='스피드')
        self.inputs={name:tk.StringVar(value='') for name in FIELDS}
        self._build()

    def button(self,p,t,fun):
        return tk.Button(p,text=t,command=fun,bg='#255475',fg='white',activebackground='#396784',relief='flat',padx=10,pady=6)

    def _build(self):
        top=tk.Frame(self,bg=BG,padx=15,pady=12);top.pack(fill='x')
        tk.Label(top,text='R23 · 오프라인 리플레이 / Windows 첫 실행 준비',font=('Malgun Gothic',16,'bold'),fg=FG,bg=BG).pack(anchor='w')
        tk.Label(top,text='화면 자동 클릭 없음 · OCR 후보는 사용자가 확인 · 분석용 파일은 로컬에서만 처리',font=('Malgun Gothic',9),fg=TEAL,bg=BG).pack(anchor='w',pady=(3,0))
        bar=tk.Frame(self,bg=BG,padx=13);bar.pack(fill='x')
        self.button(bar,'1. 합성 샘플 사전점검',lambda:self.run_manifest(demo_manifest())).pack(side='left',padx=(0,7))
        self.button(bar,'2. 실제 캡처 목록 열기',self.open_manifest).pack(side='left',padx=4)
        self.button(bar,'실제 캡처 5장 묶기',self.prepare_local_captures).pack(side='left',padx=4)
        self.button(bar,'PC 연결 환경 점검',self.environment_test).pack(side='left',padx=4)
        self.button(bar,'진단 JSON 저장',self.export).pack(side='right')
        tk.Label(self,textvariable=self.current_status,bg=BG,fg=YELLOW,anchor='w',wraplength=1120).pack(fill='x',padx=15,pady=7)
        split=tk.PanedWindow(self,orient='horizontal',sashwidth=6,relief='flat',bg=BG);split.pack(fill='both',expand=True,padx=12,pady=8)
        left=tk.Frame(split,bg=PANEL,padx=9,pady=7);split.add(left,minsize=585)
        right=tk.Frame(split,bg=PANEL,padx=10,pady=8);split.add(right,minsize=430)
        tk.Label(left,text='검사 이미지 / OCR 후보',bg=PANEL,fg=TEAL,font=('Malgun Gothic',11,'bold')).pack(anchor='w')
        self.canvas=tk.Canvas(left,bg='#08101D',highlightthickness=0,height=330);self.canvas.pack(fill='both',expand=True,pady=(6,8))
        self.canvas.bind('<Configure>',lambda e:self.show_picture())
        self.table=ttk.Treeview(left,columns=('state','missing','review'),show='tree headings',height=7,selectmode='browse')
        self.table.heading('#0',text='훈련 선택지');self.table.column('#0',width=125,stretch=False)
        for key,caption,w in [('state','OCR',120),('missing','미확인 항목',115),('review','사용자 검수',110)]:
            self.table.heading(key,text=caption);self.table.column(key,width=w,anchor='center')
        self.table.pack(fill='x');self.table.bind('<<TreeviewSelect>>',self.choose_row)
        tk.Label(left,text='화면 아래 숫자 표시는 확인 전 OCR 후보입니다. 게임 결과나 정답이 아닙니다.',fg=MUTED,bg=PANEL,wraplength=550,justify='left').pack(anchor='w',pady=5)
        outer=tk.Canvas(right,bg=PANEL,highlightthickness=0)
        sb=ttk.Scrollbar(right,orient='vertical',command=outer.yview);outer.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');outer.pack(side='left',fill='both',expand=True)
        body=tk.Frame(outer,bg=PANEL,padx=3)
        win=outer.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e:outer.configure(scrollregion=outer.bbox('all')))
        outer.bind('<Configure>',lambda e:outer.itemconfigure(win,width=e.width))
        self._heading(body,'① 현재 이미지의 수치 직접 확인')
        tk.Label(body,text='후보값은 자동 확정하지 않습니다. 게임 이미지와 숫자를 비교한 뒤 검수 완료를 누르세요.',
                 wraplength=350,justify='left',fg=MUTED,bg=PANEL,font=('Malgun Gothic',9)).pack(anchor='w')
        grid=tk.Frame(body,bg=PANEL);grid.pack(fill='x',pady=5)
        for index,name in enumerate(FIELDS):
            row,col=divmod(index,2)
            f=tk.Frame(grid,bg=PANEL);f.grid(row=row,column=col,sticky='ew',padx=5,pady=3)
            tk.Label(f,text=name,fg=FG,bg=PANEL,font=('Malgun Gothic',8)).pack(anchor='w')
            ttk.Entry(f,textvariable=self.inputs[name],width=18).pack(fill='x')
        self.button(body,'OCR 후보를 입력칸에 복사 (검수 전)',self.copy_candidates).pack(fill='x',pady=(3,3))
        self.button(body,'눈으로 확인한 값 · 이 훈련 검수 완료',self.confirm_choice).pack(fill='x',pady=(0,8))
        self._heading(body,'② 훈련 5종 비교 (가정 기반 실험 점수)')
        for name,var in [('현재 체력 (직접 확인)',self.energy),('섬 티켓 (직접 확인)',self.tickets)]:
            line=tk.Frame(body,bg=PANEL);line.pack(fill='x',pady=3)
            tk.Label(line,text=name,bg=PANEL,fg=FG).pack(side='left')
            ttk.Entry(line,textvariable=var,width=12).pack(side='right')
        for name,var,options in [('거리',self.distance,['단거리','마일','중거리','장거리']),('각질',self.style,['도주','선행','선입','추입'])]:
            line=tk.Frame(body,bg=PANEL);line.pack(fill='x',pady=3)
            tk.Label(line,text=name,bg=PANEL,fg=FG).pack(side='left')
            ttk.Combobox(line,textvariable=var,values=options,state='readonly',width=16).pack(side='right')
        self.button(body,'확인한 5종만 비교하기',self.compare).pack(fill='x',pady=(10,5))
        self.result_text=tk.Text(body,wrap='word',bg='#101F34',fg=FG,height=10,relief='flat',font=('Malgun Gothic',9))
        self.result_text.pack(fill='x',pady=(3,8))
        self._display('OCR 결과를 직접 확인하기 전에는 추천하지 않습니다.\n데모 자료는 실제 게임 육성 데이터로 학습할 수 없습니다.')

    def _heading(self,body,title):
        tk.Label(body,text=title,bg=PANEL,fg=TEAL,font=('Malgun Gothic',11,'bold'),anchor='w').pack(fill='x',pady=(10,6))

    def _display(self,message):
        self.result_text.configure(state='normal');self.result_text.delete('1.0','end')
        self.result_text.insert('1.0',str(message));self.result_text.configure(state='disabled')

    def open_manifest(self):
        fp=filedialog.askopenfilename(title='R23_검수목록.json 선택',filetypes=[('JSON','*.json')])
        if fp:self.run_manifest(Path(fp))

    def prepare_local_captures(self):
        """Explicit user-selected screenshot COPY into a new local test folder."""
        target=filedialog.askdirectory(title='R23 검사 폴더를 저장할 상위 폴더 선택')
        if not target:return
        base=Path(target)
        dest=base/'UmaTrainerKR_R23_실게임점검'
        idx=1
        while dest.exists():
            dest=base/f'UmaTrainerKR_R23_실게임점검_{idx}'
            idx+=1
            if idx>100:
                messagebox.showerror('폴더 오류','사용 가능한 검사 폴더 이름이 없습니다.');return
        orig=user_dir()/'r22_training_preview_rois.json'
        if orig.is_file():
            roi=orig
        else:
            selected=filedialog.askopenfilename(title='R22에서 저장한 OCR 영역 JSON 선택',filetypes=[('JSON','*.json')])
            if not selected:return
            roi=Path(selected)
        from live_training_r22 import load_profile
        try:
            if not load_profile(roi):raise ValueError('OCR 설정이 없습니다.')
        except Exception as e:
            messagebox.showerror('OCR 설정 오류',str(e));return
        sources={}
        for choice in STATS:
            selected=filedialog.askopenfilename(title=f'{choice} 훈련을 누른 상태의 캡처 선택 (취소하면 중단)',
                          filetypes=[('Images','*.png *.jpg *.jpeg *.webp')])
            if not selected:return
            sources[choice]=Path(selected)
        if not messagebox.askyesno('캡처 로컬 복사',
           '직접 선택한 게임 캡처 5장과 OCR 영역을 새 폴더에 복사합니다. 인터넷으로 업로드하지 않습니다. 진행할까요?'):
            return
        try:
            dest.mkdir(parents=False,exist_ok=False)
            shutil.copyfile(roi,dest/'r22_training_preview_rois.json')
            capture_names={}
            for index,choice in enumerate(STATS,1):
                image=load_image(sources[choice])
                filename=f'training_{index}.png'
                image.save(dest/filename,format='PNG')
                capture_names[choice]=filename
            manifest=create_manifest(dest,source_type='local_unverified',turn='실제 캡처 · 턴 확인 필요',
                captures=capture_names,roi_profile='r22_training_preview_rois.json')
            self.run_manifest(manifest)
        except Exception as exc:
            messagebox.showerror('검사 폴더 준비 실패',str(exc))

    def run_manifest(self,path):
        if self.running:return
        try:
            doc=load_manifest(path)
        except Exception as e:
            messagebox.showerror('목록 오류',str(e));return
        self.manifest=Path(path);self.metadata=doc['metadata']
        self.session=TrainingCaptureSession(self.metadata['turn'])
        self.images={choice:fp for choice,fp,_ in doc['captures']}
        self.pinned={choice:digest for choice,_,digest in doc['captures']}
        self.manifest_proof=(doc['manifest_sha256'],doc['roi_path'],doc['roi_sha256'])
        self.result=None;self.selected_choice=None
        for k in self.inputs:self.inputs[k].set('')
        for k in self.table.get_children():self.table.delete(k)
        self.canvas.delete('all')
        self.current_status.set('이미지 무결성 통과 · OCR 실행 중 · 게임 화면과는 연결하지 않습니다.')
        self.running=True
        threading.Thread(target=self._work,args=(path,),daemon=True).start()

    def _verified_image(self,choice):
        if not self.manifest or not self.manifest_proof:
            raise ReplayError('검수 목록이 없습니다.')
        manifest_hash,roi_path,roi_hash=self.manifest_proof
        if file_sha256(self.manifest)!=manifest_hash or file_sha256(roi_path)!=roi_hash:
            raise ReplayError('검수 중 목록 또는 OCR 위치 설정이 변경됐습니다. 다시 불러오세요.')
        return read_pinned_image(self.images[choice],self.pinned[choice])

    def _check_all_proofs(self):
        for choice in self.pinned:
            self._verified_image(choice)

    def _work(self,path):
        try:result=replay(path)
        except Exception as e:result=e
        self.after(0,lambda:self._finish(result))

    def _finish(self,result):
        self.running=False
        if isinstance(result,Exception):
            self.current_status.set('검사 실패: '+str(result))
            return
        self.result=result
        for item in result.findings:
            ok=len(item.candidates)-len(item.missing)
            self.table.insert('', 'end',iid=item.choice,text=item.choice,
                              values=(f'{ok}/{len(item.candidates)} 후보',len(item.missing),'미확인'))
        self.current_status.set(f'{result.status} · {len(result.findings)}개 이미지 · 실제 검증 턴 0건')
        self._display('\n'.join(result.warnings+['검수 대상 행을 클릭해 이미지를 확인하세요.']))
        if result.findings:self.table.selection_set(result.findings[0].choice)

    def choose_row(self,e=None):
        selection=self.table.selection()
        if not selection or not self.result:return
        self.selected_choice=selection[0]
        for k in self.inputs:self.inputs[k].set('')
        self.show_picture()
        f=next((x for x in self.result.findings if x.choice==self.selected_choice),None)
        if f:
            self._display(f'{f.choice}: OCR 후보 {sum(v.get("candidate") is not None for v in f.candidates.values())}/{len(f.candidates)}개.\n'
                 '이미지를 확인하고 OCR 후보를 복사하거나 직접 입력하세요.\n'+ '\n'.join(f'{k}: {v.get("candidate") if v.get("candidate") is not None else "읽기 실패"} (확신도 {v.get("confidence")})' for k,v in f.candidates.items()))

    def show_picture(self):
        self.canvas.delete('all')
        if not self.selected_choice or self.selected_choice not in self.images:return
        try:
            im=self._verified_image(self.selected_choice)
            w=max(self.canvas.winfo_width()-15,100);h=max(self.canvas.winfo_height()-15,100)
            im.thumbnail((w,h))
            self.photo=ImageTk.PhotoImage(im)
            self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)
        except Exception as exc:
            self.canvas.create_text(10,10,text='이미지를 표시할 수 없습니다: '+str(exc),anchor='nw',fill='white')

    def copy_candidates(self):
        if not self.result or not self.selected_choice:return
        finding=next((f for f in self.result.findings if f.choice==self.selected_choice),None)
        if not finding:return
        try:self._verified_image(self.selected_choice)
        except (ValueError,OSError) as exc:
            self.current_status.set(str(exc));return
        for k,v in finding.candidates.items():
            if k in self.inputs and v.get('candidate') is not None:self.inputs[k].set(str(v['candidate']))
        self.current_status.set('OCR 후보를 입력칸에만 복사했습니다. 사진 확인 후 검수 완료를 누르세요.')

    def confirm_choice(self):
        if not self.session or not self.selected_choice:return
        try:
            im=self._verified_image(self.selected_choice)
            digest=self.session.register_capture(self.selected_choice,im)
            vals={k:v.get() for k,v in self.inputs.items() if v.get().strip()}
            self.session.confirm(self.selected_choice,vals,digest)
            self.table.set(self.selected_choice,'review','사용자 확인')
            self.current_status.set(self.selected_choice+' 검수 완료. 게임 내 최적 선택임을 뜻하지 않습니다.')
        except Exception as exc:
            messagebox.showwarning('검수 보류',str(exc))

    def compare(self):
        if not self.session:return
        try:
            self._check_all_proofs()
            if not self.energy.get().strip():raise ValueError('현재 체력을 입력하세요.')
            energy=int(self.energy.get());tickets=int(self.tickets.get())
            if not 0<=energy<=100 or not 0<=tickets<=3:
                raise ValueError('체력(0~100), 티켓(0~3) 값이 잘못되었습니다.')
            state=TurnState(turn_label=self.session.turn_id,energy=energy,island_tickets=tickets)
            run=RunProfile(distance=self.distance.get(),style=self.style.get())
            comparison=self.session.compare(run,state)
            if comparison.missing:
                text='비교 보류 · 미확인 훈련/항목이 있습니다.\n'+'\n'.join(k+': '+', '.join(v) for k,v in comparison.missing.items())
            else:
                text=comparison.status+'\n'+'\n'.join(f'{i+1}. {r.name}: 실험점수 {r.score:.1f}' for i,r in enumerate(comparison.ranked))
                text+='\n\n훈련 5종끼리만 비교합니다. 게임 최적 행동, ML 예측, 승률이 아닙니다.'
                if self.metadata['source_type']=='synthetic_test':text+='\n합성 예시만으로 계산한 결과입니다.'
            self._display(text)
        except Exception as exc:messagebox.showwarning('비교 보류',str(exc))

    def environment_test(self):
        try:
            preflight=inspect_local_environment()
            self._display('R23 첫 실행 환경 점검\n\n'+'\n'.join(explain(preflight)))
            self.current_status.set('환경 점검 완료 · 한국 서버 연동을 검증한 결과는 아닙니다.')
        except Exception as exc:
            messagebox.showwarning('환경 점검 불가',str(exc))

    def export(self):
        if not self.result:return
        dest=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],initialfile='UmaTrainerKR_R23_진단.json')
        if not dest:return
        path=Path(dest)
        if path.exists():
            messagebox.showwarning('이미 있음','기존 파일은 덮어쓰지 않습니다. 새 이름으로 저장하세요.');return
        try:self._check_all_proofs()
        except (ValueError,OSError) as exc:
            messagebox.showwarning('진단 저장 보류',str(exc));return
        payload=self.result.public_json()
        payload['reviewed_choices']=list(self.session.options) if self.session else []
        payload['test_environment']='offline_only'
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
        self.current_status.set('진단 저장 완료 · 원본 이미지/컴퓨터 경로 제외: '+path.name)

if __name__=='__main__':
    from package_selftest_r25 import maybe_run_cli
    maybe_run_cli("UmaTrainerKR_Preflight")
    OfflineReplayApp().mainloop()
