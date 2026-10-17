"""R59 manual registration of visible KR setup choices, passive only."""
from __future__ import annotations

import ctypes
import os
import tkinter as tk
from tkinter import ttk

from PIL import ImageGrab, ImageTk

from capture_pack_r29 import check_capture_target
from companion_core import choose_window
from companion_window import discover_windows
from screen_r4 import user_dir
from setup_choices_r59 import BRANCHES, register_choice, save_choice
from visual_controls_r50 import _bbox


class SetupChoiceRegistration(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("R59 육성 시작 전 선택지 등록 · 자동 클릭 없음")
        self.geometry("770x850")
        self.minsize(540, 610)
        self.branch = tk.StringVar(value="normal")
        self.step = tk.StringVar(value="")
        self.choice = tk.StringVar(value="")
        self.mode = tk.StringVar(value="scene")
        self.confirmed = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="일반 시작 또는 이벤트 시작을 선택하고 실제 한국 게임 화면을 등록하세요.")
        self.image = None
        self.game = None
        self.photo = None
        self.drag = None
        self.extent = (1, 1)
        self.boxes = {}
        tk.Label(self, text="고유한 화면 표식과 선택 버튼의 두 영역을 따로 지정합니다. 선택 버튼을 누르거나 게임을 변경하지 않습니다.",
                 wraplength=710,justify="left").pack(fill="x",padx=9,pady=7)
        line = tk.Frame(self)
        line.pack(fill="x",padx=9)
        ttk.Combobox(line, textvariable=self.branch,
                     values=BRANCHES,state="readonly",width=10).pack(side="left")
        tk.Label(line,text="단계").pack(side="left",padx=(6,2))
        tk.Entry(line,textvariable=self.step,width=15).pack(side="left")
        tk.Label(line,text="화면 선택지").pack(side="left",padx=(6,2))
        tk.Entry(line,textvariable=self.choice,width=19).pack(side="left")
        line2=tk.Frame(self);line2.pack(fill="x",padx=9,pady=(5,0))
        tk.Button(line2,text="4초 후 게임 화면 캡처",command=self.schedule_capture).pack(side="left",padx=4)
        for name,desc in (("scene","고유한 화면 표식"),("button","선택지 버튼")):
            tk.Radiobutton(line2,text=desc,variable=self.mode,value=name).pack(side="left",padx=5)
        self.canvas=tk.Canvas(self,bg="#142338",highlightthickness=0)
        self.canvas.pack(fill="both",expand=True,padx=9,pady=8)
        self.canvas.bind("<Configure>",lambda event:self.redraw())
        self.canvas.bind("<ButtonPress-1>",self.down)
        self.canvas.bind("<ButtonRelease-1>",self.up)
        tk.Checkbutton(self,text="실제 한국 서버 화면의 선택지 명칭과 위치를 직접 확인했습니다",
                       variable=self.confirmed).pack(anchor="w",padx=9)
        tk.Button(self,text="현재 선택지 등록 (기존 선택지 보존)",
                  command=self.save).pack(fill="x",padx=9,pady=5)
        tk.Label(self,textvariable=self.status,wraplength=730,justify="left",
                 fg="#98482e").pack(fill="x",padx=9,pady=6)

    def schedule_capture(self):
        if os.name != "nt" or self.master.game is None:
            self.status.set("Windows 실제 게임 창을 먼저 활성화하세요.")
            return
        self.game=self.master.game
        self.withdraw()
        self.after(4000,self.capture)

    def capture(self):
        try:
            current,_=choose_window(discover_windows())
            panel=(self.master.winfo_rootx(),self.master.winfo_rooty(),
                   self.master.winfo_rootx()+self.master.winfo_width(),
                   self.master.winfo_rooty()+self.master.winfo_height())
            rect=check_capture_target(
                self.game,current,ctypes.windll.user32.GetForegroundWindow(),panel)
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            if image.size != (current.width,current.height):
                raise ValueError("게임 창 크기가 캡처 이미지와 다릅니다")
            self.image=image.convert("RGB")
            self.boxes.clear()
            self.confirmed.set(False)
            self.redraw()
            self.status.set("화면 캡처 완료 · 고유 표식 및 선택지 버튼을 각각 드래그하세요.")
        except (OSError,ValueError,RuntimeError) as exc:
            self.status.set("화면 캡처 보류: "+str(exc)[:170])
        finally:
            self.deiconify()

    def redraw(self):
        self.canvas.delete("all")
        if self.image is None:
            return
        cw=max(1,self.canvas.winfo_width()-10)
        ch=max(1,self.canvas.winfo_height()-10)
        ratio=min(cw/self.image.width,ch/self.image.height)
        w,h=max(1,round(self.image.width*ratio)),max(1,round(self.image.height*ratio))
        self.extent=(w,h)
        self.photo=ImageTk.PhotoImage(self.image.resize((w,h)))
        self.canvas.create_image(5,5,image=self.photo,anchor="nw")
        for kind,box in self.boxes.items():
            x1,y1,x2,y2=box
            self.canvas.create_rectangle(5+x1*w,5+y1*h,5+x2*w,5+y2*h,
                        outline="#FBC96D" if kind=="button" else "#64DCC8",width=3)

    def down(self,event):
        self.drag=(event.x,event.y)

    def up(self,event):
        if self.image is None or self.drag is None:
            return
        x0,y0=self.drag
        self.drag=None
        w,h=self.extent
        x1,x2=sorted(((x0-5)/w,(event.x-5)/w))
        y1,y2=sorted(((y0-5)/h,(event.y-5)/h))
        try:
            self.boxes[self.mode.get()]=_bbox((
                max(0,x1),max(0,y1),min(1,x2),min(1,y2)))
            self.redraw()
        except ValueError as exc:
            self.status.set("선택 영역 오류: "+str(exc)[:130])

    def save(self):
        try:
            if self.image is None or set(self.boxes) != {"scene","button"}:
                raise ValueError("같은 화면에서 고유 표식과 선택지 버튼을 모두 지정하세요")
            if not self.confirmed.get():
                raise ValueError("실제 게임에서 선택지를 확인했다고 체크하세요")
            profile=register_choice(
                self.image,branch=self.branch.get(),step=self.step.get(),
                choice=self.choice.get(),scene_box=self.boxes["scene"],
                button_box=self.boxes["button"],reviewed=True)
            save_choice(user_dir()/"r59_setup_choices.json",profile)
            self.master.setup_choice_tracker.reset()
            self.status.set("등록 완료 · 일반/이벤트 경로별로 구분 · 자동 클릭은 아직 허용하지 않음")
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.status.set("선택지 저장 보류: "+str(exc)[:165])
