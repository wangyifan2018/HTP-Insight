"""Local Web entry point for the same bounded Android capture used by the CLI."""

import os
from math import prod
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from threading import Lock
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .android import AndroidRunner

CAPTURE_LOCK = Lock()
VERIFIED_ARCH = {"SM6650": "v73"}


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    inputs: dict[str, str]
    mode: Literal["basic", "detailed", "linting", "optrace"] = "basic"
    runs: int = Field(default=110, ge=1, le=1000)
    warmup: int = Field(default=10, ge=0, lt=1000)
    native_io: bool = False
    schematic: str | None = None
    trace_dlc: str | None = None
    framework_csv: str | None = None


def local_runner(root):
    adb = os.getenv("ADB_BIN") or shutil.which("adb") or str(Path.home() / "Library/Android/sdk/platform-tools/adb")
    configured_sdk = os.getenv("QAIRT_SDK_ROOT")
    candidates = sorted((root / "qairt/sdk").glob("2.50.*"), reverse=True)
    sdk = Path(configured_sdk) if configured_sdk else next(iter(candidates), None)
    if sdk is None or not (sdk / "bin/aarch64-android/qnn-net-run").is_file():
        raise ValueError("Configure QAIRT_SDK_ROOT or install an Android QAIRT 2.50 SDK in the workspace")
    serial = os.getenv("HTP_INSIGHT_ADB_SERIAL")
    probe = AndroidRunner(adb, serial, sdk, "v73", 10)
    if probe.adb(["get-state"]) != "device":
        raise RuntimeError("Connect and authorize an Android device over ADB")
    device = {key: probe.shell(["getprop", prop]) or None for key, prop in {
        "model": "ro.product.model", "soc": "ro.soc.model", "abi": "ro.product.cpu.abi",
    }.items()}
    if device["abi"] != "arm64-v8a":
        raise ValueError(f"Expected Android arm64-v8a, got {device['abi']}")
    known = VERIFIED_ARCH.get((device["soc"] or "").upper())
    arch = (os.getenv("HTP_INSIGHT_ANDROID_ARCH") or known or "").lower()
    if not re.fullmatch(r"v\d+", arch):
        raise ValueError("Configure HTP_INSIGHT_ANDROID_ARCH for this device's verified Hexagon version")
    if known and arch != known:
        raise ValueError(f"The connected {device['soc']} was verified with Hexagon {known}")
    runner = AndroidRunner(adb, serial, sdk, arch, 180)
    if any(not path.is_file() for path in runner.tools("basic", True)):
        raise ValueError(f"The SDK is missing basic DLC tools for Hexagon {arch}")
    return runner, {**device, "hexagon": arch.upper(), "sdk": sdk.name}


def status(root):
    try:
        _, details = local_runner(root)
    except (ValueError, RuntimeError, OSError, TimeoutExpired) as exc:
        return {"ready": False, "reason": str(exc)}
    return {"ready": True, "device": details, "busy": CAPTURE_LOCK.locked()}


def capture(core, spec: CaptureRequest):
    artifact = core.read(spec.artifact_id, "artifact.json")
    suffixes = {"HTP_CONTEXT": "context.bin", "QNN_DLC": "model.dlc"}
    if artifact["format"] not in suffixes or not artifact.get("source_model_id"):
        raise ValueError("Pair the DLC or Context with its source ONNX before capture")
    graph = core.graph(artifact["source_model_id"])
    if set(spec.inputs) != set(graph.inputs):
        raise ValueError(f"Provide raw inputs for {', '.join(graph.inputs)}")
    files = {name: core.inbox_path(filename, {".raw", ".bin"}) for name, filename in spec.inputs.items()}
    for name, path in files.items():
        tensor = graph.tensors[name]
        if not path.stat().st_size:
            raise ValueError(f"Input {name} is empty")
        if not spec.native_io and tensor.dtype == "FLOAT" and tensor.shape is not None and all(isinstance(n, int) for n in tensor.shape):
            size = prod(tensor.shape) * 4
            if path.stat().st_size != size:
                raise ValueError(f"Input {name} must contain {size} bytes for {tensor.shape} FP32")
    if not CAPTURE_LOCK.acquire(blocking=False):
        raise RuntimeError("An Android capture is already running")
    try:
        runner, device = local_runner(core.root)
        target = artifact.get("target_device")
        if target and target.casefold() not in {(device[key] or "").casefold() for key in ("model", "soc")}:
            raise ValueError(f"Compiled artifact targets {target}; connected device reports {device['soc'] or device['model']}")
        target_arch = artifact["compatibility"].get("hexagon")
        if isinstance(target_arch, str) and target_arch.upper() != device["hexagon"]:
            raise ValueError(f"Compiled artifact targets Hexagon {target_arch}; connected device reports {device['hexagon']}")
        optional = {name: core.inbox_path(filename, {ext}) if filename else None for name, filename, ext in (
            ("schematic", spec.schematic, ".bin"), ("trace_dlc", spec.trace_dlc, ".dlc"),
            ("framework_csv", spec.framework_csv, ".csv"),
        )}
        args = SimpleNamespace(model_id=graph.artifact.id, model=core.item(spec.artifact_id, suffixes[artifact["format"]]),
                               input=[f"{name}={path}" for name, path in files.items()], mode=spec.mode,
                               runs=spec.runs, warmup=spec.warmup, native_io=spec.native_io, perf_profile="default",
                               keep_device_files=False, compiled_artifact_id=spec.artifact_id, **optional)
        result = runner.capture(core, args)
        return {"profile": result["profile"], "evidence": result["evidence"]}
    except (OSError, TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        CAPTURE_LOCK.release()
