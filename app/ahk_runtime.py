"""Managed AutoHotkey v2 runtime for the CAXA helper.

Downloads the official portable ZIP on first use, verifies the publisher's
SHA-256 digest, and extracts only the matching architecture executable into
the configured CAXA user-data directory (or LOCALAPPDATA fallback). No installer,
registry write, or administrator privilege is required.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

AHK_VERSION = "2.0.32"
CONTROLLER_BUILD_ID = "caxa-helper-v0.42.16"
ARCHIVE_URL = "https://github.com/AutoHotkey/AutoHotkey/releases/download/v2.0.32/AutoHotkey_2.0.32.zip"
ARCHIVE_SHA256 = "384a4c125e8d7b5b77ddbd5a593ec761d3e9e96e97a95931cf56e9a077fda114"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MIN_EXE_BYTES = 500 * 1024


def _is_windows() -> bool:
    return os.name == "nt"


def _default_storage_dir() -> Path:
    configured = os.environ.get("CAXA_HELPER_DATA_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise RuntimeError("CAXA_HELPER_DATA_DIR 必须是绝对路径。")
        return path
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return Path(local) / "CAXA_Library_Helper"
    return Path.home() / ".local" / "share" / "CAXA_Library_Helper"


def executable_name(machine: Optional[str] = None) -> str:
    machine = (machine or platform.machine()).lower()
    if machine in {"x86", "i386", "i486", "i586", "i686"}:
        return "AutoHotkey32.exe"
    # x64 is also the normal emulation choice on Windows ARM64.
    return "AutoHotkey64.exe"


def runtime_directory(storage_dir: Optional[Path] = None) -> Path:
    root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
    return root / "runtime" / ("AutoHotkey_" + AHK_VERSION)


def read_controller_pid(storage_dir: Optional[Path] = None) -> int:
    """Read the AHK PID marker, accepting both legacy UTF-8 BOM and raw UTF-8."""
    root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
    marker = root / "ahk_controller.pid"
    try:
        raw = marker.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return 0
    if not raw or not raw.isascii() or not raw.isdecimal():
        return 0
    try:
        pid = int(raw)
    except ValueError:
        return 0
    return pid if pid > 0 else 0


def read_controller_build(storage_dir: Optional[Path] = None) -> str:
    """Read the build identity written by the running AHK controller."""
    root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
    marker = root / "ahk_controller_build.txt"
    try:
        value = marker.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", value) else ""


def _startup_diagnostics(root: Path) -> str:
    parts = []
    for path in (root / "ahk_controller_startup.log",
                 root / "ahk_controller_marker_error.log"):
        try:
            detail = path.read_text(encoding="utf-8-sig", errors="replace").strip()
        except OSError:
            detail = ""
        if detail:
            parts.append(f"[{path}]\n{detail[-2400:]}")
    return "\n".join(parts) or "没有捕获到启动错误文本。"

def _valid_pe(path: Path, expected_name: str) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < MIN_EXE_BYTES:
            return False
        with path.open("rb") as stream:
            header = stream.read(4096)
        if len(header) < 64 or header[:2] != b"MZ":
            return False
        pe_offset = int.from_bytes(header[0x3C:0x40], "little")
        if pe_offset + 6 > len(header) or header[pe_offset:pe_offset + 4] != b"PE\0\0":
            return False
        machine = int.from_bytes(header[pe_offset + 4:pe_offset + 6], "little")
        if expected_name == "AutoHotkey64.exe":
            return machine == 0x8664
        return machine == 0x014C
    except (OSError, ValueError):
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_runtime(storage_dir: Optional[Path] = None, machine: Optional[str] = None) -> Optional[Path]:
    name = executable_name(machine)
    folder = runtime_directory(storage_dir)
    exe = folder / name
    marker = folder / "runtime-version.txt"
    try:
        lines = marker.read_text(encoding="ascii").splitlines()
        if (len(lines) == 2 and lines[0].strip() == AHK_VERSION
                and _valid_pe(exe, name) and _sha256_file(exe) == lines[1].strip()):
            return exe
    except OSError:
        pass
    return None


def _download_archive(destination: Path, opener=None) -> str:
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "CAXA-Gallery-Helper/0.35", "Accept": "application/octet-stream"},
    )
    digest = hashlib.sha256()
    total = 0
    try:
        response = open_url(request, timeout=60)
        with response:
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise RuntimeError("AutoHotkey 官方压缩包超过大小限制，已停止下载。")
                    digest.update(chunk)
                    output.write(chunk)
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    actual = digest.hexdigest()
    if actual != ARCHIVE_SHA256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            "AutoHotkey 下载文件的 SHA-256 校验失败，文件已删除。\n"
            f"期望：{ARCHIVE_SHA256}\n实际：{actual}"
        )
    if not zipfile.is_zipfile(destination):
        destination.unlink(missing_ok=True)
        raise RuntimeError("下载文件通过哈希校验但不是有效 ZIP，已停止安装。")
    return actual


def install_runtime(storage_dir: Optional[Path] = None, opener=None, machine: Optional[str] = None) -> Path:
    """Install official portable AHK into the user's data directory."""
    cached = cached_runtime(storage_dir, machine)
    if cached:
        return cached
    name = executable_name(machine)
    folder = runtime_directory(storage_dir)
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="ahk-stage-", dir=str(folder.parent)))
    archive = staging / "AutoHotkey_2.0.32.zip"
    try:
        _download_archive(archive, opener=opener)
        with zipfile.ZipFile(archive, "r") as package:
            candidates = [
                info for info in package.infolist()
                if PurePosixPath(info.filename.replace("\\", "/")).name.lower() == name.lower()
                and len(PurePosixPath(info.filename.replace("\\", "/")).parts) == 1
                and not info.is_dir()
            ]
            if len(candidates) != 1:
                raise RuntimeError(f"官方 ZIP 中未找到唯一的 {name}。")
            info = candidates[0]
            if info.file_size < MIN_EXE_BYTES or info.file_size > 15 * 1024 * 1024:
                raise RuntimeError("AutoHotkey 可执行文件大小异常，已停止安装。")
            data = package.read(info)
            exe_stage = staging / name
            exe_stage.write_bytes(data)
            if not _valid_pe(exe_stage, name):
                raise RuntimeError("AutoHotkey 可执行文件架构或 PE 签名不正确。")
            license_info = next((x for x in package.infolist()
                                 if PurePosixPath(x.filename.replace("\\", "/")).name.lower() == "license.txt"
                                 and not x.is_dir()), None)
            license_data = package.read(license_info) if license_info else None
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        staged_target = folder / (name + ".new")
        shutil.copyfile(exe_stage, staged_target)
        os.replace(staged_target, target)
        if license_data:
            (folder / "license.txt").write_bytes(license_data)
        if not _valid_pe(target, name):
            target.unlink(missing_ok=True)
            raise RuntimeError("安装后的 AutoHotkey 文件校验失败。")
        marker_tmp = folder / "runtime-version.txt.tmp"
        marker_tmp.write_text(AHK_VERSION + "\n" + _sha256_file(target) + "\n", encoding="ascii")
        os.replace(marker_tmp, folder / "runtime-version.txt")
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)




