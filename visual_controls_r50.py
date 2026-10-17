"""R50: locally registered Korean-game visual control profiles (not a guessed bot).

Each profile contains TWO distinct user-reviewed patches: a stable scene marker
and the intended button, plus its normalized click point. No whole screenshots
are persisted. A profile is a *UI calibration*, never a claim about TP amount,
skill affordability, outcome, character, or turn correctness.

The visual matching result alone is NOT an authorization to click. R49's
BatchPlanner must independently verify the live state and requested action.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import base64
import hashlib
import io
import json
import math
import os
import tempfile

from PIL import Image

SCHEMA="uma_r50_visual_control_v1"
SCENES=frozenset(("setup","tp","skill","result","repeat"))
MAX_PROFILES=80
MAX_SIZE=3_000_000
ANCHOR_LIMIT=.92
CONTROL_LIMIT=.94


def _num(v):
    return type(v) in (int,float) and math.isfinite(v)


def _bbox(box):
    if not isinstance(box, (tuple,list)) or len(box)!=4 or not all(_num(x) for x in box):
        raise ValueError("ROI 좌표 오류")
    x1,y1,x2,y2=box
    if not (0<=x1<x2<=1 and 0<=y1<y2<=1 and (x2-x1)>=.025 and (y2-y1)>=.018):
        raise ValueError("화면 검증 ROI 크기/범위 오류")
    return tuple(float(x) for x in box)


def allowed_action(scene,action):
    if not isinstance(action,str) or len(action)>100 or not action.strip():
        return False
    if any(s in action.casefold() for s in ("premium","jewel","diamond","쥬얼","주얼","유료","결제","현금")):
        return False
    return ((scene=="setup" and action=="start_run")
        or (scene=="tp" and action.startswith("free_tp:") and len(action)>8)
        or (scene=="tp" and action=="start_run")
        or (scene=="skill" and action.startswith("skill:") and len(action)>6)
        or (scene=="result" and action in ("finish_run:good","finish_run:ordinary",
                                             "finish_run:disposed","finish_run:failed"))
        or (scene=="repeat" and action=="repeat_run"))


def _png(image):
    if not isinstance(image,Image.Image) or image.width<10 or image.height<10:
        raise ValueError("영역 템플릿 이미지 없음")
    if image.width*image.height>90000:
        raise ValueError("부분 템플릿 크기 초과")
    buf=io.BytesIO()
    image.convert("RGB").save(buf,format="PNG")
    b=buf.getvalue()
    if len(b)>350000:
        raise ValueError("부분 템플릿 데이터 크기 초과")
    return base64.b64encode(b).decode("ascii")


def _decode(encoded):
    if not isinstance(encoded,str) or len(encoded)>480000:
        raise ValueError("부분 템플릿 인코딩 오류")
    try:
        raw=base64.b64decode(encoded,validate=True)
        with Image.open(io.BytesIO(raw)) as x:
            x.verify()
        with Image.open(io.BytesIO(raw)) as x:
            img=x.convert("RGB")
        if img.width<10 or img.height<10 or img.width*img.height>90000:
            raise ValueError("부분 템플릿 크기 오류")
        return img
    except (OSError,ValueError) as exc:
        raise ValueError("저장된 부분 템플릿 손상") from exc


def crop(image,box):
    b=_bbox(box)
    w,h=image.size
    xy=(round(b[0]*w),round(b[1]*h),round(b[2]*w),round(b[3]*h))
    if xy[2]-xy[0]<10 or xy[3]-xy[1]<10:
        raise ValueError("너무 작은 템플릿 영역")
    return image.crop(xy)


@dataclass(frozen=True)
class ControlProfile:
    stage: str
    action: str
    width: int
    height: int
    scene_box: tuple[float,float,float,float]
    button_box: tuple[float,float,float,float]
    click: tuple[float,float]
    scene_png: str
    button_png: str
    reviewed: bool
    free_only: bool=False
    source: str="user_reviewed_live_kr_screenshot"
    schema: str=SCHEMA
    target_scope: str=""  # skill UI bound to selected round/running style

    def validate(self):
        if self.schema!=SCHEMA or self.stage not in SCENES or not allowed_action(self.stage,self.action):
            raise ValueError("허용되지 않은 화면/조작 이름")
        if (type(self.width) is not int or type(self.height) is not int
                or self.width<300 or self.height<320 or self.width*self.height>24_000_000):
            raise ValueError("게임 화면 크기 오류")
        sx1,sy1,sx2,sy2=_bbox(self.scene_box)
        bx1,by1,bx2,by2=_bbox(self.button_box)
        if max(0,min(sx2,bx2)-max(sx1,bx1))*max(0,min(sy2,by2)-max(sy1,by1))>0:
            raise ValueError("장면/버튼 템플릿 영역이 겹칩니다.")
        if (not isinstance(self.click,(list,tuple)) or len(self.click)!=2
                or not all(_num(x) for x in self.click)
                or not (.05<self.click[0]<.95 and .05<self.click[1]<.95)):
            raise ValueError("게임 버튼 클릭 좌표 오류")
        x1,y1,x2,y2=self.button_box
        if not(x1<=self.click[0]<=x2 and y1<=self.click[1]<=y2):
            raise ValueError("클릭 좌표가 확인된 버튼 내부가 아닙니다.")
        if self.reviewed is not True or self.source!="user_reviewed_live_kr_screenshot":
            raise ValueError("직접 확인한 한국 게임 캡처가 아닙니다.")
        if (not isinstance(self.target_scope,str) or len(self.target_scope)>80
                or (self.stage=="skill" and ":" not in self.target_scope)
                or (self.stage!="skill" and self.target_scope)):
            raise ValueError("스킬 대회/각질 검수 범위 오류")
        if self.action.startswith("free_tp:") and self.free_only is not True:
            raise ValueError("무료 TP만 허용")
        if self.free_only and not self.action.startswith("free_tp:"):
            raise ValueError("무료 TP 검증 대상과 행동이 다릅니다.")
        sc=_decode(self.scene_png);bu=_decode(self.button_png)
        for img,box in ((sc,self.scene_box),(bu,self.button_box)):
            if abs(img.width-round((box[2]-box[0])*self.width))>2 or abs(img.height-round((box[3]-box[1])*self.height))>2:
                raise ValueError("원본 창 크기/이미지 영역이 다릅니다.")
        return self

    @property
    def identity(self):
        return self.stage+"|"+self.action


def register(image,*,stage,action,scene_box,button_box,click,
             reviewed=False,free_only=False,target_scope=""):
    if not isinstance(image,Image.Image):
        raise ValueError("실제 이미지가 아닙니다.")
    from training_preview_r48 import portrait_supported
    if not portrait_supported(image):
        raise ValueError("이 화면 비율은 실험적 캘리브레이션 대상이 아닙니다.")
    sx1,sy1,sx2,sy2=_bbox(scene_box)
    bx1,by1,bx2,by2=_bbox(button_box)
    if max(0,min(sx2,bx2)-max(sx1,bx1))*max(0,min(sy2,by2)-max(sy1,by1))>0:
        raise ValueError("장면 표식과 버튼 영역이 겹치면 오인식될 수 있습니다.")
    return ControlProfile(
        stage,action,image.width,image.height,(sx1,sy1,sx2,sy2),
        (bx1,by1,bx2,by2),tuple(click),
        _png(crop(image,scene_box)),_png(crop(image,button_box)),
        reviewed,free_only,target_scope=target_scope).validate()


def _match_patch(image,box,reference,threshold):
    """Exact place, near-exact frame geometry, modest image compression tolerance."""
    import cv2
    import numpy as np
    actual=crop(image,box).convert("L")
    wanted=_decode(reference).convert("L")
    if actual.size != wanted.size:
        return False,0.
    a=np.asarray(actual,dtype=np.float32)
    b=np.asarray(wanted,dtype=np.float32)
    # Absolute pixel difference avoids false high NCC from flat/blank patches.
    mae=float(np.mean(np.abs(a-b)))/255.
    score=1.-mae
    # Homogeneous patches cannot identify a unique scene/button.
    if float(np.std(b))<10. or float(np.std(a))<8.:
        return False,score
    return score>=threshold,score


@dataclass(frozen=True)
class VisualMatch:
    stage: str
    action: str
    x: float
    y: float
    fingerprint: str
    score: float
    profile_identity: str
    approved_for_click: bool=False


def recognize(image,profile:ControlProfile):
    profile.validate()
    if not isinstance(image,Image.Image) or image.size!=(profile.width,profile.height):
        return None
    scene_ok,scene_score=_match_patch(image,profile.scene_box,profile.scene_png,ANCHOR_LIMIT)
    if not scene_ok:
        return None
    button_ok,button_score=_match_patch(image,profile.button_box,profile.button_png,CONTROL_LIMIT)
    if not button_ok:
        return None
    token=hashlib.sha256(
        (profile.identity+"|"+str(image.size)+"|"+
         str(round(scene_score,3))+"|"+str(round(button_score,3))).encode()
    ).hexdigest()
    return VisualMatch(profile.stage,profile.action,*profile.click,token,
                       min(scene_score,button_score),profile.identity)


def unique_scene(image,profiles):
    """Never resolve ambiguous simultaneous scene labels to an arbitrary action."""
    candidates=[x for p in profiles if (x:=recognize(image,p)) is not None]
    scenes={v.stage for v in candidates}
    if len(scenes)!=1:
        return None, ()
    stage=next(iter(scenes))
    return stage,tuple(candidates)


def load_profiles(path):
    path=Path(path)
    if path.is_symlink():
        raise ValueError("링크로 연결된 조작 설정 거부")
    if not path.exists():
        return ()
    if path.stat().st_size>MAX_SIZE:
        raise ValueError("조작 설정 파일 크기 초과")
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA or not isinstance(raw.get("profiles"),list):
        raise ValueError("조작 설정 버전 오류")
    if len(raw["profiles"])>MAX_PROFILES:
        raise ValueError("조작 설정 수량 초과")
    profiles=tuple(ControlProfile(**{**entry,
              "scene_box":tuple(entry["scene_box"]),
              "button_box":tuple(entry["button_box"]),
              "click":tuple(entry["click"])}).validate() for entry in raw["profiles"])
    if len({p.identity for p in profiles})!=len(profiles):
        raise ValueError("같은 버튼의 설정 중복")
    return profiles


def save_profile(path,profile):
    profile.validate()
    path=Path(path)
    original=load_profiles(path)
    if any(x.identity==profile.identity for x in original) or len(original)>=MAX_PROFILES:
        raise ValueError("같은 버튼 설정을 중복/덮어쓰기 금지 · 검토 후 이전 프로필 별도 백업")
    payload=json.dumps({"schema":SCHEMA,"profiles":[asdict(x) for x in (*original,profile)]},
                       ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(payload.encode("utf-8"))>MAX_SIZE:
        raise ValueError("설정 용량 제한")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".uma_r50_",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path
