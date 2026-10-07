"""Repository and tag names, as they are filed."""

from __future__ import annotations


def store_name(raw: str | None) -> str:
    """A repository name as it is filed: trimmed, squeezed, lowercased.

    So "News", "news" and " news " are one pile rather than three that look
    alike on the canvas. Said in one place because both ends have to agree on
    it — a Deposit and a Withdraw that disagreed would be two boxes that look
    joined and are not.
    """
    return " ".join((raw or "").split()).lower()[:60]


def tag_name(raw: str | None) -> str:
    """A tag as it is filed: trimmed, squeezed, lowercased.

    The same treatment a repository name gets, and for the same reason — a
    Tag box and a Filter box that disagreed about capitals would be two
    boxes that look joined up and are not.
    """
    return " ".join((raw or "").split()).lower()[:40]


def tag_names(raw: str | None) -> list[str]:
    """A comma-separated list of tags, each filed as `tag_name` files one,
    once each and in the order given."""
    said: list[str] = []
    for part in (raw or "").split(","):
        name = tag_name(part)
        if name and name not in said:
            said.append(name)
    return said
