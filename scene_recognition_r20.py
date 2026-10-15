"""R20 visible-screen classification using two *locally calibrated* UI anchors.

No game process inspection, memory access, Internet, training decisions or automated clicks.
A match proves only a screen *category*, never that a particular skill is present.
The game screen must be confirmed with Korean-client screenshots before public release.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import base64
import io
import json
import os
from typing import Optional

from PIL import Image, ImageChops, ImageStat

SCENES_R20 = ('훈련','스킬','시설','이벤트')
VERSION = 'uma_scene_templates_r20_v1'


class SceneError(ValueError):
    pass


@dataclass(frozen=True)
class Anchor:
    scene: str
    x: float
    y: float
    w: float
    h: float
    image_b64: str
    source_w: int
    source_h: int

    def validate(self):
        if self.scene not in SCENES_R20: raise SceneError('지원하지 않는 화면 종류')
        if (self.source_w < 200 or self.source_h < 200 or self.source_w*self.source_h > 24_000_000):
            raise SceneError('기준 캡처 해상도 오류')
        if not (.01 <= self.x < 0.95 and .01 <= self.y < 0.95 and
                .02 <= self.w <= .30 and .02 <= self.h <= .20 and
                self.x+self.w <= .99 and self.y+self.h <= .99):
            raise SceneError('인식 위치가 화면 바깥이거나 너무 큽니다')
        try:
            data=base64.b64decode(self.image_b64,validate=True)
            if len(data)>100_000: raise SceneError('이미지 조각 크기 초과')
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except (ValueError, OSError, base64.binascii.Error) as e:
            raise SceneError('저장한 기준 이미지가 잘못되었습니다') from e
        return self

    def reference(self):
        data=base64.b64decode(self.image_b64,validate=True)
        with Image.open(io.BytesIO(data)) as im:
            return im.convert('RGB')


def _box(im, x,y,w,h):
    return (round(x*im.width),round(y*im.height),round((x+w)*im.width),round((y+h)*im.height))


def make_anchor(im: Image.Image, scene: str, x: float,y: float,w: float,h: float):
    if scene not in SCENES_R20: raise SceneError('알 수 없는 화면')
    if im.width<200 or im.height<200: raise SceneError('캡처가 너무 작습니다')
    if not (.01<=x and .01<=y and .02<=w<=.30 and .02<=h<=.20 and x+w<=.99 and y+h<=.99):
        raise SceneError('인식 영역이 올바르지 않습니다')
    sub=im.convert('RGB').crop(_box(im,x,y,w,h))
    # A flat/background-only patch cannot identify a game scene.
    st=ImageStat.Stat(sub.convert('L'))
    if st.stddev[0]<14:
        raise SceneError('특징이 부족한 이미지입니다. 문자/고유 버튼이 포함된 영역을 선택하세요.')
    buf=io.BytesIO();sub.save(buf,format='PNG')
    obj=Anchor(scene,x,y,w,h,base64.b64encode(buf.getvalue()).decode('ascii'),im.width,im.height)
    return obj.validate()


def profile_path():
    base=Path(os.getenv('LOCALAPPDATA') or Path.home()/'.local'/'share')
    return base/'UmaTrainerKR'/'r20_scene_anchors.json'


def save_library(path, anchors):
    path=Path(path)
    if len(anchors)>20: raise SceneError('기준 이미지는 최대 20개')
    rows=[]
    for a in anchors:
        a.validate();rows.append(vars(a).copy())
    payload={'schema':VERSION,'evidence':'사용자가 실제 화면에서 선택한 UI 조각, 자동 육성 검증 아님','anchors':rows}
    path.parent.mkdir(parents=True,exist_ok=True)
    p=path.with_suffix(path.suffix+'.tmp')
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    p.replace(path)


def load_library(path):
    path=Path(path)
    if not path.exists():return []
    raw=path.read_text(encoding='utf8')
    if len(raw)>2_000_000:raise SceneError('데이터 파일이 비정상적으로 큽니다')
    data=json.loads(raw)
    if data.get('schema')!=VERSION or not isinstance(data.get('anchors'),list) or len(data['anchors'])>20:
        raise SceneError('R20 기준 이미지 파일 형식 오류')
    return [Anchor(**row).validate() for row in data['anchors']]


def _similarity(reference, crop):
    if crop.size!=reference.size:crop=crop.resize(reference.size,Image.Resampling.BILINEAR)
    delta=ImageChops.difference(reference,crop)
    mean=ImageStat.Stat(delta).mean
    return 1.0-sum(mean)/(len(mean)*255)


def anchor_match(img, anchor, shift=0.014, step=0.007):
    """Best of 5x5 local placements. Resolves small camera/window positional changes.

    This is NOT universal object detection: templates must be user-calibrated from
    the same PC-client visual language; resolution aspect ratio must be similar.
    """
    anchor.validate()
    if abs(img.width/img.height - anchor.source_w/anchor.source_h) > .035:
        return 0.0
    ref=anchor.reference()
    screen=img.convert('RGB')
    dx=[-shift,-step,0,step,shift]
    scores=[]
    for ox in dx:
        for oy in dx:
            x=anchor.x+ox;y=anchor.y+oy
            if x<0 or y<0 or x+anchor.w>1 or y+anchor.h>1: continue
            scores.append(_similarity(ref,screen.crop(_box(screen,x,y,anchor.w,anchor.h))))
    return max(scores,default=0.0)


@dataclass(frozen=True)
class SceneGuess:
    scene: Optional[str]
    confidence: float
    reason: str


def detect_scene(img, anchors, threshold=.91, margin=.055):
    """Requires at least two independently chosen anchors per scene."""
    grouped={s:[] for s in SCENES_R20}
    for a in anchors:
        grouped[a.scene].append(a)
    scores=[]
    for scene, parts in grouped.items():
        if len(parts)<2: continue
        matches=sorted((anchor_match(img,a) for a in parts),reverse=True)
        # Two separate anchors must both match; an additional weak anchor cannot overrule.
        score=min(matches[:2])
        scores.append((score,scene))
    if not scores:
        return SceneGuess(None,0.0,'장면별 고유 영역 2개 등록 필요')
    scores.sort(reverse=True)
    best,scene=scores[0]
    next_best=scores[1][0] if len(scores)>1 else 0
    if best<threshold:
        return SceneGuess(None,round(best,3),'화면 특징 불일치 · 추천 보류')
    if best-next_best<margin:
        return SceneGuess(None,round(best,3),'서로 다른 화면의 특징이 유사해 장면 불확실')
    return SceneGuess(scene,round(best,3),'화면 특징 2개 일치 · 반복 확인 필요')


class StableScene:
    """Never retain a previous scene after a conflicting/unknown observation."""
    def __init__(self,frames=2,threshold=.91,margin=.055):
        self.frames=max(2,int(frames))
        self.threshold=threshold
        self.margin=margin
        self.pending=None
        self.count=0
        self.confirmed=None

    def reset(self):
        self.pending=self.confirmed=None;self.count=0

    def observe(self,image,anchors):
        guess=detect_scene(image,anchors,self.threshold,self.margin)
        if guess.scene is None:
            self.reset()
            return guess
        if guess.scene!=self.pending:
            self.pending=guess.scene;self.count=1;self.confirmed=None
        else:
            self.count+=1
            if self.count>=self.frames:self.confirmed=guess.scene
        if self.confirmed is None:
            return SceneGuess(None,guess.confidence,'화면 일치 재확인 중')
        return SceneGuess(self.confirmed,guess.confidence,'동일 장면 연속 확인됨')


def remap_marked_locations(marks, scene, width, height, anchors):
    """Re-use one-time calibrated R19 positions across proportional window sizes.

    Allowed ONLY after R20 independently established the same screen scene. An
    aspect ratio change can rearrange UI controls and must not be inferred.
    """
    if scene not in SCENES_R20 or width < 200 or height < 200:return []
    scene_anchors=[a for a in anchors if a.scene==scene]
    if len(scene_anchors)<2:return []
    allowed=[]
    for m in marks:
        if m.scene!=scene:continue
        if abs(m.width/m.height-width/height)>.035:continue
        allowed.append(type(m)(m.scene,m.name,m.x,m.y,width,height))
    return allowed
