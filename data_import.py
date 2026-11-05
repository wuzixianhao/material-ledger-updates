"""Explicit full-ledger import with preview, validation and rollback backup."""
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from portable import SnapshotSource
from store import Store


def inspect_database(path):
    path=Path(path).resolve()
    if not path.is_file():
        raise ValueError('请选择旧版数据目录中的 ledger.sqlite3，或工具生成的数据库备份。')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('数据库完整性校验未通过。')
            required={
                'assets':{'id','batch_id','barcode','category','model','owner','location','status','note','created_at','updated_at','active'},
                'batches':{'id','label','category','model','source','note','created_at','active'},
                'events':{'id','at','action','summary','reason','before_json','after_json','reversible','undo_of'}}
            for table,columns in required.items():
                present={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                if not columns<=present:
                    raise ValueError('文件不是兼容的物料台账数据库。')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('数据库关联校验未通过。')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return dict(path=str(path),on_account=db.execute("SELECT count(*) FROM assets WHERE active=1 AND status<>'已转出'").fetchone()[0],
                logs=db.execute('SELECT count(*) FROM events').fetchone()[0],
                last_log=db.execute('SELECT max(at) FROM events').fetchone()[0] or '无日志',
                supplies=db.execute('SELECT count(*) FROM supplies WHERE active=1').fetchone()[0] if 'supplies' in tables else 0)
    except sqlite3.DatabaseError as exc:
        raise ValueError('无法读取该数据库，请确认选择的是本工具的 .sqlite3 文件。') from exc


def import_database(current, source):
    source=Path(source).resolve()
    if source==current.path.resolve():
        raise ValueError('选择的就是当前数据库，无需导入。')
    report=inspect_database(source)
    with tempfile.TemporaryDirectory(prefix='ledger-import-',dir=current.directory.parent) as folder:
        staged=Path(folder)/'ledger.sqlite3'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
            with closing(sqlite3.connect(staged)) as dst:
                src.backup(dst)
        inspect_database(staged)
        # Validate additive migration before touching the current database.
        migrated=Store(folder)
        migrated.close()
        backup=current.backup()
        directory=current.directory
        path=current.path
        current.close()
        new=None
        try:
            os.replace(staged,path)
            new=Store(directory)
            with new.db:
                new._event('导入台账',f"导入 {report['on_account']} 件挂账、{report['supplies']} 种非挂账物品、{report['logs']} 条原日志",
                    f'来源：{source}；导入前台账备份：{backup}',{'assets':[],'batches':[]},{'assets':[],'batches':[]},False)
            return new,backup
        except Exception:
            if new is not None:
                new.close()
            shutil.copy2(backup,path)
            # Reconnect the original object so the UI remains usable after failure.
            current.db=sqlite3.connect(path,timeout=10)
            current.db.row_factory=sqlite3.Row
            current.db.execute('PRAGMA foreign_keys=ON')
            raise
