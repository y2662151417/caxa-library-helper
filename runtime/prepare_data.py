"""Prepare and verify the private CAXA user-data directory before startup."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare_data_directory(raw_path: str | Path) -> tuple[Path, Path]:
    data_dir = Path(raw_path).expanduser()
    if not data_dir.is_absolute():
        raise ValueError(f"用户数据目录必须是绝对路径：{data_dir}")
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    startup_log = log_dir / "startup.log"
    with startup_log.open("a", encoding="utf-8") as stream:
        stream.write("[BOOTSTRAP] User-data directory write check passed.\n")
        stream.flush()
        os.fsync(stream.fileno())
    return data_dir, log_dir


def main() -> int:
    raw_path = os.environ.get("CAXA_HELPER_DATA_DIR", "").strip()
    if not raw_path:
        print("ERROR: CAXA_HELPER_DATA_DIR is not set.", file=sys.stderr)
        return 2
    try:
        data_dir, log_dir = prepare_data_directory(raw_path)
    except (OSError, ValueError) as exc:
        print("ERROR: Cannot prepare the CAXA user-data directory.", file=sys.stderr)
        print(f"User-data path: {raw_path}", file=sys.stderr)
        print(f"Reason: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"User-data directory: {data_dir}")
    print(f"Log directory: {log_dir}")
    print("User-data write check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
