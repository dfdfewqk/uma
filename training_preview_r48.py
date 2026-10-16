"""R48 passive live-game training preview comparison.

Works from an actual, focused Korean PC game screenshot. The user previews each
of the five training icons in-game; the helper neither clicks nor reads memory.
The portrait geometry was derived from a user-provided 2026-10-16 recording;
other game layouts must not be guessed. OCR values are UNREVIEWED estimates.
An estimate cannot be treated as an R40 verified decision or an ML training label.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import re
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

NAMES = ("스피드", "스태미나", "파워", "근성", "지능")
CENTERS = (.099, .282, .467, .649, .83)
SCHEMA = "uma_r48_portrait_preview_candidate_v1"


@dataclass(frozen=True)
class PreviewReading:
    name: str
    gains: tuple[int, int, int, int, int]
    signature: str
    ocr_candidate: bool = True


@dataclass(frozen=True)
class PreviewState:
    selected: str | None
    collected: int
    total: int
    recommendation: str | None
    explanation: str
    candidates: tuple[tuple[str, float], ...] = ()
    actual_game_verified: bool = False
    optimality_verified: bool = False


def portrait_supported(image: Image.Image) -> bool:
    return bool(image.width >= 300 and image.height >= 520
                and image.width < 700 and .43 <= image.width/image.height <= .62
                and image.width*image.height <= 24_000_000)


def _array(image):
    return np.asarray(image.convert("RGB"))


def selected_training(image: Image.Image) -> str | None:
    """Recognize the gold '결정' ribbon under exactly one of five training icons."""
    if not portrait_supported(image):
        return None
    rgb=_array(image)
    h,w=rgb.shape[:2]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    scores=[]
    for x in CENTERS:
        x0=max(0,round((x-.055)*w))
        x1=min(w,round((x+.055)*w))
        y0=round(h*.854);y1=round(h*.930)
        if x1-x0<15 or y1-y0<15:return None
        roi=hsv[y0:y1,x0:x1]
        yellow=cv2.inRange(roi,(14,130,125),(39,255,255))
        scores.append(float(cv2.countNonZero(yellow))/yellow.size)
    order=sorted(range(5),key=lambda j:scores[j],reverse=True)
    best,second=order[:2]
    if scores[best]<.075 or scores[second]>=max(.05,scores[best]*.37):
        return None
    return NAMES[best]


def _gain_crops(image):
    """Color-gated PLUS gain sprites above the 5 baseline stat panels.

    Missing gold pixels are zero ONLY for an otherwise recognized portrait
    training preview, and the whole frame still remains an OCR candidate.
    """
    rgb=_array(image)
    h,w=rgb.shape[:2]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    crops=[]
    for x in CENTERS:
        x0=max(0,round((x-.105)*w))
        x1=min(w,round((x+.105)*w))
        y0=round(h*.612);y1=round(h*.659)
        roi=rgb[y0:y1,x0:x1]
        colors=hsv[y0:y1,x0:x1]
        gold=cv2.inRange(colors,(7,75,95),(43,255,255))
        pixel_fraction=float(cv2.countNonZero(gold))/gold.size if gold.size else 0
        crops.append((roi,pixel_fraction))
    return crops


def _run_digit_ocr(rgb, binary):
    """Local-only Tesseract; never shell, upload or persist a full game screenshot."""
    if not binary:
        return None
    pic=Image.fromarray(rgb).convert("RGB")
    scale=4
    pic=pic.resize((pic.width*scale,pic.height*scale),Image.Resampling.BICUBIC)
    with tempfile.TemporaryDirectory(prefix="uma_r48_ocr_") as tempdir:
        source=Path(tempdir)/"bonus.png"
        pic.save(source)
        cmd=[str(binary),str(source),"stdout","--psm","7","-l","eng",
             "-c","tessedit_char_whitelist=+0123456789"]
        try:
            done=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                text=True,encoding="utf-8",errors="replace",
                                shell=False,timeout=4)
        except (OSError,subprocess.TimeoutExpired):
            return None
    if done.returncode:
        return None
    matches=re.findall(r"(?:\+)?([0-9]{1,3})",done.stdout.replace(" ",""))
    nums=[int(n) for n in matches if 1<=int(n)<=150]
    return nums[0] if len(nums)==1 else None


def read_training_gains(image, ocr_binary):
    """Return 5 measured gain candidates or None; never invent missing OCR digits."""
    if selected_training(image) is None or not ocr_binary:
        return None
    values=[]
    visible=0
    for rgb, fraction in _gain_crops(image):
        if fraction<.012:
            values.append(0)
            continue
        value=_run_digit_ocr(rgb,ocr_binary)
        if value is None:
            return None
        visible+=1
        values.append(value)
    return tuple(values) if visible else None


def _turn_signature(image):
    # Baseline stat values (unlike their "+" previews) are stable while browsing
    # the same turn; a changed turn, crop/layout or major scene switch resets.
    w,h=image.size
    sample=image.crop((round(w*.03),round(h*.67),
                       round(w*.97),round(h*.73))).convert("L").resize((94,6))
    quantized=np.asarray(sample,dtype=np.uint8)//16
    return hashlib.sha256(quantized.tobytes()).hexdigest()


class PreviewCollector:
    """Keeps evidence only for the same window, size and stat-baseline fingerprint."""
    def __init__(self):
        self.window_key=None
        self.signature=None
        self.pending=None
        self.collected={}
        self.pending_count=0

    def reset(self):
        self.window_key=None
        self.signature=None
        self.pending=None
        self.collected={}
        self.pending_count=0

    def observe(self,image,window_key,ocr_binary):
        if not portrait_supported(image):
            self.reset()
            return PreviewState(None,0,5,None,"이 화면 크기는 아직 미검증 · 세로형 게임 화면으로 확인하세요.")
        selected=selected_training(image)
        if selected is None:
            # One missed animation frame must not misattribute a prior option.
            self.pending=None;self.pending_count=0
            return self._status(None,"훈련 화면의 노란 '결정' 표식을 확인하지 못했습니다.")
        token=(window_key,image.size)
        signature=_turn_signature(image)
        if self.window_key!=token or self.signature!=signature:
            self.reset()
            self.window_key=token
            self.signature=signature
        if not ocr_binary:
            return self._status(selected,"숫자 인식 OCR이 없어 상승량을 읽지 못했습니다. Tesseract 확인 필요.")
        gains=read_training_gains(image,ocr_binary)
        if gains is None:
            self.pending=None;self.pending_count=0
            return self._status(selected,"선택된 훈련의 상승량 OCR이 불확실합니다 · 수치/창 크기를 확인하세요.")
        current=(selected,gains)
        if self.pending==current:
            self.pending_count+=1
        else:
            self.pending=current
            self.pending_count=1
        if self.pending_count>=2:
            self.collected[selected]=PreviewReading(selected,gains,signature)
        return self._status(selected,"같은 턴에서 게임의 훈련 5개를 한 번씩 선택해 미리보기를 확인하세요.")

    def _status(self,selected,note):
        count=len(self.collected)
        if count<5:
            missing="·".join(s for s in NAMES if s not in self.collected)
            return PreviewState(selected,count,5,None,
                f"훈련 미리보기 {count}/5 · 남음: {missing} · {note}")
        ranked=tuple(sorted(
            ((name, float(sum(self.collected[name].gains))) for name in NAMES),
            key=lambda pair:(-pair[1],pair[0])))
        if ranked[0][1]-ranked[1][1] < 3:
            return PreviewState(selected,5,5,None,
                "현재 화면의 상승량이 비슷합니다. 인연·스킬 Pt·체력/실패율 미확인으로 1순위 보류.",
                ranked)
        return PreviewState(selected,5,5,ranked[0][0],
            f"현재 턴의 관측 상승량 합계 기준 임시 1순위. {ranked[0][0]} +{int(ranked[0][1])}, "
            f"다음 +{int(ranked[1][1])}. 인연·우정·스킬 Pt·체력·시설 비용 미포함, 검수 전 추정.",
            ranked)
