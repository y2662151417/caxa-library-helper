"""Local offline workbench for tracking CAXA gallery items. Python standard library only."""
from __future__ import annotations
import os
import time
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import core
import bridge
import autoread
import preflight
import verify_action
import clipboard_utils
import cad_window

# Must stay disabled until Windows+CAXA 2024 controls are actually verified.
ENABLE_UNVERIFIED_AUTO_CAPTURE = False

DB_PATH = core.storage_dir() / 'progress.sqlite3'

class App:
    def __init__(self, master):
        self.root=master
        self.mini_mode = os.environ.get('CAXA_MINI_PANEL') == '1'
        self._selector = None
        self._floating = None
        try:
            version=(Path(__file__).with_name('VERSION.txt')).read_text(encoding='ascii').strip()
        except OSError:
            version='未知'
        self.root.title(f'CAXA 高级管理工作台 v{version}')
        width=min(1240,max(960,master.winfo_screenwidth()-60))
        height=min(820,max(650,master.winfo_screenheight()-95))
        self.root.geometry(f'{width}x{height}')
        self.root.minsize(960,650)
        self.c=core.connect(DB_PATH)
        # A previous workbench may have crashed, leaving an AHK INI without a
        # live verifier. Require a fresh handoff after each workbench start.
        bridge.clear_active_job(core.storage_dir())
        # The runner is the Python runtime (or frozen EXE) actually used by
        # this workbench. AHK fails closed if this configuration is missing.
        bridge.write_guard_launcher(core.storage_dir(),executable=sys.executable,
            script='' if getattr(sys,'frozen',False) else str(Path(__file__).with_name('verify_action.py').resolve()))
        self.path=None
        self.capture_id=None
        self.capture_source=None
        self.capture_started=None
        self.last_view_template=self.load_view_template()
        self.view_template_summary_var=tk.StringVar(value=core.view_template_summary(self.last_view_template))
        self.iid_to_path={}
        self.root_path=tk.StringVar(value='')
        self.exclude_var=tk.StringVar(value='工作副本;中间格式;完成图库;图符输出')
        self.qc_vars={key:tk.BooleanVar(value=False) for key,_ in core.QC_ITEMS}
        self.keyword=tk.StringVar(value='')
        self.code_var=tk.StringVar(value='当前未选择图纸')
        self.params={k:tk.StringVar() for k in core.FIELDS}
        self.name_var=tk.StringVar(value='')
        self.block_name_var=tk.StringVar(value='')
        self.block_name_status_var=tk.StringVar(value='尚未导入块名称清单')
        self.mode_var=tk.StringVar(value='待确认')
        self.status_var=tk.StringVar(value='状态：尚未加载任务')
        self._build()
        last_root_file=core.storage_dir()/'last_root.txt'
        try:
            if last_root_file.is_file():
                prev=Path(last_root_file.read_text(encoding='utf-8').strip())
                if prev.is_dir():
                    self.root_path.set(str(prev))
                    self.rescan()
                else:
                    self.refresh()
            else:
                self.refresh()
        except (OSError,ValueError):
            self.refresh()
        self.daily_backup()
        # Track every recurring/launch callback so closing the workbench cannot
        # leave a Tk callback targeting an already-destroyed interpreter.
        self._closing = False
        self._ahk_launching = False
        self._auto_read_timer = None
        self._panel_start_timer = None
        if os.environ.get('CAXA_MINI_PANEL') == '1':
            self._panel_start_timer = self.root.after(500,self.open_floating_panel)
        self._auto_read_timer = self.root.after(1500,self.poll_auto_read)
        # Only one published job is checked, not the whole drawing library.
        # This does not replace the Windows/CAXA side's live document checks.
        self._job_guard_timer = self.root.after(15000, self.poll_job_guard)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_admin_workbench if self.mini_mode else self.close)
        if self.mini_mode:
            self.root.withdraw()

    def load_view_template(self):
        try:
            saved=json.loads((core.storage_dir()/'last_view_template.json').read_text(encoding='utf-8'))
            return core.validate_view_template(saved)
        except (OSError,ValueError,TypeError):
            return list(core.DEFAULT_VIEW_TEMPLATE)

    def save_view_template(self,selected):
        # Contains only the selected view preset, never company paths or CAD data.
        selected=core.validate_view_template(selected)
        dest=core.storage_dir()/'last_view_template.json'
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(selected,ensure_ascii=False),encoding='utf-8')
        os.replace(tmp,dest)
        self.last_view_template=list(selected)
        self.view_template_summary_var.set(core.view_template_summary(selected))

    def is_manifest_parent(self,path):
        row=self.c.execute("SELECT 1 FROM manifest WHERE matched_path=? AND match_status='已匹配' LIMIT 1",(str(path),)).fetchone()
        return row is not None

    def _build(self):
        main=ttk.Frame(self.root,padding=10)
        main.pack(fill='both',expand=True)
        ttk.Label(main,text='日常制图请使用始终置顶的「CAXA 制作控制台」；本窗口只用于目录扫描、名称清单导入、图纸切换和批量管理。',foreground='#24527a',wraplength=1180).pack(anchor='w',pady=(0,7))
        bar=ttk.Frame(main)
        bar.pack(fill='x',pady=(0,8))
        ttk.Label(bar,text='图纸根目录：').pack(side='left')
        ttk.Entry(bar,textvariable=self.root_path,width=58,state='readonly').pack(side='left',fill='x',expand=True,padx=4)
        ttk.Button(bar,text='选择目录并扫描',command=self.scan).pack(side='left',padx=3)
        ttk.Button(bar,text='刷新',command=self.rescan).pack(side='left',padx=3)
        ttk.Button(bar,text='导入图纸名单',command=self.import_names).pack(side='left',padx=3)
        bar2=ttk.Frame(main)
        bar2.pack(fill='x',pady=(0,5))
        ttk.Button(bar2,text='备份记录',command=self.backup).pack(side='left',padx=3)
        ttk.Button(bar2,text='导出汇总CSV',command=self.export).pack(side='left',padx=3)
        ttk.Button(bar2,text='操作历史',command=self.show_history).pack(side='left',padx=3)
        ttk.Button(bar2,text='导入图符名称清单',command=self.import_block_names).pack(side='left',padx=3)
        ttk.Button(bar2,text='启动 CAD 快捷工具',command=self.launch_hotkeys).pack(side='left',padx=3)
        ttk.Button(bar2,text='进入日常制作模式',command=self.open_floating_panel).pack(side='left',padx=3)

        scanopts=ttk.Frame(main)
        scanopts.pack(fill='x',pady=(0,5))
        ttk.Label(scanopts,text='扫描排除目录名（分号隔开）：').pack(side='left')
        ttk.Entry(scanopts,textvariable=self.exclude_var,width=55).pack(side='left',fill='x',expand=True)
        ttk.Label(scanopts,text='避免将工作副本／成果当成源图',foreground='#555').pack(side='left',padx=5)
        top=ttk.PanedWindow(main,orient='horizontal')
        top.pack(fill='both',expand=True)
        left=ttk.Frame(top,padding=5)
        right_container=ttk.Frame(top)
        top.add(left,weight=4)
        top.add(right_container,weight=5)
        # The workbench must remain usable on 1366x768 laptops: scroll the
        # entire right-side editor instead of hiding review controls below the screen.
        self.right_canvas=tk.Canvas(right_container,highlightthickness=0)
        right_scroll=ttk.Scrollbar(right_container,orient='vertical',command=self.right_canvas.yview)
        self.right_canvas.configure(yscrollcommand=right_scroll.set)
        right_scroll.pack(side='right',fill='y')
        self.right_canvas.pack(side='left',fill='both',expand=True)
        right=ttk.Frame(self.right_canvas,padding=8)
        content_window=self.right_canvas.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda e:self.right_canvas.configure(scrollregion=self.right_canvas.bbox('all')))
        self.right_canvas.bind('<Configure>',lambda e:self.right_canvas.itemconfigure(content_window,width=e.width))

        query=ttk.Frame(left)
        query.pack(fill='x',pady=3)
        ttk.Label(query,text='检索图号/图名：').pack(side='left')
        ent=ttk.Entry(query,textvariable=self.keyword)
        ent.pack(side='left',fill='x',expand=True)
        ent.bind('<KeyRelease>',lambda _:self.refresh())
        ttk.Button(query,text='异常检查',command=self.check).pack(side='left',padx=4)

        columns=('code','name','parent','status')
        self.drawings=ttk.Treeview(left,columns=columns,show='headings',selectmode='browse')
        for cid,title,width in [('code','图号',140),('name','图纸名称',170),('parent','候选父项',120),('status','状态',100)]:
            self.drawings.heading(cid,text=title)
            self.drawings.column(cid,width=width,stretch=cid=='name')
        self.drawings.pack(fill='both',expand=True,side='left',pady=4)
        sy=ttk.Scrollbar(left,orient='vertical',command=self.drawings.yview)
        sy.pack(fill='y',side='right')
        self.drawings.configure(yscrollcommand=sy.set)
        self.drawings.bind('<<TreeviewSelect>>',self.select)
        self.drawings.bind('<Double-1>',lambda _:self.open_work_copy())

        ttk.Label(right,textvariable=self.code_var,font=('Microsoft YaHei UI',11,'bold'),wraplength=480).pack(anchor='w',pady=3)
        actions=ttk.Frame(right)
        actions.pack(fill='x',pady=4)
        ttk.Button(actions,text='创建并打开工作副本',command=self.open_work_copy).pack(side='left',padx=(0,6))
        ttk.Button(actions,text='复制当前图符名称',command=self.copy_name).pack(side='left',padx=(0,6))
        ttk.Button(actions,text='设为快捷键当前任务',command=self.publish_job).pack(side='left',padx=(0,6))
        ttk.Button(actions,text='人工确认整张复核',command=self.finish).pack(side='left')
        ttk.Button(right,text='确认已保存 → 定位并打开下一张',command=self.next_pending).pack(fill='x',pady=(2,5))

        params=ttk.LabelFrame(right,text='1. 剪贴板参数提取（复制 CAXA 参数栏里的多行单元格后点击读取）',padding=8)
        params.pack(fill='x',pady=8)
        ttk.Label(params,text='命名类型：').grid(row=0,column=0,sticky='e')
        mode=ttk.Combobox(params,textvariable=self.mode_var,state='readonly',
            values=('待确认','垂直重锤拉紧装置','其他图纸（人工确认）'),width=31)
        mode.grid(row=0,column=1,sticky='we',pady=4)
        ttk.Button(params,text='一键读取参数 → 核对并生成名称',command=self.quick_name).grid(row=1,column=0,columnspan=2,sticky='w',pady=4)
        for n,k in enumerate(core.FIELDS,2):
            ttk.Label(params,text=k+'：').grid(row=n,column=0,sticky='e',pady=2)
            ttk.Entry(params,textvariable=self.params[k],width=36).grid(row=n,column=1,sticky='we',pady=2)
        params.columnconfigure(1,weight=1)
        ttk.Button(params,text='确认命名（主体自动生成／下级手动核对）',command=self.save_params).grid(row=5,column=0,columnspan=2,sticky='we',pady=6)
        ttk.Label(params,text='本地建议名称（可由参数生成；不等同于正式块名称）：').grid(row=6,column=0,columnspan=2,sticky='w')
        ttk.Entry(params,textvariable=self.name_var,width=65).grid(row=7,column=0,columnspan=2,sticky='we',pady=3)
        ttk.Label(params,text='按完整图号匹配的正式图符名称：').grid(row=8,column=0,columnspan=2,sticky='w')
        ttk.Entry(params,textvariable=self.block_name_var,width=65,state='readonly').grid(row=9,column=0,columnspan=2,sticky='we',pady=3)
        ttk.Label(params,textvariable=self.block_name_status_var,foreground='#555',wraplength=480).grid(row=10,column=0,columnspan=2,sticky='w')

        plan=ttk.LabelFrame(right,text='2. 视图模板（同类型图纸设置一次）',padding=8)
        plan.pack(fill='x',pady=4)
        ttk.Label(plan,textvariable=self.view_template_summary_var,
                  font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w',pady=2)
        ttk.Label(plan,text='每种视图自动建立带尺寸和无尺寸两个版本。双视图共4项，三视图共6项；修改请在悬浮助手的“设置”中完成。',
                  wraplength=480,foreground='#555').pack(anchor='w',pady=3)

        version=ttk.LabelFrame(right,text='3. 视图版本记录（只表示人工确认，不自动检查 EXB 对象）',padding=8)
        version.pack(fill='both',expand=True,pady=5)
        self.versions=ttk.Treeview(version,columns=('view','kind','state'),show='headings',height=7,selectmode='browse')
        for cid,title,width in [('view','视图',110),('kind','版本',100),('state','当前状态',100)]:
            self.versions.heading(cid,text=title)
            self.versions.column(cid,width=width)
        self.versions.pack(fill='both',expand=True,pady=4)
        row=ttk.Frame(version)
        row.pack(fill='x')
        ttk.Button(row,text='已复核',command=lambda:self.set_version('已复核')).pack(side='left',padx=3)
        ttk.Button(row,text='待处理',command=lambda:self.set_version('待处理')).pack(side='left',padx=3)
        ttk.Button(row,text='明确不需要',command=lambda:self.set_version('不需要')).pack(side='left',padx=3)
        ttk.Button(version,text='所有计划视图已逐项复核（一次标记）',command=self.review_all_versions).pack(fill='x',pady=3)
        ttk.Label(version,text='已复核仅在你确认：轮廓/图层/基点/原生属性填入/图库插入效果后标记。',wraplength=480,foreground='#555').pack(anchor='w',pady=3)

        qc=ttk.LabelFrame(right,text='4. 人工验收清单（仅记录你确认的结果，不替代 CAD 验证）',padding=8)
        qc.pack(fill='x',pady=5)
        for key,label in core.QC_ITEMS:
            ttk.Checkbutton(qc,text=label,variable=self.qc_vars[key],
                            command=lambda k=key:self.on_qc_change(k)).pack(anchor='w',pady=2)
        ttk.Label(qc,text='完成全部图元、视图及属性检查后再逐项勾选；若源图内容变化会自动清空这些确认。',
                  foreground='#555',wraplength=480).pack(anchor='w',pady=5)
        status=ttk.Frame(main)
        status.pack(fill='x',pady=5)
        ttk.Label(status,textvariable=self.status_var,wraplength=1080).pack(side='left')
        ttk.Label(main,text='离线管理：不解析 EXB 内容、仅复制工作副本。可另行启动 AHK 快捷工具辅助点击“定义图符/属性编辑/填入标题栏”；必须先用虚构图标定验证。',foreground='#666').pack(anchor='w')

    def open_floating_panel(self):
        import floating_panel
        if getattr(self,'_floating',None) is not None:
            try:
                if self._floating.win.winfo_exists():
                    self._floating.win.deiconify()
                    self._floating.win.attributes('-topmost',True)
                    try:self.root.after(900,self.root.lower)
                    except tk.TclError:pass
                    return
            except Exception: pass
        self._floating=floating_panel.Panel(self)
        # In mini mode the full management root remains withdrawn; the compact
        # drawing selector is opened on demand from the floating assistant.
        if not self.mini_mode:
            try:self.root.after(900,self.root.lower)
            except tk.TclError:pass

    def open_drawing_selector(self):
        """Open the compact, task-focused drawing picker instead of the admin dashboard."""
        if self._selector is not None:
            try:
                if self._selector.exists():
                    self._selector.show()
                    return
            except Exception:
                self._selector = None
        if self._floating is not None:
            try:
                self._floating.suspend_topmost()
            except Exception:
                pass
        from drawing_selector import DrawingSelector
        self._selector = DrawingSelector(self)

    def open_admin_workbench(self):
        """Show the full management workspace only when explicitly requested."""
        if self._selector is not None:
            try:
                self._selector.close(restore_panel=False)
            except Exception:
                self._selector = None
        if self._floating is not None:
            try:
                self._floating.suspend_topmost()
            except Exception:
                pass
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()

    def hide_admin_workbench(self):
        """Hide the advanced workspace and return to the compact assistant."""
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        if self._floating is not None:
            try:
                self._floating.resume_topmost()
            except Exception:
                pass

    def daily_backup(self):
        marker=core.storage_dir()/'last_backup_day.txt'
        today=core.dt.date.today().isoformat()
        try:
            if not marker.exists() or marker.read_text(encoding='utf-8') != today:
                self.backup(silent=True)
                marker.write_text(today,encoding='utf-8')
        except OSError as e:
            self.status_var.set('自动备份未成功：'+str(e))

    def backup(self,silent=False):
        try:
            dest=core.backup(self.c,core.storage_dir()/'backups')
        except Exception as e:
            messagebox.showerror('备份失败',str(e))
            return
        if not silent: messagebox.showinfo('本地备份完成',str(dest))

    def scan(self,parent=None):
        folder=filedialog.askdirectory(title='选择包含 EXB 的根文件夹',parent=parent or self.root)
        if not folder: return
        self.path=None  # prevent accidentally editing the previous root's selection
        self.root_path.set(folder)
        self.rescan()

    def rescan(self):
        folder=self.root_path.get()
        if not folder:
            self.status_var.set('先选择目录。')
            return
        try:
            excludes=[x.strip() for x in self.exclude_var.get().split(';') if x.strip()]
            n=core.scan_folder(self.c,Path(folder),exclude_dirs=excludes)
            try:
                (core.storage_dir()/'last_root.txt').write_text(folder,encoding='utf-8')
            except OSError:
                pass
            self.refresh()
            matched=sum(m['match_status']=='已匹配' for m in core.manifest_summary(self.c))
            total=len(core.manifest_summary(self.c))
            block_rows=core.block_name_summary(self.c)
            block_matched=sum(m['match_status']=='已匹配' for m in block_rows)
            block_total=len(block_rows)
            self.status_var.set(f'扫描 {n} 个源 EXB（已排除成果目录）；主体名单匹配 {matched}/{total}；正式块名称匹配 {block_matched}/{block_total}。')
        except Exception as e:
            messagebox.showerror('扫描失败',str(e))

    def refresh(self):
        keep=self.path
        self.iid_to_path={}
        for i in self.drawings.get_children(): self.drawings.delete(i)
        query=self.keyword.get().casefold().strip()
        queue=[d for d in core.task_queue(self.c) if not query or query in (d['code']+' '+d['name']+' '+d['path']).casefold()]
        for idx,d in enumerate(queue):
            state=d['status']
            if not d['present']: state='文件缺失'
            elif core.file_changed(d): state='已变更需复核'
            iid='r'+str(idx)
            self.iid_to_path[iid]=d['path']
            self.drawings.insert('', 'end',iid=iid,values=(d['code'],d['name'],d['parent_candidate'],state))
            # Store exact path in Python rather than Tk tags; paths may contain spaces/braces.
            self.drawings.set(iid,'status',state)
            if d['path']==keep:
                self.drawings.selection_set(iid)
                self.drawings.see(iid)
        if keep: self.load_detail(keep)
        selector=getattr(self,'_selector',None)
        if selector is not None:
            try: selector.refresh()
            except Exception: pass

    def select(self,event=None):
        selection=self.drawings.selection()
        if not selection: return
        path=self.iid_to_path.get(selection[0])
        if path: self.load_detail(path)

    def load_detail(self,path):
        d=core.get_drawing(self.c,path)
        if not d: return
        if self.path is not None and self.path!=path:
            bridge.clear_active_job(core.storage_dir())
        self.path=path
        self.code_var.set(f"{d['code']}｜{d['name']}\n{d['path']}")
        self.name_var.set(d['suggested_name'])
        block_info=core.block_name_for_path(self.c,path)
        self.block_name_var.set(block_info['block_name'])
        self.block_name_status_var.set('正式块名称匹配状态：'+block_info['status'])
        self.mode_var.set('垂直重锤拉紧装置' if d['naming_mode']=='待确认' and self.is_manifest_parent(path) else d['naming_mode'])
        self.params['带宽'].set(d['bandwidth'])
        self.params['轴径'].set(d['shaft'])
        self.params['筒径'].set(d['diameter'])
        # Auto-captured values are *provisional*: show them immediately, but
        # do not replace an already manually confirmed name or review status.
        provisional=autoread.cached(self.c,path)
        if provisional and not d['suggested_name']:
            for k in core.FIELDS:self.params[k].set(provisional[k])
            if self.mode_var.get()=='垂直重锤拉紧装置':
                self.name_var.set(core.suggest_name(d['code'],d['name'],*(provisional[k] for k in core.FIELDS)))
        ss=core.slots_for(self.c,path)
        for key,label,checked in core.qc_status(self.c,path):
            self.qc_vars[key].set(checked)
        for x in self.versions.get_children(): self.versions.delete(x)
        for s in ss:
            self.versions.insert('','end',values=(s['view_type'],s['size_kind'],s['status']))

    def on_qc_change(self,key):
        if not self.path:return
        try:
            core.set_qc(self.c,self.path,key,self.qc_vars[key].get())
        except Exception as e:
            messagebox.showerror('质检记录失败',str(e))
            self.load_detail(self.path)

    def review_all_versions(self):
        if not self.require():return
        if not messagebox.askyesno('批量人工复核',
                '确认你已经逐项检查本张图所有计划视图的带/无尺寸版本、对象、基点及实际入库结果？\n\n'
                '此操作只会更新本地记录，不会检查或修改 CAXA，也不会自动保存图纸。',default='no'):
            return
        try:
            core.mark_all_slots_reviewed(self.c,self.path)
            self.load_detail(self.path);self.refresh()
        except Exception as e:messagebox.showerror('复核失败',str(e))

    def import_names(self):
        filename=filedialog.askopenfilename(title='导入主体图纸名称（TXT或CSV）',
            filetypes=[('名单 TXT / CSV','*.txt *.csv'),('所有文件','*.*')])
        if not filename:return
        try:
            try:text=Path(filename).read_text(encoding='utf-8-sig')
            except UnicodeDecodeError:text=Path(filename).read_text(encoding='gb18030')
            n=core.import_manifest(self.c,text)
            found=sum(m['match_status']=='已匹配' for m in core.manifest_summary(self.c))
            self.refresh()
            messagebox.showinfo('名单已导入',f'清单 {n} 项，已准确匹配 {found} 项。\n未匹配或重名条目可点击“异常检查”查看。\n原有进度记录不会被删除。')
        except Exception as e:messagebox.showerror('名单导入失败',str(e))

    def import_block_names(self):
        filename=filedialog.askopenfilename(title='导入正式块名称 Excel（.xlsx）',
            filetypes=[('Excel 工作簿','*.xlsx')])
        if not filename:return
        try:
            n=core.import_block_names_xlsx(self.c,filename)
            rows=core.block_name_summary(self.c)
            found=sum(x['match_status']=='已匹配' for x in rows)
            missing=[x for x in rows if x['match_status']!='已匹配']
            self.refresh()
            self.sync_job()
            detail='\\n'.join(f"{x['code']}：{x['match_status']}" for x in missing[:12])
            message=f'从 Excel 导入 {n} 个正式块名称，按完整图号准确匹配 {found}/{n} 项。'
            if detail:
                message+='\\n\\n未匹配项（最多显示12项）：\\n'+detail
            message+='\\n\\n只有图号唯一匹配且当前 CAXA 工作副本核验通过时，才允许复制正式块名称。'
            messagebox.showinfo('Excel 块名称导入完成',message,parent=self.root)
        except Exception as e:
            messagebox.showerror('Excel 导入失败',str(e),parent=self.root)

    def require(self):
        if not self.path:
            messagebox.showwarning('未选图纸','请先选一张图纸。')
            return False
        return True

    def quick_name(self):
        """Single deliberate step for copying and checking a formatted property grid.
        Neither CAD nor its clipboard is modified; database write needs confirmation.
        """
        if not self.require():return
        if self.mode_var.get()!='垂直重锤拉紧装置':
            messagebox.showwarning('命名类型','此操作只用于已核对的垂直重锤拉紧装置主体图。下级图请先确认不同规则。')
            return
        try:
            text=clipboard_utils.read_clipboard_text(self.root)
            parsed=core.parse_clipboard(text)
            values=[parsed.get(k,'') for k in core.FIELDS]
            row=core.get_drawing(self.c,self.path)
            name=core.suggest_name(row['code'],row['name'],*values)
            if not messagebox.askyesno('核对复制的参数',
                    '当前图纸：'+row['code']+' / '+row['name']+'\n'
                    +'带宽：'+values[0]+'\n轴径：'+values[1]+'\n筒径：'+values[2]
                    +'\n\n建议名称：\n'+name
                    +'\n\n确认上述字段属于当前图纸，并保存本地建议名称？',default='no'):
                return
            core.save_params(self.c,self.path,*values)
            self.sync_job()
            self.load_detail(self.path)
            self.refresh()
            self.status_var.set('参数已解析并核对，名称已保存在本地；CAD 中仍需原生属性填入。')
        except Exception as e:
            messagebox.showwarning('无法生成名称',str(e))

    def from_clipboard(self):
        if not self.require(): return
        try:
            text=clipboard_utils.read_clipboard_text(self.root)
            params=core.parse_clipboard(text)
            if not params:
                raise ValueError('未找到已知字段。可能是复制了 CAD 对象而不是属性表格文字；也可能字段名称不同。')
            # clear all to prevent stale values from a previous copy
            for k in core.FIELDS: self.params[k].set(params.get(k,''))
            self.status_var.set('解析到：'+ '、'.join(params.keys())+'。请核对后点击“保存参数”。')
        except Exception as e:
            for k in core.FIELDS: self.params[k].set('')
            messagebox.showwarning('参数解析未成功',str(e))

    def save_params(self):
        if not self.require(): return
        try:
            mode=self.mode_var.get()
            if mode=='垂直重锤拉紧装置':
                name=core.save_params(self.c,self.path,self.params['带宽'].get().strip(),
                                      self.params['轴径'].get().strip(),self.params['筒径'].get().strip())
            elif mode=='其他图纸（人工确认）':
                name=core.save_custom_name(self.c,self.path,self.name_var.get())
            else:
                raise ValueError('先选择并核对命名规则，不能用待确认规则生成名称')
            self.name_var.set(name)
            self.sync_job()
            self.status_var.set('命名方案已本地保存。此处不会向 CAXA 写入属性；最终以公司规则为准。')
            self.refresh()
        except Exception as e:
            messagebox.showwarning('命名检查未通过',str(e))

    def verify_selected_cad_document(self):
        """Verify the selected source, its registered work copy, and the live CAXA caption."""
        if not self.path:
            return False, '请先在助手中选择一张图纸。'
        drawing=core.get_drawing(self.c,self.path)
        if not drawing or not drawing['present']:
            return False, '当前选择不在有效的源图清单中。'
        if core.file_changed(drawing):
            return False, '源图或已复核工作副本发生变化，请先刷新并核对。'
        if not drawing['working_path']:
            return False, '当前图纸还没有登记工作副本。请先点击“打开图纸”创建并打开工作副本。'
        source=Path(drawing['path'])
        work=Path(drawing['working_path'])
        root=Path(drawing['root'])
        if source.is_symlink() or not source.is_file():
            return False, '源 EXB 不存在或路径异常，已禁止复制。'
        if work.is_symlink() or not work.is_file():
            return False, '登记的工作副本不存在或路径异常，请重新创建工作副本。'
        if core.path_contains_symlink(root,source) or core.path_contains_symlink(root,work):
            return False, '源图或工作副本路径包含符号链接，无法安全核验。'
        if not drawing['working_base_sha256'] or drawing['working_base_sha256'] != drawing['sha256']:
            return False, '工作副本不是基于当前登记源图创建的，请重新创建并核对。'
        try:
            if core.work_copy_aliases_source(source,work):
                return False, '工作副本与原始 EXB 实际指向同一文件，已禁止复制。'
        except ValueError as exc:
            return False, str(exc)
        return cad_window.verify_current_document(core.storage_dir(),work.name)

    def copy_official_block_name(self,parent=None):
        parent=parent or self.root
        if not self.path:
            messagebox.showwarning('未选图纸','请先选择一张图纸。',parent=parent)
            return False
        info=core.block_name_for_path(self.c,self.path)
        if info['status']!='已匹配' or not info['block_name']:
            messagebox.showwarning('正式块名称未匹配',
                f"当前图号：{info['code']}\\n匹配状态：{info['status']}\\n\\n"
                '请核对 Excel 中的图号与正式块名称；不会使用本地建议名称或相似图号代替。',
                parent=parent)
            return False
        ok,reason=self.verify_selected_cad_document()
        if not ok:
            messagebox.showwarning('当前 CAXA 图纸未通过核验',reason,parent=parent)
            return False
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(info['block_name'])
            self.root.update()
            self.status_var.set('正式块名称已复制；请在 CAXA 中人工核对并粘贴。')
            return True
        except Exception as e:
            messagebox.showerror('复制失败',str(e),parent=parent)
            return False

    def copy_name(self):
        return self.copy_official_block_name(parent=self.root)

    def update_plan(self):
        if not self.require(): return False
        try:
            chosen=core.validate_view_template(self.last_view_template)
            n=core.plan_views(self.c,self.path,chosen)
            self.sync_job()
            self.load_detail(self.path)
            self.refresh()
            self.status_var.set('已按当前视图模板建立 '+str(n)+' 项任务；CAD 图元仍由你在 CAXA 中选择。')
            return True
        except Exception as e:
            messagebox.showerror('无法建立视图计划',str(e))
            return False

    def set_version(self,state):
        if not self.require(): return
        selection=self.versions.selection()
        if not selection:
            messagebox.showwarning('未选视图版本','请先点选版本表中的一行。')
            return
        v,k,_=self.versions.item(selection[0],'values')
        if state=='已复核':
            yes=messagebox.askyesno('人工复核声明',
                f'{v} / {k}\n\n请确认已在 CAXA 检查：\n'+
                '① 对象完整，外形及图层符合标准\n② 基点准确\n③ 已使用原生标题栏属性填入\n④ 图符已入库并重新插入测试\n⑤ 中间格式和必要文件已保存\n\n这只是人工记录，工具无法自动验证 EXB 内容。')
            if not yes:return
        elif state=='不需要':
            if not messagebox.askyesno('明确跳过',f'确定公司本张图不要求制作 {v} / {k} 吗？'):
                return
        core.set_slot(self.c,self.path,v,k,state)
        self.load_detail(self.path)
        self.refresh()

    def finish(self):
        if not self.require(): return
        if not messagebox.askyesno('最终人工确认',
            '是否确认这张图的全部计划视图均已按公司规范制作并保存，\n且规格名称、基点、属性以及图库插入结果已复核？'):
            return
        try:
            core.finish_drawing(self.c,self.path)
            self.refresh()
            self.status_var.set('本张已记录为“已人工复核”；再次扫描后若源 EXB 改动将提示重新复核。')
        except ValueError as e:
            messagebox.showwarning('尚不能标记完成',str(e))

    def sync_job(self):
        """Republish only this drawing's verified metadata; invalid states clear old job."""
        bridge.clear_active_job(core.storage_dir())
        if not self.path:return
        d=core.get_drawing(self.c,self.path)
        plan=self.get_view_plan()
        if d and plan:
            block_info=core.block_name_for_path(self.c,self.path)
            try:
                preflight.validate_handoff(self.c,self.path,plan)
            except ValueError:
                return  # Invalid/stale CAD task has already been cleared above.
            bridge.publish_active_job(core.storage_dir(),d,d['suggested_name'],plan,
                                      block_info['block_name'],block_info['status'])
            signature=bridge.expected_job_signature(d,d['suggested_name'],plan,
                                                    block_info['block_name'],block_info['status'])
            bridge.refresh_job_lease(core.storage_dir(),signature)

    def get_view_plan(self):
        """Stable operator-selected plan. This is advisory; no CAD object is auto-selected."""
        if not self.path:
            return ()
        slots=core.slots_for(self.c,self.path)
        by={(s['view_type'],s['size_kind']):s for s in slots}
        # Confirmed production order: finish all dimensioned views first;
        # then hide the dimension layer and prepare all no-dimension views.
        # Within each pass, preserve the stable core view ordering.
        return tuple(f'{view}·{kind}' for kind in ('带尺寸','无尺寸')
                     for view in core.VIEW_TYPES
                     if (view,kind) in by and by[(view,kind)]['status']!='不需要')

    def open_work_copy(self):
        if not self.require():return False
        try:
            copy=core.ensure_working_copy(self.c,self.path)
            self.status_var.set('已在工作副本目录准备图纸：'+copy.name+'。原图保持不变。')
            self.sync_job()
            return self.open_file(file_to_open=copy)
        except Exception as e:
            messagebox.showerror('工作副本失败',str(e),parent=self._selector.win if self._selector else self.root)
            return False

    def open_file(self,file_to_open=None):
        if not self.require(): return False
        if file_to_open is None:
            messagebox.showwarning('源图保护','禁止从工作台直接打开原图进行编辑，请使用“打开工作副本”。',
                                   parent=self._selector.win if self._selector else self.root)
            return False
        p=Path(file_to_open)
        if not p.is_file():
            messagebox.showerror('文件不存在',str(p),parent=self._selector.win if self._selector else self.root)
            return False
        try:
            if os.name=='nt':
                # On every new working-copy open, queue a read-only attempt.
                # AHK only consumes it if the exact CAD window and calibrated
                # parameter dialog match; otherwise nothing is copied.
                # A CAXA caption may expose only the basename, not the full
                # path. With duplicate basenames an automatic capture could
                # be attributed to the wrong drawing. Disable it in that case.
                basenames=[Path(r['path']).name.casefold() for r in core.list_drawings(self.c)
                           if r['present']]
                unique_basename=(basenames.count(Path(self.path).name.casefold())==1 and p.name.casefold()!=Path(self.path).name.casefold())
                if (ENABLE_UNVERIFIED_AUTO_CAPTURE and
                        autoread.cached(self.c,self.path) is None and unique_basename):
                    self.capture_source=self.path
                    self.capture_id=autoread.request_capture(core.storage_dir(),Path(self.path),p)
                    self.capture_started=time.monotonic()
                else:
                    self.capture_id=None
                    self.capture_source=None
                    self.capture_started=None
                    (core.storage_dir()/autoread.REQUEST).unlink(missing_ok=True)
                    if not unique_basename:
                        self.status_var.set('检测到不同目录中同名 EXB：为避免串图，已禁用这张图的自动参数读取。')
                os.startfile(str(p))
            elif sys.platform=='darwin':subprocess.Popen(['open',str(p)])
            else:subprocess.Popen(['xdg-open',str(p)])
            self.status_var.set('已请求打开工作副本。CAXA 自动参数采集尚未通过实机验证，本版仅复用有效缓存或人工复制。')
            return True
        except Exception as e:
            messagebox.showerror('打开失败',str(e),parent=self._selector.win if self._selector else self.root)
            return False

    def check(self):
        issues=core.checks(self.c)
        win=tk.Toplevel(self.root)
        win.title('本地异常检查')
        win.geometry('820x510')
        text=tk.Text(win,wrap='word',font=('Microsoft YaHei UI',10))
        text.pack(fill='both',expand=True,padx=10,pady=10)
        text.insert('end',f'共 {len(issues)} 项提醒；提示不等于已经检测 CAD 内部图形。\n\n')
        for n,(label,issue) in enumerate(issues,1):
            text.insert('end',f'{n}. {label} —— {issue}\n')
        text.configure(state='disabled')
        ttk.Button(win,text='关闭',command=win.destroy).pack(pady=(0,10))

    def export(self):
        path=filedialog.asksaveasfilename(title='导出本地汇总',defaultextension='.csv',
            filetypes=[('CSV 文件','*.csv')],initialfile='图库制作进度汇总.csv')
        if not path: return
        try:
            core.export_csv(self.c,path)
            messagebox.showinfo('导出完成','已生成汇总表（包含本机文件路径）。\n请按公司保密要求存放与发送。\n\n'+path)
        except Exception as e:
            messagebox.showerror('导出失败',str(e))

    def next_pending(self):
        if self.path and not messagebox.askyesno('确认切换图纸',
                'CAXA 可能还有未保存的图纸或正在执行的命令。\n\n请先手动保存工作图、退出当前命令。\n'
                '确认后将打开下一张的工作副本，不会自动保存或关闭当前 CAD 图。',default='no'):
            return
        next_row=core.next_pending(self.c,self.path)
        if next_row is None:
            messagebox.showinfo('进度','已扫描图纸均记录为人工复核完成。请仍以公司首件审核与最终图库检查为准。')
            return
        self.keyword.set('')
        self.path=next_row['path']
        self.refresh()
        for iid,path in self.iid_to_path.items():
            if path==next_row['path']:
                self.drawings.selection_set(iid)
                self.drawings.see(iid)
                self.load_detail(path)
                break
        try:
            bridge.clear_active_job(core.storage_dir())
            self.open_work_copy()
        except Exception as e:
            messagebox.showerror('下一张打开失败',str(e))
        self.status_var.set('已选择 '+next_row['code']+'。打开前已清除上一张任务；当前有确认名称时会重新发布。')

    def publish_job(self):
        # An explicit publish attempt must invalidate the prior AHK job first.
        # Otherwise a failed validation could leave an older CAD task active.
        bridge.clear_active_job(core.storage_dir())
        if not self.require(): return
        d=core.get_drawing(self.c,self.path)
        block_info=core.block_name_for_path(self.c,self.path)
        exact_block_name=(block_info['status']=='已匹配' and bool(block_info['block_name']))
        if not d or (not d['suggested_name'] and not exact_block_name):
            messagebox.showwarning('不能发布任务',
                '当前图纸既没有已确认的本地建议名称，也没有按完整图号匹配的正式块名称。\n'
                '请先导入图符名称清单，或按原流程确认名称。')
            return
        if d['naming_mode']=='待确认' and not exact_block_name:
            messagebox.showwarning('命名规则待确认','当前图纸尚未确认命名规则，且没有正式块名称匹配。')
            return
        if not core.slots_for(self.c,self.path):
            messagebox.showwarning('没有视图计划','请先确定本张图要做的视图类型。')
            return
        if core.file_changed(d):
            messagebox.showwarning('图纸有变更','图纸复核后又发生变更，请刷新并核对。')
            return
        try:
            preflight.validate_handoff(self.c,self.path,self.get_view_plan())
            target=bridge.publish_active_job(core.storage_dir(),d,d['suggested_name'],self.get_view_plan(),
                                             block_info['block_name'],block_info['status'])
            signature=bridge.expected_job_signature(d,d['suggested_name'],self.get_view_plan(),
                                                    block_info['block_name'],block_info['status'])
            bridge.refresh_job_lease(core.storage_dir(),signature)
            with self.c:
                core.add_event(self.c,'发布快捷任务',self.path,block_info['block_name'] or d['suggested_name'])
            messagebox.showinfo('当前任务已发布',
                '快捷键工具现在可读取当前图纸任务。\n\n' +
                f"图纸：{d['code']}｜{d['name']}\n" +
                f"本地建议名称：{d['suggested_name'] or '未生成'}\n" +
                f"正式块名称：{block_info['block_name'] or '未匹配'}（{block_info['status']}）\n\n" +
                '只有正式块名称状态为“已匹配”时，Ctrl+Alt+F8 才会自动填写图符名称。')
        except Exception as e:
            messagebox.showerror('发布失败',str(e))

    def launch_hotkeys(self, on_complete=None):
        """Prepare the official portable AutoHotkey runtime and launch the controller.

        The first run downloads the official ZIP into the current user's LOCALAPPDATA,
        verifies its pinned SHA-256 digest, and extracts the interpreter without an
        installer or administrator privilege. Work happens on a daemon thread.
        """
        if sys.platform != 'win32':
            messagebox.showinfo('Windows 专用','CAD 快捷控制器仅在 Windows + CAXA 2024 中运行。')
            return None
        script=Path(__file__).resolve().parent/'快捷键工具'/'CAXA_半自动辅助.ahk'
        if not script.exists():
            messagebox.showerror('文件缺失',str(script));return None
        if self._ahk_launching:
            self.status_var.set('正在准备 AutoHotkey v2.0.32，请稍候。')
            return None
        self._ahk_launching = True
        self.status_var.set('正在检查 AutoHotkey v2.0.32；首次运行会自动下载并校验官方便携版。')
        try:
            import ahk_runtime
            def completed(ok, message):
                def update_ui():
                    self._ahk_launching = False
                    if not self._closing:
                        self.status_var.set(message)
                        if not ok:
                            messagebox.showerror('CAXA 控制器启动失败',message)
                        if on_complete:
                            on_complete(ok, message)
                try:
                    self.root.after(0, update_ui)
                except Exception:
                    self._ahk_launching = False
            self._ahk_launch_thread = ahk_runtime.start_script_async(
                script, callback=completed, storage_dir=core.storage_dir())
            return self._ahk_launch_thread
        except Exception as e:
            self._ahk_launching = False
            messagebox.showerror('无法启动',str(e))
            return None

    def show_history(self):
        history=core.recent_events(self.c,150)
        win=tk.Toplevel(self.root)
        win.title('本地操作历史（最近 150 条）')
        win.geometry('1000x550')
        text=tk.Text(win,wrap='none',font=('Consolas',10))
        text.pack(fill='both',expand=True,padx=8,pady=8)
        for event in history:
            p=Path(event['drawing_path']).name if event['drawing_path'] else '-'
            text.insert('end',f"{event['time']}  {event['action']}  {p}  {event['detail']}\n")
        text.configure(state='disabled')
        ttk.Button(win,text='关闭',command=win.destroy).pack(pady=5)


    def poll_auto_read(self):
        """Nonblocking intake; a failed capture never edits CAD or approves a name."""
        self._auto_read_timer = None
        if self._closing:
            return
        try:
            if self.capture_id and self.capture_source:
                fields=autoread.receive(self.c,core.storage_dir(),self.capture_id,self.capture_source)
                if fields:
                    source=self.capture_source
                    self.capture_id=None
                    self.capture_source=None
                    self.capture_started=None
                    if source==self.path:
                        self.load_detail(source)
                        self.status_var.set('已自动缓存本张图的规格参数，生成了待核对的名称；无需再次手动复制。')
            if self.capture_id and self.capture_started and time.monotonic()-self.capture_started>40:
                self.capture_id=None
                self.capture_source=None
                self.capture_started=None
                (core.storage_dir()/autoread.REQUEST).unlink(missing_ok=True)
                self.status_var.set('未检测到匹配的 CAXA 参数窗口；已停止本次自动读取，不影响原图和继续绘图。')
        except Exception as e:
            self.capture_id=None
            self.capture_source=None
            self.capture_started=None
            self.status_var.set('自动参数读取未通过：'+str(e)+'。不会自动命名或写入 CAD。')
        finally:
            if not self._closing:
                self._auto_read_timer = self.root.after(1500,self.poll_auto_read)

    def poll_job_guard(self):
        """Revoke stale AHK metadata during an otherwise idle CAD session."""
        self._job_guard_timer = None
        if self._closing:
            return
        try:
            revoked, sig = preflight.reconcile_active_job(self.c, core.storage_dir())
            if revoked:
                (core.storage_dir()/'active_job_lease.json').unlink(missing_ok=True)
                self.status_var.set('图纸、工作副本或任务计划发生变化：已撤销旧快捷任务，请核对后重新发布。')
            elif sig:
                bridge.refresh_job_lease(core.storage_dir(),sig)
            else:
                (core.storage_dir()/'active_job_lease.json').unlink(missing_ok=True)
        except Exception as e:
            # A failed safety check must not silently leave an unsafe job.
            # If deletion is blocked by OS permissions, report prominently.
            (core.storage_dir()/'active_job_lease.json').unlink(missing_ok=True)
            self.status_var.set('快捷任务安全检查失败，请停止使用 AHK 快捷键：' + str(e))
        finally:
            if not self._closing:
                self._job_guard_timer = self.root.after(15000, self.poll_job_guard)

    def close(self):
        # The idle guard cannot run after Tk exits. Revoke this session's AHK
        # task rather than leaving an apparently usable job indefinitely.
        try:
            bridge.clear_active_job(core.storage_dir())
        except OSError as e:
            messagebox.showerror('无法安全退出',
                '旧快捷任务无法撤销，请先退出 AutoHotkey 快捷脚本后再关闭工作台。\n' + str(e))
            return
        self._closing = True
        for timer_name in ('_auto_read_timer','_panel_start_timer'):
            timer=getattr(self,timer_name,None)
            if timer is not None:
                try:self.root.after_cancel(timer)
                except tk.TclError:pass
                setattr(self,timer_name,None)
        if self._job_guard_timer is not None:
            try:
                self.root.after_cancel(self._job_guard_timer)
            except tk.TclError:
                pass
            self._job_guard_timer = None
        try:self.c.close()
        finally:self.root.destroy()

if __name__=='__main__':
    if len(sys.argv)>=2 and sys.argv[1]=='--check-job':
        raise SystemExit(verify_action.main(sys.argv[1:]))
    root=tk.Tk()
    if sys.platform=='win32':
        try:root.tk.call('tk','scaling',1.25)
        except Exception:pass
    App(root)
    root.mainloop()
