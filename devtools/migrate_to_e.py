#!/usr/bin/env python3
"""One-time, verified migration of the CAXA helper and its private data to E:.

The source repository and source user-data directory are never deleted.
The destination is assembled in a staging directory and renamed into place
only after repository hashes and the SQLite backup have been verified.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

APP_ID = "CAXA_Library_Helper"
REPOSITORY_DIRNAME = "caxa-library-helper"
USER_DATA_DIRNAME = "UserData"
USER_DATA_MARKER = ".caxa_userdata.json"
DATABASE_NAME = "progress.sqlite3"
DATABASE_SIDECARS = {
    DATABASE_NAME + "-wal",
    DATABASE_NAME + "-shm",
    DATABASE_NAME + "-journal",
}
DEFAULT_TARGET_ROOT = Path("E:/CAXA助手")
MIN_FREE_RESERVE = 128 * 1024 * 1024
REPO_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


class MigrationError(RuntimeError):
    """A safe-to-abort migration error."""


def source_data_directory() -> Path:
    configured = os.environ.get("CAXA_HELPER_DATA_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise MigrationError("CAXA_HELPER_DATA_DIR 不是绝对路径，无法安全确定旧数据目录。")
        return path
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return Path(local) / "CAXA_Library_Helper"
    return Path.home() / ".local" / "share" / "CAXA_Library_Helper"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path, *, repository: bool = False):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            raise MigrationError(f"检测到符号链接，为避免复制到意外位置，已停止：{path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if repository:
            if relative.parts and relative.parts[0] == "logs":
                continue
            if any(part in REPO_CACHE_DIRS for part in relative.parts):
                continue
            if path.suffix.lower() == ".pyc":
                continue
        yield path


def _tree_size(root: Path, *, repository: bool = False) -> int:
    return sum(path.stat().st_size for path in _iter_files(root, repository=repository))


def _copy_file_verified(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if source.stat().st_size != destination.stat().st_size:
        raise MigrationError(f"复制后文件大小不一致：{source}")
    if sha256_file(source) != sha256_file(destination):
        raise MigrationError(f"复制后 SHA-256 校验失败：{source}")
    return destination.stat().st_size


def _repo_ignore(source_root: Path):
    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        skipped = set()
        if current == source_root and "logs" in names:
            skipped.add("logs")
        for name in names:
            if name in REPO_CACHE_DIRS or name.lower().endswith(".pyc"):
                skipped.add(name)
        return skipped
    return ignore


def copy_repository(source: Path, destination: Path) -> dict:
    if not (source / ".git").exists():
        raise MigrationError("当前目录不是完整 Git 仓库（缺少 .git），不能保留提交历史。")
    if (source / ".git" / "index.lock").exists():
        raise MigrationError("Git 仓库正在写入（存在 .git/index.lock）。请等待 GitHub Desktop 操作结束后重试。")
    shutil.copytree(source, destination, ignore=_repo_ignore(source.resolve()))
    source_files = {p.relative_to(source).as_posix(): sha256_file(p)
                    for p in _iter_files(source, repository=True)}
    destination_files = {p.relative_to(destination).as_posix(): sha256_file(p)
                         for p in _iter_files(destination, repository=True)}
    if source_files != destination_files:
        missing = sorted(set(source_files) - set(destination_files))
        extra = sorted(set(destination_files) - set(source_files))
        changed = sorted(k for k in set(source_files) & set(destination_files)
                         if source_files[k] != destination_files[k])
        raise MigrationError(
            "Git 仓库复制校验失败。"
            f"缺失={missing[:5]}，多出={extra[:5]}，内容不同={changed[:5]}"
        )
    return {
        "files": len(source_files),
        "bytes": sum(p.stat().st_size for p in _iter_files(source, repository=True)),
        "git_metadata_preserved": (destination / ".git").exists(),
    }


def _sqlite_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    counts = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
    return counts


def snapshot_database(source: Path, destination: Path) -> dict:
    source_connection = None
    destination_connection = None
    try:
        source_connection = sqlite3.connect(str(source), timeout=30)
        source_check = [row[0] for row in source_connection.execute("PRAGMA quick_check")]
        if source_check != ["ok"]:
            raise MigrationError(f"原始图纸进度数据库完整性检查失败：{source_check}")
        source_counts = _sqlite_table_counts(source_connection)

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_connection = sqlite3.connect(str(destination), timeout=30)
        source_connection.backup(destination_connection, pages=256, sleep=0.05)
        destination_connection.commit()
        destination_connection.execute("PRAGMA journal_mode=DELETE")
        destination_connection.commit()

        destination_check = [row[0] for row in destination_connection.execute("PRAGMA quick_check")]
        destination_counts = _sqlite_table_counts(destination_connection)
        if destination_check != ["ok"] or destination_counts != source_counts:
            raise MigrationError(
                "目标数据库校验失败。"
                f"quick_check={destination_check}；源表记录数={source_counts}；目标表记录数={destination_counts}"
            )
    except sqlite3.Error as exc:
        raise MigrationError(f"SQLite 数据库迁移失败：{exc}") from exc
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()

    shutil.copystat(source, destination)
    return {
        "file": DATABASE_NAME,
        "quick_check": "ok",
        "table_rows": source_counts,
        "bytes": destination.stat().st_size,
    }


def copy_user_data(source: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return {"files": 0, "bytes": 0, "database": None, "source_existed": False}

    source_database = source / DATABASE_NAME
    orphaned_sidecars = [source / name for name in DATABASE_SIDECARS if (source / name).exists()]
    if not source_database.exists() and orphaned_sidecars:
        raise MigrationError(
            "发现 SQLite 数据库日志文件，但主数据库不存在。为避免遗漏未合并事务，已停止迁移。"
        )

    file_count = 0
    copied_bytes = 0
    for path in _iter_files(source):
        relative = path.relative_to(source)
        if relative.as_posix() == DATABASE_NAME or path.name in DATABASE_SIDECARS:
            continue
        copied_bytes += _copy_file_verified(path, destination / relative)
        file_count += 1

    database_info = None
    if source_database.is_file():
        database_info = snapshot_database(source_database, destination / DATABASE_NAME)
        file_count += 1
        copied_bytes += int(database_info["bytes"])

    return {
        "files": file_count,
        "bytes": copied_bytes,
        "database": database_info,
        "source_existed": True,
    }


def copy_legacy_repository_logs(source_repo: Path, destination_data: Path) -> int:
    legacy_logs = source_repo / "logs"
    if not legacy_logs.is_dir():
        return 0
    destination = destination_data / "logs" / "legacy-from-install"
    count = 0
    for path in _iter_files(legacy_logs):
        relative = path.relative_to(legacy_logs)
        _copy_file_verified(path, destination / relative)
        count += 1
    return count


def _pid_is_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def check_helper_is_stopped(source_repo: Path, source_data: Path) -> None:
    marker = source_data / "ahk_controller.pid"
    if marker.is_file():
        try:
            pid = int(marker.read_text(encoding="utf-8-sig").strip())
        except (OSError, ValueError) as exc:
            raise MigrationError(
                "无法读取 AutoHotkey 控制器状态标记。请先关闭 CAXA 助手和浮动面板，再重试。"
            ) from exc
        if _pid_is_alive(pid):
            raise MigrationError(
                "检测到 AutoHotkey 控制器仍在运行。请先关闭 CAXA 制作控制台和浮动面板，再运行迁移。"
            )

    if os.name != "nt":
        return
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise MigrationError("无法检查助手进程状态（未找到 PowerShell）。请关闭助手后联系维护者。")
    root_literal = str(source_repo.resolve()).replace("'", "''").lower()
    command = (
        f"$root = '{root_literal}'\n"
        "$hits = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {\n"
        "  ($_.Name -ieq 'python.exe' -or $_.Name -ieq 'pythonw.exe') -and $_.CommandLine -and\n"
        "  $_.CommandLine.ToLowerInvariant().Contains($root) -and\n"
        "  ($_.CommandLine.ToLowerInvariant().Contains('launcher.py') -or $_.CommandLine.ToLowerInvariant().Contains('app.py'))\n"
        "} | ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.Name }\n"
        "$hits\n"
    )
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MigrationError(f"无法检查 CAXA 助手是否正在运行：{exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise MigrationError(f"无法确认 CAXA 助手已关闭，请关闭控制台和浮动面板后重试。{detail}")
    running = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if running:
        raise MigrationError(
            "检测到 CAXA 助手进程仍在运行：" + "、".join(running)
            + "。请先关闭 CAXA 制作控制台和浮动面板，再运行迁移。"
        )


def migrate(source_repo: Path, target_root: Path) -> dict:
    source_repo = source_repo.resolve()
    target_root = target_root.expanduser().resolve()
    source_data = source_data_directory()

    if not (source_repo / "app" / "app.py").is_file() or not (source_repo / "runtime" / "launcher.py").is_file():
        raise MigrationError("请从 caxa-library-helper 仓库根目录运行迁移程序。")
    if not (source_repo / ".git").exists():
        raise MigrationError("当前目录不是 Git 仓库，无法保留 GitHub Desktop 的提交历史。")
    if os.name == "nt" and target_root.drive.upper() != "E:":
        raise MigrationError(f"本次已确认迁移到 E 盘，目标路径必须位于 E:，当前为：{target_root}")
    if not target_root.parent.is_dir():
        raise MigrationError(f"目标磁盘或目录不存在：{target_root.parent}")
    if target_root == source_repo or source_repo in target_root.parents:
        raise MigrationError("目标目录不能位于当前 Git 仓库内部。")
    if target_root.exists() and (not target_root.is_dir() or any(target_root.iterdir())):
        raise MigrationError(
            f"目标目录已经存在且不为空：{target_root}\n"
            "为避免覆盖已有文件，迁移已停止。请先确认该目录内容。"
        )

    check_helper_is_stopped(source_repo, source_data)

    repo_bytes = _tree_size(source_repo, repository=True)
    data_bytes = _tree_size(source_data) if source_data.exists() else 0
    total_bytes = repo_bytes + data_bytes
    required_free = total_bytes + max(MIN_FREE_RESERVE, int(total_bytes * 0.10))
    free_bytes = shutil.disk_usage(target_root.parent).free
    if free_bytes < required_free:
        raise MigrationError(
            "E 盘剩余空间不足。\n"
            f"预计需要至少 {required_free / (1024 ** 3):.2f} GB，"
            f"当前可用 {free_bytes / (1024 ** 3):.2f} GB。"
        )

    staging = target_root.parent / f".{target_root.name}.migration-{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        staging.mkdir(parents=False, exist_ok=False)
        staged_repo = staging / REPOSITORY_DIRNAME
        staged_data = staging / USER_DATA_DIRNAME

        print("1/5 正在复制 GitHub 仓库（包括 .git 历史）……")
        repo_stats = copy_repository(source_repo, staged_repo)

        print("2/5 正在复制 UserData 并校验文件……")
        data_stats = copy_user_data(source_data, staged_data)

        print("3/5 正在归档旧安装目录日志……")
        legacy_log_count = copy_legacy_repository_logs(source_repo, staged_data)

        marker = {
            "app_id": APP_ID,
            "schema_version": 1,
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "data_directory": str(target_root / USER_DATA_DIRNAME),
        }
        (staged_data / USER_DATA_MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        report = {
            "app_id": APP_ID,
            "migration_schema": 1,
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_repository": str(source_repo),
            "target_repository": str(target_root / REPOSITORY_DIRNAME),
            "source_user_data": str(source_data),
            "target_user_data": str(target_root / USER_DATA_DIRNAME),
            "repository": repo_stats,
            "user_data": data_stats,
            "legacy_repository_log_files": legacy_log_count,
            "source_files_deleted": False,
        }
        (staged_data / "migration-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        print("4/5 正在检查目标目录和 Git 元数据……")
        if not (staged_repo / ".git").exists():
            raise MigrationError("目标仓库缺少 .git 元数据，迁移已取消。")
        if not (staged_repo / "启动CAXA助手.bat").is_file():
            raise MigrationError("目标仓库缺少启动文件，迁移已取消。")
        if not (staged_data / USER_DATA_MARKER).is_file():
            raise MigrationError("目标 UserData 标记文件缺失，迁移已取消。")

        print("5/5 正在完成目录切换……")
        if target_root.exists():
            target_root.rmdir()
        os.replace(staging, target_root)
        report["target_root"] = str(target_root)
        return report
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="将 CAXA 图库助手和本地数据迁移到 E 盘。")
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    args = parser.parse_args()
    source_repo = Path(__file__).resolve().parents[1]
    try:
        report = migrate(source_repo, args.target_root)
    except MigrationError as exc:
        print("\n迁移未执行：")
        print(exc)
        return 1
    except Exception as exc:
        print("\n迁移失败，原始 C 盘文件未删除：")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    print("\n迁移完成。")
    print(f"新程序目录：{report['target_repository']}")
    print(f"新数据目录：{report['target_user_data']}")
    print(f"仓库文件：{report['repository']['files']} 个")
    print(f"用户数据文件：{report['user_data']['files']} 个")
    if report["user_data"]["database"]:
        print("SQLite 完整性：通过")
        print(f"数据库表记录数：{report['user_data']['database']['table_rows']}")
    print(f"旧安装日志归档：{report['legacy_repository_log_files']} 个")
    print("\n原始 C 盘仓库和 UserData 均未删除。请先验证 E 盘程序，再切换 GitHub Desktop。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
