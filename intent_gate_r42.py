"""Offline-only action-intent protocol; deliberately never sends game clicks."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json

ALLOWED_SCENES = frozenset(('훈련', '시설', '이벤트', '레이스', '스킬', '외출', '휴식', '육성완료', 'TP회복'))
ORIGINS = frozenset(('synthetic_test', 'reviewed_game_screenshot', 'reviewed_game_video'))


@dataclass(frozen=True)
class ObservedFrame:
    window_id: int
    run_id: str
    turn_id: str
    scene: str
    frame_number: int
    action_labels: tuple[str, ...]
    source: str
    active: bool
    reviewed: bool

    def validate(self):
        if (type(self.window_id) is not int or self.window_id < 1 or
                type(self.frame_number) is not int or self.frame_number < 1):
            raise ValueError('프레임/게임 창 식별자 오류')
        if (self.scene not in ALLOWED_SCENES or self.source not in ORIGINS or
                type(self.active) is not bool or type(self.reviewed) is not bool):
            raise ValueError('프레임 출처/장면/활성 상태 오류')
        if any(not isinstance(s, str) or not (1 <= len(s) <= 128)
               for s in (self.run_id, self.turn_id)):
            raise ValueError('육성/턴 ID 오류')
        if (not isinstance(self.action_labels, tuple) or
                len(self.action_labels) > 30 or
                any(not isinstance(x, str) or not (1 <= len(x) <= 128)
                    for x in self.action_labels) or
                len(set(self.action_labels)) != len(self.action_labels)):
            raise ValueError('동작 식별자 중복/형식 오류')
        return self

    @property
    def identity(self):
        self.validate()
        return (self.window_id, self.run_id, self.turn_id,
                self.scene, self.action_labels, self.source)


@dataclass(frozen=True)
class ActionIntent:
    ticket: str
    action: str
    identity: tuple
    frame_number: int
    preview_only: bool = True


class IntentGate:
    """Two stable observations; require a distinct reviewed post-action scene/turn.

    No input backend is provided. Even a trusted frame produces only a proposal.
    """
    def __init__(self):
        self.last_frame = 0
        self.last_identity = None
        self.stable_count = 0
        self.pending: ActionIntent | None = None
        self.completed = set()

    def propose(self, frame: ObservedFrame, action: str):
        frame.validate()
        if frame.frame_number <= self.last_frame:
            return None, '과거/중복 프레임 무시'
        self.last_frame = frame.frame_number
        if frame.identity == self.last_identity:
            self.stable_count += 1
        else:
            self.last_identity = frame.identity
            self.stable_count = 1
        if self.pending is not None:
            return None, '화면 전환/실제 결과 확인 대기'
        if not frame.active or not frame.reviewed:
            return None, '활성 게임/검수된 화면이 아닙니다.'
        if frame.source not in ('reviewed_game_screenshot', 'reviewed_game_video'):
            return None, '합성 화면에서는 실제 행동 후보를 발행하지 않습니다.'
        if action not in frame.action_labels:
            return None, '현재 화면에 확인된 행동이 아닙니다.'
        if self.stable_count < 2:
            return None, '동일한 장면/선택지의 두 번째 화면 확인 대기'
        key = (frame.run_id, frame.turn_id, frame.scene, action)
        if key in self.completed:
            return None, '이미 처리된 턴/동작입니다.'
        raw = json.dumps((frame.identity, action, frame.frame_number), ensure_ascii=False)
        ticket = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self.pending = ActionIntent(ticket, action, frame.identity, frame.frame_number)
        return self.pending, '읽기 전용 행동 제안 · 자동 클릭 미연결'

    def acknowledge(self, after: ObservedFrame, ticket: str):
        after.validate()
        if self.pending is None or ticket != self.pending.ticket:
            return False
        if after.frame_number <= max(self.pending.frame_number, self.last_frame):
            return False
        previous = self.pending.identity
        if (after.source not in ('reviewed_game_screenshot', 'reviewed_game_video') or
                not after.active or not after.reviewed or
                after.window_id != previous[0] or after.run_id != previous[1] or
                (after.turn_id == previous[2] and after.scene == previous[3])):
            return False
        self.completed.add((previous[1], previous[2], previous[3], self.pending.action))
        self.pending = None
        self.last_identity = after.identity
        self.last_frame = after.frame_number
        self.stable_count = 1
        return True

    def stop(self):
        """Discard pending intent without treating it as a confirmed game action."""
        self.pending = None
        self.stable_count = 0
        self.last_identity = None


def send_game_input(*args, **kwargs):
    raise RuntimeError('게임 입력 어댑터는 검증되지 않아 차단되어 있습니다.')
