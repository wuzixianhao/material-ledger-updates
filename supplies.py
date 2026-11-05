"""Quantity-tracked physical items outside the company's asset ledger."""
import uuid
from datetime import datetime


def stamp():
    return datetime.now().astimezone().isoformat(timespec='microseconds')


def business_time(value=''):
    value=value.strip()
    if not value:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for pattern in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%Y-%m-%d'):
        try:
            return datetime.strptime(value,pattern).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    raise ValueError('时间格式请填 2026-09-08 或 2026-09-08 14:30；留空使用当前时间。')


def integer(value, minimum=0):
    if isinstance(value,bool):
        raise ValueError('数量必须是整数。')
    try:
        n=int(str(value))
    except (ValueError,TypeError):
        raise ValueError('数量必须是整数。')
    if n<minimum or n>1000000:
        raise ValueError(f'数量应为 {minimum}～1000000 的整数。')
    return n


class SuppliesMixin:
    def setup_supplies(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS supplies (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, spec TEXT NOT NULL, unit TEXT NOT NULL,
          location TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
          threshold INTEGER NOT NULL DEFAULT 0 CHECK(threshold>=0), note TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS supply_loans (
          id TEXT PRIMARY KEY, supply_id TEXT NOT NULL REFERENCES supplies(id),
          person TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
          remaining INTEGER NOT NULL CHECK(remaining>=0 AND remaining<=quantity),
          note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1);
        ''')
        if 'status' not in {r[1] for r in self.db.execute('PRAGMA table_info(supplies)')}:
            self.backup(self.directory / ('before-personal-update-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
            self.db.execute("ALTER TABLE supplies ADD COLUMN status TEXT NOT NULL DEFAULT '待确认'")
            self.db.commit()
        columns={r[1] for r in self.db.execute('PRAGMA table_info(supplies)')}
        if 'borrowed_at' not in columns:
            self.backup(self.directory / ('before-time-update-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
            with self.db:
                self.db.execute("ALTER TABLE supplies ADD COLUMN borrowed_at TEXT NOT NULL DEFAULT ''")
                self.db.execute("ALTER TABLE supplies ADD COLUMN returned_at TEXT NOT NULL DEFAULT ''")

    def supply_rows(self, query='', low_only=False):
        rows=[dict(r) for r in self.db.execute('''SELECT s.*,
          coalesce((SELECT sum(l.remaining) FROM supply_loans l WHERE l.supply_id=s.id AND l.active=1),0) AS lent
          FROM supplies s WHERE s.active=1 ORDER BY s.name,s.spec,s.location''')]
        if query.strip():
            q=query.strip().lower()
            rows=[r for r in rows if q in ' '.join(str(r[k]) for k in ('name','spec','location','note')).lower()]
        if low_only:
            rows=[r for r in rows if r['threshold']>0 and r['quantity']<=r['threshold']]
        return rows

    def supply_loan_rows(self):
        return [dict(r) for r in self.db.execute('''SELECT l.*,s.name,s.spec,s.unit,s.location
          FROM supply_loans l JOIN supplies s ON s.id=l.supply_id
          WHERE l.active=1 AND s.active=1 AND l.remaining>0 ORDER BY l.created_at DESC''')]

    def add_supply(self,name,spec,unit,location,quantity,threshold=0,note='',status='闲置',borrowed_at=''):
        if status not in ('在用','闲置','待确认'):
            raise ValueError('请选择在用、闲置或待确认。')
        if not name.strip() or not unit.strip() or not location.strip():
            raise ValueError('请填写名称、单位和存放位置。')
        row=dict(id=uuid.uuid4().hex,name=name.strip(),spec=spec.strip(),unit=unit.strip(),
          location=location.strip(),quantity=integer(quantity),threshold=integer(threshold),note=note.strip(),
          created_at=stamp(),updated_at=stamp(),active=1,status=status,borrowed_at=business_time(borrowed_at),returned_at='')
        self.daily_backup()
        with self.db:
            self._save_rows('supplies',[row])
            self._event('非挂账·新增',f"{row['name']} {row['quantity']}{row['unit']}",note,
                {'assets':[],'batches':[],'supplies':[]}, {'assets':[],'batches':[],'supplies':[row]},occurred_at=row['borrowed_at'])
        return row['id']

    def personal_supply_change(self,ident,action,quantity=0,reason='',changes=None,returned_at=''):
        self.daily_backup()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            before=self._get('supplies',[ident])[0]
            if not before['active']:
                raise ValueError('记录已撤销，请刷新。')
            after=dict(before)
            if action=='归还':
                after['returned_at']=business_time(returned_at)
                if before['borrowed_at'] and after['returned_at']<before['borrowed_at']:
                    raise ValueError('归还时间不能早于借用时间。')
                n=integer(quantity,1)
                if n>before['quantity']:
                    raise ValueError('归还数量不能超过当前持有数量。')
                after['quantity']-=n
                if after['quantity']==0:
                    after['status']='已归还'
            elif action=='修改':
                changes=dict(changes or {})
                if set(changes)-{'name','spec','location','note','status','borrowed_at'}:
                    raise ValueError('无效修改。')
                if 'borrowed_at' in changes:
                    changes['borrowed_at']=business_time(changes['borrowed_at']) if changes['borrowed_at'].strip() else before['borrowed_at']
                    if before['returned_at'] and changes['borrowed_at']>before['returned_at']:
                        raise ValueError('借用时间不能晚于已记录的归还时间。')
                if changes.get('status',before['status']) not in ('在用','闲置','待确认','已归还'):
                    raise ValueError('状态无效。')
                if before['quantity']>0 and changes.get('status')=='已归还':
                    raise ValueError('请使用归还操作扣减数量。')
                if before['quantity']==0 and changes.get('status',before['status'])!=before['status']:
                    raise ValueError('没有持有数量，重新领到物品请新增记录。')
                for key in ('name','location'):
                    if key in changes and not changes[key].strip():
                        raise ValueError('名称和位置不能为空。')
                after.update(changes)
            else:
                raise ValueError('未知操作。')
            if after==before:
                raise ValueError('内容没有变化。')
            after['updated_at']=stamp()
            self._save_rows('supplies',[after])
            self._event('非挂账·'+action,f"{before['name']} · 个人持有 {before['quantity']} → {after['quantity']} {before['unit']}",reason,
                {'assets':[],'batches':[],'supplies':[before]}, {'assets':[],'batches':[],'supplies':[after]},occurred_at=after['returned_at'] if action=='归还' else '')

    def supply_change(self,ident,action,quantity=0,person='',reason='',changes=None):
        self.daily_backup()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            before=self._get('supplies',[ident])[0]
            if not before['active']:
                raise ValueError('此记录已经撤销，请刷新。')
            after=dict(before)
            loans=[]
            n=integer(quantity,0 if action in ('盘点修正','编辑资料') else 1)
            if action=='入库':
                after['quantity']+=n
            elif action in ('借出','耗用 / 送出'):
                if n>before['quantity']:
                    raise ValueError('操作数量超过当前可用数量，未保存。')
                after['quantity']-=n
                if action=='借出':
                    if not person.strip():
                        raise ValueError('借出必须填写借用人或机器去向。')
                    loans=[dict(id=uuid.uuid4().hex,supply_id=ident,person=person.strip(),quantity=n,
                      remaining=n,note=reason.strip(),created_at=stamp(),updated_at=stamp(),active=1)]
                elif not reason.strip():
                    raise ValueError('请填写耗用 / 送出说明。')
            elif action=='盘点修正':
                if not reason.strip():
                    raise ValueError('盘点修正必须填写差异原因。')
                after['quantity']=n
            elif action=='编辑资料':
                changes=dict(changes or {})
                if not changes or set(changes)-{'name','spec','unit','location','threshold','note'}:
                    raise ValueError('无效的资料修改。')
                if 'threshold' in changes:
                    changes['threshold']=integer(changes['threshold'])
                for key in ('name','unit','location'):
                    if key in changes and not changes[key].strip():
                        raise ValueError('名称、单位、位置不能为空。')
                if 'unit' in changes and changes['unit']!=before['unit'] and (before['quantity'] or self.db.execute(
                    'SELECT 1 FROM supply_loans WHERE supply_id=? AND remaining>0 AND active=1',(ident,)).fetchone()):
                    raise ValueError('仍有库存或未还记录，不能直接改变计量单位。请新增对应单位的物品记录。')
                after.update(changes)
            else:
                raise ValueError('未知操作。')
            if after==before and not loans:
                raise ValueError('内容没有变化。')
            after['updated_at']=stamp()
            self._save_rows('supplies',[after])
            self._save_rows('supply_loans',loans)
            self._event('非挂账·'+action,f"{before['name']} · 可用 {before['quantity']} → {after['quantity']} {before['unit']}",
              ('去向：'+person+'；' if person else '')+reason,
              {'assets':[],'batches':[],'supplies':[before],'supply_loans':[]},
              {'assets':[],'batches':[],'supplies':[after],'supply_loans':loans})

    def return_supply(self,loan_id,quantity,reason=''):
        n=integer(quantity,1)
        self.daily_backup()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            loan=self._get('supply_loans',[loan_id])[0]
            if not loan['active'] or n>loan['remaining']:
                raise ValueError('收回数量超过这条借出记录尚未归还的数量。')
            item=self._get('supplies',[loan['supply_id']])[0]
            after=dict(item,quantity=item['quantity']+n,updated_at=stamp())
            updated=dict(loan,remaining=loan['remaining']-n,updated_at=stamp())
            self._save_rows('supplies',[after])
            self._save_rows('supply_loans',[updated])
            self._event('非挂账·借出收回',f"{item['name']} · 从 {loan['person']} 收回 {n}{item['unit']}",reason,
              {'assets':[],'batches':[],'supplies':[item],'supply_loans':[loan]},
              {'assets':[],'batches':[],'supplies':[after],'supply_loans':[updated]})
