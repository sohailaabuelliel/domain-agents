#!/usr/bin/env python3
"""Start the whole system with one command — Windows, macOS or Linux.

    python start.py              # set up (first time only), start, open the browser
    python start.py --port 8080  # use another port
    python start.py --no-browser # do not open the browser

What it does:
  1. checks Python 3.11+
  2. creates .venv and installs requirements.txt the first time
     (and again only when requirements.txt changes)
  3. starts the server, waits until it answers, opens http://localhost:<port>
  4. keeps running in this terminal. Press Ctrl+C to stop.
     Lost the terminal? Run `python stop.py` (or stop.sh / stop.bat).

Uses only the Python standard library, so it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
RUN_DIR = ROOT / ".run"
STATE = RUN_DIR / "server.json"
REQS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
WINDOWS = os.name == "nt"


def say(msg: str) -> None:
    print(f"[domain-agents] {msg}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


# ---------- setup ----------
def ensure_env() -> Path:
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11 or newer is needed (found {sys.version.split()[0]}). "
                 "Install it from https://www.python.org/downloads/ and try again.")
    py = venv_python()
    if not py.exists():
        say("First run: creating a virtual environment in .venv ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    want = hashlib.sha256(REQS.read_bytes()).hexdigest()
    have = STAMP.read_text().strip() if STAMP.exists() else ""
    if want != have:
        say("Installing requirements (first run only, takes a minute) ...")
        has_pip = subprocess.run([str(py), "-m", "pip", "--version"], capture_output=True).returncode == 0
        if not has_pip:  # venvs made by uv/conda can come without pip
            subprocess.run([str(py), "-m", "ensurepip", "--upgrade"], capture_output=True)
        cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQS)]
        if subprocess.run(cmd).returncode != 0:
            sys.exit("Installing the requirements failed (see the message above). "
                     "Check your internet connection and run start again.")
        STAMP.write_text(want)
    return py


# ---------- state ----------
def read_state() -> dict | None:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def responds(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/domains", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def pick_port(start: int) -> int:
    for p in range(start, start + 20):
        if port_free(p):
            return p
    sys.exit(f"No free port between {start} and {start + 19}. Use --port to choose one.")


# ---------- main ----------
def main() -> int:
    ap = argparse.ArgumentParser(description="Start Domain Agents (server + browser).")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = this computer only (default); 0.0.0.0 = whole network")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    st = read_state()
    if st and responds(st["port"]):
        url = f"http://localhost:{st['port']}"
        say(f"Already running at {url} — opening the browser. (Stop it with: python stop.py)")
        if not a.no_browser:
            webbrowser.open(url)
        return 0

    py = ensure_env()
    port = a.port if port_free(a.port) else pick_port(a.port + 1)
    if port != a.port:
        say(f"Port {a.port} is busy, using {port} instead.")
    url = f"http://localhost:{port}"

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if WINDOWS else 0
    server = subprocess.Popen(
        [str(py), "-m", "uvicorn", "api.server:app", "--host", a.host, "--port", str(port)],
        cwd=ROOT, creationflags=flags, start_new_session=not WINDOWS)
    RUN_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"pid": server.pid, "launcher_pid": os.getpid(), "port": port,
                                 "started": time.strftime("%Y-%m-%d %H:%M:%S")}))

    def shutdown(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    if hasattr(signal, "SIGHUP"):              # terminal window closed (Linux/macOS)
        signal.signal(signal.SIGHUP, shutdown)
    try:
        say("Starting the server ...")
        for _ in range(120):
            if server.poll() is not None:
                say("The server stopped during start-up — see the error above.")
                return 1
            if responds(port):
                break
            time.sleep(0.5)
        else:
            say("The server did not answer within 60 s — see the messages above.")
        print()
        say(f"READY  ->  {url}")
        say("Paste your API key in Settings (gear at the bottom of the sidebar), or put it in .env")
        say("Stop: press Ctrl+C here — or run `python stop.py` from any terminal.")
        print(flush=True)
        if not a.no_browser:
            webbrowser.open(url)
        return server.wait()
    except KeyboardInterrupt:
        print()
        say("Stopping ...")
        return 0
    finally:
        stop_process(server)
        try:
            if (read_state() or {}).get("pid") == server.pid:
                STATE.unlink()
        except OSError:
            pass
        say("Stopped.")


def stop_process(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        if WINDOWS:
            p.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))
        else:
            os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=8)
    except Exception:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
