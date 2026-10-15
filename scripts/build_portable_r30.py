"""Build a strictly validated portable release archive from checked Windows EXEs."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portable_update_r30 import EXE_FILES, _check_zip


def package(dist_dir: Path, version: str) -> tuple[Path, Path]:
    dist_dir = Path(dist_dir).resolve()
    output = dist_dir / 'portable'
    output.mkdir(parents=True, exist_ok=True)
    name = f'UmaTrainerKR-Portable-v{version}.zip'
    destination = output / name
    for executable in EXE_FILES:
        if not (dist_dir / executable).is_file():
            raise FileNotFoundError(f'Missing checked Windows executable: {executable}')
    readme = (
        f'Uma Trainer KR v{version} - Windows portable edition\n\n'
        '1. Extract the ZIP to your own folder.\n'
        '2. Run UmaTrainerKR_Companion.exe (no program installation required).\n'
        '3. Open the updater panel inside the program to check official GitHub Releases.\n'
        '4. Updates are placed in a separate sibling folder and the older version stays intact.\n'
        '5. Personal settings and training records are stored under LOCALAPPDATA\\UmaTrainerKR.\n'
        'Note: Tesseract OCR may still require separate setup.\n'
        'In-game detection, training decisions and overlay are not yet validated on Korean live game.\n'
    )
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for executable in sorted(EXE_FILES):
            zf.write(dist_dir / executable, arcname=executable)
        zf.writestr('PORTABLE_VERSION.txt', version + '\n')
        zf.writestr('PORTABLE_README.txt', readme)
    _check_zip(destination, version)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix('.zip.sha256')
    checksum.write_text(f'{digest}  {name}\n', encoding='ascii')
    return destination, checksum


def main() -> None:
    version_text = (ROOT / 'VERSION.txt').read_text(encoding='utf-8')
    result = re.search(r'(?m)^Version:\s*(\d+\.\d+\.\d+)\s*$', version_text)
    if not result:
        raise SystemExit('Invalid VERSION.txt')
    archive, checksum = package(Path(sys.argv[1] if len(sys.argv)>1 else 'dist'), result.group(1))
    print(f'Portable archive verified: {archive}\nSHA256: {checksum}')


if __name__ == '__main__':
    main()
