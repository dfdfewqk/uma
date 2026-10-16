"""R44 click-only cultivation planning preferences (NOT automatic game input).

Existing R39 goal files and all previous run data remain untouched.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import os
import tempfile

SCHEMA = "uma_r44_preferences_v1"
REPEAT_CHOICES = tuple(range(1, 101)) + (150, 200, 300, 500, 1000)


@dataclass(frozen=True)
class Preferences:
    repeats: int = 20

    def validate(self):
        if type(self.repeats) is not int or not 1 <= self.repeats <= 10000:
            raise ValueError("반복 육성 횟수는 1~10000회 사이여야 합니다.")
        return self


def load_preferences(path):
    path = Path(path)
    if not path.is_file():
        return Preferences()
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("설정 파일 형식/크기 확인 필요")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("반복 육성 설정 버전 오류")
    return Preferences(data["repeats"]).validate()


def save_preferences(path, preferences):
    preferences.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".uma_r44_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA, "repeats": preferences.repeats},
                      f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def describe_plan(target, preferences, course=None):
    """No character/deck/parent defaults: they must come from the actual game."""
    preferences.validate()
    if target is None:
        return "통합 대회 1~4회차와 각질을 선택해 주세요."
    target.validate()
    suffix = " · 한국 서버 코스 정보 미검증" if course is None else " · 코스 참고 정보 확인"
    return f"{target.label} · 반복 {preferences.repeats}회 계획" + suffix
