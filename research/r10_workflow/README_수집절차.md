# R10 원본 영상 검수 및 표시값 수집 절차

1. ⑪ R10 영상 탭에서 작업 선택 → `출처 영상 열기`. 저작권·약관이 허용하는 방식으로 로컬 이미지 또는 소유 영상 확보.
2. R2 전용 검수 도구(`research/review_tools/reviewer_ui.py`)에서 영상 출처 S번호, `case_id`, 실제 육성 목적(`champ_main` / `loh_main` / `factor_farming` / `evaluation_score`)을 분리.
3. 게임 화면에서 **실제** 선택 전후 이미지, 현재 스탯, 실제 선택/결과를 눈으로 검증해 `verified_turns.csv`에 저장. 타임스탬프만으로 추정하지 않음.
4. R10 영상 탭에서 `완료 증거 연결`로 R2 기록의 annotation_id 지정. 두 이미지 해시 및 출처/시점 검증 통과해야 완료.
5. R9 실측 CSV 변환이 필요하면 `R10_수동표시값_검수양식.json`를 별도 파일로 복사해 JSON 배열 안에 각 화면의 검증 객체를 직접 기입. 단순 행동 선택이나 R2 `post_action_json`의 값을 표시된 훈련 상승량으로 간주하면 안 됨.
6. 각 객체에는 다음 키가 모두 필요:
   - `annotation_id`, `source_url`, `preview_frame_path`, `reviewer_confirmed_preview`: true, `synthetic`: false
   - `visual_evidence_note`: 실제 화면에 보이는 표시 수치의 확인 근거 (15자 이상)
   - `training`: '스피드'/'스태미나'/'파워'/'근성'/'지능'/'섬 트레이닝'
   - `displayed_gains`: `g_speed`, `g_stamina`, `g_power`, `g_guts`, `g_wisdom`, `skill_points` 정수 6개
   - `capture_date`: 날짜 YYYY-MM-DD (일본 수정 후이면서 실제 기록·패치 확인 필요)
   - `phase`, `support_deck_key`, `context_key` (같은 조건을 정확히 구별)
   - `facility_levels`: 6개 시설의 정확한 Lv, `facility_routes`: 본능/기교/미선택
   - `friendship_counts`: 스피드/스태미나/파워/근성/지능 우정 인원
7. 예측용 미확인 값은 0으로 채우지 말고 **해당 기록 검수를 보류**. 변환된 CSV는 R9 탭에서 재감사해야 함.

## CLI

작업 CSV 생성:

`python review_pipeline_r10.py queue --out my_review_jobs.csv`

검수 상태 감사:

`python review_pipeline_r10.py audit`

R2 검수 자료와 수동 확인된 표시값을 R9 형식으로 변환:

`python review_pipeline_r10.py export-r9 --annotations 검수턴.csv --bundles 수동검수표시값.json --out r9_검수완료.csv`

**참고:** 입력 JSON이 비어 있다면 R9 CSV는 헤더만 생성되며 실전 표본은 0건. 실전 검수를 했다고 표시하지 않음. 연구 목적에 맞지 않는 수치나 원본 없는 정보는 제외.
