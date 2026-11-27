"""Data exchange with the optional local AutoHotkey macro (not CAD integration)."""
from __future__ import annotations
import configparser
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import sys
import secrets
import re


PANEL_ACTIONS = {
    "bind_cad", "duplicate_line_cleanup", "fill_symbol_name",
    "set_pick_filter", "restore_pick_filter", "apply_color_layer",
    "calibrate_layer_combo", "calibrate_color_combo", "calibrate_linetype_combo", "calibrate_lineweight_combo",
    "start_view_guide", "next_view", "previous_view", "show_view_guide", "end_view_guide",
    "define_symbol", "edit_symbol_attributes", "fill_titleblock_attributes", "finish_gallery_insert",
    "calibrate_define", "calibrate_attr_edit", "calibrate_attr_fill", "calibrate_symbol_name", "calibrate_gallery_finish",
    "probe_cad_controls", "probe_pick_filter_dialog",
}

def request_panel_action(storage: Path, action: str, signature: str, *,
                         source_color: str | None = None,
                         target_layer: str | None = None,
                         target_color: str | None = None,
                         target_linetype: str | None = None,
                         linetype_scale: float | None = None,
                         target_lineweight: str | None = None) -> Path:
    """Queue one allow-listed UI action for the local AHK controller.

    The request is atomically replaced and bound to the exact published job.
    It contains no drawing content and cannot carry arbitrary commands.
    """
    if action not in PANEL_ACTIONS:
        raise ValueError("不允许的面板操作")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise ValueError("当前任务签名无效，不能发送面板操作")
    storage.mkdir(parents=True, exist_ok=True)
    conf = configparser.ConfigParser(interpolation=None)
    conf.optionxform = str
    allowed_colors = {"红色", "绿色", "蓝色", "洋红色", "白色+黑白色"}
    if action in {"set_pick_filter", "apply_color_layer"}:
        if source_color not in allowed_colors:
            raise ValueError("不允许的颜色筛选项")
    elif source_color is not None:
        raise ValueError("当前操作不接受源颜色参数")
    if action == "apply_color_layer":
        if (not isinstance(target_layer, str) or not target_layer.strip()
                or len(target_layer.strip()) > 64
                or any(ord(ch) < 32 or ch in "=;#[]|" for ch in target_layer)):
            raise ValueError("目标图层名称无效，拒绝发送")
        for label, value in (("对象颜色", target_color),
                             ("对象线型", target_linetype),
                             ("对象线宽", target_lineweight)):
            if (not isinstance(value, str) or not value.strip()
                    or len(value.strip()) > 32
                    or any(ord(ch) < 32 or ch in "=;#[]|" for ch in value)):
                raise ValueError(f"{label}配置无效，拒绝发送")
        if (isinstance(linetype_scale, bool)
                or not isinstance(linetype_scale, (int, float))
                or linetype_scale <= 0 or linetype_scale > 1000):
            raise ValueError("线型比例必须是 0 到 1000 之间的正数")
    elif any(value is not None for value in
             (target_layer, target_color, target_linetype, linetype_scale, target_lineweight)):
        raise ValueError("当前操作不接受特性参数")
    conf["request"] = {
        "token": secrets.token_hex(16),
        "action": action,
        "job_signature": signature,
        "created_at": str(time.time()),
    }
    if source_color is not None:
        conf["request"]["source_color"] = source_color
    if target_layer is not None:
        conf["request"]["target_layer"] = target_layer.strip()
    if target_color is not None:
        conf["request"]["target_color"] = target_color.strip()
    if target_linetype is not None:
        conf["request"]["target_linetype"] = target_linetype.strip()
    if linetype_scale is not None:
        conf["request"]["linetype_scale"] = str(float(linetype_scale))
    if target_lineweight is not None:
        conf["request"]["target_lineweight"] = target_lineweight.strip()
    target = storage / "panel_action.ini"
    fd, tmpname = tempfile.mkstemp(prefix=".panel_action_", suffix=".tmp", dir=str(storage))
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            conf.write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpname, target)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)
    return target


