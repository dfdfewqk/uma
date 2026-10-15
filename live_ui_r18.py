"""R18 desktop live-game viewer + optional once-per-arm guarded click demonstration.

This is NOT yet a complete automatic training bot: without observed real KR game
screens, there is no verified scene recognizer or training choice->click mapping.
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from PIL import Image, ImageTk

from live_r18 import WindowsGameBackend, LiveError, OneClickGuard, create_template
from hud_ui_r19 import GameHUD
from hud_r19 import Mark, default_mark_path, save_marks, load_marks, SCENES
from skill_ocr_r20 import (run_skill_ocr, evidence_crop, same_visible_text,SkillListRegion,
                           skill_region_path,load_skill_region,save_skill_region)
from scene_recognition_r20 import (SCENES_R20, SceneError, StableScene, make_anchor,
                                   load_library, save_library, remap_marked_locations, profile_path as scene_profile_path)
from button_detection_r21 import (LABELS as BUTTON_LABELS, StableButtons, make_pattern,
                                  find_button, recommended_training_marks, save_patterns, load_patterns, path_default as button_pattern_path,
                                  DetectionError, DetectorUnavailable)
from screen_r4 import (FIELD_LIMITS, read_profile, profile_path, tesseract_executable,
                       _recognize_one, parse_numeric)


class LivePanel(ttk.Frame):
    def __init__(self, parent, context_provider=None):
        super().__init__(parent)
        self.context_provider=context_provider or (lambda: {})
        self.hud=GameHUD(self, self.context_provider)
        self.marks=[]
        try:self.marks=load_marks(default_mark_path())
        except (ValueError, OSError):pass
        self.marker_scene=tk.StringVar(value="훈련")
        self.marker_name=tk.StringVar(value="스피드")
        self.scene_confirmed=tk.BooleanVar(value=False)
        self.auto_scene=tk.BooleanVar(value=True)
        self.anchor_scene=tk.StringVar(value='훈련')
        self.auto_status=tk.StringVar(value='화면 인식 기준을 등록하면 자동 장면 판별이 시작됩니다.')
        self.scene_engine=StableScene()
        try:self.anchors=load_library(scene_profile_path())
        except (SceneError,ValueError,OSError):self.anchors=[]
        self.verified_scene=None
        self.button_name=tk.StringVar(value='스피드')
        self.button_status=tk.StringVar(value='R21 · 버튼 특징 이미지를 등록하면 자동 위치 탐지를 시도합니다.')
        self.button_tracker=StableButtons()
        self.button_q=queue.Queue()
        self.button_hits=[]
        self.button_epoch=0
        self.button_request=None
        try:self.button_patterns=load_patterns(button_pattern_path())
        except (DetectionError,OSError):self.button_patterns=[]
        self.skill_ocr_q=queue.Queue()
        self.skill_evidence=[]
        self.skill_pending=False
        self._last_skill_at=0.0
        self.skill_roi_first=None
        self.skill_roi_calibrating=False
        try:self.skill_region=load_skill_region(skill_region_path())
        except (OSError,ValueError,KeyError):self.skill_region=None
        self.backend=None
        self.game_windows={}
        self.selected=tk.StringVar(value='')
        self.interval_ms=1200
        self.running=False
        self.guard=None
        self.image=None
        self.photo=None
        self.display_box=None
        self.last_window=None
        self.pending_position=None
        self._pending_ocr=False
        self._ocr_results=queue.Queue()
        self._last_ocr_at=0.0
        self.status=tk.StringVar(value='Windows 게임 창을 선택하세요. 실전 육성 자동 판단은 아직 미연결입니다.')
        self.summary=tk.StringVar(value='현재 화면 정보를 아직 확인하지 못했습니다.')
        self.action_status=tk.StringVar(value='자동 클릭: 기본 꺼짐 · 등록 버튼 1회 실험만 지원')
        self.overlay=None
        self.overlay_summary=None
        self.overlay_action=None
        self._build()
        self.bind('<Destroy>', self._destroyed, add='+')
        self.after(100,self._drain)

    def _build(self):
        wrap=ttk.Frame(self)
        wrap.pack(fill='both',expand=True,padx=14,pady=12)
        ttk.Label(wrap,text='게임 실행 → 창 선택 → 실시간 정보 보기',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Label(wrap,text='게임 화면 위에는 누를 후보를, 옆 창에는 스탯·필수 스킬을 보여줍니다. 훈련 위치는 R21 등록 후 자동 재탐색하고, 스킬 위치는 OCR로 검수합니다.',
                  style='Muted.TLabel').pack(anchor='w',pady=(0,9))
        bar=ttk.Frame(wrap);bar.pack(fill='x',pady=5)
        ttk.Label(bar,text='게임 창').pack(side='left',padx=(0,6))
        self.choice=ttk.Combobox(bar,textvariable=self.selected,width=48,state='readonly')
        self.choice.pack(side='left',padx=(0,6))
        ttk.Button(bar,text='창 찾기',command=self.refresh).pack(side='left',padx=3)
        ttk.Button(bar,text='감시 시작',command=self.start).pack(side='left',padx=3)
        ttk.Button(bar,text='즉시 중단',command=self.stop).pack(side='left',padx=3)
        ttk.Button(bar,text='게임 위 표시 + 옆 정보창',command=self.toggle_overlay).pack(side='left',padx=3)
        ttk.Label(wrap,textvariable=self.status,style='Muted.TLabel',wraplength=1100).pack(anchor='w',pady=7)
        work=ttk.Frame(wrap);work.pack(fill='both',expand=True,pady=5)
        left=ttk.Frame(work);left.pack(side='left',fill='both',expand=True,padx=(0,15))
        ttk.Label(left,text='실시간 게임 창 미리보기 (게임을 활성화하면 갱신)',style='Section.TLabel').pack(anchor='w',pady=(0,4))
        self.canvas=tk.Canvas(left,bg='#0c1625',height=365,highlightthickness=1,highlightbackground='#3d516b',cursor='crosshair')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonRelease-1>',self.mark_target)
        self.canvas.bind('<Configure>',lambda _:self.redraw())
        ttk.Label(left,text='실험 클릭을 시험하려면 미리보기에서 버튼 중앙을 누르고 아래에서 등록하세요. 실제 게임 레이아웃 확인 전까지 자동 육성은 실행되지 않습니다.',
                  style='Muted.TLabel',wraplength=690).pack(anchor='w',pady=8)
        right_wrap=ttk.Frame(work,width=350)
        right_wrap.pack(side='left',fill='y')
        side_scroll=tk.Canvas(right_wrap,width=330,highlightthickness=0,bg='#111827')
        side_scroll.pack(side='left',fill='both',expand=True)
        scroll_bar=ttk.Scrollbar(right_wrap,orient='vertical',command=side_scroll.yview)
        scroll_bar.pack(side='right',fill='y')
        side_scroll.configure(yscrollcommand=scroll_bar.set)
        right=ttk.Frame(side_scroll)
        window_id=side_scroll.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda _e:side_scroll.configure(scrollregion=side_scroll.bbox('all')))
        side_scroll.bind('<Configure>',lambda ev:side_scroll.itemconfigure(window_id,width=ev.width))
        def on_mousewheel(ev):
            if ev.delta:side_scroll.yview_scroll(int(-ev.delta/120),'units')
        side_scroll.bind('<MouseWheel>',on_mousewheel)
        right.bind('<MouseWheel>',on_mousewheel)
        ttk.Label(right,text='현재 인식 정보',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Label(right,textvariable=self.summary,wraplength=315,justify='left').pack(anchor='w',pady=(0,18))
        ttk.Label(right,text='R19 · 게임 위 표시 위치 지정',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Label(right,text='① 현재 화면 종류 선택 → ② 미리보기의 실제 버튼 위치 클릭 → ③ 항목 이름 입력 후 저장. 훈련/스킬 화면 전환 시 직접 다시 확인해야 합니다.',style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=(2,8))
        choose=ttk.Frame(right);choose.pack(fill='x',pady=5)
        self.scene_choice=ttk.Combobox(choose,textvariable=self.marker_scene,values=SCENES,state='readonly',width=9)
        self.scene_choice.pack(side='left')
        self.scene_choice.bind('<<ComboboxSelected>>',lambda _e:self.scene_changed())
        ttk.Entry(choose,textvariable=self.marker_name,width=18).pack(side='left',padx=5)
        ttk.Button(right,text='미리보기에서 선택한 위치 등록',command=self.save_marker).pack(fill='x',pady=3)
        ttk.Button(right,text='이 화면 종류의 위치 초기화',command=self.clear_markers).pack(fill='x',pady=3)
        ttk.Checkbutton(right,text='현재 게임 화면 종류를 직접 확인했음',variable=self.scene_confirmed,command=self._update_hud).pack(anchor='w',pady=(8,10))
        ttk.Label(right,text='표시는 수동 보정이며 실제 버튼 자동 검출이 아닙니다. 창 크기나 화면 종류가 바뀌면 자동으로 숨깁니다.',style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=(0,16))
        ttk.Label(right,text='R20 · 장면 자동 판별',style='Section.TLabel').pack(anchor='w',pady=(4,5))
        ttk.Checkbutton(right,text='저장된 기준 이미지로 화면 종류 자동 판별',variable=self.auto_scene,
                        command=self.reset_recognition).pack(anchor='w')
        ar=ttk.Frame(right);ar.pack(fill='x',pady=4)
        ttk.Label(ar,text='기준 장면:').pack(side='left')
        ttk.Combobox(ar,textvariable=self.anchor_scene,values=SCENES_R20,
                     state='readonly',width=9).pack(side='left',padx=5)
        ttk.Button(right,text='선택한 위치를 장면 인식 기준으로 등록',command=self.register_anchor).pack(fill='x',pady=3)
        ttk.Button(right,text='이 장면의 인식 기준 삭제',command=self.clear_anchors).pack(fill='x',pady=3)
        ttk.Label(right,textvariable=self.auto_status,wraplength=305,style='Muted.TLabel').pack(anchor='w',pady=5)
        ttk.Label(right,text='장면당 서로 다른 특징 영역 2개가 필요해요. 버튼 아이콘이나 화면 제목을 미리보기에서 선택해 등록하세요. 화면 변경 시 자동 보류됩니다.',
                  style='Muted.TLabel',wraplength=305).pack(anchor='w',pady=(0,12))
        ttk.Button(right,text='스킬 목록 영역 지정 (좌상단·우하단)',command=self.start_skill_roi).pack(fill='x',pady=3)
        ttk.Label(right,text='스킬 표시에는 한국어 OCR과 코스별 R12 검수가 모두 필요합니다. 스킬 목록 위치를 한 번 지정하세요.',style='Muted.TLabel',wraplength=305).pack(anchor='w',pady=(2,12))
        ttk.Label(right,text='R21 · 훈련 버튼 자동 위치 탐지',style='Section.TLabel').pack(anchor='w',pady=(5,6))
        ttk.Label(right,text='훈련 화면에서 버튼 중앙을 한 번 선택해 특징 이미지를 등록하세요. 다음 화면부터 모양·위치를 검출합니다. 실제 한국 서버 정확도는 미검증입니다.',
                  style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=(0,5))
        self.button_choice=ttk.Combobox(right,textvariable=self.button_name,values=BUTTON_LABELS,width=19,state='readonly')
        self.button_choice.pack(fill='x',pady=4)
        ttk.Button(right,text='선택한 훈련 버튼의 모양 등록',command=self.register_training_button).pack(fill='x',pady=3)
        ttk.Button(right,text='선택한 훈련 버튼 등록 삭제',command=self.clear_training_button).pack(fill='x',pady=3)
        ttk.Label(right,textvariable=self.button_status,style='Muted.TLabel',wraplength=305).pack(anchor='w',pady=(5,16))
        ttk.Label(right,text='한 번 클릭 시험 (기본 비활성)',style='Section.TLabel').pack(anchor='w')
        ttk.Label(right,text='훈련·이벤트 자동 선택 기능이 아닙니다. 화면 속 한 버튼을 사용자 등록 후, 동일 화면이 두 번 확인된 경우에만 1회 클릭합니다.',
                  style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=8)
        ttk.Button(right,text='선택 좌표의 버튼 모양 등록',command=self.register_target).pack(fill='x',pady=5)
        ttk.Button(right,text='등록 버튼 1회 자동 클릭 허용',command=self.arm_click).pack(fill='x',pady=5)
        ttk.Button(right,text='클릭 허용 취소',command=self.disarm_click).pack(fill='x',pady=5)
        ttk.Label(right,textvariable=self.action_status,style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=10)
        ttk.Label(right,text='장애물: 실제 한국 서버 화면/훈련 버튼 자료가 없어 완전 자동 육성 판단과 클릭 연결은 아직 구현되지 않았습니다.',
                  style='Muted.TLabel',wraplength=310).pack(anchor='w',pady=(18,0))

    def refresh(self):
        try:
            self.backend=self.backend or WindowsGameBackend()
            games=self.backend.list_game_windows()
        except LiveError as exc:
            self.status.set(str(exc));return
        self.game_windows={f'{w.title} (창 {w.hwnd})':w for w in games}
        self.choice['values']=list(self.game_windows)
        if self.selected.get() not in self.game_windows:
            self.selected.set(next(iter(self.game_windows),'') )
        self.status.set(f'발견한 게임 창 {len(games)}개. 게임 창이 없으면 한국 PC 클라이언트를 실행하세요.')

    def start(self):
        if not self.game_windows:
            self.refresh()
        if self.selected.get() not in self.game_windows:
            self.status.set('먼저 한국 서버 게임 창을 선택하세요.');return
        self.stop(reset=False)
        self.running=True
        self.scene_confirmed.set(False)
        self.scene_engine.reset()
        self.verified_scene=None
        self._reset_button_detection()
        self.guard=OneClickGuard(self.backend)
        self.last_window=self.game_windows[self.selected.get()]
        self.status.set('감시 시작. 게임 화면을 클릭해서 게임 창을 활성화하세요.')
        self.after(450,self.poll)

    def stop(self,reset=True):
        self.running=False
        self.skill_evidence=[]
        self.scene_engine.reset()
        self.verified_scene=None
        self._reset_button_detection()
        self.scene_confirmed.set(False)
        if self.guard:self.guard.disarm()
        self.action_status.set('자동 클릭 중단')
        if reset:self.status.set('감시를 정지했습니다. 클릭도 함께 중단했습니다.')
        self._update_hud(active=False)

    def poll(self):
        if not self.running:
            return
        try:
            win=self.game_windows.get(self.selected.get())
            if win is None or self.last_window is None or win.hwnd!=self.last_window.hwnd:
                self.stop();self.status.set('선택한 창이 바뀌어 감시 중단');return
            image,current=self.backend.capture(win.hwnd)
            self.image=image
            self.last_window=current
            self.redraw()
            self._observe_scene(image)
            # A new capture must NEVER reuse the previous frame's button marks.
            self.button_hits=[]
            if self.verified_scene=='훈련' and self.auto_scene.get():
                self._schedule_button_scan(image,win.hwnd)
            elif self.button_request is None:
                self.button_tracker.reset()
            if self.verified_scene=='스킬':
                self._maybe_skill_ocr(image)
            else:self.skill_evidence=[]
            self.status.set(f'화면 갱신: {image.width}×{image.height} / 인식 결과는 아직 검수 전')
            if self.guard and self.guard.armed:
                message=self.guard.observe(image,win.hwnd)
                self.action_status.set(message)
            self._update_hud(active=True)
            now=time.monotonic()
            if not self._pending_ocr and now-self._last_ocr_at>=5:
                self._last_ocr_at=now
                self._pending_ocr=True
                threading.Thread(target=self._ocr_worker,args=(image.copy(),),daemon=True).start()
        except LiveError as exc:
            self.reset_recognition()
            if self.guard:self.guard.disarm()
            self.status.set(f'{exc} · 클릭은 자동 중단됩니다.')
            self._update_hud(active=False)
        except (OSError,ValueError) as exc:
            self.stop();self.status.set(f'화면 오류: {exc}')
        if self.running:
            self.after(self.interval_ms,self.poll)

    def reset_recognition(self):
        self.scene_engine.reset()
        self.verified_scene=None
        self.skill_evidence=[]
        self._reset_button_detection()
        self.scene_confirmed.set(False)
        self._update_hud(active=False)

    def _observe_scene(self, image):
        if not self.auto_scene.get():return
        guess=self.scene_engine.observe(image,self.anchors)
        if guess.scene is None:
            self._reset_button_detection()
            self.verified_scene=None
            self.scene_confirmed.set(False)
            self.auto_status.set(guess.reason)
            return
        if self.verified_scene != guess.scene:
            self._reset_button_detection()
            if self.guard:self.guard.disarm()
            self.verified_scene=guess.scene
            # An identified screen is NOT proof that an individual skill is currently visible.
            self.scene_confirmed.set(guess.scene=='훈련')
            if guess.scene in SCENES:
                self.marker_scene.set(guess.scene)
        self.auto_status.set(f'{guess.scene} 화면 자동 확인 (영상/게임에서 실제 인식 정확도는 미검증)')

    def _reset_button_detection(self):
        self.button_epoch+=1
        self.button_request=None
        self.button_hits=[]
        self.button_tracker.reset()

    def register_training_button(self):
        if self.image is None or self.pending_position is None or self.last_window is None:
            self.button_status.set('먼저 실제 훈련 화면에서 버튼 중앙을 선택하세요.')
            return
        if self.verified_scene not in (None,'훈련') or self.marker_scene.get()!='훈련':
            self.button_status.set('훈련 화면을 확인한 뒤에만 등록해 주세요.')
            return
        try:
            pattern=make_pattern(self.image,self.button_name.get(),*self.pending_position)
            updated=[p for p in self.button_patterns if p.label!=pattern.label]+[pattern]
            save_patterns(button_pattern_path(),updated)
            self.button_patterns=updated
            self._reset_button_detection()
            self.button_status.set(f'{pattern.label} 특징 등록됨 · 총 {len(updated)}개 / 실제 게임 확인 전')
        except (DetectionError,OSError) as exc:
            self.button_status.set(f'버튼 등록 실패: {exc}')

    def clear_training_button(self):
        label=self.button_name.get()
        updated=[p for p in self.button_patterns if p.label!=label]
        try:
            save_patterns(button_pattern_path(),updated)
            self.button_patterns=updated
            self._reset_button_detection()
            self.button_status.set(f'{label} 등록 삭제됨')
            self._update_hud(active=False)
        except (OSError,DetectionError) as exc:self.button_status.set(str(exc))

    def _schedule_button_scan(self,image,hwnd):
        if not self.button_patterns or self.button_request is not None:return
        request=(self.button_epoch,hwnd,id(image))
        self.button_request=request
        patterns=tuple(self.button_patterns)
        def worker():
            try:
                hits=[hit for pattern in patterns
                      if (hit:=find_button(image,pattern)) is not None]
                self.button_q.put((request,hits,None))
            except (DetectionError,DetectorUnavailable,ValueError,OSError) as exc:
                self.button_q.put((request,[],str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _apply_button_scan(self,request,hits,error):
        if request != self.button_request:return False
        self.button_request=None
        if (not self.running or self.verified_scene!='훈련' or not self.last_window
                or self.last_window.hwnd!=request[1] or self.image is None
                or id(self.image)!=request[2]):
            self._reset_button_detection();return False
        if error:
            self.button_tracker.reset()
            self.button_hits=[]
            self.button_status.set('탐지 보류: '+error[:110])
        else:
            self.button_hits=self.button_tracker.observe_hits(hits,'훈련')
            self.button_status.set(f'훈련 버튼 {len(self.button_hits)}개 위치 연속 확인 · 등록 {len(self.button_patterns)}개 '
                                   '· 실게임 정확도 미검증' if self.button_hits else
                                   '버튼 위치 재확인 중 또는 유사 버튼/위치 불일치 · 표시 보류')
        return True

    def start_skill_roi(self):
        self.skill_roi_first=None
        self.skill_roi_calibrating=True
        self.auto_status.set('스킬 구매 화면에서 목록 왼쪽 위와 오른쪽 아래를 차례로 클릭하세요.')

    def _mark_skill_corner(self,pos):
        if not self.skill_roi_first:
            self.skill_roi_first=pos
            self.auto_status.set('스킬 목록 오른쪽 아래를 클릭하세요.')
            return
        x,y=self.skill_roi_first
        x2,y2=pos
        self.skill_roi_first=None
        self.skill_roi_calibrating=False
        if self.image is None:return
        try:
            roi=SkillListRegion(min(x,x2),min(y,y2),abs(x2-x),abs(y2-y),
                                self.image.width,self.image.height).validate()
            save_skill_region(skill_region_path(),roi)
            self.skill_region=roi
            self.skill_evidence=[]
            self.auto_status.set('스킬 목록 위치 저장됨 · 이 영역 안의 실제 OCR 스킬만 표시합니다.')
        except (ValueError,OSError) as exc:self.auto_status.set(f'스킬 목록 영역 설정 실패: {exc}')

    def register_anchor(self):
        if self.image is None or not self.pending_position or not self.last_window:
            self.auto_status.set('화면 캡처에서 특징적인 UI 요소의 중앙을 먼저 클릭하세요.')
            return
        x,y=self.pending_position
        w,h=.12,.060
        x=max(.012,min(.988-w,x-w/2))
        y=max(.012,min(.988-h,y-h/2))
        try:
            anchor=make_anchor(self.image,self.anchor_scene.get(),x,y,w,h)
            group=[a for a in self.anchors if a.scene==anchor.scene]
            if len(group)>=4:raise SceneError('한 화면당 최대 4개까지 등록 가능합니다.')
            if any(abs(a.x-anchor.x)<.065 and abs(a.y-anchor.y)<.038 for a in group):
                raise SceneError('같은 곳이 아닌, 서로 떨어진 다른 특징 영역을 선택하세요.')
            self.anchors.append(anchor)
            save_library(scene_profile_path(),self.anchors)
            self.reset_recognition()
            self.auto_status.set(f'{anchor.scene} 기준 {len(group)+1}개 등록 · 2개부터 자동 판별')
        except (SceneError,ValueError,OSError) as exc:
            self.auto_status.set(f'기준 이미지 저장 실패: {exc}')

    def clear_anchors(self):
        scene=self.anchor_scene.get()
        self.anchors=[a for a in self.anchors if a.scene!=scene]
        try:
            save_library(scene_profile_path(),self.anchors)
            self.reset_recognition()
            self.auto_status.set(f'{scene} 기준 이미지 삭제')
        except (SceneError,ValueError,OSError) as exc:self.auto_status.set(str(exc))

    def _maybe_skill_ocr(self,image):
        # OCR is advisory, never used for game clicking. Only R12-verified skill names.
        if self.skill_pending or time.monotonic()-self._last_skill_at<3.5:return
        try:context=self.context_provider() or {}
        except (ValueError,TypeError,AttributeError):return
        if not context.get('skill_checked') or self.skill_region is None:return
        names=[n for n,v in (context.get('skill_advice') or {}).items()
               if v.get('verdict','').startswith(('우선 검토','조건 일치','조건 불일치','비효율'))]
        if not names:return
        binary=tesseract_executable()
        if not binary:
            self.auto_status.set('스킬 이름 OCR 사용 불가: Tesseract 한국어 인식기 필요')
            return
        self.skill_pending=True
        self._last_skill_at=time.monotonic()
        scene_id=self.last_window.hwnd if self.last_window else 0
        def work():
            try:
                hits=run_skill_ocr(image,binary,names,region=self.skill_region)
                crops=[(hit,evidence_crop(image,hit)) for hit in hits]
                self.skill_ocr_q.put((scene_id,crops))
            finally:self.skill_pending=False
        threading.Thread(target=work,daemon=True).start()

    def _ocr_worker(self,image):
        output=[]
        try:
            if not profile_path().exists():
                self._ocr_results.put('게임 스탯 영역을 R4에서 지정하면 실시간 숫자 후보를 읽을 수 있어요.')
                return
            prof=read_profile(profile_path())
            if not prof.matches_image(image):
                self._ocr_results.put('R4 인식 영역과 게임 화면 비율이 달라서 숫자 인식을 보류했어요.')
                return
            binary=tesseract_executable()
            if not binary:
                self._ocr_results.put('Tesseract OCR을 설치해야 스탯을 읽을 수 있어요. 현재는 화면 표시만 가능합니다.')
                return
            for field in ('스피드','스태미나','파워','근성','지능','체력'):
                reg=prof.regions.get(field)
                if not reg:
                    continue
                txt,conf=_recognize_one(image.crop(reg.pixel_box(image.width,image.height)),binary,timeout=4)
                value=parse_numeric(txt,field)
                if value is not None and conf is not None and conf>=80:
                    output.append(f'{field}: {value} (OCR 후보)')
                else:
                    output.append(f'{field}: 확인 불가')
            self._ocr_results.put(' | '.join(output) if output else 'R4에서 숫자 영역을 먼저 지정해 주세요.')
        except Exception as exc:
            self._ocr_results.put(f'인식 오류: {exc}')
        finally:
            self._pending_ocr=False

    def _drain(self):
        try:
            while True:
                request,hits,error=self.button_q.get_nowait()
                if self._apply_button_scan(request,hits,error):self._update_hud()
        except queue.Empty:pass
        try:
            while True:
                hwnd, entries=self.skill_ocr_q.get_nowait()
                if self.running and self.verified_scene=='스킬' and self.last_window and self.last_window.hwnd==hwnd:
                    self.skill_evidence=entries
        except queue.Empty:pass
        try:
            while True:
                self.summary.set(self._ocr_results.get_nowait())
        except queue.Empty:
            pass
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay_summary.config(text=self.summary.get())
            self.overlay_action.config(text=self.action_status.get())
        if self.winfo_exists():
            self.after(150,self._drain)

    def redraw(self):
        self.canvas.delete('all')
        if self.image is None:
            self.canvas.create_text(320,170,text='게임 창 감시를 시작하면 여기에 화면이 나타납니다.',fill='#d1dae5')
            return
        width=max(150,self.canvas.winfo_width()-16)
        height=max(150,self.canvas.winfo_height()-16)
        scale=min(width/self.image.width,height/self.image.height,1.0)
        w,h=int(self.image.width*scale),int(self.image.height*scale)
        left=(self.canvas.winfo_width()-w)//2
        top=(self.canvas.winfo_height()-h)//2
        self.photo=ImageTk.PhotoImage(self.image.resize((w,h)))
        self.canvas.create_image(left,top,image=self.photo,anchor='nw')
        self.display_box=(left,top,w,h)
        if self.pending_position:
            x=left+self.pending_position[0]*w
            y=top+self.pending_position[1]*h
            self.canvas.create_oval(x-9,y-9,x+9,y+9,outline='#ffcc66',width=2)

    def mark_target(self,event):
        if self.image is None or not self.display_box or not self.last_window:
            return
        left,top,w,h=self.display_box
        if not (left<=event.x<left+w and top<=event.y<top+h):return
        pos=((event.x-left)/w,(event.y-top)/h)
        if self.skill_roi_calibrating:
            self._mark_skill_corner(pos)
            return
        self.pending_position=pos
        self.redraw()
        self.action_status.set('화면 위치를 골랐습니다. R19 위치 저장은 자동 클릭과 별개입니다.')

    def register_target(self):
        if not self.image or not self.last_window or not self.pending_position:
            self.action_status.set('먼저 실제 게임 화면에서 버튼 위치를 표시하세요.');return
        try:
            # Register uses last captured frame. Real action always requires same visual match.
            template=create_template(self.image,self.last_window.hwnd,*self.pending_position)
            if self.guard is None:
                self.guard=OneClickGuard(self.backend)
            self.guard.register(template)
            self.action_status.set('버튼 모양을 등록했어요. 자동 클릭은 아직 꺼져 있습니다.')
        except LiveError as exc:self.action_status.set(str(exc))

    def arm_click(self):
        if not self.running or self.guard is None or self.guard.template is None:
            self.action_status.set('감시 시작 후 실제 화면의 버튼을 등록해야 합니다.');return
        if not messagebox.askyesno('1회 자동 클릭 확인',
          '실제 게임 창에서 방금 등록한 버튼이 동일한 모습으로 2회 연속 확인되면 딱 1회 클릭합니다.\n'
          '아직 무인도 상황 판단이나 실제 서버 검증이 완료되지 않았습니다.\n'
          '유료 재화·구매·확정·포기 버튼은 등록하지 마세요.\n'
          '게임 운영정책도 직접 확인해야 합니다. 진행할까요?'):
            return
        try:
            self.guard.arm()
            self.action_status.set('1회 클릭 대기 중. 게임 창으로 이동하세요. 불일치/창 전환 시 자동 중단됩니다.')
        except LiveError as exc:self.action_status.set(str(exc))

    def disarm_click(self):
        if self.guard:self.guard.disarm()
        self.action_status.set('자동 클릭 취소됨')

    def toggle_overlay(self):
        opened=self.hud.open()
        self.status.set('게임 화면 위 후보 표시와 옆 정보창이 열렸습니다.' if opened else 'R19 정보창을 닫았습니다.')
        self._update_hud()

    def scene_changed(self):
        self.scene_confirmed.set(False)
        self.pending_position=None
        self.redraw()
        self.marker_name.set('스피드' if self.marker_scene.get()=='훈련' else '왕수')
        self._update_hud(active=False)

    def save_marker(self):
        if not self.pending_position or self.image is None or self.last_window is None:
            self.action_status.set('먼저 게임 미리보기에서 표시할 위치를 클릭해 주세요.');return
        try:
            mark=Mark(self.marker_scene.get(),self.marker_name.get().strip(),
                      self.pending_position[0],self.pending_position[1],
                      self.image.width,self.image.height).validate()
            self.marks=[m for m in self.marks if not (m.scene==mark.scene and m.name==mark.name)]
            self.marks.append(mark)
            save_marks(default_mark_path(),self.marks)
            self.scene_confirmed.set(False)
            self.action_status.set(f'{mark.scene} · {mark.name} 수동 좌표 저장됨. 추천 자체는 R6/R12 검수 여부에 따름.')
            self._update_hud()
        except (ValueError,OSError) as exc:self.action_status.set(f'위치 저장 실패: {exc}')

    def clear_markers(self):
        scene=self.marker_scene.get()
        self.marks=[m for m in self.marks if m.scene!=scene]
        self.scene_confirmed.set(False)
        try:save_marks(default_mark_path(),self.marks)
        except OSError as exc:self.action_status.set(f'초기화 실패: {exc}');return
        self.action_status.set(scene+' 화면 위치를 초기화했습니다.')
        self._update_hud(active=False)

    def _update_hud(self,active=None):
        if active is None:
            active=(self.running and self.backend is not None and self.last_window is not None
                    and self.backend.active(self.last_window.hwnd))
        # Training landmarks can be displayed after automatic scene verification.
        # Skill list positions are NOT fixed: only current visible text OCR can mark them.
        marks=self.marks
        confirmed=self.scene_confirmed.get()
        if self.auto_scene.get() and self.verified_scene=='훈련' and self.last_window:
            # R21: only *visually confirmed* actual button locations, never old R19
            # estimated coordinates. A valid CURRENT R6 choice is also required.
            marks=[]
            context=self.context_provider() or {}
            marks=recommended_training_marks(self.button_hits,context,
                                             self.last_window.width,self.last_window.height)
            confirmed=bool(marks) and confirmed
        if self.auto_scene.get() and self.verified_scene=='스킬':
            confirmed=False
            marks=[]
            if self.image is not None:
                current=[]
                for hit,crop in self.skill_evidence:
                    if not same_visible_text(crop,self.image,hit):continue
                    # Source must be the same frame size; stale OCR disappears after scrolling.
                    current.append(Mark('스킬',hit.name,(hit.x+hit.w/2)/self.image.width,
                                        (hit.y+hit.h/2)/self.image.height,
                                        self.image.width,self.image.height))
                marks=current
                confirmed=bool(current)
        self.hud.update(self.last_window if self.running else None,
                        marks,self.marker_scene.get(),confirmed,active)

    def _destroyed(self,event):
        if event.widget is self:
            self.running=False
            if self.guard:self.guard.disarm()
            self.hud.close()
