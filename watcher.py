#!/usr/bin/env python3
"""
File watcher — runs the full test suite whenever a .py file changes in src/ or tests/.

Usage:
    python watcher.py

Stop with Ctrl+C.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    print("ERROR: watchdog is not installed. Run: pip install watchdog")
    sys.exit(1)

ROOT = Path(__file__).parent
WATCH_DIRS = [ROOT / "src", ROOT / "tests"]
PYTEST_CMD = [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "--no-header"]

# ANSI colours (work on Windows 10+ terminals and most CI environments)
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

_last_run_time: float = 0.0
_DEBOUNCE_SECS = 1.5


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_tests(triggered_by: str = "") -> None:
    """Run pytest and print a colour-coded summary."""
    global _last_run_time

    now = time.monotonic()
    if now - _last_run_time < _DEBOUNCE_SECS:
        return
    _last_run_time = now

    separator = "─" * 62
    print(f"\n{_CYAN}{separator}{_RESET}")
    if triggered_by:
        short = Path(triggered_by).relative_to(ROOT) if ROOT in Path(triggered_by).parents else triggered_by
        print(f"{_BOLD}  [{_now()}] Changed: {short}{_RESET}")
    else:
        print(f"{_BOLD}  [{_now()}] Running tests...{_RESET}")
    print(f"{_CYAN}{separator}{_RESET}\n")

    proc = subprocess.run(PYTEST_CMD, cwd=ROOT)

    print(f"\n{_CYAN}{separator}{_RESET}")
    if proc.returncode == 0:
        print(f"{_GREEN}{_BOLD}  ✔  ALL TESTS PASSED  [{_now()}]{_RESET}")
    else:
        print(f"{_RED}{_BOLD}  ✘  TESTS FAILED (exit {proc.returncode})  [{_now()}]{_RESET}")
        print(f"{_YELLOW}  Fix the errors above, then save a file to re-run.{_RESET}")
    print(f"{_CYAN}{separator}{_RESET}\n")


class _ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = str(getattr(event, "src_path", ""))
        if path.endswith(".py") and not path.endswith((".pyc", "__pycache__")):
            run_tests(triggered_by=path)


def main() -> None:
    # Enable ANSI on Windows
    if sys.platform == "win32":
        import os
        os.system("")  # activates VT100 mode in cmd/powershell

    observer = Observer()
    watching: list[Path] = []
    for d in WATCH_DIRS:
        if d.exists():
            observer.schedule(_ChangeHandler(), str(d), recursive=True)
            watching.append(d)
        else:
            print(f"{_YELLOW}Warning: watch directory not found, skipping: {d}{_RESET}")

    if not watching:
        print(f"{_RED}No valid watch directories found. Exiting.{_RESET}")
        sys.exit(1)

    observer.start()
    print(f"\n{_BOLD}Product Scraper — Test Watcher{_RESET}")
    print(f"Watching: {', '.join(str(d.relative_to(ROOT)) for d in watching)}")
    print("Press Ctrl+C to stop.\n")

    run_tests()  # run immediately on start

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
        print(f"\n{_YELLOW}Watcher stopped.{_RESET}")
    observer.join()


if __name__ == "__main__":
    main()
