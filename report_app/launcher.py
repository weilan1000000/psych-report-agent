from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT_DIR / "output" / "report_app" / "service"


def is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        service_root = os.path.normcase(os.path.abspath(str(payload.get("project_root") or "")))
        expected_root = os.path.normcase(os.path.abspath(str(ROOT_DIR)))
        return (
            payload.get("ok") is True
            and payload.get("service") == "psych-report-console"
            and service_root == expected_root
        )
    except (OSError, ValueError, urllib.error.URLError):
        return False


def start_server(port: int, timeout_seconds: int) -> int:
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = SERVICE_DIR / "server.stdout.log"
    stderr_path = SERVICE_DIR / "server.stderr.log"
    command = [
        sys.executable,
        "-m",
        "report_app.server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open(
        "a", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    (SERVICE_DIR / "server.pid").write_text(str(process.pid), encoding="ascii")

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Report console failed to start.\n{detail}")
        if is_ready(url):
            return process.pid
        time.sleep(0.25)
    raise TimeoutError(
        f"Report console was not ready within {timeout_seconds} seconds. "
        f"Check {stderr_path}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the local report console.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--startup-timeout", type=int, default=15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not is_ready(url):
        start_server(args.port, args.startup_timeout)
    if not args.no_browser:
        webbrowser.open(f"{url}/")
    print(f"Report console is ready: {url}/")


if __name__ == "__main__":
    main()
