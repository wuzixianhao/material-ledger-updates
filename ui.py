"""Small, event-driven native UI components. No extra runtime dependencies."""
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, ttk

BG = '#f3f6fb'
INK = '#17263c'
MUTED = '#718097'
ACCENT = '#287aef'
NAV = '#142238'


class Scrollbar(ttk.Scrollbar):
    """Hide controls when there is no overflow, restoring their original layout."""
    def set(self, first, last):
        super().set(first,last)
        needed = float(first)>0.000001 or float(last)<0.999999
        manager = self.winfo_manager()
        if not needed and manager == 'grid':
            self._hidden_layout = ('grid',None,None)
            self.grid_remove()
        elif not needed and manager == 'pack':
            info=self.pack_info()
            siblings=self.master.pack_slaves()
            index=siblings.index(self)
            following=siblings[index+1] if index+1<len(siblings) else None
            self._hidden_layout=('pack',info,following)
            self.pack_forget()
        elif needed and not manager and getattr(self,'_hidden_layout',None):
            kind,info,following=self._hidden_layout
            self._hidden_layout=None
            if kind=='grid':
                self.grid()
            else:
                if following and following.winfo_exists() and following.winfo_manager()=='pack':
                    info['before']=following
                self.pack(**info)


def rounded(canvas, x, y, w, h, radius=12, **kwargs):
    r = min(radius, w/2, h/2)
    return canvas.create_polygon(x+r, y, x+w-r, y, x+w, y, x+w, y+r,
        x+w, y+h-r, x+w, y+h, x+w-r, y+h, x+r, y+h, x, y+h,
        x, y+h-r, x, y+r, x, y, smooth=True, splinesteps=24, **kwargs)


class Button(tk.Canvas):
    def __init__(self, parent, text, command=None, style='', **kwargs):
        self.command, self.text = command, text
        self.kind = 'primary' if 'Accent' in style else 'danger' if 'Danger' in style else 'secondary'
        self.state = kwargs.pop('state', 'normal')
        self.face = tkfont.Font(family='Microsoft YaHei UI', size=10, weight='bold' if self.kind=='primary' else 'normal')
        try:
            parent_style = parent.cget('style') or parent.winfo_class()
        except tk.TclError:
            parent_style = parent.winfo_class()
        bg = ttk.Style().lookup(parent_style, 'background') or BG
        try:
            bg = parent.cget('background')
        except tk.TclError:
            pass
        super().__init__(parent, width=self.face.measure(text)+30, height=max(38, self.face.metrics('linespace')+18),
                         background=bg, highlightthickness=0, takefocus=1, cursor='hand2', **kwargs)
        self.hover = False
        self.pressed = False
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Enter>', lambda e: self.over(True))
        self.bind('<Leave>', lambda e: self.over(False))
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<Return>', lambda e: self.invoke())
        self.bind('<space>', lambda e: self.invoke())
        self.bind('<FocusIn>', lambda e: self.draw())
        self.bind('<FocusOut>', lambda e: self.draw())

    def over(self, hovered):
        self.hover = hovered
        self.draw()

    def press(self, event):
        if self.state != 'disabled':
            self.focus_set()
            self.pressed = True
            self.draw()

    def release(self, event):
        armed = self.pressed
        self.pressed = False
        self.draw()
        if armed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        if self.state != 'disabled' and self.command:
            self.command()
        return 'break'

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if self.state == 'disabled':
            fill, fg, border = '#eef1f5', '#abb5c2', '#eef1f5'
        elif self.kind == 'primary':
            fill, fg, border = ('#1454b8' if self.pressed else '#1b65d2' if self.hover else ACCENT), '#ffffff', ACCENT
        elif self.kind == 'danger':
            fill, fg, border = ('#ffe1e1' if self.hover else '#fff0ef'), '#b94b48', '#fff0ef'
        else:
            fill, fg, border = ('#d5e3f8' if self.pressed else '#e6eefc' if self.hover else '#f2f5fa'), '#354c6b', '#f2f5fa'
        if self.focus_get() == self:
            border = ACCENT
        rounded(self, 1, 1, w-2, h-2, 9, fill=fill, outline=border, width=2)
        self.create_text(w/2, h/2, text=self.text, fill=fg, font=self.face)