def launch_script(script: Path, storage_dir: Optional[Path] = None, popen=None):
    """Launch AHK with fresh diagnostics and clear stale PID/build markers."""
    if not _is_windows():
        raise RuntimeError("CAXA 快捷控制器只能在 Windows 上运行。")
    script = Path(script).resolve()
    if not script.is_file():
        raise FileNotFoundError(str(script))
    root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
    exe = install_runtime(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "ahk_controller.pid"
    build_marker = root / "ahk_controller_build.txt"
    marker_error = root / "ahk_controller_marker_error.log"
    log_path = root / "ahk_controller_startup.log"
    try:
        marker.unlink(missing_ok=True)
        build_marker.unlink(missing_ok=True)
        marker_error.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"无法清理旧的控制器标记文件：{exc}") from exc
    runner = popen or subprocess.Popen
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    with log_path.open("wb") as log:
        log.write((f"--- Launch AutoHotkey {AHK_VERSION}: {script.name} ---\n").encode("utf-8"))
        log.flush()
        proc = runner(
            [str(exe), "/ErrorStdOut=UTF-8", str(script)],
            cwd=str(script.parent),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    return proc

def start_script_async(script: Path, callback: Optional[Callable[[bool, str], None]] = None,
                       storage_dir: Optional[Path] = None) -> threading.Thread:
    """Prepare AHK, then wait for this exact process to register its PID and build markers."""
    def worker():
        proc = None
        try:
            root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
            proc = launch_script(script, storage_dir=root)
            marker = root / "ahk_controller.pid"
            deadline = time.monotonic() + 8.0
            registered = False
            while time.monotonic() < deadline:
                return_code = proc.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"AutoHotkey 进程启动后立即退出，退出代码 {return_code}。\n"
                        + _startup_diagnostics(root)
                    )
                if (read_controller_pid(root) == proc.pid
                        and read_controller_build(root) == CONTROLLER_BUILD_ID):
                    registered = True
                    break
                time.sleep(0.1)
            if not registered:
                observed = read_controller_pid(root)
                observed_build = read_controller_build(root)
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                except Exception:
                    pass
                raise RuntimeError(
                    "AutoHotkey 进程仍在运行，但 8 秒内没有写入与本次进程 PID、构建版本均匹配的控制器标记。\n"
                    f"本次进程 PID：{proc.pid}；标记文件 PID：{observed or '缺失/无效'}；"
                    f"控制器版本标记：{observed_build or '缺失/无效'}；期望版本：{CONTROLLER_BUILD_ID}；"
                    f"标记路径：{marker}\n"
                    + _startup_diagnostics(root)
                )
            message = f"AutoHotkey v{AHK_VERSION} 控制器 {CONTROLLER_BUILD_ID} 已注册，PID {proc.pid}。"
            ok = True
        except Exception as exc:
            root = Path(storage_dir) if storage_dir is not None else _default_storage_dir()
            message = (
                f"AutoHotkey v{AHK_VERSION} 控制器启动失败：{exc}\n\n"
                "无需重新安装助手。请检查本机启动诊断日志；首次运行需要联网下载并校验官方便携版。"
            )
            ok = False
        if callback:
            try:
                callback(ok, message)
            except Exception:
                pass
    thread = threading.Thread(target=worker, name="CAXA-AHK-runtime", daemon=True)
    thread.start()
    return thread
