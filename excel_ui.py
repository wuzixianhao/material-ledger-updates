"""Review-first website reconciliation."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ui import Button, Scrollbar
from excel_sync import read_export,parse_sheet,plan_sync,apply_sync


class ExcelUI:
    def website_item_detail(self,parent,row,group):
        win=tk.Toplevel(parent)
        win.title('对账详情 · '+(row.get('barcode') or '待补条码'))
        win.geometry('780x620')
        win.minsize(560,400)
        win.transient(parent)
        body=ttk.Frame(win,padding=22)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=group+' · '+(row.get('barcode') or '待补条码'),style='Heading.TLabel').pack(anchor='w',pady=(0,14))
        Button(body,text='关闭',command=win.destroy).pack(side='bottom',anchor='e',pady=(12,0))
        text=tk.Text(body,wrap='word',font=('Microsoft YaHei UI',10),relief='flat',padx=12,pady=12)
        bar=Scrollbar(body,command=text.yview)
        bar.pack(side='right',fill='y')
        text.configure(yscrollcommand=bar.set)
        text.pack(fill='both',expand=True)
        fields={'category':'资产分类','barcode':'资产编码','model':'型号','puid':'PUID','sn':'设备序列号 SN',
                'description':'详细描述','platform_note':'网站资产使用备注','note':'个人备注','location':'本地位置','status':'本地状态'}
        parts=[]
        for key,label in fields.items():
            if key in row:
                parts.append(f"{label}\n{row.get(key) or '未填写'}")
        old=row.get('old')
        if old:
            changes=[f"{label}\n原值：{old.get(key) or '未填写'}\n网站：{row.get(key) or '未填写'}" for key,label in fields.items() if key in row and key in old and row[key]!=old[key]]
            parts.append('修改前后\n\n'+'\n\n'.join(changes))
        text.insert('1.0','\n\n'.join(parts))
        text.configure(state='disabled')
        return win

    def import_website(self):
        path=filedialog.askopenfilename(parent=self,title='选择本人名下完整网站资产清单',filetypes=[('Excel / CSV','*.xlsx *.csv'),('所有文件','*.*')])
        if not path:
            return
        try:
            sheets=read_export(path)
        except (ValueError,OSError) as exc:
            messagebox.showerror('无法读取',str(exc),parent=self)
            return
        win=tk.Toplevel(self)
        win.title('网站清单对账 · 先预览再同步')
        win.geometry('1180x760')
        win.minsize(940,620)
        win.transient(self)
        body=ttk.Frame(win,padding=22)
        body.pack(fill='both',expand=True)
        footer=ttk.Frame(body)
        footer.pack(side='bottom',fill='x')
        ttk.Label(body,text='以网站清单核对我的挂账',style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body,text='资产编码对应本地条码；网站更新类别、型号、PUID、SN、详细描述和使用备注。\n本地位置、使用状态、个人备注和历史继续保留；网站减少项转为已转出。',style='Muted.TLabel').pack(anchor='w',pady=(8,12))
        top=ttk.Frame(body)
        top.pack(fill='x')
        ttk.Label(top,text='工作表').pack(side='left',padx=(0,10))
        sheet=tk.StringVar(value=next(iter(sheets),'') )
        picker=ttk.Combobox(top,textvariable=sheet,values=list(sheets),state='readonly',width=32)
        picker.pack(side='left')
        summary=tk.StringVar()
        ttk.Label(body,textvariable=summary,style='Muted.TLabel',wraplength=1050).pack(anchor='w',pady=12)
        notebook=ttk.Notebook(body)
        # Global theme hides tabs; use explicit category buttons below.
        buttons=ttk.Frame(body)
        buttons.pack(fill='x',pady=(0,10))
        notebook.pack(fill='both',expand=True)
        trees={}
        records={}
        names={'added':'新增','removed':'减少','changed':'信息更新','unidentified':'未补码待核对','unchanged':'一致'}
        for key,title in names.items():
            page=ttk.Frame(notebook)
            notebook.add(page,text=title)
            Button(buttons,text=title,command=lambda p=page:notebook.select(p)).pack(side='left',padx=(0,8))
            trees[key]=self.tree(page,[('barcode','资产编码 / 条码'),('category','类别'),('model','型号'),('description','详细描述'),('note','资产使用备注'),('detail','变化 / 说明')],[210,80,140,340,240,340])
            records[key]={}
            def show_detail(event=None,tree=trees[key],key=key):
                selected=tree.selection()
                if selected:
                    return self.website_item_detail(win,records[key][selected[0]],names[key])
            trees[key].bind('<Double-1>',show_detail)
            trees[key].show_full_detail=show_detail
        def selected_detail():
            for tree in trees.values():
                if str(tree.master)==notebook.select():
                    if tree.selection():
                        tree.show_full_detail()
                    else:
                        messagebox.showinfo('查看详情','请先选择一条物料，或直接双击一行。',parent=win)
                    return
        Button(buttons,text='查看完整详情',command=selected_detail).pack(side='right')
        full=tk.BooleanVar()
        uncoded=tk.BooleanVar()
        ttk.Checkbutton(footer,text='我确认这是本人名下完整清单，网站未出现的条码应从当前挂账移出',variable=full).pack(anchor='w',pady=(12,4))
        ttk.Checkbutton(footer,text='未补码记录也已在网站完整清单中体现，将旧数量记录移出，避免重复计数（有此类记录时必选）',variable=uncoded).pack(anchor='w')
        state={}
        def preview(event=None):
            state.clear()
            full.set(False)
            uncoded.set(False)
            for key,tree in trees.items():
                tree.delete(*tree.get_children())
                records[key].clear()
            try:
                plan=plan_sync(self.store,parse_sheet(sheets[sheet.get()]))
                state['plan']=plan
                summary.set('  ·  '.join(f'{names[k]} {len(plan[k])}' for k in names)+f"  | 网站共 {len(plan['items'])} 件")
                for key,tree in trees.items():
                    for row in plan[key]:
                        detail=row.get('platform_note','') or row.get('note','')
                        if key=='changed':
                            labels={'category':'类别','model':'型号','puid':'PUID','sn':'SN','description':'描述','platform_note':'网站备注'}
                            detail='；'.join(f"{label}：{row['old'][k] or '空'} → {row[k] or '空'}" for k,label in labels.items() if row['old'][k]!=row[k])
                        if key=='unidentified':
                            detail='无法逐件匹配；确认完整清单后移出旧数量记录。 '+detail
                        iid=tree.insert('','end',values=(row.get('barcode') or '待补 · '+row['id'][:8],row['category'],row['model'],row.get('description',''),row.get('platform_note',''),detail))
                        records[key][iid]=row
            except ValueError as exc:
                summary.set(str(exc))
        picker.bind('<<ComboboxSelected>>',preview)
        def sync():
            if 'plan' not in state:
                return
            plan=state['plan']
            if not full.get() or (plan['unidentified'] and not uncoded.get()):
                messagebox.showinfo('请核对清单范围','请确认完整清单和未补码处理方式，再执行同步。',parent=win)
                return
            count=len(plan['removed'])+len(plan['unidentified'])
            if not messagebox.askyesno('确认同步',f"新增 {len(plan['added'])} 件，减少 {count} 件，信息更新 {len(plan['changed'])} 件。\n执行前自动备份；操作可在日志中整体撤销。",parent=win):
                return
            try:
                backup=apply_sync(self.store,plan,path+' · 工作表 '+sheet.get(),uncoded.get())
                self.refresh()
                win.destroy()
                messagebox.showinfo('同步完成',f'台账已按网站清单更新。\n同步前备份：{backup}',parent=self)
            except (ValueError,OSError) as exc:
                messagebox.showerror('未同步',str(exc),parent=win)
        actions=ttk.Frame(footer)
        actions.pack(fill='x',pady=(12,0))
        Button(actions,text='确认同步',style='Accent.TButton',command=sync).pack(side='right')
        Button(actions,text='关闭',command=win.destroy).pack(side='right',padx=10)
        preview()
        return win
