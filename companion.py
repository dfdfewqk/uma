"""Uma Trainer KR companion: game-side overlay preview, not an auto-bot.
Run 'python companion.py --demo' to see layout without the game.
"""
from __future__ import annotations

# Validate a packaged EXE before importing tkinter or any GUI-heavy modules.
import sys as _uma_startup_sys
if __name__ == '__main__' and '--self-check-report' in _uma_startup_sys.argv[1:]:
    from package_selftest_r25 import maybe_run_cli as _uma_early_selfcheck
    _uma_early_selfcheck('UmaTrainerKR_Companion')
if __name__ == '__main__' and '--first-run-report' in _uma_startup_sys.argv[1:]:
    from runtime_probe_r26 import maybe_run_cli as _uma_early_first_run
    _uma_early_first_run()
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from companion_core import choose_window, overlay_position, usable_ocr_values
from helper_view_r37 import view_from_frame, paused_view, StableLowEnergy
from capture_pack_r29 import (CaptureError, SCENES, check_capture_target, new_pack,
                              store_capture, export_pack)
from screen_r4 import user_dir
from live_state_r24 import FreshnessGate, rectangles_overlap
from companion_window import discover_windows
from recommendation_bridge_r28 import load_handoff, HintGate, HandoffError
from game_overlay_r28 import TrainingOverlay
from portable_update_r30 import check_latest, download_portable, UpdateError, CURRENT_VERSION
from scene_recognition_r20 import StableScene, load_library, profile_path as scene_profile_path
from button_detection_r21 import StableButtons, load_patterns, path_default as button_pattern_path, DetectionError, DetectorUnavailable

BG='#0D1524'; CARD='#17243B'; TEXT='#EFF6FF'; MUTED='#9DAFC5'; AQUA='#6DDCCB'; YELLOW='#F9C56B'
STATS=('스피드','스태미나','파워','근성','지능')

