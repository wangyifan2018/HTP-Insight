"""Stream browser-selected files into a dedicated, relative Inbox batch."""

import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from fastapi import HTTPException, Request

MAX_UPLOAD_SIZE = 2 * 1024 ** 3


async def receive(inbox: Path, batch: str, name: str, request: Request):
    parts = name.split("/")
    if (not re.fullmatch(r"[a-f0-9]{32}", batch) or len(parts) > 12
            or any(not part or part in {".", ".."} or not part.isprintable() or "\\" in part for part in parts)):
        raise HTTPException(400, "Use a relative path within a single upload batch")
    if request.headers.get("content-type") != "application/octet-stream":
        raise HTTPException(415, "Expected a binary file upload")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or not 0 < int(declared) <= MAX_UPLOAD_SIZE):
        raise HTTPException(413, "Each local file must be nonempty and at most 2 GiB")
    relative = PurePosixPath("uploads", batch, *parts)
    target = inbox / relative
    if not target.resolve().is_relative_to(inbox):
        raise HTTPException(400, "Upload path escapes the Inbox")
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            async for block in request.stream():
                size += len(block)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(413, "Local file exceeds 2 GiB")
                stream.write(block)
            if not size or (declared is not None and size != int(declared)):
                raise HTTPException(400, "Upload was empty or incomplete")
            stream.close()
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise HTTPException(409, "This filename is already staged in the upload batch") from exc
        finally:
            temporary.unlink(missing_ok=True)
    return {"filename": relative.as_posix(), "size": size}
