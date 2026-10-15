# Uma Trainer KR

한국 우마무스메 PC 전용 육성 보조 프로젝트. R29 개발본.

- **일반 화면:** 게임 옆 작은 정보창 및 게임 위 훈련 추천 표식(검증 전).
- **R29 추가:** 게임이 업데이트되거나 화면이 달라도 사용자가 원할 때 진단용 실제 게임 화면 자료를 로컬에 저장하고 ZIP으로 내보내는 기능. 자동 업로드 없음.
- **목표:** 챔피언스 미팅·리그 오브 히어로즈 / 무인도부터 지원하고 향후 시나리오 추가.
- **미구현:** 게임 자동 클릭, 검증된 자동 육성 및 실제 승률 기반 ML.

## 실행
`python -m pip install -r requirements.txt` 후 `python companion.py` (Windows 실PC).
`python -m unittest discover -s tests -q` (소스 테스트).

Python 없는 설치파일은 GitHub **수동** Actions 빌드로 생성합니다. 아직 빌드 및 한국 서버 실제 호환성은 검증되지 않았습니다.

자세한 내용은 `docs/R29_실게임화면_증거팩_사용방법.md`에 있습니다.

## Windows 설치파일 받기 (소스 업로드와 별개)
1. GitHub 저장소의 **Actions** 탭에서 **Build and verify Windows installer (manual only)** 워크플로를 엽니다.
2. **Run workflow** → `main` → **Run workflow**를 클릭합니다.
3. 성공한 실행의 **Artifacts**에서 `UmaTrainerKR-R29-Windows-Verified`를 내려받습니다.
4. 내부의 `installer/UmaTrainerKR_Setup_0.29.0.exe`를 사용합니다.

이 단계는 수동 실행되며, 아직 실제 Windows 빌드 성공 여부와 게임 화면 호환성은 확인되지 않았습니다.
