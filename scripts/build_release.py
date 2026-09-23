"""Portable Windows release stages; no user data is copied."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / 'source/appmeta.py'))['VERSION']
OUT = ROOT / 'release'
BUNDLE = OUT / 'bundle/TitleVisionAssistant'


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def bundle():
    OUT.mkdir(exist_ok=True)
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', OUT / 'bundle',
        '--workpath', ROOT / 'build/release', ROOT / 'TitleVisionAssistant.spec')
    for filename in ('README.md', 'VALIDATION.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / filename, BUNDLE / filename)
    for distribution in importlib.metadata.distributions():
        for entry in distribution.files or []:
            if any(token in entry.name.upper() for token in ('LICENSE', 'COPYING', 'NOTICE')):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    destination = BUNDLE / 'third-party-licenses' / distribution.metadata['Name'] / entry.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)


def installer(iscc):
    compiler = iscc or shutil.which('ISCC.exe')
    if not compiler:
        candidates = [Path(r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'),
                      Path(r'C:\Program Files\Inno Setup 6\ISCC.exe')]
        compiler = next((p for p in candidates if p.exists()), None)
    if not compiler:
        raise SystemExit('Install Inno Setup 6, or pass --iscc PATH. The application bundle is still usable.')
    run(compiler, f'/DMyAppVersion={VERSION}', f'/DSourceDir={BUNDLE}',
        f'/DOutputDir={OUT}', ROOT / 'installer/TitleVisionAssistant.iss')


def package():
    OUT.mkdir(exist_ok=True)
    portable = OUT / f'TitleVisionAssistant-Portable-{VERSION}.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(BUNDLE.rglob('*')):
            if p.is_file():
                relative = p.relative_to(BUNDLE)
                if relative.parts[0] in {'data', 'browser-profile', 'updates'} or p.suffix in {'.sqlite3', '.db', '.pfx', '.key'}:
                    raise SystemExit('Local data detected in release bundle: ' + str(relative))
                archive.write(p, p.relative_to(BUNDLE.parent))
    inventory = {'app': 'TitleVision Assistant', 'version': VERSION,
                 'python': sys.version.split()[0], 'packages': []}
    for d in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        if d.metadata['Name'].lower() != 'pip':
            inventory['packages'].append({'name':d.metadata['Name'], 'version':d.version})
    (OUT/'dependency-inventory.json').write_text(json.dumps(inventory, indent=2)+'\n', encoding='utf-8')
    assets = [portable, OUT/'dependency-inventory.json']
    setup = OUT/f'TitleVisionAssistant-Setup-{VERSION}.exe'
    if setup.exists():
        assets.append(setup)
    lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}' for p in assets]
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(f'Release assets: {OUT}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('bundle', 'installer', 'package', 'all'))
    parser.add_argument('--iscc')
    args = parser.parse_args()
    if args.stage in ('bundle', 'all'):
        bundle()
    if args.stage in ('installer', 'all'):
        installer(args.iscc)
    if args.stage in ('package', 'all'):
        package()
