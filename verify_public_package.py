"""Audit the public release assets before publishing."""
import hashlib
import json
from pathlib import Path
import zipfile

from PyInstaller.archive.readers import CArchiveReader
from portable import BUNDLE_NAME, EXE_NAME, VERSION

root=Path(__file__).resolve().parent
release=root/'release'
meta=json.loads((release/'release.json').read_text(encoding='utf-8'))
archive=release/f'MaterialLedger-{VERSION}-Windows-x64.zip'
assert meta['version']==VERSION and meta['filename']==archive.name
assert meta['sha256']==hashlib.sha256(archive.read_bytes()).hexdigest()
assert meta['size']==archive.stat().st_size
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    names=bundle.namelist()
    assert all(n.startswith(BUNDLE_NAME+'/') for n in names)
    assert not any('/data/' in n or n.endswith(('.sqlite3','.db','.csv','.jsonl')) for n in names)
    built=sorted((root/'.build-output').glob('*/dist/物料台账'))[-1]/EXE_NAME
    assert bundle.read(BUNDLE_NAME+'/'+EXE_NAME)==built.read_bytes()
archive_reader=CArchiveReader(str(built))
pyz=archive_reader.open_embedded_archive(next(k for k in archive_reader.toc if k.endswith('.pyz')))
assert 'seed' not in pyz.toc
print('Public package integrity verified; no ledger database or personal seed module.')
