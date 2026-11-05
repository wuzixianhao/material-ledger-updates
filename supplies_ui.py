"""Personal belongings UI."""
import tkinter as tk
from tkinter import ttk, messagebox
from ui import Button


class SuppliesUI:
    def build_supplies(self):
        top=ttk.Frame(self.supply_tab)
        top.pack(fill='x',pady=(0,12))
        self.supply_query=tk.StringVar()
        entry=ttk.Entry(top,textvariable=self.supply_query,width=30)
        entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda e:self.refresh_supplies())
        Button(top,text='搜索',command=self.refresh_supplies).pack(side='left',padx=8)
        self.supply_scope=tk.StringVar(value='当前持有')
        scope=ttk.Combobox(top,textvariable=self.supply_scope,values=['当前持有','已归还','全部记录'],state='readonly',width=10)
        scope.pack(side='left',padx=(0,12))
        scope.bind('<<ComboboxSelected>>',lambda e:self.refresh_supplies())
        Button(top,text='＋ 新增物品',style='Accent.TButton',command=self.add_supply_dialog).pack(side='right')
        self.supply_summary=tk.StringVar()
        ttk.Label(self.supply_tab,textvariable=self.supply_summary,style='Muted.TLabel').pack(anchor='w',pady=(0,12))
        toolbar=ttk.Frame(self.supply_tab)
        toolbar.pack(fill='x',pady=(0,12))
        for action in ('归还','修改'):
            Button(toolbar,text=action,command=lambda a=action:self.supply_dialog(a)).pack(side='left',padx=(0,8))
        Button(toolbar,text='历史记录',command=self.supply_history).pack(side='left')
        Button(toolbar,text='查看详情',command=self.supply_detail).pack(side='left',padx=8)
        self.supply_tree=self.tree(self.supply_tab,[('name','名称'),('spec','规格'),('quantity','持有数量'),
            ('status','状态'),('location','位置 / 使用机器'),('date','借用日期')],[170,170,95,95,200,125],height=9)
        self.supply_tree.bind('<Double-1>',lambda e:self.supply_detail())

    def refresh_supplies(self):
        if not hasattr(self,'supply_tree'):
            return
        all_rows=self.store.supply_rows()
        rows=self.store.supply_rows(self.supply_query.get())
        scope=self.supply_scope.get()
        if scope=='当前持有':
            rows=[r for r in rows if r['quantity']>0 or r['lent']>0]
        elif scope=='已归还':
            rows=[r for r in rows if r['status']=='已归还' and not r['lent']]
        self.supply_items={r['id']:r for r in rows}
        held=sum(r['quantity']>0 or r['lent']>0 for r in all_rows)
        self.supply_summary.set(f'我的非挂账物品 · 当前持有 {held} 条记录 · 不计入挂账总数')
        self.supply_tree.delete(*self.supply_tree.get_children())
        for r in rows:
            note=r['note']
            if r['lent']:
                note+=f" （旧版借出未收回 {r['lent']}{r['unit']}，详见历史）"
            self.supply_tree.insert('','end',iid=r['id'],values=[r['name'],r['spec'],f"{r['quantity']} {r['unit']}",r['status'],r['location'],r['borrowed_at'][:10] or '未记录'])

    def add_supply_dialog(self,location='',status='闲置'):
        f=self.supply_form_class(self,'新增我的物品','记录本次领到或自己持有的物品，无需条码。不同状态或位置可分别记录。')
        for key,label,value in [('name','名称 *',''),('spec','规格 / 长度 / 接口',''),('quantity','本次新增数量 *','1'),
            ('unit','单位 *','根'),('location','位置 / 使用机器 *',location)]:
            f.field(key,label,value)
        f.field('status','状态',status,options=['在用','闲置','待确认'],readonly=True)
        f.field('note','备注')
        f.field('borrowed_at','借用时间（留空为当前）')
        ttk.Label(f.body,text='可填 2026-09-08 或 2026-09-08 14:30',style='Muted.TLabel').grid(row=f.row,column=1,sticky='w')
        f.row+=1
        def save():
            from supplies import integer
            integer(f.get('quantity'),1)
            return self.store.add_supply(**{key:f.get(key) for key in ('name','spec','unit','location','quantity','status','note','borrowed_at')})
        f.finish(save,'保存物品')
        return f

    def selected_supply(self):
        ids=self.supply_tree.selection()
        if len(ids)!=1:
            messagebox.showinfo('选择物品','请先选择一条物品记录。',parent=self)
            return None
        return self.supply_items[ids[0]]

    def supply_dialog(self,action):
        row=self.selected_supply()
        if row is None:
            return
        f=self.supply_form_class(self,action+'非挂账物品',f"{row['name']} · 当前持有 {row['quantity']}{row['unit']}。"+
            ('归还表示你还回去，持有数量随之减少；支持分次归还。' if action=='归还' else ''))
        if action=='修改':
            for key,label in [('name','名称'),('spec','规格'),('location','位置 / 使用机器')]:
                f.field(key,label,row[key])
            f.field('status','状态',row['status'],options=['在用','闲置','待确认'] if row['quantity'] else [row['status']],readonly=True)
            f.field('note','备注',row['note'])
            f.field('borrowed_at','借用时间（留空保持原值）',row['borrowed_at'])
            f.finish(lambda:self.store.personal_supply_change(row['id'],'修改',changes={k:f.get(k) for k in ('name','spec','location','status','note','borrowed_at')}))
        else:
            f.field('quantity','本次归还数量',str(row['quantity']))
            f.field('reason','归还给谁 / 备注')
            f.field('returned_at','归还时间（留空为当前）')
            f.finish(lambda:self.store.personal_supply_change(row['id'],'归还',quantity=f.get('quantity'),reason=f.get('reason'),returned_at=f.get('returned_at')),'确认归还')
        return f

    def supply_detail(self):
        row=self.selected_supply()
        if not row:
            return
        win=tk.Toplevel(self)
        win.title('物品详情')
        win.geometry('620x480')
        win.transient(self)
        body=ttk.Frame(win,padding=26)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=row['name'],style='Heading.TLabel').pack(anchor='w',pady=(0,16))
        lines=[f"规格：{row['spec'] or '未填写'}",f"持有：{row['quantity']} {row['unit']}  ·  {row['status']}",
            f"位置：{row['location']}",f"借用时间：{row['borrowed_at'] or '未记录，可通过修改补充'}",
            f"最近登记的归还时间：{row['returned_at'] or '未记录'}",f"备注：{row['note'] or '无'}"]
        if row['lent']:
            lines.append(f"旧版借出未收回：{row['lent']} {row['unit']}（详见历史）")
        box=tk.Text(body,wrap='word',height=12,font=('Microsoft YaHei UI',10),relief='flat',padx=4,pady=8)
        box.pack(fill='both',expand=True)
        box.insert('1.0','\n\n'.join(lines))
        box.configure(state='disabled')
        Button(body,text='关闭',command=win.destroy).pack(anchor='e',pady=(12,0))
        return win

    def supply_history(self):
        row=self.selected_supply()
        if row:
            self.log_query.set(row['id'])
            self.refresh_logs()
            self.tabs.select(self.log_tab)
