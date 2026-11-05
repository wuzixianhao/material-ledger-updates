"""Build using .build-env; preserve the user's data directory."""
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
import hashlib
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw
from portable import VERSION, EXE_NAME, SnapshotSource, export_portable

BASE = Path(__file__).resolve().parent


def main():
    icon = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((0, 0, 255, 255), radius=52, fill='#142238')
    draw.polygon([(57, 91), (128, 51), (199, 91), (128, 132)], fill='#72bcff')
    draw.polygon([(57, 103), (122, 141), (122, 213), (57, 175)], fill='#378aef')
    draw.polygon([(134, 141), (199, 103), (199, 175), (134, 213)], fill='#225dcc')
    icon.save(BASE / 'ledger.ico', sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = BASE / '.build-output' / stamp
    output.mkdir(parents=True)
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed', '--noupx',
        '--name', '物料台账', '--icon', str(BASE/'ledger.ico'), '--add-data', str(BASE/'ledger.ico')+':.',
        '--add-data', str(BASE/'ui_assets')+':ui_assets',
        '--distpath', str(output/'dist'), '--workpath', str(output/'work'), '--specpath', str(output),
        '--exclude-module', 'PIL', '--exclude-module', 'seed', '--exclude-module', 'unittest', str(BASE/'app.py')]
    subprocess.run(command, cwd=BASE, check=True)
    built = output / 'dist' / '物料台账'
    # Package the clean build output; never overwrite a running installation or its data.
    versions = {name: importlib.metadata.version(name) for name in ['pyinstaller','pillow','pyinstaller-hooks-contrib']}
    (BASE/'build-requirements.txt').write_text('\n'.join(f'{name}=={value}' for name,value in versions.items())+'\n', encoding='utf-8')
    (BASE/'版本信息.json').write_text(json.dumps(dict(version=VERSION, target='Windows 10/11 x64',
        built_at=datetime.now().astimezone().isoformat(), python=sys.version, build_tools=versions,
        storage='data/ledger.sqlite3', runtime='_internal'), ensure_ascii=False, indent=2), encoding='utf-8')
    notices = ['物料台账 '+VERSION, 'Bundled components and licenses:',
        'Python: Python Software Foundation License; https://docs.python.org/3/license.html',
        'Tcl/Tk: BSD-style license; https://www.tcl.tk/software/tcltk/license.html',
        'SQLite: Public domain; https://www.sqlite.org/copyright.html',
        'PyInstaller bootloader: GPL with exception allowing distribution of bundled applications; https://pyinstaller.org/en/stable/license.html',
        'Pillow is used only at build time for the icon and is not bundled.',
        'License files supplied by the bundler are included under _internal.']
    license_candidates = [Path(sys.base_prefix)/'LICENSE.txt', Path(sys.base_prefix)/'Lib'/'LICENSE.txt',
                          Path(sys.base_prefix)/'Library'/'lib'/'tcl8.6'/'license.terms',
                          Path(sys.base_prefix)/'Library'/'lib'/'tk8.6'/'license.terms']
    for path in license_candidates:
        if path.is_file():
            notices += ['', '--- '+path.name+' ---', path.read_text(encoding='utf-8', errors='replace')]
    (BASE/'THIRD_PARTY_NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
    archive = BASE / 'release' / ('物料台账-'+VERSION+'-Windows-x64-升级包不含数据.zip')
    archive.parent.mkdir(exist_ok=True)
    manifest=dict(format=1,product='material-ledger',platform='windows-x64',version=VERSION,files={})
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
        for path in sorted(built.rglob('*')):
            if path.is_file():
                relative=path.relative_to(built).as_posix()
                package.write(path,'MaterialLedger-Windows-x64/'+relative)
                manifest['files'][relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('使用说明.txt','升级说明.txt','网站Excel对账说明.md','版本信息.json','THIRD_PARTY_NOTICES.txt'):
            package.write(BASE/name,'MaterialLedger-Windows-x64/'+name)
            manifest['files'][name]=hashlib.sha256((BASE/name).read_bytes()).hexdigest()
        package.writestr('MaterialLedger-Windows-x64/update-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    online=archive.parent/f'MaterialLedger-{VERSION}-Windows-x64.zip'
    shutil.copy2(archive,online)
    notes=next((p.read_text(encoding='utf-8') for p in (BASE/'RELEASE-NOTES.md',BASE/'public-release-notes.md') if p.is_file()),'')
    (archive.parent/'release.json').write_text(json.dumps(dict(product='material-ledger',platform='windows-x64',version=VERSION,
        filename=online.name,size=online.stat().st_size,sha256=hashlib.sha256(online.read_bytes()).hexdigest(),notes=notes[:3000]),indent=2),encoding='utf-8')
    print(json.dumps(dict(archive=str(archive), size_mb=round(archive.stat().st_size/1048576,2))))


if __name__ == '__main__':
    main()