class Companion(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.demo=demo
        self.title(f'Uma Trainer KR v{CURRENT_VERSION} · 클릭형 헬퍼')
        self.geometry('344x790+750+75')
        self.minsize(310,680)
        self.configure(bg=BG)
        self.scroll_canvas=tk.Canvas(self,bg=BG,highlightthickness=0,borderwidth=0)
        self.scrollbar=tk.Scrollbar(self,orient='vertical',command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right',fill='y')
        self.scroll_canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.scroll_canvas,bg=BG)
        body_id=self.scroll_canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda event:self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox('all')))
        self.scroll_canvas.bind('<Configure>',lambda event:self.scroll_canvas.itemconfigure(body_id,width=event.width))
        self.attributes('-topmost', True)
        self.game=None
        self.reading=False
        self.last_capture=0
        self.q=queue.Queue()
        self.update_queue=queue.Queue()
        self.update_release=None
        self.update_busy=False
        self.update_status=tk.StringVar(value=f'현재 R37 · v{CURRENT_VERSION} · 업데이트 확인 대기')
        self.event_var=tk.StringVar(value='미확인')
        self.monitoring=True
        self.helper_switch=None
        self.dev_visible=False
        self.dev_panel=None
        self.status=tk.StringVar(value='게임 창 찾는 중…')
        self.detail=tk.StringVar(value='게임을 실행하면 자동으로 창을 찾습니다.')
        self.action=tk.StringVar(value='게임 화면 자동 확인 중')
        self.reason=tk.StringVar(value='육성 중 입력할 필요 없습니다. 확인되지 않은 화면에서는 추천을 보류합니다.')
        self.scene_info=tk.StringVar(value='화면 유형: 확인 전 (R20 기준 화면 필요)')
        self.scene_tracker=StableScene()
        self.hint_gate=HintGate()
        self.hint_overlay=TrainingOverlay(self)
        self.button_tracker=StableButtons()
        self.button_patterns=[]
        self.button_info=tk.StringVar(value='훈련 버튼 자동 확인 대기')
        self.r28_info=tk.StringVar(value='훈련 추천: 화면 확인·검수 전')
        self.capture_label=tk.StringVar(value='훈련')
        self.capture_pack=None
        self.capture_pending=False
        self.scene_anchors=[]
        self.last_hwnd=None
        self.freshness=FreshnessGate()
        self.low_energy=StableLowEnergy()
        self.statvals={name:tk.StringVar(value='—') for name in STATS}
        self.energy=tk.StringVar(value='—')
        self.skill=tk.StringVar(value='—')
        self._draw()
        self.after(300,self._update_poll)
        if getattr(sys, 'frozen', False) and os.name == 'nt':
            self.after(2600,self._check_updates)
            self.after(24*60*60*1000,self._periodic_update_check)
        else:
            self.update_status.set('소스 실행 · 자동 교체는 Windows 포터블 EXE에서 지원')
        if self.demo:
            self.status.set('시연 화면 · 실제 게임 아님')
            self.detail.set('이 화면은 원하는 사용 방식의 UI 프로토타입입니다.')
            for n,v in zip(STATS,('1,201','873','1,098','777','1,005')):
                self.statvals[n].set(v)
            self.energy.set('62'); self.skill.set('1,245')
            self.scene_info.set('화면 유형: 시연 화면 (실제 감지 아님)')
            self.action.set('스피드 훈련 · 표시 예시')
            self.reason.set('실제 추천 아님 · 게임 연동 후 검증 필요')
        else:
            self.after(350,self._poll)
            self.after(1300,self._scan)

    def _label(self,parent,text,fg=MUTED,size=10,weight='normal'):
        return tk.Label(parent,text=text,bg=parent['bg'],fg=fg,
            font=('Malgun Gothic' if os.name=='nt' else 'DejaVu Sans',size,weight),anchor='w')

    def _card(self):
        f=tk.Frame(self.body,bg=CARD,padx=12,pady=9,highlightthickness=1,highlightbackground='#22334E')
        f.pack(fill='x',padx=12,pady=(0,9))
        return f

    def _draw(self):
        top=tk.Frame(self.body,bg=BG,padx=14,pady=13);top.pack(fill='x')
        self._label(top,'Uma Trainer KR',TEXT,17,'bold').pack(anchor='w')
        self._label(top,'화면은 자동으로 확인 · 선택과 클릭은 게임에서 직접',MUTED,9).pack(anchor='w',pady=(2,0))
        c=self._card()
        self._label(c,'게임 연결',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.status,fg=TEXT,bg=CARD,anchor='w',font=('Malgun Gothic',10,'bold'),wraplength=290,justify='left').pack(anchor='w',pady=(5,1))
        tk.Label(c,textvariable=self.detail,fg=MUTED,bg=CARD,anchor='w',font=('Malgun Gothic',8),wraplength=290,justify='left').pack(anchor='w')
        c=self._card()
        self._label(c,'지금 할 일 · 게임에서 직접 누르세요',AQUA,11,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.action,bg=CARD,fg=YELLOW,
                 font=('Malgun Gothic',14,'bold'),anchor='w',
                 wraplength=290,justify='left').pack(anchor='w',pady=(7,4))
        tk.Label(c,textvariable=self.reason,bg=CARD,fg=TEXT,
                 font=('Malgun Gothic',9),wraplength=290,
                 justify='left',anchor='w').pack(anchor='w',pady=(0,4))
        self.helper_switch=tk.Button(c,text='화면 분석 일시 정지',command=self._helper,
                 bg='#226F83',fg='white',relief='flat')
        self.helper_switch.pack(fill='x',pady=(8,1))
        self._label(c,'훈련·휴식·이벤트 선택은 게임에서만 클릭합니다. 프로그램은 입력하지 않습니다.',
                    MUTED,8).pack(anchor='w',pady=(5,0))

        c=self._card()
        self._label(c,'게임 화면 자동 확인',AQUA,10,'bold').pack(anchor='w')
        tk.Label(c,textvariable=self.scene_info,bg=CARD,fg=TEXT,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=(5,2))
        tk.Label(c,textvariable=self.button_info,bg=CARD,fg=MUTED,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=2)
        tk.Label(c,textvariable=self.r28_info,bg=CARD,fg=MUTED,
                 anchor='w',wraplength=290,justify='left').pack(anchor='w',pady=(0,4))

        c=self._card()
        self._label(c,'현재 수치 · 자동 관측 후보',AQUA,10,'bold').pack(anchor='w',pady=(0,6))
        grid=tk.Frame(c,bg=CARD);grid.pack(fill='x')
        for i,k in enumerate(STATS):
            box=tk.Frame(grid,bg=CARD)
            box.grid(row=i//3,column=i%3,sticky='w',padx=(0,17),pady=(0,5))
            self._label(box,k,MUTED,8).pack(anchor='w')
            tk.Label(box,textvariable=self.statvals[k],bg=CARD,fg=TEXT,
                     font=('Malgun Gothic',10,'bold')).pack(anchor='w')
        info=tk.Frame(c,bg=CARD);info.pack(fill='x',pady=(2,0))
        self._label(info,'체력 ',MUTED,9).pack(side='left')
        tk.Label(info,textvariable=self.energy,bg=CARD,fg=TEXT).pack(side='left')
        self._label(info,'      스킬 Pt ',MUTED,9).pack(side='left')
        tk.Label(info,textvariable=self.skill,bg=CARD,fg=TEXT).pack(side='left')
        self._label(c,'* 표시는 검수 전 OCR 후보 · 화면 전환 시 자동으로 지움',
                    MUTED,8).pack(anchor='w',pady=(5,0))

        tools=tk.Frame(self.body,bg=BG)
        tools.pack(fill='x',padx=12,pady=(0,9))
        tk.Button(tools,text='설정·개발자 점검 보기 (평소 사용 불필요)',
                  command=self._toggle_dev_tools,bg='#263754',fg=TEXT,
                  relief='flat').pack(fill='x')
        self.dev_panel=tk.Frame(self.body,bg=BG)
        advanced=self.dev_panel
        settings=tk.Frame(advanced,bg=CARD,padx=12,pady=9)
        settings.pack(fill='x',padx=12,pady=(0,9))
        self._label(settings,'대회 구분 (선택 사항 · 추천 엔진 자동 연계 전)',
                    AQUA,9,'bold').pack(anchor='w')
        ttk.Combobox(settings,values=['미확인','챔피언스 미팅','리그 오브 히어로즈'],
                     textvariable=self.event_var,state='readonly').pack(fill='x',pady=(6,0))

        row=tk.Frame(advanced,bg=BG)
        row.pack(fill='x',padx=12,pady=(0,5))
        tk.Button(row,text='실게임 훈련 점검 · R22',command=self._launch_game_test,
                  bg='#247368',fg='white',relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='R23 · 게임 없이 사전점검',
                  command=self._launch_preflight,bg='#345778',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,5))
        self._label(row,'R29 · 화면 자료 수집 (개발 검수용)',AQUA,9,'bold').pack(anchor='w',pady=(3,2))
        ttk.Combobox(row,values=SCENES,textvariable=self.capture_label,
                     state='readonly').pack(fill='x',pady=(0,4))
        tk.Button(row,text='4초 뒤 게임 화면 저장 · 게임 창으로 돌아가기',
                  command=self._schedule_capture,bg='#346075',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,4))
        tk.Button(row,text='저장된 화면 ZIP 내보내기 (직접 선택)',
                  command=self._export_capture_pack,bg='#344766',fg=TEXT,
                  relief='flat').pack(fill='x',pady=(0,5))
        tk.Button(row,text='상세 설정·자료 관리 열기',
                  command=self._launch_advanced,bg='#263754',fg=TEXT,
                  relief='flat').pack(fill='x')

        u=tk.Frame(advanced,bg=CARD,padx=12,pady=9)
        u.pack(fill='x',padx=12,pady=(0,9))
        self._label(u,'무설치 프로그램 업데이트',AQUA,10,'bold').pack(anchor='w')
        tk.Label(u,textvariable=self.update_status,bg=CARD,fg=TEXT,
                 wraplength=290,justify='left',anchor='w').pack(anchor='w',pady=(5,4))
        self.update_check_button=tk.Button(u,text='GitHub 최신 버전 확인',
                     command=self._check_updates,bg='#345778',fg=TEXT,relief='flat')
        self.update_check_button.pack(fill='x',pady=(0,4))
        self.update_install_button=tk.Button(u,text='새 포터블 버전 받기 및 실행',
                     command=self._download_update,state='disabled',relief='flat')
        self.update_install_button.pack(fill='x')
        self._label(u,'기존 버전·기록 보존',MUTED,8).pack(anchor='w',pady=(5,0))
        self._label(advanced,'고급 점검은 실게임 인식 검증을 위한 개발 도구이며 육성 중 필요하지 않습니다.',
                    MUTED,8).pack(anchor='w',padx=14,pady=(0,8))

    def _toggle_dev_tools(self):
        self.dev_visible=not self.dev_visible
        if self.dev_visible:
            self.dev_panel.pack(fill='x')
        else:
            self.dev_panel.pack_forget()

    def _periodic_update_check(self):
        if not self.update_busy:
            self._check_updates()
        self.after(24*60*60*1000,self._periodic_update_check)

    def _check_updates(self):
        if self.update_busy:
            return
        if os.name != 'nt' or not getattr(sys,'frozen',False):
            self.update_status.set('소스 실행에서는 버전 교체를 지원하지 않습니다.')
            return
        self.update_busy=True
        self.update_check_button.configure(state='disabled')
        self.update_install_button.configure(state='disabled')
        self.update_status.set('GitHub 공개 릴리스 확인 중…')
        def worker():
            try:
                self.update_queue.put(('check_ok',check_latest()))
            except Exception as exc:
                self.update_queue.put(('error',str(exc)[:150]))
        threading.Thread(target=worker,daemon=True).start()

    def _download_update(self):
        release=self.update_release
        if self.update_busy or release is None:
            return
        if not messagebox.askyesno('포터블 업데이트 확인',
            f'v{release.version}을 공식 GitHub에서 내려받아 SHA-256 검증 후 새 폴더에 준비합니다.\n'
            '기존 버전과 육성 기록은 지워지지 않습니다. 진행할까요?',parent=self):
            return
        self.update_busy=True
        self.update_check_button.configure(state='disabled')
        self.update_install_button.configure(state='disabled')
        self.update_status.set(f'v{release.version} 다운로드 및 무결성 검증 중…')
        exe=Path(sys.executable).resolve()
        def worker():
            try:
                self.update_queue.put(('download_ok',download_portable(release,exe)))
            except Exception as exc:
                self.update_queue.put(('error',str(exc)[:150]))
        threading.Thread(target=worker,daemon=True).start()

    def _update_poll(self):
        try:
            while True:
                kind,result=self.update_queue.get_nowait()
                self.update_busy=False
                self.update_check_button.configure(state='normal')
                if kind=='error':
                    self.update_status.set('업데이트 오류 · 기존 버전 유지: '+result)
                    self.update_install_button.configure(state='normal' if self.update_release else 'disabled')
                elif kind=='check_ok':
                    self.update_release=result
                    if result is None:
                        self.update_status.set(f'현재 버전 v{CURRENT_VERSION} · 새 공개 버전 없음')
                    else:
                        self.update_status.set(f'새 공개 버전 v{result.version} · 사용자 확인 후 업데이트')
                        self.update_install_button.configure(state='normal')
                elif kind=='download_ok':
                    new_exe=Path(result)
                    self.update_status.set(f'새 버전 준비 완료: {new_exe.parent.name}')
                    if messagebox.askyesno('새 버전 준비 완료',
                            '검증된 새 버전이 별도 폴더에 준비됐습니다. 지금 새 버전을 실행할까요?\n'
                            '기존 프로그램은 종료되며 저장된 기록은 유지됩니다.',parent=self):
                        try:
                            subprocess.Popen([str(new_exe)],cwd=str(new_exe.parent))
                        except OSError as exc:
                            self.update_status.set('새 프로그램 실행 실패 · 기존 버전 유지: '+str(exc)[:80])
                        else:
                            self.destroy()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(350,self._update_poll)

    def _helper(self):
        """Click-only monitoring control; no game keyboard or pointer events."""
        self.monitoring=not self.monitoring
        if not self.monitoring:
            self.freshness.update(None)
            self.hint_gate.clear()
            self.scene_tracker.reset()
            self.button_tracker.reset()
            self.reading=False
            self._clear_live_evidence()
            view=paused_view()
            self.action.set(view.title)
            self.reason.set(view.explanation)
            self.status.set('헬퍼 일시 정지')
            self.helper_switch.configure(text='화면 분석 다시 시작')
        else:
            self.action.set('게임 화면 자동 확인 중')
            self.reason.set('게임 창이 활성화되면 화면을 자동으로 분석합니다.')
            self.status.set('게임 창 연결 대기')
            self.helper_switch.configure(text='화면 분석 일시 정지')

    def _schedule_capture(self):
        """Button is clicked on the companion; user has 4 seconds to refocus game."""
        if self.capture_pending or self.demo:
            self.reason.set('시연 모드에서는 게임 화면을 저장할 수 없습니다.')
            return
        if self.game is None or os.name != 'nt':
            self.reason.set('Windows에서 실제 게임 창을 찾은 뒤 사용하세요.')
            return
        self.capture_pending=True
        target=self.game
        scene=self.capture_label.get()
        self.hint_overlay.hide()
        self.reason.set('4초 뒤 캡처: 게임 창으로 돌아가고 다른 창으로 가리지 마세요.')
        self.after(4000,lambda:self._capture_r29(target,scene))

    def _capture_r29(self,expected,scene):
        try:
            if os.name!='nt':raise CaptureError('Windows PC에서만 사용할 수 있습니다.')
            import ctypes
            from PIL import ImageGrab
            current, _=choose_window(discover_windows())
            panel=(self.winfo_rootx(),self.winfo_rooty(),
                   self.winfo_rootx()+self.winfo_width(),self.winfo_rooty()+self.winfo_height())
            rect=check_capture_target(expected,current,ctypes.windll.user32.GetForegroundWindow(),panel)
            if not self.capture_pack:
                self.capture_pack=new_pack(user_dir()/'r29_local_captures')
            self.hint_overlay.hide()
            # No game clicks or keyboard events are sent.
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            store_capture(self.capture_pack,image,scene_label=scene,
                          window_size=(current.width,current.height))
            self.reason.set(f'로컬 화면 저장 완료 · {scene} · 폴더: r29_local_captures (외부 전송 없음)')
        except (CaptureError,OSError,ValueError) as error:
            self.reason.set('R29 캡처 보류 · '+str(error)[:100])
        finally:
            self.capture_pending=False

    def _export_capture_pack(self):
        if not self.capture_pack:
            self.reason.set('R29 캡처를 먼저 저장하세요.')
            return
        location=filedialog.asksaveasfilename(title='본인이 확인한 화면만 공유하세요',
                   defaultextension='.zip',filetypes=[('ZIP archives','*.zip')])
        if not location:return
        try:
            export_pack(self.capture_pack,Path(location))
            self.reason.set('ZIP 저장 완료 · 게임 화면에 개인 정보가 없는지 공유 전 확인하세요.')
        except (CaptureError,OSError,ValueError) as error:
            self.reason.set('R29 ZIP 내보내기 실패 · '+str(error)[:100])

    def _launch_game_test(self):
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        name='UmaTrainerKR_GameTest.exe' if getattr(sys,'frozen',False) else 'live_test_ui_r22.py'
        target=base/name
        if target.is_file():
            args=[str(target)] if getattr(sys,'frozen',False) else [sys.executable,str(target)]
            try:
                subprocess.Popen(args,cwd=str(base))
            except OSError as exc:
                self.reason.set('R22 실행 오류: '+str(exc)[:85])
        else:
            self.reason.set('R22 점검 도구가 없습니다. 전체 설치형 패키지를 확인하세요.')

    def _launch_preflight(self):
        """Launch local read-only test app, never game control."""
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        filename='UmaTrainerKR_Preflight.exe' if getattr(sys,'frozen',False) else 'offline_replay_ui_r23.py'
        target=base/filename
        if not target.is_file():
            self.reason.set('R23 점검 도구가 없습니다. 전체 설치본인지 확인하세요.')
            return
        args=[str(target)] if getattr(sys,'frozen',False) else [sys.executable,str(target)]
        try:subprocess.Popen(args,cwd=str(base))
        except OSError as exc:self.reason.set('R23 점검 도구 실행 오류: '+str(exc)[:85])

    def _launch_advanced(self):
        base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        path=base/'app.py'
        if getattr(sys,'frozen',False):
            advanced=Path(sys.executable).resolve().parent/'UmaTrainerKR.exe'
            if advanced.is_file():
                try:subprocess.Popen([str(advanced)],cwd=str(base))
                except OSError as exc:self.reason.set('상세 설정 실행 오류: '+str(exc)[:85])
            else:
                self.reason.set('고급 설정 도구가 없습니다. 설치형 패키지를 사용하세요.')
        elif path.is_file():
            try:subprocess.Popen([sys.executable,str(path)],cwd=str(base))
            except OSError as exc:self.reason.set('상세 설정 실행 오류: '+str(exc)[:85])
        else:
            self.reason.set('상세 설정 프로그램을 찾지 못했습니다.')

    def _clear_live_evidence(self):
        """Never display last-turn values after window/layout/scene invalidation."""
        for var in self.statvals.values(): var.set('—')
        self.energy.set('—');self.skill.set('—')
        self.scene_info.set('화면 유형: 미확인 · 검수 대기')
        self.hint_overlay.hide()
        self.low_energy.reset()
        self.r28_info.set('R28: 현재 화면 추천 보류')
        self.button_info.set('훈련 버튼: 현재 화면 미확인')
        self.action.set('추천 보류')
        self.reason.set('이전 화면의 추천과 OCR 수치를 무효화했습니다.')

    def _scan(self):
        if not self.monitoring:
            self.status.set('헬퍼 일시 정지')
            self.after(2500,self._scan)
            return
        try:
            game, message=choose_window(discover_windows())
            if self.freshness.update(game.hwnd if game else None,game.rect if game else None):
                self.scene_tracker.reset()
                self.button_tracker.reset()
                self._clear_live_evidence()
                self.reading=False  # pending older worker response is rejected by epoch
                self.hint_gate.clear()
                self.last_hwnd=game.hwnd if game else None
            self.game=game
            self.status.set(message)
            self.detail.set((game.title[:50] if game else '게임을 실행하면 자동으로 연결을 시도합니다.'))
            if game:
                if os.name=='nt':
                    import ctypes
                    if ctypes.windll.user32.GetForegroundWindow()!=game.hwnd:
                        self.hint_overlay.hide()
                        self.hint_gate.clear()
                width=max(344,self.winfo_width())
                height=max(790,self.winfo_height())
                x,y=overlay_position(game.rect,self.winfo_screenwidth(),self.winfo_screenheight(),width,height)
                self.geometry(f'+{x}+{y}')
                if rectangles_overlap(game.rect,(x,y,x+width,y+height)):
                    self._clear_live_evidence()
                    self.reason.set('도우미가 게임 화면을 가림 · 패널 이동/게임 창 크기 조정 후 재시도')
                elif not self.reading:
                    self.hint_overlay.hide()  # prevent our own overlay being captured as game pixels
                    self._read_game(game)
        except Exception as exc:
            self.game=None
            self.hint_gate.clear()
            self.freshness.update(None)
            self._clear_live_evidence()
            self.status.set('게임 연결 감지 오류')
            self.detail.set(type(exc).__name__)
        self.after(2500,self._scan)

    def _read_game(self,game):
        from screen_r4 import profile_path
        self.reading=True
        epoch=self.freshness.ticket()
        def work():
            from PIL import ImageGrab
            from screen_r4 import read_profile,read_regions
            try:
                # A desktop screenshot of a background window can contain another
                # app in the same pixels. Never label such content as game data.
                if os.name == 'nt':
                    import ctypes
                    u=ctypes.windll.user32
                    if u.IsIconic(game.hwnd) or u.GetForegroundWindow()!=game.hwnd:
                        raise RuntimeError('게임 창이 활성화되지 않았습니다 · 추천 보류')
                image=ImageGrab.grab(bbox=game.rect,all_screens=True)
                if image.size!=(game.rect[2]-game.rect[0],game.rect[3]-game.rect[1]):
                    raise RuntimeError('게임 화면 캡처 크기가 일치하지 않습니다.')
                try:anchors=load_library(scene_profile_path())
                except (OSError,ValueError):anchors=[]
                guess=self.scene_tracker.observe(image,anchors)
                scene=guess.scene
                text_scene=f'화면 유형: {scene or "보류"} · {guess.reason}'
                hits=[]
                try:patterns=load_patterns(button_pattern_path())
                except (DetectionError,OSError):patterns=[]
                try:
                    hits=self.button_tracker.observe(image,patterns,scene)
                    buttons=('훈련 버튼: '+', '.join(h.label for h in hits)+' · 위치 확인 (추천 계산 전)'
                             if hits else '훈련 버튼: 미검출 또는 반복 확인 중')
                except (DetectorUnavailable,DetectionError,ValueError) as exc:
                    self.button_tracker.reset()
                    buttons='버튼 인식 보류: '+str(exc)[:70]
                values={}
                if scene == '훈련' and profile_path().exists():
                    with tempfile.TemporaryDirectory(prefix='uma_companion_') as td:
                        path=Path(td)/'game.png'
                        image.save(path)
                        profile=read_profile(profile_path())
                        results=read_regions(path,profile,min_confidence=80)
                    values=usable_ocr_values(results)
                self.q.put(('frame',epoch,game.hwnd,(text_scene,buttons,scene,values,hits)))
            except Exception as e:
                self.q.put(('error',epoch,game.hwnd,str(e)))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind,epoch,hwnd,data=self.q.get_nowait()
                if not self.freshness.accepts(epoch,hwnd):
                    continue
                self.reading=False
                if kind=='error':
                    self._clear_live_evidence()
                    self.reason.set('화면 인식 보류 · '+data[:85])
                    continue
                scene_text,buttons,scene,values,hits=data
                self.scene_info.set(scene_text)
                self.button_info.set(buttons)
                # Entire frame replaces, never merges with last frame's values.
                safe=self.freshness.safe_values(scene,values)
                for k,var in self.statvals.items():
                    var.set(f'{safe[k]:,} *' if k in safe else '—')
                self.energy.set(f'{safe["체력"]} *' if '체력' in safe else '—')
                self.skill.set(f'{safe["스킬 Pt"]:,} *' if '스킬 Pt' in safe else '—')
                self.action.set('화면 분석 중')
                self.reason.set('화면에서 읽은 수치와 선택지를 확인하는 중입니다.')
                try:
                    obj=load_handoff()
                except (HandoffError,OSError) as exc:
                    obj=None
                    self.r28_info.set('R28 전달 오류: '+str(exc)[:75])
                rect=self.game.rect if self.game and self.game.hwnd==hwnd else None
                active=False
                if rect and os.name=='nt':
                    import ctypes
                    active=ctypes.windll.user32.GetForegroundWindow()==hwnd
                hint=self.hint_gate.observe(obj,hwnd=hwnd,
                        size=((rect[2]-rect[0],rect[3]-rect[1]) if rect else None),
                        scene=scene,hits=hits,active=active)
                view=view_from_frame(
                    scene=scene,active=active,value_count=len(safe),
                    detected_buttons=tuple(h.label for h in hits),
                    reviewed_hint=hint.label if hint is not None else None,
                    low_energy_candidate=self.low_energy.observe(
                        energy=safe.get('체력'),epoch=epoch,scene=scene,active=active))
                self.action.set(view.title)
                self.reason.set(view.explanation)
                if view.verified_training and hint and rect:
                    self.r28_info.set('확인된 훈련 후보: '+hint.label)
                    if not self.hint_overlay.show(rect,hint):
                        self.r28_info.set('훈련 후보 확인 · 게임 위 표시 실패 (옆 창에서 확인)')
                else:
                    self.hint_overlay.hide()
                    if obj is None:
                        self.r28_info.set('자동 판단 준비 중 · 현재 훈련 추천 없음')
                    elif obj['id'] in self.hint_gate.revoked:
                        self.r28_info.set('이전 추천 폐기 · 화면 재확인 중')
                    else:
                        self.r28_info.set('화면의 훈련 후보 검수 중')
        except queue.Empty:pass
        self.after(250,self._poll)


if __name__=='__main__':
    from package_selftest_r25 import maybe_run_cli
    maybe_run_cli("UmaTrainerKR_Companion")
    from package_selftest_r25 import maybe_run_startup_cli
    maybe_run_startup_cli("UmaTrainerKR_Companion")
    from runtime_probe_r26 import maybe_run_cli as r26_first_run
    r26_first_run()
    from helper_smoke_r37 import maybe_run_cli as r37_helper_smoke
    r37_helper_smoke(lambda: Companion(demo=True))
    app=Companion('--demo' in sys.argv)
    if '--screenshot' in sys.argv:
        idx=sys.argv.index('--screenshot')
        dest=sys.argv[idx+1]
        def capture():
            from PIL import ImageGrab
            app.update()
            box=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())
            ImageGrab.grab(bbox=box).save(dest)
            app.destroy()
        app.after(900,capture)
    app.mainloop()
