"""Exporting everything De-Algo knows as portable JSON.

Rows reference each other by YouTube's own ids — channel ids and playlist ids —
rather than by database primary keys, so the file means the same thing on a
machine whose tables were numbered differently.

No credentials are exported at all — not the OAuth grant, not the Google client
id and secret. A backup file lives in a Downloads folder for years, and both are
re-enterable in a minute. Nor is the video history: this is the shape of the
setup, not a record of everything it has ever seen.

Reading is deliberately more forgiving than writing, so files written by earlier
versions — which did carry history, and optionally the client id — still restore.
"""

from __future__ import annotations

from .export import FORMAT_VERSION, _stamp, build_export, filename
from .restore import RestoreError, restore

__all__ = [
    "FORMAT_VERSION",
    "RestoreError",
    "_stamp",
    "build_export",
    "filename",
    "restore",
]
