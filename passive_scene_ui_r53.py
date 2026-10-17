"""One-time user-directed calibration of passive R20 Korean game scenes.

Only TWO independent cropped landmarks are saved, with no game input, upload,
ML labels, or modification to existing R50 authorizations.
"""
from __future__ import annotations
import ctypes
import os
import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab, ImageTk
from capture_pack_r29 import check_capture_target
from companion_core import choose_window
from companion_window import discover_windows
from scene_recognition_r20 import (SCENES_R20, SceneError, make_anchor,
                                   load_library, save_library, profile_path)

class PassiveSceneRegistration(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("R53 한국 서버 장면 기준 등록 · 게임 조작 없음")
        self.geometry("760x880")
        self.minsize(560,620)
        self.scene=tk.StringVar(value="레이스")
        self.anchor_type=tk.StringVar(value="A")
        self.status=tk.StringVar(value="게임을 연 뒤 4초 뒤 캡처를 누르세요.")
        self.image=None
        self.photo=None
        self.boxes={}
        self.start_point=None
        self.image_extent=(1,1)
        self.expected_game=None
        tk.Label(self,text="화면 종류를 고르고 서로 떨어진 고유 영역 두 곳을 표시하세요.",
                 wraplength=650).pack(anchor="w",padx=10,pady=8)
        bar=tk.Frame(self);bar.pack(fill="x",padx=10)
        ttk.Combobox(bar,textvariable=self.scene,values=SCENES_R20,
                     state="readonly",width=16).pack(side="left",padx=3)
        tk.Button(bar,text="4초 뒤 게임 화면 캡처",command=self.schedule_capture).pack(side="left",padx=5)
        for label in ("A","B"):
            tk.Radiobutton(bar,text="기준 "+label,variable=self.anchor_type,value=label).pack(side="left")
        self.canvas=tk.Canvas(self,bg="#172236",highlightthickness=0)
        self.canvas.pack(fill="both",expand=True,padx=10,pady=8)
        self.canvas.bind("<ButtonPress-1>",self.mouse_down)
        self.canvas.bind("<ButtonRelease-1>",self.mouse_up)
        self.canvas.bind("<Configure>",lambda event:self.redraw())
        tk.Button(self,text="고유 영역 2개 저장 (기존 기준 보존)",
                  command=self.save).pack(fill="x",padx=10,pady=4)
        tk.Label(self,textvariable=self.status,fg="#9B3A2B",wraplength=670,
                 justify="left").pack(fill="x",padx=10,pady=8)

    def schedule_capture(self):
        if os.name!="nt" or self.master.game is None:
            self.status.set("Windows 게임 창이 감지된 상태에서만 캡처할 수 있습니다.")
            return
        self.expected_game=self.master.game
        self.withdraw()
        self.after(4000,self.capture)

    def capture(self):
        try:
            game,_=choose_window(discover_windows())
            panel=(self.master.winfo_rootx(),self.master.winfo_rooty(),
                   self.master.winfo_rootx()+self.master.winfo_width(),
                   self.master.winfo_rooty()+self.master.winfo_height())
            rect=check_capture_target(self.expected_game,game,
                    ctypes.windll.user32.GetForegroundWindow(),panel)
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            if image.size!=(game.width,game.height):
                raise SceneError("실제 게임 창과 이미지 크기 불일치")
            self.image=image.convert("RGB")
            self.boxes.clear()
            self.redraw()
            self.status.set("캡처 성공. 기준 A와 B를 별개의 고유 영역으로 드래그하세요.")
        except (OSError,RuntimeError,ValueError) as exc:
            self.status.set("캡처 보류: "+str(exc)[:140])
        finally:
            self.deiconify()

    def redraw(self):
        self.canvas.delete("all")
        if self.image is None:return
        w=max(1,self.canvas.winfo_width()-10)
        h=max(1,self.canvas.winfo_height()-10)
        scale=min(w/self.image.width,h/self.image.height)
        sw,sh=max(1,round(scale*self.image.width)),max(1,round(scale*self.image.height))
        self.photo=ImageTk.PhotoImage(self.image.resize((sw,sh)))
        self.image_extent=(sw,sh)
        self.canvas.create_image(5,5,image=self.photo,anchor="nw")
        for label,(x,y,bw,bh) in self.boxes.items():
            self.canvas.create_rectangle(5+x*sw,5+y*sh,5+(x+bw)*sw,
                 5+(y+bh)*sh,outline="#f8ca54",width=3)
            self.canvas.create_text(5+x*sw,5+y*sh-8,text=label,
                                    fill="#f8ca54",anchor="w")

    def mouse_down(self,event):
        self.start_point=(event.x,event.y)

    def mouse_up(self,event):
        if self.start_point is None or self.image is None:return
        x0,y0=self.start_point
        self.start_point=None
        sw,sh=self.image_extent
        x1,x2=sorted(((x0-5)/sw,(event.x-5)/sw))
        y1,y2=sorted(((y0-5)/sh,(event.y-5)/sh))
        x1,y1=max(.01,x1),max(.01,y1)
        x2,y2=min(.99,x2),min(.99,y2)
        box=(x1,y1,x2-x1,y2-y1)
        try:
            make_anchor(self.image,self.scene.get(),*box)
        except (SceneError,OSError,ValueError) as exc:
            self.status.set("영역 오류: "+str(exc)[:130])
            return
        self.boxes[self.anchor_type.get()]=box
        self.redraw()

    def save(self):
        try:
            if self.image is None or set(self.boxes)!={"A","B"}:
                raise SceneError("같은 화면에서 A와 B 두 영역을 선택하세요")
            scene=self.scene.get()
            old=load_library(profile_path())
            if sum(a.scene==scene for a in old)>=2:
                raise SceneError("기존 등록이 있어 덮어쓰지 않습니다. 이전 기준을 검토하세요")
            a,b=[make_anchor(self.image,scene,*self.boxes[k]) for k in ("A","B")]
            from scene_recognition_r20 import independent_anchors
            if not independent_anchors(a,b):
                raise SceneError("두 영역이 겹칩니다. 서로 다른 위치를 고르세요")
            save_library(profile_path(),[*old,a,b])
            self.master.scene_tracker.reset()
            self.master.scene_fusion.reset()
            self.status.set("장면 기준 2개 저장 · 연속 화면 확인 이후 표시 (자동 클릭 없음)")
        except (SceneError,OSError,ValueError,TypeError) as exc:
            self.status.set("저장 보류: "+str(exc)[:165])
