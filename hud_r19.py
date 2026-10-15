"""R19 presentation mapping: only user-marked locations, verified context, no fake recognition.

A marker is a *position hint*, never a proof that the same skill is currently on screen.
Full game-scene recognition, screen-match OCR and automatic game action are NOT implemented.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path

SCENES = ('훈련', '스킬')
MARKER_KINDS = ('선택 후보', '우선 검토', '조건 일치', '주의', '추천 보류')


@dataclass(frozen=True)
class Mark:
    scene: str
    name: str
    x: float
    y: float
    width: int
    height: int

    def validate(self):
        if self.scene not in SCENES or not self.name or len(self.name)>65:
            raise ValueError('표시할 화면 종류나 항목 이름을 확인하세요.')
        if not 0.02 <= self.x <= 0.98 or not 0.02 <= self.y <= 0.98:
            raise ValueError('화면 바깥 위치는 등록할 수 없습니다.')
        if self.width < 200 or self.height < 200 or self.width*self.height>24_000_000:
            raise ValueError('등록한 게임 해상도가 올바르지 않습니다.')
        return self


def marker_label(mark, context):
    """Only attach a recommendation if the corresponding analysis matches current context.

    Both R6 and R12 can be stale or manually entered. Never infer that the target is
    visibly present from its name and a previously stored position.
    """
    mark.validate()
    if mark.scene=='훈련':
        rankings=context.get('training_rankings') or []
        if context.get('training_checked') and rankings:
            names=[x.get('name') for x in rankings]
            if mark.name in names:
                rank=names.index(mark.name)
                return ('추천 후보' if rank==0 else '비교 후보', f'{mark.name} · R6 입력값 기준 {rank+1}순위')
    if mark.scene=='스킬':
        if context.get('skill_checked'):
            entry=(context.get('skill_advice') or {}).get(mark.name)
            if entry:
                status=entry.get('verdict','추천 보류')
                if '불일치' in status or '비효율' in status:
                    return ('주의', f'{mark.name} · {status}')
                if status.startswith('우선 검토') or status.startswith('조건 일치'):
                    return ('우선 검토', f'{mark.name} · {status}')
                return ('추천 보류', f'{mark.name} · {status}')
    return ('추천 보류', f'{mark.name} · 현재 상황 검수 필요')


def visible_marks(marks, scene, window_size, context):
    """No guesses at different layout/resolution, and never combine scene types."""
    if scene not in SCENES or not isinstance(window_size,(tuple,list)) or len(window_size)!=2:
        return []
    if not context.get('manual_scene_confirmed'):
        return []
    return [(m, *marker_label(m, context)) for m in marks
            if m.scene==scene and (m.width,m.height)==tuple(window_size)]


def default_mark_path():
    home=Path(os.getenv('LOCALAPPDATA') or Path.home()/'.local'/'share')
    return home/'UmaTrainerKR'/'r19_screen_positions.json'


def save_marks(path, marks):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    items=[asdict(m.validate()) for m in marks]
    if len(items)>100:
        raise ValueError('등록 위치는 100개를 넘을 수 없습니다.')
    payload={'schema':'uma_r19_marks_1', 'warning':'수동으로 지정한 화면 위치. 자동 스킬/훈련 인식 증거가 아님', 'marks':items}
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def load_marks(path):
    path=Path(path)
    if not path.exists():return []
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='uma_r19_marks_1' or not isinstance(data.get('marks'),list) or len(data['marks'])>100:
        raise ValueError('수동 위치 데이터 형식이 잘못됐습니다.')
    return [Mark(**item).validate() for item in data['marks']]


def side_summary(context):
    """Friendly, short labels; human-set targets are not official course thresholds."""
    course=context.get('course','대회 코스 미입력') or '대회 코스 미입력'
    style=context.get('style','미설정')
    event=context.get('event','미설정')
    targets=context.get('targets') or {}
    stats=context.get('stats') or {}
    rows=[]
    for key in ('스피드','스태미나','파워','근성','지능'):
        t=targets.get(key)
        c=stats.get(key)
        t=int(t) if isinstance(t,(int,str)) and str(t).isdigit() else None
        c=int(c) if isinstance(c,(int,str)) and str(c).isdigit() else None
        rows.append((key, c, t))
    required=list(context.get('required_skills') or [])
    return {'event':event,'course':course,'style':style,'stats':rows,'required_skills':required[:12]}
