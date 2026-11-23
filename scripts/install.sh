#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"${PYTHON:-python3.11}" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix web ci
