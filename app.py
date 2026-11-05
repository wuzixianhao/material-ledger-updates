"""Portable native Windows material ledger."""
import argparse
import json
import os
import sys
import tkinter as tk
import traceback
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from server_ui import ServerUI
from store import CATEGORIES, STATUSES, Store, parse_codes
from portable import VERSION, EXE_NAME, SnapshotSource, export_portable
from ui import BG, INK, MUTED, NAV, Button, MetricCard, SidebarButton, Scrollbar, setup_style
from supplies_ui import SuppliesUI
from excel_ui import ExcelUI
from column_filters import ColumnFilters
from online_update_ui import OnlineUpdateUI

BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
RESOURCES = Path(__file__).resolve().parent
TITLE = "物料台账 · 本地版"
LABELS = dict(barcode="条码", category="类别", model="型号", owner="挂账归属",
              location="位置 / 使用人", status="状态", note="备注", active="有效记录",
              created_at="登记时间", updated_at="变动时间", batch_id="批次编号")
LABELS.update(received_at='挂账时间',lent_at='最近借出时间',recovered_at='最近收回时间',transferred_at='归还/转出时间',occurred_at='最近登记的业务时间')
LABELS.update(puid='PUID',sn='设备序列号 SN',description='网站详细描述',platform_note='网站使用备注')


def readable_date(value):
    return value[:19].replace("T", " ")


