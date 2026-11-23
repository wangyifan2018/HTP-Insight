from concurrent.futures import ThreadPoolExecutor
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from htp_insight.core import atomic_write

RELEASE = "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/mobilenet_v2/releases/v0.64.0"


def fetch(url: str, destination: Path):
    try:
        with ZipFile(destination) as package:
            if package.testzip() is None:
                return
    except (FileNotFoundError, BadZipFile):
        pass

    with urlopen(Request(url, method="HEAD"), timeout=15) as response:
        length = int(response.headers["Content-Length"])
    chunk = 1024 * 1024
    ranges = [(start, min(start + chunk, length) - 1) for start in range(0, length, chunk)]

    def fetch_range(bounds):
        start, end = bounds
        part = destination.parent / f".{destination.name}.{length}.{start}"
        if part.is_file() and part.stat().st_size == end - start + 1:
            return part.read_bytes()
        for attempt in range(3):
            try:
                request = Request(url, headers={"Range": f"bytes={start}-{end}"})
                with urlopen(request, timeout=25) as response:
                    content = response.read()
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{length}":
                        raise ValueError("Unexpected Content-Range")
                if len(content) != end - start + 1:
                    raise ValueError("Incomplete range")
                atomic_write(part, content)
                return content
            except (OSError, IncompleteRead, ValueError):
                if attempt == 2:
                    raise

    with ThreadPoolExecutor(max_workers=10) as workers:
        data = b"".join(workers.map(fetch_range, ranges))
    with ZipFile(BytesIO(data)) as package:
        damaged = package.testzip()
        if damaged:
            raise ValueError(f"Archive CRC check failed for {damaged}")
    atomic_write(destination, data)
    for start, _ in ranges:
        (destination.parent / f".{destination.name}.{length}.{start}").unlink(missing_ok=True)
