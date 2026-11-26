#!/usr/bin/env python3
"""Build a self-contained, isolated CAXA helper test ZIP from a source checkout."""
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
    "docs/CHANGELOG_v0.42.16.md",
)
FORBIDDEN_SUFFIXES = {".exb", ".dwg", ".dxf", ".sqlite", ".sqlite3", ".db", ".pyc"}
FORBIDDEN_PARTS = {".git", "__pycache__", "devtools", ".github", "working_copies", "backups"}
LAUNCHER_NAME = "启动CAXA助手.bat"


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Required package directory is missing: {source}")
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Refusing to package a symbolic link: {item}")
        if any(part in FORBIDDEN_PARTS for part in item.relative_to(source.parent).parts):
            raise ValueError(f"Refusing to package a forbidden path: {item}")
        relative = item.relative_to(source)
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


def _isolated_launcher(source: Path, version: str) -> bytes:
    raw = source.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    old = newline.join((
        "rem A migrated E: installation has a marker beside the repository.",
        "rem The original C: installation keeps using its existing LOCALAPPDATA data.",
        'set "CAXA_HELPER_DATA_DIR="',
        'if exist "%~dp0..\\UserData\\.caxa_userdata.json" (',
        '    for %%I in ("%~dp0..\\UserData") do set "CAXA_HELPER_DATA_DIR=%%~fI"',
        ")",
        "if not defined CAXA_HELPER_DATA_DIR (",
        '    if defined LOCALAPPDATA set "CAXA_HELPER_DATA_DIR=%LOCALAPPDATA%\\CAXA_Library_Helper"',
        ")",
        "if not defined CAXA_HELPER_DATA_DIR goto DATA_ERROR",
    ))
    folder = f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}"
    new = newline.join((
        "rem Isolated test profile: never read or write the stable user's CAXA profile.",
        'set "CAXA_HELPER_DATA_DIR="',
        f'if defined LOCALAPPDATA set "CAXA_HELPER_DATA_DIR=%LOCALAPPDATA%\\{folder}"',
        "if not defined CAXA_HELPER_DATA_DIR goto DATA_ERROR",
    ))
    if text.count(old) != 1:
        raise ValueError("Could not safely replace the launcher data-directory block.")
    text = text.replace(old, new, 1)
    if r"\\CAXA_Library_Helper" + '"' in text or r"UserData\\.caxa_userdata.json" in text:
        raise ValueError("Stable user-data path remains in the test launcher.")
    encoded = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + encoded) if has_bom else encoded


def _write_test_readme(path: Path, version: str) -> None:
    folder = f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}"
    content = f"""# CAXA 图库助手 v{version}｜独立测试版

## 这份测试包与现有程序隔离

- 请将 ZIP 解压到一个新的目录，不要覆盖现有 CAXA 图库助手目录。
- 根目录只有一个日常入口：启动CAXA助手.bat。
- 本测试包将用户数据固定写入：%LOCALAPPDATA%\\{folder}
- 不读取或修改原有的 %LOCALAPPDATA%\\CAXA_Library_Helper，也不使用迁移目录中的 UserData。
- 自动更新已关闭；此测试包不会从 main 稳定分支下载或替换程序文件。
- 图纸、工作副本、数据库、个人配置和日志不随 ZIP 分发。

## 启动条件

1. Windows 10/11。
2. 本机已安装 Python 3.10+，安装时包含 Tkinter。
3. 双击根目录的 启动CAXA助手.bat。
4. 第一次使用 CAD 控制器时，程序会从 AutoHotkey 官方发布页下载固定版本的便携运行时并校验 SHA-256。

## 本轮重点检查

悬浮面板首页应直接显示以下六个常用入口：

- 清理重复线
- 颜色归层
- 打开图层设置
- 全部图层打开
- 定义图符
- 属性与入库

日常操作不需要记忆快捷键；本版本不注册全局快捷键，不拦截 CAXA 原生按键。

## 实机测试要求

- 第一次验收只使用自制虚构测试图，或真实图纸的独立副本；不要直接打开、修改或保存公司正式图纸。
- 先检查面板是否显示完整、置顶是否正常，以及“打开图层设置”是否能打开 CAXA 原生图层管理窗口。
- “全部图层打开”会对当前 CAXA 图纸执行 layon；只在测试图中使用。
- “清理重复线”和“颜色归层”会修改当前选集；必须在测试图中确认选取范围，检查结果后再保存测试副本。
- “定义图符”“属性与入库”会在测试环境中创建或修改图符/图库内容；只使用虚构测试内容。
- 若任何按钮无响应、误选对象或出现无法确认的对话框，停止操作并截图反馈，不要继续保存。

## 测试数据说明

测试数据与原程序完全分开。测试过程中产生的记录保存在上述 TEST 数据目录。关闭测试程序不会自动删除这些数据；确认不再需要后，可自行删除该 TEST 目录。不要删除原有的 CAXA_Library_Helper 数据目录。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_test_package(repo_root: Path, output_dir: Path) -> tuple[Path, Path]:
    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    version_path = repo_root / "app" / "VERSION.txt"
    if not version_path.is_file():
        raise FileNotFoundError(f"Missing version file: {version_path}")
    version = version_path.read_text(encoding="ascii").strip()
    if not version or any(ch not in "0123456789." for ch in version):
        raise ValueError(f"Invalid application version: {version!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"CAXA_图库助手_v{version}_{PACKAGE_LABEL}"
    zip_path = output_dir / f"{package_name}.zip"
    checksum_path = output_dir / f"{package_name}.sha256"

    with tempfile.TemporaryDirectory(prefix="caxa-test-package-") as temp:
        staging = Path(temp) / package_name
        staging.mkdir()
        _copy_tree(repo_root / "app", staging / "app")
        _copy_tree(repo_root / "runtime", staging / "runtime")

        launcher = repo_root / LAUNCHER_NAME
        if not launcher.is_file():
            raise FileNotFoundError(f"Missing launcher: {launcher}")
        (staging / LAUNCHER_NAME).write_bytes(_isolated_launcher(launcher, version))

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
        if f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}" not in (staging / LAUNCHER_NAME).read_text(encoding="utf-8-sig"):
            raise ValueError("Test launcher does not use its isolated user-data directory.")
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
        if roots != {"启动CAXA助手.bat", "app", "runtime", "updates", "docs", "logs"}:
            raise ValueError(f"Unexpected package root entries: {sorted(roots)}")
        config_name = expected_prefix + "updates/update_source.json"
        config = json.loads(archive.read(config_name).decode("utf-8"))
        if config.get("auto_check") is not False or config.get("manifest_url") != "":
            raise ValueError("Automatic updates must remain disabled in the test package.")
        bat = archive.read(expected_prefix + LAUNCHER_NAME).decode("utf-8-sig")
        if f"CAXA_Library_Helper_TEST_{version.replace('.', '_')}" not in bat:
            raise ValueError("The package launcher is not isolated from stable user data.")
        if r"\\CAXA_Library_Helper" + '"' in bat or r"UserData\\.caxa_userdata.json" in bat:
            raise ValueError("The package launcher still references stable user data.")

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    return zip_path, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    zip_path, checksum_path = build_test_package(args.repo_root, args.output_dir)
    print(f"Created: {zip_path}")
    print(f"SHA-256: {checksum_path.read_text(encoding='ascii').strip()}")
    print("The ZIP uses a separate TEST user-data directory and has automatic updates disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
