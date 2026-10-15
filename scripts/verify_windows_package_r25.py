"""R25 CI: verify real built EXE startup reports and installer, emit checksums.

This verifies Windows packaging only. It never accesses a game client.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

PROGRAMS = ('UmaTrainerKR', 'UmaTrainerKR_Companion',
            'UmaTrainerKR_GameTest', 'UmaTrainerKR_Preflight')


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(directory: Path, version: str) -> dict:
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
        if any(not item.get('ok') for item in report.get('required_resources',[])):
            raise ValueError(f'{name} missing runtime asset')
        results[f'{name}.exe']={'size':exe.stat().st_size,'sha256':sha256(exe)}
    installer=directory/'installer'/f'UmaTrainerKR_Setup_{version}.exe'
    if not installer.is_file() or installer.stat().st_size<10_000:
        raise ValueError('Installer missing')
    results[f'installer/{installer.name}']={'size':installer.stat().st_size,'sha256':sha256(installer)}
    return {
        'schema':'uma_r25_windows_package_manifest_v1',
        'version':version,
        'verification':'real_windows_runner_exe_startup_and_installer_created',
        'korean_game_tested':False,
        'automation_enabled':False,
        'files':results,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('version')
    parser.add_argument('--output',type=Path,default=None)
    a=parser.parse_args()
    info=verify(a.directory,a.version)
    target=a.output or (a.directory/'SHA256_MANIFEST.json')
    if target.exists():
        raise SystemExit('Refusing to overwrite an existing verification manifest')
    target.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Windows binary package validated: {len(info["files"])} files')

if __name__=='__main__':
    main()
