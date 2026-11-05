"""Offline, verified program updates. User data is never taken from a package."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile
from contextlib import closing
from portable import BUNDLE_NAME, EXE_NAME, VERSION

DOCS={'使用说明.txt','升级说明.txt','网站Excel对账说明.md','版本信息.json','THIRD_PARTY_NOTICES.txt','update-manifest.json'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def allowed(name):
    p=PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and ':' not in name and '\\' not in name
            and p.as_posix()==name and not any(part.endswith((' ','.')) or any(ord(c)<32 or c in '<>"|?*' for c in part) for part in p.parts)
            and (name==EXE_NAME or name in DOCS or (len(p.parts)>1 and p.parts[0]=='_internal')))


def version_tuple(value):
    try:
        parts=tuple(int(p) for p in value.split('.'))
        if len(parts)!=3 or any(p<0 for p in parts):
            raise ValueError()
        return parts
    except (ValueError,AttributeError):
        raise ValueError('更新包版本号无效。')


def unpack_update(archive,destination,current_version=VERSION):
    destination=Path(destination)
    try:
        with zipfile.ZipFile(archive) as z:
            if sum(i.file_size for i in z.infolist())>300_000_000:
                raise ValueError('更新包过大。')
            prefix=BUNDLE_NAME+'/'
            manifest=json.loads(z.read(prefix+'update-manifest.json'))
            if manifest.get('product')!='material-ledger' or manifest.get('platform')!='windows-x64' or manifest.get('format')!=1:
                raise ValueError('不是兼容的物料台账更新包。')
            if version_tuple(manifest['version'])<=version_tuple(current_version):
                raise ValueError('请选择比当前版本更新的更新包。')
            files=manifest['files']
            if not isinstance(files,dict) or EXE_NAME not in files or not any(n.startswith('_internal/') for n in files):
                raise ValueError('更新包缺少程序或运行库。')
            names=[i.filename for i in z.infolist() if not i.is_dir()]
            if len(names)!=len(set(n.casefold() for n in names)):
                raise ValueError('更新包包含重复文件。')
            expected={prefix+n for n in files}|{prefix+'update-manifest.json'}
            if set(names)!=expected or any(not allowed(n) or n=='update-manifest.json' for n in files):
                raise ValueError('更新包包含不允许的文件（例如 data），未执行更新。')
            if sum(i.file_size for i in z.infolist())>300_000_000:
                raise ValueError('更新包过大。')
            destination.mkdir(parents=True,exist_ok=False)
            for name,sha in files.items():
                data=z.read(prefix+name)
                if hashlib.sha256(data).hexdigest()!=sha:
                    raise ValueError('更新包文件校验失败，请重新完整复制：'+name)
                path=destination/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(data)
            (destination/'update-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            meta=json.loads((destination/'版本信息.json').read_text(encoding='utf-8'))
            if meta['version']!=manifest['version']:
                raise ValueError('更新包版本信息不一致。')
            return manifest
    except (zipfile.BadZipFile,KeyError,TypeError,json.JSONDecodeError,UnicodeDecodeError) as exc:
        raise ValueError('更新包损坏或缺少校验清单，请选择支持本地更新的新包。') from exc


def prepare_update(base,store,archive):
    base=Path(base).resolve()
    session=base/'.updates'/uuid.uuid4().hex
    session.mkdir(parents=True)
    manifest=unpack_update(archive,session/'new')
    backup=store.backup()
    # Run the updater from an independent copy, so Windows can replace the original runtime.
    helper=session/'helper'
    helper.mkdir()
    shutil.copy2(base/EXE_NAME,helper/EXE_NAME)
    shutil.copytree(base/'_internal',helper/'_internal')
    plan=dict(base=str(base),session=str(session),data=str(store.directory.resolve()),backup=str(backup.resolve()),
              parent_pid=os.getpid(),version=manifest['version'])
    path=session/'plan.json'
    path.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    return path,manifest


def swap_program(base,staged,rollback):
    """Only known program roots are moved; roll back even a partially completed move."""
    base,staged,rollback=map(Path,(base,staged,rollback))
    rollback.mkdir(exist_ok=False)
    names=[EXE_NAME,'_internal']+sorted(DOCS)
    saved=[]
    installed=[]
    try:
        for name in names:
            if not (staged/name).exists():
                continue
            if (base/name).exists():
                os.replace(base/name,rollback/name)
                saved.append(name)
            os.replace(staged/name,base/name)
            installed.append(name)
    except Exception:
        restore_program(base,rollback,installed,saved,staged)
        raise
    return installed,saved


def restore_program(base,rollback,installed,saved,staged):
    for name in reversed(installed):
        os.replace(base/name,staged/name)
    for name in reversed(saved):
        os.replace(rollback/name,base/name)


def wait_parent(pid):
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    api.OpenProcess.restype=wintypes.HANDLE
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x00100000,False,pid)
    if not handle:
        if ctypes.get_last_error()==87:
            return
        raise OSError('无法等待旧程序退出，请关闭后重试。')
    try:
        if api.WaitForSingleObject(handle,60000)!=0:
            raise TimeoutError('旧程序未退出，未替换文件。')
    finally:
        api.CloseHandle(handle)


def run_update(plan_path):
    plan_path=Path(plan_path).resolve()
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    base=Path(plan['base']).resolve()
    session=Path(plan['session']).resolve()
    if session.parent!=base/'.updates' or plan_path!=session/'plan.json':
        raise ValueError('更新任务路径无效。')
    staged=session/'new'
    rollback=session/'rollback'
    installed=saved=None
    process=None
    wait_parent(plan['parent_pid'])
    try:
        # Check that staging was not damaged after validation.
        manifest=json.loads((staged/'update-manifest.json').read_text(encoding='utf-8'))
        for name,sha in manifest['files'].items():
            if not allowed(name) or digest(staged/name)!=sha:
                raise ValueError('待更新文件校验失败。')
        # Exercise the actual new runtime against a COPY of this user's database first.
        probe=session/'probe'
        probe.mkdir()
        shutil.copy2(plan['backup'],probe/'ledger.sqlite3')
        with closing(sqlite3.connect(probe/'ledger.sqlite3')) as db:
            expected_count=db.execute("SELECT count(*) FROM assets WHERE active=1 AND status<>'已转出'").fetchone()[0]
            expected_logs=db.execute('SELECT count(*) FROM events').fetchone()[0]
        report=session/'probe-result.json'
        subprocess.run([str(staged/EXE_NAME),'--data-dir',str(probe),'--verify-runtime',str(report)],timeout=40,check=True)
        info=json.loads(report.read_text(encoding='utf-8'))
        if info['version']!=plan['version'] or info['integrity']!='ok' or info['stats']['total']!=expected_count or info['log_count']!=expected_logs:
            raise ValueError('新版启动验证未通过。')
        installed,saved=swap_program(base,staged,rollback)
        ready=session/'ready.json'
        process=subprocess.Popen([str(base/EXE_NAME),'--data-dir',plan['data'],'--update-ready',str(ready)])
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if ready.exists():
                (base/'update-result.json').write_text(json.dumps(dict(result='success',version=plan['version'],program_backup=str(rollback),database_backup=plan['backup']),ensure_ascii=False,indent=2),encoding='utf-8')
                return
            if process.poll() is not None:
                break
            time.sleep(.2)
        raise RuntimeError('新版未能完成启动，正在恢复旧版。')
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if installed is not None:
            restore_program(base,rollback,installed,saved,staged)
            # No ready signal means the new app has not yet accepted user operations.
            shutil.copy2(plan['backup'],Path(plan['data'])/'ledger.sqlite3')
        (base/'update-result.json').write_text(json.dumps(dict(result='failed',error=str(exc),database_backup=plan['backup']),ensure_ascii=False,indent=2),encoding='utf-8')
        subprocess.Popen([str(base/EXE_NAME),'--data-dir',plan['data']])
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'更新未完成，已保留或恢复旧版。\n'+str(exc)+'\n详情见程序目录 update-result.json。','物料台账更新',0x10)
