"""Per-channel accept/reject rules.

Pure functions: no database, no network, so the decisions are easy to test and
easy to explain back to the user in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    """Whether an item is accepted and, if not, why."""

    accept: bool
    reason: str | None = None


def validate_pattern(pattern: str | None, label: str) -> None:
    """Raise `ValueError` if a pattern is not a valid regular expression."""
    if not pattern:
        return
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{label} is not a valid regular expression: {exc}") from exc


def _matches(pattern: str, text: str) -> bool:
    """Whether a pattern matches, ignoring case; False for a broken pattern."""
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        # A pattern that got past validation somehow should not stall the sync.
        return False


def evaluate(
    *,
    title: str,
    duration_sec: int | None,
    left_out: str | None = None,
    title_include: str | None = None,
    title_exclude: str | None = None,
    min_duration_sec: int | None = None,
    max_duration_sec: int | None = None,
) -> Decision:
    """Decide whether one item belongs in the feed.

    `left_out` is the label of the kind of content it is, when its source
    leaves that kind out — which kind it is was its plugin's to say, and
    whether that kind is wanted the source's.
    """
    if title_include and not _matches(title_include, title):
        return Decision(False, f"title does not match include pattern /{title_include}/")
    if title_exclude and _matches(title_exclude, title):
        return Decision(False, f"title matches exclude pattern /{title_exclude}/")

    if left_out:
        return Decision(False, left_out)

    if duration_sec is not None:
        if min_duration_sec and duration_sec < min_duration_sec:
            return Decision(False, f"shorter than {min_duration_sec}s ({duration_sec}s)")
        if max_duration_sec and duration_sec > max_duration_sec:
            return Decision(False, f"longer than {max_duration_sec}s ({duration_sec}s)")

    return Decision(True)


def format_duration(seconds: int | None) -> str:
    """Seconds as `m:ss` or `h:mm:ss`; a dash when unknown."""
    if seconds is None:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def evaluate_post(
    *,
    text: str,
    left_out: str | None = None,
    title_include: str | None = None,
    title_exclude: str | None = None,
) -> Decision:
    """Decide whether one item that is only words belongs in a feed.

    A post or a link has no duration, so only the kind and the text
    patterns apply. The patterns are matched against the whole text rather
    than its first line: a title here is often an excerpt De-Algo made up,
    and filtering on it would be filtering on our own truncation.
    """
    if left_out:
        return Decision(False, left_out)
    if title_include and not _matches(title_include, text):
        return Decision(False, f"post does not match include pattern /{title_include}/")
    if title_exclude and _matches(title_exclude, text):
        return Decision(False, f"post matches exclude pattern /{title_exclude}/")
    return Decision(True)
