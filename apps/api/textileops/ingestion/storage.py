"""Safe storage of uploaded files.

Uploads are untrusted in every sense: the bytes, the declared content type, and
above all the filename. The rules here:

* The stored name is derived from a UUID, never from user input. A filename of
  ``../../etc/passwd`` or ``C:\\windows\\x`` cannot escape the upload root
  because it is never used as a path component.
* The resolved path is checked to be inside the upload root before writing.
* Extension and size are validated against configuration before anything is
  written to disk.
* Content is hashed so re-forwarded duplicates are detectable.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from textileops.core.config import settings
from textileops.core.errors import ValidationError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_DISPLAY_NAME = 255


@dataclass(frozen=True)
class StoredFile:
    stored_path: str
    sha256: str
    byte_size: int
    display_name: str


def upload_root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitise_display_name(filename: str) -> str:
    """A name safe to show and to log. Never used to build a path."""
    base = os.path.basename(filename.replace("\\", "/")).strip() or "upload"
    cleaned = _SAFE_NAME.sub("_", base)[:MAX_DISPLAY_NAME]
    return cleaned.lstrip(".") or "upload"


def validate_extension(filename: str) -> str:
    suffix = Path(sanitise_display_name(filename)).suffix.lower()
    allowed = [ext.lower() for ext in settings.allowed_upload_extensions]
    if suffix not in allowed:
        raise ValidationError(
            f"Files of type {suffix or '(none)'} are not accepted. "
            f"Allowed: {', '.join(allowed)}.",
            details={"extension": suffix, "allowed": allowed},
        )
    return suffix


def store(content: bytes, *, filename: str) -> StoredFile:
    if len(content) == 0:
        raise ValidationError("The uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise ValidationError(
            f"File is {len(content):,} bytes; the limit is "
            f"{settings.max_upload_bytes:,} bytes.",
            details={"size": len(content), "limit": settings.max_upload_bytes},
        )
    suffix = validate_extension(filename)
    display_name = sanitise_display_name(filename)

    root = upload_root()
    # The on-disk name comes from a UUID, so nothing user-supplied is a path part.
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = (root / stored_name).resolve()
    if root not in target.parents:
        raise ValidationError("Refusing to write outside the upload directory.")

    target.write_bytes(content)
    os.chmod(target, 0o600)
    return StoredFile(
        stored_path=stored_name,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        display_name=display_name,
    )


def read(stored_path: str) -> bytes:
    """Read a previously stored file, refusing any traversal attempt."""
    if "/" in stored_path or "\\" in stored_path or stored_path.startswith("."):
        raise ValidationError("Invalid stored path.")
    root = upload_root()
    target = (root / stored_path).resolve()
    if root not in target.parents:
        raise ValidationError("Invalid stored path.")
    if not target.is_file():
        # Expected on a deployment without persistent storage (the hosted demo):
        # files live until the service restarts. What was extracted from the
        # file is in the database and is unaffected.
        raise ValidationError(
            "The original file is no longer stored on this server, so it cannot be "
            "read again. What was already extracted from it is kept."
        )
    return target.read_bytes()


def content_hash(text: str) -> str:
    """Hash of normalised text — used to spot the same message forwarded twice."""
    normalised = " ".join(text.split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


#: PostgreSQL ``text`` cannot hold a NUL byte. Nothing else in the Unicode
#: range is rejected, so this is the whole of what must be removed.
_UNSTORABLE = "\x00"


def sanitise_text(value: str) -> tuple[str, int]:
    """Strip bytes PostgreSQL refuses to store, reporting how many went.

    A NUL byte is ordinary in text extracted from a PDF and in exports from
    older Windows systems. Passing one through to the insert raises
    ``psycopg.DataError``, which aborts the whole transaction — so a single
    malformed supplier email took down everything else in the same request,
    returned a 500 rather than a refusal, and in the worker retried forever
    against the identical payload until the job died.

    The count is returned rather than discarded because invariant 11 says the
    stored document is the evidence: if we had to alter it, that has to be on
    the record instead of being done quietly.
    """
    if _UNSTORABLE not in value:
        return value, 0
    return value.replace(_UNSTORABLE, ""), value.count(_UNSTORABLE)
