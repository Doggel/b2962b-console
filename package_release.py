"""Create a Windows download from the built EXE and the generic settings."""

from importlib.metadata import distribution
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
ASSET = DIST / 'B2962B_Console_Windows_x64.zip'


def add_licenses(archive):
    python = Path(sys.base_prefix)
    archive.write(python / 'LICENSE.txt', 'third-party-licenses/CPython.txt')
    for notice in sorted((python / 'tcl').glob('*/license.terms')):
        archive.write(notice, f'third-party-licenses/{notice.parent.name}.txt')

    for name in ('PyVISA', 'typing_extensions', 'PyInstaller'):
        package = distribution(name)
        notices = [entry for entry in package.files or ()
                   if entry.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE'))]
        if not notices:
            raise RuntimeError(f'No license notices found for {name}')
        for entry in notices:
            archive.write(package.locate_file(entry), f'third-party-licenses/{name}/{entry.as_posix()}')


def main():
    temp = NamedTemporaryFile(dir=DIST, suffix='.zip', delete=False)
    pending = Path(temp.name)
    try:
        with temp, ZipFile(temp, 'w', compression=ZIP_DEFLATED) as archive:
            archive.write(DIST / 'B2962B_Console.exe', 'B2962B_Console.exe')
            archive.write(ROOT / 'b2962b_scan.example.toml', 'b2962b_scan.toml')
            archive.write(ROOT / 'README.md', 'README.md')
            add_licenses(archive)
        pending.replace(ASSET)
    finally:
        pending.unlink(missing_ok=True)
    print(f'Created {ASSET}')


if __name__ == '__main__':
    main()
