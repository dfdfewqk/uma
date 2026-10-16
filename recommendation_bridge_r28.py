"""R28 read-only, ephemeral transfer of user-reviewed R22 training comparison to Companion.

Explicit user action is required to publish; screenshots are not published. A handoff
is NOT evidence that the training is optimal, nor that the game turn has not changed.
R28 cannot make game clicks. Another scenario needs its own validated adapter.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import tempfile
import uuid
from screen_r4 import user_dir
from companion_core import is_game_capture_size_supported
from training_r5 import TRAINING_CHOICES
from uma_core import STATS

SCHEMA='uma_training_live_hint_r28_v1'
TTL_SECONDS=120

class HandoffError(ValueError):
    pass


def handoff_path():
    return user_dir()/'r28_current_training_hint.json'


def cancel_handoff(path=None):
    file=Path(path) if path is not None else handoff_path()
    file.unlink(missing_ok=True)


def create_handoff(session, report, profile, state, *, window_id, window_size, now=None):
    """Accept only 5 individually reviewed LIVE captures; do not trust loaded screenshots."""
    if not report or report.missing or not report.ranked or report.status.startswith('추천 보류'):
        raise HandoffError('모든 훈련의 수치 검수가 끝난 경우에만 표시할 수 있습니다.')
    if session.turn_id != state.turn_label or not isinstance(state.turn_label,str):
        raise HandoffError('현재 턴이 일치하지 않습니다.')
    if (not isinstance(window_id,int) or window_id<=0 or session.window_id!=window_id):
        raise HandoffError('실제 게임 창에서 캡처한 자료가 필요합니다. 파일 이미지 전용 검수는 화면 위 표시에서 제외합니다.')
    if (not isinstance(window_size,(tuple,list)) or len(window_size)!=2 or
        not all(isinstance(n,int) and not isinstance(n,bool) for n in window_size)):
        raise HandoffError('게임 창 해상도 오류')
    w,h=window_size
    if not is_game_capture_size_supported(w,h) or session.size!=(w,h):
        raise HandoffError('캡처한 게임 창 해상도가 바뀌었습니다.')
    if profile.scenario not in ('island_post_patch_v1',):
        raise HandoffError('등록되지 않은 시나리오는 화면 위 추천을 표시하지 않습니다.')
    required=list(STATS)+(['섬 트레이닝'] if state.island_tickets>0 else [])
    if not set(required).issubset(session.options):
        raise HandoffError('필수 훈련 검수가 누락됐습니다.')
    for name in required:
        if not session.options[name].complete() or not session.frames.get(name):
            raise HandoffError(f'{name} 캡처/검수 누락')
        if getattr(session,'capture_origin',{}).get(name)!='live_game':
            raise HandoffError(f'{name}은 직접 게임 화면으로 캡처하지 않았습니다.')
    if len({session.frames[name] for name in required})!=len(required):
        raise HandoffError('같은 화면이 여러 훈련에 들어 있습니다.')
    top=report.ranked[0]
    if top.name not in TRAINING_CHOICES or top.name not in required:
        raise HandoffError('훈련 외 행동 또는 검수되지 않은 행동은 강조할 수 없습니다.')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise HandoffError('시간대가 필요합니다.')
    now=now.astimezone(timezone.utc)
    obj={
        'schema':SCHEMA, 'id':str(uuid.uuid4()),'issued_at':now.isoformat(),
        'expires_at':(now+timedelta(seconds=TTL_SECONDS)).isoformat(),
        'window_id':window_id,'width':w,'height':h,
        'turn':state.turn_label,'scenario':profile.scenario,
        'event':profile.event,'distance':profile.distance,'style':profile.style,
        'suggestion':top.name,
        'reviewed_options':required,
        'frame_hashes':{name:session.frames[name] for name in required},
        'source':'R22_live_capture_user_reviewed',
        'advice_kind':'TRAINING_ONLY_HEURISTIC',
        'notice':'훈련끼리의 검수된 임시 점수 비교 · 휴식/외출/레이스 미포함 · 자동 클릭 없음',
    }
    validate_handoff(obj,now=now)
    return obj


def validate_handoff(obj,now=None):
    if not isinstance(obj,dict) or obj.get('schema')!=SCHEMA:
        raise HandoffError('R28 전달 자료 형식 오류')
    try:
        uuid.UUID(obj['id'])
        issued=datetime.fromisoformat(obj['issued_at'])
        expires=datetime.fromisoformat(obj['expires_at'])
        now=now or datetime.now(timezone.utc)
        if any(t.tzinfo is None for t in (issued,expires,now)):
            raise ValueError('timezone')
        now=now.astimezone(timezone.utc);issued=issued.astimezone(timezone.utc);expires=expires.astimezone(timezone.utc)
        if not(issued-timedelta(seconds=5)<=now<expires and 0<(expires-issued).total_seconds()<=TTL_SECONDS):
            raise HandoffError('검수 추천의 유효 시간이 지났거나 아직 시작되지 않았습니다.')
        if (not isinstance(obj['window_id'],int) or isinstance(obj['window_id'],bool) or obj['window_id']<=0 or
            not isinstance(obj['width'],int) or not isinstance(obj['height'],int) or
            not is_game_capture_size_supported(obj['width'],obj['height'])):
            raise HandoffError('게임 창 정보 오류')
        if obj['scenario']!='island_post_patch_v1' or obj['source']!='R22_live_capture_user_reviewed':
            raise HandoffError('허용되지 않은 출처 또는 시나리오')
        if not isinstance(obj['reviewed_options'],list) or not isinstance(obj['frame_hashes'],dict):
            raise HandoffError('검수 자료 형식 오류')
        if obj['suggestion'] not in TRAINING_CHOICES or obj['suggestion'] not in obj['reviewed_options']:
            raise HandoffError('추천 훈련 명칭 오류')
        if not set(STATS).issubset(set(obj['reviewed_options'])):
            raise HandoffError('훈련 5종 검수 누락')
        if len(set(obj['reviewed_options']))!=len(obj['reviewed_options']):
            raise HandoffError('검수 목록이 중복됐습니다.')
        frames=obj['frame_hashes']
        if any(not isinstance(frames.get(name),str) or len(frames[name])!=64 or
               any(ch not in '0123456789abcdef' for ch in frames[name]) for name in obj['reviewed_options']):
            raise HandoffError('이미지 증거 해시 오류')
        if len(set(frames.values()))!=len(frames):
            raise HandoffError('중복 캡처')
        if not 1<=len(obj['turn'])<=100:
            raise HandoffError('턴 입력 오류')
        return obj
    except (KeyError,ValueError,TypeError) as exc:
        if isinstance(exc,HandoffError):raise
        raise HandoffError('R28 추천 자료가 손상됐습니다.') from exc


def save_handoff(obj,path=None,now=None):
    path=Path(path) if path is not None else handoff_path()
    validate_handoff(obj,now=now)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='r28_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return path


def load_handoff(path=None,now=None):
    path=Path(path) if path is not None else handoff_path()
    if not path.exists():return None
    if path.stat().st_size>40_000:raise HandoffError('추천 전달 파일 크기 초과')
    try:
        obj=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError) as exc:raise HandoffError('추천 파일을 읽을 수 없습니다.') from exc
    return validate_handoff(obj,now=now)


@dataclass(frozen=True)
class OnScreenHint:
    label: str
    x: float
    y: float
    caption: str


class HintGate:
    """Invalidate permanently when a verified scene leaves training or loses focus.

    The same handoff id cannot be reactivated by returning to training. A NEW,
    explicitly published user review is required. Scene recognition and button
    localization must already have completed their own stable-frame checks.
    """
    def __init__(self):
        self.current_id=None
        self.activated=False
        self.revoked=set()

    def clear(self):
        if self.current_id:self.revoked.add(self.current_id)
        self.current_id=None;self.activated=False

    def observe(self, obj, *, hwnd=None, size=None, scene=None, hits=(), active=False, now=None):
        if obj is None:
            self.clear();return None
        try:validate_handoff(obj,now)
        except HandoffError:
            self.clear();return None
        key=obj['id']
        if key in self.revoked:return None
        if self.current_id!=key:
            if self.current_id:self.revoked.add(self.current_id)
            self.current_id=key;self.activated=False
        matches=(active and hwnd==obj['window_id'] and tuple(size or ())==(obj['width'],obj['height'])
                 and scene=='훈련')
        if not matches:
            if self.activated or (active and hwnd!=obj['window_id']):
                self.revoked.add(key);self.clear()
            return None
        eligible=[h for h in hits if h.label==obj['suggestion'] and .88<=h.score<=1.
                  and h.width>=15 and h.height>=15]
        if len(eligible)!=1:return None
        found=eligible[0]
        if not (.02<found.x<.98 and .02<found.y<.98):return None
        self.activated=True
        return OnScreenHint(obj['suggestion'],found.x,found.y,
                            '사용자 검수 훈련 비교 1순위 · 클릭은 직접')
