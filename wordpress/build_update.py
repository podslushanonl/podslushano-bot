#!/usr/bin/env python3
"""Package a compact theme update with the same layout as update 32.

Run build_theme.py first, then: python3 wordpress/build_update.py 34 --asset img/tikkie-logo.png
Existing images, fonts and media are not duplicated unless explicitly selected.
"""
import argparse
import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
THEME = ROOT / 'theme' / 'podslushano-2026'


def package(number, assets=()):
    paths = [THEME / name for name in ('links.html', 'functions.php', 'index.php', 'page-links.php', 'shell.php', 'style.css')]
    for folder, pattern in [('assets', '*.css'), ('assets', '*.js'), ('data', '*.json'), ('inc', '*.php')]:
        paths.extend(sorted((THEME / folder).glob(pattern)))
    for asset in assets:
        path = (THEME / 'assets' / asset).resolve()
        if not path.is_relative_to((THEME / 'assets').resolve()) or not path.is_file():
            raise ValueError('Asset must be a file inside the theme assets directory')
        paths.append(path)
    paths = list(dict.fromkeys(paths))
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError('Build the theme first: ' + ', '.join(missing))
    directories = {'podslushano-2026/'}
    for path in paths:
        parent = path.relative_to(THEME.parent).parent
        while str(parent) != '.':
            directories.add(parent.as_posix() + '/')
            parent = parent.parent
    out = ROOT / 'dist' / f'podslushano-2026-obnovlenie-{number}.zip'
    out.parent.mkdir(exist_ok=True)
    now = datetime.datetime.now().timetuple()[:6]
    with ZipFile(out, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(directories):
            info = ZipInfo(name, now)
            info.create_system = 3
            info.external_attr = (0o40755 << 16) | 0x10
            archive.writestr(info, b'')
        for path in paths:
            info = ZipInfo(path.relative_to(THEME.parent).as_posix(), now)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with ZipFile(out) as archive:
        assert archive.testzip() is None
        for info in archive.infolist():
            assert (info.external_attr >> 16) & 0o777 == (0o755 if info.is_dir() else 0o644)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('number', type=int)
    parser.add_argument('--asset', action='append', default=[])
    args = parser.parse_args()
    if args.number < 1:
        parser.error('Update number must be positive')
    result = package(args.number, args.asset)
    print(result, result.stat().st_size, 'bytes; files 644, folders 755')
