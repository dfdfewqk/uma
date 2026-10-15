# R15 자료 정책

학습 후보 내보내기 파일(`uma_r15_*.jsonl`)은 **일부러 이 저장소에 포함하지 않습니다.**

- JSONL 생성: 앱의 `⑯ R15 학습자료` → 검수 등록 → 감사 → 내보내기
- 기본 검수 데이터 위치: Windows `%LOCALAPPDATA%\UmaTrainerKR\r15_learning_reviews.sqlite3`
- 기존 게임 기록 DB: Windows `%LOCALAPPDATA%\UmaTrainerKR\runs.sqlite3`
- 템플릿 및 근거: `docs/R15_학습데이터_확장설계.md`
- 미검수 일본 영상 프레임: 0건. 실제 ML 학습 모델: 없음.

중복 영상/육성, 조작된 증거, 서버·패치 혼합이 학습 성능을 심각하게 손상시킬 수 있으므로 충분한 실제 검수 전에는 학습을 시작하지 마세요.
