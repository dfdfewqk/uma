"""R50 foreground-only registered-scene clicker.

Registered TP/skill/result/repeat buttons are NOT clicked based on text guesses.
Caller must supply R49 StageAdvice.input_ready backed by stable OCR scene facts.
No premium or background input; re-check focused HWND, full client rect, target
patch, scene-marker patch and optional numeric invariants immediately before.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time

from visual_controls_r50 import ControlProfile,unique_scene,recognize,allowed_action

class SceneClickBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class SceneTicket:
    hwnd: int
    rect: tuple[int,int,int,int]
    profile_identity: str
    stage: str
    action: str
    issued_at: float
    source_evidence: str
    approved: bool
    numeric_verified: bool
    free_confirmed: bool=False


class RegisteredScenePointer:
    def __init__(self, *, dry_run=True, clock=time.monotonic):
        self.dry_run=dry_run
        self.clock=clock
        self.used=set()

    def click(self, ticket:SceneTicket, image, profiles:tuple[ControlProfile,...]):
        if (not ticket.approved or not ticket.numeric_verified
                or type(ticket.hwnd) is not int or ticket.hwnd<=0
                or len(ticket.source_evidence)<8 or not ticket.action):
            raise SceneClickBlocked("사용자 활성화/실제 수치 검수가 부족합니다.")
        if not allowed_action(ticket.stage,ticket.action):
            raise SceneClickBlocked("등록되지 않은 종류의 조작입니다.")
        if ticket.stage=="tp" and ticket.action.startswith("free_tp:") and not ticket.free_confirmed:
            raise SceneClickBlocked("무료 TP 사용을 확인하지 못했습니다.")
        if self.clock()<ticket.issued_at or self.clock()-ticket.issued_at>2.5:
            raise SceneClickBlocked("오래된 클릭 명령입니다.")
        identity=(ticket.hwnd,ticket.source_evidence,ticket.action)
        if identity in self.used:
            raise SceneClickBlocked("같은 게임 화면에 중복 입력 금지")
        if (not isinstance(ticket.rect,tuple) or len(ticket.rect)!=4
                or any(type(n) is not int for n in ticket.rect)):
            raise SceneClickBlocked("게임 창 좌표 오류")
        width=ticket.rect[2]-ticket.rect[0]
        height=ticket.rect[3]-ticket.rect[1]
        if image is None or image.size!=(width,height):
            raise SceneClickBlocked("클릭 직전 실제 화면 크기가 다릅니다.")
        stage,matches=unique_scene(image,profiles)
        if stage!=ticket.stage:
            raise SceneClickBlocked("클릭 직전 화면 장면을 다시 인식하지 못했습니다.")
        found=[m for m in matches if m.action==ticket.action and
               m.profile_identity==ticket.profile_identity and m.score>=.92]
        if len(found)!=1:
            raise SceneClickBlocked("클릭 대상이 화면에서 유일하게 재확인되지 않았습니다.")
        profile=next((p for p in profiles if p.identity==ticket.profile_identity),None)
        if profile is None or not profile.reviewed or (ticket.stage=="tp" and
            ticket.action.startswith("free_tp:") and not profile.free_only):
            raise SceneClickBlocked("사용자 검수된 버튼 템플릿 불일치")
        # Runtime numeric amount and item selection are independently checked
        # by the stage planner; visual clicker NEVER bypasses its decision.
        if self.dry_run:
            return False
        if os.name!="nt":
            raise SceneClickBlocked("실제 클릭은 Windows 게임에서만 가능합니다.")
        import ctypes
        from companion_window import discover_windows
        u=ctypes.windll.user32
        game=next((w for w in discover_windows() if w.hwnd==ticket.hwnd),None)
        if game is None or game.rect!=ticket.rect or u.IsIconic(ticket.hwnd):
            raise SceneClickBlocked("게임 창/좌표 변경·최소화")
        if u.GetForegroundWindow()!=ticket.hwnd:
            raise SceneClickBlocked("게임 창이 현재 활성 상태가 아닙니다.")
        x=round(ticket.rect[0]+found[0].x*width)
        y=round(ticket.rect[1]+found[0].y*height)
        if not u.SetCursorPos(x,y) or u.GetForegroundWindow()!=ticket.hwnd:
            raise SceneClickBlocked("클릭 직전 창 활성 상태가 변경됐습니다.")
        u.mouse_event(0x0002,0,0,0,0)
        u.mouse_event(0x0004,0,0,0,0)
        self.used.add(identity)
        if len(self.used)>512:
            # Fail closed rather than silently allow duplicate old clicks.
            raise SceneClickBlocked("자동 클릭 세션 한도 도달 · 다시 확인 필요")
        return True
