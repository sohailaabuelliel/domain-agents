#!/usr/bin/env sh
# Start Domain Agents (Linux / macOS). Same as: python3 start.py
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python) || { echo "Python 3.11+ is needed: https://www.python.org/downloads/"; exit 1; }
exec "$PY" start.py "$@"
