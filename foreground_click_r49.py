"""R49 opt-in, foreground-only Windows game pointer with independent rechecks.

No process/memory inspection, network, injection, currency-spending fallback, or
background clicks. A single attempt only; a caller MUST see a new game frame.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import os
import time

SAFE_KINDS = frozenset({"preview_training", "confirm_training", "reviewed_scene_action"})
MAX_FRAME_AGE = 3.5


class AutoInputBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class ClickIntent:
    hwnd: int
    rect: tuple[int, int, int, int]
    x: float
    y: float
    kind: str
    expected_scene: str
    expected_selection: str | None
    frame_signature: str
    timestamp: float
    target_label: str = ""
    is_free: bool = False

    def validate(self):
        if type(self.hwnd) is not int or self.hwnd <= 0:
            raise AutoInputBlocked("검수된 게임 창 ID가 없습니다.")
        if self.kind not in SAFE_KINDS or not self.expected_scene:
            raise AutoInputBlocked("허용하지 않는 게임 입력 종류입니다.")
        if (not isinstance(self.rect, tuple) or len(self.rect) != 4 or
                any(type(v) is not int for v in self.rect)):
            raise AutoInputBlocked("게임 영역 좌표 오류")
        left, top, right, bottom = self.rect
        if right - left < 300 or bottom - top < 320 or (right-left)*(bottom-top) > 24_000_000:
            raise AutoInputBlocked("게임 창 크기가 허용 범위를 벗어났습니다.")
        if not isinstance(self.x, (int,float)) or not isinstance(self.y, (int,float)):
            raise AutoInputBlocked("좌표 형식 오류")
        if not (.045 <= self.x <= .955 and .045 <= self.y <= .955):
            raise AutoInputBlocked("화면 가장자리 또는 외부 클릭은 차단합니다.")
        if not isinstance(self.frame_signature,str) or len(self.frame_signature) != 64:
            raise AutoInputBlocked("화면 식별 정보가 없습니다.")
        if not isinstance(self.timestamp, (int,float)) or self.timestamp < 0:
            raise AutoInputBlocked("화면 관측 시간 오류")
        return self


class ForegroundWindowsPointer:
    def __init__(self, *, dry_run: bool = True, clock: Callable[[],float] = time.monotonic):
        self.dry_run = dry_run
        self.clock = clock
        self.clicked = set()

    def click(self, intent: ClickIntent, *, approved: bool, fresh_image, observed_selection: str | None):
        """One physical click; enforce focused HWND, exact rect & fresh image proof.

        A real click MUST be called from a direct user-armed local session.
        If anything is uncertain, raise and never send the mouse event.
        """
        intent.validate()
        if not approved:
            raise AutoInputBlocked("사용자가 자동 실행을 활성화하지 않았습니다.")
        if self.clock() - intent.timestamp > MAX_FRAME_AGE or self.clock() < intent.timestamp:
            raise AutoInputBlocked("화면 확인이 오래돼 입력을 중단합니다.")
        if intent.frame_signature in self.clicked:
            raise AutoInputBlocked("같은 프레임에 중복 클릭하지 않습니다.")
        if fresh_image is None:
            raise AutoInputBlocked("클릭 직전 게임 화면을 다시 촬영해야 합니다.")
        if tuple(fresh_image.size) != (intent.rect[2]-intent.rect[0],intent.rect[3]-intent.rect[1]):
            raise AutoInputBlocked("클릭 직전 창 크기가 달라졌습니다.")
        if intent.expected_scene != "훈련":
            raise AutoInputBlocked("검증되지 않은 장면의 자동 클릭은 중단합니다.")
        from training_preview_r48 import _turn_signature,selected_training
        detected_now=selected_training(fresh_image)
        if (intent.expected_selection is None or observed_selection != intent.expected_selection
                or detected_now != intent.expected_selection):
            raise AutoInputBlocked("클릭 직전 실제 훈련 표식이 다릅니다.")
        import hashlib
        expected_digest=hashlib.sha256(
            (str(_turn_signature(fresh_image))+"|"+intent.expected_selection+"|"
             +intent.kind+"|"+intent.target_label).encode("utf-8")).hexdigest()
        if expected_digest != intent.frame_signature:
            raise AutoInputBlocked("클릭 직전 턴/선택지 식별값이 달라졌습니다.")
        if self.dry_run:
            return False
        if os.name != "nt":
            raise AutoInputBlocked("실제 입력은 Windows 게임 창에서만 허용합니다.")
        import ctypes
        from ctypes import wintypes
        from companion_window import discover_windows
        user32=ctypes.windll.user32
        current=next((w for w in discover_windows() if w.hwnd == intent.hwnd),None)
        if current is None or current.rect != intent.rect:
            raise AutoInputBlocked("게임 창 ID 또는 실제 위치가 바뀌었습니다.")
        if user32.GetForegroundWindow() != intent.hwnd or user32.IsIconic(intent.hwnd):
            raise AutoInputBlocked("게임이 현재 활성 창이 아닙니다.")
        # SetCursorPos and mouse_event only simulate an ordinary foreground click.
        # They do not bypass game protections; never target background windows.
        x=round(intent.rect[0]+intent.x*(intent.rect[2]-intent.rect[0]))
        y=round(intent.rect[1]+intent.y*(intent.rect[3]-intent.rect[1]))
        if not user32.SetCursorPos(x,y):
            raise AutoInputBlocked("마우스 이동 실패")
        # Recheck focus once more after mouse movement.
        if user32.GetForegroundWindow() != intent.hwnd:
            raise AutoInputBlocked("다른 창이 활성화되어 클릭을 차단했습니다.")
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        self.clicked.add(intent.frame_signature)
        if len(self.clicked)>512:
            self.clicked=set(list(self.clicked)[-128:])
        return True
