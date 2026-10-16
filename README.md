# Uma Trainer KR — R31 Portable-first

한국 우마무스메 PC 육성 보조 도구 연구·개발 프로젝트.

## 설치 없이 사용하기

GitHub **Actions → Build Windows portable (installer optional, manual only)**에서 Windows 수동 빌드가 성공하면 `UmaTrainerKR-R31-Windows-Verified`라는 Artifacts를 받을 수 있습니다. 내부 `portable/UmaTrainerKR-Portable-v0.31.1.zip`을 압축 해제한 뒤 `UmaTrainerKR_Companion.exe`를 실행하세요. **설치 프로그램과 Python 설치가 필요하지 않습니다.** 단 OCR용 Tesseract가 별도로 필요할 수 있습니다.

### 이후 버전 업데이트

R31 포터블 도우미는 시작 시와 실행 중 매일 공식 GitHub Release의 안정 버전을 확인합니다. 새 버전이 있으면 **사용자가 동의한 경우에만** 내려받고 SHA-256을 검증하여 새 버전 폴더에 설치합니다. 기존 버전은 삭제하지 않으며 설정/육성 기록은 `%LOCALAPPDATA%\UmaTrainerKR`에 보존됩니다.

GitHub 코드가 변경되었다고 자동으로 실행파일이 업데이트되는 것은 **아닙니다**. 새 **GitHub Release**가 Windows 테스트 후 실제로 게시되어야 새 버전을 받을 수 있습니다. Releases 게시 작업도 수동이고, `publish_release=false`가 기본입니다.

소스 실행: `python -m pip install -r requirements.txt` 이후 `python companion.py`. 전체 테스트: `python -m unittest discover -s tests -q`.

구체적인 사용·릴리스 절차 및 4개월 주기 운영 방침은 [R30 포터블 업데이트 안내](docs/R30_포터블업데이트_사용방법.md)를 확인하세요.

### 기능/검증 범위

- 지원 개발 중: 게임 옆 패널, 훈련 스크린샷 인식 및 검수, 게임 위 추천 표시(Windows 한국 서버 실검증 전).
- R29: 화면 캡처 자료를 **로컬**에서 관리/내보내기. 자동 전송 없음.
- R30: 포터블 버전 조회·검증·별도 폴더 설치·선택적 버전 전환.
- 자동 클릭·완전 자동 육성/실제 게임 기반 ML 학습은 구현되지 않았음.

게임 화면 감지와 OCR 정확도는 실제 한국 서버 환경 테스트 전입니다.

### R31 — 포터블 우선 빌드 변경

수동 `Run workflow`에서 기본값 `build_installer=false`, `publish_release=false`로 실행하면 **Windows EXE 4종·실행 자체검사·포터블 ZIP·SHA256 검증**에 집중합니다. 기존 설치 프로그램 생성/설치/제거 검사는 `build_installer=true`를 명시한 경우에만 실행합니다. 소스 테스트 및 4개 실제 EXE 자체검사는 어떤 옵션에서도 생략되지 않습니다. `publish_release=true`는 검증 완료 시에만 공개 릴리스를 생성하므로 첫 실행은 `false`를 권장합니다.

R31.1의 Windows Actions EXE 자체검사와 시작 모듈 검사는 통과했습니다. 사용자는 Companion GUI가 열리는 것까지 확인했으나, 한국 게임 화면과의 연동/인식 정확도는 여전히 미검증입니다.

### R31 Windows 장시간 대기 방지 패치

기존 Windows 빌드 #2의 EXE 자체검사 구간에 시간제한 없는 `Start-Process -Wait`가 있었다. 이제 `scripts/windows_smoke_r31.ps1`가 개별 EXE·첫 실행 진단에 최대 90초를 적용하고, 설치형 사용 시 설치/제거에도 시간제한을 적용한다. 실패하면 어느 프로그램에서 멈췄는지 표시하고 릴리스 생성은 차단한다. 기존 실행 중인 빌드에는 이 수정이 적용되지 않으므로 **새 Run workflow**로 검사해야 한다. [진단 기록](docs/R31_Windows_빌드_장시간_대기_진단.md)

### R32 오프라인 연구 보강

게임 실행이 불가능한 동안에는 실제 학습 라벨을 꾸며 넣지 않고, 일본 2025-06-30 패치 후 근거·학습 데이터 구조·검증 안전장치를 보완합니다. [오프라인 연구/검증 계획](docs/R32_오프라인_학습_및_검증_계획.md)을 참고하세요. 데이터 검증 자동 테스트는 기존 전체 유닛 테스트에 포함됩니다.

### R33 일본 무인도 고점 육성 조사 (연구 전용)

영상 설명·제3자 전사 요약·일본 사용자 육성 수기를 조건별로 비교했습니다. **실제 영상 프레임/턴 검증 0건 및 ML 학습 0건**이며 추천 점수를 변경하지 않았습니다. [R33 출처·가설·충돌 분석](docs/R33_JP_무인도_고점육성_비교연구.md) / [구조 검증 데이터](research/r33_high_score_island/study_pack.json).

### R34 무인도 조건별 검토 (추가 화면)

상세 설정 프로그램의 **R34 무인도 조건** 탭에서 직접 확인한 인연·티켓·레이스·외출·성장률·시설 상태로 장기 조건을 점검합니다. [사용 안내](docs/R34_무인도_조건별육성_검토.md). **기존 R6 점수/ML/자동 조작을 변경하지 않으며**, 현재 0.31.1 EXE에는 아직 포함되지 않은 새 소스 기능입니다. 실제 Windows GUI 검증 후 별도 빌드가 필요합니다.
