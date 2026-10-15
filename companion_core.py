"""Core rules for a lightweight companion UI. Fail closed on uncertain screens."""
from __future__ import annotations
from dataclasses import dataclass

MATCH_WORDS = ('우마무스메', 'ウマ娘', 'umamusume', 'pretty derby')
BROWSER_CLASSES = ('chrome_widgetwin', 'mozillawindowclass', 'internet explorer', 'applicationframewindow')

@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]
    class_name: str = ''

    @property
    def width(self): return self.rect[2] - self.rect[0]
    @property
    def height(self): return self.rect[3] - self.rect[1]


def is_game_candidate(title: str, class_name: str = '') -> bool:
    title = title.strip().casefold()
    cls = class_name.casefold()
    return bool(title and any(w in title for w in MATCH_WORDS) and
                not any(w in cls for w in BROWSER_CLASSES) and
                'trainer kr' not in title and '도우미' not in title)


def choose_window(windows: list[GameWindow]):
    """Never guess when several game windows look plausible."""
    candidates=[w for w in windows if is_game_candidate(w.title,w.class_name)
                and w.width >= 500 and w.height >= 320]
    if len(candidates) != 1:
        return None, ('게임 창 후보가 여러 개입니다. 창을 정리해야 합니다.' if candidates
                      else '실행 중인 우마무스메 게임 창을 찾지 못했습니다.')
    return candidates[0], '게임 창 감지됨 (화면 인식은 별도 검증 필요)'


def overlay_position(game_rect, screen_width, screen_height, panel_width=344, panel_height=505):
    x1, y1, x2, y2 = game_rect
    if x2 + panel_width + 12 <= screen_width:
        x=x2 + 8
    elif x1 - panel_width - 12 >= 0:
        x=x1-panel_width-8
    else:
        x=max(0, min(screen_width-panel_width, x2-panel_width))
    y=max(0,min(y1, screen_height-panel_height))
    return x,y


def usable_ocr_values(results):
    """Return only candidate values with OCR confidence, never verified data."""
    result={}
    for r in results:
        if r.number is None or r.confidence is None or r.confidence < 80:
            continue
        if '후보' not in r.status:
            continue
        result[r.field]=r.number
    return result


def recommendation_status(action_data_complete: bool, screen_verified: bool) -> str:
    if not screen_verified: return '화면 상태 미검증 · 추천 보류'
    if not action_data_complete: return '훈련 선택지 정보 부족 · 추천 보류'
    return '선택지 비교 가능 · 기존 판단 엔진에 전달'
