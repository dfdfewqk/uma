"""Non-invasive R19 dual presentation: click-through on-game hints + adjacent detail window.

Positions are user calibrated, NOT automatic recognition. No game input from this module.
"""
from __future__ import annotations
import sys
import tkinter as tk
from hud_r19 import marker_label, visible_marks, side_summary

TRANSPARENT = '#ff00ff'
BG = '#111b30'


class GameHUD:
    def __init__(self, parent, context_provider):
        self.parent=parent
        self.context_provider=context_provider
        self.side=None
        self.overlay=None
        self.side_content=None
        self.paint=None
        self.current_window=None
        self.marks=[]
        self.scene='훈련'
        self.confirmed=False
        self._overlay_supported=sys.platform=='win32'

    def open(self):
        if self.side is not None and self.side.winfo_exists():
            self.close()
            return False
        self.side=tk.Toplevel(self.parent)
        self.side.title('Uma Trainer KR · 옆 정보창')
        self.side.configure(bg=BG)
        self.side.geometry('380x640+70+70')
        self.side.minsize(315,430)
        self.side.attributes('-topmost',True)
        self.side.protocol('WM_DELETE_WINDOW',self.close)
        tk.Label(self.side,text='UMA TRAINER  |  육성 도우미',bg=BG,fg='#8bcaff',font=('맑은 고딕',13,'bold')).pack(anchor='w',padx=14,pady=(13,5))
        tk.Label(self.side,text='게임 위: 누를 후보만 표시  /  이 창: 육성 계획',bg=BG,fg='#c2cee0',font=('맑은 고딕',9)).pack(anchor='w',padx=14)
        self.side_content=tk.Text(self.side,bg=BG,fg='#f3f7fc',borderwidth=0,highlightthickness=0,wrap='word',padx=12,pady=10,font=('맑은 고딕',10))
        self.side_content.pack(fill='both',expand=True,padx=8,pady=8)
        self.side_content.tag_configure('head',foreground='#86ceff',font=('맑은 고딕',11,'bold'),spacing1=12,spacing3=5)
        self.side_content.tag_configure('muted',foreground='#b2c1d6')
        self.side_content.tag_configure('good',foreground='#8fe6b1')
        self.side_content.tag_configure('warn',foreground='#ffe19a')
        self.side_content.tag_configure('bad',foreground='#ff9a9a')
        if self._overlay_supported:
            try:self._create_game_overlay()
            except tk.TclError:self._overlay_supported=False
        self.update(None, [], '훈련', False, False)
        return True

    def _create_game_overlay(self):
        overlay=tk.Toplevel(self.parent)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.configure(bg=TRANSPARENT)
        overlay.wm_attributes('-transparentcolor', TRANSPARENT)
        overlay.wm_attributes('-topmost',True)
        self.paint=tk.Canvas(overlay,bg=TRANSPARENT,borderwidth=0,highlightthickness=0)
        self.paint.pack(fill='both',expand=True)
        overlay.update_idletasks()
        # Extended styles make *all* mouse input pass through to the game.
        # This prevents the overlay from accidentally stealing clicks.
        import ctypes
        u=ctypes.windll.user32
        parent_api=u.GetParent
        parent_api.argtypes=[ctypes.c_void_p]
        parent_api.restype=ctypes.c_void_p
        child=overlay.winfo_id()
        hwnd=parent_api(child) or child
        GWL_EXSTYLE=-20
        WS_EX_LAYERED=0x00080000
        WS_EX_TRANSPARENT=0x00000020
        WS_EX_TOOLWINDOW=0x00000080
        WS_EX_NOACTIVATE=0x08000000
        get_style=getattr(u,'GetWindowLongPtrW',u.GetWindowLongW)
        set_style=getattr(u,'SetWindowLongPtrW',u.SetWindowLongW)
        get_style.argtypes=[ctypes.c_void_p,ctypes.c_int]
        get_style.restype=ctypes.c_ssize_t
        set_style.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_ssize_t]
        set_style.restype=ctypes.c_ssize_t
        style=get_style(hwnd,GWL_EXSTYLE)
        set_style(hwnd,GWL_EXSTYLE,style|WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE)
        if (get_style(hwnd,GWL_EXSTYLE)&WS_EX_TRANSPARENT)==0:
            overlay.destroy()
            raise RuntimeError('클릭 통과 오버레이 구성 실패')
        self.overlay=overlay

    def close(self):
        if self.overlay is not None:
            try:self.overlay.destroy()
            except tk.TclError:pass
        if self.side is not None:
            try:self.side.destroy()
            except tk.TclError:pass
        self.side=self.overlay=self.paint=None

    def _render_side(self,context,notice):
        if self.side_content is None:return
        info=side_summary(context)
        area=self.side_content
        area.config(state='normal')
        area.delete('1.0','end')
        def line(t,tag=None):
            area.insert('end',t+'\n',tag or '')
        line('대회 · 육성 목표','head')
        line(f"{info['event']}  ·  {info['style']}")
        line(info['course'])
        line('목표 스탯 / 현재 입력값','head')
        for name,current,target in info['stats']:
            c='?' if current is None else str(current)
            t='미설정' if target is None else str(target)
            line(f'  {name:<5}   {c}  /  {t}')
        line('필수 스킬 / 획득 상태','head')
        if info['required_skills']:
            for item in info['required_skills']:
                if isinstance(item,dict):
                    name=item.get('name','-');status=item.get('status','미확인')
                else:name=str(item);status='미확인'
                line(f'  • {name}  [{status}]')
        else:
            line('  R11에서 필수 스킬을 먼저 설정하세요.','muted')
        line('게임 화면 위 추천 근거','head')
        if context.get('training_checked') and context.get('training_rankings'):
            for ix,item in enumerate(context['training_rankings'][:3],1):
                line(f"  {ix}. {item['name']} · R6 수동 검수 결과",'good' if ix==1 else '')
        else:
            line('  현재 턴의 훈련 추천은 검증 전','warn')
        good=[(name,obj) for name,obj in (context.get('skill_advice') or {}).items() if obj.get('verdict','').startswith(('우선 검토','조건 일치'))]
        if context.get('skill_checked') and good:
            for name,obj in good[:5]:line(f"  • {name}: {obj['verdict']}",'good')
        else:line('  실제 구매 스킬 후보 검수 필요','warn')
        line('주의','head')
        line('  목표값은 사용자가 입력한 값입니다.','muted')
        line('  화면 위 위치는 수동으로 맞춰둔 좌표입니다.','muted')
        line('  스킬 보유·발동률·구매 가능 여부는 자동 확인되지 않습니다.','muted')
        line('  '+notice,'warn')
        area.config(state='disabled')

    def update(self, window, marks, scene, confirmed, game_active):
        if self.side is None or not self.side.winfo_exists():return
        self.marks=marks
        self.scene=scene
        self.confirmed=confirmed
        try:context=self.context_provider() or {}
        except (ValueError,TypeError,AttributeError):context={}
        context['manual_scene_confirmed']=confirmed
        notice=('현재 화면 종류를 직접 확인했을 때만 위치 표시' if not confirmed else
                '수동 위치 표시 중 · 실제 버튼/스킬 자동 인식 아님')
        self._render_side(context,notice)
        if window is not None:
            self.current_window=window
            # Keep the detail panel adjacent but do not cover the game content.
            try:
                left=window.x+window.width+9
                width=380
                if left+width>self.side.winfo_screenwidth():
                    left=max(0,window.x-width-9)
                self.side.geometry(f'{width}x640+{left}+{max(0,window.y)}')
            except tk.TclError:pass
        if self.overlay is None or not self.overlay.winfo_exists():return
        if not confirmed or not game_active or window is None:
            self.overlay.withdraw()
            return
        result=visible_marks(marks,scene,(window.width,window.height),context)
        if not result:
            self.overlay.withdraw()
            return
        ov=self.overlay
        ov.geometry(f'{window.width}x{window.height}+{window.x}+{window.y}')
        ov.deiconify()
        self.paint.delete('all')
        for mark,status,label in result:
            x,y=int(mark.x*window.width),int(mark.y*window.height)
            color='#78e5a2' if status in ('추천 후보','우선 검토') else '#ffd16f'
            if status=='주의':color='#ff8e8e'
            self.paint.create_oval(x-20,y-20,x+20,y+20,outline=color,width=3)
            short=label[:42]
            text_x=max(70,min(window.width-150,x+23))
            text_y=max(16,min(window.height-27,y-36))
            text_id=self.paint.create_text(text_x,text_y,text=short,anchor='w',fill='#ffffff',font=('맑은 고딕',10,'bold'))
            bbox=self.paint.bbox(text_id)
            if bbox:
                box_id=self.paint.create_rectangle(bbox[0]-7,bbox[1]-4,bbox[2]+7,bbox[3]+4,fill='#12233d',outline=color,width=1)
                self.paint.tag_lower(box_id,text_id)
