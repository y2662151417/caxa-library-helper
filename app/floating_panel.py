"""Tkinter control surface for the CAXA gallery workbench.

The panel routes allow-listed, task-signed operations to AHK. Geometry selection,
base points, property review and final insertion remain operator-controlled.
"""
from __future__ import annotations
import copy, json, os, tempfile, sys, ctypes, configparser, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import core, profiles, workflow_v08, router_v11, autoread, bridge, ahk_runtime, clipboard_utils

class Panel:
    def __init__(self, app):
        self.app=app
        self.win=tk.Toplevel(app.root)
        self.win.title('CAXA 制作控制台')
        sw=max(1024,self.win.winfo_screenwidth())
        sh=max(720,self.win.winfo_screenheight())
        self._expanded_geometry=f'320x265+{max(10,sw-340)}+{max(35,min(90,sh-315))}'
        self._collapsed_geometry=f'270x58+{max(10,sw-290)}+{max(35,min(90,sh-110))}'
        self.win.geometry(self._expanded_geometry)
        self.win.minsize(300,245)
        self.win.maxsize(340,285)
        self.win.resizable(False,False)
        self.win.attributes('-topmost',True)
        self.win.protocol('WM_DELETE_WINDOW',self.hide_panel)
        self.profile_path=core.storage_dir()/'my_gallery_profiles.json'
        self.profile_pref_path=core.storage_dir()/'active_profile.json'
        self.profiles=self._load_profiles()
        self.profile_choice=tk.StringVar(value=self._load_profile_preference())
        self.profile_display=tk.StringVar(value=self._profile_display_name(self.profile_choice.get()))
        self.lock_profile=tk.BooleanVar(value=self._load_profile_lock())
        self.color_rule_var=tk.StringVar(value='')
        self.color_rule_detail=tk.StringVar(value='请先选择已配置的颜色规则')
        self._color_rule_lookup={}
        self.color_combo=None
        self.view_tree=None
        self.combo=None
        self._color_flow_signature=''
        self._color_flow_source=''
        self._color_flow_profile_hash=''
        self.last_path=None
        self.context=tk.StringVar(value='当前未选择图纸')
        self.block_name_status=tk.StringVar(value='正式名称：尚未匹配')
        self.copy_name_button=None
        self._color_buttons={}
        self.apply_properties_button=None
        self.status=tk.StringVar(value='正在检查 CAD 控制器…')
        self.recommended=tk.StringVar(value='先选择图纸')
        self.action_reason=tk.StringVar(value='点击“选择图纸”，选中一行后点击“打开图纸”。系统会自动创建工作副本。')
        self.guide_status=tk.StringVar(value='视图引导尚未启动')
        self._closed=False
        self._after_ids=set()
        self._dialogs={}
        self._page_key='home'
        self._page_frame=None
        self._collapsed=False
        self.advanced_open=False
        self._topmost_suspended_until=0.0
        self._build_compact_ui()
        self.update_recommendation()
        self.win.bind('<Destroy>',self._on_destroy,add='+')
        self._schedule(120,self._enforce_topmost)
        self._schedule(700,self.ensure_ahk_controller)
        self._schedule(950,self._poll)


    def _build_compact_ui(self):
        self.normal_frame=ttk.Frame(self.win,padding=6)
        self.normal_frame.pack(fill='both',expand=True)
        header=ttk.Frame(self.normal_frame);header.pack(fill='x')
        ttk.Label(header,text='CAXA 制作助手',font=('Microsoft YaHei UI',9,'bold')).pack(side='left')
        ttk.Button(header,text='换图',width=4,command=self.open_workbench).pack(side='right',padx=(3,0))
        ttk.Button(header,text='⋯',width=3,command=self.open_settings_window).pack(side='right',padx=(3,0))
        ttk.Button(header,text='—',width=3,command=self.collapse_panel).pack(side='right')
        self.page_host=ttk.Frame(self.normal_frame)
        self.page_host.pack(fill='both',expand=True,pady=(3,1))
        ttk.Separator(self.normal_frame).pack(fill='x',pady=(2,3))
        ttk.Label(self.normal_frame,textvariable=self.status,wraplength=285,
                  foreground='#666',font=('Microsoft YaHei UI',8)).pack(anchor='w')
        self.collapsed_frame=ttk.Frame(self.win,padding=5)
        collapsed_row=ttk.Frame(self.collapsed_frame);collapsed_row.pack(fill='x')
        ttk.Label(collapsed_row,text='CAXA',font=('Microsoft YaHei UI',9,'bold')).pack(side='left')
        ttk.Label(collapsed_row,textvariable=self.context,wraplength=150,
                  font=('Microsoft YaHei UI',8)).pack(side='left',fill='x',expand=True,padx=5)
        ttk.Button(collapsed_row,text='展开',command=self.expand_panel).pack(side='right')
        self._show_home_page()

    def _clear_page_host(self):
        for child in self.page_host.winfo_children():
            try:child.destroy()
            except tk.TclError:pass
        self._page_frame=None
        self._dialogs.clear()
        self.color_combo=None
        self._color_buttons={}
        self.apply_properties_button=None
        self.view_tree=None
        self.copy_name_button=None

    def _show_home_page(self):
        self._clear_page_host()
        self._page_key='home'
        self.win.title('CAXA 制作助手')
        self.win.geometry(self._expanded_geometry)
        self.win.minsize(300,245);self.win.maxsize(340,285)
        body=ttk.Frame(self.page_host,padding=(1,2,1,0));body.pack(fill='both',expand=True)
        ttk.Label(body,textvariable=self.context,wraplength=292,
                  font=('Microsoft YaHei UI',8,'bold')).pack(anchor='w',pady=(0,1))
        ttk.Label(body,textvariable=self.block_name_status,wraplength=292,
                  foreground='#24527a',font=('Microsoft YaHei UI',8)).pack(anchor='w',pady=(0,3))

        color_row=ttk.Frame(body);color_row.pack(fill='x',pady=(0,2))
        color_specs=[
            ('红色','红色','#D92D20','#FFFFFF'),
            ('绿色','绿色','#16A34A','#FFFFFF'),
            ('蓝色','蓝色','#1D4ED8','#FFFFFF'),
            ('洋红','洋红色','#D000C8','#FFFFFF'),
            ('白+黑','白色+黑白色','#FFFFFF','#111111'),
        ]
        for col,(label,source,bg,fg) in enumerate(color_specs):
            color_row.columnconfigure(col,weight=1)
            button=tk.Button(color_row,text=label,relief='raised',bd=1,
                bg=bg,fg=fg,activebackground=bg,activeforeground=fg,
                font=('Microsoft YaHei UI',8),height=1,
                command=lambda value=source:self.open_color_filter(value))
            button.grid(row=0,column=col,sticky='ew',padx=1,pady=1)
            self._color_buttons[source]=button

        ttk.Button(body,text='恢复全选',command=self.restore_color_filter).pack(
            fill='x',pady=(1,3),ipady=1)
        self.apply_properties_button=ttk.Button(body,text='一键设置特性',
            command=self.open_color_properties)
        self.apply_properties_button.pack(fill='x',pady=(0,3),ipady=2)
        actions=ttk.Frame(body);actions.pack(fill='x',pady=(0,3))
        actions.columnconfigure(0,weight=1);actions.columnconfigure(1,weight=1)
        ttk.Button(actions,text='删除重线',command=self.delete_duplicate_lines).grid(
            row=0,column=0,sticky='ew',padx=(0,2))
        ttk.Button(actions,text='定义属性块',command=self.define_symbol).grid(
            row=0,column=1,sticky='ew',padx=(2,0))
        self.copy_name_button=ttk.Button(body,text='复制正式块名称',command=self.copy_block_name)
        self.copy_name_button.pack(fill='x')
        self.refresh_color_buttons()

    def refresh_color_buttons(self):
        try:
            configured={r['source_color'] for r in core.get_cad_color_rules(self.app.c)}
        except Exception:
            configured=set()
        for source,button in self._color_buttons.items():
            try:
                button.configure(state='normal' if source in configured else 'disabled')
            except tk.TclError:
                pass

    def open_actions_page(self):
        w=self._dialog('actions','操作入口','350x420')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Label(w,text='只在需要时进入对应操作；所有页面都在这个悬浮窗口内切换。',
                  wraplength=320,foreground='#666').pack(anchor='w',pady=(0,8))
        ttk.Button(w,text='清理图纸',command=self.open_cleanup_window).pack(fill='x',pady=3,ipady=4)
        ttk.Button(w,text='开始定义图符',command=self.define_symbol).pack(fill='x',pady=3,ipady=4)
        # 属性核对和最终入库由操作者在 CAXA 中完成；助手不提供提交入口。
        ttk.Separator(w).pack(fill='x',pady=7)
        ttk.Button(w,text='连接当前 CAXA',command=self.connect_cad).pack(fill='x',pady=3)
        ttk.Separator(w).pack(fill='x',pady=6)
        ttk.Button(w,text='只读诊断 CAXA 控件',command=self.probe_cad_controls).pack(fill='x',pady=3,ipady=4)
        ttk.Label(w,text='仅记录窗口/控件类别和位置；不读取图纸文字，不点击、不修改、不保存。',
                  wraplength=315,foreground='#666').pack(anchor='w',pady=(2,0))
    def collapse_panel(self):
        if self._collapsed:return
        self._collapsed=True
        self.normal_frame.pack_forget()
        self.collapsed_frame.pack(fill='both',expand=True)
        self.win.geometry(self._collapsed_geometry)
        self.win.minsize(260,52);self.win.maxsize(310,70)

    def expand_panel(self):
        if not self._collapsed:return
        self._collapsed=False
        self.collapsed_frame.pack_forget()
        self.normal_frame.pack(fill='both',expand=True)
        self.win.minsize(285,210);self.win.maxsize(340,270)
        self.win.geometry(self._expanded_geometry)
        self.win.attributes('-topmost',True)

    def hide_panel(self):
        try:self.win.withdraw()
        except tk.TclError:pass

    def suspend_topmost(self):
        """Temporarily release the topmost flag while a focused task window is open."""
        self._topmost_suspended_until=float('inf')
        try:self.win.attributes('-topmost',False)
        except tk.TclError:pass

    def resume_topmost(self):
        """Restore the compact assistant above CAXA after a task window closes."""
        self._topmost_suspended_until=0.0
        try:
            if self.win.state()!='withdrawn':
                self.win.attributes('-topmost',True)
                self.win.lift()
        except tk.TclError:pass

    def open_workbench(self):
        try:
            self.app.open_drawing_selector()
            self.status.set('选择图纸窗口已打开。选中图纸后，点击“打开工作副本”即可继续。')
        except Exception as e:
            self.status.set('无法打开图纸选择窗口：'+str(e))


    def _dialog(self,key,title,geometry):
        if self._page_key==key and self._page_frame is not None:
            try:
                if self._page_frame.winfo_exists():return self._page_frame
            except tk.TclError:pass
        self._clear_page_host()
        self._page_key=key
        self._dialogs[key]=self.win
        self.win.title('CAXA 制作助手')
        self.win.geometry(geometry)
        self.win.minsize(320,270);self.win.maxsize(430,650)
        nav=ttk.Frame(self.page_host);nav.pack(fill='x',pady=(0,5))
        ttk.Button(nav,text='← 返回',command=self._show_home_page).pack(side='left')
        ttk.Label(nav,text=title,font=('Microsoft YaHei UI',10,'bold')).pack(side='left',padx=8)
        page=ttk.Frame(self.page_host,padding=8);page.pack(fill='both',expand=True)
        page._caxa_built=False
        self._page_frame=page
        return page

    def open_cleanup_window(self):
        w=self._dialog('cleanup','清理图纸','350x300')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Label(w,text='重复线清理',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,5))
        ttk.Label(w,text='启动 CAXA 原生命令后，由你框选需要检查的机械视图范围并确认。不会自动选择或删除图元。',
                  wraplength=315,foreground='#555').pack(anchor='w',pady=4)
        ttk.Button(w,text='启动删除重复线',command=self.delete_duplicate_lines).pack(fill='x',pady=8,ipady=6)
        ttk.Separator(w).pack(fill='x',pady=5)
        ttk.Label(w,text='颜色映射已从配置 Excel 读取。拾取过滤和属性批量写入正在校准 CAXA 2024 控件；校准前不会猜测控件位置或自动改图。',
                  wraplength=315,foreground='#8a5a20').pack(anchor='w',pady=5)
    def open_views_window(self):
        # This is a batch/type-level preference, not a per-drawing prompt.
        w=self._dialog('views','视图模板设置','370x285')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        body=ttk.Frame(w,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,text='默认视图模板',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,4))
        ttk.Label(body,text='同一类型的图纸只需设置一次。主视图和左视图固定，俯视图按该批图纸的实际要求决定是否需要。',
                  wraplength=335,foreground='#555').pack(anchor='w',pady=3)
        current=list(self.app.last_view_template)
        mode=tk.StringVar(value='three' if current==list(core.DEFAULT_VIEW_TEMPLATE) else 'two')
        choices=ttk.LabelFrame(body,text='选择制作方案',padding=7);choices.pack(fill='x',pady=6)
        ttk.Radiobutton(choices,text='三视图：主视图 + 俯视图 + 左视图（6个版本）',
                        variable=mode,value='three').pack(anchor='w',pady=4)
        ttk.Radiobutton(choices,text='双视图：主视图 + 左视图（4个版本）',
                        variable=mode,value='two').pack(anchor='w',pady=4)
        def save():
            selected=list(core.DEFAULT_VIEW_TEMPLATE if mode.get()=='three' else core.TWO_VIEW_TEMPLATE)
            try:
                self.app.save_view_template(selected)
            except Exception as e:
                messagebox.showerror('模板保存失败',str(e),parent=self.win);return
            self.status.set('视图模板已保存；尚未建立视图计划的图纸会自动沿用。')
            self.update_recommendation()
            self._show_home_page()
            messagebox.showinfo('视图模板已保存',
                core.view_template_summary(selected)+'\n\n已建立视图计划的图纸不会被自动改动。',
                parent=self.win)
        ttk.Button(body,text='保存视图模板',command=save).pack(fill='x',pady=(7,4),ipady=5)
        ttk.Label(body,text='模板保存在本机。已有图纸计划不会被覆盖；后续尚未建立计划的图纸自动使用新方案。',
                  wraplength=335,foreground='#666').pack(anchor='w',pady=3)

    def _update_view_plan_from_panel(self):
        if not self.require():return
        self.app.update_plan()
        self._refresh_view_table()
        self.status.set('当前图纸的视图计划已更新。')

    def _refresh_view_table(self):
        if self.view_tree is None or not self.app.path:return
        try:
            for iid in self.view_tree.get_children():self.view_tree.delete(iid)
            for i,row in enumerate(core.slots_for(self.app.c,self.app.path)):
                self.view_tree.insert('', 'end',iid=str(i),values=(row['view_type'],row['size_kind'],row['status']))
        except Exception as e:
            self.status.set('视图状态暂不可读：'+str(e))

    def _set_view_status_from_panel(self,state):
        if not self.require() or self.view_tree is None:return
        selected=self.view_tree.selection()
        parent=self._dialogs.get('views',self.win)
        if not selected:
            messagebox.showwarning('未选视图版本','请先在视图版本表中选择一行。',parent=parent);return
        view,kind,_=self.view_tree.item(selected[0],'values')
        if state=='已复核':
            if not messagebox.askyesno('人工复核声明',
                f'{view} / {kind}\n\n请确认已在 CAXA 检查对象完整、图层符合规范、基点准确、属性已填入、图符已入库并重新插入测试。\n\n这只是人工记录，不会自动检查 EXB。',parent=parent,default='no'):return
        elif state=='不需要':
            if not messagebox.askyesno('明确跳过',f'确定公司本张图不要求制作 {view} / {kind} 吗？',parent=parent,default='no'):return
        try:
            core.set_slot(self.app.c,self.app.path,view,kind,state)
            self.app.load_detail(self.app.path);self.app.refresh();self.app.sync_job()
            self._refresh_view_table();self.update_recommendation()
        except Exception as e:messagebox.showerror('视图状态更新失败',str(e),parent=parent)

    def _review_all_views_from_panel(self):
        if not self.require():return
        parent=self._dialogs.get('views',self.win)
        if not messagebox.askyesno('批量人工复核',
            '确认你已逐项检查当前图纸所有计划视图的带/无尺寸版本、对象、基点及实际入库结果？\n\n此操作只更新本地记录，不会检查或修改 CAXA。',parent=parent,default='no'):return
        try:
            core.mark_all_slots_reviewed(self.app.c,self.app.path)
            self.app.load_detail(self.app.path);self.app.refresh();self.app.sync_job()
            self._refresh_view_table();self.update_recommendation()
        except Exception as e:messagebox.showerror('复核失败',str(e),parent=parent)


    def open_insert_window(self):
        w=self._dialog('insert','属性与入库','360x430')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Label(w,textvariable=self.block_name_status,wraplength=325,
                  foreground='#24527a').pack(anchor='w',pady=(0,7))
        ttk.Button(w,text='填写正式块名称',command=self.fill_symbol_name).pack(fill='x',pady=3,ipady=4)
        ttk.Button(w,text='复制正式块名称',command=self.copy_block_name).pack(fill='x',pady=3,ipady=4)
        ttk.Separator(w).pack(fill='x',pady=6)
        ttk.Button(w,text='属性编辑',command=self.edit_symbol_attributes).pack(fill='x',pady=3,ipady=4)
        ttk.Button(w,text='填入标题栏属性',command=self.fill_titleblock_attributes).pack(fill='x',pady=3,ipady=4)
        ttk.Button(w,text='确认并完成入库',command=self.finish_gallery_insert).pack(fill='x',pady=5,ipady=5)
        ttk.Label(w,text='入库后仍须重新插入图符，检查视图、基点和属性。全部检查完成后，再记录本张人工复核。',
                  wraplength=325,foreground='#666').pack(anchor='w',pady=6)
        ttk.Button(w,text='人工复核清单',command=self.open_qc_page).pack(fill='x',pady=4)

    def open_qc_page(self):
        w=self._dialog('qc','人工复核','360x500')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Label(w,text='只有实际检查完成后才勾选。每项确认都会保存到本机进度记录。',
                  wraplength=325,foreground='#555').pack(anchor='w',pady=(0,7))
        for key,label in core.QC_ITEMS:
            tk.Checkbutton(w,text=label,variable=self.app.qc_vars[key],
                command=lambda k=key:self.app.on_qc_change(k),
                wraplength=325,justify='left',anchor='w').pack(fill='x',anchor='w',pady=4)
        ttk.Separator(w).pack(fill='x',pady=6)
        ttk.Button(w,text='确认全部计划视图已逐项复核',command=self._review_all_views_from_panel).pack(fill='x',pady=4)
        ttk.Button(w,text='记录本张人工复核完成',command=self.signoff_current_drawing).pack(fill='x',pady=4,ipady=4)


    def signoff_current_drawing(self):
        if not self.require():return
        if not messagebox.askyesno('最终人工复核',
            '确认本张所有计划视图、正式名称、基点、属性、图库插入及重新插入结果均已检查并保存？',
            parent=self.win,default='no'):return
        try:
            core.finish_drawing(self.app.c,self.app.path)
            self.app.refresh();self.app.sync_job();self.update_recommendation()
            self.status.set('本张已记录为人工复核完成；可以进入下一张。')
            self._show_home_page()
        except Exception as e:
            messagebox.showwarning('尚不能标记完成',str(e),parent=self.win)
    def open_settings_window(self):
        w=self._dialog('settings','设置','350x430')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Button(w,text='打开助手数据文件夹（诊断日志）',
                   command=self.open_data_folder).pack(fill='x',pady=(0,5))
        ttk.Label(w,text='如再次出现“面板请求过期”，请将 panel_action_expiry.log 发回。',
                  wraplength=315,foreground='#8a5a20').pack(anchor='w',pady=(0,5))
        ttk.Separator(w).pack(fill='x',pady=(0,5))
        ttk.Label(w,text='制作模板',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,4))
        self.combo=ttk.Combobox(w,state='readonly',textvariable=self.profile_display,
                                values=[self._profile_display_name(x['id']) for x in self.profiles])
        self.combo.pack(fill='x',pady=4)
        self.combo.bind('<<ComboboxSelected>>',self._on_profile_display_change)
        ttk.Checkbutton(w,text='切换图纸时保留当前模板',variable=self.lock_profile,
                        command=self._save_profile_preference).pack(anchor='w',pady=5)
        ttk.Separator(w).pack(fill='x',pady=7)
        ttk.Label(w,text='视图方案',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(2,2))
        ttk.Label(w,textvariable=self.app.view_template_summary_var,wraplength=315,
                  foreground='#555').pack(anchor='w',pady=2)
        ttk.Button(w,text='设置视图模板（双视图 / 三视图）',
                   command=self.open_views_window).pack(fill='x',pady=4,ipady=4)
        ttk.Separator(w).pack(fill='x',pady=7)
        ttk.Button(w,text='首次校准其他 CAD 控件',command=self.open_calibration_window).pack(fill='x',pady=4,ipady=4)
        ttk.Label(w,text='颜色映射从配置 Excel 读取。对象颜色、线型、线宽均按 ByLayer；线型比例为 1。',
                  wraplength=315,foreground='#666').pack(anchor='w',pady=5)
        ttk.Button(w,text='查看颜色映射规则',command=self.show_colors).pack(fill='x',pady=3)
    def _enforce_topmost(self):
        if self._closed:return
        try:
            if self.win.state()!='withdrawn' and time.monotonic()>=self._topmost_suspended_until:
                self.win.attributes('-topmost',True)
                if sys.platform=='win32':
                    hwnd=self.win.winfo_id()
                    # HWND_TOPMOST with NOACTIVATE: keep the palette above CAXA
                    # without stealing keyboard focus from the drawing canvas.
                    ctypes.windll.user32.SetWindowPos(hwnd,-1,0,0,0,0,0x0001|0x0002|0x0010)
        except Exception:pass
        self._schedule(900,self._enforce_topmost)

    def _schedule(self,delay,callback):
        holder={}
        def run():
            aid=holder.get('id')
            if aid:self._after_ids.discard(aid)
            if self._closed:return
            try:
                if self.win.winfo_exists():callback()
            except tk.TclError:
                return
        aid=self.win.after(delay,run)
        holder['id']=aid
        self._after_ids.add(aid)
        return aid

    def _on_destroy(self,event):
        if event.widget is not self.win:return
        self._closed=True
        for aid in tuple(self._after_ids):
            try:self.win.after_cancel(aid)
            except tk.TclError:pass
        self._after_ids.clear()

    def _default_profile_id(self):
        # Prefer the first equipment-specific profile; generic naming is a fallback.
        for profile in self.profiles:
            if profile.get('required_params') or profile.get('view_plan'):
                return profile['id']
        return self.profiles[0]['id']

    def _load_profile_preference(self):
        ids={x['id'] for x in self.profiles}
        try:
            data=json.loads(self.profile_pref_path.read_text(encoding='utf-8'))
            preferred=data.get('profile_id','')
            if preferred in ids:return preferred
        except (OSError,ValueError,TypeError):pass
        return self._default_profile_id()

    def _load_profile_lock(self):
        try:
            data=json.loads(self.profile_pref_path.read_text(encoding='utf-8'))
            return bool(data.get('keep_on_switch',True))
        except (OSError,ValueError,TypeError):return True

    def _save_profile_preference(self):
        try:
            self.profile_pref_path.parent.mkdir(parents=True,exist_ok=True)
            data={'profile_id':self.profile_choice.get(),'keep_on_switch':bool(self.lock_profile.get())}
            tmp=self.profile_pref_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(tmp,self.profile_pref_path)
        except OSError as e:
            self.status.set('模板偏好未保存：'+str(e))

    def _on_profile_change(self):
        self._color_flow_signature='';self._color_flow_source='';self._color_flow_profile_hash=''
        self.update_color_rule_choices()
        self._save_profile_preference()
        self.status.set('制作模板已切换并保存；后续图纸默认沿用该模板。')

    def _load_profiles(self):
        default=Path(__file__).resolve().parent / 'resources' / '图库模板_示例.json'
        try: return profiles.read_profiles(self.profile_path if self.profile_path.is_file() else default)
        except Exception as e:
            messagebox.showwarning('模板异常','自定义模板无效，改用内置模板：'+str(e))
            return profiles.read_profiles(default)

    def _profile_display_name(self,profile_id):
        p=next((x for x in self.profiles if x['id']==profile_id),None)
        if not p:return profile_id
        return p.get('label',profile_id).split('（')[0].split('(')[0].strip()

    def _on_profile_display_change(self,_event=None):
        label=self.profile_display.get()
        p=next((x for x in self.profiles if self._profile_display_name(x['id'])==label),None)
        if p:
            self.profile_choice.set(p['id'])
            self._on_profile_change()

    def current_profile(self):
        return next(p for p in self.profiles if p['id']==self.profile_choice.get())

    def _poll(self):
        try:
            row=core.get_drawing(self.app.c,self.app.path) if self.app.path else None
            if self.app.path!=self.last_path:
                self.last_path=self.app.path
                self._color_flow_signature='';self._color_flow_source='';self._color_flow_profile_hash=''
                if not self.lock_profile.get():
                    self.profile_choice.set(self._default_profile_id())
                    self.profile_display.set(self._profile_display_name(self.profile_choice.get()))
                    self.update_color_rule_choices();self._save_profile_preference()
                    self.status.set('已切换图纸，模板恢复通用默认。请核实设备类别。')
            if row:
                self.context.set(row['code']+'｜'+row['name'][:10])
                try:
                    info=core.block_name_for_path(self.app.c,self.app.path)
                    self.block_name_status.set('名称：已匹配' if info.get('status')=='已匹配'
                                               else '名称：'+info.get('status','待匹配'))
                    if self.copy_name_button is not None:
                        self.copy_name_button.configure(state='normal' if info.get('status')=='已匹配' else 'disabled')
                except Exception:
                    self.block_name_status.set('名称：暂不可读取')
            else:
                self.context.set('尚未选择图纸')
                self.block_name_status.set('名称：请先选择图纸并导入 Excel')
                if self.copy_name_button is not None:
                    self.copy_name_button.configure(state='disabled')
            self.refresh_color_buttons()
            self.update_recommendation()
            self._refresh_guide_status()
            if self.view_tree is not None:self._refresh_view_table()
        finally:
            if not self._closed:self._schedule(1200,self._poll)

    def _published_job(self):
        if not self.require():
            return None
        try:
            # Re-publish only after the normal workbench handoff checks.
            self.app.sync_job()
            path=core.storage_dir()/'active_job.ini'
            if not path.is_file():
                raise ValueError('当前图纸尚未形成有效快捷任务。请先创建工作副本、确认名称并设置视图计划。')
            job=bridge.read_active_job(path)
            if not job.get('job_signature') or not job.get('working_file'):
                raise ValueError('当前任务缺少签名或工作副本信息。')
            if not Path(job.get('working_path','')).is_file():
                raise ValueError('工作副本不存在，请重新创建或打开工作副本。')
            return job
        except Exception as e:
            messagebox.showwarning('当前任务不可用',str(e),parent=self.win)
            return None

    def _queue_ahk_action(self,action,confirm_text=None,source_color=None,target_layer=None,
                          target_color=None,target_linetype=None,linetype_scale=None,target_lineweight=None):
        job=self._published_job()
        if not job:return False
        if sys.platform=='win32':
            pid=ahk_runtime.read_controller_pid(core.storage_dir())
            build=ahk_runtime.read_controller_build(core.storage_dir())
            if not self._pid_alive(pid):
                self.status.set('CAXA 控制器未运行；请等待控制器连接后再操作。')
                return False
            if build!=ahk_runtime.CONTROLLER_BUILD_ID:
                self.status.set('检测到旧版 CAXA 控制器。请在系统托盘中右键旧版 H 图标选择 Exit，然后重新启动制作助手。')
                return False
        if confirm_text and not messagebox.askyesno('确认 CAXA 操作',confirm_text.format(
                code=job.get('code',''),work=job.get('working_file','')),parent=self.win,default='no'):
            return False
        try:
            bridge.request_panel_action(core.storage_dir(),action,job['job_signature'],
                source_color=source_color,target_layer=target_layer,target_color=target_color,
                target_linetype=target_linetype,linetype_scale=linetype_scale,
                target_lineweight=target_lineweight)
            self.status.set('操作请求已发送；正在核验当前 CAXA 图纸。')
            return True
        except Exception as e:
            messagebox.showerror('发送失败',str(e),parent=self.win)
            return False

    def _pid_alive(self,pid):
        if sys.platform!='win32' or pid<=0:return False
        try:
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.restype=ctypes.c_void_p
            kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
            kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:return False
            code=ctypes.c_ulong()
            ok=kernel.GetExitCodeProcess(handle,ctypes.byref(code))
            kernel.CloseHandle(handle)
            return bool(ok and code.value==259)
        except Exception:return False


    def ensure_ahk_controller(self):
        if sys.platform!='win32':
            self.status.set('CAXA 控制器仅支持 Windows。')
            return
        pid=ahk_runtime.read_controller_pid(core.storage_dir())
        if self._pid_alive(pid):
            build=ahk_runtime.read_controller_build(core.storage_dir())
            if build==ahk_runtime.CONTROLLER_BUILD_ID:
                self.status.set(f'CAXA 控制器已连接（{build}）；可以直接使用上方操作。')
            else:
                self.status.set('检测到旧版 CAXA 控制器。请在系统托盘中右键旧版 H 图标选择 Exit，然后重新启动制作助手。')
            return
        try:
            self.status.set('正在准备并验证 CAXA 控制器…')
            self.app.launch_hotkeys(on_complete=self._ahk_launch_complete)
        except Exception as e:
            self.status.set('控制器未启动：'+str(e))

    def _ahk_launch_complete(self, ok, message):
        if self._closed:
            return
        if ok:
            self.check_ahk_controller_start()
        else:
            first=message.splitlines()[0] if message else '未知启动错误'
            self.status.set(first[:190])

    def check_ahk_controller_start(self):
        pid=ahk_runtime.read_controller_pid(core.storage_dir())
        if self._pid_alive(pid):
            build=ahk_runtime.read_controller_build(core.storage_dir())
            if build==ahk_runtime.CONTROLLER_BUILD_ID:
                self.status.set(f'CAXA 控制器已连接（{build}；PID {pid}）；可以开始操作。')
            else:
                self.status.set('控制器版本不匹配；请退出系统托盘中的旧版 H 图标，再重新启动制作助手。')
            return
        root=core.storage_dir()
        marker_error=root/'ahk_controller_marker_error.log'
        startup_log=root/'ahk_controller_startup.log'
        details=[]
        for path in (marker_error,startup_log):
            try:
                value=path.read_text(encoding='utf-8-sig',errors='replace').strip()
            except OSError:
                value=''
            if value:
                details.append(value[-500:])
        if details:
            self.status.set('控制器未注册：'+details[-1].splitlines()[-1][:150])
        else:
            self.status.set('控制器未注册；诊断日志：'+str(startup_log))
    def connect_cad(self):
        self._queue_ahk_action('bind_cad',
            '将尝试定位当前任务的工作副本窗口：\n图号：{code}\n工作副本：{work}\n\n找到唯一匹配窗口后会显示进程信息，请确认绑定。')

    def probe_cad_controls(self):
        self._queue_ahk_action('probe_cad_controls',
            '请确认当前任务对应的 CAXA 工作副本是自制的虚构测试图纸。\n\n'
            '诊断只读取窗口类名、控件类名和控件位置；不会保存或输出窗口标题、图纸文字、参数或实体内容；'
            '不会点击、发送 CAD 命令、修改或保存图纸。\n\n继续？')

    def delete_duplicate_lines(self):
        self._show_home_page()
        self._queue_ahk_action('duplicate_line_cleanup')
    def fill_symbol_name(self):
        # One click queues a signed request. AHK writes only the calibrated name
        # field and reads it back; a non-empty different value still prompts.
        self._queue_ahk_action('fill_symbol_name')

    def _refresh_guide_status(self):
        """Read the AHK operator checklist checkpoint; never infer CAD completion."""
        try:
            job_path=core.storage_dir()/'active_job.ini'
            checkpoint=core.storage_dir()/'view_guide_checkpoint.ini'
            if not job_path.is_file() or not checkpoint.is_file():
                self.guide_status.set('视图引导尚未启动')
                return
            job=bridge.read_active_job(job_path)
            cfg=configparser.ConfigParser(interpolation=None)
            cfg.read(checkpoint,encoding='utf-16')
            if 'guide' not in cfg:
                self.guide_status.set('没有可用的视图引导记录')
                return
            g=cfg['guide']
            plan=job.get('view_plan','').split('|') if job.get('view_plan') else []
            if (g.get('signature','')!=job.get('job_signature','') or
                g.get('working_file','')!=job.get('working_file','') or
                g.get('view_plan','')!=job.get('view_plan','') or not plan):
                self.guide_status.set('视图引导记录与当前任务不一致；请重新启动引导')
                return
            cursor=int(g.get('cursor','0'));count=int(g.get('count','0'))
            if count!=len(plan) or cursor<1 or cursor>count+1:
                self.guide_status.set('视图引导记录无效；请重新启动引导')
            elif cursor>count:
                self.guide_status.set(f'已人工确认全部 {count} 项视图；请检查 CAXA 入库窗口、属性和插入结果')
            else:
                step=plan[cursor-1]
                hint='；请先手动关闭尺寸线层' if step.endswith('·无尺寸') and (cursor==1 or not plan[cursor-2].endswith('·无尺寸')) else ''
                self.guide_status.set(f'当前第 {cursor}/{count} 项：{step}{hint}（人工完成后点击“下一视图”）')
        except Exception:
            self.guide_status.set('视图引导状态暂不可读；请以 CAXA 实际界面为准')

    def _queue_guide_action(self,action):
        # Coordinate-based calibrated clicks must not be intercepted by this
        # always-on-top panel. Lower it briefly while the AHK controller clicks.
        lower = action in ('define_symbol','edit_symbol_attributes','fill_titleblock_attributes','finish_gallery_insert')
        if lower:
            self._topmost_suspended_until=time.monotonic()+1.8
            self.win.attributes('-topmost',False)
        if self._queue_ahk_action(action):
            self.status.set('已发送视图/图库操作请求；控制器正在核对当前工作副本。')
            self._schedule(350,self._refresh_guide_status)
            if lower:self._schedule(1900,self._restore_panel_topmost)
        elif lower:
            self._topmost_suspended_until=0
            self._schedule(300,self._restore_panel_topmost)

    def _restore_panel_topmost(self):
        self._topmost_suspended_until=0
        try:
            if self.win.winfo_exists():
                self.win.attributes('-topmost',True)
        except tk.TclError:pass

    def start_view_guide(self):
        self._queue_guide_action('start_view_guide')

    def next_view(self):
        self._queue_guide_action('next_view')

    def previous_view(self):
        self._queue_guide_action('previous_view')

    def show_view_guide(self):
        self._queue_guide_action('show_view_guide')

    def end_view_guide(self):
        self._queue_guide_action('end_view_guide')
        self._schedule(500,self._refresh_guide_status)


    def define_symbol(self):
        if not self.require():return
        job=self._published_job()
        if not job:return
        raw_plan=job.get('view_plan','')
        plan=raw_plan.split('|') if raw_plan else []
        if len(plan) not in (4,6) or any(not item.strip() for item in plan):
            messagebox.showwarning('视图计划无效','当前图纸必须是双视图4项（主视图、左视图）或三视图6项（主视图、俯视图、左视图），每种视图各有带尺寸和无尺寸版本。请先核对本张视图计划。',parent=self.win)
            return
        self._show_home_page()
        self._queue_guide_action('define_symbol')
    def edit_symbol_attributes(self):
        self._queue_guide_action('edit_symbol_attributes')

    def fill_titleblock_attributes(self):
        self._queue_guide_action('fill_titleblock_attributes')

    def _guide_checkpoint_complete(self,job):
        try:
            checkpoint=core.storage_dir()/'view_guide_checkpoint.ini'
            if not checkpoint.is_file():return False
            cfg=configparser.ConfigParser(interpolation=None);cfg.read(checkpoint,encoding='utf-16')
            if 'guide' not in cfg:return False
            g=cfg['guide'];plan=job.get('view_plan','').split('|') if job.get('view_plan') else []
            return (bool(plan) and g.get('signature','')==job.get('job_signature','')
                    and g.get('working_file','')==job.get('working_file','')
                    and g.get('view_plan','')==job.get('view_plan','')
                    and int(g.get('count','0'))==len(plan)
                    and int(g.get('cursor','0'))==len(plan)+1)
        except Exception:return False

    def finish_gallery_insert(self):
        if not self.require():return
        job=self._published_job()
        if not job:return
        if job.get('block_name_status')!='已匹配' or not job.get('block_name'):
            messagebox.showwarning('正式块名称未匹配','当前图纸没有按完整图号唯一匹配正式块名称，不能执行最终入库。',parent=self.win);return
        if not messagebox.askyesno('最终入库确认',
            '即将点击 CAXA 图符入库窗口中的【完成】按钮。\n\n请确认：\n'
            '① 正式块名称与当前图号一致；\n② 图库类别正确；\n③ 标题栏属性已填入并核对；\n'
            '④ 六个（或当前计划的全部）视图及基点正确；\n⑤ 已检查不会覆盖错误的已有图符。\n\n'
            '如果 CAXA 随后弹出覆盖确认，助手不会自动替你选择。',parent=self.win,default='no'):
            return
        self._queue_guide_action('finish_gallery_insert')

    def show_dimension_steps(self):
        self._text_window('带尺寸／无尺寸制作顺序',
            '1. 先保持尺寸线层显示，完成所有需要的带尺寸视图。\n'
            '2. 检查带尺寸视图的对象范围、基点及图形完整性。\n'
            '3. 在 CAXA 图层管理中手动关闭尺寸线层；不要删除尺寸对象。\n'
            '4. 按视图计划完成全部无尺寸视图。\n'
            '5. 恢复尺寸线层显示，并检查图面没有误关其它图层。\n\n'
            '注意：当前版本不自动切换图层可见性，因为尚未验证 CAXA 2024 图层列表控件及行状态。')


    def open_calibration_window(self):
        w=self._dialog('calibration','首次校准','370x500')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        ttk.Label(w,text='属性自动设置只需校准一次。先切换 CAXA 的“常用”选项卡，再点击对应按钮；鼠标移到目标下拉框上停留 8 秒，不要点击。',
                  wraplength=335,foreground='#555').pack(anchor='w',pady=(0,8))
        ttk.Label(w,text='一键设置特性（必需）',font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w',pady=(2,3))
        for label,action in (
            ('校准图层下拉框','calibrate_layer_combo'),
            ('校准颜色下拉框','calibrate_color_combo'),
            ('校准线型下拉框','calibrate_linetype_combo'),
            ('校准线宽下拉框','calibrate_lineweight_combo')):
            ttk.Button(w,text=label,command=lambda a=action:self._begin_calibration(a,w,9000)).pack(fill='x',pady=2,ipady=2)
        ttk.Button(w,text='诊断左侧特性栏（只读）',
                   command=lambda:self._queue_ahk_action('probe_properties_palette')).pack(
                       fill='x',pady=(5,2),ipady=2)
        ttk.Label(w,text='先在测试图中框选少量对象，再运行诊断；仅读取属性字段和控件信息，不修改图纸。',
                  wraplength=335,foreground='#666').pack(anchor='w',pady=(0,5))
        ttk.Separator(w).pack(fill='x',pady=7)
        ttk.Label(w,text='其他低频控件',font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w',pady=(2,3))
        for label,action in (
            ('属性编辑按钮','calibrate_attr_edit'),
            ('标题栏属性填入按钮','calibrate_attr_fill'),
            ('图符名称输入框','calibrate_symbol_name'),
            ('图符入库完成按钮','calibrate_gallery_finish')):
            ttk.Button(w,text=label,command=lambda a=action:self._begin_calibration(a,w)).pack(fill='x',pady=2,ipady=2)

    def _begin_calibration(self,action,dialog,restore_ms=7200):
        if self._queue_ahk_action(action):
            self.win.withdraw()
            self._schedule(restore_ms,self._restore_after_calibration)
    def _restore_after_calibration(self):
        try:
            if self.win.winfo_exists():
                self.win.deiconify();self._topmost_suspended_until=0;self.win.attributes('-topmost',True)
                self.status.set('首次校准流程结束；请检查状态提示并继续。')
        except tk.TclError:pass

    def copy_block_name(self):
        if self.app.copy_official_block_name(parent=self.win):
            self.status.set('正式块名称已复制；请在 CAXA 中人工核对并粘贴')

    def toggle_advanced(self):
        if self._page_key=='settings':
            self._show_home_page()
        else:
            self.open_settings_window()
    def suggested_action(self, verify_content=False):
        if not self.app.path:return router_v11.choose(None,work_exists=False,slots=[],configured_views=False,changed=False)
        d=core.get_drawing(self.app.c,self.app.path)
        if not d:return router_v11.choose(None,work_exists=False,slots=[],configured_views=False,changed=False)
        work=Path(d['working_path']) if d['working_path'] else None
        # The frequent UI refresh uses cheap stat checks; a real command click
        # rehashes source and reviewed working file (which may be many MB).
        changed=False
        try:
            src=Path(d['path'])
            if not src.is_file():changed=True
            else:
                st=src.stat()
                changed=(st.st_size != d['size_bytes'] or st.st_mtime_ns != d['mtime_ns'])
                if verify_content and d['sha256']:
                    changed=changed or core.digest_file(src)!=d['sha256']
            if d['working_review_sha256']:
                work=Path(d['working_path'])
                changed=changed or not work.is_file()
                if verify_content and work.is_file():
                    changed=changed or core.digest_file(work)!=d['working_review_sha256']
        except OSError:
            changed=True
        rows=[dict(x) for x in core.slots_for(self.app.c,self.app.path)]
        block_info=core.block_name_for_path(self.app.c,self.app.path)
        has_exact_block_name=(block_info.get('status')=='已匹配' and bool(block_info.get('block_name')))
        return router_v11.choose(dict(d),work_exists=bool(work and work.is_file()),
            slots=rows,configured_views=bool(self.app.last_view_template),
            changed=changed,has_exact_block_name=has_exact_block_name)


    def do_recommended(self):
        action=self.suggested_action(verify_content=True).key
        if action=='open_copy':self.open_copy()
        elif action=='parse_name':self.parse_name()
        elif action=='prepare_views':self.prepare_views()
        elif action=='next':self.app.next_pending()
        elif action=='review':self.open_qc_page()
        elif action=='define_symbol':self.define_symbol()
        elif action=='cad_guide':self.open_actions_page()
        elif action=='configure_views':self.open_views_window()
        elif action=='blocked':
            messagebox.showwarning('已停止自动推进',self.suggested_action(verify_content=True).reason+'\n请在主工作台检查并刷新。',parent=self.win)
        else:self.open_workbench()
        self.update_recommendation()
    def update_recommendation(self):
        act=self.suggested_action()
        self.recommended.set(act.label)
        self.action_reason.set(act.reason)

    def require(self):
        if not self.app.path:
            messagebox.showwarning('未选图纸','请先在主工作台选择图纸',parent=self.win)
            return False
        return True

    def open_copy(self):
        if self.require(): self.app.open_work_copy()

    def show_plan(self):
        plan=workflow_v08.plan_summary(self.current_profile())
        self._text_window('本类图纸制作计划',plan)

    def _text_window(self,title,body):
        win=tk.Toplevel(self.win);win.title(title);win.geometry('620x560')
        text=tk.Text(win,wrap='word',font=('Microsoft YaHei UI',10))
        text.insert('1.0',body);text.configure(state='disabled')
        text.pack(fill='both',expand=True,padx=10,pady=10)
        ttk.Button(win,text='关闭',command=win.destroy).pack(pady=(0,8))

    def update_color_rule_choices(self):
        try:
            rules=self.current_profile().get('color_rules',[])
        except Exception:
            rules=[]
        self._color_rule_lookup={}
        labels=[]
        for rule in rules:
            source=rule.get('source_color','')
            label=f"{source} → {rule.get('target_layer') or '未配置图层'} / {rule.get('target_linetype') or '未配置线型'} / 比例 {rule.get('linetype_scale') or '未配置'}"
            self._color_rule_lookup[label]=source
            labels.append(label)
        if self.color_combo is None:
            return
        try:self.color_combo.configure(values=labels)
        except tk.TclError:return
        if labels:
            if self.color_rule_var.get() not in self._color_rule_lookup:
                self.color_rule_var.set(labels[0])
            self.update_color_rule_detail()
        else:
            self.color_rule_var.set('')
            self.color_rule_detail.set('当前模板没有颜色规则。点击上方“编辑颜色规则”添加。')

    def _selected_color_rule(self):
        source=self._color_rule_lookup.get(self.color_rule_var.get(),'')
        if not source:
            raise workflow_v08.WorkflowError('当前模板没有选中的颜色规则')
        return workflow_v08.validate_color_rule(self.current_profile(),source)

    def update_color_rule_detail(self):
        try:
            r=self._selected_color_rule()
            if self._color_flow_source and self._color_flow_source.casefold()!=r['source_color'].casefold():
                self._color_flow_signature=''
                self._color_flow_source=''
            self.color_rule_detail.set(f"目标：{r['target_layer']}｜{r['target_linetype']}｜比例 {r['linetype_scale']}｜颜色 {r.get('target_color') or '保持原色'}")
        except Exception as e:
            self.color_rule_detail.set(str(e))

    def _cad_color_rule(self,source_color):
        source=str(source_color or '').strip()
        if not source:
            raise workflow_v08.WorkflowError('请先点击一种颜色。')
        rule=core.get_cad_color_rule(self.app.c,source)
        if not rule:
            raise workflow_v08.WorkflowError(f'Excel 配置中没有“{source}”的颜色规则，请重新导入配置工作簿。')
        return rule

    def open_color_filter(self,source_color):
        if not self.require():return
        try:
            rule=self._cad_color_rule(source_color)
        except Exception as e:
            self.status.set(str(e))
            return
        if self._queue_ahk_action('set_pick_filter',source_color=rule['source_color']):
            try:
                self._color_flow_signature=bridge.read_active_job(
                    core.storage_dir()/'active_job.ini').get('job_signature','')
            except Exception:
                self._color_flow_signature=''
            self._color_flow_source=rule['source_color']
            self.status.set(f"已发送{rule['source_color']}筛选请求；等待 CAXA 自动设置勾选状态，再点击“确定”并框选对象。")

    def open_color_properties(self):
        if not self.require():return
        try:
            current_job=self._published_job()
            if not current_job:return
            if not self._color_flow_signature or current_job.get('job_signature')!=self._color_flow_signature:
                raise workflow_v08.WorkflowError('请先点击一种颜色，确认过滤条件后，在 CAXA 中框选需要归层的对象。')
            rule=self._cad_color_rule(self._color_flow_source)
            target_layer=str(rule.get('target_layer') or '').strip()
            if not target_layer:
                raise workflow_v08.WorkflowError(f'Excel 中“{rule["source_color"]}”没有配置目标图层。')
            if self._queue_ahk_action('apply_color_layer',source_color=rule['source_color'],
                    target_layer=target_layer,target_color=rule['target_color'],
                    target_linetype=rule['target_linetype'],linetype_scale=rule['linetype_scale'],
                    target_lineweight=rule['target_lineweight']):
                self.status.set(f"已发送特性设置请求：{rule['source_color']} → {target_layer}；请查看左侧特性栏核对执行结果，助手不会自动保存。")
        except Exception as e:
            self.status.set(str(e))

    def restore_color_filter(self):
        if not self.require():return
        if self._queue_ahk_action('restore_pick_filter'):
            self.status.set('已发送恢复全选请求；请确认 CAXA 颜色列表恢复全选后点击“确定”。')
            self._color_flow_signature=''
            self._color_flow_source=''

    def show_colors(self):
        try:
            rules=core.get_cad_color_rules(self.app.c)
            lines=['【当前 Excel 颜色映射】','以下规则保存在本机数据库；重新导入配置 Excel 时整体更新。','']
            for rule in rules:
                lines.append(
                    f"{rule['source_color']} → {rule['target_layer']}；"
                    f"颜色 {rule['target_color']}；线型 {rule['target_linetype']}；"
                    f"比例 {rule['linetype_scale']:g}；线宽 {rule['target_lineweight']}"
                )
            lines += [
                '',
                '【执行说明】',
                '颜色按钮会自动设置 CAXA 拾取过滤对话框的颜色勾选状态；仍需在 CAXA 中点击确定。',
                '一键设置特性直接读取 Excel 目标图层，并修改当前选集；首次使用需校准一次 CAXA 属性工具栏。',
                '修改后检查左侧特性栏；助手不会自动保存 EXB。',
            ]
            self._text_window('颜色规则检查','\n'.join(lines))
        except Exception as e:
            messagebox.showwarning('颜色规则检查失败',str(e),parent=self.win)

    def open_data_folder(self):
        try:
            folder=core.storage_dir()
            folder.mkdir(parents=True,exist_ok=True)
            if sys.platform=='win32':
                os.startfile(str(folder))
            else:
                messagebox.showinfo('助手数据目录',str(folder),parent=self.win)
        except Exception as e:
            messagebox.showerror('无法打开数据目录',str(e),parent=self.win)


    def _save_profiles(self):
        for p in self.profiles: profiles.validate(p)
        self.profile_path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.profiles_',suffix='.tmp',dir=self.profile_path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(self.profiles,f,ensure_ascii=False,indent=2)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.profile_path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def edit_colors(self):
        # Edit a private copy: closing the dialog without Save must not change
        # the active profile or future automated actions.
        p=copy.deepcopy(self.current_profile())
        w=tk.Toplevel(self.win);w.title('编辑颜色与线条特性预设｜'+p['label'])
        w.geometry('700x420')
        cols=('src','layer','type','ratio','dest')
        tree=ttk.Treeview(w,columns=cols,show='headings',height=9)
        for col,text,width in [('src','原颜色',110),('layer','目标图层',160),('type','线型',130),('ratio','比例',90),('dest','目标颜色（可不改）',140)]:
            tree.heading(col,text=text);tree.column(col,width=width,stretch=True)
        tree.pack(fill='both',expand=True,padx=9,pady=7)
        def refill():
            for i in tree.get_children():tree.delete(i)
            for idx,r in enumerate(p.get('color_rules',[])):
                tree.insert('','end',iid=str(idx),values=(r['source_color'],r.get('target_layer') or '',r.get('target_linetype') or '',r.get('linetype_scale') or '',r.get('target_color') or ''))
        refill()
        def edit():
            ix=tree.selection()
            if not ix:return
            idx=int(ix[0]);r=p['color_rules'][idx]
            fields=[('原颜色','source_color'),('目标图层','target_layer'),('目标线型','target_linetype'),('线型比例','linetype_scale'),('目标颜色（可留空）','target_color')]
            new=dict(r)
            for title,key in fields:
                old=new.get(key)
                val=simpledialog.askstring('修改颜色预设',title+'：',initialvalue='' if old is None else str(old),parent=w)
                if val is None:return
                if key=='linetype_scale':
                    try: new[key]=float(val) if val.strip() else None
                    except ValueError:
                        messagebox.showerror('无效','线型比例必须为正数字',parent=w);return
                else:new[key]=val.strip() or None
            test=dict(p); test['color_rules']=list(p['color_rules']);test['color_rules'][idx]=new
            try:profiles.validate(test)
            except Exception as e:
                messagebox.showerror('规则不合法',str(e),parent=w);return
            p['color_rules'][idx]=new;refill()
        def add():
            val=simpledialog.askstring('新增颜色','原颜色名称（如 黄色）：',parent=w)
            if val is None or not val.strip():return
            p.setdefault('color_rules',[]).append({'source_color':val.strip(),'target_layer':None,'target_linetype':None,'linetype_scale':None})
            try:profiles.validate(p)
            except Exception as e:
                p['color_rules'].pop();messagebox.showerror('不能新增',str(e),parent=w)
            refill()
        def remove():
            ix=tree.selection()
            if ix and messagebox.askyesno('删除规则','确认删除该颜色规则？',parent=w):
                p['color_rules'].pop(int(ix[0]));refill()
        def save():
            prior=self.profiles
            try:
                profiles.validate(p)
                self.profiles=[p if x['id']==p['id'] else x for x in prior]
                self._save_profiles()
            except Exception as e:
                self.profiles=prior
                messagebox.showerror('保存失败',str(e),parent=w);return
            self._color_flow_signature='';self._color_flow_source='';self._color_flow_profile_hash=''
            self.update_color_rule_choices()
            messagebox.showinfo('已保存','规则仅保存在本机，未修改CAD图纸。',parent=w);w.destroy()
        bar=ttk.Frame(w);bar.pack(pady=(0,10))
        for title,cmd in [('编辑选中项',edit),('新增颜色',add),('删除选中项',remove),('保存规则',save)]:
            ttk.Button(bar,text=title,command=cmd).pack(side='left',padx=5)

    def parse_name(self):
        if not self.require():return
        p=self.current_profile();d=core.get_drawing(self.app.c,self.app.path)
        params={}
        if p.get('required_params'):
            try:
                cached=autoread.cached(self.app.c,self.app.path)
                if cached and all(cached.get(k) for k in p['required_params']):
                    params={k:cached[k] for k in p['required_params']}
                else:
                    raw=clipboard_utils.read_clipboard_text(self.win)
                    params=profiles.parse_property_grid(raw,p)
            except Exception as e:
                messagebox.showwarning('读取失败','本图没有可用缓存，请先复制参数栏的多行文字。\n'+str(e),parent=self.win);return
        try: name=profiles.build_name(d['path'],p,params)
        except Exception as e:
            messagebox.showwarning('无法自动命名',str(e),parent=self.win);return
        summary='\n'.join(f'{k}: {v}' for k,v in params.items())
        if not messagebox.askyesno('确认当前图纸的建议名称',
                 '当前图号：'+d['code']+'\n模板：'+p['label']+'\n'+summary+'\n建议名称：'+name+'\n\n确认属于当前图纸？',parent=self.win,default='no'):
            return
        try:
            core.save_custom_name(self.app.c,self.app.path,name)
            self.app.load_detail(self.app.path);self.app.refresh();self.app.sync_job()
            self.status.set('已将名称保存到本地进度；CAD属性仍需按规定原生填入。')
        except Exception as e:messagebox.showerror('保存失败',str(e),parent=self.win)


    def prepare_views(self):
        if not self.require():return
        try:
            selected=core.validate_view_template(self.app.last_view_template)
            existing=list(core.slots_for(self.app.c,self.app.path))
            if existing:
                existing_views={row['view_type'] for row in existing}
                if existing_views==set(selected) and len(existing)==2*len(selected):
                    self.status.set('本张图纸已按当前视图模板建立任务，无需重复设置。')
                else:
                    messagebox.showwarning('本张已有视图计划',
                        '当前图纸已经存在视图任务。为避免覆盖已做的进度，本次不会自动替换。\n'
                        '如确需更换，请先在图纸管理中核对并处理旧计划。',
                        parent=self.win)
                self._show_home_page()
                return
            if not self.app.update_plan():
                return
            self.status.set('已建立本张视图任务，正在直接启动 CAXA 图符定义。')
            self._show_home_page()
            self.define_symbol()
        except Exception as e:
            messagebox.showerror('视图计划建立失败',str(e),parent=self.win)
    def complete_next(self):
        if not self.require():return
        d=core.get_drawing(self.app.c,self.app.path)
        if d['status']!='已人工复核':
            self.app.finish()
        d=core.get_drawing(self.app.c,self.app.path)
        if d['status']=='已人工复核':self.app.next_pending()
        else:self.status.set('本张尚未通过复核，不允许跳至下一张作为已完成项。')
