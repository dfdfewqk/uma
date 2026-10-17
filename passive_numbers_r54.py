"""R54 read-only numeric OCR from user-marked live Korean-game regions.

Two agreeing OCR passes are required for a *candidate* number, NOT for proof
of a reward, purchase, training outcome or a machine-learning label.
Unknown scene/window/turn, missing engine, poor confidence and missing fields
fail closed. Existing R4 and R50 numeric profiles remain untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import math
import os
import re
import tempfile

from screen_r4 import FIELD_LIMITS, ScreenError, _recognize_one, parse_numeric
from visual_controls_r50 import _bbox

SCHEMA = "uma_r54_passive_numbers_v1"
NUMERIC_FIELDS = tuple(FIELD_LIMITS) + ("실패율",)
LIMITS = dict(FIELD_LIMITS, **{"실패율": (0, 100)})
SCENES = ("훈련", "스킬", "시설", "섬 훈련", "휴식/외출", "레이스", "육성 결과")
MAX_REGIONS = 40
MAX_BYTES = 60000
MIN_CONFIDENCE = 80


@dataclass(frozen=True)
class LiveNumberRegion:
    scene: str
    field: str
    box: tuple[float, float, float, float]
    width: int
    height: int
    reviewed: bool
    source: str = "manual_kr_game_number_region"

    def validate(self):
        if self.scene not in SCENES or self.field not in LIMITS:
            raise ValueError("지원하지 않는 한국 게임 숫자/화면 종류")
        if self.reviewed is not True or self.source != "manual_kr_game_number_region":
            raise ValueError("실제 한국 서버 숫자 위치 직접 확인 필요")
        if (type(self.width) is not int or type(self.height) is not int
                or not 300 <= self.width <= 8000 or self.height < 320
                or self.width * self.height > 24_000_000):
            raise ValueError("게임 숫자 영역의 캡처 크기 오류")
        x1, y1, x2, y2 = _bbox(self.box)
        if round((x2 - x1) * self.width) < 10 or round((y2 - y1) * self.height) < 10:
            raise ValueError("숫자 영역이 너무 작습니다")
        return self

    @property
    def identity(self):
        return self.scene, self.field

    def compatible(self, image):
        # UI positions may change under a different aspect/layout/zoom.
        return (abs(image.width / image.height - self.width / self.height) <= .012
                and .75 <= image.width / self.width <= 1.5
                and .75 <= image.height / self.height <= 1.5)


def read_regions(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("연결된 숫자 설정 파일 사용 불가")
    if not path.exists():
        return ()
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("숫자 설정 파일 용량 초과")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("regions"), list):
        raise ValueError("R54 숫자 설정 파일 형식 오류")
    if len(data["regions"]) > MAX_REGIONS:
        raise ValueError("R54 숫자 설정 수량 초과")
    regions = tuple(LiveNumberRegion(
        v["scene"], v["field"], tuple(v["box"]), v["width"], v["height"],
        v["reviewed"], v.get("source", "")).validate() for v in data["regions"])
    if len({r.identity for r in regions}) != len(regions):
        raise ValueError("같은 화면/수치 중복 등록")
    return regions


def save_region(path, region):
    region.validate()
    path = Path(path)
    old = read_regions(path)
    if len(old) >= MAX_REGIONS or any(r.identity == region.identity for r in old):
        raise ValueError("이미 등록된 항목을 덮어쓰지 않습니다. 기존 설정 백업 후 검토 필요")
    data = json.dumps({"schema": SCHEMA, "regions": [asdict(r) for r in (*old, region)]},
                      ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("숫자 설정 용량 제한")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".uma_r54_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def parse_live_number(raw, field):
    if field not in LIMITS:
        raise ValueError("등록되지 않은 수치")
    if field != "실패율":
        return parse_numeric(raw, field)
    value = str(raw).strip().replace(" ", "")
    if not re.fullmatch(r"[0-9]{1,3}%?", value):
        return None
    result = int(value.rstrip("%"))
    return result if 0 <= result <= 100 else None


def read_candidate(image, region, binary, confidence=MIN_CONFIDENCE):
    """OCR result is a candidate even after two matching frames."""
    region.validate()
    if not binary or not region.compatible(image):
        return None
    from visual_controls_r50 import crop
    try:
        part = crop(image, region.box)
        text, cert = _recognize_one(part, str(binary), timeout=4)
    except (OSError, ScreenError, ValueError):
        return None
    if cert is None or cert < confidence:
        return None
    return parse_live_number(text, region.field)


@dataclass(frozen=True)
class NumericCandidateFrame:
    numbers: dict[str, int]
    scene: str | None
    status: str
    source: str = "double_ocr_candidate_only"
    reviewed_outcome: bool = False
    authorized_for_click: bool = False
    ml_training_label: bool = False


class StableLiveNumberReader:
    def __init__(self):
        self.reset()

    def reset(self):
        self.scope = None
        self.previous = {}

    def observe(self, image, scene, regions, ocr_binary, window_key, window_rect=None, turn_key=None):
        if scene not in SCENES or image is None or not ocr_binary:
            self.reset()
            return NumericCandidateFrame({}, scene, "인식 가능한 화면/OCR 확인 전")
        registered = [r.validate() for r in regions if r.scene == scene]
        if not registered:
            self.reset()
            return NumericCandidateFrame({}, scene, "화면별 숫자 영역 미등록")
        if len({r.identity for r in registered}) != len(registered):
            self.reset()
            raise ValueError("한 장면에서 숫자 항목이 중복됐습니다")
        region_key = tuple(sorted((r.field, r.box, r.width, r.height) for r in registered))
        scope = (scene, window_key, window_rect, image.size, turn_key, region_key)
        if scope != self.scope:
            self.reset()
            self.scope = scope
        result = {}
        for region in registered:
            value = read_candidate(image, region, ocr_binary)
            if value is None:
                self.previous.pop(region.field, None)
                continue
            previous = self.previous.get(region.field)
            count = min((previous[1] + 1 if previous and previous[0] == value else 1), 2)
            self.previous[region.field] = (value, count)
            if count == 2:
                result[region.field] = value
        return NumericCandidateFrame(
            result, scene,
            ("현재 장면 OCR 잠정 수치 " + str(len(result)) + "개 (연속 확인, 검수 전)"
             if result else "수치 OCR 2회 일치 대기 · 불확실한 값 제외"))
