"""R22 Windows live-game test workbench.

Run with UmaTrainerKR_GameTest.exe. Read-only screen capture, user-guided training
preview collection, OCR suggestions, manual evidence verification and comparison.
"""
from __future__ import annotations

# Validate a packaged EXE before importing tkinter or any GUI-heavy modules.
import sys as _uma_startup_sys
if __name__ == '__main__' and '--self-check-report' in _uma_startup_sys.argv[1:]:
    from package_selftest_r25 import maybe_run_cli as _uma_early_selfcheck
    _uma_early_selfcheck('UmaTrainerKR_GameTest')
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image,ImageTk,ImageGrab

from companion_core import choose_window
from companion_window import discover_windows
from screen_r4 import user_dir,load_image,tesseract_executable
from live_training_r22 import (TrainingCaptureSession,NumericProfile,FieldBox,
    SCREEN_FIELDS,profile_file,save_profile,load_profile,ocr_candidates,CaptureError)
from training_r5 import TRAINING_CHOICES,FIELDS
from uma_core import RunProfile,TurnState,STATS
from recommendation_bridge_r28 import create_handoff, save_handoff, cancel_handoff, HandoffError

BG='#101929'; PANEL='#1B2B43'; FG='#F0F6FF'; MUTED='#AFC1D5'; GOOD='#66E0C4'; HILITE='#FFCF76'

