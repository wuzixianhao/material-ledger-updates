"""Portable archive creation: bundle whitelist + consistent SQLite snapshot."""
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

VERSION = '2.7.0'
BUNDLE_NAME = 'MaterialLedger-Windows-x64'
EXE_NAME = '物料台账.exe'


class SnapshotSource:
    """Independent read-only connection, safe to create in an export worker."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def backup(self, target):
        uri = (self.directory / 'ledger.sqlite3').resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)


def export_portable(bundle, store, destination):
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    if not (bundle / EXE_NAME).is_file() or not (bundle / '_internal').is_dir():
        raise ValueError('请使用便携 EXE 版本导出完整迁移包。')
    if destination.suffix.lower() != '.zip':
        raise ValueError('迁移包请保存为 .zip 文件。')
    if destination.is_relative_to((bundle / '_internal').resolve()) or destination.is_relative_to(store.directory.resolve()):
        raise ValueError('迁移包请保存在数据和运行库目录之外，例如桌面或 U 盘。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Temporary files are scoped to a unique directory and removed by TemporaryDirectory.
    with tempfile.TemporaryDirectory(prefix='material-transfer-', dir=destination.parent) as temporary:
        temporary = Path(temporary)
        snapshot = temporary / 'ledger.sqlite3'
        store.backup(snapshot)
        with closing(sqlite3.connect(snapshot)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('数据库快照校验失败，迁移包未生成。')
            asset_count = db.execute("SELECT count(*) FROM assets WHERE active=1 AND status<>'已转出'").fetchone()[0]
            log_count = db.execute('SELECT count(*) FROM events').fetchone()[0]
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            supply_count=db.execute('SELECT count(*) FROM supplies WHERE active=1').fetchone()[0] if 'supplies' in tables else 0
        output = temporary / 'archive.zip'
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            def add(path, relative):
                archive.write(path, BUNDLE_NAME + '/' + Path(relative).as_posix())
            add(bundle / EXE_NAME, EXE_NAME)
            for path in sorted((bundle / '_internal').rglob('*')):
                if path.is_file():
                    add(path, path.relative_to(bundle))
            for name in ('使用说明.txt', '升级说明.txt', '版本信息.json', 'THIRD_PARTY_NOTICES.txt'):
                if (bundle / name).is_file():
                    add(bundle / name, name)
            add(snapshot, 'data/ledger.sqlite3')
            initial = store.directory / 'initial-inventory.sqlite3'
            if initial.exists():
                add(initial, 'data/initial-inventory.sqlite3')
            backups = store.directory / 'backups'
            if backups.exists():
                for path in sorted(backups.glob('*.sqlite3')):
                    add(path, 'data/backups/' + path.name)
            for path in sorted(store.directory.glob('before-*.sqlite3')):
                add(path,'data/'+path.name)
            archive.writestr(BUNDLE_NAME + '/迁移清单.json', json.dumps(dict(
                version=VERSION, exported_at=datetime.now().astimezone().isoformat(),
                on_account=asset_count, event_count=log_count, non_platform_records=supply_count, database='data/ledger.sqlite3',
                note='包含导出时点的完整台账及日志，不包含导出后发生的修改。'), ensure_ascii=False, indent=2))
        os.replace(output, destination)
    return destination
