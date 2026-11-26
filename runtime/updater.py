"""Transactional, manifest-driven incremental updater for CAXA Library Helper.

Only program files under app/ and runtime/ may be replaced or removed. The root
launcher, update-source config, and user data are never part of an update manifest.
Git checkouts are protected: source files are synchronized only through Git.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

APP_ID = "CAXA_Library_Helper"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 160 * 1024 * 1024
USER_AGENT = "CAXA-Library-Helper-Updater/1"


class UpdateError(RuntimeError):
    pass


def is_git_checkout(root: Path) -> bool:
    """Return True when root contains Git metadata (directory or worktree file).

    A false negative could let the updater overwrite tracked source files, so
    inspection errors fail closed and disable automatic updates.
    """
    marker = Path(root) / ".git"
    try:
        return marker.exists() or marker.is_symlink()
    except OSError:
        return True


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _https_url(value: str, label: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UpdateError(f"{label} 必须是有效的 HTTPS 地址")
    return str(value)


def _safe_program_path(value: str) -> Path:
    raw = str(value or "")
    if "\\" in raw or "\x00" in raw:
        raise UpdateError(f"更新清单包含非法路径：{raw!r}")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise UpdateError(f"更新清单包含越界路径：{raw!r}")
    if pure.parts[0] not in ("app", "runtime"):
        raise UpdateError(f"更新器只允许更新 app/ 或 runtime/ 下的程序文件：{raw}")
    if pure.as_posix().lower() == "app/version.txt":
        raise UpdateError("VERSION.txt 由更新器统一维护，不能放入 files 列表")
    return Path(*pure.parts)


def _version_key(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(value))
    if not nums:
        raise UpdateError(f"版本号格式无效：{value!r}")
    return tuple(int(x) for x in nums)


def _read_url(url: str, timeout: float, opener=None, limit: int = MAX_FILE_BYTES) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/octet-stream"})
    open_fn = opener or urlopen
    try:
        response = open_fn(request, timeout=timeout)
        with response:
            data = response.read(limit + 1)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"下载失败：{url}；{exc}") from exc
    if len(data) > limit:
        raise UpdateError(f"下载内容超过限制（{limit} bytes）：{url}")
    return data


def _load_config(config_path: Path) -> dict:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"manifest_url": "", "auto_check": True, "timeout_seconds": 3}
    except (OSError, ValueError) as exc:
        raise UpdateError(f"更新源配置无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("更新源配置必须是 JSON 对象")
    return data


def _load_manifest(url: str, timeout: float, opener=None) -> dict:
    payload = _read_url(url, timeout, opener=opener, limit=MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError(f"更新清单不是有效 UTF-8 JSON：{exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("app_id") != APP_ID:
        raise UpdateError("更新清单的 app_id 不匹配")
    _version_key(manifest.get("version", ""))
    return manifest


def _validate_manifest(manifest: dict, manifest_url: str) -> tuple[list[dict], list[Path], str]:
    base_url = manifest.get("base_url") or manifest_url.rsplit("/", 1)[0]
    base_url = _https_url(base_url, "base_url")
    manifest_host = urlparse(manifest_url).hostname.casefold()
    if urlparse(base_url).hostname.casefold() != manifest_host:
        raise UpdateError("base_url 必须与 manifest_url 使用同一 HTTPS 主机")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise UpdateError("更新清单缺少 files 数组")
    clean_files = []
    seen = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise UpdateError("files 中存在非对象条目")
        rel = _safe_program_path(item.get("path", ""))
        key = rel.as_posix().casefold()
        if key in seen:
            raise UpdateError(f"更新清单存在重复路径：{rel.as_posix()}")
        seen.add(key)
        digest = str(item.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError(f"SHA-256 格式无效：{rel.as_posix()}")
        size = item.get("size")
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise UpdateError(f"文件大小字段无效：{rel.as_posix()}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise UpdateError("本次更新总大小超过安全限制")
        file_url = item.get("url") or urljoin(base_url.rstrip("/") + "/", rel.as_posix())
        file_url = _https_url(file_url, f"文件下载地址 {rel.as_posix()}")
        if urlparse(file_url).hostname.casefold() != manifest_host:
            raise UpdateError(f"文件下载地址与更新源不在同一主机：{rel.as_posix()}")
        clean_files.append({"path": rel, "sha256": digest, "size": size, "url": file_url})

    remove_items = manifest.get("remove", [])
    if not isinstance(remove_items, list):
        raise UpdateError("remove 必须是数组")
    removals = []
    for item in remove_items:
        rel = _safe_program_path(item)
        if rel.as_posix().casefold() in {"app/app.py", "runtime/launcher.py", "runtime/updater.py"}:
            raise UpdateError(f"关键启动文件不能从 remove 列表删除：{rel.as_posix()}")
        key = rel.as_posix().casefold()
        if key in seen:
            raise UpdateError(f"同一文件不能同时更新和删除：{rel.as_posix()}")
        if rel not in removals:
            removals.append(rel)
    return clean_files, removals, base_url


def _safe_target(root: Path, relative: Path) -> Path:
    root_real = root.resolve()
    target = root / relative
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise UpdateError(f"拒绝跟随更新目录中的符号链接：{cursor}")
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root_real):
        raise UpdateError(f"更新目标越出安装目录：{relative}")
    return target


def _copy_restore(backup: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".restore.tmp")
    shutil.copy2(backup, temp)
    os.replace(temp, target)


def _prune_rollback(rollback_root: Path, keep: int = 3) -> None:
    if not rollback_root.is_dir():
        return
    entries = sorted((p for p in rollback_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for old in entries[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def apply_update(root: Path, config: dict, opener=None, log=None) -> dict:
    """Check and apply one incremental update. No user-data path is writable."""
    root = Path(root).resolve()
    if is_git_checkout(root):
        version = _installed_version(root)
        if log:
            log("检测到 Git 仓库（根目录存在 .git）：拒绝自动替换受 Git 管理的程序文件。")
        return {"status": "development_checkout", "updated": [], "version": version}
    manifest_url = str(config.get("manifest_url", "")).strip()
    if not config.get("auto_check", True) or not manifest_url:
        return {"status": "disabled", "updated": [], "version": _installed_version(root)}
    manifest_url = _https_url(manifest_url, "manifest_url")
    timeout = float(config.get("timeout_seconds", 3))
    timeout = max(1.0, min(timeout, 12.0))
    manifest = _load_manifest(manifest_url, timeout, opener=opener)
    files, removals, _ = _validate_manifest(manifest, manifest_url)
    target_version = str(manifest["version"])
    current_version = _installed_version(root)
    if _version_key(target_version) < _version_key(current_version):
        return {"status": "newer_installed", "updated": [], "version": current_version}

    changed = []
    for item in files:
        target = _safe_target(root, item["path"])
        if not target.is_file() or target.is_symlink() or target.stat().st_size != item["size"] or sha256_file(target) != item["sha256"]:
            changed.append(item)
    remove_targets = []
    for rel in removals:
        target = _safe_target(root, rel)
        if target.exists():
            if target.is_dir():
                raise UpdateError(f"拒绝把目录作为文件删除：{rel}")
            remove_targets.append((rel, target))

    version_path = root / "app" / "VERSION.txt"
    if version_path.is_symlink():
        raise UpdateError("拒绝写入符号链接版本文件")
    if not changed and not remove_targets and current_version == target_version:
        return {"status": "current", "updated": [], "version": current_version}

    updates_dir = root / "updates"
    staging = Path(tempfile.mkdtemp(prefix="stage-", dir=str(updates_dir)))
    rollback_root = updates_dir / "rollback"
    rollback_root.mkdir(parents=True, exist_ok=True)
    backup_dir = rollback_root / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns()}-{os.getpid()}")
    backup_dir.mkdir(parents=True, exist_ok=False)
    applied: list[tuple[Path, Path | None]] = []
    removed: list[tuple[Path, Path]] = []
    version_backup = None
    try:
        # Download and verify every changed file before touching the installation.
        for item in changed:
            payload = _read_url(item["url"], timeout, opener=opener, limit=MAX_FILE_BYTES)
            if len(payload) != item["size"] or sha256_bytes(payload) != item["sha256"]:
                raise UpdateError(f"更新文件校验失败：{item['path'].as_posix()}")
            staged = staging / item["path"]
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(payload)

        if version_path.exists():
            version_backup = backup_dir / "app" / "VERSION.txt"
            version_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(version_path, version_backup)

        for item in changed:
            rel = item["path"]
            target = _safe_target(root, rel)
            staged = staging / rel
            backup = None
            if target.exists():
                backup = backup_dir / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            applied.append((target, backup))

        for rel, target in remove_targets:
            backup = backup_dir / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            target.unlink()
            removed.append((target, backup))

        version_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_version = version_path.with_suffix(".tmp")
        tmp_version.write_text(target_version + "\n", encoding="ascii")
        os.replace(tmp_version, version_path)
        _prune_rollback(rollback_root)
        result = {"status": "updated", "updated": [x["path"].as_posix() for x in changed],
                  "removed": [x.as_posix() for x in removals], "version": target_version,
                  "rollback_dir": str(backup_dir) if (backup_dir.exists() and any(backup_dir.iterdir())) else ""}
        if log:
            log(f"更新成功：{current_version} -> {target_version}；替换 {len(changed)} 个文件，删除 {len(remove_targets)} 个文件")
        return result
    except Exception:
        # Restore in reverse order; leave the previous installed version usable.
        for target, backup in reversed(applied):
            try:
                if backup and backup.exists():
                    _copy_restore(backup, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as restore_error:
                if log:
                    log(f"严重：恢复更新文件失败 {target}：{restore_error}")
        for target, backup in reversed(removed):
            try:
                _copy_restore(backup, target)
            except OSError as restore_error:
                if log:
                    log(f"严重：恢复已删除文件失败 {target}：{restore_error}")
        if version_backup and version_backup.exists():
            try:
                _copy_restore(version_backup, version_path)
            except OSError as restore_error:
                if log:
                    log(f"严重：恢复版本号失败：{restore_error}")
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _installed_version(root: Path) -> str:
    path = Path(root) / "app" / "VERSION.txt"
    try:
        return path.read_text(encoding="ascii").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def check_from_install(root: Path, log=None, opener=None) -> dict:
    root = Path(root).resolve()
    if is_git_checkout(root):
        version = _installed_version(root)
        if log:
            log("检测到 Git 开发仓库（.git）：已跳过更新源读取和自动增量更新，请通过 GitHub Desktop 同步代码。")
        return {"status": "development_checkout", "updated": [], "version": version}
    config_path = root / "updates" / "update_source.json"
    config = _load_config(config_path)
    return apply_update(root, config, opener=opener, log=log)
