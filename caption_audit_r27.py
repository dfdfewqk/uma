"""R27 caption reader: review queue, NOT trained labels or speaker recognition.

Usage: python caption_audit_r27.py transcript.srt --output report.json
Accepts .srt, .vtt, YouTube's copied timestamps, and plain text.
No video downloading, no music/voice copying, and no unreviewed model training.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

CATEGORIES = {
    'facilities': ('시설','건설','해변','바닷가','시설 레벨','본능','기교'),
    'island_training': ('섬트','섬 트','티켓','우정','합숙'),
    'bond_supports': ('인연','유대','서포트','서폿','카드','편성'),
    'actions': ('휴식','외출','레이스','훈련','스킬','체력','도축'),
}
# Cues only: these do NOT determine who said a line. Automatic subtitles may mix speakers.
DIALOGUE_CUES = ('트레이너님','트레이너 씨','야호','힘내자','부탁해','좋았어','고마워','선생님')
COMMENTARY_CUES = ('추천','효율','초반','후반','이렇게','이유는','선택','건설','티켓','무조건','시설','포인트')
TIME_RE = re.compile(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?')
CUE_RE = re.compile(r'(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})')
YT_RE = re.compile(r'^\[?(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2})\]?\s+[-–:]?\s*(?P<text>.*)$')

def to_seconds(value: str) -> float | None:
    m = TIME_RE.search(value)
    if not m: return None
    hh = int(m.group(1) or 0); mm = int(m.group(2)); ss = int(m.group(3))
    if mm > 59 and m.group(1) is not None or ss > 59: return None
    frac = float('0.' + (m.group(4) or '0'))
    return hh * 3600 + mm * 60 + ss + frac

def _safe_text(text: str) -> str:
    text = re.sub(r'<[^>]*>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_captions(text: str) -> list[dict]:
    if not isinstance(text, str) or not text.strip() or len(text) > 3_000_000:
        raise ValueError('자막이 비어 있거나 허용 용량을 초과합니다.')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    segments = []
    lines = text.split('\n')
    # SRT/VTT: cues carry a time interval, with one or more text lines per cue.
    if '-->' in text:
        index = 0
        while index < len(lines):
            cue = CUE_RE.search(lines[index])
            if not cue:
                index += 1
                continue
            start = to_seconds(cue.group('start')); end = to_seconds(cue.group('end'))
            index += 1
            body = []
            while index < len(lines) and lines[index].strip() and '-->' not in lines[index]:
                body.append(lines[index]); index += 1
            content = _safe_text(' '.join(body))
            if content: segments.append({'start_sec':start,'end_sec':end,'text':content})
        if segments: return segments
    for line in lines:
        raw = line.strip()
        if not raw: continue
        match = YT_RE.match(raw)
        if match:
            content = _safe_text(match.group('text'))
            if content: segments.append({'start_sec':to_seconds(match.group('time')),'end_sec':None,'text':content})
        else:
            content = _safe_text(raw)
            if content and raw not in ('WEBVTT',) and not re.fullmatch(r'\d+',raw):
                segments.append({'start_sec':None,'end_sec':None,'text':content})
    return segments

def audit(text: str, *, video_id: str = 'L7zlNFfm8aY') -> dict:
    segments = parse_captions(text)
    cues = []
    for i, seg in enumerate(segments):
        s = seg['text']; topics = [topic for topic, keys in CATEGORIES.items() if any(k in s for k in keys)]
        dialogue = any(k in s for k in DIALOGUE_CUES)
        commentary = any(k in s for k in COMMENTARY_CUES)
        # Mixed/ambiguous segments are *never* automatically accepted as narration.
        candidate = ('possible_game_dialogue' if dialogue and not commentary else
                     'possible_commentary' if commentary and not dialogue else 'ambiguous')
        attention=[]
        if ('스피드 5' in s or '스피드 다섯' in s):
            attention.append('support_composition_patch_dependency_check')
        if ('무조건' in s or '항상' in s):
            attention.append('absolute_strategy_claim_needs_counterexamples')
        if '섬' in s and ('처음' in s or '첫' in s):
            attention.append('first_ticket_exception_check')
        cues.append({**seg,'index':i,'topics':topics,'speaker_hypothesis':candidate,
                     'speaker_verified':False,'content_verified':False,'training_eligible':False,
                     'required_review':['original_audio_speaker','video_screen_if_numeric','patch_and_context'],
                     'review_flags':attention})
    return {'schema':'uma_r27_caption_review_v1','video_id':video_id,
            'source_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'segment_count':len(cues),'verified_creator_explanations':0,'approved_training_labels':0,
            'review_status':'manual_review_required', 'segments':cues}

def main():
    p=argparse.ArgumentParser(description='유튜브 자동 자막 검수 후보 추출 (학습 자동 승인 안 함)')
    p.add_argument('transcript',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    text=args.transcript.read_text(encoding='utf-8-sig')
    result=audit(text)
    dest=args.output or args.transcript.with_suffix('.audit.json')
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'검수 후보 {result["segment_count"]}건. 해설 검증 0건. 학습 승인 0건. 결과: {dest}')

if __name__ == '__main__': main()
