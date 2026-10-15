"""Screen R4 desktop widget. OCR candidates must be manually checked before applying."""
from __future__ import annotations
import os
import sys
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from screen_r4 import (FIELDS, FIELD_LIMITS, Region, ScreenProfile, ScreenError,
                       load_image, parse_numeric, profile_path, read_profile, save_profile,
                       read_regions, save_review, sha256_file, user_dir)


class ScreenPanel(ttk.Frame):
    def __init__(self, parent, apply_callback, screenshot_callback=None):
        super().__init__(parent)
        self.apply_callback=apply_callback
        self.screenshot_callback=screenshot_callback
        self.image=None
        self.photo=None
        self.image_path=None
        self.regions={}
        self.results=[]
        self._draw=(0,0,1)
        self._drag_start=None
        self.selected_field=tk.StringVar(value=FIELDS[0])
        self.custom_ocr=tk.StringVar(value='')
        self.info=tk.StringVar(value='PNG/JPG/WebP 이미지를 열거나 합성 테스트 화면을 사용하세요.')
        self.status=tk.StringVar(value='OCR 후보는 사용자 확인 전까지 기존 턴 값에 반영하지 않습니다.')
        self.values={name:tk.StringVar(value='') for name in FIELDS}
        self.verified={name:tk.BooleanVar(value=False) for name in FIELDS}
        self._build()
        self.after_idle(self._load_saved_profile)

    def _build(self):
        bar=ttk.Frame(self)
        bar.pack(fill='x',padx=12,pady=(10,3))
        ttk.Button(bar,text='이미지 불러오기',command=self.browse).pack(side='left',padx=(0,5))
        ttk.Button(bar,text='현재 화면 캡처',command=self.capture_clicked).pack(side='left',padx=(0,5))
        ttk.Button(bar,text='합성 테스트 이미지',command=self.load_demo).pack(side='left',padx=(0,5))
        ttk.Button(bar,text='ROI 저장',command=self.save_regions).pack(side='left',padx=(0,5))
        ttk.Button(bar,text='ROI 불러오기',command=self._load_saved_profile).pack(side='left',padx=(0,5))
        ttk.Label(bar,text='이미지 전체가 아닌 숫자 영역을 드래그로 지정',style='Muted.TLabel').pack(side='left',padx=8)
        ttk.Label(self,textvariable=self.info,style='Muted.TLabel').pack(anchor='w',padx=15,pady=(0,7))
        body=ttk.Frame(self)
        body.pack(fill='both',expand=True,padx=12)
        body.columnconfigure(0,weight=5)
        body.columnconfigure(1,weight=3)
        body.rowconfigure(0,weight=1)
        left=ttk.Frame(body)
        left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        choose=ttk.Frame(left)
        choose.pack(fill='x',pady=(0,6))
        ttk.Label(choose,text='지정할 값:').pack(side='left')
        ttk.Combobox(choose,textvariable=self.selected_field,values=FIELDS,
                     state='readonly',width=14).pack(side='left',padx=(6,14))
        ttk.Button(choose,text='현재 값 영역 삭제',command=self.remove_region).pack(side='left')
        self.canvas=tk.Canvas(left,bg='#0d1624',highlightthickness=1,
                              highlightbackground='#34445d',cursor='crosshair',height=425)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.start_drag)
        self.canvas.bind('<B1-Motion>',self.move_drag)
        self.canvas.bind('<ButtonRelease-1>',self.end_drag)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        right=ttk.Frame(body)
        right.grid(row=0,column=1,sticky='nsew')
        ttk.Label(right,text='인식 후보 및 사용자 검수',style='Section.TLabel').pack(anchor='w',pady=(0,5))
        ttk.Label(right,text='OCR 값을 확인·수정한 뒤 사용할 항목만 체크하세요.',
                  style='Muted.TLabel',wraplength=330).pack(anchor='w',pady=(0,7))
        table=ttk.Frame(right)
        table.pack(fill='x')
        for i,(label,_) in enumerate((('항목',0),('숫자',1),('적용',2))):
            ttk.Label(table,text=label,style='Muted.TLabel').grid(row=0,column=i,sticky='w',padx=3,pady=(0,4))
        self.markers={}
        for i,name in enumerate(FIELDS,1):
            ttk.Label(table,text=name).grid(row=i,column=0,sticky='w',padx=3,pady=3)
            ttk.Entry(table,textvariable=self.values[name],width=11).grid(row=i,column=1,sticky='ew',padx=3,pady=3)
            ttk.Checkbutton(table,variable=self.verified[name]).grid(row=i,column=2,sticky='w',padx=4)
            marker=ttk.Label(table,text='영역 없음',style='Muted.TLabel')
            marker.grid(row=i,column=3,sticky='w',padx=3)
            self.markers[name]=marker
        table.columnconfigure(1,weight=1)
        ttk.Label(right,text='Tesseract 경로 (선택 · 설치된 경우 기본 탐색)',style='Muted.TLabel').pack(anchor='w',pady=(15,2))
        ttk.Entry(right,textvariable=self.custom_ocr).pack(fill='x',pady=(0,6))
        row=ttk.Frame(right)
        row.pack(fill='x',pady=(5,5))
        ttk.Button(row,text='OCR 후보 읽기',command=self.run_ocr).pack(side='left',padx=(0,6))
        ttk.Button(row,text='확인한 항목 적용',style='Accent.TButton',command=self.apply_checked).pack(side='left')
        ttk.Label(right,text='※ 수동 입력·OCR 모두 검수 전에는 추천 입력값으로 사용되지 않습니다.',
                  style='Muted.TLabel',wraplength=340).pack(anchor='w',pady=9)
        ttk.Label(self,textvariable=self.status,style='Muted.TLabel',wraplength=1100).pack(anchor='w',padx=15,pady=(6,11))

    def _path_to_image(self,path):
        pic=load_image(path)
        self.image=pic
        self.image_path=Path(path)
        self.results=[]
        for name in FIELDS:
            self.verified[name].set(False)
            self.values[name].set('')
        saved=profile_path()
        if saved.exists():
            try:
                old=read_profile(saved)
                if old.matches_image(pic):
                    self.regions=old.regions.copy()
                else:
                    self.regions={}
                    self.status.set('화면 비율이 바뀌어 기존 ROI를 사용하지 않습니다. 다시 지정하세요.')
            except ScreenError:
                self.regions={}
        self.info.set(f'{self.image_path.name} | {pic.width}×{pic.height} | SHA256 {sha256_file(path)[:16]}…')
        self.update_idletasks()
        self.draw()

    def browse(self):
        path=filedialog.askopenfilename(title='게임 스크린샷 선택',
                  filetypes=[('이미지','*.png *.jpg *.jpeg *.webp')])
        if not path:return
        try:self._path_to_image(path)
        except (ScreenError,OSError) as e:messagebox.showerror('이미지 읽기 오류',str(e))

    def load_demo(self):
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
        image=root/'examples'/'synthetic_r4.png'
        example=root/'examples'/'synthetic_roi.json'
        try:
            self._path_to_image(image)
            prof=read_profile(example)
            self.regions=prof.regions.copy()
            self.draw()
            self.status.set('합성 예제입니다. 게임 자료가 아닙니다. 실제 육성 데이터/ML 학습에 넣지 마세요.')
        except (ScreenError,OSError) as e:
            messagebox.showerror('예제 오류',str(e))

    def capture_clicked(self):
        if not messagebox.askyesno('전체 화면 캡처',
            '현재 PC 화면 전체를 이미지 파일로 이 PC에만 저장합니다.\n다른 앱의 개인 정보도 포함될 수 있습니다. 계속할까요?'):
            return
        self.winfo_toplevel().iconify()
        self.after(950,self._finish_capture)

    def _finish_capture(self):
        try:
            from PIL import ImageGrab
            # Capture BEFORE restoring the tool's own window, or it obscures the game.
            img=ImageGrab.grab(all_screens=False)
            folder=user_dir()/'captures'
            folder.mkdir(parents=True,exist_ok=True)
            filename=folder/f'capture_{datetime.now():%Y%m%d_%H%M%S_%f}.png'
            img.save(filename)
        except (ImportError,OSError,ScreenError,ValueError) as exc:
            self.winfo_toplevel().deiconify()
            messagebox.showerror('캡처 실패',f'화면 캡처에 실패했습니다: {exc}\n게임 스크린샷 파일을 직접 불러오세요.')
            return
        self.winfo_toplevel().deiconify()
        try:
            self._path_to_image(filename)
            self.status.set(f'화면 캡처 저장: {filename} / 게임 보호 화면에서는 캡처가 제한될 수 있습니다.')
        except (ScreenError,OSError) as exc:
            messagebox.showerror('캡처 이미지 오류',str(exc))

    def draw(self):
        self.canvas.delete('all')
        if self.image is None:
            self.canvas.create_text(330,190,text='먼저 스크린샷을 불러오세요',fill='#bcc9d6')
            return
        from PIL import ImageTk
        w=max(self.canvas.winfo_width()-16,250)
        h=max(self.canvas.winfo_height()-16,180)
        scale=min(w/self.image.width,h/self.image.height)
        pw=max(1,int(self.image.width*scale))
        ph=max(1,int(self.image.height*scale))
        ox=(self.canvas.winfo_width()-pw)//2
        oy=(self.canvas.winfo_height()-ph)//2
        self._draw=(ox,oy,scale)
        self.photo=ImageTk.PhotoImage(self.image.resize((pw,ph)))
        self.canvas.create_image(ox,oy,image=self.photo,anchor='nw')
        for field,reg in self.regions.items():
            x1=ox+reg.x1*self.image.width*scale
            y1=oy+reg.y1*self.image.height*scale
            x2=ox+reg.x2*self.image.width*scale
            y2=oy+reg.y2*self.image.height*scale
            color='#ffde80' if field == self.selected_field.get() else '#8ce9bb'
            self.canvas.create_rectangle(x1,y1,x2,y2,outline=color,width=2)
            self.canvas.create_text(x1,max(9,y1-9),text=field,anchor='sw',fill=color)
            self.markers[field].config(text='영역 지정')
        for field in FIELDS:
            if field not in self.regions:self.markers[field].config(text='영역 없음')

    def _position(self,evt):
        if self.image is None:return None
        ox,oy,scale=self._draw
        x=(evt.x-ox)/(self.image.width*scale)
        y=(evt.y-oy)/(self.image.height*scale)
        if not 0<=x<=1 or not 0<=y<=1:return None
        return x,y

    def start_drag(self,evt):
        self._drag_start=self._position(evt)

    def move_drag(self,evt):
        if self._drag_start is None:return
        self.draw()
        now=self._position(evt)
        if now:
            ox,oy,scale=self._draw
            x1,y1=self._drag_start
            x2,y2=now
            self.canvas.create_rectangle(ox+x1*self.image.width*scale,oy+y1*self.image.height*scale,
                  ox+x2*self.image.width*scale,oy+y2*self.image.height*scale,outline='#ffffff',width=2,dash=(3,3))

    def end_drag(self,evt):
        point=self._position(evt)
        start=self._drag_start
        self._drag_start=None
        if start is None or point is None:return
        name=self.selected_field.get()
        coords=tuple(round(v,6) for v in (min(start[0],point[0]),min(start[1],point[1]),
                                            max(start[0],point[0]),max(start[1],point[1])))
        try:
            r=Region(name,*coords)
            r.validate()
            self.regions[name]=r
            self.verified[name].set(False)
            self.status.set(f'{name} 영역을 지정했습니다. 수치 확인 후 ROI를 저장하세요.')
            self.draw()
        except ScreenError as exc:
            self.status.set(str(exc))

    def remove_region(self):
        name=self.selected_field.get()
        self.regions.pop(name,None)
        self.verified[name].set(False)
        self.draw()

    def _profile(self):
        if not self.image:
            raise ScreenError('이미지를 먼저 불러오세요.')
        p=ScreenProfile('무인도 한국 PC 수동 ROI', 'island_post_patch_v1',
                      self.image.width/self.image.height, self.regions.copy())
        p.validate()
        return p

    def save_regions(self):
        try:
            p=self._profile()
            if not p.regions:raise ScreenError('최소 하나의 숫자 영역을 지정하세요.')
            save_profile(p,profile_path())
            self.status.set(f'{len(p.regions)}개 ROI 저장: {profile_path()} (기존 게임 데이터 불변)')
        except (ScreenError,OSError) as exc:messagebox.showerror('저장 오류',str(exc))

    def _load_saved_profile(self):
        if not profile_path().exists():return
        try:
            p=read_profile(profile_path())
            if self.image and not p.matches_image(self.image):
                raise ScreenError('현재 이미지와 저장된 프로필의 화면 비율이 맞지 않습니다.')
            self.regions=p.regions.copy()
            self.draw()
            self.status.set(f'저장된 영역 {len(self.regions)}개를 불러왔습니다.')
        except ScreenError as exc:self.status.set(str(exc))

    def run_ocr(self):
        try:
            if not self.image_path:raise ScreenError('이미지 파일을 먼저 선택하세요.')
            if not self.regions:raise ScreenError('인식할 숫자 영역을 먼저 드래그로 지정하세요.')
            self.results=read_regions(self.image_path,self._profile(),self.custom_ocr.get().strip())
            for result in self.results:
                if result.field not in self.regions:continue
                self.verified[result.field].set(False)
                # Low confidence/ambiguous reads are never silently promoted to numbers.
                if result.status == '후보 · 사용자 확인 필요':
                    self.values[result.field].set(str(result.value))
                else:self.values[result.field].set('')
                self.markers[result.field].config(text=(f'{result.confidence:g}%' if result.confidence is not None else '?')+' · '+('검수' if result.value is not None else '불확실'))
            strong=sum(r.status=='후보 · 사용자 확인 필요' for r in self.results)
            self.status.set(f'OCR 완료: 확인 가능 후보 {strong}/{len(self.regions)}개. 화면과 숫자를 대조해 체크해야 적용됩니다.')
        except (ScreenError,OSError) as exc:
            messagebox.showwarning('OCR 사용 불가',str(exc))
            self.status.set('OCR 사용 불가 · 영역 지정과 수동 숫자 입력·검수는 계속 사용 가능합니다.')

    def apply_checked(self):
        try:
            if not self.image_path:raise ScreenError('이미지를 불러와야 합니다.')
            p=self._profile()
            values={}
            for field in FIELDS:
                if not self.verified[field].get():continue
                if field not in self.regions:
                    raise ScreenError(f'{field}: 화면 영역부터 지정하세요.')
                value=parse_numeric(self.values[field].get(),field)
                if value is None:raise ScreenError(f'{field}: 확인한 정수 값을 직접 입력하세요 ({FIELD_LIMITS[field]})')
                values[field]=value
            if not values:raise ScreenError('화면과 숫자를 대조한 항목에 체크하세요. 아무 값도 변경하지 않았습니다.')
            if not messagebox.askyesno('인식 결과 확인',
                f'선택한 {len(values)}개 숫자를 현재 턴에 반영합니다.\n실제 게임 화면과 대조했습니까?'):
                return
            output=user_dir()/'screen_reviews'
            output.mkdir(parents=True,exist_ok=True)
            dest=output/f'review_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
            save_review(self.image_path,p,self.results,values,dest,manual=not bool(self.results))
            self.apply_callback(values,str(self.image_path))
            self.status.set(f'직접 검수한 {len(values)}개 숫자를 적용했습니다. 증거 메타데이터: {dest.name}.\n턴과 행동 후보는 별도로 검수·저장해야 합니다.')
        except (ScreenError,OSError,ValueError) as exc:
            messagebox.showerror('검수 오류',str(exc))
