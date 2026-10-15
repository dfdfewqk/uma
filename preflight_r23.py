"""R23 local first-run preflight, read-only and privacy-minimal.

The resulting JSON contains no user path, window title, screenshots, or IP address.
"""
from __future__ import annotations
import importlib.util
import os
from dataclasses import dataclass, asdict

from screen_r4 import tesseract_executable

@dataclass(frozen=True)
class PreflightStatus:
    platform_windows: bool
    screenshot_module_available: bool
    image_matcher_available: bool
    numeric_ocr_available: bool
    saved_numeric_rois_present: bool
    saved_scene_profiles_present: bool
    saved_button_templates_present: bool
    detected_game_window: bool
    manual_review_required: bool = True
    automatic_clicks_enabled: bool = False
    actually_tested_on_korean_client: bool = False

    def safe_export(self):
        return {'schema':'uma_r23_first_run_preflight_v1',**asdict(self)}


def inspect_local_environment() -> PreflightStatus:
    """Gather *availability*, not user-specific path or window-title details."""
    from screen_r4 import profile_path as numeric_path
    from scene_recognition_r20 import profile_path as scene_path
    from button_detection_r21 import path_default as button_path
    from companion_window import discover_windows
    from companion_core import choose_window

    has_image = importlib.util.find_spec('PIL') is not None
    has_matcher = (importlib.util.find_spec('cv2') is not None and
                   importlib.util.find_spec('numpy') is not None)
    game_found = False
    if os.name == 'nt':
        try:game_found = choose_window(discover_windows())[0] is not None
        except (OSError,ValueError,RuntimeError):game_found = False
    return PreflightStatus(
        platform_windows=(os.name=='nt'),
        screenshot_module_available=has_image,
        image_matcher_available=has_matcher,
        numeric_ocr_available=bool(tesseract_executable()),
        saved_numeric_rois_present=numeric_path().is_file(),
        saved_scene_profiles_present=scene_path().is_file(),
        saved_button_templates_present=button_path().is_file(),
        detected_game_window=game_found)


def explain(status: PreflightStatus) -> list[str]:
    def text(label,ready):return ('[확인] ' if ready else '[미완료] ')+label
    return [text('Windows PC 환경',status.platform_windows),
            text('화면 캡처 라이브러리',status.screenshot_module_available),
            text('버튼 이미지 비교용 OpenCV',status.image_matcher_available),
            text('숫자 OCR 엔진 Tesseract',status.numeric_ocr_available),
            text('기존 숫자 영역 보정',status.saved_numeric_rois_present),
            text('화면 종류 인식 기준 등록',status.saved_scene_profiles_present),
            text('훈련 버튼 모양 등록',status.saved_button_templates_present),
            text('실행 중 게임 창 감지',status.detected_game_window),
            '읽기·추천 보조 기능만 사용합니다. 자동 클릭은 비활성화 상태입니다.',
            '한국 서버 실게임 테스트는 아직 수행하지 않았습니다.']
