"""Server inventory page, sharing records with the hardware and supplies ledgers."""
import tkinter as tk
from tkinter import messagebox,ttk
from ui import Button


class ServerUI:
    def build_servers(self):
        sidebar=ttk.Frame(self.server_tab,width=245,padding=(0,0,12,0))
        sidebar.pack(side='left',fill='y')
        self.server_query=tk.StringVar()
        ttk.Label(sidebar,text='按名称或 IP / 位置搜索').pack(anchor='w',pady=(0,6))
        ttk.Entry(sidebar,textvariable=self.server_query).pack(fill='x',pady=(0,8))
        actions=ttk.Frame(sidebar)
        actions.pack(fill='x',pady=(0,8))
        Button(actions,text='＋ 登记服务器',style='Accent.TButton',command=self.server_form).pack(side='left')
        Button(actions,text='编辑',command=lambda:self.server_form(self.selected_server())).pack(side='left',padx=6)
        self.server_tree=self.tree(sidebar,[('name','服务器')],[205],height=8)
        self.server_tree.configure(selectmode='browse')
        self.server_tree.bind('<<TreeviewSelect>>',lambda e:self.refresh_server_items())
        self.server_query.trace_add('write',lambda *args:self.refresh_servers())
        pane=ttk.Frame(self.server_tab)
        pane.pack(side='left',fill='both',expand=True)
        self.server_title=tk.StringVar()
        self.server_info=tk.StringVar()
        ttk.Label(pane,textvariable=self.server_title,style='Heading.TLabel').pack(anchor='w')
        ttk.Label(pane,textvariable=self.server_info,wraplength=620,style='Muted.TLabel').pack(anchor='w',pady=(5,12))
        lists=ttk.Frame(pane)
        lists.pack(fill='both',expand=True)
        lists.columnconfigure(0,weight=1)
        lists.rowconfigure(0,weight=3,uniform='inventory')
        lists.rowconfigure(1,weight=2,uniform='inventory')
        hardware=ttk.Frame(lists)
        hardware.grid(row=0,column=0,sticky='nsew',pady=(0,10))
        controls=ttk.Frame(hardware)
        controls.pack(fill='x',pady=(0,5))
        ttk.Label(controls,text='挂账硬件').pack(side='left')
        for label,command in [('分配已有条码',self.server_assign),('新增挂账',self.server_receive),('录入 / 更正条码',self.server_barcode)]:
            Button(controls,text=label,command=command).pack(side='left',padx=(6,0))
        self.server_assets=self.tree(hardware,[('barcode','条码'),('category','类别'),('model','型号'),('status','状态'),('note','描述 / 备注')],
                                     [188,70,110,75,245],height=5)
        supplies=ttk.Frame(lists)
        supplies.grid(row=1,column=0,sticky='nsew')
        controls=ttk.Frame(supplies)
        controls.pack(fill='x',pady=(0,5))
        ttk.Label(controls,text='非挂账物品').pack(side='left')
        Button(controls,text='分配已有物品',command=self.server_assign_supply).pack(side='left',padx=6)
        Button(controls,text='新增物品',command=self.server_supply).pack(side='left')
        self.server_supplies=self.tree(supplies,[('name','名称'),('spec','规格'),('quantity','数量'),('status','状态'),('note','备注')],
                                       [125,150,85,75,215],height=4)

    def refresh_servers(self):
        selected=next(iter(self.server_tree.selection()),None)
        q=self.server_query.get().strip().casefold()
        self.server_rows={r['id']:r for r in self.store.servers() if q in (r['name']+' '+r['location']).casefold()}
        self.server_tree.delete(*self.server_tree.get_children())
        for ident,row in self.server_rows.items():
            self.server_tree.insert('','end',iid=ident,values=(row['name'],))
        ident=selected if selected in self.server_rows else next(iter(self.server_rows),None)
        if ident:
            self.server_tree.selection_set(ident)
        self.refresh_server_items()

    def selected_server(self,quiet=False):
        ident=next(iter(self.server_tree.selection()),None)
        row=self.server_rows.get(ident)
        if row is None and not quiet:
            messagebox.showinfo('选择服务器','请先登记或选择一台服务器。',parent=self)
        return row

    def refresh_server_items(self):
        self.server_assets.delete(*self.server_assets.get_children())
        self.server_supplies.delete(*self.server_supplies.get_children())
        row=self.selected_server(quiet=True)
        if not row:
            self.server_title.set('尚未选择服务器')
            self.server_info.set('可将已有台账的位置登记为服务器，该位置的物料会直接显示。')
            self.server_hardware={}
            return
        assets,supplies=self.store.server_items(row)
        self.server_hardware={a['id']:a for a in assets}
        self.server_title.set(row['name'])
        self.server_info.set(f"台账位置：{row['location']}  ·  硬件 {len(assets)} 件  ·  非挂账物品 {len(supplies)} 条"
                             + ('\n'+row['note'] if row['note'] else ''))
        for item in assets:
            self.server_assets.insert('','end',iid=item['id'],values=(item['barcode'] or '待补条码',item['category'],item['model'],
                item['status'],'；'.join(v for v in (item['description'],item['note'],item['platform_note']) if v)))
        for item in supplies:
            self.server_supplies.insert('','end',iid=item['id'],values=(item['name'],item['spec'],f"{item['quantity']} {item['unit']}",item['status'],item['note']))

    def server_form(self,row=None):
        form=self.supply_form_class(self,'编辑服务器' if row else '登记服务器',
            '台账位置可填写 IP 或选择已有位置。位置完全匹配的记录会显示在此服务器下，无需重复录入。')
        form.field('name','服务器名称',row['name'] if row else '')
        form.field('location','台账位置 / IP',row['location'] if row else '',[row['location']] if row else self.locations(),bool(row))
        form.field('note','备注',row['note'] if row else '')
        def save():
            ident=self.store.save_server(form.get('name'),form.get('location'),form.get('note'),row['id'] if row else None)
            self.server_query.set('')
            self.server_tree.selection_set(ident)
        form.finish(save)
        return form

    def server_receive(self):
        row=self.selected_server()
        if row:
            return self.receive_dialog(location=row['location'],status='在用')

    def server_supply(self):
        row=self.selected_server()
        if row:
            return self.add_supply_dialog(location=row['location'],status='在用')

    def server_assign(self):
        row=self.selected_server()
        if row:
            form=self.supply_form_class(self,'分配已有硬件 · '+row['name'],
                '可逐个扫码或批量粘贴。现有记录的位置会改为这台服务器，状态设为在用，并记录操作历史。')
            form.text('codes','已有条码（每行一个）',height=8)
            form.finish(lambda:self.store.assign_server_barcodes(row,form.get('codes')),'确认分配')
            return form

    def server_barcode(self):
        selection=self.server_assets.selection()
        if len(selection)!=1:
            messagebox.showinfo('录入条码','请先选择一件硬件。',parent=self)
            return
        row=self.server_hardware[selection[0]]
        form=self.supply_form_class(self,'录入 / 更正条码',f"{row['category']} · {row['model']} · {row['location']}。每条记录只对应一个条码。")
        form.field('barcode','条码',row['barcode'] or '')
        def save():
            from store import parse_codes
            codes=parse_codes(form.get('barcode'))
            if len(codes)!=1:
                raise ValueError('请填写一个条码。')
            self.store.update([row['id']],{'barcode':codes[0]},'服务器录入条码',row['location'])
        form.finish(save)
        return form

    def server_assign_supply(self):
        row=self.selected_server()
        if not row:
            return
        items=[s for s in self.store.supply_rows() if s['quantity']>0 and s['location'].casefold()!=row['location'].casefold()]
        if not items:
            messagebox.showinfo('分配已有物品','没有可从其他位置分配的非挂账物品。',parent=self)
            return
        options={f"{i+1}. {s['name']} · {s['spec']} · {s['quantity']} {s['unit']} · {s['location']}":s for i,s in enumerate(items)}
        form=self.supply_form_class(self,'分配已有物品 · '+row['name'],'整条物品记录将移到此服务器，数量保持不变。')
        form.field('item','物品',next(iter(options)),list(options),True)
        form.finish(lambda:self.store.personal_supply_change(options[form.get('item')]['id'],'修改',
                    reason='分配到服务器 '+row['name'],changes={'location':row['location'],'status':'在用'}),'确认分配')
        return form
