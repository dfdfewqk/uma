# R9 수집 양식 사용법

- `verified_observations_blank.csv` 는 **빈 CSV 양식**이며 실제 게임 표본 **0건**입니다.
- 각 행은 육성의 한 턴에서 실제로 확인한 한 훈련 선택지의 스탯·스킬 Pt **표시값**입니다. 스킬 발동률·최종 고점 예측 라벨이 아닙니다.
- 동일 육성이라면 `run_id`를 일관되게 사용하며 **다른 턴을 새 육성으로 속여 입력하지 않습니다.**
- `sample_id`는 전체 자료 내에서 유일하게 지정하고, `frame_sha256`에 실제 검수한 프레임 파일의 SHA-256 문자열을 씁니다.
- `verified=true`, `synthetic=false`는 **실제 프레임을 사람이 확인한 경우에만** 씁니다. 실측/재현을 했다는 증빙을 이 도구가 자체 보장하지는 않습니다.
- `server=JP`, `patch_status=JP_after_2025_06_30_2320`인 경우 2025-07-01 이후 기록만 허용합니다.
- `server=KR`인 경우 게임의 수정 후 적용이 확인된 자료에만 `patch_status=KR_post_patch_confirmed`를 사용합니다.
- `purpose`는 `챔피언스 미팅` / `리그 오브 히어로즈` 중 하나로 입력합니다.
- `source_type`은 `original_capture` 또는 `reviewed_video_frame`; 영상은 원본 URL 필수입니다.
- `facility_levels_json`은 `스피드`, `스태미나`, `파워`, `근성`, `지능`, `해변의 집` 키를 가진 JSON 객체(레벨 0~5, 집 0~3).
- `facility_routes_json`은 같은 6개 키, Lv1~2는 `미선택`, Lv3 이상은 `본능` 또는 `기교`입니다.
- `friendship_counts_json`은 스피드~지능 5개 우정 인원(0~6) JSON입니다.
- `support_deck_key`는 카드/돌파/편성 변동을 구분하는 식별 문자열입니다. 개인정보를 입력하지 마세요.
- `context_key`는 의욕, 훈련 Lv, 훈련 보정, 현재 우정 배치 등 비교에 영향을 주는 추가 요소들을 완전히 확인한 동일 조건 키입니다. 달라지면 다른 키를 사용하세요.
- `g_speed` / `g_stamina` / `g_power` / `g_guts` / `g_wisdom`, `skill_points`에 표시된 숫자만 입력합니다. **모르면 0으로 채우지 말고 행 전체를 검수 보류**하세요.
- CSV 파일은 개인 PC에 저장합니다. R9 보고서에는 개별 프레임/개인정보를 포함하지 않습니다.
- 10건/8개 독립 육성 조건은 **최소 기술적 표시 조건이지 통계적 성능 보장 기준이 아닙니다.**
