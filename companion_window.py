"""Find a visible Windows game window. Read-only; no injection or keyboard hooks."""
from __future__ import annotations
import os


def discover_windows():
    if os.name != 'nt':
        return []
    import ctypes
    from ctypes import wintypes
    from companion_core import GameWindow
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.IsWindowVisible.restype=wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes=[wintypes.HWND]
    user32.GetWindowTextLengthW.restype=ctypes.c_int
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype=wintypes.BOOL
    user32.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype=wintypes.BOOL
    out=[]
    enumproc=ctypes.WINFUNCTYPE(ctypes.c_bool,wintypes.HWND,wintypes.LPARAM)
    def callback(hwnd,lp):
        if not user32.IsWindowVisible(hwnd): return True
        n=user32.GetWindowTextLengthW(hwnd)
        if n<=0: return True
        buf=ctypes.create_unicode_buffer(n+2)
        user32.GetWindowTextW(hwnd,buf,n+2)
        cls=ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd,cls,256)
        box=wintypes.RECT()
        if not user32.GetClientRect(hwnd,ctypes.byref(box)):
            return True
        pos=wintypes.POINT(0,0)
        if not user32.ClientToScreen(hwnd,ctypes.byref(pos)):
            return True
        left,top=pos.x,pos.y
        out.append(GameWindow(int(hwnd),buf.value,(left,top,left+box.right,top+box.bottom),cls.value))
        return True
    user32.EnumWindows(enumproc(callback),0)
    return out


def same_game_window(hwnd):
    return any(w.hwnd==hwnd for w in discover_windows())
