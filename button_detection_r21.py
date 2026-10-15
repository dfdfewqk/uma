"""R21 optical training-button localization (no mouse actions).

A training button is recognized ONLY using a locally calibrated image patch.
The patch is searched in a bounded ROI with multi-scale normalized correlation.
Rejects uncertain/duplicate matches and waits for two consecutive frames.
Never asserts that a detected icon is currently the best action to choose.

No screenshots or patterns are transmitted anywhere. Real KR game accuracy
is unknown until screenshots are independently inspected and tested.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import base64
import hashlib
import io
import json
import os

from PIL import Image, ImageStat

SCENE = '훈련'
LABELS = ('스피드', '스태미나', '파워', '근성', '지능', '섬 트레이닝')
SCHEMA = 'uma_r21_training_ui_v1'


class DetectionError(ValueError):
    pass


class DetectorUnavailable(RuntimeError):
    pass


def _cv_modules():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError as exc:
        raise DetectorUnavailable('R21 버튼 탐지에는 opencv-python-headless와 numpy가 필요합니다.') from exc


@dataclass(frozen=True)
class ButtonPattern:
    label: str
    x: float
    y: float
    width: int
    height: int
    image_b64: str
    sha256: str
    scenario: str = '무인도'

    def raw(self):
        try:
            content = base64.b64decode(self.image_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise DetectionError('등록 버튼 이미지가 손상됐습니다.') from exc
        if not 120 <= len(content) <= 80_000:
            raise DetectionError('등록 버튼 이미지의 크기가 올바르지 않습니다.')
        if hashlib.sha256(content).hexdigest() != self.sha256:
            raise DetectionError('등록 버튼 이미지의 해시가 일치하지 않습니다.')
        return content

    def image(self):
        try:
            with Image.open(io.BytesIO(self.raw())) as img:
                if img.width<20 or img.height<20 or img.width>180 or img.height>140:
                    raise DetectionError('버튼 이미지 크기를 확인하세요.')
                return img.convert('RGB')
        except OSError as exc:
            raise DetectionError('버튼 이미지 형식이 잘못됐습니다.') from exc

    def validate(self):
        if self.label not in LABELS or self.scenario != '무인도':
            raise DetectionError('시나리오/버튼 명칭이 올바르지 않습니다.')
        if not (200 <= self.width <= 8000 and 200 <= self.height <= 8000 and
                self.width*self.height <= 24_000_000):
            raise DetectionError('원본 화면 크기가 잘못됐습니다.')
        if not (.025 <= self.x <= .975 and .025 <= self.y <= .975):
            raise DetectionError('버튼이 화면 경계에 너무 가깝습니다.')
        if len(self.sha256)!=64:
            raise DetectionError('이미지 해시 오류')
        sample=self.image()
        if ImageStat.Stat(sample.convert('L')).stddev[0] < 12:
            raise DetectionError('등록 버튼의 모양이 너무 단조롭습니다.')
        return self


def make_pattern(image: Image.Image, label: str, x: float, y: float,
                 patch_width=76, patch_height=48):
    """x/y are normalized CENTER from screenshot; user calibrates once.

    Capture at native resolution to avoid interpolating away fine icon details.
    """
    if label not in LABELS: raise DetectionError('훈련 버튼 종류를 확인하세요.')
    if image.width<200 or image.height<200 or image.width*image.height>24_000_000:
        raise DetectionError('캡처 해상도 오류')
    if not (.025<=x<=.975 and .025<=y<=.975):
        raise DetectionError('캡처 중심 좌표 오류')
    w,h=int(patch_width),int(patch_height)
    if not (20<=w<=180 and 20<=h<=140):raise DetectionError('버튼 특징 영역 크기 오류')
    center_x=round(x*image.width);center_y=round(y*image.height)
    left=center_x-w//2;top=center_y-h//2
    if left<0 or top<0 or left+w>image.width or top+h>image.height:
        raise DetectionError('버튼 특징 영역이 화면을 벗어났습니다.')
    patch=image.convert('RGB').crop((left,top,left+w,top+h))
    if ImageStat.Stat(patch.convert('L')).stddev[0]<12:
        raise DetectionError('버튼 아이콘이나 문자가 있는 위치를 선택하세요.')
    out=io.BytesIO();patch.save(out,format='PNG')
    data=out.getvalue()
    return ButtonPattern(label,x,y,image.width,image.height,
                         base64.b64encode(data).decode('ascii'),
                         hashlib.sha256(data).hexdigest()).validate()


def path_default():
    home=Path(os.getenv('LOCALAPPDATA') or Path.home()/'.local'/'share')
    return home/'UmaTrainerKR'/'r21_button_patterns.json'


def save_patterns(path, patterns):
    if len(patterns)>len(LABELS) or len({p.label for p in patterns})!=len(patterns):
        raise DetectionError('한 버튼마다 하나의 특징 이미지로 등록하세요.')
    data={'schema':SCHEMA,'scenario':'무인도','verified_game':False,
          'note':'로컬 사용자가 지정한 버튼 모양; 실제 한국 서버 정확도 미검증',
          'patterns':[asdict(p.validate()) for p in patterns]}
    dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix(dest.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    tmp.replace(dest)


def load_patterns(path):
    dest=Path(path)
    if not dest.exists():return []
    if dest.stat().st_size>700_000:raise DetectionError('버튼 인식 설정 파일이 비정상적으로 큽니다.')
    try:
        data=json.loads(dest.read_text(encoding='utf8'))
        if data.get('schema')!=SCHEMA or data.get('scenario')!='무인도':
            raise DetectionError('버튼 인식 설정 버전 오류')
        rows=data['patterns']
        if not isinstance(rows,list) or len(rows)>len(LABELS):
            raise DetectionError('버튼 등록 개수 오류')
        pats=[ButtonPattern(**row).validate() for row in rows]
        if len({p.label for p in pats})!=len(pats):raise DetectionError('중복 등록')
        return pats
    except (KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,DetectionError):raise
        raise DetectionError('버튼 설정을 읽을 수 없습니다.') from exc


@dataclass(frozen=True)
class ButtonHit:
    label: str
    x: float                 # center in normalized screen coordinates
    y: float
    score: float
    width: int
    height: int


def _array(image):
    cv2,np=_cv_modules()
    return cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)


def find_button(image: Image.Image, pattern: ButtonPattern, threshold=.88,
                uniqueness_margin=.065, radius_x=.14, radius_y=.105):
    """Return one uniquely matched button, otherwise None.

    Search only near its original relative location: for completely rearranged UI,
    recalibration is safer than guessing a position somewhere on the screen.
    """
    cv2,np=_cv_modules()
    pattern.validate()
    if abs(image.width/image.height - pattern.width/pattern.height)>.03:
        return None
    if image.width*image.height>24_000_000:return None
    original=_array(pattern.image())
    whole=_array(image)
    # Search centers inside the allowed radius, not template upper-lefts.
    # Without the extra half-patch margin a second matching button near the
    # right edge of the ROI is clipped and incorrectly passes uniqueness.
    half_w=round(original.shape[1]*image.width/pattern.width*.60)
    half_h=round(original.shape[0]*image.height/pattern.height*.60)
    x0=max(0,round((pattern.x-radius_x)*image.width)-half_w)
    y0=max(0,round((pattern.y-radius_y)*image.height)-half_h)
    x1=min(image.width,round((pattern.x+radius_x)*image.width)+half_w)
    y1=min(image.height,round((pattern.y+radius_y)*image.height)+half_h)
    crop=whole[y0:y1,x0:x1]
    h0,w0=original.shape[:2]
    expected=image.width/pattern.width
    gray_crop=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    possible=[]
    # Relative 10% icon zoom differences while the outer window aspect stays stable.
    for factor in (.90,.95,1.0,1.05,1.10):
        scale=expected*factor
        w=round(w0*scale);h=round(h0*(image.height/pattern.height)*factor)
        if w<18 or h<18 or w>=crop.shape[1] or h>=crop.shape[0]:continue
        temp=cv2.resize(original,(w,h),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
        gray_temp=cv2.cvtColor(temp,cv2.COLOR_BGR2GRAY)
        if float(gray_temp.std())<10:continue
        result=cv2.matchTemplate(gray_crop,gray_temp,cv2.TM_CCOEFF_NORMED)
        # Inspect high candidates, including any repeated visually identical buttons.
        for _ in range(4):
            _,score,_,point=cv2.minMaxLoc(result)
            if score<max(.65,threshold-.12):break
            px,py=point
            candidate=crop[py:py+h,px:px+w]
            color_diff=float(np.abs(candidate.astype(np.float32)-temp.astype(np.float32)).mean())/255
            if color_diff<.15:
                center=((x0+px+w/2)/image.width,(y0+py+h/2)/image.height)
                # Only candidate CENTERS inside the bounded UI search zone.
                if abs(center[0]-pattern.x)<=radius_x and abs(center[1]-pattern.y)<=radius_y:
                    possible.append((float(score)-color_diff*.16,center,w,h))
            # Non-maximum suppression: suppress this rectangle, not just one pixel.
            pad_x=max(3,w//2);pad_y=max(3,h//2)
            result[max(0,py-pad_y):min(result.shape[0],py+pad_y+1),
                   max(0,px-pad_x):min(result.shape[1],px+pad_x+1)]=-1
    if not possible:return None
    possible.sort(key=lambda z:z[0],reverse=True)
    best=possible[0]
    if best[0]<threshold:return None
    # Distinct, competing locations must not both be accepted.
    for other in possible[1:]:
        delta=((best[1][0]-other[1][0])**2+(best[1][1]-other[1][1])**2)**.5
        if delta>.025 and best[0]-other[0]<uniqueness_margin:
            return None
    x,y=best[1]
    if abs(x-pattern.x)>radius_x or abs(y-pattern.y)>radius_y:return None
    return ButtonHit(pattern.label,x,y,round(best[0],3),best[2],best[3])


class StableButtons:
    """Hold a location only after two successive matching frames; fail closed."""
    def __init__(self,frames=2,max_move=.022):
        self.frames=max(2,int(frames));self.max_move=max_move
        self.pending={}

    def reset(self):self.pending.clear()

    def observe(self,image,patterns,scene):
        if scene!=SCENE or not patterns:
            self.reset();return []
        hits=[h for pat in patterns if (h:=find_button(image,pat)) is not None]
        return self.observe_hits(hits,scene)

    def observe_hits(self,hits,scene):
        """Confirm computer-vision worker results on the UI thread.

        The worker only reads pixels. A stale/ambiguous frame cannot produce a
        visible location, and conflicting labels sharing one place are rejected.
        """
        if scene!=SCENE:
            self.reset();return []
        fresh={h.label:h for h in hits}
        if len(fresh)!=len(hits):
            self.reset();return []
        positions=list(fresh.values())
        for i,a in enumerate(positions):
            for b in positions[i+1:]:
                if ((a.x-b.x)**2+(a.y-b.y)**2)**.5<.022:
                    self.reset();return []
        confirmed=[]
        updated={}
        for label,hit in fresh.items():
            previous=self.pending.get(label)
            if previous is not None:
                old,count=previous
                moved=((old.x-hit.x)**2+(old.y-hit.y)**2)**.5
                count=count+1 if moved<=self.max_move else 1
            else:count=1
            updated[label]=(hit,count)
            if count>=self.frames:confirmed.append(hit)
        self.pending=updated
        return sorted(confirmed,key=lambda h:LABELS.index(h.label))


def recommended_training_marks(hits, context, width, height):
    """Return an on-game mark ONLY for a uniquely located, reviewed R6 top action.

    A visually detected button is not proof that training is optimal.
    Caller must separately ensure the training scene is verified and active.
    """
    from hud_r19 import Mark
    if not context or not context.get('training_checked'):
        return []
    ranking=context.get('training_rankings') or []
    if not ranking or not isinstance(ranking[0],dict):return []
    choice=ranking[0].get('name')
    candidates=[hit for hit in hits if hit.label==choice and hit.score>=.88]
    if len(candidates)!=1:return []
    hit=candidates[0]
    if (width<200 or height<200 or width*height>24_000_000):return []
    return [Mark('훈련',hit.label,hit.x,hit.y,width,height).validate()]
