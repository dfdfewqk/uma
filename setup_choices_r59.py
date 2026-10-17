"""R59 passive user-registered choices before KR Uma cultivation.

Normal start and temporary-event routes are distinct. A template is only a
visible option, NEVER an approved click or a verified current selection.
No input, game memory access, remote upload, currency or training scores.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import tempfile

from PIL import Image
from visual_controls_r50 import _bbox, _png, _decode, _match_patch, crop

SCHEMA = "uma_r59_setup_choice_v1"
BRANCHES = ("normal", "event")
MAX_PROFILES = 80
MAX_BYTES = 3_000_000


def _label(value, max_length=60):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= max_length
            or any(ord(ch) < 32 for ch in value)):
        raise ValueError("화면 선택지 이름이 올바르지 않습니다")
    return value.strip()


@dataclass(frozen=True)
class SetupChoice:
    branch: str
    step: str
    choice: str
    width: int
    height: int
    scene_box: tuple[float, float, float, float]
    button_box: tuple[float, float, float, float]
    scene_png: str
    button_png: str
    reviewed: bool = True
    source: str = "user_marked_live_kr_setup"
    schema: str = SCHEMA
    # Optional *observed selected-state* marker from an actual game screen.
    # Older R59 profiles remain readable with all three fields at defaults.
    selected_box: tuple[float, float, float, float] | None = None
    selected_png: str | None = None
    selected_reviewed: bool = False

    @property
    def identity(self):
        return self.branch, self.step, self.choice

    def validate(self):
        if self.schema != SCHEMA or self.branch not in BRANCHES:
            raise ValueError("지원되지 않는 시작 경로 또는 설정 버전")
        _label(self.step, 50)
        _label(self.choice, 60)
        if self.reviewed is not True or self.source != "user_marked_live_kr_setup":
            raise ValueError("실제 게임에서 확인한 선택지 표시가 아닙니다")
        if (type(self.width) is not int or type(self.height) is not int
                or self.width < 300 or self.height < 520
                or self.width * self.height > 24_000_000):
            raise ValueError("원본 게임 화면 크기 오류")
        a = _bbox(self.scene_box)
        b = _bbox(self.button_box)
        if max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1])) > 0:
            raise ValueError("화면 고유 표식과 버튼 영역이 겹칩니다")
        for ref, box in ((self.scene_png, a), (self.button_png, b)):
            im = _decode(ref)
            if (abs(im.width - round((box[2]-box[0])*self.width)) > 2
                    or abs(im.height - round((box[3]-box[1])*self.height)) > 2):
                raise ValueError("등록된 부분 이미지 크기가 실제 화면과 다릅니다")
        if any((self.selected_box is not None, self.selected_png is not None,
                self.selected_reviewed is True)):
            if (self.selected_box is None or self.selected_png is None
                    or self.selected_reviewed is not True):
                raise ValueError("선택 표시 영역은 실제 선택된 게임 화면에서만 등록")
            box = _bbox(self.selected_box)
            image = _decode(self.selected_png)
            if (abs(image.width-round((box[2]-box[0])*self.width))>2
                    or abs(image.height-round((box[3]-box[1])*self.height))>2):
                raise ValueError("선택 표식의 이미지/원본 화면 크기가 다릅니다")
        return self


def register_choice(image, *, branch, step, choice, scene_box, button_box,
                    reviewed=False, selected_box=None, selected_reviewed=False):
    from training_preview_r48 import portrait_supported
    if not isinstance(image, Image.Image) or not portrait_supported(image):
        raise ValueError("현재 지원하지 않는 한국 PC 게임 창 비율")
    a = _bbox(scene_box)
    b = _bbox(button_box)
    if (selected_box is None) != (selected_reviewed is False):
        raise ValueError("선택 표식은 선택된 실제 게임 화면 확인 후에만 등록")
    selected = _bbox(selected_box) if selected_box is not None else None
    obj = SetupChoice(branch, _label(step, 50), _label(choice, 60),
                      image.width, image.height, a, b,
                      _png(crop(image, a)), _png(crop(image, b)), reviewed,
                      selected_box=selected,
                      selected_png=(_png(crop(image, selected)) if selected else None),
                      selected_reviewed=selected_reviewed)
    return obj.validate()


def load_choices(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("연결된 설정 파일 사용 금지")
    if not path.exists():
        return ()
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("선택지 등록 파일 용량 초과")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or not isinstance(data.get("choices"), list)
            or len(data["choices"]) > MAX_PROFILES):
        raise ValueError("육성 선택지 등록 형식 오류")
    records = tuple(SetupChoice(**{
        **item, "scene_box": tuple(item["scene_box"]),
        "button_box": tuple(item["button_box"]),
        "selected_box": (tuple(item["selected_box"])
                         if item.get("selected_box") is not None else None)}).validate()
        for item in data["choices"])
    if len({x.identity for x in records}) != len(records):
        raise ValueError("중복 등록된 화면 선택지")
    return records


def save_choice(path, item):
    item.validate()
    path = Path(path)
    old = load_choices(path)
    if len(old) >= MAX_PROFILES or any(x.identity == item.identity for x in old):
        raise ValueError("같은 경로/단계/선택지 덮어쓰기 금지 · 백업 후 검토 필요")
    raw = json.dumps({"schema": SCHEMA, "choices": [asdict(x) for x in (*old, item)]},
                     ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("선택지 설정 크기 제한 초과")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".uma_r59_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def visible_choice(image, choice):
    """Two independent patches, exact game geometry, display-only output."""
    choice.validate()
    if not isinstance(image, Image.Image) or image.size != (choice.width, choice.height):
        return False
    a, _ = _match_patch(image, choice.scene_box, choice.scene_png, .92)
    b, _ = _match_patch(image, choice.button_box, choice.button_png, .94)
    return a and b


def selected_marker_visible(image, choice):
    """A marker is evidence only when the user registered a selected state."""
    choice.validate()
    if not (choice.selected_reviewed and choice.selected_box
            and choice.selected_png and visible_choice(image, choice)):
        return False
    found, _ = _match_patch(image, choice.selected_box, choice.selected_png, .94)
    return bool(found)


@dataclass(frozen=True)
class SetupChoiceView:
    branch: str | None
    step: str | None
    choices: tuple[str, ...]
    status: str
    game_input_allowed: bool = False
    click_position: None = None
    selected_choice: str | None = None
    ml_training_label: bool = False


class StableSetupChoices:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.count = 0

    def observe(self, image, *, hwnd, rect, active, scene, profiles):
        if (not active or image is None or type(hwnd) is not int or hwnd <= 0 or
                not isinstance(rect, tuple) or len(rect) != 4 or
                scene not in ("육성 준비", "TP 회복", "팝업/기타", None)):
            self.reset()
            return SetupChoiceView(None, None, (), "육성 시작 전 화면이 아니거나 게임 창 비활성")
        if not profiles:
            self.reset()
            return SetupChoiceView(None, None, (), "일반/이벤트 시작 선택지 기준 미등록")
        matches = tuple(p for p in profiles if visible_choice(image, p))
        routes = {(p.branch, p.step) for p in matches}
        if len(routes) != 1:
            self.reset()
            return SetupChoiceView(None, None, (), "시작 경로/단계가 불확실하거나 중복 · 선택 보류")
        branch, step = next(iter(routes))
        choices = tuple(sorted({p.choice for p in matches}))
        selected = tuple(sorted({p.choice for p in matches
                                 if selected_marker_visible(image,p)}))
        if len(selected)>1:
            self.reset()
            return SetupChoiceView(None,None,(),"서로 다른 선택 표식 동시 감지 · 상태 보류")
        selected_choice=selected[0] if selected else None
        token = (hwnd, rect, image.size, scene, branch, step, choices, selected_choice)
        self.count = min(self.count + 1, 2) if token == self.previous else 1
        self.previous = token
        if self.count < 2:
            return SetupChoiceView(None, None, (), "화면 선택지를 한 번 더 확인하는 중")
        return SetupChoiceView(
            branch, step, choices,
            "화면 선택지 확인 · 실제 클릭/진행은 사용자 검수 전 보류",
            selected_choice=selected_choice)
