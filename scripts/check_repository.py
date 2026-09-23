"""Small release gates: version agreement and tracked-file hygiene."""
from pathlib import Path
import os
import re
import runpy
import subprocess
import tomllib

root=Path(__file__).resolve().parents[1]
version=runpy.run_path(str(root/'source/appmeta.py'))['VERSION']
assert re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',version), 'Invalid release version'
assert tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8-sig'))['project']['version']==version, 'Version mismatch'
ref=os.environ.get('GITHUB_REF','')
if ref.startswith('refs/tags/'):
    assert ref=='refs/tags/v'+version, 'Tag must match application version'
tracked=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True).stdout.decode().split('\0')
for name in filter(None,tracked):
    p=Path(name)
    assert not any(part in {'data','browser-profile','.venv','release','dist','build'} for part in p.parts), f'Local build/data tracked: {name}'
    assert p.suffix.lower() not in {'.sqlite3','.db','.pfx','.p12','.key','.docx','.xlsx','.exe','.zip'}, f'Unexpected private/binary artifact tracked: {name}'
print(f'Repository gates passed for v{version}.')
