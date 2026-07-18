#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
WATCH_INTERVAL_SECONDS = float(os.environ.get("RENEWAL_REMINDER_WATCH_INTERVAL_SECONDS", "3600"))


def run_reminders() -> None:
    subprocess.run(
        [sys.executable, "manage.py", "send_renewal_reminders"],
        cwd=BASE_DIR,
        check=True,
    )


def main() -> int:
    while True:
        try:
            run_reminders()
        except subprocess.CalledProcessError:
            pass
        time.sleep(WATCH_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
