"""The record of what a run did, line by line.

The counts on a finished run say how much happened. They do not say what, or
in what order, or which of the several things that can go quiet went quiet —
and those are the questions asked of a run that did not do what was expected.

Written as the run goes rather than summarised at the end, so a run still in
flight can be read, and one that fell over says how far it got.

Kept in the database rather than in the process, unlike ``RunProgress``: the
whole point is to be able to look at a run that happened while nobody was
watching. Old runs are pruned, because a log nobody trims is a log that
eventually is the database.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import RunEvent, SyncRun
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

Level = Literal["info", "warn", "bad"]

#: How many runs keep their lines. The counts on a run are cheap and are kept
#: for ever; the lines are the bulky part, and nobody reads the detail of a
#: run from three weeks ago.
RUNS_WITH_DETAIL = 40

#: Most lines one run may write. A run over a hundred channels with a filter
#: on each could otherwise write tens of thousands, and a log that costs more
#: than the work it describes is not worth having.
MOST_LINES = 600


class Pen:
    """Writes the log of one run.

    Holds the run's id and its own counter rather than asking the database
    where it got to: a run writes many lines and a count(*) per line would be
    the most expensive thing about logging.
    """

    def __init__(self, session: Session, run_pk: int, owner: OwnerId = None):
        self.session = session
        self.run_pk = run_pk
        self.owner = owner
        self.seq = 0
        self.stage = "starting"
        self._full = False

    def at(self, stage: str) -> None:
        """Say which part of the run the lines after this belong to."""
        self.stage = stage

    def write(
        self, message: str, *, about: str | None = None, level: Level = "info"
    ) -> None:
        if self._full:
            return
        self.seq += 1
        if self.seq >= MOST_LINES:
            # The last line a run may write is the one saying it wrote too
            # many, so the cap is the whole of what a run can cost.
            self._full = True
            message = (
                "The rest of this run's lines were not kept. "
                "The counts above cover the whole of it."
            )
            about, level = None, "warn"
        self.session.add(
            RunEvent(
                owner_pk=self.owner,
                run_pk=self.run_pk,
                seq=self.seq,
                level=level,
                stage=self.stage,
                about=(about or None) and about[:200],
                message=message,
            )
        )

    def warn(self, message: str, *, about: str | None = None) -> None:
        self.write(message, about=about, level="warn")

    def bad(self, message: str, *, about: str | None = None) -> None:
        self.write(message, about=about, level="bad")


class Quiet(Pen):
    """A pen that writes nothing.

    So that a code path with no run behind it — a trial asked of one box, a
    call from a test — needs no "if the log exists" at every line.
    """

    def __init__(self) -> None:  # noqa: D107 - deliberately takes nothing
        self.seq = 0
        self.stage = "starting"
        self._full = True

    def write(
        self, message: str, *, about: str | None = None, level: Level = "info"
    ) -> None:
        return


def prune(session: Session, owner: OwnerId = None) -> int:
    """Drop the detail of runs older than the ones worth reading.

    The runs themselves stay: their counts are one row each and are the record
    of what this install has done. It is the lines that are dropped.
    """
    keeping = list(
        session.scalars(
            owned(select(SyncRun.id), SyncRun, owner)
            .order_by(SyncRun.id.desc())
            .limit(RUNS_WITH_DETAIL)
        )
    )
    if not keeping:
        return 0
    # Scoped by owner on the events themselves: one account pruning its own
    # history must not touch another's.
    stale = list(
        session.scalars(
            owned(select(RunEvent.id), RunEvent, owner).where(RunEvent.run_pk.not_in(keeping))
        )
    )
    if stale:
        session.execute(delete(RunEvent).where(RunEvent.id.in_(stale)))
    return len(stale)


def lines_for(session: Session, run_pk: int, owner: OwnerId = None) -> list[RunEvent]:
    return list(
        session.scalars(
            owned(select(RunEvent), RunEvent, owner)
            .where(RunEvent.run_pk == run_pk)
            .order_by(RunEvent.seq)
        )
    )


def counted(session: Session, owner: OwnerId = None) -> dict[int, int]:
    """How many lines each run has, so a list can say which are worth opening."""
    rows = session.execute(
        owned(select(RunEvent.run_pk, func.count(RunEvent.id)), RunEvent, owner).group_by(
            RunEvent.run_pk
        )
    )
    return {run_pk: count for run_pk, count in rows}