def expected_job_signature(drawing, suggested_name: str, slots=(),
                            block_name: str = '', block_name_status: str = '未导入块名称清单') -> str:
    """Bind the job to both generated metadata and the exact imported CAXA block name."""
    plan = tuple(str(x) for x in slots)
    source_digest = str(drawing['sha256'] or '')
    working_path = str(drawing['working_path'] or '')
    signature_payload = json.dumps(
        ['v3', str(drawing['path']), source_digest, working_path,
         suggested_name.strip(), block_name.strip(), block_name_status, list(plan)],
        ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(signature_payload.encode('utf-8')).hexdigest()


def publish_active_job(storage: Path, drawing, suggested_name: str, slots=(),
                       block_name: str = '', block_name_status: str = '未导入块名称清单') -> Path:
    """Atomic UTF-16 INI for AutoHotkey v2 (Windows INI APIs read UTF-16 BOM)."""
    if not drawing or not (suggested_name.strip() or
                           (block_name_status == '已匹配' and block_name.strip())):
        raise ValueError('必须确认建议名称或通过完整图号匹配到正式块名称，才能设置快捷键任务。')
    if block_name_status == '已匹配' and not block_name.strip():
        raise ValueError('块名称状态为已匹配但名称为空，拒绝发布任务。')
    if block_name_status != '已匹配' and block_name.strip():
        raise ValueError('块名称未唯一匹配，不能把候选名称发布给 CAD。')
    if any(c in block_name for c in '\r\n'):
        raise ValueError('块名称不能包含换行。')
    storage.mkdir(parents=True,exist_ok=True)
    p=storage/'active_job.ini'
    code=drawing['code'].strip()
    if not code or not drawing['valid_name']:
        raise ValueError('文件名中的图号或图名无效，请核对。')
    if any(c in suggested_name for c in '\r\n'):
        raise ValueError('图库名称不能包含换行。')
    conf=configparser.ConfigParser(interpolation=None)
    conf.optionxform=str
    # Stable task *identity* across the Python/AHK boundary: a previously
    # started AHK guide must reject a newly published source revision or a
    # different registered working copy, even when name/plan stay unchanged.
    # Do not hash the mutable copy's current bytes: users legitimately edit it
    # while following the view guide. preflight validates source/copy safety.
    plan = tuple(str(x) for x in slots)
    source_digest = str(drawing['sha256'] or '')
    working_path = str(drawing['working_path'] or '')
    job_signature = expected_job_signature(drawing, suggested_name, plan, block_name, block_name_status)
    conf['active']={
        'code':code,
        'filename':Path(drawing['path']).name,
        # The guard uses the exact DB key; filename-only matches are unsafe.
        'source_path':str(drawing['path']),
        'suggested_name':suggested_name.strip(),
        'block_name':block_name.strip(),
        'block_name_status':block_name_status,
        # Human-specified order for the guided CAD operation, not CAD-side object evidence.
        'view_plan':'|'.join(plan),
        'job_signature':job_signature,
        'working_file':Path(working_path).name if working_path else '',
        # The user-selected work copy, not only the original drawing file.
        'working_path':working_path,
        'source_digest':source_digest,
    }
    fd, tmpname=tempfile.mkstemp(prefix='.job_',suffix='.tmp',dir=str(storage))
    try:
        with os.fdopen(fd,'w',encoding='utf-16') as f:
            conf.write(f)
            f.flush();os.fsync(f.fileno())
        os.replace(tmpname,p)
    finally:
        if os.path.exists(tmpname):os.unlink(tmpname)
    return p


def read_active_job(path: Path) -> dict:
    conf=configparser.ConfigParser(interpolation=None)
    conf.read(path,encoding='utf-16')
    return dict(conf['active'])


def clear_active_job(storage: Path) -> None:
    """Invalidate an old macro's suggested name when switching CAD drawings."""
    p=storage/'active_job.ini'
    if p.exists():
        p.unlink()
    (storage / 'active_job_lease.json').unlink(missing_ok=True)
    (storage / 'panel_action.ini').unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.guard_', suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        os.replace(temp_name,path)
    finally:
        if os.path.exists(temp_name):os.unlink(temp_name)


def refresh_job_lease(storage: Path, signature: str) -> None:
    """Short-lived proof that the *live workbench* checked this job recently."""
    if not signature:
        raise ValueError('缺少活动任务签名')
    _atomic_json(storage/'active_job_lease.json',
                 {'signature':signature,'seen_at':time.time()})


def write_guard_launcher(storage: Path, *, executable: str, script: str = '') -> None:
    """Configure AHK's on-demand local verifier, not any CAD executable/API."""
    conf=configparser.ConfigParser(interpolation=None)
    conf['guard']={'executable':executable,'script':script}
    storage.mkdir(parents=True,exist_ok=True)
    fd, temp_name=tempfile.mkstemp(prefix='.runner_',suffix='.tmp',dir=str(storage))
    try:
        with os.fdopen(fd,'w',encoding='utf-16') as f:
            conf.write(f);f.flush();os.fsync(f.fileno())
        os.replace(temp_name,storage/'ahk_guard_runner.ini')
    finally:
        if os.path.exists(temp_name):os.unlink(temp_name)
