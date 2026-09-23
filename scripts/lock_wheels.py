"""Generate a Windows wheel hash lock from an explicitly downloaded wheel set."""
from pathlib import Path
from email.parser import BytesParser
import argparse
import hashlib
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('wheels',type=Path)
parser.add_argument('--output',type=Path,default=Path('requirements-build.lock'))
args=parser.parse_args()
rows=[]
for wheel in sorted(args.wheels.glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        metadata=BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
    rows.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
if not rows:
    raise SystemExit('No wheels found')
args.output.write_text('# Windows x64 / CPython 3.13. Regenerate from requirements-build.in.\n'+'\n'.join(sorted(rows,key=str.lower))+'\n',encoding='utf-8')
