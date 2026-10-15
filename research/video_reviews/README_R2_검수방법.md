# R2 — 영상 기반 턴별 실측 연구 도구

이 팩은 일본 서버 무인도(2025-06-30 수정 **이후**) 연구 R1에 **턴별 검수 입력/검증 프로그램**을 추가한 연구용 중간 결과물입니다.

## 포함된 것

- `review_queue.csv`: 먼저 살펴볼 영상 후보 4개와 주의사항. 출처 영상은 포함되지 않음.
- `verified_turns.csv`: 실제 화면에서 확인한 턴만 기록하는 표 (출시 시 **0행**).
- `review_tools/reviewer_ui.py`: 로컬 이미지와 실제 영상 시점·선택을 함께 기록하는 UI.
- `review_tools/frame_sampler.py`: **합법적으로 보유한 로컬 영상**을 ffmpeg로 필요한 시점만 추출하는 스크립트.
- `review_tools/audit_cli.py`: 프레임 유무·원본 변경·선택/결과 기재 여부 검증.
- `review_tools/annotation_core.py`: 필드 검증, 중복 방지, 프레임 SHA-256, 원자적 저장.

## 작업 순서

1. 출처 원본 영상을 브라우저에서 시청하고 패치 이후인지, 챔미/리오히 본육성인지 구별.
2. **영상 소유자에게 허락받았거나 이용 조건상 허용되는 경우에만** 로컬 영상으로 프레임 추출. 또는 직접 화면 캡처를 선택해 기록.
3. 영상이 챔미/리오히 본육성인지, 인자작인지, 평가점 육성인지 먼저 구분합니다. 목적 미확인이면 unknown으로 기록.
4. 개발자 환경에서 `python research/review_tools/reviewer_ui.py` 실행 (일반 사용자 배포 앱이 아닌 **연구용 도구**).
5. 영상 출처 ID, 타임스탬프, 캐릭터, 연도, 스탯, 체력, 티켓, 확인 가능한 행동과 선택 결과 입력.
6. 화면에 없거나 가려진 값은 **공란**; 관찰한 행동만 체크. 이미지가 있어야 저장할 수 있음.
7. `python research/review_tools/audit_cli.py` 실행. 연구 파일은 앱의 판단 가중치에 자동 반영되지 않음.

참고: `python research/review_tools/frame_sampler.py --video 내영상.mp4 --source-id S010 --output 내캡처폴더`
이 기능은 ffmpeg 설치가 선택적으로 필요합니다. 영상 자동 다운로드 기능이 아닙니다.

- 챕터가 없는 영상: `python research/review_tools/frame_sampler.py --video 내영상.mp4 --source-id S011 --output 내캡처폴더 --at 120 240 360`
- 육성 전구간을 일부씩 점검: `python research/review_tools/frame_sampler.py --video 내영상.mp4 --source-id S011 --output 내캡처폴더 --start 0 --end 900 --every 15` (최대 100장 제한)
- **프레임 추출은 UI/장면 선택을 돕는 기능일 뿐 턴별 인식·의사결정의 자동 추출이 아닙니다.**

## 판정 가드레일

- `complete` = 6개 주요 체력/스탯 필드가 확인되고, 비교 선택지 2개 이상 및 선택·결과 이미지가 존재하는 경우. **최적 행동 검증이라는 의미는 아님.**
- `partial` = 일부 정보만 확인됨. 사용하지 않은 선택지의 이득을 추정하지 않음.
- 도축은 영상 제작자의 실제 중단 행위/설명과 혼동 금지. 완주 후 출전 제외, 중도 포기, 실제 경기 패배는 각각 다른 레이블.
- 동일 영상의 인접 턴은 서로 독립적인 ML 표본이 아님. 나중에 모델을 평가할 때 반드시 **영상·육성 단위 분리**가 필요함.
- 한국 서버에서 동일한 수치가 적용되었는지는 별도 검증해야 함.

## 수정 시각 근거 확인

일본 GameWith 무인도 시나리오 전문 페이지에는 2025-06-30 **23:20** 밸런스 조정으로 표기되어 있음. 동일 매체의 범용 밸런스 변경 요약 페이지에는 약 **12:00**으로 적혀 있어 두 페이지가 상충함. R1 자료에는 이 불일치가 기록되어 있고, R2에서 23:20을 더 직접적인 시나리오 기록으로 우선 표시하되 공식 공지/앱 내 변경 시각 재확인 전에는 단정하지 않음.
- https://gamewith.jp/uma-musume/article/show/499493
- https://gamewith.jp/uma-musume/article/show/270350

## 저작권·영상 처리

유튜브 동영상 전체를 재배포하지 않습니다. 검수용 로컬 스크린샷과 원본 영상은 ZIP에 담지 않고, 해시·로컬 경로만 기록합니다. 플랫폼 이용 조건과 권리자의 사용 허락을 지켜야 합니다.

## Windows 연구 담당자용 EXE

GitHub Actions의 수동 `Build Windows EXE + Installer` 작업을 실행하면, **별도 비공개 작업 산출물** `UmaResearchReviewer-Internal`에 `UmaResearchReviewer.exe`를 생성하도록 설정했습니다. 이는 일반 사용자용 설치파일에 자동 포함되거나 Release에 게시되지 않습니다. 실제 Windows 빌드 결과는 아직 확인하지 못했습니다. EXE 버전 기록은 `내 문서/UmaTrainerKR_Research/video_reviews`에 저장됩니다.

- `run_purpose`가 `factor_farming`, `evaluation_score`, `unknown`인 턴은 챔미/리오히 본육성 행동 데이터와 섞어 학습해서는 안 됩니다.
