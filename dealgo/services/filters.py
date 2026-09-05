"""Per-channel accept/reject rules.

Pure functions: no database, no network, so the decisions are easy to test and
easy to explain back to the user in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    accept: bool
    reason: str | None = None


def validate_pattern(pattern: str | None, label: str) -> None:
    if not pattern:
        return
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{label} is not a valid regular expression: {exc}") from exc


def _matches(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        # A pattern that got past validation somehow should not stall the sync.
        return False


def evaluate(
    *,
    title: str,
    duration_sec: int | None,
    live_state: str | None,
    is_short: bool = False,
    title_include: str | None = None,
    title_exclude: str | None = None,
    min_duration_sec: int | None = None,
    max_duration_sec: int | None = None,
    skip_shorts: bool = True,
    skip_live: bool = True,
    skip_videos: bool = False,
    shorts_max_seconds: int = 60,
) -> Decision:
    """Decide whether one video belongs in the playlist."""
    if title_include and not _matches(title_include, title):
        return Decision(False, f"title does not match include pattern /{title_include}/")
    if title_exclude and _matches(title_exclude, title):
        return Decision(False, f"title matches exclude pattern /{title_exclude}/")

    # Every upload is exactly one of three kinds, and each has its own switch.
    is_broadcast = live_state in {"live", "upcoming"}
    looks_short = is_short or (duration_sec is not None and duration_sec <= shorts_max_seconds)

    if is_broadcast:
        if skip_live:
            return Decision(
                False, "live stream" if live_state == "live" else "scheduled premiere"
            )
    elif looks_short:
        if skip_shorts:
            length = f" ({duration_sec}s)" if duration_sec is not None else ""
            return Decision(False, f"Short{length}")
    elif skip_videos:
        return Decision(False, "regular video")

    if duration_sec is not None:
        if min_duration_sec and duration_sec < min_duration_sec:
            return Decision(False, f"shorter than {min_duration_sec}s ({duration_sec}s)")
        if max_duration_sec and duration_sec > max_duration_sec:
            return Decision(False, f"longer than {max_duration_sec}s ({duration_sec}s)")

    return Decision(True)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