class Form(tk.Toplevel):
    def __init__(self, app, title, hint, width=620):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.transient(app)
        self.resizable(True, True)
        self.configure(background="white")
        self.vars = {}
        self.row = 0
        self.actions = ttk.Frame(self, padding=(22, 14))
        self.actions.pack(side='bottom', fill='x')
        viewport = ttk.Frame(self)
        viewport.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(viewport, bg='white', highlightthickness=0)
        scroll = Scrollbar(viewport, command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body = ttk.Frame(self.canvas, padding=22)
        self.body_window = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.body_window, width=e.width))
        def wheel(event):
            if not isinstance(event.widget, (tk.Text, ttk.Combobox)):
                self.canvas.yview_scroll(-int(event.delta/120), 'units')
        self.bind('<MouseWheel>', wheel)
        self.body.columnconfigure(1, weight=1)
        ttk.Label(self.body, text=title, style="Heading.TLabel").grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        ttk.Label(self.body, text=hint, wraplength=width-50, style="Muted.TLabel").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(7, 15))
        self.row += 1
        self.bind("<Escape>", lambda e: self.destroy())
        self.minsize(width, 200)
        self.grab_set()

    def field(self, key, title, value="", options=None, readonly=False):
        ttk.Label(self.body, text=title).grid(row=self.row, column=0, sticky="w", padx=(0, 16), pady=5)
        var = tk.StringVar(value=value)
        self.vars[key] = var
        if options is None:
            entry = ttk.Entry(self.body, textvariable=var)
        else:
            entry = ttk.Combobox(self.body, textvariable=var, values=options, state="readonly" if readonly else "normal")
        entry.grid(row=self.row, column=1, sticky="ew", pady=5)
        self.row += 1
        return entry

    def text(self, key, title, value="", height=5):
        ttk.Label(self.body, text=title).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        self.row += 1
        frame = ttk.Frame(self.body)
        frame.grid(row=self.row, column=0, columnspan=2, sticky="nsew")
        box = tk.Text(frame, height=height, width=55, font=("Microsoft YaHei UI", 10), wrap="word",
                      relief="flat", borderwidth=0, highlightthickness=1, highlightbackground='#dce4ef',
                      highlightcolor='#287aef', background='#f8fafc', padx=12, pady=10, undo=True)
        scroll = Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        box.pack(fill="both", expand=True)
        box.insert("1.0", value)
        self.vars[key] = box
        self.row += 1
        return box

    def get(self, key):
        value = self.vars[key]
        return value.get("1.0", "end-1c").strip() if isinstance(value, tk.Text) else value.get().strip()

    def finish(self, callback, label="保存"):
        self.error = tk.StringVar()
        ttk.Label(self.actions, textvariable=self.error, foreground="#b42318", wraplength=550).pack(anchor='w', pady=(0, 8))
        buttons = ttk.Frame(self.actions)
        buttons.pack(anchor='e')
        Button(buttons, text="取消", command=self.destroy).pack(side="left", padx=8)

        def submit(event=None):
            try:
                callback()
                self.app.refresh()
                self.destroy()
            except (ValueError, OSError) as exc:
                self.error.set(str(exc))
        self.submit = submit
        Button(buttons, text=label + "  Ctrl+Enter", style="Accent.TButton", command=submit).pack(side="left")
        self.bind("<Control-Return>", submit)
        self.update_idletasks()
        width = max(650, self.body.winfo_reqwidth()+18)
        height = min(self.body.winfo_reqheight()+self.actions.winfo_reqheight()+4, self.winfo_screenheight()-110)
        x = min(self.winfo_screenwidth()-width-20, self.app.winfo_rootx() + max(0, (self.app.winfo_width()-width)//2))
        y = max(15, min(self.winfo_screenheight()-height-65, self.app.winfo_rooty()+35))
        self.geometry(f"{width}x{height}+{max(0,x)}+{y}")


class App(ServerUI,OnlineUpdateUI,ColumnFilters,ExcelUI,SuppliesUI,tk.Tk):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.program_base=BASE
        self.title(TITLE)
        self.geometry(f"{min(1460,self.winfo_screenwidth()-70)}x{min(900,self.winfo_screenheight()-90)}+30+25")
        self.minsize(1160, 680)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.report_callback_exception = self.callback_error
        setup_style(self)
        icon = RESOURCES / 'ledger.ico'
        if icon.exists():
            self.iconbitmap(str(icon))
        sidebar = tk.Frame(self, bg=NAV, width=196)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        brand = tk.Canvas(sidebar, height=95, width=190, bg=NAV, highlightthickness=0)
        brand.pack(fill='x', pady=(20, 12))
        brand.create_polygon(24,25,42,15,60,25,42,35, fill='#72bcff', outline='')
        brand.create_polygon(24,28,40,38,40,57,24,47, fill='#378aef', outline='')
        brand.create_polygon(44,38,60,28,60,47,44,57, fill='#225dcc', outline='')
        brand.create_text(72,30, text='物料台账', anchor='w', fill='white', font=('Microsoft YaHei UI',13,'bold'))
        brand.create_text(25,80, text='M A T E R I A L   D E S K', anchor='w', fill='#7794b8', font=('Segoe UI',8))
        tk.Label(sidebar, text='工作空间', bg=NAV, fg='#6783a5', font=('Microsoft YaHei UI',9)).pack(anchor='w', padx=24, pady=(5, 12))
        nav_area = tk.Frame(sidebar, bg=NAV)
        nav_area.pack(fill='x', padx=10)
        bottom = tk.Frame(sidebar, bg=NAV)
        bottom.pack(side='bottom', fill='x', padx=23, pady=25)
        tk.Label(bottom, text='●  离线可用', bg=NAV, fg='#71d4bb', font=('Microsoft YaHei UI',10)).pack(anchor='w')
        tk.Label(bottom, text='便携版  ·  v'+VERSION, bg=NAV, fg='#7290b3', font=('Segoe UI',9)).pack(anchor='w', pady=(8, 0))
        main = ttk.Frame(self, padding=(26, 22), style='Workspace.TFrame')
        main.pack(side='left', fill='both', expand=True)
        header = ttk.Frame(main, style='Workspace.TFrame')
        header.pack(fill='x')
        left = ttk.Frame(header, style='Workspace.TFrame')
        left.pack(side='left')
        ttk.Label(left, text='个人工作空间  /  物料管理', style='Workspace.TLabel', font=('Microsoft YaHei UI',9)).pack(anchor='w')
        self.page_title = tk.StringVar(value='当前台账')
        ttk.Label(left, textvariable=self.page_title, style='PageTitle.TLabel').pack(anchor='w', pady=(7, 3))
        self.page_subtitle = tk.StringVar(value='掌握每件物料的状态，让每一次流转都有记录。')
        ttk.Label(left, textvariable=self.page_subtitle, style='Workspace.TLabel').pack(anchor='w')
        self.header_add=Button(header, text='＋  新增挂账', style='Accent.TButton', command=self.receive_dialog)
        self.header_add.pack(side='right', padx=(8, 0))
        Button(header, text='备份', command=self.backup).pack(side='right')
        Button(header,text='网站 Excel 对账',command=self.import_website).pack(side='right',padx=8)
        cards = ttk.Frame(main, style='Workspace.TFrame')
        self.metric_frame=cards
        cards.pack(fill='x', pady=(23, 20))
        self.metrics = {}
        for i, (key, label, subtitle, color) in enumerate((
            ('total', '当前在账', '借出仍计入在账', '#287aef'),
            ('pending', '待补条码', '补码不会重复入账', '#d49a36'),
            ('lent', '借出未归还', '点击查看借用去向', '#2aa693'),
            ('uncertain', '信息待完善', '型号或位置待确认', '#8d78c1'))):
            var = tk.StringVar(value='0')
            self.metrics[key] = var
            card = MetricCard(cards, label, subtitle, var, color, str(i+1), lambda k=key: self.metric_clicked(k))
            card.grid(row=0, column=i, sticky='ew', padx=(0 if i==0 else 12, 0))
            cards.columnconfigure(i, weight=1, uniform='cards')
        self.footer = tk.StringVar()
        ttk.Label(main, textvariable=self.footer, style='Workspace.TLabel', font=('Microsoft YaHei UI',9)).pack(side='bottom', anchor='w', pady=(12, 0))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill='both', expand=True)
        self.asset_tab = ttk.Frame(self.tabs, padding=18)
        self.supply_tab = ttk.Frame(self.tabs, padding=18)
        self.server_tab = ttk.Frame(self.tabs, padding=18)
        self.pending_tab = ttk.Frame(self.tabs, padding=18)
        self.summary_tab = ttk.Frame(self.tabs, padding=18)
        self.log_tab = ttk.Frame(self.tabs, padding=18)
        self.help_tab = ttk.Frame(self.tabs, padding=18)
        pages = ((self.asset_tab, '当前台账', '▦', '掌握每件物料的状态，让每一次流转都有记录。'),
            (self.server_tab, '服务器管理', '▥', '按服务器查看、添加和补录硬件条码。'),
            (self.supply_tab, '非挂账物品', '◇', '记录我持有的物品、使用状态和归还情况。'),
            (self.pending_tab, '批次与补码', '▤', '先记录数量，随时补齐身份信息。'),
            (self.summary_tab, '分类汇总', '◴', '按类别、型号、位置查看当前在账分布。'),
            (self.log_tab, '操作日志', '≡', '完整保留每次操作，随时追溯修改前后。'),
            (self.help_tab, '备份与迁移', '⇄', '把工具和数据一起带走，换一台电脑继续使用。'))
        self.navigation = []
        for page, title, symbol, subtitle in pages:
            self.tabs.add(page, text=title)
            button = SidebarButton(nav_area, title, symbol, lambda p=page: self.tabs.select(p))
            button.pack(fill='x', pady=4)
            self.navigation.append((page, button, title, subtitle))
        self.tabs.bind('<<NotebookTabChanged>>', self.sync_navigation)
        self.build_assets()
        self.supply_form_class=Form
        self.build_supplies()
        self.build_servers()
        self.build_batches()
        self.build_summary()
        self.build_logs()
        self.build_help()
        self.bind('<Control-n>', lambda e: self.receive_dialog())
        self.bind('<Control-f>', self.focus_search)
        self.bind('<F5>', lambda e: self.refresh())
        self.refresh()
        self.sync_navigation()

    def sync_navigation(self, event=None):
        current = self.tabs.select()
        if current in (str(self.supply_tab),str(self.server_tab)):
            self.metric_frame.pack_forget()
            self.header_add.pack_forget()
            self.tabs.pack_configure(pady=(20,0))
        else:
            self.metric_frame.pack(fill='x',pady=(23,20),before=self.tabs)
            self.header_add.pack(side='right',padx=(8,0))
            self.tabs.pack_configure(pady=0)
        for page, button, title, subtitle in self.navigation:
            chosen = str(page) == current
            button.select(chosen)
            if chosen:
                self.page_title.set(title)
                self.page_subtitle.set(subtitle)
        self.update_footer()

    def callback_error(self, exc_type, exc, tb):
        path = self.store.directory / "errors.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(datetime.now().isoformat() + "\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
        messagebox.showerror("操作未完成", f"{exc}\n\n错误详情已保存到 {path}", parent=self)

    def tree(self, parent, columns, widths, height=10):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode="extended")
        tree.heading_labels = dict(columns)
        for (key, label), width in zip(columns, widths):
            tree.heading(key, text=label, command=lambda k=key: self.sort_tree(tree, k))
            tree.column(key, width=width, minwidth=65, stretch=True)
        y = Scrollbar(frame, orient="vertical", command=tree.yview)
        x = Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree.tag_configure("pending", foreground="#9a6700")
        tree.tag_configure("out", foreground="#8290a3")
        tree.tag_configure("stripe", background="#f8fafd")
        tree.bind("<Control-a>", lambda e: (tree.selection_set(tree.get_children()), "break")[-1])
        return tree

    def sort_tree(self, tree, column, reverse=None):
        if reverse is None:
            reverse = getattr(tree, "sort_key", None) == (column, False)
        items = [(tree.set(i, column), i) for i in tree.get_children()]
        def key(item):
            value = item[0]
            return (0, int(value)) if value.isdigit() else (1, value.casefold())
        for index, (_, iid) in enumerate(sorted(items, key=key, reverse=reverse)):
            tree.move(iid, "", index)
        tree.sort_key = (column, reverse)
        for key, label in tree.heading_labels.items():
            tree.heading(key, text=label + (('  ↓' if reverse else '  ↑') if key==column else ''))
        if tree is getattr(self,'asset_tree',None):
            self.refresh_asset_headings()

    def build_assets(self):
        filters = ttk.Frame(self.asset_tab)
        filters.pack(fill="x", pady=(0, 9))
        self.query = tk.StringVar()
        self.search = ttk.Entry(filters, textvariable=self.query, width=34)
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<Return>", lambda e: self.refresh_assets())
        def paste_search(event):
            try:
                value=' '.join(self.clipboard_get().splitlines())
                try:
                    self.search.delete('sel.first','sel.last')
                except tk.TclError:
                    pass
                self.search.insert('insert',value)
                return 'break'
            except tk.TclError:
                return 'break'
        self.search.bind('<<Paste>>',paste_search)
        Button(filters, text="搜索", command=self.refresh_assets).pack(side="left", padx=6)
        Button(filters,text='批量搜索',command=self.batch_search_dialog).pack(side='left',padx=(0,6))
        self.category = tk.StringVar(value="全部类别")
        self.status = tk.StringVar(value="全部状态")
        self.scope = tk.StringVar(value="在账")
        for var, vals, width in ((self.category, ("全部类别",)+CATEGORIES, 10), (self.status, ("全部状态",)+STATUSES, 10),
                                 (self.scope, ("在账", "已转出", "全部"), 8)):
            cb = ttk.Combobox(filters, textvariable=var, values=vals, width=width, state="readonly")
            if var is self.category:
                self.category_picker=cb
            cb.pack(side="left", padx=(0, 6))
            cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_assets())
        Button(filters, text="重置", command=self.reset_filter).pack(side="left")
        bar = ttk.Frame(self.asset_tab)
        bar.pack(fill="x", pady=(0, 9))
        for label, callback in (("按条码选中", self.select_codes_dialog), ("编辑", self.edit_dialog),
          ("换位置", lambda: self.operation_dialog("换位置")), ("借出", lambda: self.operation_dialog("借出")),
          ("借出收回", lambda: self.operation_dialog("归还")), ("归还/转出挂账", lambda: self.operation_dialog("转出挂账")),
          ("物料历史", self.asset_history), ("导出当前列表", self.export_assets)):
            Button(bar, text=label, command=callback).pack(side="left", padx=(0, 5))
        ttk.Label(self.asset_tab, text="Ctrl 或 Shift 多选；双击查看详情与时间，修改请点“编辑”。", style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
        filterbar=ttk.Frame(self.asset_tab)
        filterbar.pack(fill='x',pady=(0,7))
        self.column_filter_text=tk.StringVar()
        ttk.Label(filterbar,textvariable=self.column_filter_text,style='Muted.TLabel').pack(side='left')
        Button(filterbar,text='清除列筛选',command=self.clear_column_filters).pack(side='right')
        self.asset_tree = self.tree(self.asset_tab,
          [("barcode", "条码 / 待补编号"), ("category", "类别"), ("model", "型号"), ("location", "位置 / 使用人"),
           ("status", "状态"), ("description", "详细描述"), ("note", "备注"), ("received_at", "挂账日期")], [200, 70, 120, 150, 75, 300, 260, 135])
        self.asset_tree.bind('<Configure>',self.layout_asset_columns)
        self.asset_tree.bind("<Double-1>", lambda e: self.asset_detail())
        self.asset_tree.bind("<<TreeviewSelect>>", lambda e: self.update_footer())
        self.init_column_filters()
        # Keep the import action apart from the already dense operation toolbar.

    def layout_asset_columns(self,event):
        # Reserve the first viewport for identification and notes; dates scroll into view.
        columns=('barcode','category','model','location','status','description','note')
        minimum=(180,65,85,115,65,160,170)
        extra=max(0,event.width-2-sum(minimum))
        weights=(.10,.02,.08,.13,.03,.34,.30)
        widths=[base+int(extra*weight) for base,weight in zip(minimum,weights)]
        widths[-1]+=int(extra)-sum(w-b for w,b in zip(widths,minimum))
        for key,width,base in zip(columns,widths,minimum):
            self.asset_tree.column(key,width=width,minwidth=base,stretch=False)
        self.asset_tree.column('received_at',width=135,minwidth=135,stretch=False)

    def build_batches(self):
        top = ttk.Frame(self.pending_tab)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="先记数量，之后按批次补条码。补录不会增加在账数量。", style="Muted.TLabel").pack(side="left")
        Button(top, text="为选中批次补条码", style="Accent.TButton", command=self.fill_dialog).pack(side="right")
        Button(top, text="查看批次物料", command=self.show_batch).pack(side="right", padx=8)
        self.batch_tree = self.tree(self.pending_tab, [("label", "批次"), ("category", "类别"), ("model", "型号"),
          ("total", "登记数"), ("on_account", "在账"), ("pending", "待补码"), ("note", "原始记录 / 备注")], [240, 65, 175, 70, 65, 70, 340])
        self.batch_tree.bind("<Double-1>", lambda e: self.fill_dialog())

    def build_summary(self):
        ttk.Label(self.summary_tab, text="按类别、型号、位置、状态汇总；全部为当前在账数量（含借出）。", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.summary_tree = self.tree(self.summary_tab, [("category", "类别"), ("model", "型号"), ("location", "位置 / 使用人"),
          ("status", "状态"), ("quantity", "数量"), ("pending", "待补条码")], [110, 260, 250, 110, 90, 110])

    def build_logs(self):
        top = ttk.Frame(self.log_tab)
        top.pack(fill="x", pady=(0, 10))
        self.log_query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.log_query, width=30)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.refresh_logs())
        for label, callback in (("搜索日志", self.refresh_logs), ("查看详情", self.log_detail),
                                ("撤销选中操作", self.undo_dialog), ("导出完整日志", self.export_logs)):
            Button(top, text=label, command=callback).pack(side="left", padx=(7, 0))
        ttk.Label(self.log_tab, text="日志只追加、不覆盖。撤销也会留档；可搜索条码、日期、机器、人员和原因。", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.log_tree = self.tree(self.log_tab, [("id", "编号"), ("at", "操作时间"), ("action", "操作"),
          ("summary", "变动摘要"), ("reason", "原因 / 来源"), ("state", "状态")], [65, 175, 100, 360, 220, 95])
        self.log_tree.bind("<Double-1>", lambda e: self.log_detail())

    def build_help(self):
        actions = ttk.Frame(self.help_tab)
        actions.pack(fill='x', pady=(0, 18))
        Button(actions, text='导出完整迁移包', style='Accent.TButton', command=self.export_transfer).pack(side='left')
        Button(actions, text='打开数据目录', command=lambda: os.startfile(self.store.directory)).pack(side='left', padx=10)
        Button(actions, text='立即备份', command=self.backup).pack(side='left')
        Button(actions, text='导入旧版台账', command=self.import_ledger).pack(side='left',padx=10)
        Button(actions,text='导入更新包',command=self.import_program_update).pack(side='left')
        self.build_online_updates(self.help_tab)
        ttk.Label(self.help_tab, text='换机三步：导出 ZIP  →  工作机完整解压  →  双击「物料台账.exe」',
                  font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=(0, 14))
        text = f"""开始使用

• 新增挂账：只填类别与数量也能保存。已有条码可以批量粘贴，一行一个。
• 补条码：到“批次 / 待补条码”选中批次；补码只完善身份，不会重复计数。
• 借出 / 归还 / 换位置：选中一件或多件物料后操作。借出仍挂在你名下。
• 转出挂账：用于正式移交，填写新归属和去向；转出后不计入当前在账。
• 编辑：单件可以改条码；多件可以统一补型号、位置、状态等，留空表示不修改。
• 操作日志：双击看修改前后。误操作可撤销；有后续变动时需先处理后续变动。
• 非挂账物品：记录个人持有的数量、位置和状态；归还减少持有数量，全部归还后仍可查历史。

快捷操作

Ctrl+N 新增挂账    Ctrl+F 搜索    F5 刷新    Ctrl+A 选中当前表格全部行
录入窗口 Ctrl+Enter 保存；条码支持换行、空格、逗号、顿号分隔。
USB 扫码枪使用键盘输入模式时，可在条码框连续输入；未做实体扫码枪测试。

数据与备份

所有保存都立即写入本地数据库，不依赖网络；关闭窗口即退出。
每天第一次修改前自动备份；右上“备份”可以随时保存完整数据库。
升级保留原 data 文件夹；旧数据结构自动兼容并提前备份，不会重置为初始数量。
“导入旧版台账”可选择最新 ledger.sqlite3，核对数量和最后日志时间后整本替换，导入前自动备份。
CSV 供 Excel / WPS 查看；完整日志导出为 JSONL，包含修改前后快照。
备份恢复：退出程序，保留现有数据库副本，再把备份复制为 ledger.sqlite3。
详细步骤见同目录 README.md。复制整个 data 文件夹可一起保留日志和备份。

换机与便携运行

EXE 版本自带运行环境，目标电脑无需 Python、无需安装、无需联网。
面向 Windows 10 / 11 64 位电脑；请完整解压到可写的普通文件夹。
不要只复制 EXE，必须带上 _internal 和 data 文件夹。
“导出完整迁移包”包含程序、当前台账、全部操作日志和已有数据库备份。
导出后本机的新变动不会自动同步到工作机。建议迁移后只在一台电脑维护主账。
正在使用的数据库位于下方路径；所有相对默认路径均基于 EXE 所在目录。

数据目录：{self.store.directory}

首次使用与在线更新

公开发布程序不内置个人清单，新目录首次启动为空台账；升级继续使用原data。
“更新设置”配置GitHub发布仓库后，启动时自动检查；也可手动点击“检查更新”。
确认新版后自动下载、校验、备份并重启；网络不可用时继续使用本地台账。
"""
        box = tk.Text(self.help_tab, wrap="word", font=("Microsoft YaHei UI", 10), background="white", relief="flat", padx=18, pady=12)
        scroll = Scrollbar(self.help_tab, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def refresh(self):
        self.category_picker.configure(values=['全部类别']+self.store.categories())
        for key, val in self.store.stats().items():
            self.metrics[key].set(str(val))
        self.refresh_assets()
        self.batch_rows = {r['id']: r for r in self.store.batches()}
        self.batch_tree.delete(*self.batch_tree.get_children())
        for row in sorted(self.batch_rows.values(), key=lambda r: (r['pending'] == 0, -r['pending'])):
            self.batch_tree.insert("", "end", iid=row['id'], values=[row[k] for k in ("label", "category", "model", "total", "on_account", "pending", "note")], tags=("pending",) if row['pending'] else ())
        self.summary_tree.delete(*self.summary_tree.get_children())
        counts, pending = Counter(), Counter()
        for r in self.store.assets():
            key = (r['category'], r['model'] or "待补型号", r['location'], r['status'])
            counts[key] += 1
            pending[key] += int(r['barcode'] is None)
        for key, count in sorted(counts.items()):
            self.summary_tree.insert("", "end", values=(*key, count, pending[key]))
        self.refresh_logs()
        self.refresh_supplies()
        self.refresh_servers()

    def refresh_assets(self):
        self.visible_rows = self.store.assets(self.query.get(), self.category.get(), self.status.get(), self.scope.get())
        if getattr(self, 'only_uncertain', False):
            self.visible_rows = [r for r in self.visible_rows if r['location']=='待确认' or r['status']=='待确认'
                                 or not r['model'] or '待确认' in r['model']]
        self.visible_rows=self.filter_asset_rows(self.visible_rows)
        self.render_assets(self.visible_rows)
        order=getattr(self.asset_tree,'sort_key',None)
        if order:
            self.sort_tree(self.asset_tree,order[0],reverse=order[1])
        self.refresh_asset_headings()

    def render_assets(self, rows):
        self.visible_rows = rows
        self.asset_rows = {r['id']: r for r in rows}
        self.asset_tree.delete(*self.asset_tree.get_children())
        for index, r in enumerate(sorted(rows, key=lambda r: r['barcode'] is None)):
            barcode = r['barcode'] or ("待补 · " + r['id'][:8])
            tags = ("out",) if r['status'] == "已转出" else (("pending",) if not r['barcode'] else ())
            tags += ('stripe',) if index % 2 else ()
            self.asset_tree.insert("", "end", iid=r['id'], values=(barcode, r['category'], r['model'] or "待补型号",
              r['location'], r['status'], r['description'], '；'.join(v for v in (r['note'],r['platform_note']) if v), r['received_at'][:10] or '未记录'), tags=tags)
        self.update_footer()

    def update_footer(self):
        if hasattr(self, "footer"):
            if self.tabs.select()==str(self.server_tab):
                self.footer.set('服务器物料与原台账共用记录，变更自动留痕')
                return
            if self.tabs.select()==str(self.supply_tab):
                self.footer.set('本地保存 · 非挂账物品独立统计 · 操作自动留痕    |    关闭窗口即退出，不驻留后台')
                return
            self.footer.set(f"本地保存 · 当前列表 {len(self.asset_tree.get_children())} 件 · 已选 {len(self.asset_tree.selection())} 件    |    关闭窗口即退出，不驻留后台")
            if getattr(self, 'only_uncertain', False):
                self.footer.set(self.footer.get() + " · 仅显示待完善；点击重置退出")

    def metric_clicked(self, key):
        self.reset_filter()
        if key == 'pending':
            self.tabs.select(self.pending_tab)
            return
        self.tabs.select(self.asset_tab)
        if key == 'lent':
            self.status.set('借出')
        elif key == 'uncertain':
            self.only_uncertain = True
        self.refresh_assets()

    def reset_filter(self):
        self.column_filters.clear()
        self.only_uncertain = False
        self.query.set("")
        self.category.set("全部类别")
        self.status.set("全部状态")
        self.scope.set("在账")
        self.refresh_assets()

    def focus_search(self, event=None):
        self.tabs.select(self.asset_tab)
        self.search.focus_set()
        self.search.selection_range(0, "end")
        return "break"

    def selected(self):
        ids = list(self.asset_tree.selection())
        if not ids:
            messagebox.showinfo("先选择物料", "请在当前台账里选择物料，可使用 Ctrl 或 Shift 多选。", parent=self)
        return ids

    def receive_dialog(self,location='待确认',status='在库'):
        form = Form(self, "新增挂账", "先记数量也可以；没有条码的物料会自动进入待补清单。")
        form.field("category", "类别 *", "内存", self.store.categories())
        form.field("model", "型号（可后补）")
        form.field("quantity", "本次总数量 *", "1")
        form.field("location", "位置 / 使用人", location, self.locations())
        form.field("status", "当前状态", status, STATUSES[:-1], True)
        form.field("source", "来源 / 转入人")
        form.field("label", "批次名称（可不填）")
        codes = form.text("codes", "条码（可空；一行一个，支持批量粘贴 / 扫码）", height=5)
        hint = tk.StringVar(value="已输入 0 个条码")
        ttk.Label(form.body, textvariable=hint, style="Muted.TLabel").grid(row=form.row, column=0, columnspan=2, sticky="w")
        form.row += 1
        def count(event=None):
            try:
                hint.set(f"已输入 {len(parse_codes(form.get('codes')))} 个条码")
            except ValueError as exc:
                hint.set(str(exc))
        codes.bind("<KeyRelease>", count)
        form.field("note", "备注（可不填）")
        form.field('occurred_at','挂账时间（留空为当前）')
        def save():
            try:
                qty = int(form.get("quantity"))
            except ValueError:
                raise ValueError("数量必须是整数。")
            self.store.receive(form.get("category"), form.get("model"), qty, parse_codes(form.get("codes")),
              location=form.get("location"), status=form.get("status"), source=form.get("source"),
              note=form.get("note"), label=form.get("label"),occurred_at=form.get('occurred_at'))
        form.finish(save, "确认入账")
        return form

    def locations(self):
        return sorted({r['location'] for r in self.store.assets(scope="全部")} |
                      {r['location'] for r in self.store.supply_rows()} |
                      {r['location'] for r in self.store.servers()} | {"待确认", "盒子里"})

    def fill_dialog(self):
        selection = self.batch_tree.selection()
        if len(selection) != 1:
            messagebox.showinfo("选择批次", "请先选择一个需要补条码的批次。", parent=self)
            return
        batch = self.batch_rows[selection[0]]
        if not batch['pending']:
            messagebox.showinfo("条码已齐", "该批次的在账物料没有待补条码。", parent=self)
            return
        form = Form(self, "补录条码", f"{batch['label']}\n当前在账 {batch['on_account']} 件，待补 {batch['pending']} 个。可以分多次补齐。\n原始备注：{batch['note']}")
        entry = form.text("codes", "逐个扫码或粘贴条码（一行一个）", height=10)
        form.field('occurred_at','补码时间（留空为当前）')
        form.finish(lambda: self.store.fill_codes(batch['id'], parse_codes(form.get("codes")),occurred_at=form.get('occurred_at')), "保存条码")
        entry.focus_set()
        return form

    def show_batch(self):
        selected = self.batch_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo("选择批次", "请先选择一个批次。", parent=self)
            return
        self.reset_filter()
        self.scope.set("全部")
        self.render_assets([r for r in self.store.assets(scope="全部") if r['batch_id'] == selected[0]])
        self.tabs.select(self.asset_tab)
        self.footer.set(self.footer.get() + " · 当前为选中批次；搜索或重置返回普通列表")

    def edit_dialog(self):
        ids = self.selected()
        if not ids:
            return
        single = len(ids) == 1
        row = self.asset_rows[ids[0]]
        form = Form(self, "编辑物料" if single else f"批量编辑 {len(ids)} 件", "保存后自动记录修改前后。" if single else "只填写要统一修改的字段；留空表示保持原值。")
        keys = ["barcode"] if single else []
        keys += ["category", "model", "owner", "location", "status", "note", "received_at"]
        for key in keys:
            opts = self.store.categories() if key == "category" else STATUSES if key == "status" else self.locations() if key == "location" else None
            if opts and not single:
                opts = ("",) + tuple(opts)
            form.field(key, LABELS[key], (row[key] or "") if single else "", opts, key == "status")
        form.field("reason", "修改原因（可不填）")
        form.field('occurred_at','变更时间（留空为当前）')
        def save():
            changes = {k: form.get(k) for k in keys if single or form.get(k)}
            self.store.update(ids, changes, "编辑物料", form.get("reason"),occurred_at=form.get('occurred_at'))
        form.finish(save)
        return form

    def operation_dialog(self, action):
        ids = self.selected()
        if not ids:
            return
        rows = [self.asset_rows[i] for i in ids]
        if any(r['status'] == "已转出" for r in rows):
            messagebox.showinfo("包含已转出物料", "已转出物料如需重新挂账，请使用编辑，明确修改挂账归属与状态。", parent=self)
            return
        if action == "归还" and any(r['status'] != "借出" for r in rows):
            messagebox.showinfo("请检查选择", "归还操作仅适用于状态为“借出”的物料。其他状态可使用编辑或换位置。", parent=self)
            return
        if action == "借出" and any(r['status'] == "借出" for r in rows):
            messagebox.showinfo("请检查选择", "所选物料包含已经借出的记录，请先确认实际归还情况。", parent=self)
            return
        preview = "、".join(r['barcode'] or ("待补·"+r['id'][:8]) for r in rows[:4])
        hint = f"本次处理 {len(ids)} 件：{preview}{'…' if len(ids)>4 else ''}\n"
        hint += "转出后不计入当前在账，历史仍保留。" if action == "转出挂账" else "操作只改变去向或状态，不增加或减少挂账总数。"
        display={'归还':'借出收回（别人还给我）','转出挂账':'归还/转出挂账（减少挂账数）'}.get(action,action)
        form = Form(self, f"{display} · {len(ids)} 件", hint)
        form.field("location", "借用人 / 去向 *" if action == "借出" else "新位置 / 接收人 *", "", self.locations())
        if action == "归还":
            form.field("status", "归还后状态", "已取回", ("已取回", "在库", "在用"), True)
        if action == "转出挂账":
            form.field("owner", "新的挂账归属 *")
        form.field("reason", "备注 / 交接说明")
        form.field('occurred_at',{'借出':'借出时间','归还':'收回时间','转出挂账':'归还/转出时间'}.get(action,'变动时间')+'（留空为当前）')
        def save():
            if not form.get("location"):
                raise ValueError("请填写去向或接收人。")
            changes = {"location": form.get("location")}
            if action == "借出":
                changes['status'] = "借出"
            elif action == "归还":
                changes['status'] = form.get("status")
            elif action == "转出挂账":
                if not form.get("owner"):
                    raise ValueError("请填写新的挂账归属。")
                changes.update(status="已转出", owner=form.get("owner"))
            self.store.update(ids, changes, action, form.get("reason"),occurred_at=form.get('occurred_at'))
        form.finish(save, "确认" + action)
        return form

    def select_codes_dialog(self):
        form = Form(self, "按条码批量选中", "粘贴或扫描一组条码，匹配后批量换位置、借出或转出。未找到时会提示，不会悄悄漏选。")
        entry = form.text("codes", "条码列表", height=10)
        def select():
            codes = parse_codes(form.get("codes"))
            if not codes:
                raise ValueError("请输入至少一个条码。")
            rows = self.store.assets(scope="全部")
            by_code = {r['barcode']: r['id'] for r in rows if r['barcode']}
            missing = [c for c in codes if c not in by_code]
            if missing:
                raise ValueError("未找到：" + "、".join(missing[:8]))
            self.query.set("")
            self.only_uncertain = False
            self.category.set("全部类别")
            self.status.set("全部状态")
            self.scope.set("全部")
            self.column_filters.clear()
            # Form refreshes once after callback, so defer selection until then.
            def apply_selection():
                self.tabs.select(self.asset_tab)
                self.asset_tree.selection_set([by_code[c] for c in codes])
                self.asset_tree.see(by_code[codes[0]])
            self.after_idle(apply_selection)
        form.finish(select, "选中物料")
        entry.focus_set()
        return form

    def batch_search_dialog(self):
        form=Form(self,'批量搜索','每行一个条码，也支持空格、逗号分隔；任一关键词命中即显示。搜索后清除类别和状态筛选，显示全部范围。')
        form.text('terms','粘贴条码 / 型号 / 关键词',height=10)
        def search():
            if not form.get('terms'):
                raise ValueError('请填写要搜索的内容。')
            self.category.set('全部类别')
            self.status.set('全部状态')
            self.scope.set('全部')
            self.only_uncertain=False
            self.column_filters.clear()
            self.query.set(' '.join(form.get('terms').splitlines()))
            self.store.assets(self.query.get(),scope='全部')
        form.finish(search,'搜索')
        return form

    def asset_detail(self):
        ids=self.selected()
        if len(ids)!=1:
            return
        row=self.asset_rows[ids[0]]
        win=tk.Toplevel(self)
        win.title('物料详情与时间')
        win.geometry('680x610')
        body=ttk.Frame(win,padding=24)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=row['barcode'] or '待补条码',style='Heading.TLabel').pack(anchor='w',pady=(0,14))
        box=tk.Text(body,wrap='word',font=('Microsoft YaHei UI',10),relief='flat',padx=10,pady=10)
        scroll=Scrollbar(body,command=box.yview)
        scroll.pack(side='right',fill='y')
        box.configure(yscrollcommand=scroll.set)
        box.pack(fill='both',expand=True)
        keys=('category','model','status','owner','location','received_at','lent_at','recovered_at','transferred_at','occurred_at','created_at','note','platform_note','puid','sn','description')
        box.insert('1.0','\n\n'.join(f"{LABELS[k]}：{row[k] or '未记录'}" for k in keys)+'\n\n每次借还的时间均保留在物料历史中。')
        box.configure(state='disabled')
        return win

    def refresh_logs(self):
        self.log_rows = {str(r['id']): r for r in self.store.history(self.log_query.get())}
        self.log_tree.delete(*self.log_tree.get_children())
        for ident, e in self.log_rows.items():
            state = "已撤销" if e['undone'] else "可撤销*" if e['reversible'] else "存档"
            self.log_tree.insert("", "end", iid=ident, values=(e['id'], readable_date(e['at']), e['action'], e['summary'], e['reason'], state))

    def asset_history(self):
        ids = self.selected()
        if len(ids) != 1:
            if ids:
                messagebox.showinfo("选择一件物料", "请只选择一件物料查看其完整历史。", parent=self)
            return
        self.log_query.set(ids[0])
        self.refresh_logs()
        self.tabs.select(self.log_tab)

    def log_detail(self):
        sel = self.log_tree.selection()
        if len(sel) != 1:
            return
        event = self.log_rows[sel[0]]
        before, after = json.loads(event['before_json']), json.loads(event['after_json'])
        lines = [f"日志 #{event['id']}    录入时间：{readable_date(event['at'])}",f"业务发生时间：{event.get('occurred_at') or '旧记录未填写'}", event['summary'], f"原因 / 来源：{event['reason'] or '未填写'}", ""]
        old = {r['id']: r for r in before['assets']}
        for r in after['assets']:
            lines.append(f"{r['barcode'] or ('待补 · '+r['id'][:8])}  |  {r['category']}  {r['model']}")
            prior = old.get(r['id'])
            for key, label in LABELS.items():
                if key in ("created_at", "updated_at", "batch_id"):
                    continue
                value = r.get(key)
                if prior is None:
                    lines.append(f"  {label}：{value if value is not None else '待补'}")
                elif prior.get(key) != value:
                    lines.append(f"  {label}：{prior.get(key) if prior.get(key) is not None else '待补'} → {value if value is not None else '待补'}")
            lines.append("")
        for table,title in [('supplies','非挂账物品'),('supply_loans','借出明细'),('servers','服务器')]:
            previous={r['id']:r for r in before.get(table,[])}
            labels={'name':'名称','spec':'规格','unit':'单位','location':'位置','quantity':'数量','threshold':'提醒阈值',
                'note':'备注','status':'状态','borrowed_at':'借用时间','returned_at':'本次归还时间','active':'有效记录','person':'借用人 / 机器','remaining':'待收回数量'}
            for row in after.get(table,[]):
                lines.append(f"{title} · {row.get('name',row.get('person',''))}")
                old=previous.get(row['id'])
                for key,label in labels.items():
                    if key in row and (old is None or old.get(key)!=row[key]):
                        lines.append(f"  {label}：{row[key]}" if old is None else f"  {label}：{old.get(key)} → {row[key]}")
                lines.append('')
        win = tk.Toplevel(self)
        win.title(f"日志 #{event['id']} · 修改前后")
        win.geometry("850x600")
        frame = ttk.Frame(win, padding=15)
        frame.pack(fill="both", expand=True)
        box = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10), padx=12, pady=12)
        scroll = Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        box.pack(fill="both", expand=True)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")
        return win

    def undo_dialog(self):
        sel = self.log_tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("选择日志", "请先选择一条需要撤销的操作。", parent=self)
            return
        e = self.log_rows[sel[0]]
        if not e['reversible'] or e['undone']:
            messagebox.showinfo("不能撤销", "初始盘点、撤销日志和已经撤销的记录不能再次撤销。", parent=self)
            return
        form = Form(self, "撤销操作", f"将恢复日志 #{e['id']} 之前的状态：\n{e['summary']}\n撤销也会追加一条日志；若相关物料已有后续修改，本次撤销会被阻止。")
        form.field("reason", "撤销原因 *")
        form.finish(lambda: self.store.undo(e['id'], form.get("reason")), "确认撤销")
        return form

    def backup(self):
        try:
            path = self.store.backup()
            messagebox.showinfo("备份完成", f"台账与全部日志已备份：\n{path}", parent=self)
        except (OSError, ValueError) as exc:
            messagebox.showerror("备份未完成", str(exc), parent=self)

    def export_assets(self):
        path = filedialog.asksaveasfilename(parent=self, title="导出当前筛选列表", defaultextension=".csv",
          initialfile="物料台账-"+datetime.now().strftime("%Y%m%d")+".csv", filetypes=[("Excel / WPS 可打开的 CSV", "*.csv")])
        if path:
            self.store.export_csv(path, self.visible_rows)
            messagebox.showinfo("导出完成", f"已导出当前列表 {len(self.visible_rows)} 件。\n{path}", parent=self)

    def export_logs(self):
        path = filedialog.asksaveasfilename(parent=self, title="导出完整操作日志", defaultextension=".jsonl",
          initialfile="物料操作日志-"+datetime.now().strftime("%Y%m%d")+".jsonl", filetypes=[("含完整前后快照的日志", "*.jsonl")])
        if path:
            self.store.export_history(path)
            messagebox.showinfo("导出完成", "完整日志已导出（包含未显示在搜索结果中的记录）。", parent=self)

    def export_transfer(self):
        if getattr(self, 'exporting', False):
            messagebox.showinfo('正在导出', '迁移包仍在生成，请稍候。', parent=self)
            return
        if not (BASE / EXE_NAME).is_file():
            messagebox.showinfo('请使用便携版', '请通过同目录的物料台账.exe 启动后导出迁移包。', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='保存完整迁移包', defaultextension='.zip',
            initialfile='物料台账-迁移包-'+datetime.now().strftime('%Y%m%d-%H%M')+'.zip', filetypes=[('ZIP 便携包','*.zip')])
        if not path:
            return
        self.exporting = True
        self.footer.set('正在生成完整迁移包…  台账仍可浏览，请等待导出完成后关闭。')
        result = []
        def worker():
            try:
                result.append(export_portable(BASE, SnapshotSource(self.store.directory), path))
            except Exception as exc:
                result.append(exc)
        thread = threading.Thread(target=worker, name='material-transfer')
        thread.start()
        def completed():
            if thread.is_alive():
                self.after(150, completed)
                return
            self.exporting = False
            self.update_footer()
            if isinstance(result[0], Exception):
                messagebox.showerror('迁移包未完成', str(result[0]), parent=self)
            else:
                messagebox.showinfo('迁移包已就绪', f'复制到工作机并完整解压，再双击物料台账.exe。\n\n{result[0]}\n\n含导出时点的台账、日志与备份；之后的修改不会自动同步。', parent=self)
        self.after(150, completed)

    def import_ledger(self):
        from data_import import inspect_database, import_database
        if getattr(self,'exporting',False):
            messagebox.showinfo('请稍候','请等迁移包导出完成后再导入台账。',parent=self)
            return
        source=filedialog.askopenfilename(parent=self,title='选择旧版 ledger.sqlite3 或数据库备份',
            filetypes=[('物料台账数据库','*.sqlite3')])
        if not source:
            return
        try:
            summary=inspect_database(source)
            current=self.store.stats()['total']
            message=(f"准备导入：{summary['on_account']} 件挂账、{summary['supplies']} 种非挂账物品、{summary['logs']} 条日志。\n"
                f"最后日志：{summary['last_log']}\n来源：{source}\n\n"
                f"当前为 {current} 件挂账。导入会替换当前台账，不做合并。\n导入前会自动备份当前完整台账。是否继续？")
            if not messagebox.askyesno('核对后导入',message,parent=self):
                return
            self.store,backup=import_database(self.store,source)
            self.reset_filter()
            self.log_query.set('')
            self.refresh()
            messagebox.showinfo('导入完成',f'台账、原日志已导入，旧版结构已兼容升级。\n\n导入前数据保留在：\n{backup}',parent=self)
        except (ValueError,OSError) as exc:
            messagebox.showerror('未导入',str(exc),parent=self)

    def import_program_update(self,path=None,preconfirmed=False):
        if not getattr(sys,'frozen',False):
            messagebox.showinfo('本地更新','请在便携 EXE 版本中使用本地更新。',parent=self)
            return
        if getattr(self,'exporting',False):
            messagebox.showinfo('请稍候','请等待迁移包导出完成。',parent=self)
            return
        if path is None:
            path=filedialog.askopenfilename(parent=self,title='选择物料台账更新包（ZIP）',filetypes=[('物料台账更新包','*.zip')])
        if not path:
            return
        from updater import unpack_update,prepare_update
        import tempfile
        import subprocess
        try:
            # Preview the package version and fully verify it before closing the app.
            with tempfile.TemporaryDirectory(prefix='ledger-update-check-') as folder:
                manifest=unpack_update(path,Path(folder)/'new')
            if not preconfirmed and not messagebox.askyesno('确认更新',f"当前版本：{VERSION}\n更新版本：{manifest['version']}\n\n程序将备份台账及旧版程序，验证新版后自动重启。\ndata 文件夹保留在当前目录。是否更新？",parent=self):
                return
            self.configure(cursor='watch')
            self.update_idletasks()
            plan,manifest=prepare_update(BASE,self.store,path)
            helper=plan.parent/'helper'/EXE_NAME
            subprocess.Popen([str(helper),'--apply-update',str(plan)],creationflags=subprocess.CREATE_NO_WINDOW)
            self.close()
        except (ValueError,OSError) as exc:
            self.configure(cursor='')
            messagebox.showerror('未更新',str(exc),parent=self)

    def close(self):
        if getattr(self, 'exporting', False):
            messagebox.showinfo('正在导出', '请等迁移包生成完成后再关闭。', parent=self)
            return
        self.store.close()
        self.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=BASE / "data")
    parser.add_argument('--verify-runtime', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--apply-update',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--update-ready',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.apply_update:
        from updater import run_update
        run_update(args.apply_update)
        return
    if os.name == "nt":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    lock = open(args.data_dir / ".instance.lock", "a+b")
    if os.name == "nt":
        import msvcrt
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            # Bring the existing app forward instead of opening a second writer.
            handle = ctypes.windll.user32.FindWindowW(None, TITLE)
            if handle:
                ctypes.windll.user32.ShowWindow(handle, 9)
                ctypes.windll.user32.SetForegroundWindow(handle)
            lock.close()
            return
    store = Store(args.data_dir)
    app = App(store)
    if getattr(sys,'frozen',False) and not args.verify_runtime:
        app.after(5000,lambda:app.check_online_update(automatic=True))
    if args.update_ready:
        app.withdraw()
        args.update_ready.write_text(json.dumps(dict(version=VERSION,ready=True)),encoding='utf-8')
        app.deiconify()
    if args.verify_runtime:
        # Read-only app startup check used on a separately extracted release copy.
        def report_runtime():
            try:
                report = dict(frozen=bool(getattr(sys, 'frozen', False)), version=VERSION,
                    executable=sys.executable, base=str(BASE), database=str(store.path.resolve()),
                    stats=store.stats(), log_count=len(store.history()),
                    visible_assets=len(app.asset_tree.get_children()),
                    control_theme_assets=len(app._control_images),
                    integrity=store.db.execute('PRAGMA integrity_check').fetchone()[0])
                args.verify_runtime.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            finally:
                app.close()
        app.after(700, report_runtime)
    app.mainloop()
    lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        try:
            with (BASE / "startup-error.log").open("a", encoding="utf-8") as log:
                log.write(datetime.now().isoformat() + "\n" + error)
        except OSError:
            pass
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("物料台账启动失败", "详情见程序目录 startup-error.log\n\n" + error[-1200:])
        root.destroy()
