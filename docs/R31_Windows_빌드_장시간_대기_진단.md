# R31 Windows 빌드 장시간 대기 진단 · 통합 패치

## 근거

- GitHub Actions run #1: `Run all source tests and syntax checks`에서 실패. Windows 기본 인코딩, sqlite 파일 잠금, 임시 경로 실체화 차이로 인한 네 가지 오류를 직전 패치에서 수정함.
- run #2 (`38790462582`): 소스 테스트와 4개 PyInstaller EXE 생성이 성공했지만 `Run the real Windows EXEs with no GUI and verify bundled resources`가 장시간 진행 중이었다. 해당 기존 workflow는 `Start-Process -Wait`로 **시간제한 없이** 실행파일을 기다렸고, 어느 EXE에서 멈춘 것인지 로그가 불충분했다.
- 정확히 어떤 EXE 또는 하위 프로세스가 대기를 유발했는지는 현재 GitHub 실행 로그의 해당 단계가 완료되지 않아 확정하지 못했다.

## 한 번에 적용한 변경

1. 4개 Windows 실행파일 자체검사와 Companion 첫 실행 진단을 `scripts/windows_smoke_r31.ps1`에 통합.
2. 설치형 사용 시 설치·설치 후 EXE 검증·제거에도 같은 시간제한 프로세스 감시 적용.
3. 개별 EXE 실행 시작과 종료 시간, 실패 코드, **90초 제한을 초과한 프로세스 이름**을 로그에 표시하고, 시간초과 시 하위 프로세스까지 종료.
4. 임시·기존 보고서 재활용 금지. 모든 EXE 보고서의 버전/실행 여부/검사 성공을 확인하고, 게임 검증이나 자동 조작 성공으로 잘못 표시하지 못하도록 검사.
5. PowerShell 스크립트 실행 결과를 `$LASTEXITCODE`로 오판하지 않도록, 오류 발생 시 throw로 바로 CI 단계를 실패 처리.
6. `publish_release`/`build_installer` 기본값 false 및 4 EXE와 ZIP·해시 검증 필수 유지. 자동 배포, 게임 자동 클릭은 추가하지 않음.
7. 이전 CI 검증 테스트를 새 스크립트 구조로 수정하고, 타임아웃·중단·보고서 검증·자동 배포 금지 정적 회귀 테스트 추가.

## 검증 범위

- Linux 소스 유닛 테스트 516건 통과, `compileall -q .` 통과.
- YAML 구문/구조 파싱 통과.
- PowerShell 실행과 Windows PyInstaller EXE 시작은 **새 GitHub Actions Windows 빌드 결과가 있어야 검증할 수 있음**.
- **이 패치에서 Windows 실행이 성공했다고 주장하지 않는다.** 수정 이전의 진행 중인 기존 run #2에는 수정 내용이 적용되지 않는다.

## 다음 확인 순서

1. 새 GitHub `main` 커밋에서 Actions → `Build Windows portable` → Run workflow. 기본값 `build_installer=false`, `publish_release=false` 유지.
2. `Bounded Windows EXE smoke checks`에서 마지막으로 표시된 `[UMA smoke] START` 대상 확인. 실패하면 90초 내에 해당 실행파일 이름 또는 오류 코드가 표시되어야 함.
3. 정상일 때에만 `Artifacts → UmaTrainerKR-R31-Windows-Verified → portable/UmaTrainerKR-Portable-v0.31.0.zip` 다운로드.
4. 배포 파일을 테스트한 뒤에만 선택적으로 공식 Release 등록. 실제 한국 서버의 OCR·추천 정확도는 추가 검증 필요.

## 2026-10-16 후속 조사와 진단 경로 보강

- Actions #2 (`38790462582`)에서는 메인·Companion·GameTest·Preflight의 네 EXE 빌드가 모두 성공했다. 종료 정리에서 `UmaTrainerKR_Companion` 프로세스 둘이 강제 종료됐다. 기존 검사 단계에는 대상별 START 로그가 없으므로 어느 EXE 또는 자식이 대기 원인이었는지는 확정할 수 없다.
- Actions #3 (`38795705012`) 로그에는 `Aborted by user request`가 명시되어 있다. 메인 EXE 빌드 실패로 분류하지 않는다.
- 네 GUI 진입점의 `--self-check-report` 요청을 tkinter·OCR·화면 관련 모듈 import 이전에 처리한다. Companion의 `--first-run-report`도 조기 처리한다. 일반 실행 경로와 기능은 유지한다.
- PowerShell smoke 단계는 대상별 PID와 실패 경과 시간을 출력한다. 실패했을 때는 검증 전 EXE가 아닌 smoke JSON 및 PyInstaller 경고만 별도의 진단 artifact에 보관한다.
- 아카이브 전 검증은 EXE별 필수 리소스 목록 전체, 각 항목의 성공 여부와 필수 의존성을 재검사한다. 빈 목록·누락된 의존성으로 `PASS`를 주장할 수 없게 한다.
- 이 변경은 **실제 Windows 빌드의 성공 증거가 아니다.** 소스 정적 회귀 검사를 추가했으며, 새 커밋으로 수동 빌드를 실행해야만 Windows 동작을 확인할 수 있다. 한국 서버 실게임 인식 검증은 별도다.
