#!/usr/bin/env sh
# Stop Domain Agents (Linux / macOS). Same as: python3 stop.py
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python) || { echo "Python is not installed."; exit 1; }
exec "$PY" stop.py "$@"
