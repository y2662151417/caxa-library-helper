"""Reliable text clipboard access for CAXA property-grid copies."""
from __future__ import annotations

import os
import time


class ClipboardReadError(RuntimeError):
    pass


def decode_unicode_clipboard_data(data: bytes) -> str:
    """Decode CF_UNICODETEXT bytes, stopping at an aligned UTF-16 NUL terminator."""
    raw = bytes(data)
    end = len(raw)
    for offset in range(0, len(raw) - 1, 2):
        if raw[offset:offset + 2] == b'\x00\x00':
            end = offset
            break
    if end % 2:
        end -= 1
    try:
        return raw[:end].decode('utf-16-le')
    except UnicodeDecodeError as exc:
        raise ClipboardReadError('Windows 剪贴板中的 Unicode 文本格式无效。') from exc


def _read_windows_clipboard_text() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    opened = False
    for attempt in range(5):
        if user32.OpenClipboard(None):
            opened = True
            break
        if attempt < 4:
            time.sleep(0.04)
    if not opened:
        raise ClipboardReadError('无法打开 Windows 剪贴板；请稍后重试。')

    try:
        for clipboard_format in (13, 1):  # CF_UNICODETEXT, then legacy CF_TEXT
            if not user32.IsClipboardFormatAvailable(clipboard_format):
                continue
            handle = user32.GetClipboardData(clipboard_format)
            if not handle:
                continue
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                continue
            try:
                size = kernel32.GlobalSize(handle)
                if not size:
                    continue
                raw = ctypes.string_at(pointer, size)
            finally:
                kernel32.GlobalUnlock(handle)

            if clipboard_format == 13:
                text = decode_unicode_clipboard_data(raw)
            else:
                text = raw.split(b'\x00', 1)[0].decode('mbcs', errors='replace')
            if text:
                return text
        raise ClipboardReadError('剪贴板中没有可读取的文本。请在 CAXA 参数栏中重新复制文字。')
    finally:
        user32.CloseClipboard()


def read_clipboard_text(widget=None) -> str:
    """Read Unicode text without Tk's fragile Windows STRING selection conversion."""
    if os.name == 'nt':
        return _read_windows_clipboard_text()
    if widget is None:
        raise ClipboardReadError('当前平台需要 Tk 窗口对象才能读取剪贴板。')
    try:
        return widget.clipboard_get()
    except Exception as first_error:
        try:
            return widget.selection_get(selection='CLIPBOARD', type='UTF8_STRING')
        except Exception as second_error:
            raise ClipboardReadError(
                f'无法读取剪贴板文本：{second_error or first_error}'
            ) from second_error
