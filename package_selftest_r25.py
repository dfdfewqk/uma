"""R25: independent, read-only startup self-check for Windows EXE packages.

This checks bundled assets and importability, *not* Korean game compatibility.
Reports avoid process/window titles, usernames, absolute filesystem paths,
screenshots and user data. A failed required check results in a non-zero exit code.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

SCHEMA = 'uma_r25_executable_selfcheck_v1'
ESSENTIAL_DEPS = {
    'UmaTrainerKR': ('PIL',),
    'UmaTrainerKR_Companion': ('PIL','cv2','numpy'),
    'UmaTrainerKR_GameTest': ('PIL',),
    'UmaTrainerKR_Preflight': ('PIL',),
}

ASSETS = {
    'UmaTrainerKR': (
        'research/sources.json',
        'research/r13/japan_island_2025_events.json',
        'research/r14/lineage_and_calendar.json',
        'scenario_policies/island_post_patch_v1.json',
        'research/video_reviews/verified_turns.csv',
        'research/video_reviews/review_queue.csv',
        'research/jp_post_patch_2025/sources.csv',
        'research/jp_post_patch_2025/video_chapters.csv',
    ),
    'UmaTrainerKR_Companion': (),
    'UmaTrainerKR_GameTest': ('scenario_policies/island_post_patch_v1.json',),
    'UmaTrainerKR_Preflight': (
        'examples/r23_demo_manifest.json',
        'examples/r22_mock_roi.json',
        'examples/r22_mock_1.png',
        'examples/r22_mock_2.png',
        'examples/r22_mock_3.png',
        'examples/r22_mock_4.png',
        'examples/r22_mock_5.png',
    ),
}


def bundle_root() -> Path:
    # PyInstaller onefile extracts data to _MEIPASS. Python source uses project root.
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def inspect(package: str, *, root: Path | None = None,
            frozen: bool | None = None) -> dict:
    if package not in ASSETS:
        raise ValueError('Unknown executable profile')
    base = Path(root) if root is not None else bundle_root()
    frozen_flag = bool(getattr(sys, 'frozen', False)) if frozen is None else bool(frozen)
    resources = []
    bad = []
    for relative in ASSETS[package]:
        path = base / relative
        exists = path.is_file() and not path.is_symlink()
        nonempty = exists and path.stat().st_size > 0
        valid_json = True
        if nonempty and path.suffix == '.json':
            try:
                json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError):
                valid_json = False
        valid_image = True
        if nonempty and path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            try:
                from PIL import Image
                with Image.open(path) as img:
                    img.verify()
            except (ImportError, OSError, ValueError):
                valid_image = False
        ok = bool(nonempty and valid_json and valid_image)
        if not ok:
            bad.append(relative)
        # Only relative asset labels in the report; do not export actual path.
        resources.append({'resource': relative, 'ok': ok})
    dependencies = {}
    for module in ('PIL', 'cv2', 'numpy'):
        try:
            dependencies[module] = importlib.util.find_spec(module) is not None
        except (ValueError, ImportError):
            dependencies[module] = False
    # Modules are imported directly at app startup. Presence is prerequisite for
    # OCR screenshots and template matching, but NOT proof of on-screen accuracy.
    missing_dependencies = [m for m in ESSENTIAL_DEPS[package] if not dependencies[m]]
    fatal = bool(bad or missing_dependencies)
    return {
        'schema': SCHEMA,
        'executable': package,
        'frozen_binary': frozen_flag,
        'required_resources': resources,
        'dependencies_available': dependencies,
        'requires_external_ocr': True,
        'game_client_tested': False,
        'actual_button_detection_verified': False,
        'automatic_click_enabled': False,
        'result': 'FAIL' if fatal else 'PASS',
        'failed_resource_names': bad,
        'missing_dependencies': missing_dependencies,
    }


def write_report(payload: dict, path: Path) -> None:
    """Atomic, non-overwriting report; no unintended capture of personal data."""
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise ValueError('진단 파일이 이미 있습니다. 새로운 이름을 사용하세요.')
    if not destination.parent.is_dir():
        raise ValueError('진단 파일을 저장할 폴더가 없습니다.')
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    # Keep side effect limited to a caller-provided local output path.
    fd, temporary = tempfile.mkstemp(prefix='uma_selfcheck_', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(raw)
        # Link with exclusive creation semantics instead of replacing existing data.
        os.link(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def maybe_run_cli(package: str, argv: list[str] | None = None) -> bool:
    """Intercept packaged --self-check-report PATH without starting any Tk GUI.

    Return False for ordinary launches. Self-check launches exit explicitly so
    GUI entrypoint blocks cannot silently fall through.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--self-check-report' not in argv:
        return False
    if len(argv) != 2 or argv[0] != '--self-check-report' or not argv[1]:
        raise SystemExit(2)
    try:
        report = inspect(package)
        write_report(report, Path(argv[1]))
    except (OSError, ValueError) as exc:
        # GUI executables do not have a console. Exit code signals failure.
        raise SystemExit(2) from exc
    raise SystemExit(0 if report['result'] == 'PASS' else 1)
