"""R54 optional user-marked, passive numeric ROI registration UI."""
from __future__ import annotations

import ctypes
import os
import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab, ImageTk

from capture_pack_r29 import check_capture_target
from companion_core import choose_window
from companion_window import discover_windows
from passive_numbers_r54 import SCENES, NUMERIC_FIELDS, LiveNumberRegion, save_region
from screen_r4 import user_dir
from visual_controls_r50 import _bbox


class PassiveNumberRegistration(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("R54 한국 서버 수치 OCR 영역 등록 · 게임 입력 없음")
        self.geometry("745x830")
        self.minsize(560,620)
        self.scene = tk.StringVar(value="훈련")
        self.field = tk.StringVar(value="스피드")
        self.reviewed = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="실제 게임의 해당 숫자 화면을 띄운 뒤 캡처를 누르세요.")
        self.image = None
        self.photo = None
        self.region = None
        self.drag_start = None
        self.photo_size = (1,1)
        self.game = None

        tk.Label(self,text="읽을 숫자 하나를 선택하고, 그 숫자만 포함하도록 드래그합니다. 등록된 OCR도 학습 정답이 아닙니다.",
                 wraplength=675,justify="left").pack(anchor="w",padx=9,pady=8)
        bar=tk.Frame(self);bar.pack(fill="x",padx=9)
        ttk.Combobox(bar,textvariable=self.scene,values=SCENES,
                     state="readonly",width=12).pack(side="left")
        ttk.Combobox(bar,textvariable=self.field,values=NUMERIC_FIELDS,
                     state="readonly",width=12).pack(side="left",padx=5)
        tk.Button(bar,text="4초 뒤 게임 화면 캡처",command=self.schedule_capture).pack(side="left")
        self.canvas=tk.Canvas(self,bg="#172236",highlightthickness=0)
        self.canvas.pack(fill="both",expand=True,padx=9,pady=8)
        self.canvas.bind("<Configure>",lambda event:self.redraw())
        self.canvas.bind("<ButtonPress-1>",self.drag_down)
        self.canvas.bind("<ButtonRelease-1>",self.drag_up)
        tk.Checkbutton(self,text="해당 화면에서 이 숫자의 위치를 직접 확인했습니다",
                       variable=self.reviewed).pack(anchor="w",padx=9)
        tk.Button(self,text="숫자 영역 저장 (기존 설정 덮어쓰기 없음)",
                  command=self.save).pack(fill="x",padx=9,pady=5)
        tk.Label(self,textvariable=self.status,fg="#99402A",wraplength=680,
                 justify="left").pack(fill="x",padx=9,pady=6)

    def schedule_capture(self):
        if os.name != "nt" or self.master.game is None:
            self.status.set("Windows에서 실제 우마무스메 게임 창이 감지되어야 합니다.")
            return
        self.game = self.master.game
        self.withdraw()
        self.after(4000,self.capture)

    def capture(self):
        try:
            game,_=choose_window(discover_windows())
            panel=(self.master.winfo_rootx(),self.master.winfo_rooty(),
                   self.master.winfo_rootx()+self.master.winfo_width(),
                   self.master.winfo_rooty()+self.master.winfo_height())
            rect=check_capture_target(self.game,game,
                       ctypes.windll.user32.GetForegroundWindow(),panel)
            image=ImageGrab.grab(bbox=rect,all_screens=True)
            if image.size != (game.width,game.height):
                raise ValueError("게임 창과 화면 크기가 다릅니다")
            self.image=image.convert("RGB")
            self.region=None
            self.reviewed.set(False)
            self.redraw()
            self.status.set("캡처 완료. 숫자만 표시된 부분을 드래그하세요.")
        except (OSError,RuntimeError,ValueError) as exc:
            self.status.set("캡처 오류: "+str(exc)[:140])
        finally:
            self.deiconify()

    def redraw(self):
        self.canvas.delete("all")
        if self.image is None:
            return
        width=max(1,self.canvas.winfo_width()-10)
        height=max(1,self.canvas.winfo_height()-10)
        factor=min(width/self.image.width,height/self.image.height)
        w,h=max(1,round(self.image.width*factor)),max(1,round(self.image.height*factor))
        self.photo=ImageTk.PhotoImage(self.image.resize((w,h)))
        self.photo_size=(w,h)
        self.canvas.create_image(5,5,image=self.photo,anchor="nw")
        if self.region is not None:
            x1,y1,x2,y2=self.region
            self.canvas.create_rectangle(5+x1*w,5+y1*h,5+x2*w,5+y2*h,
                                         outline="#F9C56B",width=3)

    def drag_down(self,event):
        self.drag_start=(event.x,event.y)

    def drag_up(self,event):
        if self.drag_start is None or self.image is None:
            return
        x0,y0=self.drag_start
        self.drag_start=None
        w,h=self.photo_size
        x1,x2=sorted(((x0-5)/w,(event.x-5)/w))
        y1,y2=sorted(((y0-5)/h,(event.y-5)/h))
        rect=(max(0,x1),max(0,y1),min(1,x2),min(1,y2))
        try:
            box=_bbox(rect)
            LiveNumberRegion(self.scene.get(),self.field.get(),box,
                             self.image.width,self.image.height,True).validate()
        except ValueError as exc:
            self.status.set("숫자 영역이 올바르지 않습니다: "+str(exc)[:110])
            return
        self.region=box
        self.redraw()

    def save(self):
        try:
            if self.image is None or self.region is None or not self.reviewed.get():
                raise ValueError("실제 숫자 화면과 영역을 선택한 뒤 직접 확인을 체크하세요")
            roi=LiveNumberRegion(self.scene.get(),self.field.get(),self.region,
                                self.image.width,self.image.height,True).validate()
            dest=user_dir()/"r54_numeric_regions.json"
            save_region(dest,roi)
            self.master.numeric_reader.reset()
            self.status.set("OCR 수치 영역 저장 완료 · 인식값은 검수 전 후보로만 표시됩니다.")
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.status.set("저장 보류: "+str(exc)[:165])
