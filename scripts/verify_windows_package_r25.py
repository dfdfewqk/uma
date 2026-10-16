"""R25 CI: verify real built EXE startup reports and installer, emit checksums.

This verifies Windows packaging only. It never accesses a game client.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

# This script is invoked as `python scripts/verify_windows_package_r25.py` in CI.
# Add the repository root so shared inspection contracts are importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_selftest_r25 import ASSETS, ESSENTIAL_DEPS

PROGRAMS = ('UmaTrainerKR', 'UmaTrainerKR_Companion',
            'UmaTrainerKR_GameTest', 'UmaTrainerKR_Preflight')


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(directory: Path, version: str, *, require_installer: bool = True) -> dict:
    directory=Path(directory)
    if not version or any(c not in '0123456789.' for c in version):
        raise ValueError('version is invalid')
    results={}
    for name in PROGRAMS:
        exe=directory/f'{name}.exe'
        record=directory/'smoke-reports'/f'{name}.json'
        if not exe.is_file() or exe.stat().st_size<10_000:
            raise ValueError(f'{name} executable missing or too small')
        if not record.is_file():
            raise ValueError(f'{name} startup check did not run')
        report=json.loads(record.read_text(encoding='utf-8'))
        if (report.get('schema')!='uma_r25_executable_selfcheck_v1' or
                report.get('executable')!=name or not report.get('frozen_binary') or
                report.get('result')!='PASS' or report.get('game_client_tested') is not False or
                report.get('automatic_click_enabled') is not False):
            raise ValueError(f'{name} self-check failed or report invalid')
        resources=report.get('required_resources')
        if (not isinstance(resources,list) or len(resources)!=len(ASSETS[name]) or
                any(not isinstance(item,dict) or
                    not isinstance(item.get('resource'),str) or
                    item.get('ok') is not True for item in resources) or
                {item['resource'] for item in resources} != set(ASSETS[name])):
            raise ValueError(f'{name} resource checklist invalid or incomplete')
        dependencies=report.get('dependencies_available')
        if (not isinstance(dependencies,dict) or
                any(dependencies.get(dep) is not True for dep in ESSENTIAL_DEPS[name]) or
                report.get('failed_resource_names') != [] or
                report.get('missing_dependencies') != []):
            raise ValueError(f'{name} dependency or asset failure not resolved')
        # Startup pass is invoked after the real GUI module imports, but before Tk.
        # Packaging is rejected when it is absent, even if early asset checks pass.
        startup_file=directory/'smoke-reports'/f'{name}_startup.json'
        if not startup_file.is_file():
            raise ValueError(f'{name} startup import verification did not run')
        startup=json.loads(startup_file.read_text(encoding='utf-8'))
        if (not isinstance(startup,dict) or
                startup.get('schema')!='uma_r25_executable_selfcheck_v1' or
                startup.get('executable')!=name or
                startup.get('result')!='PASS' or
                startup.get('frozen_binary') is not True or
                startup.get('game_client_tested') is not False or
                startup.get('automatic_click_enabled') is not False or
                startup.get('required_resources')!=resources or
                startup.get('dependencies_available')!=dependencies or
                startup.get('failed_resource_names')!=[] or
                startup.get('missing_dependencies')!=[]):
            raise ValueError(f'{name} startup import verification failed')
        results[f'{name}.exe']={'size':exe.stat().st_size,'sha256':sha256(exe)}
    # R36 Windows packaging is blocked unless Tk UI actually constructs and
    # both R34/R35 button paths run with isolated synthetic data.
    gui_file = directory / 'smoke-reports' / 'UmaTrainerKR_gui.json'
    if not gui_file.is_file():
        raise ValueError('R36 real Tk GUI smoke report missing')
    gui = json.loads(gui_file.read_text(encoding='utf-8'))
    required = {
        'schema': 'uma_r36_windows_gui_synthetic_smoke_v1',
        'result': 'PASS',
        'r6_reviewed_actions': 2,
        'r34_panel_created': True,
        'r35_actions_rendered': 2,
        'r35_stale_invalidation_checked': True,
        'r35_conflict_detected': True,
        'game_client_tested': False,
        'automatic_click_enabled': False,
        'synthetic_only': True,
    }
    if not isinstance(gui, dict) or any(type(gui.get(k)) is not type(v) or gui[k] != v for k, v in required.items()):
        raise ValueError('R36 real Tk GUI smoke report invalid or incomplete')
    if require_installer:
        installer=directory/'installer'/f'UmaTrainerKR_Setup_{version}.exe'
        if not installer.is_file() or installer.stat().st_size<10_000:
            raise ValueError('Installer missing')
        results[f'installer/{installer.name}']={'size':installer.stat().st_size,'sha256':sha256(installer)}
    return {
        'schema':'uma_r25_windows_package_manifest_v1',
        'version':version,
        'verification':('real_windows_runner_exe_startup_and_installer_created' if require_installer
                        else 'real_windows_runner_exe_startup_portable_only'),
        'korean_game_tested':False,
        'automation_enabled':False,
        'files':results,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('version')
    parser.add_argument('--output',type=Path,default=None)
    parser.add_argument('--portable-only', action='store_true',
                        help='Verify four actual Windows EXEs without requiring an Inno Setup installer')
    a=parser.parse_args()
    info=verify(a.directory,a.version, require_installer=not a.portable_only)
    target=a.output or (a.directory/'SHA256_MANIFEST.json')
    if target.exists():
        raise SystemExit('Refusing to overwrite an existing verification manifest')
    target.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Windows binary package validated: {len(info["files"])} files')

if __name__=='__main__':
    main()
