#!/usr/bin/env python3
"""Build a self-contained Windows CAXA helper ZIP with bundled Python and AHK runtimes."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

PACKAGE_LABEL = "独立测试版"
DOC_FILES = (
    "docs/README_实际使用.md",
    "docs/块名称清单导入说明.md",
    "docs/CHANGELOG_v0.42.17.md",
    "docs/开发接续说明_v0.42.17.md",
)
FORBIDDEN_SUFFIXES = {".exb", ".dwg", ".dxf", ".sqlite", ".sqlite3", ".db", ".pyc"}
FORBIDDEN_PARTS = {".git", "__pycache__", "devtools", ".github", "working_copies", "backups"}
LAUNCHER_NAME = "启动CAXA助手.bat"
PROGRAM_NAME = "CAXA助手.exe"
AHK_VERSION = "2.0.32"


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Required package directory is missing: {source}")
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Refusing to package a symbolic link: {item}")
        relative = item.relative_to(source)
        if "__pycache__" in relative.parts or item.suffix.lower() == ".pyc":
            continue
        if any(part in FORBIDDEN_PARTS for part in item.relative_to(source.parent).parts):
            raise ValueError(f"Refusing to package a forbidden path: {item}")
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            continue
        if item.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"Refusing to package a user-data or build file: {item}")
        if item.name.endswith("~") or item.name.lower().endswith((".bak", ".tmp")):
            raise ValueError(f"Refusing to package a temporary file: {item}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _isolated_launcher(version: str) -> bytes:
    folder = f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}"
    lines = [
        "@echo off",
        "setlocal EnableExtensions DisableDelayedExpansion",
        'pushd "%~dp0" >nul 2>&1',
        "if errorlevel 1 goto PATH_ERROR",
        "if not defined LOCALAPPDATA goto DATA_ERROR",
        f'set "CAXA_HELPER_DATA_DIR=%LOCALAPPDATA%\\{folder}"',
        'set "CAXA_INSTALL_ROOT=%~dp0"',
        'set "CAXA_MINI_PANEL=1"',
        'if not exist "program\\CAXA助手.exe" goto MISSING_PROGRAM',
        'if not exist "app\\app.py" goto MISSING_APP',
        'if not exist "%CAXA_HELPER_DATA_DIR%\\logs" mkdir "%CAXA_HELPER_DATA_DIR%\\logs" >nul 2>&1',
        'set "LOG=%CAXA_HELPER_DATA_DIR%\\logs\\launcher.log"',
        '>>"%LOG%" echo [START] %DATE% %TIME%',
        '>>"%LOG%" echo [START] Install folder: %CD%',
        '>>"%LOG%" echo [START] Python runtime: bundled with program\\CAXA助手.exe',
        "echo Starting CAXA Library Helper...",
        '"program\\CAXA助手.exe" >>"%LOG%" 2>&1',
        'set "RC=%ERRORLEVEL%"',
        'if "%RC%"=="0" goto DONE',
        '>>"%LOG%" echo [ERROR] Launcher exit code: %RC%',
        "echo Startup failed. Details:",
        'type "%LOG%"',
        "pause",
        "goto DONE",
        ":MISSING_PROGRAM",
        "echo Missing bundled program: program\\CAXA助手.exe",
        "pause",
        "goto DONE",
        ":MISSING_APP",
        "echo Missing application files: app\\app.py",
        "pause",
        "goto DONE",
        ":DATA_ERROR",
        "echo ERROR: LOCALAPPDATA is unavailable; cannot create an isolated user-data folder.",
        "pause",
        "popd",
        "exit /b 1",
        ":PATH_ERROR",
        "echo ERROR: Windows could not open the folder containing this launcher.",
        "pause",
        "exit /b 1",
        ":DONE",
        "popd",
        "exit /b 0",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def _copy_ahk_runtime(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"AutoHotkey runtime directory is missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("AutoHotkey64.exe", "AutoHotkey32.exe", "license.txt", "LICENSE.txt"):
        item = source / name
        if item.is_file():
            target = destination / ("license.txt" if name.lower() == "license.txt" else name)
            shutil.copy2(item, target)
            if name.lower().endswith(".exe"):
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                target.with_name(target.name + ".sha256").write_text(digest + "\n", encoding="ascii")
                copied += 1
    if copied < 1 or not (destination / "license.txt").is_file():
        raise ValueError("Verified AutoHotkey runtime must include an EXE and its license.txt.")


def _write_test_readme(path: Path, version: str) -> None:
    folder = f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}"
    content = f"""# CAXA 图库助手 v{version}｜独立测试版

