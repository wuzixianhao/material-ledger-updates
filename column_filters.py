"""Excel-style, exact-value multi-select filters for the asset table."""
import tkinter as tk
from tkinter import ttk
from ui import Button, Scrollbar

FILTER_COLUMNS=('category','model','location','status')


class ColumnFilters:
    def init_column_filters(self):
        self.column_filters={}
        self.filter_popup=None
        for key in FILTER_COLUMNS:
            self.asset_tree.heading(key,command=lambda k=key:self.open_column_filter(k))
        self.refresh_asset_headings()

    def filter_asset_rows(self,rows,exclude=None):
        return [r for r in rows if all(k==exclude or r[k] in values for k,values in self.column_filters.items())]

    def refresh_asset_headings(self):
        if not hasattr(self,'column_filters'):
            return
        tree=self.asset_tree
        sort=getattr(tree,'sort_key',None)
        for key,label in tree.heading_labels.items():
            suffix=('  ●' if key in self.column_filters else '  ▾') if key in FILTER_COLUMNS else ''
            if sort and sort[0]==key:
                suffix+= ' ↓' if sort[1] else ' ↑'
            tree.heading(key,text=label+suffix)
        active=[f"{tree.heading_labels[k]}（{len(v)}项）" for k,v in self.column_filters.items()]
        self.column_filter_text.set('列筛选：'+'、'.join(active) if active else '点击表头 ▾ 筛选型号、类别、位置或状态；支持多选与组合。')

    def clear_column_filters(self):
        self.column_filters.clear()
        self.refresh_assets()

    def open_column_filter(self,key):
        if self.filter_popup and self.filter_popup.winfo_exists():
            self.filter_popup.destroy()
        # Facet values respect search and other column filters, excluding this column.
        rows=self.store.assets(self.query.get(),self.category.get(),self.status.get(),self.scope.get())
        if getattr(self,'only_uncertain',False):
            rows=[r for r in rows if r['location']=='待确认' or r['status']=='待确认' or not r['model'] or '待确认' in r['model']]
        rows=self.filter_asset_rows(rows,exclude=key)
        counts={}
        for row in rows:
            counts[row[key]]=counts.get(row[key],0)+1
        options=sorted(set(counts)|set(self.column_filters.get(key,())),key=lambda v:v.casefold())
        selected=set(self.column_filters.get(key,options))
        win=tk.Toplevel(self)
        self.filter_popup=win
        win.title(self.asset_tree.heading_labels[key]+'筛选')
        win.transient(self)
        win.resizable(False,True)
        win.geometry('430x570')
        win.minsize(430,430)
        body=ttk.Frame(win,padding=18)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=self.asset_tree.heading_labels[key]+'筛选',style='Heading.TLabel').pack(anchor='w',pady=(0,10))
        sortbar=ttk.Frame(body)
        sortbar.pack(fill='x',pady=(0,10))
        def sort(reverse):
            self.sort_tree(self.asset_tree,key,reverse=reverse)
            win.destroy()
        Button(sortbar,text='升序 ↑',command=lambda:sort(False)).pack(side='left')
        Button(sortbar,text='降序 ↓',command=lambda:sort(True)).pack(side='left',padx=8)
        search=tk.StringVar()
        ttk.Label(body,text='搜索筛选选项',style='Muted.TLabel').pack(anchor='w',pady=(0,5))
        entry=ttk.Entry(body,textvariable=search)
        entry.pack(fill='x',pady=(0,8))
        footer=ttk.Frame(body)
        footer.pack(side='bottom',fill='x',pady=(12,0))
        count=tk.StringVar()
        ttk.Label(footer,textvariable=count,style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        buttons=ttk.Frame(footer)
        buttons.pack(fill='x')
        def apply():
            if set(options)==selected:
                self.column_filters.pop(key,None)
            else:
                self.column_filters[key]=set(selected)
            self.refresh_assets()
            win.destroy()
        def clear():
            self.column_filters.pop(key,None)
            self.refresh_assets()
            win.destroy()
        Button(buttons,text='清除此列',command=clear).pack(side='left')
        Button(buttons,text='应用',style='Accent.TButton',command=apply).pack(side='right')
        Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=8)
        tools=ttk.Frame(body)
        tools.pack(fill='x',pady=(0,8))
        def visible():
            q=search.get().strip().casefold()
            return [v for v in options if q in (v or '空白').casefold()]
        def toggle_all(on):
            selected.update(visible()) if on else selected.difference_update(visible())
            render()
        Button(tools,text='全选搜索结果',command=lambda:toggle_all(True)).pack(side='left')
        Button(tools,text='取消勾选',command=lambda:toggle_all(False)).pack(side='left',padx=8)
        frame=ttk.Frame(body)
        frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=('value',),show='headings',height=7,selectmode='browse')
        tree.heading('value',text='勾选值（符合其他条件的件数）')
        tree.column('value',width=345)
        bar=Scrollbar(frame,command=tree.yview)
        bar.pack(side='right',fill='y')
        tree.configure(yscrollcommand=bar.set)
        tree.pack(fill='both',expand=True)
        values={}
        def render(*args):
            tree.delete(*tree.get_children())
            values.clear()
            for index,value in enumerate(visible()):
                iid=str(index)
                values[iid]=value
                tree.insert('','end',iid=iid,values=(f"{'☑' if value in selected else '☐'}  {value or '（空白）'}   ({counts.get(value,0)})",))
            count.set(f'已勾选 {len(selected)} / {len(options)} 项；未勾选任何项将显示空列表。')
        def toggle(event):
            iid=tree.identify_row(event.y) if event.type==tk.EventType.ButtonRelease else next(iter(tree.selection()),'')
            if iid in values:
                value=values[iid]
                selected.remove(value) if value in selected else selected.add(value)
                render()
                if iid in values:
                    tree.selection_set(iid)
        tree.bind('<ButtonRelease-1>',toggle)
        tree.bind('<space>',toggle)
        search.trace_add('write',render)
        win.bind('<Escape>',lambda e:win.destroy())
        win.bind('<Control-Return>',lambda e:apply())
        # Stable test/UI automation handles, also useful for keyboard accessibility checks.
        win.filter_selected=selected
        win.filter_search=search
        win.filter_tree=tree
        win.filter_apply=apply
        render()
        win.update_idletasks()
        x=min(self.winfo_pointerx(),self.winfo_screenwidth()-win.winfo_width()-15)
        y=min(self.asset_tree.winfo_rooty()+40,self.winfo_screenheight()-win.winfo_height()-45)
        win.geometry(f'+{max(0,x)}+{max(0,y)}')
        entry.focus_set()
        return win
