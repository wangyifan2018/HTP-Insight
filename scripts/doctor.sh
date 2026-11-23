#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
uname -sm
if [ "$(uname -s)" = Darwin ]; then
  sw_vers
  sysctl hw.memsize hw.ncpu machdep.cpu.brand_string
fi
df -h .
for cmd in node npm claude qnn-net-run qnn-profile-viewer qairt-visualizer; do
  command -v "$cmd" || echo "$cmd unavailable on PATH"
done
node -v
npm -v
python3 -V
runner=python3
if [ -x .venv/bin/python ]; then runner=.venv/bin/python; fi
"$runner" - <<'PY'
from importlib.metadata import version, PackageNotFoundError
import os, sys
from pathlib import Path

print("Active Python", sys.version.split()[0], "virtualenv", sys.prefix != sys.base_prefix)
for package in ("torch", "onnx", "onnxruntime", "aimet-torch", "aimet-onnx", "qairt-visualizer", "qai-hub", "mcp"):
    try:
        print(package, version(package))
    except PackageNotFoundError:
        print(package, "unavailable")
for variable in ("QAIRT_SDK_ROOT", "QNN_SDK_ROOT", "AI_HUB_API_TOKEN", "QAI_HUB_API_TOKEN"):
    print(variable, "set" if os.getenv(variable) else "unset")
for path in ("~/.qai_hub/client.ini", "~/.qai_hub/client.yaml", "~/qairt", "/opt/qcom"):
    print(path, "present" if Path(path).expanduser().exists() else "unavailable")
PY
