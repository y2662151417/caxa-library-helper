"""Fail-closed validation before publishing a CAXA keyboard-helper task.

This is a local file/metadata check, not verification of CAD object edits or
proof of the active document tab inside CAXA.
"""
from __future__ import annotations
from pathlib import Path
import configparser
import sqlite3
import core
import bridge


def validate_handoff(c, path, view_plan):
    d = core.get_drawing(c, path)
    if d is None or not d['present'] or not d['valid_name']:
        raise ValueError('当前图纸不在有效的源图清单内')
    block_info=core.block_name_for_path(c,path)
    has_exact_block_name=(block_info['status']=='已匹配' and bool(block_info['block_name']))
    if not d['suggested_name'] and not has_exact_block_name:
        raise ValueError('尚无建议名称，也没有按完整图号匹配的正式块名称')
    if d['naming_mode'] == '待确认' and not has_exact_block_name:
        raise ValueError('命名规则待确认，且没有正式块名称匹配，不能发布 CAD 快捷任务')

    source = Path(d['path'])
    root = Path(d['root'])
    work = Path(d['working_path']) if d['working_path'] else None
    if core.path_contains_symlink(root, source):
        raise ValueError('源图路径含符号链接或已离开登记目录，不能发布任务')
    if not source.is_file() or source.is_symlink():
        raise ValueError('源图不存在或是符号链接，不能发布任务')
    if core.digest_file(source) != d['sha256']:
        raise ValueError('源图在扫描后发生变化，请重新扫描并核对参数')
    if not work or not d['working_base_sha256']:
        raise ValueError('没有登记过工作副本，不能让快捷脚本操作原图')
    if core.path_contains_symlink(root, work):
        raise ValueError('工作副本路径含符号链接或已离开登记目录，不能发布任务')
    if not work.is_file() or work.is_symlink():
        raise ValueError('工作副本不存在或不是普通文件')
    if core.work_copy_aliases_source(source, work):
        raise ValueError('工作副本与原图为同一文件（可能为硬链接），已禁用 CAD 快捷操作')
    if work.name.casefold() == source.name.casefold():
        raise ValueError('旧版工作副本与原图同名，CAD 标签无法可靠区分；禁用自动点击，原有副本保持不变')
    if d['working_base_sha256'] != d['sha256']:
        raise ValueError('工作副本来自旧版源图，不能发布快捷任务')
    try:
        rel = source.resolve(strict=True).relative_to(root.resolve(strict=True))
        expected = core.working_copy_path(root,rel)
        if work.absolute() != expected.absolute():
            raise ValueError('工作副本路径与原始图纸目录结构不符')
    except (OSError, RuntimeError) as e:
        raise ValueError('工作副本路径无法安全核验') from e

    # A CAXA main-window caption typically exposes only the basename, not a
    # unique on-disk path. Never bind an unattended click to ambiguous names.
    same_basename = [x['path'] for x in core.list_drawings(c)
                     if x['present'] and Path(x['path']).name.casefold() == source.name.casefold()]
    if len(same_basename) != 1:
        raise ValueError('不同目录中存在同名 EXB：无法仅凭 CAD 窗口标题辨别当前图纸，已禁用快捷自动点击')

    effective_name=block_info['block_name'] if has_exact_block_name else d['suggested_name']
    if has_exact_block_name:
        same_gallery_name = [x for x in core.block_name_summary(c)
                             if x['block_name'].casefold()==effective_name.casefold()
                             and x['match_status']=='已匹配']
    else:
        same_gallery_name = [x for x in core.list_drawings(c)
                             if x['present'] and x['suggested_name'] == effective_name]
    if len(same_gallery_name) != 1:
        raise ValueError('图库建议名称重复或正式块名称匹配不唯一，已禁用快捷自动点击')

    plan = tuple(view_plan)
    if not 1 <= len(plan) <= 6 or len(set(plan)) != len(plan):
        raise ValueError('视图任务必须为1至6个互不重复的项目')
    db_slots = {f"{s['view_type']}·{s['size_kind']}" for s in core.slots_for(c, path)
                if s['status'] != '不需要'}
    if set(plan) != db_slots:
        raise ValueError('当前快捷视图顺序与数据库计划不一致，已拒绝发布')
    return d


def _validate_published_job(c, original: bytes, expected_signature: str | None = None) -> str:
    """Raise when an INI no longer identifies the current verified work copy.

    Read-only: never touches CAD, updates SQLite, or modifies the active INI.
    """
    conf = configparser.ConfigParser(interpolation=None)
    conf.optionxform = str
    conf.read_string(original.decode('utf-16'))
    job = conf['active']
    path = job.get('source_path', '')
    plan_string = job.get('view_plan', '')
    if not path or not plan_string:
        raise ValueError('missing source path / view plan')
    plan = tuple(plan_string.split('|'))
    drawing = validate_handoff(c, path, plan)
    expected_plan = tuple(
        f"{view}·{kind}" for view in core.VIEW_TYPES
        for kind in ('带尺寸', '无尺寸')
        for slot in core.slots_for(c, path)
        if slot['view_type'] == view and slot['size_kind'] == kind
        and slot['status'] != '不需要')
    if plan != expected_plan:
        raise ValueError('view order changed')
    block_info=core.block_name_for_path(c,path)
    signature = bridge.expected_job_signature(
        drawing, drawing['suggested_name'], plan,
        block_info['block_name'], block_info['status'])
    if (job.get('source_digest', '') != drawing['sha256']
            or job.get('working_path', '') != drawing['working_path']
            or job.get('working_file', '') != Path(drawing['working_path']).name
            or job.get('filename', '') != Path(drawing['path']).name
            or job.get('suggested_name', '') != drawing['suggested_name']
            or job.get('block_name', '') != block_info['block_name']
            or job.get('block_name_status', '') != block_info['status']
            or job.get('code', '') != drawing['code']
            or job.get('job_signature', '') != signature
            or (expected_signature is not None and signature != expected_signature)):
        raise ValueError('published task no longer matches the drawing')
    return signature


def active_job_valid(c, storage: Path, expected_signature: str | None = None) -> bool:
    """Independent non-mutating verification for a user-triggered CAD action."""
    path = storage / 'active_job.ini'
    try:
        original = path.read_bytes()
        _validate_published_job(c, original, expected_signature)
        # An in-progress republish must not make an earlier verification valid.
        return path.read_bytes() == original
    except (ValueError, KeyError, UnicodeError, configparser.Error,
            OSError, sqlite3.Error):
        return False


def reconcile_active_job(c, storage: Path) -> tuple[bool, str | None]:
    """Validate once; revoke if stale; return (revoked, valid_signature).

    Avoid re-hashing the full EXB a second time on every 15-second Tk poll.
    A concurrent republish is never treated as validated under an older job.
    """
    job_file = storage / 'active_job.ini'
    try:
        original = job_file.read_bytes()
    except FileNotFoundError:
        return False, None
    try:
        sig = _validate_published_job(c, original)
        if job_file.read_bytes() != original:
            return False, None
        return False, sig
    except (ValueError, KeyError, UnicodeError, configparser.Error,
            OSError, sqlite3.Error):
        try:
            if job_file.read_bytes() != original:
                return False, None
            job_file.unlink()
            return True, None
        except FileNotFoundError:
            return False, None


def revoke_stale_active_job(c, storage: Path) -> bool:
    """Legacy bool API, now sharing the one-pass reconciliation validator."""
    revoked, _ = reconcile_active_job(c, storage)
    return revoked