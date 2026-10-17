"""R55 read-only evidence assembly for the five Korean-client training previews.

The R48 collector supplies independently double-observed stat-gain candidates.
R54 supplies separately stable OCR candidates scoped to a selected training.
Neither source proves support bonds/friendship, the action outcome, or the
optimal decision. No game input, network, storage, or model training occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

TRAININGS = ("스피드", "스태미나", "파워", "근성", "지능")
EXTRA_LIMITS = {"실패율": 100, "체력 소모": 100, "스킬 Pt 증가": 200}


@dataclass(frozen=True)
class TrainingOptionEvidence:
    name: str
    stat_gains: tuple[int, int, int, int, int]
    failure_rate: int | None = None
    energy_cost: int | None = None
    skill_point_gain: int | None = None
    friendship_count: int | None = None
    support_bond_gain: int | None = None
    stat_gains_source: str = "r48_twice_observed_ocr_candidate"

    @property
    def stat_total(self) -> int:
        return sum(self.stat_gains)

    @property
    def extras_count(self) -> int:
        return sum(x is not None for x in
                   (self.failure_rate, self.energy_cost, self.skill_point_gain))


@dataclass(frozen=True)
class TrainingEvidenceView:
    selected: str | None
    options: tuple[TrainingOptionEvidence, ...]
    stat_count: int
    risk_count: int
    explanation: str
    source: str = "unreviewed_kr_ocr_candidate"
    game_input_allowed: bool = False
    decision_ready: bool = False
    ml_training_label: bool = False


class TrainingEvidenceCollector:
    """Keep 5 option records only within one unchanged window/size/turn."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.scope = None
        self.records: dict[str, TrainingOptionEvidence] = {}

    def _view(self, selected=None, reason=None):
        options = tuple(self.records[k] for k in TRAININGS if k in self.records)
        risk_count = sum(o.failure_rate is not None for o in options)
        if reason is None:
            reason = (f"훈련 후보 스탯 {len(options)}/5 · 실패율 {risk_count}/5 · "
                      "우정/인연·체력 소모·스킬 Pt 증가 미검수 · 자동 최적화 보류")
        return TrainingEvidenceView(selected, options, len(options), risk_count, reason)

    def observe(self, *, scene: str | None, selected: str | None,
                window_key: int | None, window_rect: tuple | None,
                image_size: tuple[int, int], turn_signature: str | None,
                preview_readings: Mapping,
                numeric_candidates: Mapping[str, int] | None = None):
        if (scene != "훈련" or selected not in TRAININGS or
                type(window_key) is not int or not window_rect or
                len(window_rect) != 4 or len(image_size) != 2 or
                not isinstance(turn_signature, str) or len(turn_signature) != 64):
            self.reset()
            return self._view(reason="훈련 화면/턴/게임 창 확인 전 · 후보 폐기")
        if not isinstance(preview_readings, Mapping):
            self.reset()
            return self._view(reason="R48 훈련 후보가 유효하지 않습니다")
        scope = (window_key, tuple(window_rect), tuple(image_size), turn_signature)
        if scope != self.scope:
            self.reset()
            self.scope = scope
        keys = set(preview_readings)
        if len(keys) > 5 or not keys.issubset(TRAININGS):
            self.reset()
            return self._view(reason="훈련 후보 이름 중복/불일치 · 후보 폐기")
        # R48 must already have observed two identical gain screens per option.
        for name in TRAININGS:
            raw = preview_readings.get(name)
            if raw is None:
                self.records.pop(name, None)
                continue
            gains = getattr(raw, "gains", None)
            if (getattr(raw, "name", None) != name or
                    getattr(raw, "signature", None) != turn_signature or
                    getattr(raw, "ocr_candidate", None) is not True or
                    not isinstance(gains, tuple) or len(gains) != 5 or
                    any(type(v) is not int or not 0 <= v <= 150 for v in gains)):
                self.records.pop(name, None)
                continue
            previous = self.records.get(name)
            if previous is None or previous.stat_gains != gains:
                self.records[name] = TrainingOptionEvidence(name, gains)
        # Extras are CURRENTLY SELECTED option only: R54 turn scope includes
        # both the turn fingerprint and selected training name.
        if selected in self.records and numeric_candidates:
            current = self.records[selected]
            extra = {}
            for field, attr in (("실패율", "failure_rate"),
                                ("체력 소모", "energy_cost"),
                                ("스킬 Pt 증가", "skill_point_gain")):
                number = numeric_candidates.get(field)
                if type(number) is int and 0 <= number <= EXTRA_LIMITS[field]:
                    extra[attr] = number
            if extra:
                from dataclasses import replace
                self.records[selected] = replace(current, **extra)
        return self._view(selected=selected)
