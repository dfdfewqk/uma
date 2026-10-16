# R36 GUI 검증 재설계 — v0.31.2

## 확인한 사실

8차 Actions 38842216363: Python 567개 테스트 통과(2개 skipped), EXE 4종 제작 및 각 EXE 자체검사·시작 import 검사 통과. 이후 Windows Actions의 비대화형 환경에서 전체 Tk GUI 검사만 90초 TIMEOUT. 창 생성 단계인지 팝업인지는 기존 기록으로 단정할 수 없음.

## 검증 분리

- 새 `linux-gui-preflight` 선행 작업: Ubuntu 가상 화면(Xvfb)에서 실제 app.py Tk 창을 생성, 합성 입력으로 R6→R34→R35 검토, 변경 시 결과 무효화, 수동 입력 불일치를 검사.
- 검사 실패 시 단계별 진행 메시지와 예외 클래스만 남기고 비정상 종료. 예상 못 한 모달 팝업은 실패로 처리하며 120초 상한 적용.
- 성공 증거 JSON은 `gui_platform=linux`, `frozen_binary=false`, `synthetic_only=true`로 구분.
- Windows 작업은 성공한 source GUI 증거를 다운로드·확인한 뒤 기존 4종 EXE 빌드, 4종 자체검사, 4종 시작 모듈 검사, Companion 첫 실행 진단을 진행.
- Windows 서비스에서 창을 다시 띄우는 검사는 중단. 이 방식은 Windows 실물 GUI 실행 성공을 보증하지 않으며, 가상 화면의 Python Tk UI와 Windows 실행파일 자체·모듈 시작을 각기 검증함.
- 패키징 검사는 선행 GUI 성공 자료와 Windows EXE 검사 모두 통과해야 ZIP을 허용함. 검증 실패 시 이전 정상 실행파일을 그대로 보존.

## 테스트와 검증 한계

추가/보완된 파일: gui_smoke_r36.py, scripts/validate_gui_r36.py, scripts/verify_windows_package_r25.py, scripts/windows_smoke_r31.ps1, Actions 워크플로 및 관련 Python 단위 테스트. R6 점수·R34/35 추천 알고리즘·기존 DB는 수정하지 않음.

실제 한국 서버 게임과의 연결·OCR·추천 정확도, Windows의 사용자 데스크톱 GUI 실행은 미검증 상태. 새 빌드 성공 여부는 Actions 결과로 별도 확인해야 함.

## 실행

https://github.com/dfdfewqk/uma/actions/workflows/windows-exe.yml

Run workflow → main → publish_release=false, build_installer=false. 자동 배포/자동 재실행은 설정하지 않음. 커밋만으로 새 Windows 빌드가 실행되지는 않음.
