#!/usr/bin/env python3
"""Stop the server started by start.py — from any terminal, on any OS.

    python stop.py

Use it when the terminal that runs start.py is closed or lost.
(In that terminal itself, Ctrl+C does the same.)
Uses only the Python standard library.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".run" / "server.json"
WINDOWS = os.name == "nt"


def say(msg: str) -> None:
    print(f"[domain-agents] {msg}", flush=True)


def alive(pid: int) -> bool:
    if WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def responds(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/domains", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def kill(pid: int) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)          # the server runs in its own process group
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                return
        for _ in range(16):
            if not alive(pid):
                return
            time.sleep(0.5)


def main() -> int:
    try:
        st = json.loads(STATE.read_text())
    except (OSError, ValueError):
        say("Nothing to stop: no server started by start.py is running.")
        return 0
    pid, port = int(st["pid"]), int(st["port"])
    if alive(pid):
        say(f"Stopping the server (pid {pid}, port {port}) ...")
        kill(pid)
    launcher = st.get("launcher_pid")
    if launcher and alive(int(launcher)) and not WINDOWS:
        try:
            os.kill(int(launcher), signal.SIGTERM)   # lets the start.py window finish cleanly
        except OSError:
            pass
    time.sleep(0.5)
    try:
        STATE.unlink()
    except OSError:
        pass
    if responds(port):
        say(f"Port {port} still answers — another program is using it. Close it manually.")
        return 1
    say("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
