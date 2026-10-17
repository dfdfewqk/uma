"""R50 local, optional visual calibration dialog for confirmed Korean UI controls.

User takes one foreground screenshot per screen and drags THREE optional
regions: a static scene marker, a particular game button and numeric OCR box.
No screenshot is saved: only the two cropped patches and numeric ROI coords.
This dialogue never clicks inside the game or edits existing profiles.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from visual_controls_r50 import register,save_profile
from skill_authorizations_r51 import SkillAuthorization,save_authorization
from numeric_observer_r50 import NumberROI,save_roi,FIELDS
from screen_r4 import user_dir

STAGE_CHOICES=("setup","tp","skill","result","repeat")
DEFAULT_ACTION={
    "setup":"start_run","tp":"free_tp:verified_item",
    "skill":"skill:verified_target","result":"finish_run:ordinary",
    "repeat":"repeat_run",
}


class CalibrationWindow(tk.Toplevel):
    def __init__(self,owner):
        super().__init__(owner)
        self.title("R50 한국 서버 화면별 버튼/숫자 영역 등록 · 게임 조작 없음")
        self.geometry("850x900")
        self.minsize(710,680)
        self.image=None
        self.photo=None
        self.regions={}
        self.drag_start=None
        self.dimensions=(1,1)
        self.image_window=None
        self.stage=tk.StringVar(value="tp")
        self.action=tk.StringVar(value=DEFAULT_ACTION["tp"])
        self.field=tk.StringVar(value="tp")
        self.mode=tk.StringVar(value="scene")
        self.free_confirmed=tk.BooleanVar(value=False)
        self.skill_conditions_reviewed=tk.BooleanVar(value=False)
        self.reviewed=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value="먼저 게임 화면을 띄우고 4초 뒤 화면 캡처를 눌러주세요.")
        self.draw()

    def draw(self):
        header=tk.Frame(self);header.pack(fill="x",padx=8,pady=7)
        tk.Label(header,text="장면 등록은 실제 게임 화면을 직접 확인한 후 진행합니다.",
                 font=("Malgun Gothic",10,"bold")).pack(anchor="w")
        tk.Label(header,text="무료 TP·스킬 가격·보유 Pt 등은 실제 수치를 검수해야 합니다. 화면 등록만으로 자동 결제/구매하지 않습니다.",
                 wraplength=800,justify="left").pack(anchor="w")
        line=tk.Frame(self);line.pack(fill="x",padx=8,pady=4)
        tk.Button(line,text="4초 뒤 게임 화면 캡처",command=self.delayed_capture).pack(side="left")
        tk.Label(line,text="장면").pack(side="left",padx=5)
        scene=ttk.Combobox(line,textvariable=self.stage,values=STAGE_CHOICES,state="readonly",width=9)
        scene.pack(side="left");scene.bind("<<ComboboxSelected>>",self._stage_changed)
        tk.Label(line,text="버튼 키").pack(side="left",padx=5)
        tk.Entry(line,textvariable=self.action,width=24).pack(side="left")
        tk.Label(line,text="숫자").pack(side="left",padx=3)
        ttk.Combobox(line,textvariable=self.field,values=sorted(FIELDS),width=17,state="readonly").pack(side="left")
        modes=tk.Frame(self);modes.pack(fill="x",padx=8,pady=4)
        for key,description in (("scene","1. 고정 장면 표식 영역"),("button","2. 버튼 전체 영역"),("number","3. 숫자 표시 영역")):
            tk.Radiobutton(modes,text=description,variable=self.mode,value=key).pack(side="left",padx=5)
        tk.Label(self,text="영역 선택: 위에서 종류를 고르고 아래 이미지에 드래그해 사각형으로 지정하세요. 실제 클릭은 버튼 영역 가운데만 사용합니다.",
                 wraplength=800,justify="left").pack(anchor="w",padx=9)
        canvas_frame=tk.Frame(self);canvas_frame.pack(fill="both",expand=True,padx=8,pady=5)
        self.canvas=tk.Canvas(canvas_frame,width=620,height=600,bg="#111827",highlightthickness=1)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<ButtonPress-1>",self._down)
        self.canvas.bind("<ButtonRelease-1>",self._up)
        actions=tk.Frame(self);actions.pack(fill="x",padx=8,pady=4)
        tk.Checkbutton(actions,text="실제 한국 서버 화면/버튼을 직접 확인함",variable=self.reviewed).pack(side="left")
        tk.Checkbutton(actions,text="이 TP 아이템은 무료임을 게임에서 직접 확인함",
                       variable=self.free_confirmed).pack(side="left")
        tk.Checkbutton(self,text="스킬의 현재 캐릭터·거리·각질·마장 적성을 실제 한국 게임에서 모두 확인함",
                       variable=self.skill_conditions_reviewed).pack(anchor="w",padx=12)
        buttons=tk.Frame(self);buttons.pack(fill="x",padx=8,pady=6)
        tk.Button(buttons,text="버튼 템플릿 저장 (덮어쓰기 없음)",
                  command=self.save_control).pack(side="left",padx=6)
        tk.Button(buttons,text="숫자 OCR 영역 저장",command=self.save_number).pack(side="left",padx=6)
        tk.Label(self,textvariable=self.status,wraplength=780,justify="left",
                 fg="#ad4d25").pack(fill="x",padx=8,pady=5)

    def _stage_changed(self,event=None):
        self.action.set(DEFAULT_ACTION[self.stage.get()])
        self.field.set("skill_points" if self.stage.get()=="skill" else "tp")
        self.regions.clear()
        self.reviewed.set(False)
        self.free_confirmed.set(False)
        self.skill_conditions_reviewed.set(False)
        self._repaint()

    def delayed_capture(self):
        if os.name!="nt":
            self.status.set("Windows 게임 창에서만 실제 캡처를 진행할 수 있습니다.")
            return
        self.withdraw()
        self.after(4000,self._capture_foreground)

    def _capture_foreground(self):
        try:
            from PIL import ImageGrab
            import ctypes
            from companion_window import discover_windows
            from companion_core import choose_window
            game,_=choose_window(discover_windows())
            if game is None or ctypes.windll.user32.GetForegroundWindow()!=game.hwnd:
                raise ValueError("캡처 시점에는 우마무스메 게임 창이 전경이어야 합니다.")
            img=ImageGrab.grab(bbox=game.rect,all_screens=True)
            if img.size!=(game.width,game.height):
                raise ValueError("게임 창 크기와 캡처 크기가 불일치합니다.")
            self.image=img.convert("RGB")
            self.image_window=(game.hwnd,game.rect)
            self.regions.clear()
            self.reviewed.set(False)
            self.free_confirmed.set(False)
            self._repaint()
            self.status.set("캡처 완료. 장면 표식과 버튼을 각각 드래그해 지정하세요.")
        except (OSError,ValueError,RuntimeError) as exc:
            self.status.set("캡처 실패: "+str(exc)[:190])
        finally:
            self.deiconify()
            self.lift()

    def _repaint(self):
        if not hasattr(self,"canvas"):
            return
        self.canvas.delete("all")
        if self.image is None:
            return
        from PIL import ImageTk
        avail_w=max(300,self.canvas.winfo_width()-14)
        avail_h=max(350,self.canvas.winfo_height()-14)
        scale=min(avail_w/self.image.width,avail_h/self.image.height,1.7)
        sw=max(1,round(self.image.width*scale))
        sh=max(1,round(self.image.height*scale))
        resized=self.image.resize((sw,sh))
        self.photo=ImageTk.PhotoImage(resized)
        self.canvas.create_image(5,5,image=self.photo,anchor="nw",tags="image")
        self.dimensions=(sw,sh)
        for key,box in self.regions.items():
            color={"scene":"#57d6bc","button":"#f9c56b","number":"#d583f8"}[key]
            x1,y1,x2,y2=box
            self.canvas.create_rectangle(5+sw*x1,5+sh*y1,
                                         5+sw*x2,5+sh*y2,width=3,outline=color)
            self.canvas.create_text(5+sw*x1,5+sh*y1-9,anchor="w",fill=color,text=key)

    def _down(self,event):
        self.drag_start=(event.x,event.y)

    def _up(self,event):
        if self.image is None or self.drag_start is None:
            return
        sw,sh=self.dimensions
        x0,y0=self.drag_start
        x1,y1=event.x,event.y
        self.drag_start=None
        rect=(max(0,min(1,(min(x0,x1)-5)/sw)),
              max(0,min(1,(min(y0,y1)-5)/sh)),
              max(0,min(1,(max(x0,x1)-5)/sw)),
              max(0,min(1,(max(y0,y1)-5)/sh)))
        try:
            from visual_controls_r50 import _bbox
            self.regions[self.mode.get()]=_bbox(rect)
            self._repaint()
        except ValueError as exc:
            self.status.set("ROI 오류: "+str(exc))

    def save_control(self):
        try:
            if self.image is None or self.image_window is None:
                raise ValueError("실제 게임 캡처가 없습니다.")
            a=self.regions.get("scene");b=self.regions.get("button")
            if a is None or b is None:
                raise ValueError("고정 장면 표식 영역과 버튼 전체 영역을 먼저 등록하세요.")
            action=self.action.get().strip()
            click=((b[0]+b[2])/2,(b[1]+b[3])/2)
            current_goal=getattr(self.master,"current_target",None)
            if self.stage.get()=="skill" and current_goal is None:
                raise ValueError("스킬은 대회 회차·각질을 먼저 선택하고 등록해야 합니다.")
            scope=(current_goal.key+":"+current_goal.style) if self.stage.get()=="skill" else ""
            if self.stage.get()=="skill":
                if (not action.startswith("skill:") or
                        not self.skill_conditions_reviewed.get()):
                    raise ValueError("스킬의 현재 캐릭터·거리·각질·마장 조건 확인 후 승인해야 합니다.")
            p=register(self.image,stage=self.stage.get(),action=action,
                       scene_box=a,button_box=b,click=click,
                       reviewed=self.reviewed.get(),
                       free_only=self.free_confirmed.get(),target_scope=scope)
            dest=user_dir()/"r50_visual_controls.json"
            save_profile(dest,p)
            if self.stage.get()=="skill":
                auth=SkillAuthorization(
                     scope=scope,skill=action.removeprefix("skill:"),
                     character_reviewed=True,distance_reviewed=True,
                     style_reviewed=True,surface_reviewed=True).validate()
                save_authorization(user_dir()/"r51_skill_authorizations.json",auth)
            self.status.set("버튼 영역 등록 완료 · 게임 안의 숫자/스킬 검수 이후에만 자동 사용 가능합니다.")
        except (OSError,ValueError,TypeError) as exc:
            self.status.set("저장 보류: "+str(exc)[:190])

    def save_number(self):
        try:
            box=self.regions.get("number")
            if self.image is None or box is None:
                raise ValueError("숫자 OCR 영역을 게임 화면에서 먼저 지정하세요.")
            roi=NumberROI(self.stage.get(),self.field.get(),box,self.reviewed.get()).validate()
            dest=user_dir()/"r50_numeric_rois.json"
            save_roi(dest,roi)
            self.status.set("숫자 영역 저장 완료 · 실제 게임에서 두 번 일치한 숫자만 사용합니다.")
        except (OSError,ValueError,TypeError) as exc:
            self.status.set("숫자 영역 저장 보류: "+str(exc)[:190])
