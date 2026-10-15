"""Create *local* review frames from a video file the reviewer is allowed to use.

No YouTube downloading, uploading, or redistributing videos. Requires ffmpeg on PATH.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import shutil
import subprocess
try:
    from annotation_core import RESEARCH_DIR
except ImportError:
    from research.review_tools.annotation_core import RESEARCH_DIR


def read_chapters(chapter_file: Path, source_id: str):
    with chapter_file.open(encoding='utf-8-sig', newline='') as f:
        return [(int(r['start_second']), r['topic_ko']) for r in csv.DictReader(f)
                if r['source_id'] == source_id]


def sample_local_video(video: Path, output: Path, seconds: list[int], ffmpeg='ffmpeg'):
    if not video.is_file():
        raise FileNotFoundError(f'로컬 영상 파일이 없습니다: {video}')
    if shutil.which(ffmpeg) is None:
        raise RuntimeError('ffmpeg 실행 파일이 필요합니다. 직접 촬영한 스크린샷도 이용 가능합니다.')
    clean_times = sorted({t for t in seconds if isinstance(t, int) and t >= 0})
    if len(clean_times) > 100:
        raise ValueError('한 번에 100개 이하로 추출하세요. 무제한 자동 프레임 추출을 하지 않습니다.')
    output.mkdir(parents=True, exist_ok=True)
    made = []
    for second in clean_times:
        out = output / f'frame_{second:06d}.png'
        proc = subprocess.run([ffmpeg, '-hide_banner','-loglevel','error','-nostdin',
                               '-y','-ss',str(second),'-i',str(video),'-frames:v','1',
                               str(out)], capture_output=True, text=True, timeout=40)
        if proc.returncode != 0 or not out.is_file() or not out.stat().st_size:
            raise RuntimeError(f'{second}초 프레임 추출 실패: {proc.stderr[-500:]}')
        made.append(out)
    return made


def main():
    p = argparse.ArgumentParser(description='허가된 로컬 영상에서 검수 프레임만 추출합니다.')
    p.add_argument('--video', type=Path, required=True, help='로컬에 있는 영상 파일')
    p.add_argument('--source-id', required=True, help='예: S010')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--before', type=int, default=0, help='챕터 시작점 이전 n초')
    p.add_argument('--after', type=int, default=2, help='챕터 시작점 이후 n초')
    p.add_argument('--at', nargs='*', type=int, default=[], help='챕터 없어도 지정 가능한 영상 시점(초)')
    p.add_argument('--start', type=int, help='고정 간격 샘플링 시작 초')
    p.add_argument('--end', type=int, help='고정 간격 샘플링 끝 초')
    p.add_argument('--every', type=int, help='시작~끝을 n초 간격으로 추출(최대 100장)')
    a = p.parse_args()
    if not (0 <= a.before <= 60 and 0 <= a.after <= 60):
        p.error('before/after는 0~60초')
    f = RESEARCH_DIR / 'video_chapters.csv'
    chapters = read_chapters(f, a.source_id)
    times = {max(0, sec + offset) for sec,_ in chapters for offset in (-a.before,0,a.after)}
    times.update(a.at)
    if a.every is not None or a.start is not None or a.end is not None:
        if None in (a.start, a.end, a.every) or a.start < 0 or a.end < a.start or a.every < 1:
            p.error('간격 지정 시 --start --end --every 세 값을 모두 정확히 입력하세요.')
        times.update(range(a.start,a.end+1,a.every))
    if not times:
        p.error('챕터가 없습니다. --at 또는 --start/--end/--every로 초를 지정하세요.')
    if len(times) > 100:
        p.error('너무 많은 프레임입니다. 범위를 나누어 100장 이하로 추출하세요.')
    for item in sample_local_video(a.video, a.output, sorted(times)):
        print(item)
    print(f'총 {len(times)}개 추출. 출처 영상 원본/이미지는 배포 ZIP에 포함되지 않습니다.')

if __name__=='__main__':
    main()
