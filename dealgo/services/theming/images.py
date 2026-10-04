"""A person's own pictures in their theme: a background, and their own plants.

An image is the one thing in a theme that is not a value from a list, so it
is checked hardest. A picture is accepted only if its first bytes say it is a
PNG, JPEG, GIF or WebP, and it is kept and served as exactly that. An SVG is a
document that could carry script, so it is not kept as sent: it is parsed and
rebuilt from an allow-list of drawing elements and attributes. Scripts, event
handlers, styles, embedded HTML and anything that points outside the drawing
are left behind. It is served with a policy that would stop it running even
if it held something, and only ever to the account it belongs to.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

#: Where a picture can go, and what each is called on the page.
SLOTS: dict[str, str] = {
    "background": "Background",
    "edge-left": "Left edge",
    "edge-right": "Right edge",
    "heading": "Beside headings",
}

#: Pictures that belong to the account rather than its theme.
ACCOUNT_SLOTS: dict[str, str] = {
    "avatar": "Account",
}

#: Every place a picture can be kept, and so served from.
ALL_SLOTS: dict[str, str] = {**SLOTS, **ACCOUNT_SLOTS}

#: The slots that make up an account's own plants.
DRAWING_SLOTS = ("edge-left", "edge-right", "heading")

MAX_RASTER = 3 * 1024 * 1024
MAX_SVG = 512 * 1024

SVG_TYPE = "image/svg+xml"

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

#: What a drawing may be made of. Nothing that runs, loads, or holds HTML:
#: no script, style, foreignObject, image, iframe, animate or set.
_ELEMENTS = frozenset({
    "svg", "g", "defs", "symbol", "use", "title", "desc",
    "path", "circle", "ellipse", "rect", "line", "polyline", "polygon",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern",
    "text", "tspan",
})

#: What those elements may say about themselves. Presentation only.
_ATTRIBUTES = frozenset({
    "id", "class", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "fx", "fy", "d", "points", "pathLength",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity",
    "stroke-miterlimit", "opacity", "transform", "gradientUnits", "gradientTransform",
    "spreadMethod", "offset", "stop-color", "stop-opacity", "clip-path", "clip-rule",
    "clipPathUnits", "mask", "maskUnits", "maskContentUnits", "preserveAspectRatio",
    "patternUnits", "patternContentUnits", "patternTransform", "font-family",
    "font-size", "font-weight", "font-style", "text-anchor", "dominant-baseline",
    "letter-spacing", "display", "visibility", "color", "version", "href",
})

#: A value that reaches outside the drawing, or into script.
_REACHES_OUT = re.compile(r"url\(\s*['\"]?(?!#)|javascript:|data:|expression\(|@import", re.I)


class ImageError(ValueError):
    """A picture that cannot be used, and why, in words."""


@dataclass(frozen=True)
class Picture:
    """A picture as kept: what it is, and the bytes to serve."""

    media_type: str
    data: bytes

    @property
    def version(self) -> str:
        """A short fingerprint, for an address that changes when the picture does."""
        return hashlib.sha256(self.data).hexdigest()[:12]


def accept(data: bytes) -> Picture:
    """A picture someone sent, checked; ImageError if it cannot be used."""
    if not data:
        raise ImageError("That file is empty.")
    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return _raster(data, media_type)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _raster(data, "image/webp")
    head = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<?xml", b"<svg", b"<!--")):
        return Picture(SVG_TYPE, clean_svg(data))
    raise ImageError("That is not a PNG, JPEG, GIF, WebP or SVG picture.")


def _raster(data: bytes, media_type: str) -> Picture:
    if len(data) > MAX_RASTER:
        raise ImageError(f"Pictures can be up to {MAX_RASTER // (1024 * 1024)} MB.")
    return Picture(media_type, data)


def _local(name: str) -> tuple[str, str]:
    """`{namespace}name` as its namespace and name."""
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return namespace, local
    return "", name


def clean_svg(data: bytes) -> bytes:
    """An SVG rebuilt from what a drawing may hold, or ImageError."""
    if len(data) > MAX_SVG:
        raise ImageError(f"An SVG can be up to {MAX_SVG // 1024} KB.")
    lowered = data.lower()
    # Entities are how an XML file grows without limit or reads files from
    # the server. A drawing has no use for either.
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ImageError("That SVG declares a DOCTYPE or entities, which drawings here cannot.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ImageError("That SVG is not readable.") from None
    namespace, local = _local(root.tag)
    if local != "svg" or namespace not in ("", _SVG_NS):
        raise ImageError("That file is not an SVG drawing.")

    def scrub(element: ET.Element) -> None:
        for child in list(element):
            child_ns, child_name = _local(child.tag) if isinstance(child.tag, str) else ("", "")
            if child_ns not in ("", _SVG_NS) or child_name not in _ELEMENTS:
                element.remove(child)
                continue
            child.tag = child_name
            scrub(child)
        for name in list(element.attrib):
            value = element.attrib.pop(name)
            attr_ns, attr_name = _local(name)
            if attr_ns not in ("", _XLINK_NS) or attr_name not in _ATTRIBUTES:
                continue
            if attr_name == "href" and not value.startswith("#"):
                continue
            if _REACHES_OUT.search(value):
                continue
            element.set(attr_name, value)

    root.tag = "svg"
    scrub(root)
    root.set("xmlns", _SVG_NS)
    cleaned: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return cleaned
