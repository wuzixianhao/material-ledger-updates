"""Transactional offline material ledger, standard library only."""
import csv
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from supplies import SuppliesMixin, business_time
from server_inventory import ServerInventory

ASSET_TIMES=('received_at','lent_at','recovered_at','transferred_at','occurred_at')
PLATFORM_FIELDS=('puid','sn','description','platform_note')

STATUSES = ("在用", "在库", "借出", "已取回", "待确认", "已转出")
CATEGORIES = ("内存", "硬盘", "CPU", "电源", "板卡", "其他", "主板", "背板", "riser", "BMC")


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_codes(text):
    codes = [s.upper() for s in re.split(r"[\s,，;；、]+", text.strip()) if s]
    if any(not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,127}", s) for s in codes):
        raise ValueError("条码只能包含英文字母、数字和 . _ / -；请逐个填写，不能填写 ~ 范围。")
    if len(set(codes)) != len(codes):
        raise ValueError("本次输入有重复条码，请检查后再保存。")
    return codes


class Store(SuppliesMixin,ServerInventory):
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ledger.sqlite3"
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        # Existing user data is backed up before additive schema upgrades.
        existing={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'assets' in existing and 'supplies' not in existing:
            self.backup(self.directory / ('before-upgrade-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS batches (
          id TEXT PRIMARY KEY, label TEXT NOT NULL, category TEXT NOT NULL,
          model TEXT NOT NULL, source TEXT NOT NULL, note TEXT NOT NULL,
          created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
          barcode TEXT COLLATE NOCASE, category TEXT NOT NULL, model TEXT NOT NULL,
          owner TEXT NOT NULL, location TEXT NOT NULL, status TEXT NOT NULL,
          note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1);
        CREATE UNIQUE INDEX IF NOT EXISTS unique_barcode ON assets(barcode COLLATE NOCASE)
          WHERE barcode IS NOT NULL AND active=1;
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          action TEXT NOT NULL, summary TEXT NOT NULL, reason TEXT NOT NULL,
          before_json TEXT NOT NULL, after_json TEXT NOT NULL,
          reversible INTEGER NOT NULL DEFAULT 1, undo_of INTEGER REFERENCES events(id));
        CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT, '日志不可修改'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT, '日志不可删除'); END;
        """)
        self.setup_supplies()
        self.setup_servers()
        if 'puid' not in {r[1] for r in self.db.execute('PRAGMA table_info(assets)')}:
            self.backup(self.directory / ('before-platform-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
            with self.db:
                for key in PLATFORM_FIELDS:
                    self.db.execute(f"ALTER TABLE assets ADD COLUMN {key} TEXT NOT NULL DEFAULT ''")
        if 'received_at' not in {r[1] for r in self.db.execute('PRAGMA table_info(assets)')}:
            self.backup(self.directory / ('before-asset-times-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
            with self.db:
                for key in ASSET_TIMES:
                    self.db.execute(f"ALTER TABLE assets ADD COLUMN {key} TEXT NOT NULL DEFAULT ''")
        if 'occurred_at' not in {r[1] for r in self.db.execute('PRAGMA table_info(events)')}:
            self.db.execute("ALTER TABLE events ADD COLUMN occurred_at TEXT NOT NULL DEFAULT ''")
            self.db.commit()

    def close(self):
        self.db.close()

    def backup(self, target=None):
        if target is None:
            folder = self.directory / "backups"
            folder.mkdir(exist_ok=True)
            target = folder / ("ledger-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("备份不能覆盖正在使用的数据库。")
        with closing(sqlite3.connect(target)) as dest:
            self.db.backup(dest)
        return target

    def daily_backup(self):
        if not self.db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            return
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / ("daily-" + datetime.now().strftime("%Y%m%d") + ".sqlite3")
        if not path.exists():
            self.backup(path)

    def _get(self, table, ids):
        result = []
        for ident in ids:
            row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise ValueError("记录不存在，请刷新后重试。")
            result.append(dict(row))
        return result

    def _save_rows(self, table, rows):
        for row in rows:
            cols = list(row)
            self.db.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                f"ON CONFLICT(id) DO UPDATE SET {','.join(c+'=excluded.'+c for c in cols if c != 'id')}",
                [row[c] for c in cols])

    def _event(self, action, summary, reason, before, after, reversible=True, undo_of=None, occurred_at=''):
        self.db.execute("""INSERT INTO events
          (at,action,summary,reason,before_json,after_json,reversible,undo_of,occurred_at)
          VALUES(?,?,?,?,?,?,?,?,?)""", (now(), action, summary, reason,
          json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
          int(reversible), undo_of,business_time(occurred_at)))

    def receive(self, category, model, quantity, codes, location="待确认", status="在库",
                owner="我", source="", note="", label="", occurred_at=''):
        effective=business_time(occurred_at)
        category, model = category.strip(), model.strip()
        if not category or status not in STATUSES or status == "已转出":
            raise ValueError("请选择类别和有效的入账状态。")
        if not isinstance(quantity, int) or not 1 <= quantity <= 10000:
            raise ValueError("数量应为 1～10000 的整数。")
        codes = parse_codes("\n".join(codes))
        if len(codes) > quantity:
            raise ValueError("条码数量超过入账数量，请修改数量或删去多余条码。")
        stamp = now()
        batch = dict(id=uuid.uuid4().hex, label=label.strip() or f"{category} · {model or '型号待补'}",
          category=category, model=model, source=source.strip(), note=note.strip(), created_at=stamp, active=1)
        rows = [dict(id=uuid.uuid4().hex, batch_id=batch["id"], barcode=codes[i] if i < len(codes) else None,
          category=category, model=model, owner=owner.strip() or "我", location=location.strip() or "待确认",
          status=status, note=note.strip(), created_at=stamp, updated_at=stamp, active=1) for i in range(quantity)]
        for row in rows:
            row.update({k:'' for k in ASSET_TIMES})
            row.update(received_at=effective,occurred_at=effective)
        self.daily_backup()
        try:
            with self.db:
                self._save_rows("batches", [batch])
                self._save_rows("assets", rows)
                self._event("新增挂账", f"{category} {quantity} 件，已录 {len(codes)} 个条码", source,
                  {"assets": [], "batches": []}, {"assets": rows, "batches": [batch]},occurred_at=effective)
        except sqlite3.IntegrityError as exc:
            raise ValueError("条码已存在，本次未入账。请搜索条码确认是否属于归还或重新挂账。") from exc
        return batch["id"]

    def fill_codes(self, batch_id, codes, occurred_at=''):
        effective=business_time(occurred_at)
        codes = parse_codes("\n".join(codes))
        if not codes:
            raise ValueError("请至少输入一个条码。")
        self.daily_backup()
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                before = [dict(r) for r in self.db.execute("""SELECT * FROM assets
                  WHERE batch_id=? AND barcode IS NULL AND active=1 AND status<>'已转出'
                  ORDER BY rowid LIMIT ?""", (batch_id, len(codes)))]
                if len(before) != len(codes):
                    raise ValueError("输入数量超过这个批次尚未补码的在账数量。")
                signatures = {(r['category'], r['model'], r['owner'], r['location'], r['status'], r['note'])
                  for r in self.db.execute("""SELECT * FROM assets WHERE batch_id=?
                    AND barcode IS NULL AND active=1 AND status<>'已转出'""", (batch_id,))}
                if len(signatures) > 1:
                    raise ValueError("此批未补码物料的位置或状态不同，请在台账中双击对应物料，逐件补条码。")
                after = [dict(r, barcode=code, updated_at=now(),occurred_at=effective) for r, code in zip(before, codes)]
                self._save_rows("assets", after)
                self._event("补录条码", f"补录 {len(codes)} 个条码；在账数量不变", "",
                  {"assets": before, "batches": []}, {"assets": after, "batches": []},occurred_at=effective)
        except sqlite3.IntegrityError as exc:
            raise ValueError("条码已存在，本次补录全部取消。") from exc

    def update(self, ids, changes, action, reason="", occurred_at=''):
        effective=business_time(occurred_at)
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise ValueError("请先选择物料。")
        allowed = {"barcode", "category", "model", "owner", "location", "status", "note", "received_at"}
        if not changes or set(changes) - allowed:
            raise ValueError("没有有效的修改内容。")
        changes = {k: v.strip() if isinstance(v, str) else v for k, v in changes.items()}
        if 'received_at' in changes:
            changes['received_at']=business_time(changes['received_at']) if changes['received_at'] else ''
        if "barcode" in changes:
            if len(ids) != 1:
                raise ValueError("条码只能逐件编辑；批量补录请到待补条码页。")
            parsed = parse_codes(changes["barcode"] or "")
            if len(parsed) > 1:
                raise ValueError("一件物料只能填写一个条码。")
            changes["barcode"] = parsed[0] if parsed else None
        for key in ("category", "owner", "location"):
            if key in changes and not changes[key]:
                raise ValueError("类别、挂账归属和位置不能留空；未知请填待确认。")
        if "status" in changes and changes["status"] not in STATUSES:
            raise ValueError("状态不正确。")
        self.daily_backup()
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                before = self._get("assets", ids)
                if any(not r["active"] for r in before):
                    raise ValueError("所选记录已撤销，请刷新。")
                after = [dict(r, **changes) for r in before]
                if all(a == b for a, b in zip(before, after)):
                    raise ValueError("内容没有变化，无需保存。")
                for r in after:
                    if r['received_at'] and effective<r['received_at']:
                        raise ValueError('操作时间不能早于挂账时间。')
                    if r['received_at'] and any(r[k] and r[k]<r['received_at'] for k in ('lent_at','recovered_at','transferred_at')):
                        raise ValueError('挂账时间不能晚于已有的借还时间。')
                    if action=='归还' and r['lent_at'] and effective<r['lent_at']:
                        raise ValueError('收回时间不能早于借出时间。')
                    key={'借出':'lent_at','归还':'recovered_at','转出挂账':'transferred_at'}.get(action)
                    if key:
                        r[key]=effective
                    r['occurred_at']=effective
                    r["updated_at"] = now()
                self._save_rows("assets", after)
                self._event(action, f"{action} · {len(ids)} 件", reason,
                  {"assets": before, "batches": []}, {"assets": after, "batches": []},occurred_at=effective)
        except sqlite3.IntegrityError as exc:
            raise ValueError("条码已存在，修改未保存。") from exc

    def undo(self, event_id, reason):
        if not reason.strip():
            raise ValueError("请填写撤销原因，便于以后回溯。")
        self.daily_backup()
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                event = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                if not event or not event["reversible"] or self.db.execute(
                  "SELECT 1 FROM events WHERE undo_of=?", (event_id,)).fetchone():
                    raise ValueError("这条记录不能撤销，或已经撤销。")
                before, after = json.loads(event["before_json"]), json.loads(event["after_json"])
                # Old preview snapshots predate the personal status field.
                for snapshot in (before,after):
                    for row in snapshot.get('assets',[]):
                        for key in PLATFORM_FIELDS:
                            row.setdefault(key,'')
                        for key in ASSET_TIMES:
                            row.setdefault(key,'')
                    for row in snapshot.get('supplies',[]):
                        row.setdefault('status','待确认')
                        row.setdefault('borrowed_at','')
                        row.setdefault('returned_at','')
                restored = {"batches": [], "assets": [], "supplies": [], "supply_loans": [], "servers": []}
                for table in restored:
                    current = self._get(table, [r["id"] for r in after.get(table,[])])
                    if current != after.get(table,[]):
                        raise ValueError("相关物料已有后续变动。请先撤销后续变动，或编辑物料进行更正。")
                    old = {r["id"]: r for r in before.get(table,[])}
                    restored[table] = [old.get(r["id"], dict(r, active=0)) for r in after.get(table,[])]
                    self._save_rows(table, restored[table])
                self._event("撤销操作", f"撤销日志 #{event_id}：{event['summary']}", reason,
                  after, restored, False, event_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("撤销会与现有条码冲突，未执行。请先检查后续操作。") from exc

    def assets(self, query="", category="全部类别", status="全部状态", scope="在账"):
        sql = "SELECT a.*, b.label AS batch_label FROM assets a JOIN batches b ON b.id=a.batch_id WHERE a.active=1"
        args = []
        if scope == "在账":
            sql += " AND a.status<>'已转出'"
        elif scope == "已转出":
            sql += " AND a.status='已转出'"
        if category != "全部类别":
            sql += " AND a.category=?"
            args.append(category)
        if status != "全部状态":
            sql += " AND a.status=?"
            args.append(status)
        if query.strip():
            terms=list(dict.fromkeys(t for t in re.split(r'[\s,，;；、]+',query.strip()) if t))
            if len(terms)>1000:
                raise ValueError('一次最多搜索1000项。')
            haystack="lower(coalesce(a.barcode,'') || ' ' || a.category || ' ' || a.model || ' ' || a.owner || ' ' || a.location || ' ' || a.note || ' ' || a.platform_note || ' ' || a.sn || ' ' || a.puid || ' ' || b.label)"
            sql+=f' AND EXISTS (SELECT 1 FROM json_each(?) term WHERE instr({haystack}, lower(term.value))>0)'
            args.append(json.dumps(terms,ensure_ascii=False))
        sql += " ORDER BY a.created_at DESC, a.rowid"
        return [dict(r) for r in self.db.execute(sql, args)]

    def categories(self):
        return list(dict.fromkeys(CATEGORIES+tuple(r[0] for r in self.db.execute('SELECT DISTINCT category FROM assets WHERE active=1 ORDER BY category'))))

    def batches(self):
        return [dict(r) for r in self.db.execute("""SELECT b.*, count(a.id) AS total,
          sum(CASE WHEN a.status<>'已转出' THEN 1 ELSE 0 END) AS on_account,
          sum(CASE WHEN a.status<>'已转出' AND a.barcode IS NULL THEN 1 ELSE 0 END) AS pending
          FROM batches b JOIN assets a ON a.batch_id=b.id AND a.active=1
          WHERE b.active=1 GROUP BY b.id ORDER BY b.created_at DESC, b.rowid""")]

    def stats(self):
        return dict(self.db.execute("""SELECT count(*) AS total,
          coalesce(sum(barcode IS NULL),0) AS pending, coalesce(sum(status='借出'),0) AS lent,
          coalesce(sum(location='待确认' OR status='待确认' OR model='' OR instr(model,'待确认')>0),0) AS uncertain
          FROM assets WHERE active=1 AND status<>'已转出'""").fetchone())

    def history(self, query=""):
        events = [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC")]
        if query.strip():
            q = query.strip().lower()
            events = [e for e in events if q in " ".join(str(v) for v in e.values()).lower()]
        undone = {r[0] for r in self.db.execute("SELECT undo_of FROM events WHERE undo_of IS NOT NULL")}
        for event in events:
            event["undone"] = event["id"] in undone
        return events

    def export_csv(self, path, rows):
        keys = ("barcode", "category", "model", "owner", "location", "status", "batch_label", "note", "created_at", "updated_at", "id")
        headers = ("条码", "类别", "型号", "挂账归属", "位置/使用人", "状态", "批次", "备注", "登记时间", "最后变动", "内部编号")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                values = [str(row.get(k) or "") for k in keys]
                writer.writerow(["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in values])

    def export_history(self, path):
        with open(path, "w", encoding="utf-8") as f:
            for row in reversed(self.history()):
                row["before"] = json.loads(row.pop("before_json"))
                row["after"] = json.loads(row.pop("after_json"))
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
