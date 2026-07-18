#!/usr/bin/env python3
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SEED_ROOT = Path(os.environ.get("SEED_DEMO_DATA_WATCH_ROOT", BASE_DIR / "seed_demo_data")).resolve()
WATCH_INTERVAL_SECONDS = float(os.environ.get("SEED_DEMO_ACCOUNTS_WATCH_INTERVAL_SECONDS", "2"))


def iter_seed_files() -> list[Path]:
    if not SEED_ROOT.exists():
        return []
    return sorted(path for path in SEED_ROOT.rglob("*") if path.is_file())


def fingerprint_seed_files() -> str:
    digest = hashlib.sha256()
    for path in iter_seed_files():
        stat = path.stat()
        digest.update(str(path.relative_to(SEED_ROOT)).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
    return digest.hexdigest()


def seed_demo_accounts_run() -> None:
    subprocess.run(
        [sys.executable, "manage.py", "seed_demo_data"],
        cwd=BASE_DIR,
        check=True,
    )


def main() -> int:
    if not SEED_ROOT.exists():
        return 0

    previous_fingerprint = fingerprint_seed_files()

    while True:
        time.sleep(WATCH_INTERVAL_SECONDS)
        current_fingerprint = fingerprint_seed_files()
        if current_fingerprint == previous_fingerprint:
            continue

        try:
            seed_demo_accounts_run()
        except subprocess.CalledProcessError:
            previous_fingerprint = current_fingerprint
            continue

        previous_fingerprint = current_fingerprint


if __name__ == "__main__":
    raise SystemExit(main())
