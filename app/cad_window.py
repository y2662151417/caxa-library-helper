"""Read-only check that the currently foreground CAXA document is the selected work copy."""
from __future__ import annotations

import configparser
import ntpath
import os
import re
from pathlib import Path


def title_has_exact_work_file(title: str, filename: str) -> bool:
    """Match a complete EXB filename, not a substring of another filename."""
    if not filename or not filename.casefold().endswith('.exb'):
        return False
    pattern = r'(?<![\w.-])' + re.escape(filename) + r'(?![\w.-])'
    return re.search(pattern, title or '', flags=re.IGNORECASE) is not None


def parse_cad_process_ini(text: str) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
        configured = parser.get('cad', 'process', fallback='').strip()
    except configparser.Error:
        return ''
    return ntpath.basename(configured)


def read_configured_cad_process(storage_dir: Path) -> str:
    path = Path(storage_dir) / 'cad_buttons.ini'
    try:
        raw = path.read_bytes()
    except OSError:
        return ''
    try:
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = raw.decode('utf-16')
        elif raw.count(b'\x00') > len(raw) // 4:
            text = raw.decode('utf-16-le')
        else:
            text = raw.decode('utf-8-sig')
    except UnicodeError:
        return ''
    return parse_cad_process_ini(text)


def _frontmost_window_for_process(process_name: str):
    """Return the first visible root-owner window for this process in Windows Z order."""
    if os.name != 'nt':
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def window_pid(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def window_process(hwnd):
        pid = window_pid(hwnd)
        if not pid:
            return ''
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ''
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return ''
            return ntpath.basename(buffer.value)
        finally:
            kernel32.CloseHandle(handle)

    def window_title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ''
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    windows = []
    seen = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if window_process(hwnd).casefold() != process_name.casefold():
            return True
        root_owner = user32.GetAncestor(hwnd, 3) or hwnd  # GA_ROOTOWNER
        if window_pid(root_owner) != window_pid(hwnd) or root_owner in seen:
            return True
        seen.add(root_owner)
        title = window_title(root_owner)
        if title:
            windows.append((int(root_owner), title, window_pid(root_owner)))
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return windows[0] if windows else None


def verify_current_document(storage_dir: Path, work_filename: str) -> tuple[bool, str]:
    """Require the frontmost CAXA root-owner caption to identify this registered work copy."""
    if os.name != 'nt':
        return False, '当前环境不是 Windows，无法核验 CAXA 当前图纸窗口。'
    if not work_filename:
        return False, '当前图纸尚未登记工作副本，不能复制正式块名称。'
    process_name = read_configured_cad_process(storage_dir)
    if not process_name:
        return False, '尚未绑定 CAXA 进程。请先连接当前 CAXA，再复制正式块名称。'
    window = _frontmost_window_for_process(process_name)
    if window is None:
        return False, '没有检测到可见的 CAXA 绘图窗口；请确认 CAXA 已打开。'
    _hwnd, title, _pid = window
    if not title_has_exact_work_file(title, work_filename):
        return False, (
            f'当前 CAXA 图纸与助手选中的图纸不一致。\n'
            f'助手要求的工作副本：{work_filename}\n'
            '请切换到对应工作副本后再复制；本次未修改剪贴板。'
        )
    return True, f'当前 CAXA 图纸已核对：{work_filename}'