class MetricCard(tk.Canvas):
    def __init__(self, parent, label, subtitle, variable, color, index, command):
        super().__init__(parent, background=BG, highlightthickness=0, height=137, width=180, cursor='hand2')
        self.label, self.subtitle, self.variable = label, subtitle, variable
        self.color, self.index, self.command = color, index, command
        self.hover = False
        self.bind('<Enter>', lambda e: self.over(True))
        self.bind('<Leave>', lambda e: self.over(False))
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Button-1>', lambda e: command())
        self.trace_id = variable.trace_add('write', lambda *args: self.draw())

    def over(self, value):
        self.hover = value
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        rounded(self, 1, 4, w-2, h-5, 15, fill='#e8edf5', outline='')
        rounded(self, 1, 1, w-2, h-6, 15, fill='#fafdff' if self.hover else 'white', outline='#bfd7f6' if self.hover else '')
        self.create_text(19, 24, text=self.label, anchor='w', font=('Microsoft YaHei UI', 10), fill=MUTED)
        self.create_text(18, 69, text=self.variable.get(), anchor='w', font=('Segoe UI', 29, 'bold'), fill=INK)
        self.create_oval(w-42, 17, w-20, 39, fill=self.color, outline='')
        self.create_text(w-31, 28, text=self.index, fill='white', font=('Segoe UI', 9, 'bold'))
        self.create_text(19, 109, text=self.subtitle, anchor='w', font=('Microsoft YaHei UI', 9), fill=MUTED)


class SidebarButton(tk.Frame):
    def __init__(self, parent, text, symbol, command):
        super().__init__(parent, bg=NAV, cursor='hand2', height=48)
        self.pack_propagate(False)
        self.selected = False
        self.bar = tk.Frame(self, bg=NAV, width=3)
        self.bar.pack(side='left', fill='y', pady=11)
        self.icon = tk.Label(self, text=symbol, font=('Segoe UI Symbol', 16), bg=NAV, fg='#8699b6', width=3)
        self.icon.pack(side='left', padx=(8, 2))
        self.label = tk.Label(self, text=text, font=('Microsoft YaHei UI', 10), bg=NAV, fg='#aab9ce')
        self.label.pack(side='left')
        for widget in (self, self.bar, self.icon, self.label):
            widget.bind('<Button-1>', lambda e: command())
            widget.bind('<Enter>', lambda e: self.paint(True))
            widget.bind('<Leave>', lambda e: self.paint(False))

    def select(self, value):
        self.selected = value
        self.paint(False)

    def paint(self, hover):
        value = self.selected
        bg = '#223953' if value else '#1b2d46' if hover else NAV
        self.configure(bg=bg)
        self.bar.configure(bg='#56a6ff' if value else NAV)
        self.label.configure(bg=bg, fg='white' if value else '#aab9ce')
        self.icon.configure(bg=bg, fg='#8ec2ff' if value else '#8699b6')


