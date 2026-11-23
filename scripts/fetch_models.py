"""Fetch Qualcomm public ONNX archives and verify ZIP integrity."""
import argparse

from htp_insight.core import Core
from examples.downloads import RELEASE, fetch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("precision", nargs="*", choices=["float", "w8a8", "w8a16"])
    args = parser.parse_args()
    directory = Core().root / "downloads"
    for precision in args.precision or ["float", "w8a8", "w8a16"]:
        filename = f"{precision}.zip"
        fetch(f"{RELEASE}/mobilenet_v2-onnx-{precision}.zip", directory / filename)
        print(directory / filename, flush=True)


if __name__ == "__main__":
    main()
