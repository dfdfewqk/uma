"""R22: passive live-game training-preview inspection and verified comparison.

No input injection, game clicks, network requests, guessed numerical fields or model training.
The user selects each game's training tab, confirms each visible number, then compares.
The same profile/turn schema can be reused by a future scenario-specific adapter.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
import os
import tempfile
import subprocess
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from PIL import ImageOps
from typing import Optional
from PIL import Image

from uma_core import RunProfile, TurnState, STATS
from screen_r4 import user_dir, tesseract_executable, _recognize_one
from training_r5 import (OptionEvidence, compare_options, EvidenceError,
                         TRAINING_CHOICES, MANDATORY, FIELDS, parse_value)

VERSION = 'uma_r22_live_training_v1'
SCREEN_FIELDS = tuple(f'{stat} 상승' for stat in STATS) + ('스킬 Pt 상승', '실패 확률')
# Negative energy change and friendship/unique scenario effects must be reviewed manually.
REQUIRED = tuple(MANDATORY)
MAX_PIXELS = 24_000_000

class CaptureError(ValueError):
    pass


def screenshot_digest(image: Image.Image) -> str:
    if image.width < 200 or image.height < 100 or image.width*image.height > MAX_PIXELS:
        raise CaptureError('캡처 해상도가 잘못되었습니다.')
    return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


@dataclass(frozen=True)
class FieldBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def validate(self):
        v=(self.x1,self.y1,self.x2,self.y2)
        if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v):
            raise CaptureError('OCR 영역에 올바르지 않은 숫자가 있습니다.')
        if not (0 <= self.x1 < self.x2 <= 1 and 0 <= self.y1 < self.y2 <= 1):
            raise CaptureError('OCR 영역은 이미지 안에 있어야 합니다.')
        if self.x2-self.x1 < .003 or self.y2-self.y1 < .003:
            raise CaptureError('OCR 영역이 너무 작습니다.')
        return self

    def crop(self,image):
        self.validate()
        return image.crop((int(self.x1*image.width),int(self.y1*image.height),
            math.ceil(self.x2*image.width), math.ceil(self.y2*image.height)))


@dataclass
class NumericProfile:
    scenario: str = 'island_post_patch_v1'
    width: int = 0
    height: int = 0
    boxes: dict[str,FieldBox] = field(default_factory=dict)

    def validate(self):
        if self.scenario != 'island_post_patch_v1':
            raise CaptureError('R22 실게임 캡처는 무인도 시나리오만 지원합니다.')
        if not (200 <= self.width <= 8000 and 100 <= self.height <= 8000):
            raise CaptureError('OCR 기준 이미지 크기가 잘못되었습니다.')
        if len(self.boxes)>len(SCREEN_FIELDS):
            raise CaptureError('OCR 영역 개수가 올바르지 않습니다.')
        for name,rect in self.boxes.items():
            if name not in SCREEN_FIELDS:raise CaptureError('지원하지 않는 OCR 영역입니다.')
            rect.validate()
        return self

    def matches(self,image):
        self.validate()
        return abs(image.width/image.height-self.width/self.height)/(self.width/self.height)<.03


def profile_file() -> Path:
    return user_dir()/'r22_training_preview_rois.json'


def save_profile(path:Path, p:NumericProfile):
    p.validate()
    doc={'schema':VERSION,'scenario':p.scenario,'width':p.width,'height':p.height,
         'boxes':{key:asdict(r) for key,r in p.boxes.items()}}
    _atomic_write(path,doc)


def load_profile(path:Path) -> Optional[NumericProfile]:
    path=Path(path)
    if not path.exists():return None
    if path.stat().st_size>50_000:raise CaptureError('OCR 영역 파일이 너무 큽니다.')
    try:
        obj=json.loads(path.read_text(encoding='utf8'))
        if obj['schema']!=VERSION:raise CaptureError('OCR 설정 형식이 다릅니다.')
        return NumericProfile(obj['scenario'],obj['width'],obj['height'],
                              {key:FieldBox(**v) for key,v in obj['boxes'].items()}).validate()
    except (ValueError,TypeError,KeyError) as exc:
        raise CaptureError('OCR 영역 파일이 손상됐습니다.') from exc


def _atomic_write(path, doc):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='r22_',suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            json.dump(doc,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def _ocr_psm13(crop:Image.Image, executable:str):
    """Fallback for isolated digits missed by PSM7. Never force a low-confidence guess."""
    with tempfile.TemporaryDirectory(prefix='uma_r22_fallback_') as temp:
        path=Path(temp)/'crop.png'
        crop.save(path)
        try:
            r=subprocess.run([executable,str(path),'stdout','--psm','13','-l','eng',
                 '-c','tessedit_char_whitelist=0123456789,%','tsv'],
                 capture_output=True,text=True,encoding='utf8',errors='replace',timeout=12,shell=False)
        except (subprocess.TimeoutExpired,OSError):
            return '',None
        if r.returncode:return '',None
        words=[];confs=[]
        for row in csv.DictReader(io.StringIO(r.stdout),delimiter='\t'):
            value=str(row.get('text','')).strip()
            if not value:continue
            try:cf=float(row.get('conf','-1'))
            except (ValueError,TypeError):continue
            if cf>=0:words.append(value);confs.append(cf)
        return ''.join(words), (min(confs) if confs else None)


def ocr_candidates(image:Image.Image,profile:NumericProfile,binary:str='') -> dict:
    """Untrusted suggestions ONLY; confidence and text returned for manual review."""
    if not profile.matches(image):raise CaptureError('기존 ROI와 게임창 화면 비율이 다릅니다. 다시 보정하세요.')
    executable=tesseract_executable(binary)
    if not executable:raise CaptureError('Tesseract 미설치 · OCR 대신 숫자를 직접 입력할 수 있습니다.')
    result={}
    for field,rect in profile.boxes.items():
        crop=rect.crop(image)
        text,conf=_recognize_one(crop,executable)
        try:value=parse_value(field,text,ocr=True)
        except EvidenceError:value=None
        if value is None or conf is None or conf<70:
            # OCR preprocessing may crop away a one-digit glyph. Retest with padding.
            padded=ImageOps.expand(crop,border=18,fill=crop.getpixel((0,0)))
            t2,c2=_recognize_one(padded,executable)
            try:v2=parse_value(field,t2,ocr=True)
            except EvidenceError:v2=None
            if v2 is not None and c2 is not None and c2>=70:
                text,conf,value=t2,c2,v2
            else:
                t3,c3=_ocr_psm13(crop,executable)
                try:v3=parse_value(field,t3,ocr=True)
                except EvidenceError:v3=None
                if v3 is not None and c3 is not None and c3>=70:
                    text,conf,value=t3,c3,v3
        result[field]={'candidate':value if conf is not None and conf>=70 else None,
                       'confidence':conf, 'raw':text,
                       'requires_manual_review':True}
    return result


class TrainingCaptureSession:
    def __init__(self,turn_id:str,window_id:Optional[int]=None):
        self.turn_id=self._valid_turn(turn_id)
        self.window_id=window_id
        self.size=None
        self.frames:dict[str,str]={}
        self.capture_origin:dict[str,str]={}
        self.options:dict[str,OptionEvidence]={}
        self.origin='screen_or_file_reviewed'

    @staticmethod
    def _valid_turn(value:str)->str:
        val=str(value).strip()
        if not val or len(val)>100:raise CaptureError('턴 이름을 1~100자로 입력하세요.')
        return val

    def reset(self,turn_id:str,window_id:Optional[int]=None):
        self.__init__(turn_id,window_id)

    def register_capture(self,choice:str,image:Image.Image,window_id:Optional[int]=None):
        if choice not in TRAINING_CHOICES:raise CaptureError('지원하지 않는 훈련 선택지입니다.')
        if self.window_id is not None and window_id is not None and window_id!=self.window_id:
            raise CaptureError('다른 게임 창의 캡처입니다. 새 턴을 시작하세요.')
        if self.window_id is None and window_id is not None:self.window_id=window_id
        digest=screenshot_digest(image)
        if digest in (value for key,value in self.frames.items() if key!=choice):
            raise CaptureError('같은 화면을 다른 훈련으로 중복 저장할 수 없습니다.')
        size=(image.width,image.height)
        if self.size is not None and (abs(size[0]/size[1]-self.size[0]/self.size[1])>.03):
            raise CaptureError('게임 창 비율이 바뀌었습니다. 새 턴에서 다시 수집하세요.')
        self.size=size
        self.frames[choice]=digest
        self.capture_origin[choice]='live_game' if window_id is not None else 'file'
        # Recapturing the same choice invalidates its previous review.
        self.options.pop(choice,None)
        return digest

    def confirm(self,choice:str,values:dict[str,str],frame_digest:str):
        if self.frames.get(choice)!=frame_digest:
            raise CaptureError('캡처가 바뀌었습니다. 최신 화면을 다시 확인하세요.')
        if choice not in TRAINING_CHOICES:raise CaptureError('훈련 명칭 오류')
        missing=list(REQUIRED)+(['우정 발동 시설 수'] if choice=='섬 트레이닝' else [])
        if any(f not in values or not str(values[f]).strip() for f in missing):
            raise CaptureError('검수 필수값 누락: '+', '.join(f for f in missing if not str(values.get(f,'')).strip()))
        evidence=OptionEvidence(choice)
        for f,v in values.items():
            if str(v).strip():
                try:evidence.confirm(f,str(v),'ocr_reviewed')
                except EvidenceError as exc:raise CaptureError(str(exc)) from exc
        self.options[choice]=evidence
        return evidence

    def compare(self,profile:RunProfile,state:TurnState):
        if self.turn_id != state.turn_label:
            raise CaptureError('현재 턴이 바뀌었습니다. 기록을 초기화하세요.')
        if not 0 <= state.energy <= 100:raise CaptureError('체력을 확인하세요.')
        return compare_options(profile,state,self.options)

    def to_document(self,scenario='island_post_patch_v1'):
        if scenario!='island_post_patch_v1':raise CaptureError('지원하지 않는 시나리오입니다.')
        return {'schema':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),
                'scenario':scenario,'turn':self.turn_id,'window_id':self.window_id,
                'screenshot_size':list(self.size) if self.size else None,
                'frames':self.frames.copy(),
                'capture_origin':self.capture_origin.copy(),
                'reviewed':{k:{'values':v.values.copy(),'confirmed':sorted(v.confirmed)}
                            for k,v in self.options.items()},
                'game_verified':False,'not_training_labels':True,
                'note':'캡처/수동검수 기록. 화면 진위 또는 추천 최적성을 자동 증명하지 않습니다.'}

    def export(self,path:Path):
        _atomic_write(path,self.to_document())
        return Path(path)