def setup_style(root):
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei UI', 10), background='white', foreground=INK)
    style.configure('Workspace.TFrame', background=BG)
    style.configure('Sash', sashthickness=12, gripcount=0)
    style.configure('Workspace.TLabel', background=BG, foreground=MUTED)
    style.configure('PageTitle.TLabel', font=('Microsoft YaHei UI', 22, 'bold'), background=BG, foreground=INK)
    style.configure('Heading.TLabel', font=('Microsoft YaHei UI', 18, 'bold'))
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('TEntry', padding=(10, 8), fieldbackground='#f8fafc', bordercolor='#dce4ef', lightcolor='#dce4ef', darkcolor='#dce4ef')
    style.map('TEntry', bordercolor=[('focus', ACCENT)])
    style.configure('TCombobox', padding=(8, 7), fieldbackground='#f8fafc', background='#f8fafc',
                    bordercolor='#dce4ef', lightcolor='#dce4ef', darkcolor='#dce4ef', arrowsize=12)
    style.map('TCombobox', fieldbackground=[('readonly', '#f8fafc')], selectbackground=[('readonly', '#f8fafc')],
              selectforeground=[('readonly', INK)], bordercolor=[('focus', ACCENT)])
    style.configure('Treeview', rowheight=37, background='white', fieldbackground='white', borderwidth=0,
                    bordercolor='white', lightcolor='white', darkcolor='white')
    style.configure('Treeview.Heading', padding=(10, 12), font=('Microsoft YaHei UI', 9, 'bold'),
                    background='#f0f4f9', foreground='#6a7c94', relief='flat', borderwidth=0)
    style.map('Treeview.Heading', background=[('active', '#e6eef8')])
    style.map('Treeview', background=[('selected', '#e1edff')], foreground=[('selected', '#1c56a0')])
    style.configure('TNotebook', background='white', borderwidth=0, tabmargins=0,
                    bordercolor='white', lightcolor='white', darkcolor='white')
    style.layout('TNotebook.Tab', [])
    style.configure('Vertical.TScrollbar', background='#c5d0df', troughcolor='#f5f7fa', borderwidth=0, arrowsize=11)
    style.configure('Horizontal.TScrollbar', background='#c5d0df', troughcolor='#f5f7fa', borderwidth=0, arrowsize=11)
    install_controls(root, style)
    return style


def install_controls(root, style):
    """Image-backed ttk elements retain native drag, wheel and keyboard behavior."""
    folder = Path(__file__).resolve().parent/'ui_assets'
    images = {p.stem: tk.PhotoImage(master=root, file=str(p)) for p in folder.glob('*.png')}
    root._control_images = images  # Keep Tcl image handles alive for this root.
    if not images:
        return
    for orientation, axis in [('Vertical','v'),('Horizontal','h')]:
        track = f'Modern.{orientation}.Scrollbar.trough'
        thumb = f'Modern.{orientation}.Scrollbar.thumb'
        style.element_create(track,'image',images['track-'+axis],border=10,padding=0,sticky='nswe')
        style.element_create(thumb,'image',images['thumb-'+axis+'-normal'],
            ('pressed',images['thumb-'+axis+'-pressed']),('active',images['thumb-'+axis+'-hover']),
            border=10,padding=0,sticky='nswe')
        style.layout(orientation+'.TScrollbar',[(track,{'sticky':'nswe','children':[(thumb,{'sticky':'nswe'})]})])
        style.configure(orientation+'.TScrollbar',width=24,arrowsize=0)
    for name in ['Entry','Combobox']:
        field = 'Modern.'+name+'.field'
        style.element_create(field,'image',images['field-normal'],('focus',images['field-focus']),
            ('active',images['field-hover']),border=12,padding=(10,0),sticky='nswe')
        if name == 'Entry':
            children = [('Entry.padding',{'sticky':'nswe','children':[('Entry.textarea',{'sticky':'nswe'})]})]
        else:
            style.element_create('Modern.Combobox.downarrow','image',images['chevron'],sticky='')
            children = [('Modern.Combobox.downarrow',{'side':'right','sticky':'ns'}),
                ('Combobox.padding',{'sticky':'nswe','children':[('Combobox.textarea',{'sticky':'nswe'})]})]
        style.layout('T'+name,[(field,{'sticky':'nswe','children':children})])
        style.configure('T'+name,padding=(1,7))
    root.option_add('*TCombobox*Listbox.background','#ffffff')
    root.option_add('*TCombobox*Listbox.foreground',INK)
    root.option_add('*TCombobox*Listbox.selectBackground','#e1edff')
    root.option_add('*TCombobox*Listbox.selectForeground','#1c56a0')
    root.option_add('*TCombobox*Listbox.font',('Microsoft YaHei UI',11))
    root.option_add('*TCombobox*Listbox.relief','flat')
    root.option_add('*TCombobox*Listbox.borderWidth',0)
