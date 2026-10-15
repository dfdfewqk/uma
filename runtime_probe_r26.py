"""R26 first-run readiness probe for a local Windows installation.

No game process manipulation, screenshot, network or file upload. The report only
contains booleans and public schema strings (no paths or process titles).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from package_selftest_r25 import write_report
from preflight_r23 import PreflightStatus, inspect_local_environment

SCHEMA = 'uma_r26_windows_first_run_v1'


def classify(status: PreflightStatus) -> str:
    if not status.platform_windows or not status.screenshot_module_available or not status.image_matcher_available:
        return 'ENVIRONMENT_INCOMPLETE'
    if not status.numeric_ocr_available:
        return 'OCR_NOT_CONFIGURED'
    if not status.detected_game_window:
        return 'GAME_NOT_DETECTED'
    if not all((status.saved_numeric_rois_present, status.saved_scene_profiles_present,
                status.saved_button_templates_present)):
        return 'CALIBRATION_REQUIRED'
    return 'READY_FOR_GAME_VALIDATION'


def report_from(status: PreflightStatus) -> dict:
    payload = status.safe_export()
    payload['schema'] = SCHEMA
    payload['readiness'] = classify(status)
    payload['real_game_ocr_verified'] = False
    payload['automatic_clicks_enabled'] = False
    payload['installer_compatibility_verified'] = False
    return payload


def maybe_run_cli(argv: list[str] | None = None) -> bool:
    """Intercept diagnostic CLI ahead of the Tk event loop, without GUI startup."""
    args = list(sys.argv[1:] if argv is None else argv)
    if '--first-run-report' not in args:
        return False
    if len(args) != 2 or args[0] != '--first-run-report' or not args[1]:
        raise SystemExit(2)
    try:
        report = report_from(inspect_local_environment())
        write_report(report, Path(args[1]))
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(2) from error
    # 'not ready' is not an execution error (CI runners do not have Uma installed).
    raise SystemExit(0)
