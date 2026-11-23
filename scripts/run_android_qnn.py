"""Run a bounded QAIRT capture over ADB and import it into HTP Insight."""
import argparse
import os
import shutil
from pathlib import Path

from htp_insight.android import AndroidRunner, MODES
from htp_insight.core import Core, encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    fallback = Path.home() / "Library/Android/sdk/platform-tools/adb"
    parser.add_argument("--adb", default=os.getenv("ADB_BIN") or shutil.which("adb") or str(fallback))
    parser.add_argument("--serial", help="ADB serial when several devices are connected")
    parser.add_argument("--sdk", type=Path, default=os.getenv("QAIRT_SDK_ROOT"),
                        required=not bool(os.getenv("QAIRT_SDK_ROOT")), help="QAIRT 2.50 SDK directory")
    parser.add_argument("--htp-arch", required=True, help="Verified Hexagon architecture for the device")
    parser.add_argument("--model-id", required=True, help="Registered source ONNX model ID")
    parser.add_argument("--model", type=Path, required=True, help="Target DLC or HTP Context Binary")
    parser.add_argument("--input", required=True, action="append", help="tensor_name=raw_file")
    parser.add_argument("--mode", choices=MODES, default="basic")
    parser.add_argument("--runs", type=int, default=110)
    parser.add_argument("--warmup", type=int, default=10, help="Initial samples to discard from CSV latency calculations")
    parser.add_argument("--perf-profile", default="default")
    parser.add_argument("--native-io", action="store_true", help="Read/write native tensor encodings")
    parser.add_argument("--schematic", type=Path)
    parser.add_argument("--trace-dlc", type=Path)
    parser.add_argument("--framework-csv", type=Path)
    parser.add_argument("--timeout", type=int, default=120, help="Per ADB operation timeout in seconds")
    parser.add_argument("--keep-device-files", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("Timeout must be positive")
    try:
        runner = AndroidRunner(args.adb, args.serial, args.sdk, args.htp_arch, args.timeout)
        print(encode(runner.capture(Core(), args)).decode())
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
