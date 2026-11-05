"""Server hardware page, sharing records with the current ledger."""
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
        Button(actions,text='＋ 登记服务器',command=self.server_form).pack(side='left')
        self.server_tree=self.tree(sidebar,[('name','服务器')],[205],height=8)
        self.server_tree.configure(selectmode='browse')
        self.server_tree.bind('<<TreeviewSelect>>',lambda e:self.refresh_server_items())
        self.server_tree.bind('<Double-1>',self.edit_selected_server)
        self.server_query.trace_add('write',lambda *args:self.refresh_servers())
        pane=ttk.Frame(self.server_tab)
        pane.pack(side='left',fill='both',expand=True)
        self.server_title=tk.StringVar()
        self.server_info=tk.StringVar()
        heading=ttk.Frame(pane)
        heading.pack(fill='x')
        ttk.Label(heading,textvariable=self.server_title,style='Heading.TLabel').pack(side='left')
        self.server_add=Button(heading,text='＋ 添加硬件',style='Accent.TButton',command=self.server_picker)
        self.server_add.pack(side='right')
        self.server_supply_add=Button(heading,text='＋ 添加物品',style='Accent.TButton',command=self.server_supply_menu)
        ttk.Label(pane,textvariable=self.server_info,wraplength=620,style='Muted.TLabel').pack(anchor='w',pady=(5,12))
        switches=ttk.Frame(pane)
        switches.pack(fill='x',pady=(0,10))
        self.server_mode=tk.StringVar(value='hardware')
        for value,label in [('hardware','硬件条码'),('supplies','非挂账物品')]:
            ttk.Radiobutton(switches,text=label,value=value,variable=self.server_mode,command=self.switch_server_mode).pack(side='left',padx=(0,16))
        self.server_hardware_page=ttk.Frame(pane)
        self.server_hardware_page.pack(fill='both',expand=True)
        self.server_supply_page=ttk.Frame(pane)
        tools=ttk.Frame(self.server_hardware_page)
        tools.pack(fill='x',pady=(0,6))
        self.server_show_pending=tk.BooleanVar()
        ttk.Checkbutton(tools,text='显示待补条码',variable=self.server_show_pending,command=self.refresh_server_items).pack(side='left')
        ttk.Label(tools,text='双击硬件可补录或更正条码',style='Muted.TLabel').pack(side='right')
        self.server_assets=self.tree(self.server_hardware_page,[('barcode','条码'),('category','类别'),('model','型号'),('note','描述 / 备注')],
                                     [190,70,120,260],height=10)
        self.server_assets.bind('<Double-1>',lambda e:self.server_barcode() if self.server_assets.identify_row(e.y) else None)
        self.server_supplies=self.tree(self.server_supply_page,[('name','名称'),('spec','规格'),('quantity','数量'),('status','状态'),('note','备注')],
                                      [125,150,85,75,215],height=10)

    def switch_server_mode(self):
        supplies=self.server_mode.get()=='supplies'
        for widget in (self.server_hardware_page,self.server_supply_page,self.server_add,self.server_supply_add):
            widget.pack_forget()
        (self.server_supply_page if supplies else self.server_hardware_page).pack(fill='both',expand=True)
        (self.server_supply_add if supplies else self.server_add).pack(side='right')
        self.refresh_server_items()

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
        pending=sum(not a['barcode'] for a in assets)
        self.server_hardware={a['id']:a for a in assets}
        self.server_title.set(row['name'])
        summary=f'非挂账物品 {len(supplies)} 条' if self.server_mode.get()=='supplies' else f'已有条码 {len(assets)-pending} 件  ·  待补 {pending} 件'
        self.server_info.set(f"{row['location']}  ·  {summary}"+ ('\n'+row['note'] if row['note'] else ''))
        for item in assets:
            if not item['barcode'] and not self.server_show_pending.get():
                continue
            self.server_assets.insert('','end',iid=item['id'],values=(item['barcode'] or '待补条码',item['category'],item['model'],
                '；'.join(v for v in (item['description'],item['note'],item['platform_note']) if v)))
        for item in supplies:
            self.server_supplies.insert('','end',iid=item['id'],values=(item['name'],item['spec'],f"{item['quantity']} {item['unit']}",item['status'],item['note']))

    def server_supply_menu(self):
        server=self.selected_server()
        if not server:
            return
        win=tk.Toplevel(self)
        win.title('添加非挂账物品')
        win.transient(self)
        win.resizable(False,False)
        body=ttk.Frame(win,padding=20)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text='添加到 '+server['name'],style='Heading.TLabel').pack(anchor='w',pady=(0,12))
        def launch(command):
            win.destroy()
            command()
        Button(body,text='登记新物品',style='Accent.TButton',
               command=lambda:launch(lambda:self.add_supply_dialog(location=server['location'],status='在用'))).pack(side='left')
        Button(body,text='从已有物品分配',command=lambda:launch(lambda:self.server_existing_supply(server))).pack(side='left',padx=(8,0))
        win.bind('<Escape>',lambda e:win.destroy())
        return win

    def server_existing_supply(self,server):
        items=[r for r in self.store.supply_rows()
               if r['quantity']>0 and r['location'].casefold()!=server['location'].casefold()]
        if not items:
            messagebox.showinfo('分配已有物品','没有可从其他位置分配的非挂账物品。',parent=self)
            return
        choices={f"{i+1}. {r['name']} · {r['spec']} · {r['quantity']} {r['unit']} · {r['location']}":r for i,r in enumerate(items)}
        form=self.supply_form_class(self,'分配已有物品 · '+server['name'],'将整条记录移到此服务器，数量保持不变。')
        form.field('item','物品',next(iter(choices)),list(choices),True)
        form.finish(lambda:self.store.personal_supply_change(choices[form.get('item')]['id'],'修改',
                    reason='分配到服务器 '+server['name'],changes={'location':server['location'],'status':'在用'}),'确认分配')
        return form

    def edit_selected_server(self,event):
        if self.server_tree.identify_row(event.y):
            row=self.selected_server(quiet=True)
            if row:
                self.server_form(row)

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

    def server_picker(self):
        server=self.selected_server()
        if not server:
            return
        win=tk.Toplevel(self)
        win.title('添加硬件 · '+server['name'])
        win.transient(self)
        win.geometry('940x620')
        win.minsize(760,500)
        body=ttk.Frame(win,padding=20)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text='从台账选择硬件',style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body,text='搜索或筛选后点击行勾选。确认后更新原记录的位置和状态，不重复入账。',style='Muted.TLabel').pack(anchor='w',pady=(6,12))
        filters=ttk.Frame(body)
        filters.pack(fill='x',pady=(0,10))
        ttk.Label(filters,text='搜索').pack(side='left')
        query=tk.StringVar()
        search=ttk.Entry(filters,textvariable=query)
        search.pack(side='left',fill='x',expand=True,padx=8)
        category=tk.StringVar(value='全部类别')
        ttk.Combobox(filters,textvariable=category,values=['全部类别']+self.store.categories(),state='readonly',width=12).pack(side='left')
        footer=ttk.Frame(body)
        footer.pack(side='bottom',fill='x',pady=(12,0))
        picked=set()
        count=tk.StringVar()
        ttk.Label(footer,textvariable=count,style='Muted.TLabel').pack(side='left')
        Button(footer,text='＋ 手动新增条码',command=lambda:(win.destroy(),self.server_manual(server))).pack(side='left',padx=12)
        Button(footer,text='添加所选硬件',style='Accent.TButton',command=lambda:apply()).pack(side='right')
        Button(footer,text='取消',command=win.destroy).pack(side='right',padx=8)
        tree=self.tree(body,[('pick','选择'),('barcode','条码'),('category','类别'),('model','型号'),('location','当前位置')],[65,210,95,155,240])
        tree.configure(selectmode='browse')
        items={r['id']:r for r in self.store.assets()
               if r['status']!='借出' and r['location'].casefold()!=server['location'].casefold()}
        def render(*args):
            tree.delete(*tree.get_children())
            words=query.get().casefold().split()
            for ident,r in items.items():
                text=' '.join((r['barcode'] or '待补条码',r['category'],r['model'],r['location'],r['description'])).casefold()
                if (category.get()=='全部类别' or category.get()==r['category']) and all(w in text for w in words):
                    tree.insert('','end',iid=ident,values=('☑' if ident in picked else '☐',r['barcode'] or '待补条码',r['category'],r['model'],r['location']))
            count.set(f'已选 {len(picked)} 件 · 搜索不会清空选择')
        def toggle(event):
            ident=tree.identify_row(event.y) if event.type==tk.EventType.ButtonRelease else next(iter(tree.selection()),None)
            if ident in items:
                picked.symmetric_difference_update([ident])
                tree.set(ident,'pick','☑' if ident in picked else '☐')
                count.set(f'已选 {len(picked)} 件 · 搜索不会清空选择')
        def apply():
            try:
                self.store.assign_server_assets(server,sorted(picked))
            except ValueError as exc:
                messagebox.showerror('未添加',str(exc),parent=win)
                return
            if any(not items[ident]['barcode'] for ident in picked):
                self.server_show_pending.set(True)
            win.destroy()
            self.refresh()
        tree.bind('<ButtonRelease-1>',toggle)
        tree.bind('<space>',toggle)
        query.trace_add('write',render)
        category.trace_add('write',render)
        win.bind('<Escape>',lambda e:win.destroy())
        render()
        search.focus_set()
        return win

    def server_manual(self,server):
        from store import parse_codes
        form=self.supply_form_class(self,'手动新增条码 · '+server['name'],
            '每行填一个新条码，保存后新增对应挂账记录。已有条码请搜索选择，已有待补记录可双击补码。')
        form.field('category','类别', '其他',self.store.categories())
        form.field('model','型号（可空）')
        form.text('codes','新条码',height=7)
        def save():
            codes=parse_codes(form.get('codes'))
            if not codes:
                raise ValueError('请填写至少一个新条码。')
            self.store.receive(form.get('category'),form.get('model'),len(codes),codes,location=server['location'],status='在用')
        form.finish(save,'添加硬件')
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
