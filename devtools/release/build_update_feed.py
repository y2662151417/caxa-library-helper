#!/usr/bin/env python3
"""Build an incremental-update feed from an installed CAXA helper tree.

The feed contains the latest app/ tree. The client downloads only files whose
SHA-256 differs from the local installation. Hosting the output directory is a
separate, explicitly approved deployment step.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path

APP_ID = "CAXA_Library_Helper"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--install-root", required=True, type=Path)
    p.add_argument("--version", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--base-url", required=True, help="HTTPS URL of the hosted feed directory")
    p.add_argument("--previous-manifest", type=Path, help="Optional prior manifest; obsolete app/ paths become remove entries")
    args = p.parse_args()
    root = args.install_root.resolve()
    app = root / "app"
    runtime = root / "runtime"
    if not (app / "app.py").is_file() or not (runtime / "updater.py").is_file():
        p.error("--install-root must point to a CAXA helper installation containing app/app.py and runtime/updater.py")
    out = args.output.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(app, out / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(runtime, out / "runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = []
    for folder in (out / "app", out / "runtime"):
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name == "VERSION.txt":
                continue
            rel = path.relative_to(out).as_posix()
            files.append({"path": rel, "size": path.stat().st_size, "sha256": sha256(path)})
    current_paths = {item["path"].casefold() for item in files}
    removed = []
    if args.previous_manifest and args.previous_manifest.is_file():
        previous = json.loads(args.previous_manifest.read_text(encoding="utf-8"))
        for item in previous.get("files", []):
            old_path = item.get("path", "")
            if old_path.casefold().startswith(("app/", "runtime/")) and old_path.casefold() not in current_paths:
                removed.append(old_path)
    (out / "app" / "VERSION.txt").unlink(missing_ok=True)
    manifest = {
        "app_id": APP_ID,
        "version": args.version,
        "base_url": args.base_url.rstrip("/"),
        "files": files,
        "remove": sorted(set(removed), key=str.casefold)
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created update feed: {out}")
    print(f"Files in manifest: {len(files)} (client downloads only changed files)")
    print("Upload the output directory to the approved HTTPS update host; do not upload user drawings or local data.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())