class LiveTest(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Uma Trainer KR · R22 실게임 연결/훈련 점검')
        self.geometry('1190x860');self.minsize(1050,690)
        self.configure(bg=BG)
        self.game=None;self.manual_window_id=None;self.image=None;self.image_digest=None;self.image_tk=None
        self.image_scale=1.;self.image_origin=(0,0)
        self.drag_start=None;self.drag_shape=None
        self.selected=tk.StringVar(value='스피드')
        self.calib_field=tk.StringVar(value=SCREEN_FIELDS[0])
        self.turn=tk.StringVar(value='주니어급 7월 전반')
        self.energy=tk.StringVar(value='80')
        self.tickets=tk.StringVar(value='0')
        self.remaining=tk.StringVar(value='48')
        self.distance=tk.StringVar(value='중거리')
        self.style=tk.StringVar(value='선행')
        self.event=tk.StringVar(value='챔피언스 미팅')
        self.status=tk.StringVar(value='게임 창을 연결하거나 스크린샷을 열어 테스트하세요.')
        self.progress=tk.StringVar(value='훈련 입력 0/5 · OCR 결과는 반드시 직접 검수')
        self.region_info=tk.StringVar(value='OCR 숫자 영역: 설정 전')
        self.profile=None;self.session=TrainingCaptureSession(self.turn.get())
        self.latest_report=None
        self.captured_choice=None
        self.inputs={name:tk.StringVar() for name in FIELDS}
        self._draw()
        try:
            self.profile=load_profile(profile_file())
            if self.profile:self.region_info.set('OCR 영역 '+str(len(self.profile.boxes))+'개 불러옴')
        except CaptureError as e:self.status.set('OCR 설정 오류: '+str(e))
        self.after(850,self.find_game)

    def _title(self,parent,text):
        tk.Label(parent,text=text,bg=parent['bg'],fg=GOOD,
                 font=('Malgun Gothic',11,'bold'),anchor='w').pack(fill='x',pady=(6,5))

    def _button(self,parent,label,callback):
        return tk.Button(parent,text=label,command=callback,bg='#254768',fg='white',relief='flat',
                         font=('Malgun Gothic',9),padx=6,pady=5)

    def _draw(self):
        head=tk.Frame(self,bg=BG,padx=10,pady=8);head.pack(fill='x')
        tk.Label(head,text='R22 · 우마무스메 실게임 테스트',fg=FG,bg=BG,font=('Malgun Gothic',16,'bold')).pack(side='left')
        self._button(head,'게임 창 직접 선택',self.select_game_window).pack(side='right',padx=4)
        self._button(head,'게임 창 다시 찾기',self.auto_find_game).pack(side='right',padx=4)
        self._button(head,'이미지 열기',self.open_picture).pack(side='right',padx=4)
        self._button(head,'현재 게임 화면 캡처',self.capture_game).pack(side='right',padx=4)
        tk.Label(self,textvariable=self.status,bg=BG,fg=HILITE,anchor='w',wraplength=1100,
                 font=('Malgun Gothic',10)).pack(fill='x',padx=15)
        main=tk.PanedWindow(self,orient='horizontal',bg=BG,sashwidth=7,relief='flat')
        main.pack(fill='both',expand=True,padx=9,pady=8)
        left=tk.Frame(main,bg=PANEL);main.add(left,minsize=610,stretch='always')
        right=tk.Frame(main,bg=PANEL,width=380);main.add(right,minsize=365)
        self._title(left,'게임 화면 (OCR 보정: 오른쪽에서 항목 선택 → 숫자 부분 드래그)')
        self.canvas=tk.Canvas(left,bg='#111111',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,padx=7,pady=7)
        self.canvas.bind('<ButtonPress-1>',self._start_roi)
        self.canvas.bind('<B1-Motion>',self._move_roi)
        self.canvas.bind('<ButtonRelease-1>',self._finish_roi)
        tk.Label(left,textvariable=self.region_info,fg=MUTED,bg=PANEL,font=('Malgun Gothic',9)).pack(anchor='w',padx=8,pady=(0,7))
        self.canvas.bind('<Configure>',lambda e:self._draw_image())
        inner_canvas=tk.Canvas(right,bg=PANEL,highlightthickness=0,width=370)
        sb=ttk.Scrollbar(right,orient='vertical',command=inner_canvas.yview)
        inner_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');inner_canvas.pack(side='left',fill='both',expand=True)
        content=tk.Frame(inner_canvas,bg=PANEL,padx=12,pady=6)
        window_id=inner_canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda e: inner_canvas.configure(scrollregion=inner_canvas.bbox('all')))
        inner_canvas.bind('<Configure>',lambda e:inner_canvas.itemconfigure(window_id,width=e.width))
        self._title(content,'① 훈련 버튼 선택 → 화면 캡처')
        ttk.Combobox(content,values=TRAINING_CHOICES,textvariable=self.selected,state='readonly').pack(fill='x')
        self._button(content,'이 훈련 화면 기록 (캡처는 상단 버튼)',self.capture_game).pack(fill='x',pady=5)
        tk.Label(content,text='게임에서 선택한 훈련 버튼과 여기의 훈련 이름을 일치시키세요.',bg=PANEL,fg=MUTED,
                 font=('Malgun Gothic',8),wraplength=320,justify='left').pack(anchor='w')
        self._title(content,'② 숫자 자동 인식 영역 등록')
        ttk.Combobox(content,values=SCREEN_FIELDS,textvariable=self.calib_field,state='readonly').pack(fill='x')
        self._button(content,'등록한 영역에서 숫자 OCR 후보 읽기',self.run_ocr).pack(fill='x',pady=5)
        tk.Label(content,text='OCR 미설치도 가능: 아래에 숫자를 직접 입력하세요. 체력 변화는 항상 확인 후 입력.',
                 bg=PANEL,fg=MUTED,wraplength=325,justify='left',font=('Malgun Gothic',8)).pack(anchor='w')
        self._title(content,'③ 이번 훈련 결과 검수')
        grid=tk.Frame(content,bg=PANEL);grid.pack(fill='x')
        for i,name in enumerate(FIELDS):
            row,col=divmod(i,2)
            unit=tk.Frame(grid,bg=PANEL)
            unit.grid(row=row,column=col,padx=(0,9),pady=3,sticky='ew')
            tk.Label(unit,text=name,bg=PANEL,fg=FG,anchor='w',font=('Malgun Gothic',8)).pack(anchor='w')
            ttk.Entry(unit,textvariable=self.inputs[name],width=16).pack(fill='x')
        self._button(content,'이 훈련 검수 완료',self.confirm_choice).pack(fill='x',pady=6)
        tk.Label(content,textvariable=self.progress,fg=GOOD,bg=PANEL,wraplength=330,justify='left').pack(anchor='w')
        self._title(content,'④ 현재 턴 정보와 비교')
        for label,var in [('턴 이름 (바뀌면 새 턴)',self.turn),('체력',self.energy),('남은 턴',self.remaining),('섬 티켓',self.tickets)]:
            r=tk.Frame(content,bg=PANEL);r.pack(fill='x',pady=2)
            tk.Label(r,text=label,bg=PANEL,fg=FG,width=18,anchor='w').pack(side='left')
            ttk.Entry(r,textvariable=var,width=13).pack(side='right')
        for name,variable,items in [('대회',self.event,['챔피언스 미팅','리그 오브 히어로즈']),
                                    ('거리',self.distance,['단거리','마일','중거리','장거리']),
                                    ('각질',self.style,['도주','선행','선입','추입'])]:
            r=tk.Frame(content,bg=PANEL);r.pack(fill='x',pady=2)
            tk.Label(r,text=name,bg=PANEL,fg=FG,width=12,anchor='w').pack(side='left')
            ttk.Combobox(r,values=items,textvariable=variable,state='readonly',width=18).pack(side='right')
        self._button(content,'검수된 훈련 비교',self.compare).pack(fill='x',pady=(10,3))
        self._button(content,'R28 · 이번 턴 추천을 게임 위에 표시',self.publish_to_companion).pack(fill='x',pady=3)
        self._button(content,'R28 · 화면 위 추천 취소',self.cancel_companion_hint).pack(fill='x',pady=3)
        self._button(content,'다음 턴 시작 (기록 초기화)',self.new_turn).pack(fill='x',pady=3)
        self._button(content,'현재 캡처 PNG 저장',self.save_screenshot).pack(fill='x',pady=3)
        self._button(content,'연결 환경 진단',self.diagnose).pack(fill='x',pady=3)
        self._button(content,'진단 기록 JSON 내보내기',self.export_report).pack(fill='x',pady=3)
        self.result=tk.Text(content,bg='#132139',fg=FG,wrap='word',height=11,
                            font=('Malgun Gothic',9),borderwidth=0)
        self.result.pack(fill='x',pady=(5,10))
        self._show('훈련 5종의 미확인 값은 0으로 취급하지 않습니다. 자동 클릭 기능은 아직 꺼져 있습니다.')

    def _show(self,text):
        self.result.configure(state='normal')
        self.result.delete('1.0','end');self.result.insert('1.0',str(text))
        self.result.configure(state='disabled')

    def auto_find_game(self):
        self.manual_window_id=None
        self.find_game()

    def find_game(self):
        try:
            windows=discover_windows()
            if self.manual_window_id is not None:
                selected=next((w for w in windows if w.hwnd==self.manual_window_id),None)
                if selected and selected.width>=500 and selected.height>=320:
                    self.game=selected
                    self.status.set('사용자가 지정한 창: '+selected.title[:65])
                    return
                self.manual_window_id=None
            game,msg=choose_window(windows)
            self.game=game
            self.status.set(msg+((' · '+game.title[:65]) if game else ''))
        except Exception as e:self.status.set('창 검색 오류: '+str(e))

    def select_game_window(self):
        if os.name!='nt':
            messagebox.showinfo('Windows 전용','게임 창 직접 선택은 Windows에서만 작동합니다.')
            return
        choices=[w for w in discover_windows() if w.width>=500 and w.height>=320
                 and 'uma trainer kr' not in w.title.lower() and 'r22 실게임' not in w.title.lower()]
        if not choices:
            messagebox.showwarning('목록 없음','선택할 수 있는 창이 없습니다. 게임을 먼저 실행하세요.')
            return
        dialog=tk.Toplevel(self);dialog.title('게임 창 선택');dialog.geometry('520x360')
        tk.Label(dialog,text='정확히 우마무스메 게임 창을 선택하세요. 브라우저나 다른 앱은 선택하지 마세요.').pack(padx=8,pady=8)
        listing=tk.Listbox(dialog,width=75,height=13)
        listing.pack(fill='both',expand=True,padx=10)
        for w in choices:listing.insert('end',f'{w.title[:62]}  ({w.width}x{w.height})')
        def choose():
            inds=listing.curselection()
            if not inds:return
            game=choices[inds[0]]
            self.manual_window_id=game.hwnd;self.game=game
            self.status.set('직접 선택한 게임 창: '+game.title)
            dialog.destroy()
        tk.Button(dialog,text='이 창 사용',command=choose).pack(pady=8)

    def _use_image(self,picture,window_id=None):
        if picture.width*picture.height>24_000_000:raise CaptureError('이미지가 너무 큽니다.')
        self.image=picture.convert('RGB')
        choice=self.selected.get()
        cancel_handoff()
        self.latest_report=None
        self.image_digest=self.session.register_capture(choice,self.image,window_id)
        self.captured_choice=choice
        for field in FIELDS:self.inputs[field].set('')
        self._draw_image()
        self.status.set(f'{choice}: {self.image.width}×{self.image.height} 화면 캡처 완료 · 수치는 검수 전')
        self._update_progress()

    def open_picture(self):
        name=filedialog.askopenfilename(title='게임 화면 PNG/JPG 불러오기',filetypes=[('Images','*.png *.jpg *.jpeg *.webp')])
        if not name:return
        try:self._use_image(load_image(Path(name)))
        except Exception as e:messagebox.showerror('이미지 오류',str(e))

    def capture_game(self):
        self.find_game()
        if not self.game:
            messagebox.showwarning('게임 창 없음','한국 서버 게임 창을 먼저 열어주세요. 이미지 열기로도 테스트할 수 있습니다.')
            return
        try:
            # Do not accidentally capture the test tool if it overlaps the game.
            self.withdraw()
            self.update_idletasks()
            time.sleep(.18)
            try:
                if os.name=='nt':
                    import ctypes
                    u=ctypes.windll.user32
                    if u.IsIconic(self.game.hwnd) or u.GetForegroundWindow()!=self.game.hwnd:
                        raise CaptureError('게임 창이 활성화되어 있지 않습니다. 다른 창이 게임 위에 있으면 캡처를 취소합니다.')
                picture=ImageGrab.grab(bbox=self.game.rect,all_screens=True)
            finally:
                self.deiconify()
                self.lift()
            self._use_image(picture,self.game.hwnd)
        except Exception as e:messagebox.showerror('캡처 오류',str(e))

    def _draw_image(self):
        if not self.image:return
        cw=max(50,self.canvas.winfo_width()-12);ch=max(50,self.canvas.winfo_height()-12)
        ratio=min(cw/self.image.width,ch/self.image.height,2.)
        self.image_scale=ratio
        w=max(1,round(self.image.width*ratio));h=max(1,round(self.image.height*ratio))
        self.image_origin=((self.canvas.winfo_width()-w)//2,(self.canvas.winfo_height()-h)//2)
        resized=self.image.resize((w,h),Image.Resampling.LANCZOS)
        self.image_tk=ImageTk.PhotoImage(resized)
        self.canvas.delete('all')
        self.canvas.create_image(*self.image_origin,anchor='nw',image=self.image_tk)
        if self.profile and self.profile.matches(self.image):
            ox,oy=self.image_origin
            for field,b in self.profile.boxes.items():
                self.canvas.create_rectangle(ox+b.x1*w,oy+b.y1*h,ox+b.x2*w,oy+b.y2*h,
                                             outline='#42E4CB',width=2)
                self.canvas.create_text(ox+b.x1*w,oy+b.y1*h-9,text=field,fill='#EFFFFB',anchor='sw')

    def _point(self,x,y):
        if self.image is None:return None
        ox,oy=self.image_origin
        w=self.image.width*self.image_scale;h=self.image.height*self.image_scale
        if not (ox<=x<=ox+w and oy<=y<=oy+h):return None
        return ((x-ox)/w,(y-oy)/h)

    def _start_roi(self,e):
        self.drag_start=self._point(e.x,e.y)
        self.drag_shape=None
    def _move_roi(self,e):
        if not self.drag_start:return
        if self.drag_shape:self.canvas.delete(self.drag_shape)
        self.drag_shape=self.canvas.create_rectangle(e.x,e.y,e.x+1,e.y+1,outline='#FFCC55',width=2)
        a=self.drag_start;b=self._point(e.x,e.y)
        if not b:return
        ox,oy=self.image_origin
        w=self.image.width*self.image_scale;h=self.image.height*self.image_scale
        self.canvas.coords(self.drag_shape,ox+a[0]*w,oy+a[1]*h,ox+b[0]*w,oy+b[1]*h)
    def _finish_roi(self,e):
        b=self._point(e.x,e.y);a=self.drag_start;self.drag_start=None
        if not a or not b:return
        try:
            rect=FieldBox(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])).validate()
            if not self.profile or not self.profile.matches(self.image):
                self.profile=NumericProfile(width=self.image.width,height=self.image.height)
            self.profile.boxes[self.calib_field.get()]=rect
            save_profile(profile_file(),self.profile)
            self.region_info.set(f'OCR 영역 {len(self.profile.boxes)}/{len(SCREEN_FIELDS)}개 저장 · {self.calib_field.get()}')
            self._draw_image()
        except Exception as exc:self.status.set('영역 등록 실패: '+str(exc))

    def run_ocr(self):
        if not self.image:messagebox.showwarning('캡처 없음','먼저 화면을 캡처하세요.');return
        if not self.profile or not self.profile.boxes:
            messagebox.showwarning('영역 미등록','우측에서 숫자 항목을 선택하고 왼쪽 캡처의 숫자 영역을 드래그하세요.');return
        try:
            values=ocr_candidates(self.image,self.profile)
            found=[]
            for f,entry in values.items():
                if entry['candidate'] is not None:
                    self.inputs[f].set(str(entry['candidate']))
                    found.append(f'{f}={entry["candidate"]} ({entry["confidence"]:.0f}%)')
            self._show('OCR 후보 (사용자 확인 필요):\n'+'\n'.join(found) if found else '인식값 없음 · 영역을 다시 지정하거나 직접 입력하세요.')
            self.status.set('OCR 후보 입력됨 · 화면 숫자를 직접 확인한 뒤 검수 완료를 눌러주세요.')
        except Exception as e:self.status.set('OCR 보류: '+str(e))

    def confirm_choice(self):
        if not self.captured_choice or not self.image:
            messagebox.showwarning('캡처 없음','훈련 종류를 선택하고 해당 화면을 먼저 캡처하세요.');return
        if self.selected.get()!=self.captured_choice:
            messagebox.showwarning('훈련 불일치','현재 선택한 훈련 종류와 마지막 캡처 종류가 다릅니다.');return
        try:
            values={k:v.get().strip() for k,v in self.inputs.items() if v.get().strip()}
            self.session.confirm(self.captured_choice,values,self.image_digest)
            cancel_handoff()
            self.latest_report=None
            self.status.set(f'{self.captured_choice} 선택 결과 검수 완료 (현재 턴 전용)')
            self._update_progress()
        except Exception as e:messagebox.showerror('검수 불가',str(e))

    def _update_progress(self):
        count=sum(k in self.session.options for k in STATS)
        self.progress.set(f'훈련 검수 {count}/5 · 완료: '+(', '.join(self.session.options) or '없음'))

    def compare(self):
        try:
            if self.turn.get().strip()!=self.session.turn_id:
                raise CaptureError('턴 이름이 바뀌었습니다. 다음 턴 시작을 눌러 기록을 초기화하세요.')
            profile=RunProfile(event=self.event.get(),distance=self.distance.get(),style=self.style.get())
            state=TurnState(turn_label=self.session.turn_id,energy=int(self.energy.get()),
                            remaining_turns=int(self.remaining.get()),island_tickets=int(self.tickets.get()))
            if state.remaining_turns<0 or not 0<=state.island_tickets<=3:raise CaptureError('남은 턴/티켓 수를 확인하세요.')
            report=self.session.compare(profile,state)
            self.latest_report=report
            if report.missing:
                text='추천 보류 · 다음 항목을 검수하세요.\n'
                text+='\n'.join(f'{n}: {", ".join(fields)}' for n,fields in report.missing.items())
            else:
                text=report.status+'\n'+'\n'.join(f'{i+1}. {r.name} · 임시 점수 {r.score:.1f}'
                                                   for i,r in enumerate(report.ranked))
                text+='\n\n훈련 선택지끼리만 비교. 휴식·외출·레이스는 포함 안 됨. 실제 최적값 아님.'
            self._show(text)
            self.status.set(report.status)
        except Exception as e:messagebox.showerror('비교 보류',str(e))

    def cancel_companion_hint(self):
        cancel_handoff()
        self.latest_report=None
        self.status.set('게임 위 추천 취소 · 다음 추천은 다시 검수해야 합니다.')

    def publish_to_companion(self):
        """Explicit per-turn opt-in. OCR values and model suggestions are never auto-clicked."""
        try:
            if self.game is None or self.session.window_id != self.game.hwnd:
                raise HandoffError('실제 게임에서 캡처한 동일 창을 다시 선택해야 합니다.')
            if self.session.turn_id!=self.turn.get().strip():
                raise HandoffError('턴이 변경되었습니다. 새 턴부터 다시 검수하세요.')
            profile=RunProfile(event=self.event.get(),distance=self.distance.get(),style=self.style.get())
            state=TurnState(turn_label=self.session.turn_id,energy=int(self.energy.get()),
                            remaining_turns=int(self.remaining.get()),island_tickets=int(self.tickets.get()))
            # Recalculate, never reuse a comparison from before input fields changed.
            report=self.session.compare(profile,state)
            obj=create_handoff(self.session,report,profile,state,window_id=self.game.hwnd,
                               window_size=(self.game.width,self.game.height))
            save_handoff(obj)
            self.latest_report=report
            self.status.set('R28 · 2분 동안만 현재 턴 검수 추천을 표시합니다. 턴 변경 전 반드시 취소하세요.')
            self._show('R28 전달: '+obj['suggestion']+'\n'+obj['notice']+'\n게임 화면 유형과 버튼이 다시 확인될 때만 표시합니다.')
        except (HandoffError,CaptureError,ValueError) as exc:
            messagebox.showwarning('R28 추천 보류',str(exc))

    def new_turn(self):
        cancel_handoff()
        self.latest_report=None
        try:self.session.reset(self.turn.get(),self.game.hwnd if self.game else None)
        except Exception as e:messagebox.showerror('턴 초기화 실패',str(e));return
        self.image=None;self.image_digest=None;self.captured_choice=None
        self.canvas.delete('all')
        for v in self.inputs.values():v.set('')
        self._update_progress()
        self._show('새 턴 기록을 시작했습니다. 실제 게임에서 훈련 탭을 순서대로 눌러 캡처하세요.')
        self.status.set('새 턴 · 이전 화면/훈련 기록 초기화 완료')

    def save_screenshot(self):
        if self.image is None:
            messagebox.showwarning('캡처 없음','먼저 게임 화면을 캡처하세요.')
            return
        name=filedialog.asksaveasfilename(title='화면 캡처 저장 (로컬)',defaultextension='.png',
                    filetypes=[('PNG image','*.png')],initialfile='uma_r22_training_capture.png')
        if not name:return
        try:
            self.image.save(name,format='PNG')
            self.status.set('원본 게임 캡처를 PC에 저장했습니다: '+name)
        except Exception as e:messagebox.showerror('PNG 저장 오류',str(e))

    def diagnose(self):
        self.find_game()
        ocr=tesseract_executable()
        lines=['R22 실게임 테스트 환경',
               '실행 OS: '+('Windows' if os.name=='nt' else os.name),
               '게임 창: '+(self.game.title if self.game else '미감지'),
               '게임 창 좌표: '+(str(self.game.rect) if self.game else '없음'),
               'Tesseract: '+(ocr or '미설치 (수동 검수 가능)'),
               'OCR 설정: '+str(len(self.profile.boxes) if self.profile else 0)+'/'+str(len(SCREEN_FIELDS))+'개',
               '현재 턴: '+self.session.turn_id,
               '검수한 훈련: '+(', '.join(self.session.options) or '없음'),
               '자료 업로드: 없음 / 자동 클릭: 없음',
               '실게임 OCR 정확도·설치형 실행: 이 PC에서 확인 필요']
        self._show('\n'.join(lines))
        self.status.set('연결 환경 진단을 확인했습니다.')

    def export_report(self):
        folder=filedialog.asksaveasfilename(title='진단 결과 저장',defaultextension='.json',filetypes=[('JSON','*.json')],
                                           initialfile=f'uma_r22_{datetime.now():%Y%m%d_%H%M%S}.json')
        if not folder:return
        try:
            result=self.session.export(Path(folder))
            self.status.set('로컬 진단 JSON 저장: '+str(result))
        except Exception as e:messagebox.showerror('진단 저장 실패',str(e))

if __name__=='__main__':
    from package_selftest_r25 import maybe_run_cli
    maybe_run_cli("UmaTrainerKR_GameTest")
    from package_selftest_r25 import maybe_run_startup_cli
    maybe_run_startup_cli("UmaTrainerKR_GameTest")
    LiveTest().mainloop()
