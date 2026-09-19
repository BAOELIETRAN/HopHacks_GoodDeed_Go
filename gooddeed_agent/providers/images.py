"""Photo handling shared by every LLM provider.

Callers describe a photo (URL, path, bytes, base64, ``data:`` URL) and get back
a provider-neutral image content block. The provider translates that block into
its own request format (see ``openai_llm.to_openai_content``), so sniffing the
media type and rejecting unsupported formats such as HEIC stays in one place.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Magic-byte sniffing, because uploads routinely arrive with the wrong extension.
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def build_image_block(photo: str | bytes | Path) -> dict[str, Any]:
    """Turn a photo reference into an image content block.

    Accepts an ``http(s)`` URL (passed through by reference), a filesystem
    path, a ``data:`` URL, a base64 string, or raw bytes.
    """
    if isinstance(photo, Path):
        return _image_from_bytes(photo.read_bytes())

    if isinstance(photo, bytes):
        return _image_from_bytes(photo)

    if isinstance(photo, str):
        value = photo.strip()
        if not value:
            # Path("") resolves to the current directory, so without this the
            # failure surfaced as "Is a directory: '.'" -- baffling for a
            # user who simply hadn't attached a photo.
            raise ValueError("No photo was provided")
        if value.startswith(("http://", "https://")):
            return {"type": "image", "source": {"type": "url", "url": value}}
        if value.startswith("data:"):
            header, _, payload = value.partition(",")
            media_type = header[5:].split(";")[0] or "image/jpeg"
            return _image_block(media_type, payload)
        path = Path(value)
        if path.exists():
            return _image_from_bytes(path.read_bytes())
        # Last resort: assume it is already base64-encoded image data.
        try:
            return _image_from_bytes(base64.b64decode(value, validate=True))
        except Exception as exc:
            raise ValueError(
                "photo must be a URL, a readable file path, raw bytes, or base64 image data"
            ) from exc

    raise TypeError(f"Unsupported photo type: {type(photo).__name__}")


def _image_from_bytes(raw: bytes) -> dict[str, Any]:
    media_type = _sniff_media_type(raw)
    return _image_block(media_type, base64.standard_b64encode(raw).decode("utf-8"))


def _image_block(media_type: str, b64_data: str) -> dict[str, Any]:
    if media_type not in _SUPPORTED_IMAGE_TYPES:
        media_type = "image/jpeg"
    # The API rejects base64 containing newlines.
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64_data.replace("\n", "")},
    }


def _sniff_media_type(raw: bytes) -> str:
    for prefix, media_type in _MAGIC:
        if raw.startswith(prefix):
            return media_type
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    # iPhones shoot HEIC by default. The API rejects it, and relabelling it
    # as JPEG produces an opaque server-side error, so name the problem.
    if raw[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1"):
        raise ValueError(
            "HEIC photos aren't supported yet. In iOS, Settings > Camera > "
            "Formats > Most Compatible saves photos as JPEG."
        )
    return "image/jpeg"
