"""Compact, task-focused drawing picker for everyday CAXA work.

The full management workspace remains available separately for infrequent
administrative tasks. This window exposes only folder selection, filtering,
drawing selection and the primary "open working copy" action.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import core


class DrawingSelector:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("选择图纸")
        width, height = 680, 460
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = max(10, (sw - width) // 2)
        y = max(10, (sh - height) // 2)
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.minsize(620, 400)
        self.win.resizable(True, True)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.query = tk.StringVar(value="")
        self.count = tk.StringVar(value="0 张图纸")
        self.selected_text = tk.StringVar(
            value="尚未选择图纸。单击列表中的一行，再点击下方按钮。"
        )
        self.path_by_iid: dict[str, str] = {}
        self._closed = False
        self._build()
        self.refresh()
        self.win.after_idle(self.show)

    def _build(self):
        outer = ttk.Frame(self.win, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="选择需要制作的图纸",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 3))
        ttk.Label(
            outer,
            text="选中后点击下方“打开图纸”。系统会自动创建工作副本再打开，原始 EXB 不会被直接修改。",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 10))

        folder = ttk.Frame(outer)
        folder.pack(fill="x", pady=(0, 8))
        ttk.Label(folder, text="图纸目录：").pack(side="left")
        ttk.Entry(
            folder, textvariable=self.app.root_path, state="readonly"
        ).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(folder, text="选择目录", command=self.choose_directory).pack(
            side="left", padx=(2, 0)
        )
        ttk.Button(folder, text="刷新", command=self.refresh_folder).pack(
            side="left", padx=(4, 0)
        )

        search = ttk.Frame(outer)
        search.pack(fill="x", pady=(0, 5))
        ttk.Label(search, text="搜索图号／图名：").pack(side="left")
        entry = ttk.Entry(search, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True, padx=5)
        entry.bind("<KeyRelease>", lambda _event: self.refresh())
        ttk.Label(search, textvariable=self.count, foreground="#666").pack(
            side="right", padx=(6, 0)
        )

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)
        columns = ("code", "name", "status")
        self.tree = ttk.Treeview(
            table, columns=columns, show="headings", selectmode="browse", height=12
        )
        for key, label, width in (
            ("code", "图号", 150),
            ("name", "图纸名称", 330),
            ("status", "状态", 110),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=(key == "name"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        ttk.Label(
            outer,
            textvariable=self.selected_text,
            foreground="#24527a",
            wraplength=640,
        ).pack(anchor="w", pady=(8, 7))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.open_button = ttk.Button(
            actions,
            text="打开图纸",
            command=self.open_selected,
            state="disabled",
        )
        self.open_button.pack(side="left", fill="x", expand=True, ipady=7)
        ttk.Button(actions, text="更多管理", command=self.open_admin).pack(
            side="left", padx=(8, 0), ipady=5
        )
        ttk.Button(actions, text="关闭", command=self.close).pack(
            side="left", padx=(8, 0), ipady=5
        )
        ttk.Button(actions, text="退出助手", command=self.app.close).pack(
            side="left", padx=(8, 0), ipady=5
        )

    def exists(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        if not self.exists():
            return
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    def choose_directory(self):
        self.app.scan(parent=self.win)

    def refresh_folder(self):
        if not self.app.root_path.get().strip():
            self.choose_directory()
            return
        self.app.rescan()

    def refresh(self):
        if self._closed or not self.exists():
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.path_by_iid.clear()

        query = self.query.get().casefold().strip()
        folder = self.app.root_path.get().strip()
        if not folder:
            self.count.set("0 张图纸")
            self.selected_text.set("请先选择图纸目录并扫描。")
            self.open_button.configure(state="disabled")
            return

        rows = core.task_queue(self.app.c)
        visible = [
            row for row in rows
            if not query
            or query in (
                row["code"] + " " + row["name"] + " " + row["path"]
            ).casefold()
        ]
        self.count.set(f"{len(visible)} 张图纸")
        selected_iid = None
        for index, row in enumerate(visible):
            state = row["status"]
            if not row["present"]:
                state = "文件缺失"
            elif core.file_changed(row):
                state = "已变更需复核"
            iid = f"d{index}"
            self.path_by_iid[iid] = row["path"]
            self.tree.insert(
                "", "end", iid=iid,
                values=(row["code"], row["name"], state),
            )
            if row["path"] == self.app.path:
                selected_iid = iid

        if selected_iid:
            self.tree.selection_set(selected_iid)
            self.tree.see(selected_iid)
            row = core.get_drawing(self.app.c, self.app.path)
            if row:
                self.selected_text.set(
                    f"当前选择：{row['code']}｜{row['name']}"
                )
                self.open_button.configure(
                    state="normal" if Path(self.app.path).is_file() else "disabled"
                )
        else:
            self.selected_text.set("尚未选择图纸。单击列表中的一行，再点击下方按钮。")
            self.open_button.configure(state="disabled")

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            self.open_button.configure(state="disabled")
            return
        path = self.path_by_iid.get(selection[0])
        if not path:
            self.open_button.configure(state="disabled")
            return
        try:
            self.app.load_detail(path)
            row = core.get_drawing(self.app.c, path)
            if row:
                self.selected_text.set(
                    f"已选择：{row['code']}｜{row['name']}。下一步：点击下方“打开图纸”。"
                )
            available = Path(path).is_file()
            self.open_button.configure(state="normal" if available else "disabled")
            if not available:
                self.selected_text.set("源文件不存在，无法打开；请刷新目录或检查文件。")
            else:
                self.app.status_var.set("已选择图纸。点击“打开图纸”继续。")
        except Exception as exc:
            self.open_button.configure(state="disabled")
            self.selected_text.set("读取图纸信息失败："+str(exc))

    def open_selected(self):
        if not self.app.path:
            messagebox.showwarning("尚未选择图纸", "请先在列表中选择一张图纸。", parent=self.win)
            return
        if not Path(self.app.path).is_file():
            messagebox.showwarning("源文件不存在", "当前图纸文件已不存在，请刷新目录。", parent=self.win)
            self.refresh()
            return
        if self.app.open_work_copy():
            self.close()

    def open_admin(self):
        self.close(restore_panel=False)
        self.app.open_admin_workbench()

    def close(self, restore_panel=True):
        if self._closed:
            return
        self._closed = True
        try:
            if self.app._selector is self:
                self.app._selector = None
        except Exception:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if restore_panel and self.app._floating is not None:
            try:
                self.app._floating.resume_topmost()
            except Exception:
                pass
