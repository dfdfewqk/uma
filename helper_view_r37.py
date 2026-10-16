"""R37 zero-typing, read-only helper presentation policy.

This is a presentation adapter over observed game frames, not a gameplay
optimizer. It must never turn OCR candidates or detected button locations
into a claimed optimal action.
"""
from __future__ import annotations
from dataclasses import dataclass

SCENES = frozenset(('훈련', '스킬', '시설', '이벤트'))
TRAININGS = frozenset(('스피드', '스태미나', '파워', '근성', '지능', '섬 트레이닝'))


@dataclass(frozen=True)
class HelperView:
    title: str
    explanation: str
    verified_training: bool = False


class StableLowEnergy:
    """Two fresh captures with the same low OCR candidate, never a verified stat."""
    def __init__(self):
        self.previous = None
        self.count = 0

    def reset(self):
        self.previous = None
        self.count = 0

    def observe(self, *, energy: int | None, epoch: int, scene: str | None,
                active: bool) -> bool:
        if (not active or scene != '훈련'
                or type(energy) is not int or not 0 <= energy <= 25
                or type(epoch) is not int or epoch < 0):
            self.reset()
            return False
        sample = (epoch, energy)
        self.count = self.count+1 if sample == self.previous else 1
        self.previous = sample
        return self.count >= 2


def view_from_frame(*, scene: str | None, active: bool,
                    value_count: int = 0, detected_buttons: tuple[str, ...] = (),
                    reviewed_hint: str | None = None,
                    low_energy_candidate: bool = False) -> HelperView:
    """Show helpful, truthful state without requiring user data entry.

    'reviewed_hint' must come from a separately verified R28 handoff, matching
    the current game window, scene and stable button detection; no direct OCR
    or template hit is by itself a recommendation.
    """
    if type(active) is not bool:
        raise ValueError('게임 창 활성 상태가 올바르지 않습니다.')
    if type(value_count) is not int or not 0 <= value_count <= 9:
        raise ValueError('인식 값의 수가 올바르지 않습니다.')
    if scene not in SCENES and scene is not None:
        raise ValueError('알 수 없는 화면 종류입니다.')
    if not isinstance(detected_buttons, tuple) or any(x not in TRAININGS for x in detected_buttons):
        raise ValueError('검출된 버튼 이름이 올바르지 않습니다.')
    if reviewed_hint is not None and reviewed_hint not in TRAININGS:
        raise ValueError('검수하지 않은 추천 이름입니다.')
    if type(low_energy_candidate) is not bool:
        raise ValueError('체력 후보 확인 상태가 올바르지 않습니다.')
    if not active:
        return HelperView('게임 화면을 확인하는 중', '게임 창이 활성화되면 화면을 자동으로 읽습니다. 입력은 필요 없습니다.')
    if scene is None:
        return HelperView('화면 인식 중 · 추천 대기',
                          '현재 게임 장면을 아직 확실하게 구분하지 못했습니다. 확인되지 않은 행동을 추천하지 않습니다.')
    if scene == '훈련':
        if low_energy_candidate:
            return HelperView('체력 낮음 · 휴식·외출 검토',
                              '두 화면에서 체력 25 이하 숫자 후보가 반복 인식됐습니다. '
                              'OCR은 실제 수치로 검증되지 않았으므로 게임에서 체력과 선택지를 보고 결정하세요.')
        if reviewed_hint is not None:
            if reviewed_hint not in detected_buttons or detected_buttons.count(reviewed_hint) != 1:
                return HelperView('훈련 추천 보류', '이전 검수 추천과 현재 버튼이 일치하지 않습니다.')
            return HelperView(reviewed_hint + ' 훈련 추천',
                              '현재 화면에 일치하는 검수된 후보입니다. 클릭은 게임에서 직접 하세요. '
                              '휴식·외출·레이스까지 비교한 최적 행동은 아닙니다.', True)
        if detected_buttons:
            message = '훈련 버튼은 감지했지만 상승량·체력 소모·다른 행동의 유효한 비교가 아직 부족합니다.'
        else:
            message = '훈련 버튼 위치와 상승량을 검증하는 중입니다.'
        if value_count:
            message += ' 표시된 수치는 자동 인식 후보이며 정답으로 확정하지 않았습니다.'
        return HelperView('훈련 비교 준비 중', message + ' 키보드로 수치를 입력할 필요는 없습니다.')
    labels = {'이벤트':'이벤트 선택지', '스킬':'스킬 선택', '시설':'시설 강화'}
    return HelperView(labels[scene]+' 감지 · 추천 보류',
                      '화면 유형만 확인됐습니다. 각 선택의 효과가 검증되지 않아 임의로 번호를 추천하지 않습니다.')


def paused_view() -> HelperView:
    return HelperView('헬퍼 일시 정지', '다시 시작하면 게임 화면을 자동으로 확인합니다.')
