"""Read website exports and reconcile a complete personal ledger, atomically."""
import csv
import json
import posixpath
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from store import now, ASSET_TIMES, PLATFORM_FIELDS, parse_codes

HEADERS={'资产分类':'category','资产编码':'barcode','PUID':'puid','设备序列号（SN）':'sn',
         '型号':'model','详细描述':'description','资产使用备注':'platform_note'}
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def read_export(path):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        for encoding in ('utf-8-sig','gb18030'):
            try:
                with path.open(encoding=encoding,newline='') as f:
                    return {'CSV':list(csv.reader(f))}
            except UnicodeDecodeError:
                pass
        raise ValueError('CSV 编码无法识别。')
    if path.suffix.lower()!='.xlsx':
        raise ValueError('支持 .xlsx 和 .csv；旧版 .xls 请先用 Excel/WPS 另存为 .xlsx。')
    try:
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>100_000_000:
                raise ValueError('表格过大，请导出个人名下清单。')
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                strings=[''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
            rel={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
            result={}
            for sheet in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',NS):
                rid=sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
                target=rel[rid]
                target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                rows=[]
                for row in ET.fromstring(z.read(target)).findall('s:sheetData/s:row',NS):
                    values=[]
                    for cell in row.findall('s:c',NS):
                        letters=''.join(c for c in cell.attrib['r'] if c.isalpha())
                        index=0
                        for c in letters:
                            index=index*26+ord(c.upper())-64
                        while len(values)<index:
                            values.append('')
                        value=cell.findtext('s:v','',NS)
                        if cell.attrib.get('t')=='s':
                            value=strings[int(value)]
                        elif cell.attrib.get('t')=='inlineStr':
                            value=''.join(cell.find('s:is',NS).itertext())
                        if cell.find('s:f',NS) is not None:
                            value='[公式不支持]'
                        values[index-1]=value
                    rows.append(values)
                result[sheet.attrib['name']]=rows
            return result
    except (zipfile.BadZipFile,KeyError,ET.ParseError,IndexError) as exc:
        raise ValueError('无法读取 Excel，请用 Excel/WPS 重新保存为 .xlsx。') from exc


def parse_sheet(rows):
    def clean(v):
        return str(v or '').strip().replace('\n','').replace('\r','').replace(' ','').replace('(', '（').replace(')','）')
    header=None
    for index,row in enumerate(rows[:50]):
        cells=[clean(v) for v in row]
        if '资产编码' in cells and '资产分类' in cells:
            header=index
            break
    if header is None:
        raise ValueError('前50行未找到“资产分类”和“资产编码”表头。')
    positions={}
    for i,v in enumerate(rows[header]):
        key=HEADERS.get(clean(v))
        if key:
            if key in positions:
                raise ValueError('存在重复表头：'+str(v))
            positions[key]=i
    missing=set(HEADERS.values())-set(positions)
    if missing:
        raise ValueError('缺少列：'+'、'.join(k for k,v in HEADERS.items() if v in missing))
    items=[]
    seen=set()
    for index,row in enumerate(rows[header+1:],header+2):
        if not any(str(v or '').strip() for v in row):
            continue
        item={k:str(row[i] or '').strip() if i<len(row) else '' for k,i in positions.items()}
        if not item['barcode'] or not item['category']:
            raise ValueError(f'第 {index} 行缺少资产编码或资产分类，未导入。')
        codes=parse_codes(item['barcode'])
        if len(codes)!=1:
            raise ValueError(f'第 {index} 行资产编码格式无效。')
        item['barcode']=codes[0]
        if item['barcode'] in seen:
            raise ValueError(f"第 {index} 行资产编码重复：{item['barcode']}")
        seen.add(item['barcode'])
        items.append(item)
    if not items:
        raise ValueError('表格没有有效资产，不能同步空清单。')
    return items


def fingerprint(store):
    return json.dumps([dict(r) for r in store.db.execute('SELECT * FROM assets ORDER BY id')],sort_keys=True,ensure_ascii=False)


def plan_sync(store,items):
    current=store.assets(scope='全部')
    by_code={r['barcode']:r for r in current if r['barcode']}
    codes={r['barcode'] for r in items}
    plan=dict(added=[],removed=[],changed=[],unchanged=[],unidentified=[],items=items,fingerprint=fingerprint(store))
    fields=('category','model')+PLATFORM_FIELDS
    for item in items:
        old=by_code.get(item['barcode'])
        if old is None or old['status']=='已转出':
            plan['added'].append(item)
        elif any(old[k]!=item[k] for k in fields):
            plan['changed'].append(dict(item,old=old))
        else:
            plan['unchanged'].append(item)
    for row in current:
        if row['status']=='已转出':
            continue
        if not row['barcode']:
            plan['unidentified'].append(row)
        elif row['barcode'] not in codes:
            plan['removed'].append(row)
    return plan


def apply_sync(store,plan,source,include_unidentified=False):
    if plan['unidentified'] and not include_unidentified:
        raise ValueError('存在未补条码记录，请确认完整网站清单取代这些数量记录后再同步。')
    backup=store.backup()
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        if fingerprint(store)!=plan['fingerprint']:
            raise ValueError('预览后台账已有变化，请重新导入对账。')
        before=[]
        after=[]
        batch=dict(id=uuid.uuid4().hex,label='网站对账 · '+now(),category='网站导入',model='',source=str(source),note='',created_at=now(),active=1)
        by_code={r['barcode']:dict(r) for r in store.db.execute('SELECT * FROM assets WHERE active=1 AND barcode IS NOT NULL')}
        for item in plan['items']:
            old=by_code.get(item['barcode'])
            if old:
                row=dict(old,**item)
                if old['status']=='已转出':
                    row.update(status='待确认',owner='我',location='待确认')
                if row==old:
                    continue
                before.append(old)
            else:
                row=dict(id=uuid.uuid4().hex,batch_id=batch['id'],owner='我',location='待确认',status='待确认',note='',created_at=now(),active=1,
                         **{k:'' for k in ASSET_TIMES},**item)
            row.update(updated_at=now(),occurred_at=now())
            after.append(row)
        removed=plan['removed']+(plan['unidentified'] if include_unidentified else [])
        for item in removed:
            old=dict(store.db.execute('SELECT * FROM assets WHERE id=?',(item['id'],)).fetchone())
            before.append(old)
            # The export gives membership, not the actual handover date.
            after.append(dict(old,status='已转出',updated_at=now(),occurred_at=now()))
        if not after:
            return backup
        new_batch=any(r['batch_id']==batch['id'] for r in after)
        store._save_rows('batches',[batch] if new_batch else [])
        store._save_rows('assets',after)
        store._event('网站Excel对账',f"新增 {len(plan['added'])}，减少 {len(removed)}，更新 {len(plan['changed'])}",
                     f'来源：{source}；备份：{backup}；以本人完整网站清单为准',
                     {'assets':before,'batches':[]},{'assets':after,'batches':[batch] if new_batch else []})
    return backup
