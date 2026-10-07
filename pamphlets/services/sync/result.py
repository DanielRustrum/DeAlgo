"""What a run did, counted."""

from __future__ import annotations

from dataclasses import dataclass, field

# How many items each playlist or channel has taken so far this run.
Tally = dict[int, int]


@dataclass
class SyncResult:
    """What one run did, counted, and the messages for whoever started it."""

    ok: bool = False
    started: bool = True
    forced: bool = False
    channels_checked: int = 0
    channels_waiting: int = 0
    discovered: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    pruned: int = 0
    #: Items put into a repository to wait for a Withdraw box. Counted apart
    #: from `added`: nothing has reached a feed, which is the whole point.
    deposited: int = 0
    #: Items a Withdraw box took back out and sent on.
    withdrawn: int = 0
    quota_spent: int = 0
    stopped_on_quota: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        """Every message, as one line."""
        return " ".join(self.messages)
