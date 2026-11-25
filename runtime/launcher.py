"""Stable launcher. Kept outside app/ so normal incremental releases do not replace it."""
from __future__ import annotations

import os
import runpy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
RUNTIME_DIR = ROOT / "runtime"


def data_directory() -> Path:
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


DATA_DIR = data_directory()
# Ensure child processes (including AutoHotkey) use the same data directory.
os.environ["CAXA_HELPER_DATA_DIR"] = str(DATA_DIR)
LOG_DIR = DATA_DIR / "logs"


def write_log(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "launcher.log").open("a", encoding="utf-8") as stream:
            stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\\n")
    except OSError:
        pass


def main() -> int:
    if not APP_DIR.is_dir() or not (APP_DIR / "app.py").is_file():
        write_log("启动失败：app/app.py 不存在")
        print("程序文件不完整，请重新同步 CAXA 图库助手仓库。")
        return 2

    if "--skip-update" not in sys.argv[1:]:
        try:
            sys.path.insert(0, str(RUNTIME_DIR))
            import updater
            result = updater.check_from_install(ROOT, log=write_log)
            status = result.get("status", "unknown")
            version = result.get("version", "?")
            updated = result.get("updated", [])
            write_log(f"更新检查完成：状态={status}；版本={version}；下载/替换文件数={len(updated)}")
            if status == "updated":
                write_log(f"已应用增量更新：{version}；文件：{updated}")
        except Exception as exc:
            # An update failure must not prevent the last working version from starting.
            write_log(f"更新检查/应用失败，继续启动当前版本：{type(exc).__name__}: {exc}")

    sys.path.insert(0, str(APP_DIR))
    os.environ["CAXA_MINI_PANEL"] = "1"
    os.environ["CAXA_INSTALL_ROOT"] = str(ROOT)
    os.chdir(APP_DIR)
    try:
        version = (APP_DIR / "VERSION.txt").read_text(encoding="ascii").strip()
    except OSError:
        version = "unknown"
    write_log(f"启动应用，版本 {version}")
    runpy.run_path(str(APP_DIR / "app.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
