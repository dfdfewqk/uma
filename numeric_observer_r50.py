"""R50 strict, double-observed local numeric OCR for user-registered game fields.

A single OCR string is never a verified count or price. Two consecutive
identical samples from a registered ROI are needed; failures reset stability.
No fixed OCR values or screenshots are silently promoted to ML labels.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict
from pathlib import Path
import io
import json
import os
import re
import subprocess
import tempfile

from visual_controls_r50 import SCENES,_bbox

SCHEMA="uma_r50_numeric_roi_v1"
FIELDS=frozenset(("tp","tp_cost","tp_cap","free_item_count",
                 "free_item_recovery","skill_points","skill_price"))
LIMITS={
    "tp":(0,9999),"tp_cost":(1,999),"tp_cap":(1,9999),
    "free_item_count":(0,9999),"free_item_recovery":(1,9999),
    "skill_points":(0,99999),"skill_price":(1,9999)
}


@dataclass(frozen=True)
class NumberROI:
    stage: str
    field: str
    box: tuple[float,float,float,float]
    reviewed: bool
    source: str="user_marked_live_kr_screenshot"

    def validate(self):
        if self.stage not in SCENES or self.field not in FIELDS or not self.reviewed:
            raise ValueError("등록되지 않은 화면/숫자 항목")
        if self.source!="user_marked_live_kr_screenshot":
            raise ValueError("실제 게임에서 검수한 숫자 영역 필요")
        _bbox(self.box)
        if self.stage=="tp" and self.field.startswith("skill"):
            raise ValueError("스킬 수치가 TP 화면에 등록됨")
        if self.stage=="skill" and not self.field.startswith("skill"):
            raise ValueError("TP 수치가 스킬 화면에 등록됨")
        if self.stage not in ("skill","tp"):
            raise ValueError("이 장면에는 숫자 OCR 검수 정책 없음")
        return self

    @property
    def identity(self):
        return (self.stage,self.field)


def load_rois(path):
    path=Path(path)
    if path.is_symlink():
        raise ValueError("숫자 영역 파일 연결 거부")
    if not path.exists():
        return ()
    if path.stat().st_size>25000:
        raise ValueError("숫자 영역 파일 과대")
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA or not isinstance(raw.get("rois"),list):
        raise ValueError("숫자 영역 설정 형식 오류")
    rois=tuple(NumberROI(v["stage"],v["field"],tuple(v["box"]),
                         v["reviewed"],v.get("source","")).validate()
               for v in raw["rois"])
    if len(rois)>len(FIELDS) or len({r.identity for r in rois})!=len(rois):
        raise ValueError("숫자 영역 중복")
    return rois


def save_roi(path,roi):
    roi.validate()
    old=load_rois(path)
    if any(x.identity==roi.identity for x in old):
        raise ValueError("기존 숫자 영역 덮어쓰기는 먼저 백업 필요")
    data={"schema":SCHEMA,"rois":[asdict(x) for x in (*old,roi)]}
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".uma_r50_numbers_",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return path


def read_one_number(image,roi,ocr_binary):
    from visual_controls_r50 import crop
    roi.validate()
    if not ocr_binary:
        return None
    img=crop(image,roi.box).convert("L")
    img=img.resize((img.width*4,img.height*4))
    with tempfile.TemporaryDirectory(prefix="uma_r50_num_") as tmp:
        p=Path(tmp)/"digit.png"
        img.save(p)
        cmd=[str(ocr_binary),str(p),"stdout","--psm","7","-l","eng",
             "-c","tessedit_char_whitelist=0123456789,"]
        try:
            result=subprocess.run(cmd,capture_output=True,timeout=3,
                     text=True,encoding="utf-8",errors="replace",shell=False)
        except (OSError,subprocess.TimeoutExpired):
            return None
    if result.returncode:
        return None
    raw=result.stdout.strip().replace(",","")
    if not re.fullmatch(r"[0-9]{1,5}",raw):
        return None
    n=int(raw)
    low,high=LIMITS[roi.field]
    return n if low<=n<=high else None


class StableNumberReader:
    def __init__(self):
        self.previous={}
        self.confirmed={}

    def reset(self):
        self.previous.clear();self.confirmed.clear()

    def observe(self,stage,image,rois,ocr_binary,window_key):
        if not hasattr(self,"_stage") or self._stage != (stage,window_key,image.size):
            self.reset()
            self._stage=(stage,window_key,image.size)
        for r in rois:
            if r.stage!=stage:
                continue
            observed=read_one_number(image,r,ocr_binary)
            if observed is None:
                self.previous.pop(r.field,None);self.confirmed.pop(r.field,None)
                continue
            last=self.previous.get(r.field)
            if last is not None and last[0]==observed:
                self.previous[r.field]=(observed,last[1]+1)
                self.confirmed[r.field]=observed
            else:
                self.previous[r.field]=(observed,1)
                self.confirmed.pop(r.field,None)
        return dict(self.confirmed)
