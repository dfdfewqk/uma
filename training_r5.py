"""R5: manually-verified training-option evidence and safe comparison gate.

The input values are NOT game mechanics, AI/ML predictions, or an OCR accuracy claim.
This module reads no game memory, injects no input and never decides to end a run.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from uma_core import Action, STATS, RunProfile, TurnState, rank_actions
from screen_r4 import load_image, sha256_file, tesseract_executable, _recognize_one

TRAINING_CHOICES = STATS + ('섬 트레이닝',)
GAIN_FIELDS = tuple(f'{s} 상승' for s in STATS)
FIELDS = GAIN_FIELDS + ('스킬 Pt 상승', '실패 확률', '체력 변화', '우정 발동 시설 수', '발전 Pt 증가', '인연도 증가(추정)')
MANDATORY = GAIN_FIELDS + ('스킬 Pt 상승', '실패 확률', '체력 변화')
LIMITS = {**{s: (0, 999) for s in GAIN_FIELDS}, '스킬 Pt 상승': (0, 9999),
          '실패 확률': (0, 100), '체력 변화': (-100, 100),
          '우정 발동 시설 수': (0, 5), '발전 Pt 증가': (0, 9999),
          '인연도 증가(추정)': (0, 100)}
SCHEMA = 'uma_training_evidence_r5_v1'
MAX_BYTES = 3_000_000


class EvidenceError(ValueError):
    pass


def parse_value(field: str, raw: str, ocr: bool = False) -> int:
    if field not in LIMITS:
        raise EvidenceError('지원하지 않는 훈련 항목입니다.')
    text = str(raw).strip().replace(',', '')
    if ocr and field == '실패 확률':
        text = text.removesuffix('%')
    if not text or any(c not in '0123456789-' for c in text):
        raise EvidenceError(f'{field}: 숫자를 확인하세요.')
    if text.startswith('-') and field != '체력 변화':
        raise EvidenceError(f'{field}: 음수는 지원하지 않습니다.')
    if '-' in text[1:] or len(text) > 6:
        raise EvidenceError(f'{field}: 올바른 정수가 아닙니다.')
    try:
        value = int(text)
    except ValueError as exc:
        raise EvidenceError(f'{field}: 숫자 오류') from exc
    low, high = LIMITS[field]
    if not low <= value <= high:
        raise EvidenceError(f'{field}: 허용 범위 {low}~{high}를 벗어났습니다.')
    return value


@dataclass
class OptionEvidence:
    name: str
    values: dict[str, int] = field(default_factory=dict)
    confirmed: set[str] = field(default_factory=set)
    sources: dict[str, str] = field(default_factory=dict)
    screenshot_sha256: Optional[str] = None
    screenshot_file: str = ''

    def confirm(self, field_name: str, raw: str, source: str = 'manual') -> int:
        if field_name not in FIELDS or self.name not in TRAINING_CHOICES:
            raise EvidenceError('선택지/필드가 올바르지 않습니다.')
        if source not in ('manual', 'ocr_reviewed'):
            raise EvidenceError('검수 출처를 확인하세요.')
        value = parse_value(field_name, raw)
        self.values[field_name] = value
        self.confirmed.add(field_name)
        self.sources[field_name] = source
        return value

    def invalidate(self, field_name: str) -> None:
        self.confirmed.discard(field_name)
        self.values.pop(field_name, None)
        self.sources.pop(field_name, None)

    def complete(self) -> bool:
        required = set(MANDATORY)
        if self.name == '섬 트레이닝':
            required.add('우정 발동 시설 수')
        return required.issubset(self.confirmed) and all(k in self.values for k in required)

    def missing(self) -> list[str]:
        required = MANDATORY + (('우정 발동 시설 수',) if self.name == '섬 트레이닝' else ())
        return [key for key in required if key not in self.confirmed]

    def to_action(self) -> Action:
        if not self.complete():
            raise EvidenceError(f'{self.name}의 필수값이 누락되었습니다: {", ".join(self.missing())}')
        g = {stat: self.values[f'{stat} 상승'] for stat in STATS}
        return Action(name=self.name, gains=g,
                      skill_points=self.values['스킬 Pt 상승'],
                      failure_percent=float(self.values['실패 확률']),
                      energy_delta=self.values['체력 변화'],
                      friend_types=self.values.get('우정 발동 시설 수', 0),
                      development_points=self.values.get('발전 Pt 증가', 0),
                      bond_gain=self.values.get('인연도 증가(추정)', 0), observed=True,
                      notes='R5 사용자 확인 수치(실제 게임 규칙 검증 전)')

    def attach_screenshot(self, path: Path) -> str:
        load_image(path)
        self.screenshot_sha256 = sha256_file(path)
        self.screenshot_file = str(Path(path).resolve())
        # Different screenshot does not imply previous fields remain correct.
        self.values.clear()
        self.confirmed.clear()
        self.sources.clear()
        return self.screenshot_sha256


@dataclass
class Comparison:
    status: str
    missing: dict[str, list[str]]
    ranked: list
    explanation: str


def compare_options(profile: RunProfile, state: TurnState,
                    evidence: dict[str, OptionEvidence]) -> Comparison:
    """No winner unless every AVAILABLE training option is fully reviewed.

    Rest/outings/races are intentionally not compared: never claim overall best action.
    """
    required_names = list(STATS)
    if state.island_tickets > 0:
        required_names.append('섬 트레이닝')
    missing = {}
    for name in required_names:
        record = evidence.get(name)
        if record is None or record.name != name:
            missing[name] = list(MANDATORY) + (['우정 발동 시설 수'] if name == '섬 트레이닝' else [])
        elif not record.complete():
            missing[name] = record.missing()
    if missing:
        return Comparison('추천 보류', missing, [],
            '비교할 모든 훈련의 필수 수치를 사용자 확인해야 합니다. 누락된 수치를 0으로 가정하지 않습니다.')
    actions = {name: evidence[name].to_action() for name in required_names}
    # Exclusion of physically impossible choices is handled by the existing engine.
    ranked = rank_actions(profile, state, actions)
    if not ranked:
        return Comparison('추천 보류', {}, [], '가능한 훈련이 없습니다. 체력 또는 입력값을 확인하세요.')
    return Comparison('훈련끼리 비교 가능 (실험값)', {}, ranked,
        '입력한 훈련 선택지끼리만 비교했습니다. 휴식·레이스·외출과는 비교하지 않았고, ' 
        '실전 최적 선택·도축 판단·승률을 예측하지 않습니다.')


def ocr_candidate(path: Path, box: tuple[float, float, float, float],
                  field_name: str, binary: str = '') -> dict:
    """Read a rectangle only; return an untrusted candidate, NEVER auto-confirm."""
    if field_name not in FIELDS:
        raise EvidenceError('지원하지 않는 항목입니다.')
    if field_name == '체력 변화':
        raise EvidenceError('체력 변화의 +/- 부호는 자동 추정하지 않습니다. 직접 확인해 입력하세요.')
    if len(box) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box):
        raise EvidenceError('OCR 영역 좌표가 잘못되었습니다.')
    x1,y1,x2,y2 = box
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1 and x2-x1 >= .003 and y2-y1 >= .003):
        raise EvidenceError('OCR 영역은 이미지 내부여야 합니다.')
    exe = tesseract_executable(binary)
    if not exe:
        raise EvidenceError('Tesseract가 설치되지 않았습니다. 수동 입력은 계속 사용할 수 있습니다.')
    pic = load_image(path)
    crop = pic.crop((int(x1*pic.width), int(y1*pic.height),
                     max(1, math.ceil(x2*pic.width)), max(1, math.ceil(y2*pic.height))))
    text, confidence = _recognize_one(crop, exe)
    try:
        val = parse_value(field_name, text, ocr=True)
    except EvidenceError:
        val = None
    ok = val is not None and confidence is not None and confidence >= 65
    return {'field': field_name, 'raw_text': text, 'candidate': val if ok else None,
            'confidence': confidence, 'status': '사용자 검수 필요' if ok else '인식 불확실',
            'source_sha256': sha256_file(path)}


def export_evidence(path: Path, evidence: dict[str, OptionEvidence],
                    profile: RunProfile, state: TurnState) -> Path:
    """Optional R5 audit export; does not automatically enter model training data."""
    from dataclasses import asdict
    result = {'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
              'scenario': profile.scenario, 'event': profile.event, 'turn_label': state.turn_label,
              'not_ml_training_label': True, 'not_official_game_values': True,
              'options': {key: {**asdict(ev), 'confirmed': sorted(ev.confirmed)} for key, ev in evidence.items()}}
    payload = json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')
    if len(payload) > MAX_BYTES:
        raise EvidenceError('저장할 검수 기록이 너무 큽니다.')
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='r5_', suffix='.json', dir=str(output.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return output
