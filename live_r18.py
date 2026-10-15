"""R18 Windows visible-window watcher and fail-closed ONE-click proof of concept.

IMPORTANT: This does not recognize arbitrary game scenes or choose training actions.
Clicks only a manually marked, exact-layout, visually matched target, after opt-in.
No hidden process manipulation, injection, networking, or running in background after exit.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import os
import sys
from typing import Callable, Optional

from PIL import Image, ImageChops, ImageFilter, ImageStat


class LiveError(ValueError):
    pass


@dataclass(frozen=True)
class WindowItem:
    hwnd: int
    title: str
    x: int
    y: int
    width: int
    height: int

    def validate(self):
        if not isinstance(self.hwnd, int) or self.hwnd <= 0:
            raise LiveError('게임 창 식별자가 올바르지 않습니다.')
        if self.width < 200 or self.height < 200 or self.width * self.height > 24_000_000:
            raise LiveError('게임 창 크기가 허용 범위를 벗어납니다.')
        return self


class WindowsGameBackend:
    """Native HWND enumeration and *visible* client capture; no game process access."""
    def __init__(self):
        if sys.platform != 'win32':
            raise LiveError('실시간 Windows 창 연동은 Windows 환경에서만 실행됩니다.')
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()

    def _window(self, hwnd: int):
        u, ct, wt = self.user32, self.ctypes, self.wintypes
        if not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
            raise LiveError('창이 닫혔거나 최소화되었습니다.')
        length = u.GetWindowTextLengthW(hwnd)
        buf = ct.create_unicode_buffer(max(1, length + 1))
        u.GetWindowTextW(hwnd, buf, len(buf))
        rc=wt.RECT()
        if not u.GetClientRect(hwnd, ct.byref(rc)):
            raise LiveError('게임 창의 표시 영역을 확인할 수 없습니다.')
        origin=wt.POINT(0, 0)
        if not u.ClientToScreen(hwnd, ct.byref(origin)):
            raise LiveError('게임 창의 화면 좌표를 확인할 수 없습니다.')
        return WindowItem(hwnd, buf.value, origin.x, origin.y,
                          rc.right - rc.left, rc.bottom - rc.top).validate()

    def list_game_windows(self):
        ct, wt, u = self.ctypes, self.wintypes, self.user32
        found=[]
        cbtype=ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def each(hwnd, _):
            try:
                if u.GetWindow(hwnd,4): # owned popup, not top-level app window
                    return True
                item=self._window(hwnd)
                if '우마무스메' in item.title or 'umamusume' in item.title.lower():
                    found.append(item)
            except LiveError:
                pass
            return True
        callback=cbtype(each)
        u.EnumWindows(callback, 0)
        return found

    def active(self, hwnd: int):
        return self.user32.GetForegroundWindow() == hwnd

    def capture(self, hwnd: int):
        from PIL import ImageGrab
        window=self._window(hwnd)
        if not self.active(hwnd):
            raise LiveError('게임 창이 활성화되지 않았습니다. 게임 창을 클릭해 주세요.')
        img=ImageGrab.grab(bbox=(window.x, window.y,
                                 window.x + window.width,
                                 window.y + window.height), all_screens=True)
        if img.size != (window.width, window.height):
            raise LiveError('캡처 크기가 게임 창과 일치하지 않습니다.')
        return img.convert('RGB'),window

    def click(self, hwnd: int, x: int, y: int):
        """Click only when target window is focused and client coordinates are in bounds."""
        win=self._window(hwnd)
        if not self.active(hwnd):
            raise LiveError('게임 창이 활성화되지 않아 클릭을 취소했습니다.')
        if x < 0 or y < 0 or x >= win.width or y >= win.height:
            raise LiveError('게임 창을 벗어난 클릭을 차단했습니다.')
        # Avoid raw memory manipulation or process injection: standard Windows pointer input.
        abs_x,abs_y=win.x+x,win.y+y
        if not self.user32.SetCursorPos(abs_x,abs_y):
            raise LiveError('Windows 마우스 포인터 이동 실패')
        self.user32.mouse_event(0x0002,0,0,0,0) # left down
        self.user32.mouse_event(0x0004,0,0,0,0) # left up


@dataclass
class ClickTemplate:
    hwnd: int
    width: int
    height: int
    rel_x: float
    rel_y: float
    image_png: bytes
    description: str = '사용자 지정 버튼'

    def validate(self):
        if self.hwnd <= 0 or self.width < 200 or self.height < 200:
            raise LiveError('대상 창 설정이 잘못되었습니다.')
        if not (0.04 <= self.rel_x <= .96 and .04 <= self.rel_y <= .96):
            raise LiveError('가장자리 클릭은 지원하지 않습니다.')
        if len(self.image_png) > 200_000:
            raise LiveError('확인용 템플릿이 너무 큽니다.')
        return self


def _button_box(image: Image.Image, rel_x: float, rel_y: float):
    w,h=image.size
    x,y=int(w*rel_x),int(h*rel_y)
    # Strict fixed-size crop, no guessing across responsive layouts.
    return (x-45,y-24,x+45,y+24)


def create_template(image: Image.Image, hwnd: int, rel_x: float, rel_y: float,
                    description='사용자 지정 버튼') -> ClickTemplate:
    if image.width < 200 or image.height < 200:
        raise LiveError('작은 화면에서는 클릭 템플릿을 등록할 수 없습니다.')
    if not .04 <= rel_x <= .96 or not .04 <= rel_y <= .96:
        raise LiveError('게임 창 가장자리는 클릭 등록을 허용하지 않습니다.')
    box=_button_box(image,rel_x,rel_y)
    if box[0]<0 or box[1]<0 or box[2]>image.width or box[3]>image.height:
        raise LiveError('버튼 영역이 게임 창을 벗어났습니다.')
    buffer=io.BytesIO()
    image.crop(box).convert('RGB').save(buffer,format='PNG')
    return ClickTemplate(hwnd,image.width,image.height,rel_x,rel_y,
                         buffer.getvalue(), description).validate()


def match_template(template: ClickTemplate, image: Image.Image, threshold=0.985) -> bool:
    template.validate()
    if image.size != (template.width,template.height):
        return False
    crop=image.crop(_button_box(image,template.rel_x,template.rel_y)).convert('RGB')
    with Image.open(io.BytesIO(template.image_png)) as source:
        reference=source.convert('RGB')
    if reference.size!=crop.size:
        return False
    # Averaging over the entire crop; strict and intentionally fragile to animated scenes.
    diff=ImageChops.difference(reference,crop)
    means=ImageStat.Stat(diff).mean
    similarity=1-sum(means)/(len(means)*255)
    return similarity>=threshold


class OneClickGuard:
    """Only one click per explicit arm. Consecutive matching frames required."""
    def __init__(self,backend,stable_frames=2):
        self.backend=backend
        self.stable_frames=max(2,int(stable_frames))
        self.template: Optional[ClickTemplate]=None
        self.armed=False
        self.matches=0
        self.done=False

    def register(self, template: ClickTemplate):
        self.template=template.validate()
        self.disarm()
        self.done=False

    def arm(self):
        if self.template is None:
            raise LiveError('먼저 실제 버튼을 지정하고 등록하세요.')
        self.armed=True
        self.done=False
        self.matches=0

    def disarm(self):
        self.armed=False
        self.matches=0

    def observe(self, img: Image.Image, hwnd: int):
        if not self.armed or self.done or not self.template:
            return '비활성'
        if hwnd!=self.template.hwnd or not self.backend.active(hwnd):
            self.disarm()
            return '창 전환 감지: 자동 클릭 중단'
        if not match_template(self.template,img):
            self.matches=0
            return '화면 불일치: 클릭 보류'
        self.matches+=1
        if self.matches<self.stable_frames:
            return '화면 재확인 중'
        self.disarm() # disarm *before* the attempt; no retry on exception
        self.done=True
        x=int(self.template.width*self.template.rel_x)
        y=int(self.template.height*self.template.rel_y)
        self.backend.click(hwnd,x,y)
        return '사용자 등록 버튼 1회 클릭 실행 (자동 재클릭 없음)'
