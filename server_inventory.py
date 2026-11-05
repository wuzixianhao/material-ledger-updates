"""Server register over the existing ledger location field."""
import sqlite3
import uuid


class ServerInventory:
    def setup_servers(self):
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS servers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL,
                note TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
            for key in ('name','location'):
                self.db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS server_{key} ON servers({key} COLLATE NOCASE) WHERE active=1')

    def servers(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM servers WHERE active=1 ORDER BY name COLLATE NOCASE')]

    def save_server(self,name,location,note='',ident=None):
        name,location,note=name.strip(),location.strip(),note.strip()
        if not name or not location:
            raise ValueError('请填写服务器名称和台账位置。')
        before=self._get('servers',[ident]) if ident else []
        if ident and (not before or not before[0]['active'] or before[0]['location']!=location):
            raise ValueError('服务器不存在，或其台账位置已固定。')
        row=dict(id=ident or uuid.uuid4().hex,name=name,location=location,note=note,active=1)
        if before==[row]:
            return row['id']
        self.daily_backup()
        try:
            with self.db:
                self._save_rows('servers',[row])
                self._event('编辑服务器' if ident else '登记服务器',name,'',
                    {'assets':[],'servers':before},{'assets':[],'servers':[row]})
        except sqlite3.IntegrityError as exc:
            raise ValueError('服务器名称或台账位置已被使用。') from exc
        return row['id']

    def server_items(self,server):
        location=server['location'].casefold()
        hardware=[r for r in self.assets() if r['location'].casefold()==location]
        supplies=[r for r in self.supply_rows() if r['quantity']>0 and r['location'].casefold()==location]
        return hardware,supplies

    def assign_server_barcodes(self,server,text):
        from store import parse_codes
        codes=parse_codes(text)
        if not codes:
            raise ValueError('请至少输入一个条码。')
        assets={r['barcode'].upper():r for r in self.assets() if r['barcode']}
        missing=[c for c in codes if c not in assets]
        if missing:
            raise ValueError('以下条码未在当前在账记录中找到：'+'、'.join(missing))
        if any(assets[c]['status']=='借出' for c in codes):
            raise ValueError('有物料仍在借出，请先办理收回后再分配。')
        ids=[assets[c]['id'] for c in codes if assets[c]['location']!=server['location'] or assets[c]['status']!='在用']
        if ids:
            self.update(ids,{'location':server['location'],'status':'在用'},'分配到服务器',server['name'])
        return len(ids)
