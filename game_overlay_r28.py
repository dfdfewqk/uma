"""R28 read-only click-through Windows game hint; never injects mouse or keyboard input.

The overlay is created only after Windows no-activate and mouse-pass-through styles
can be verified. If either fails, the hint remains text-only in the companion.
"""
from __future__ import annotations
import sys
import tkinter as tk

MAGENTA='#ff00ff'

class TrainingOverlay:
    def __init__(self,owner):
        self.owner=owner
        self.win=None
        self.paint=None
        self.problem='Windows 이외 환경 · 게임 위 표시 비활성'
        if sys.platform=='win32':
            self._create()

    def _create(self):
        popup=tk.Toplevel(self.owner)
        popup.withdraw()
        try:
            popup.overrideredirect(True)
            popup.configure(bg=MAGENTA)
            popup.wm_attributes('-transparentcolor',MAGENTA)
            popup.wm_attributes('-topmost',True)
            canvas=tk.Canvas(popup,highlightthickness=0,bd=0,bg=MAGENTA)
            canvas.pack(fill='both',expand=True)
            popup.update_idletasks()
            import ctypes
            u=ctypes.windll.user32
            get_style=getattr(u,'GetWindowLongPtrW',u.GetWindowLongW)
            set_style=getattr(u,'SetWindowLongPtrW',u.SetWindowLongW)
            get_style.argtypes=[ctypes.c_void_p,ctypes.c_int]
            get_style.restype=ctypes.c_ssize_t
            set_style.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_ssize_t]
            set_style.restype=ctypes.c_ssize_t
            u.GetParent.argtypes=[ctypes.c_void_p]
            u.GetParent.restype=ctypes.c_void_p
            handle=u.GetParent(popup.winfo_id()) or popup.winfo_id()
            EXSTYLE=-20
            PASS=0x20;LAYERED=0x80000;NOACTIVATE=0x08000000;TOOL=0x80
            original=get_style(handle,EXSTYLE)
            set_style(handle,EXSTYLE,original|PASS|LAYERED|NOACTIVATE|TOOL)
            applied=get_style(handle,EXSTYLE)
            if (applied&(PASS|LAYERED|NOACTIVATE))!=(PASS|LAYERED|NOACTIVATE):
                raise RuntimeError('안전한 오버레이 클릭 통과 설정 실패')
            self.win=popup
            self.paint=canvas
            self.problem=''
        except Exception as exc:
            popup.destroy()
            self.problem=f'오버레이 비활성: {type(exc).__name__}'

    def hide(self):
        if self.win and self.win.winfo_exists():
            self.win.withdraw()

    def show(self,rect,hint):
        if not self.win or hint is None:
            self.hide();return False
        x1,y1,x2,y2=rect
        width=x2-x1;height=y2-y1
        if width<500 or height<320 or width*height>24_000_000:
            self.hide();return False
        self.win.geometry(f'{width}x{height}+{x1}+{y1}')
        self.paint.delete('all')
        x=int(hint.x*width);y=int(hint.y*height)
        if x<24 or y<24 or x>width-24 or y>height-24:
            self.hide();return False
        self.paint.create_oval(x-25,y-25,x+25,y+25,outline='#79f4b5',width=5)
        # Short on-screen message does not conceal the clickable button.
        anchor_x=min(width-200,max(14,x-70))
        anchor_y=max(19,y-39)
        self.paint.create_rectangle(anchor_x,anchor_y-14,anchor_x+198,anchor_y+12,fill='#12223a',outline='#79f4b5')
        self.paint.create_text(anchor_x+7,anchor_y,text='검수된 훈련 1순위 · 직접 클릭',fill='white',anchor='w',font=('맑은 고딕',9,'bold'))
        self.win.deiconify()
        return True

    def close(self):
        if self.win is not None:
            self.win.destroy();self.win=None;self.paint=None
