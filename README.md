# Uma Trainer KR — R31 Portable-first

한국 우마무스메 PC 육성 보조 도구 연구·개발 프로젝트.

## 설치 없이 사용하기

GitHub **Actions → Build Windows portable (installer optional, manual only)**에서 Windows 수동 빌드가 성공하면 `UmaTrainerKR-R31-Windows-Verified`라는 Artifacts를 받을 수 있습니다. 내부 `portable/UmaTrainerKR-Portable-v0.31.0.zip`을 압축 해제한 뒤 `UmaTrainerKR_Companion.exe`를 실행하세요. **설치 프로그램과 Python 설치가 필요하지 않습니다.** 단 OCR용 Tesseract가 별도로 필요할 수 있습니다.

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

GitHub에 아직 실행 기록이 없는 동안에는 **Windows 실물 실행 여부가 미검증**입니다.
