"""Non-blocking update checks and downloads, using the existing offline installer."""
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from ui import Button
from online_updates import load_settings,save_settings,check_release,download_release


class OnlineUpdateUI:
    def build_online_updates(self,parent):
        self.online_busy=False
        settings=load_settings(self.program_base)
        self.online_status=tk.StringVar(value='在线更新：'+settings['repository'] if settings['repository'] else '在线更新：尚未配置发布仓库')
        row=ttk.Frame(parent)
        row.pack(fill='x',pady=(0,14))
        Button(row,text='检查更新',command=self.check_online_update).pack(side='left')
        Button(row,text='更新设置',command=self.online_settings_dialog).pack(side='left',padx=8)
        ttk.Label(row,textvariable=self.online_status,style='Muted.TLabel').pack(side='left',padx=8)

    def online_settings_dialog(self):
        BASE=self.program_base
        settings=load_settings(BASE)
        win=tk.Toplevel(self)
        win.title('在线更新设置')
        win.geometry('630x290')
        win.transient(self)
        body=ttk.Frame(win,padding=24)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text='GitHub 发布仓库',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
        repo=tk.StringVar(value=settings['repository'])
        entry=ttk.Entry(body,textvariable=repo)
        entry.pack(fill='x')
        ttk.Label(body,text='填写 用户名/仓库名 或 https://github.com/用户名/仓库名',style='Muted.TLabel').pack(anchor='w',pady=8)
        automatic=tk.BooleanVar(value=settings['automatic'])
        ttk.Checkbutton(body,text='启动时自动检查新版本',variable=automatic).pack(anchor='w')
        def save():
            try:
                save_settings(BASE,repo.get(),automatic.get())
                self.online_status.set('在线更新：已配置 '+repo.get())
                win.destroy()
                self.check_online_update()
            except (ValueError,OSError) as exc:
                messagebox.showerror('未保存',str(exc),parent=win)
        Button(body,text='保存',style='Accent.TButton',command=save).pack(anchor='e',pady=(16,0))
        return win

    def check_online_update(self,automatic=False):
        BASE=self.program_base
        if self.online_busy:
            return
        settings=load_settings(BASE)
        if not settings['repository']:
            if not automatic:
                self.online_settings_dialog()
            return
        if automatic and not settings['automatic']:
            return
        self.online_status.set('正在检查新版本…')
        def done(info):
            if not info:
                self.online_status.set('当前已是最新版本')
                return
            self.online_status.set('发现新版本 '+info['version'])
            if messagebox.askyesno('发现新版本',f"新版：{info['version']}\n\n{info['notes'][:600]}\n\n下载后自动备份、更新并重启。现在更新？",parent=self):
                if not getattr(sys,'frozen',False):
                    messagebox.showinfo('预览模式','请在便携 EXE 版本中执行在线更新。',parent=self)
                    return
                if getattr(self,'exporting',False):
                    messagebox.showinfo('请稍候','请先等迁移包导出完成后再更新。',parent=self)
                    return
                self._download_online_update(info)
        self.online_job(lambda progress:check_release(settings['repository']),done,automatic)

    def online_job(self,work,done,quiet=False):
        self.online_busy=True
        events=queue.Queue()
        def worker():
            try:
                result=work(lambda n,total:events.put(('progress',int(n*100/total))))
                events.put(('done',result))
            except Exception as exc:
                events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
        def poll():
            while True:
                try:
                    kind,value=events.get_nowait()
                except queue.Empty:
                    break
                if kind=='progress':
                    self.online_status.set(f'正在下载更新… {value}%')
                elif kind=='done':
                    self.online_busy=False
                    done(value)
                    return
                elif kind=='error':
                    self.online_busy=False
                    self.online_status.set('暂时无法检查或下载更新，可稍后重试')
                    if not quiet:
                        messagebox.showerror('在线更新未完成',value,parent=self)
                    return
            self.after(150,poll)
        self.after(150,poll)

    def _download_online_update(self,info):
        BASE=self.program_base
        self.online_status.set('正在下载更新…')
        def done(path):
            self.online_status.set('下载完成，正在校验程序包…')
            self.import_program_update(path=path,preconfirmed=True)
        self.online_job(lambda progress:download_release(info,BASE/'.updates'/'downloads',progress),done)