## 运行条件

- Windows 10/11 x64。
- 不需要预先安装 Python，也不需要配置 Python 环境变量。
- Python 运行环境和 Tk/Tcl 图形库已随程序打包。
- AutoHotkey v{AHK_VERSION} 便携运行时已随程序打包并在首次启动时复制到用户数据目录。
- 解压后双击根目录的 {LAUNCHER_NAME}。

## 与原有程序隔离

- 请解压到新目录，不要覆盖现有 CAXA 图库助手。
- 本测试包将用户数据固定写入：%LOCALAPPDATA%\\{folder}
- 不读取或修改原有的 %LOCALAPPDATA%\\CAXA_Library_Helper，也不使用迁移目录中的 UserData。
- 自动更新关闭；此测试包不会从 main 稳定分支下载或替换程序文件。
- 图纸、工作副本、数据库、Excel 清单、个人配置和日志不随 ZIP 分发。

## 本轮主要调整

- 悬浮窗缩小，只显示当前图纸、块名称匹配/复制、当前 CAXA 图纸核对和常用操作。
- 块名称清单支持 Excel .xlsx，两列分别为“图号”和“块名称”。
- 清理重复线、颜色归层、图层设置和图层全开不再要求先配置六视图计划；仍要求先选择图纸并打开工作副本。
- “定义图符”仍要求有效的双视图/三视图计划。
- 属性编辑、属性填入和图库入库由操作者在 CAXA 中完成；助手只负责检索和复制正式块名称。

## 实机测试要求

- 第一次验收只使用自制虚构测试图，或真实图纸的独立副本；不要直接修改或保存公司正式图纸。
- 先选择图纸并点击“打开图纸”，确认工作副本已在 CAXA 打开。
- 点击“核对图纸”，只有显示“CAXA：图纸匹配”才表示当前活动窗口标题与所选工作副本一致。
- 清理重复线、颜色归层会影响当前选集；必须检查高亮范围，确认后再执行。
- “全部图层打开”会对当前工作副本执行 layon；只在测试图中使用。
- 不自动保存 EXB，不自动填写属性，不自动完成图库入库。
- 若任何按钮无响应、误选对象或出现无法确认的对话框，停止操作并截图反馈，不要继续保存。

## 用户数据

