"""R20 optional on-screen skill-name localization. No guessed skill percentages.

Recognizes *visible* words only; combines Tesseract TSV words by a physical line.
Results are display-only and require an independently reviewed R12 course judgment.
Never places UI markers from cached scroll positions.
"""
from __future__ import annotations
from dataclasses import dataclass
import csv
import hashlib
import io
import re
import subprocess

from PIL import Image, ImageChops, ImageStat


@dataclass(frozen=True)
class SkillHit:
    name: str
    x: int
    y: int
    w: int
    h: int
    confidence: float


def clean(s):
    return re.sub(r'[\s·•・+\-_/\[\]()○◎◯:：]+','',str(s)).casefold()


def skill_hits_from_tsv(tsv: str, expected, min_confidence=75):
    """Never accept a partial ambiguous word; require one unique visible line.

    Short names (2 chars) require higher confidence because accidental overlaps
    are substantially more likely than with longer Korean/Japanese skill names.
    """
    reader=csv.DictReader(io.StringIO(tsv),delimiter='\t')
    lines={}
    for row in reader:
        if row.get('level')!='5':continue
        word=row.get('text','').strip()
        if not word:continue
        try:
            confidence=float(row['conf'])
            if confidence < min_confidence:continue
            x,y,w,h=(int(row[k]) for k in ('left','top','width','height'))
        except (ValueError,KeyError,TypeError):continue
        if x<0 or y<0 or w<=0 or h<=0:continue
        key=tuple(row.get(k,'') for k in ('page_num','block_num','par_num','line_num'))
        lines.setdefault(key,[]).append((word,x,y,w,h,confidence))
    grouped=[]
    for words in lines.values():
        words.sort(key=lambda i:i[1])
        text=clean(' '.join(w[0] for w in words))
        left=min(w[1] for w in words);top=min(w[2] for w in words)
        right=max(w[1]+w[3] for w in words);bottom=max(w[2]+w[4] for w in words)
        conf=min(w[5] for w in words)
        grouped.append((text,left,top,right-left,bottom-top,conf))
    found=[]
    for name in set(expected):
        token=clean(name)
        if len(token)<2:continue
        compatible=[(x,y,w,h,cf) for text,x,y,w,h,cf in grouped
                    if (token==text or (len(token)>=4 and token in text))
                    and (len(token)>2 or cf>=90)]
        if len(compatible)!=1:continue  # more than one instance -> no guess
        x,y,w,h,cf=compatible[0]
        found.append(SkillHit(name,x,y,w,h,round(cf,2)))
    return sorted(found,key=lambda h:h.y)


def run_skill_ocr(image: Image.Image, executable: str, names, timeout=12, region=None):
    if not executable or not names:return []
    offset=(0,0)
    if region is not None:
        box=region.pixel_box(image)
        if box is None:return []
        offset=box[:2]
        image=image.crop(box)
    buf=io.BytesIO()
    image.convert('RGB').save(buf,format='PNG')
    try:
        p=subprocess.run([executable,'stdin','stdout','-l','kor+eng','--psm','11','tsv'],
                         input=buf.getvalue(),capture_output=True,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired):return []
    if p.returncode!=0:return []
    hits=skill_hits_from_tsv(p.stdout.decode('utf8','replace'),names)
    return [SkillHit(h.name,h.x+offset[0],h.y+offset[1],h.w,h.h,h.confidence) for h in hits]


def evidence_crop(img:Image.Image, hit:SkillHit):
    if hit.x<0 or hit.y<0 or hit.w<4 or hit.h<5 or hit.x+hit.w>img.width or hit.y+hit.h>img.height:
        return None
    return img.convert('RGB').crop((hit.x,hit.y,hit.x+hit.w,hit.y+hit.h))


def same_visible_text(old_crop, image, hit, threshold=.965):
    now=evidence_crop(image,hit)
    if old_crop is None or now is None or old_crop.size!=now.size:return False
    means=ImageStat.Stat(ImageChops.difference(old_crop,now)).mean
    return (1-sum(means)/len(means)/255)>=threshold

@dataclass(frozen=True)
class SkillListRegion:
    x:float
    y:float
    w:float
    h:float
    screen_w:int
    screen_h:int
    def validate(self):
        if (self.screen_w<200 or self.screen_h<200 or self.screen_w*self.screen_h>24_000_000
            or not (.01<=self.x<=.85 and .01<=self.y<=.85)
            or not (.15<=self.w<=.95 and .15<=self.h<=.95)
            or self.x+self.w>.99 or self.y+self.h>.99):
            raise ValueError('스킬 목록 영역의 위치나 크기가 올바르지 않습니다.')
        return self
    def pixel_box(self,image):
        self.validate()
        if abs(image.width/image.height-self.screen_w/self.screen_h)>.035:
            return None
        return (round(self.x*image.width),round(self.y*image.height),
                round((self.x+self.w)*image.width),round((self.y+self.h)*image.height))


def skill_region_path():
    import os
    from pathlib import Path
    return Path(os.getenv('LOCALAPPDATA') or Path.home()/'.local'/'share')/'UmaTrainerKR'/'r20_skill_list_region.json'


def save_skill_region(path,region):
    import json
    from pathlib import Path
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp')
    temp.write_text(json.dumps({'schema':'uma_r20_skill_list_1','region':vars(region.validate())},ensure_ascii=False),encoding='utf8')
    temp.replace(p)


def load_skill_region(path):
    import json
    from pathlib import Path
    p=Path(path)
    if not p.exists():return None
    if p.stat().st_size>5000:raise ValueError('스킬 목록 설정 파일이 너무 큽니다.')
    raw=json.loads(p.read_text(encoding='utf8'))
    if raw.get('schema')!='uma_r20_skill_list_1':raise ValueError('스킬 목록 설정 파일 버전 오류')
    return SkillListRegion(**raw['region']).validate()
