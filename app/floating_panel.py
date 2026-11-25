"""Tkinter control surface for the CAXA gallery workbench.

The panel routes allow-listed, task-signed operations to AHK. Geometry selection,
base points, property review and final insertion remain operator-controlled.
"""
from __future__ import annotations
import copy, json, os, tempfile, sys, ctypes, configparser, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import core, profiles, workflow_v08, router_v11, autoread, bridge

class Panel:
    def __init__(self, app):
        self.app=app
        self.win=tk.Toplevel(app.root)
        self.win.title('CAXA 制作控制台')
        sw=max(1024,self.win.winfo_screenwidth())
        sh=max(720,self.win.winfo_screenheight())
        self._expanded_geometry=f'340x420+{max(10,sw-360)}+{max(35,min(90,sh-470))}'
        self._collapsed_geometry=f'300x70+{max(10,sw-320)}+{max(35,min(90,sh-120))}'
        self.win.geometry(self._expanded_geometry)
        self.win.minsize(320,390)
        self.win.maxsize(370,500)
        self.win.resizable(False,False)
        self.win.attributes('-topmost',True)
        self.win.protocol('WM_DELETE_WINDOW',self.hide_panel)
        self.profile_path=core.storage_dir()/'my_gallery_profiles.json'
        self.profile_pref_path=core.storage_dir()/'active_profile.json'
        self.profiles=self._load_profiles()
        self.profile_choice=tk.StringVar(value=self._load_profile_preference())
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
        self.block_name_status=tk.StringVar(value='正式块名称：尚未匹配')
        self.status=tk.StringVar(value='正在检查 CAD 控制器…')
        self.recommended=tk.StringVar(value='先选择图纸')
        self.action_reason=tk.StringVar(value='首次使用请打开图纸管理，选择目录并导入块名称清单。')
        self.guide_status=tk.StringVar(value='视图引导尚未启动')
        self._closed=False
        self._after_ids=set()
        self._dialogs={}
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
        self.normal_frame=ttk.Frame(self.win,padding=9)
        self.normal_frame.pack(fill='both',expand=True)
        header=ttk.Frame(self.normal_frame);header.pack(fill='x')
        ttk.Label(header,text='CAXA 制作控制台',font=('Microsoft YaHei UI',11,'bold')).pack(side='left')
        ttk.Label(header,text='● 置顶',foreground='#16834a').pack(side='left',padx=8)
        ttk.Button(header,text='—',width=3,command=self.collapse_panel).pack(side='right')

        ttk.Label(self.normal_frame,textvariable=self.context,wraplength=320,
                  font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w',pady=(9,2))
        ttk.Label(self.normal_frame,textvariable=self.block_name_status,wraplength=320,
                  foreground='#24527a').pack(anchor='w',pady=(0,6))

        self.main_button=ttk.Button(self.normal_frame,textvariable=self.recommended,
                                    command=self.do_recommended)
        self.main_button.pack(fill='x',pady=(2,3),ipady=7)
        ttk.Label(self.normal_frame,textvariable=self.action_reason,wraplength=320,
                  foreground='#666').pack(anchor='w',pady=(0,8))

        grid=ttk.Frame(self.normal_frame);grid.pack(fill='x',pady=2)
        for col in range(2):grid.columnconfigure(col,weight=1)
        ttk.Button(grid,text='清理图纸',command=self.open_cleanup_window).grid(row=0,column=0,sticky='ew',padx=(0,4),pady=3,ipady=5)
        ttk.Button(grid,text='六视图定义',command=self.open_views_window).grid(row=0,column=1,sticky='ew',padx=(4,0),pady=3,ipady=5)
        ttk.Button(grid,text='属性与入库',command=self.open_insert_window).grid(row=1,column=0,sticky='ew',padx=(0,4),pady=3,ipady=5)
        ttk.Button(grid,text='图纸管理',command=self.open_workbench).grid(row=1,column=1,sticky='ew',padx=(4,0),pady=3,ipady=5)

        bottom=ttk.Frame(self.normal_frame);bottom.pack(fill='x',pady=(7,2))
        ttk.Button(bottom,text='连接当前 CAXA',command=self.connect_cad).pack(side='left',fill='x',expand=True,padx=(0,3))
        ttk.Button(bottom,text='设置',command=self.open_settings_window).pack(side='left',fill='x',expand=True,padx=(3,0))
        ttk.Separator(self.normal_frame).pack(fill='x',pady=6)
        ttk.Label(self.normal_frame,textvariable=self.status,wraplength=320,
                  foreground='#555').pack(anchor='w')

        self.collapsed_frame=ttk.Frame(self.win,padding=6)
        collapsed_row=ttk.Frame(self.collapsed_frame);collapsed_row.pack(fill='x')
        ttk.Label(collapsed_row,text='CAXA',font=('Microsoft YaHei UI',9,'bold')).pack(side='left')
        ttk.Label(collapsed_row,textvariable=self.context,wraplength=190).pack(side='left',fill='x',expand=True,padx=5)
        ttk.Button(collapsed_row,text='展开',command=self.expand_panel).pack(side='right')

    def collapse_panel(self):
        if self._collapsed:return
        self._collapsed=True
        self.normal_frame.pack_forget()
        self.collapsed_frame.pack(fill='both',expand=True)
        self.win.geometry(self._collapsed_geometry)
        self.win.minsize(290,65);self.win.maxsize(360,90)

    def expand_panel(self):
        if not self._collapsed:return
        self._collapsed=False
        self.collapsed_frame.pack_forget()
        self.normal_frame.pack(fill='both',expand=True)
        self.win.minsize(320,390);self.win.maxsize(370,500)
        self.win.geometry(self._expanded_geometry)
        self.win.attributes('-topmost',True)

    def hide_panel(self):
        try:self.win.withdraw()
        except tk.TclError:pass

    def open_workbench(self):
        try:
            self.app.root.deiconify()
            self.app.root.state('normal')
            self.app.root.lift()
            self.app.root.focus_force()
            self.status.set('图纸管理已打开。选择图纸后，回到本面板继续 CAD 操作。')
        except tk.TclError:
            self.status.set('无法打开图纸管理窗口，请从任务栏切换到主工作台。')

    def _dialog(self,key,title,geometry):
        old=self._dialogs.get(key)
        if old is not None:
            try:
                if old.winfo_exists():old.deiconify();old.lift();return old
            except tk.TclError:pass
        w=tk.Toplevel(self.win);w.title(title);w.geometry(geometry);w.resizable(False,False)
        w.transient(self.win)
        self._dialogs[key]=w
        def clear(event):
            if event.widget is w:
                self._dialogs.pop(key,None)
                if key=='cleanup':self.color_combo=None
                if key=='views':self.view_tree=None
        w.bind('<Destroy>',clear,add='+')
        return w

    def open_cleanup_window(self):
        w=self._dialog('cleanup','清理图纸｜颜色归层与删除重复线','360x360')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        body=ttk.Frame(w,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,text='先完成颜色归层，再删除重复线。',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,7))
        ttk.Label(body,text='颜色规则（按公司标准预先配置一次）：').pack(anchor='w')
        self.color_combo=ttk.Combobox(body,state='readonly',textvariable=self.color_rule_var,width=42)
        self.color_combo.pack(fill='x',pady=3)
        self.color_combo.bind('<<ComboboxSelected>>',lambda _e:self.update_color_rule_detail())
        ttk.Label(body,textvariable=self.color_rule_detail,wraplength=330,foreground='#555').pack(anchor='w',pady=4)
        ttk.Button(body,text='1. 打开颜色过滤',command=self.open_color_filter).pack(fill='x',pady=3)
        ttk.Button(body,text='2. 修改选中对象属性',command=self.open_color_properties).pack(fill='x',pady=3)
        ttk.Button(body,text='3. 恢复过滤',command=self.restore_color_filter).pack(fill='x',pady=3)
        ttk.Separator(body).pack(fill='x',pady=7)
        ttk.Button(body,text='4. 删除重复线',command=self.delete_duplicate_lines).pack(fill='x',pady=3,ipady=4)
        ttk.Label(body,text='首次仅处理完全重合对象。只选择机械视图范围；避开图框、标题栏，不要包含尺寸或其他颜色组。',wraplength=330,foreground='#777').pack(anchor='w',pady=4)
        self.update_color_rule_choices()

    def open_views_window(self):
        w=self._dialog('views','六视图定义与视图复核','390x590')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        body=ttk.Frame(w,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,text='当前图纸的视图计划',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,3))
        ttk.Label(body,text='顺序：全部带尺寸视图 → 关闭尺寸线层 → 全部无尺寸视图。',wraplength=360,foreground='#555').pack(anchor='w',pady=2)
        choices=ttk.LabelFrame(body,text='需要制作的视图类型',padding=6);choices.pack(fill='x',pady=4)
        for i,v in enumerate(core.VIEW_TYPES):
            ttk.Checkbutton(choices,text=v,variable=self.app.view_var[v]).grid(row=i//3,column=i%3,sticky='w',padx=4,pady=2)
        rowp=ttk.Frame(body);rowp.pack(fill='x',pady=2)
        ttk.Button(rowp,text='载入模板视图',command=self.prepare_views).pack(side='left',fill='x',expand=True,padx=(0,3))
        ttk.Button(rowp,text='更新当前视图计划',command=self._update_view_plan_from_panel).pack(side='left',fill='x',expand=True,padx=(3,0))
        ttk.Label(body,textvariable=self.guide_status,wraplength=360,foreground='#24527a').pack(anchor='w',pady=4)
        ttk.Button(body,text='开始视图引导',command=self.start_view_guide).pack(fill='x',pady=2)
        ttk.Button(body,text='启动定义图符',command=self.define_symbol).pack(fill='x',pady=2)
        row=ttk.Frame(body);row.pack(fill='x',pady=2)
        ttk.Button(row,text='上一视图',command=self.previous_view).pack(side='left',fill='x',expand=True,padx=(0,3))
        ttk.Button(row,text='下一视图',command=self.next_view).pack(side='left',fill='x',expand=True,padx=3)
        ttk.Button(row,text='查看当前项',command=self.show_view_guide).pack(side='left',fill='x',expand=True,padx=(3,0))
        ttk.Button(body,text='结束引导',command=self.end_view_guide).pack(fill='x',pady=2)
        ttk.Button(body,text='尺寸层操作说明',command=self.show_dimension_steps).pack(fill='x',pady=2)
        ttk.Separator(body).pack(fill='x',pady=5)
        ttk.Label(body,text='视图版本人工复核',font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w')
        self.view_tree=ttk.Treeview(body,columns=('view','kind','state'),show='headings',height=5,selectmode='browse')
        for col,title,width in [('view','视图',100),('kind','版本',90),('state','状态',90)]:
            self.view_tree.heading(col,text=title);self.view_tree.column(col,width=width,stretch=True)
        self.view_tree.pack(fill='both',expand=True,pady=3)
        rowv=ttk.Frame(body);rowv.pack(fill='x',pady=2)
        ttk.Button(rowv,text='已复核',command=lambda:self._set_view_status_from_panel('已复核')).pack(side='left',fill='x',expand=True,padx=(0,2))
        ttk.Button(rowv,text='待处理',command=lambda:self._set_view_status_from_panel('待处理')).pack(side='left',fill='x',expand=True,padx=2)
        ttk.Button(rowv,text='不需要',command=lambda:self._set_view_status_from_panel('不需要')).pack(side='left',fill='x',expand=True,padx=(2,0))
        ttk.Button(body,text='所有计划视图已逐项复核',command=self._review_all_views_from_panel).pack(fill='x',pady=3)
        ttk.Label(body,text='框选、基点和尺寸层切换仍在 CAXA 中完成；状态只记录人工确认。',wraplength=360,foreground='#777').pack(anchor='w',pady=3)
        self._refresh_view_table()

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
        w=self._dialog('insert','属性、入库与人工验收','390x590')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        body=ttk.Frame(w,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,textvariable=self.block_name_status,wraplength=360,foreground='#24527a').pack(anchor='w',pady=(0,6))
        ttk.Button(body,text='填写正式块名称',command=self.fill_symbol_name).pack(fill='x',pady=2)
        ttk.Button(body,text='复制正式块名称',command=self.copy_block_name).pack(fill='x',pady=2)
        ttk.Separator(body).pack(fill='x',pady=5)
        ttk.Button(body,text='属性编辑',command=self.edit_symbol_attributes).pack(fill='x',pady=2)
        ttk.Button(body,text='填入标题栏属性',command=self.fill_titleblock_attributes).pack(fill='x',pady=2)
        ttk.Button(body,text='确认并完成入库',command=self.finish_gallery_insert).pack(fill='x',pady=4,ipady=3)
        ttk.Label(body,text='完成后还要重新插入图符，检查视图、基点和属性。',wraplength=360,foreground='#777').pack(anchor='w',pady=3)
        qc=ttk.LabelFrame(body,text='本张图人工验收清单',padding=6);qc.pack(fill='both',expand=True,pady=5)
        for key,label in core.QC_ITEMS:
            tk.Checkbutton(qc,text=label,variable=self.app.qc_vars[key],
                command=lambda k=key:self.app.on_qc_change(k),wraplength=345,justify='left',anchor='w').pack(fill='x',anchor='w',pady=1)
        ttk.Label(qc,text='只有实际完成检查后才勾选；源图变化会使确认失效。',wraplength=345,foreground='#777').pack(anchor='w',pady=3)
        ttk.Button(body,text='记录本张人工复核完成',command=self.signoff_current_drawing).pack(fill='x',pady=4)

    def signoff_current_drawing(self):
        if not self.require():return
        if not messagebox.askyesno('最终人工复核',
            '确认本张所有计划视图、正式名称、基点、属性、图库插入及重新插入结果均已检查并保存？',
            parent=self._dialogs.get('insert',self.win),default='no'):return
        try:
            core.finish_drawing(self.app.c,self.app.path)
            self.app.refresh();self.app.sync_job();self.update_recommendation()
            self.status.set('本张已记录为人工复核完成；可以进入下一张。')
        except Exception as e:
            messagebox.showwarning('尚不能标记完成',str(e),parent=self._dialogs.get('insert',self.win))

    def open_settings_window(self):
        w=self._dialog('settings','低频设置｜首次配置后无需每张重复操作','390x430')
        if getattr(w,'_caxa_built',False):return
        w._caxa_built=True
        body=ttk.Frame(w,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,text='制作模板（同类图纸可连续沿用）：').pack(anchor='w')
        self.combo=ttk.Combobox(body,state='readonly',textvariable=self.profile_choice,
                                values=[x['id'] for x in self.profiles],width=35)
        self.combo.pack(fill='x',pady=3)
        self.combo.bind('<<ComboboxSelected>>',lambda _e:self._on_profile_change())
        ttk.Checkbutton(body,text='切换图纸时保留当前模板（默认）',variable=self.lock_profile,command=self._save_profile_preference).pack(anchor='w',pady=3)
        ttk.Button(body,text='编辑颜色与线型规则（通常只需配置一次）',command=self.edit_colors).pack(fill='x',pady=4)
        ttk.Button(body,text='首次校准',command=self.open_calibration_window).pack(fill='x',pady=4)
        ttk.Separator(body).pack(fill='x',pady=7)
        ttk.Label(body,text='其他管理操作').pack(anchor='w')
        for caption,method in (
          ('打开完整图纸管理',self.open_workbench),('检查颜色规则（只读）',self.show_colors),
          ('读取参数并生成名称',self.parse_name),('建立/更新视图任务',self.prepare_views),
          ('人工复核后进入下一张',self.complete_next),('查看本类制作计划',self.show_plan)):
            ttk.Button(body,text=caption,command=method).pack(fill='x',pady=2)

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

    def _load_profile_preference(self):
        ids={x['id'] for x in self.profiles}
        try:
            data=json.loads(self.profile_pref_path.read_text(encoding='utf-8'))
            preferred=data.get('profile_id','')
            if preferred in ids:return preferred
        except (OSError,ValueError,TypeError):pass
        # The current project is mainly vertical take-up equipment; use its
        # template as the first-run default when available, but never force it.
        if 'generic_gallery' in ids:return 'generic_gallery'
        if 'vertical_weight_takeup' in ids:return 'vertical_weight_takeup'
        return self.profiles[0]['id']

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

    def current_profile(self):
        return next(p for p in self.profiles if p['id']==self.profile_choice.get())

    def _poll(self):
        try:
            row=core.get_drawing(self.app.c,self.app.path) if self.app.path else None
            if self.app.path!=self.last_path:
                self.last_path=self.app.path
                self._color_flow_signature='';self._color_flow_source='';self._color_flow_profile_hash=''
                if not self.lock_profile.get():
                    self.profile_choice.set('generic_gallery' if any(p['id']=='generic_gallery' for p in self.profiles) else self.profiles[0]['id'])
                    self.update_color_rule_choices();self._save_profile_preference()
                    self.status.set('已切换图纸，模板恢复通用默认。请核实设备类别。')
            if row:
                self.context.set('当前：'+row['code']+'｜'+row['name']+'\n状态：'+row['status'])
                try:
                    info=core.block_name_for_path(self.app.c,self.app.path)
                    if info.get('status')=='已匹配':
                        self.block_name_status.set('正式块名称：已匹配｜'+info.get('block_name',''))
                    else:
                        self.block_name_status.set('正式块名称：'+info.get('status','待匹配'))
                except Exception:
                    self.block_name_status.set('正式块名称：暂不可读取')
            else:
                self.context.set('尚未选择图纸')
                self.block_name_status.set('正式块名称：请先在图纸管理中导入清单并选择图纸')
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

    def _queue_ahk_action(self,action,confirm_text=None):
        job=self._published_job()
        if not job:return False
        if confirm_text and not messagebox.askyesno('确认 CAXA 操作',confirm_text.format(
                code=job.get('code',''),work=job.get('working_file','')),parent=self.win,default='no'):
            return False
        try:
            bridge.request_panel_action(core.storage_dir(),action,job['job_signature'])
            self.status.set('操作请求已发送；正在等待 CAXA 控制器核验当前图纸。')
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
        marker=core.storage_dir()/'ahk_controller.pid'
        try:
            pid=int(marker.read_text(encoding='ascii').strip()) if marker.is_file() else 0
        except (OSError,ValueError):pid=0
        if self._pid_alive(pid):
            self.status.set('CAXA 控制器已运行；可直接使用上方按钮。')
            return
        try:
            self.status.set('正在准备 AutoHotkey v2.0.32（首次运行会自动下载并校验，约3.2 MB）…')
            self.app.launch_hotkeys(on_complete=self._ahk_launch_complete)
        except Exception as e:
            self.status.set('控制器未启动：' + str(e))

    def _ahk_launch_complete(self, ok, message):
        if self._closed:
            return
        if ok:
            self.status.set('AutoHotkey 运行时已就绪，正在检查控制器…')
            self._schedule(1200,self.check_ahk_controller_start)
        else:
            self.status.set('控制器启动失败；请查看启动错误信息。')

    def check_ahk_controller_start(self):
        marker=core.storage_dir()/'ahk_controller.pid'
        try:pid=int(marker.read_text(encoding='ascii').strip()) if marker.is_file() else 0
        except (OSError,ValueError):pid=0
        if self._pid_alive(pid):
            self.status.set('CAXA 控制器已运行；可直接点击操作按钮。')
        else:
            self.status.set('未检测到 AutoHotkey v2 控制器。请检查运行时下载或 Windows 安全软件拦截记录。')

    def connect_cad(self):
        self._queue_ahk_action('bind_cad',
            '将尝试定位当前任务的工作副本窗口：\n图号：{code}\n工作副本：{work}\n\n找到唯一匹配窗口后会显示进程信息，请确认绑定。')

    def delete_duplicate_lines(self):
        # The button itself is the operator's explicit command. No extra Python
        # confirmation dialog: CAXA still requires manual selection/confirmation.
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
        if not self._guide_checkpoint_complete(job):
            messagebox.showwarning('视图尚未逐项确认','必须先完成当前任务的全部视图引导，再执行最终入库。此记录只是人工确认，不代表 CAD 自动验证。',parent=self.win);return
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
        w=tk.Toplevel(self.win);w.title('首次校准 CAXA 控件');w.geometry('430x300');w.transient(self.win)
        ttk.Label(w,text='先打开对应的 CAXA 窗口，再点击校准。面板会暂时隐藏约7秒；把鼠标移到指定按钮/输入框上，不要点击。',wraplength=395).pack(anchor='w',padx=12,pady=10)
        for label,action in (
            ('校准“定义图符”按钮','calibrate_define'),
            ('校准“属性编辑”按钮（先打开对应弹窗）','calibrate_attr_edit'),
            ('校准“填入当前标题栏属性值”按钮（先打开对应弹窗）','calibrate_attr_fill'),
            ('校准“图符名称”输入框（先打开图符入库窗口）','calibrate_symbol_name'),
            ('校准图符入库“完成”按钮（先打开图符入库窗口）','calibrate_gallery_finish')):
            ttk.Button(w,text=label,command=lambda a=action:self._begin_calibration(a,w)).pack(fill='x',padx=12,pady=4)
        ttk.Button(w,text='关闭',command=w.destroy).pack(pady=8)

    def _begin_calibration(self,action,dialog):
        if self._queue_ahk_action(action):
            try:dialog.destroy()
            except tk.TclError:pass
            self.win.withdraw()
            self._schedule(7200,self._restore_after_calibration)

    def _restore_after_calibration(self):
        try:
            if self.win.winfo_exists():
                self.win.deiconify();self._topmost_suspended_until=0;self.win.attributes('-topmost',True)
                self.status.set('首次校准流程结束；请检查状态提示并继续。')
        except tk.TclError:pass

    def copy_block_name(self):
        if not self.require():return
        info=core.block_name_for_path(self.app.c,self.app.path)
        if info.get('status')!='已匹配' or not info.get('block_name'):
            messagebox.showwarning('正式块名称未匹配',
                '当前图纸没有按完整图号唯一匹配到正式块名称，不能复制候选名称。',parent=self.win)
            return
        try:
            self.win.clipboard_clear();self.win.clipboard_append(info['block_name']);self.win.update()
            self.status.set('正式块名称已复制：'+info['block_name'])
        except Exception as e:messagebox.showerror('复制失败',str(e),parent=self.win)

    def toggle_advanced(self):
        old=self._dialogs.get('settings')
        try:
            if old is not None and old.winfo_exists():
                old.destroy();self.advanced_open=False;return
        except tk.TclError:pass
        self.open_settings_window();self.advanced_open=True

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
            slots=rows,configured_views=bool(self.current_profile().get('view_plan')),
            changed=changed,has_exact_block_name=has_exact_block_name)

    def do_recommended(self):
        action=self.suggested_action(verify_content=True).key
        if action=='open_copy':self.open_copy()
        elif action=='parse_name':self.parse_name()
        elif action=='prepare_views':self.prepare_views()
        elif action=='next':self.app.next_pending()
        elif action=='review':self.open_insert_window()
        elif action=='cad_guide':self.show_plan()
        elif action=='configure_views':
            self.open_views_window()
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

    def open_color_filter(self):
        if not self.require():return
        try:
            rule=self._selected_color_rule()
        except Exception as e:
            messagebox.showwarning('颜色规则未配置',str(e),parent=self.win);return
        if self._queue_ahk_action('open_pick_filter'):
            try:
                self._color_flow_signature=bridge.read_active_job(core.storage_dir()/'active_job.ini').get('job_signature','')
            except Exception:
                self._color_flow_signature=''
            self._color_flow_source=rule['source_color']
            self._color_flow_profile_hash=workflow_v08.profile_fingerprint(self.current_profile())
            self.status.set(f"已发送拾取过滤请求：源颜色【{rule['source_color']}】。在 CAXA 对话框中选择颜色条件后，仅框选机械视图区域。")

    def open_color_properties(self):
        if not self.require():return
        try:
            rule=self._selected_color_rule()
            current_job=self._published_job()
            if not current_job:return
            if not self._color_flow_signature or current_job.get('job_signature')!=self._color_flow_signature:
                raise workflow_v08.WorkflowError('当前任务尚未在本面板启动颜色过滤，或图纸/名称/视图计划已变化。请先重新点击“打开颜色过滤”。')
            if self._color_flow_source.casefold()!=rule['source_color'].casefold():
                raise workflow_v08.WorkflowError('当前选择的源颜色与已启动的过滤规则不同，请重新打开过滤设置。')
            if workflow_v08.profile_fingerprint(self.current_profile())!=self._color_flow_profile_hash:
                raise workflow_v08.WorkflowError('颜色模板在过滤后发生变化，请重新打开过滤设置。')
        except Exception as e:
            messagebox.showwarning('颜色处理状态不一致',str(e),parent=self.win);return
        if not messagebox.askyesno('核对当前选集',
            f"当前规则：{rule['source_color']} → {rule['target_layer']} / {rule['target_linetype']} / 比例 {rule['linetype_scale']}\n\n"
            '你是否已经在 CAXA 中设置该源颜色过滤，并且只选中了当前工作副本中的机械视图对象？\n'
            '不要包含图框、标题栏、尺寸或其他颜色组。',parent=self.win,default='no'):
            return
        if self._queue_ahk_action('open_properties'):
            self.status.set('已发送属性面板请求。请在 CAXA 属性面板中手动设置并复核目标图层、线型和比例。')

    def restore_color_filter(self):
        if not self.require():return
        if self._queue_ahk_action('restore_pick_filter'):
            self.status.set('已发送拾取过滤设置请求；请在 CAXA 中恢复默认/全选过滤条件后确认。')
            self._color_flow_signature=''
            self._color_flow_source=''
            self._color_flow_profile_hash=''

    def show_colors(self):
        try:
            p=self.current_profile()
            lines=['【颜色规则检查】','逐条检查当前模板；未配置的规则不会开放颜色处理按钮。','']
            if not p.get('color_rules'):
                lines.append('当前模板没有颜色规则。')
            for rule in p.get('color_rules',[]):
                try:
                    ready=workflow_v08.validate_color_rule(p,rule['source_color'])
                    lines.append(f"✓ {ready['source_color']} → {ready['target_layer']}；{ready['target_linetype']}；比例 {ready['linetype_scale']}；颜色 {ready.get('target_color') or '保持原色'}")
                except Exception as e:
                    lines.append(f"! {rule['source_color']}：未就绪（{e}）")
            lines += ['','【操作方式】','面板使用 CAXA 原生命令 objectset 打开拾取过滤设置，再用 properties 打开选中对象属性面板。对象选择及目标属性修改由你在 CAXA 中完成。','', '【过滤与颜色风险】']
            lines += ['• '+x for x in workflow_v08.color_filter_execution_cautions(p)]
            lines += ['','该检查不意味着已经修改过 CAXA 图元。']
            self._text_window('颜色规则预检','\n'.join(lines))
            self.status.set('颜色规则已逐条检查；可执行的规则可从面板启动原生过滤/属性面板。')
        except Exception as e:
            messagebox.showwarning('颜色规则检查失败',str(e),parent=self.win)

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
                    raw=self.win.clipboard_get()
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
        p=self.current_profile()
        view=p.get('view_plan',[])
        if not view:
            messagebox.showwarning('未设置视图计划','此模板未确认视图顺序，需要先确定公司要求。',parent=self.win);return
        selected={x['view'] for x in view}
        # DB expects paired dimensions. For other structures operator must use main workbench.
        pairs={(x['view'],x['kind']) for x in view}
        if any((v,'带尺寸') not in pairs or (v,'无尺寸') not in pairs for v in selected):
            messagebox.showwarning('视图规则需人工确认','此计划含单一尺寸版本，主工作台默认按成对视图安排，不能自动转换。',parent=self.win);return
        for v in core.VIEW_TYPES:self.app.view_var[v].set(v in selected)
        self.app.update_plan()
        self.status.set('视图计划已写入工作台。仍须按CAXA实际提示逐个选图和指定基点。')
        self._text_window('图符定义顺序（需人工选图）','\n'.join(workflow_v08.view_instruction(p)))

    def complete_next(self):
        if not self.require():return
        d=core.get_drawing(self.app.c,self.app.path)
        if d['status']!='已人工复核':
            self.app.finish()
        d=core.get_drawing(self.app.c,self.app.path)
        if d['status']=='已人工复核':self.app.next_pending()
        else:self.status.set('本张尚未通过复核，不允许跳至下一张作为已完成项。')