测试数据与原程序完全分开。测试过程中产生的记录保存在上述 TEST 数据目录。关闭测试程序不会自动删除这些数据；确认不再需要后，可自行删除该 TEST 目录。不要删除原有的 CAXA_Library_Helper 数据目录。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_test_package(repo_root: Path, output_dir: Path, portable_dir: Path,
                       ahk_runtime_dir: Path) -> tuple[Path, Path]:
    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    portable_dir = Path(portable_dir).resolve()
    ahk_runtime_dir = Path(ahk_runtime_dir).resolve()
    version_path = repo_root / "app" / "VERSION.txt"
    if not version_path.is_file():
        raise FileNotFoundError(f"Missing version file: {version_path}")
    version = version_path.read_text(encoding="ascii").strip()
    if not version or any(ch not in "0123456789." for ch in version):
        raise ValueError(f"Invalid application version: {version!r}")
    if not (portable_dir / PROGRAM_NAME).is_file():
        raise FileNotFoundError(f"Missing PyInstaller executable: {portable_dir / PROGRAM_NAME}")

    output_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"CAXA_图库助手_v{version}_{PACKAGE_LABEL}"
    zip_path = output_dir / f"{package_name}.zip"
    checksum_path = output_dir / f"{package_name}.sha256"

    with tempfile.TemporaryDirectory(prefix="caxa-test-package-") as temp:
        staging = Path(temp) / package_name
        staging.mkdir()
        _copy_tree(repo_root / "app", staging / "app")
        _copy_tree(repo_root / "runtime", staging / "runtime")
        _copy_tree(portable_dir, staging / "program")
        _copy_ahk_runtime(ahk_runtime_dir,
                          staging / "runtime" / "vendor" / f"AutoHotkey_{AHK_VERSION}")

        (staging / LAUNCHER_NAME).write_bytes(_isolated_launcher(version))
        for relative in DOC_FILES:
            source = repo_root / relative
            if not source.is_file():
                raise FileNotFoundError(f"Required documentation is missing: {source}")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        _write_test_readme(staging / "docs" / f"测试版使用说明_v{version}.md", version)

        log_readme = repo_root / "logs" / "README.txt"
        if log_readme.is_file():
            (staging / "logs").mkdir(parents=True, exist_ok=True)
            shutil.copy2(log_readme, staging / "logs" / "README.txt")

        updates = staging / "updates"
        updates.mkdir(parents=True, exist_ok=True)
        update_config = {
            "app_id": "CAXA_Library_Helper",
            "channel": "test",
            "auto_check": False,
            "timeout_seconds": 3,
            "manifest_url": "",
        }
        (updates / "update_source.json").write_text(
            json.dumps(update_config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        top_files = sorted(p.name for p in staging.iterdir() if p.is_file())
        if top_files != [LAUNCHER_NAME]:
            raise ValueError(f"Unexpected files at package root: {top_files}")
        bat = (staging / LAUNCHER_NAME).read_text(encoding="utf-8-sig")
        if f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}" not in bat:
            raise ValueError("Test launcher does not use its isolated user-data directory.")
        if "py -3" in bat or "python.exe" in bat or "where python" in bat:
            raise ValueError("Test launcher must not depend on a system Python installation.")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in sorted(staging.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(staging.parent).as_posix())

    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        expected_prefix = package_name + "/"
        if not names or any(not name.startswith(expected_prefix) for name in names):
            raise ValueError("ZIP does not contain exactly one top-level package directory.")
        if any(Path(name).suffix.lower() in FORBIDDEN_SUFFIXES for name in names):
            raise ValueError("ZIP contains a forbidden user-data or build file.")
        roots = {name[len(expected_prefix):].split("/", 1)[0] for name in names}
        if roots != {"启动CAXA助手.bat", "app", "runtime", "program", "updates", "docs", "logs"}:
            raise ValueError(f"Unexpected package root entries: {sorted(roots)}")
        if expected_prefix + "program/CAXA助手.exe" not in names:
            raise ValueError("ZIP is missing the bundled Windows application executable.")
        if expected_prefix + f"runtime/vendor/AutoHotkey_{AHK_VERSION}/AutoHotkey64.exe" not in names:
            raise ValueError("ZIP is missing the bundled AutoHotkey x64 runtime.")
        config_name = expected_prefix + "updates/update_source.json"
        config = json.loads(archive.read(config_name).decode("utf-8"))
        if config.get("auto_check") is not False or config.get("manifest_url") != "":
            raise ValueError("Automatic updates must remain disabled in the test package.")
        bat = archive.read(expected_prefix + LAUNCHER_NAME).decode("utf-8-sig")
        if f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}" not in bat:
            raise ValueError("The package launcher is not isolated from stable user data.")
        if "py -3" in bat or "python.exe" in bat or "where python" in bat:
            raise ValueError("The package launcher still requires system Python.")

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--portable-dir", type=Path, required=True)
    parser.add_argument("--ahk-runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    zip_path, checksum_path = build_test_package(
        args.repo_root, args.output_dir, args.portable_dir, args.ahk_runtime_dir
    )
    print(f"Created: {zip_path}")
    print(f"SHA-256: {checksum_path.read_text(encoding='utf-8').strip()}")
    print("No system Python or first-run AutoHotkey download is required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

