# Uma Trainer KR R36 — Windows R34/R35 GUI 자동 검증 준비

작성: 2026-10-16 / 대상: 0.31.2 (R34 조건 검토 + R35 현재 턴 행동 비교)

## 왜 필요한가

이전 R31.1 Windows EXE의 자체검사·시작 import 검사는 성공했지만 실제 앱의 모든 탭이 생성되는지 또는 버튼 클릭 경로가 정상인지 테스트하지 못했다. 사용자가 한국 서버 게임을 켤 수 없는 상태이므로, **실제 Windows CI의 Tk 창을 생성한 뒤 합성 턴으로 현재 UI의 연결을 검사**한다.

## R36에서 자동 검사하는 작업

Windows Actions의 `windows_smoke_r31.ps1`가 기존 EXE 4종 자체검사, 시작 import 검사, Companion 게임 없는 상태 진단을 그대로 실행하고, 추가로 `UmaTrainerKR.exe --gui-smoke-report <report.json>`을 실행한다. 이를 실제 설치된 EXE 검사 모드에도 적용한다.

실제 GUI 진단에는 다음이 모두 필요하다.

1. 임시 `LOCALAPPDATA` 아래에서 `UmaApp` 상세 창을 생성하고 R6·R34 패널이 실제 존재해야 한다.
2. 실제 게임 대신 명확히 **합성된** 무인도 턴(섬 티켓 1장, 우정 시설 3곳)만 사용해 R34 조건 검토를 실행한다.
3. R6에서 나머지 선택지를 명시적으로 불가 처리하고, 섬 트레이닝·휴식 2개 행동을 검수한다.
4. R35에서 동일한 2개 행동을 가져와 UI에 표시하는지 확인하고, 별도의 승률·최적 행동이나 ML 라벨이 생기지 않는지 검사한다.
5. R34 우정 시설 수를 일부러 다르게 수정했을 때 이전 화면을 무효화하고 불일치 경고를 출력해야 한다.
6. 성공 시 개인정보나 화면 자료를 포함하지 않는 JSON `uma_r36_windows_gui_synthetic_smoke_v1`을 저장한다.
7. 패키징 검증기는 보고서가 없거나 필수 조건이 하나라도 거짓이면 ZIP 생성/업로드를 차단한다.

검증 루틴: `gui_smoke_r36.py`. **게임에 클릭·입력하지 않는다.** 테스트용 SQLite는 임시 폴더만 이용한다. 원본 개인 기록/설정을 이동하거나 지우지 않는다.

## 테스트 구조

- `tests/test_island_context_r34.py`: R34 조건 누락·첫 티켓·필수 레이스/외출·시설/성장률 등 합성 단위 테스트
- `tests/test_island_choices_r35.py`: R35 R6 지문 일치·미검수 항목 거절·행동 비교 및 입력 변경 차단
- `tests/test_gui_smoke_r36.py`: CLI 거절 조건, 임시 로컬 데이터 격리, 리포트 보존 및 Windows 워크플로 연결
- `tests/test_portable_first_r31.py`, `tests/test_package_selftest_r25.py`: GUI 리포트 없거나 조작 시 패키지 거절
- Windows 실 실행: `UmaTrainerKR.exe --gui-smoke-report` (Actions에서 PS 유한 시간 실행)

## 버전·배포·제약

- 버전은 **0.31.2**, Windows 검증 아티팩트 이름은 `UmaTrainerKR-R36-Windows-Verified`로 구분한다. 압축 이름: `UmaTrainerKR-Portable-v0.31.2.zip`.
- 자동 CI 트리거 없음. `.github/workflows/windows-exe.yml`은 **수동 workflow_dispatch**만 가능하다.
- `publish_release=false`, `build_installer=false`가 기본. GitHub Release/배포는 별도로 승인된 경우만 한다.
- 기존 성공한 **R31.1** ZIP과 설치 폴더는 수정·삭제하지 않는다.
- 실제 게임 없이 GUI가 생성되는지와 합성 선택지가 제대로 전달되는지만 검사한다. **실제 한국 서버 화면 인식, 자동 스킬 선택, 실게임 최적 육성, ML 고점 모델 학습을 검증하는 작업이 아니다.**
- 이 문서와 소스의 반영만으로 테스트 성공이라 말하지 않는다. Windows Actions 실행 결과를 확인하고 정상인 경우에만 사용자용 ZIP을 추천한다.

## 사용자가 빌드를 실행할 수 있는 시점

현재 연결된 GitHub 기능은 워크플로 실행 이력/로그 조회를 지원하지만 새로운 workflow_dispatch 실행 기능을 제공하지 않는다. 따라서 새 CI 실행은 GitHub의 Actions > Build Windows portable > Run workflow > main, `publish_release=false` 및 `build_installer=false`로 단 한 번 실행해야 한다. 실행 후 채팅에서 결과·아티팩트 확인은 가능하다.

검사 실패 시 GitHub Actions의 해당 단계에서 중단하고 **실패한 실행파일을 정상 ZIP으로 배포하지 않는다**. 먼저 로그에서 원인을 확인하여 한꺼번에 수정한다.
