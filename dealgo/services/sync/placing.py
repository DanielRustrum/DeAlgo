"""Putting one item into every feed its paths say it belongs in, and posts into theirs."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...models import (
    Channel,
    Placement,
    Playlist,
    Settings,
    Video,
    utcnow,
)
from ...plugins.publisher import Publisher, PublishError, VideoDetails, cost_of, names
from .. import graph, quota, runlog
from ..scope import OwnerId
from .deciding import attribute, decide, reject
from .expiry import stamp_expiry
from .placements import MAX_INSERT_ATTEMPTS, defer, local_item_id, still_queued
from .progress import note_left
from .repositories import deposit
from .result import SyncResult, Tally
from .stamps import apply_stamps

log = logging.getLogger(__name__)


@dataclass
class _Sorted:
    """Where one item's paths sent it."""

    #: The feeds that take it, and the paths that lead into them.
    allowed: list[Playlist] = field(default_factory=list)
    taking: list[graph.Route] = field(default_factory=list)
    #: The paths that end in a repository.
    stored: list[graph.Route] = field(default_factory=list)
    #: Why the others said no, in the order they said it.
    refusals: list[str] = field(default_factory=list)


@dataclass
class _Outcome:
    """What placing one item into its feeds came to."""

    landed: bool = False
    deferred: int = 0
    errors: int = 0


class Placing:
    """Putting each waiting item into every feed its paths say it belongs in.

    One per run. It carries what the run has done so far — how many each feed
    and each source has taken, what each published playlist already holds, and
    whether the quota has run out — so every item is placed knowing what the
    ones before it did.
    """

    def __init__(
        self,
        session: Session,
        client: Publisher,
        settings: Settings,
        result: SyncResult,
        owner: OwnerId,
        say: runlog.Pen | runlog.Quiet,
    ) -> None:
        """Ready to place items for one run, with nothing counted yet."""
        self.session = session
        self.client = client
        self.settings = settings
        self.result = result
        self.owner = owner
        self.say = say
        self.added_per_playlist: Tally = {}
        self.added_per_channel: Tally = {}
        #: Set when the service's allowance is gone, which ends the filing for this run.
        self.quota_spent = False
        # Each target playlist is read once, so videos already in it (added by
        # hand, or by a previous install) are adopted rather than inserted twice.
        self._contents: dict[int, dict[str, str]] = {}
        self._unreadable: set[int] = set()

    # -- one item ----------------------------------------------------------

    def file(self, video: Video, detail: VideoDetails | None, paths: list[graph.Route]) -> None:
        """Decide where one item goes, mark it, and put it there."""
        channel = video.channel
        if detail is None and self.client.can_read and video.kind == "video":
            reject(video, self.result, "video is unavailable (private, deleted, or region blocked)")
            return
        if not paths:
            # Stays pending: wiring it to a feed later picks it up.
            return

        self._note_what_its_source_thinks(video, detail, paths)
        went = self._sort(video, detail, paths)

        # What the boxes on the paths that took it said about it. Done for
        # the item as a whole rather than per feed: a tag is a property of
        # the thing, and how long you get with it is a property of reading
        # it, neither of which is a fact about one feed.
        apply_stamps(self.session, video, went.taking + went.stored, self.owner)

        if not went.allowed and not went.stored:
            # Every path said no; the first reason is the one worth showing.
            why = went.refusals[0] if went.refusals else "filtered out"
            reject(video, self.result, why)
            self.say.write(f"held back — {why}", about=video.title or video.video_id)
            return

        # Into the repositories first: nothing is sent anywhere for these, so
        # a quota stop partway through the feeds cannot lose them.
        held = deposit(self.session, video, went.stored, self.owner)
        if held:
            self.result.deposited += held
        self._say_where(video, went)

        if video.is_post:
            place_locally(
                self.session, video, channel, self.result,
                self.added_per_playlist, self.added_per_channel, went.allowed,
            )
            return

        # De-duplicated, and in fill order: two paths may end at one feed.
        targets = sorted({p.id: p for p in went.allowed}.values(), key=lambda p: (p.priority, p.id))

        cap = channel.max_per_run or 0
        if cap and self.added_per_channel.get(channel.id, 0) >= cap:
            return

        outcome = self._place(video, targets)
        stamp_expiry(self.session, video, went.taking)
        self.session.flush()
        self._settle(video, outcome, held=held, allowed=went.allowed)
        self.session.flush()

    def _note_what_its_source_thinks(
        self, video: Video, detail: VideoDetails | None, paths: list[graph.Route]
    ) -> None:
        """What the channel itself thinks of this one, before any filter box
        has a say. That is what "left the channel" means, and it is the
        difference between a quiet channel and one turning its own uploads
        away."""
        own_rules = graph.Route(
            channel=video.channel,
            playlist=paths[0].playlist,
            store=paths[0].store,
            filters=[],
        )
        if decide(video, own_rules, detail, self.settings).accept:
            note_left(video.channel.id)

    def _sort(self, video: Video, detail: VideoDetails | None, paths: list[graph.Route]) -> _Sorted:
        """One decision per path, not one per video: the same channel can reach
        two feeds through filters that disagree, and a video turned away at
        one of them still belongs in the other."""
        went = _Sorted()
        for path in paths:
            decision = decide(video, path, detail, self.settings)
            attribute(video, path, detail, self.settings)
            if not decision.accept:
                if decision.reason:
                    went.refusals.append(decision.reason)
            elif path.deposits:
                went.stored.append(path)
            elif path.playlist is not None:
                went.allowed.append(path.playlist)
                went.taking.append(path)
        return went

    def _say_where(self, video: Video, went: _Sorted) -> None:
        """Write to the run log which feeds and repositories an item goes to."""
        going = sorted(p.title for p in went.allowed)
        waiting = sorted({path.store for path in went.stored})
        self.say.write(
            "goes to " + ", ".join(going + [f"the {name} repository" for name in waiting]),
            about=video.title or video.video_id,
        )

    def _settle(self, video: Video, outcome: _Outcome, *, held: int, allowed: list[Playlist]) -> None:
        """What the item's status is now, from how its placements went."""
        if outcome.landed or (held and not allowed):
            video.status = "added"
            video.reason = None
            video.processed_at = utcnow()
            channel_pk = video.channel.id
            self.added_per_channel[channel_pk] = self.added_per_channel.get(channel_pk, 0) + 1
        elif outcome.deferred and not outcome.errors:
            # Held back by a cap or by quota, not broken: it stays pending and
            # the placements it owes are filled on a later run.
            pass
        else:
            video.attempts += 1
            failures = [p.error for p in video.placements if p.error]
            video.reason = failures[0] if failures else video.reason
            if video.attempts >= MAX_INSERT_ATTEMPTS:
                video.status = "failed"
                video.processed_at = utcnow()
                self.result.failed += 1

    # -- one item into its feeds -------------------------------------------

    def _place(self, video: Video, targets: list[Playlist]) -> _Outcome:
        """Into each feed in turn, until they are done or the quota is."""
        placed = {p.playlist_pk: p for p in video.placements}
        outcome = _Outcome()
        for playlist in targets:
            if playlist.id in placed:
                outcome.landed = outcome.landed or placed[playlist.id].playlist_item_id is not None
                continue
            if playlist.is_generic or not self.client.has_write_access:
                self._place_here(video, playlist, placed, outcome)
            elif not self._place_published(video, playlist, targets, placed, outcome):
                break  # the quota is spent
        return outcome

    def _place_here(
        self, video: Video, playlist: Playlist, placed: dict[int, Placement], outcome: _Outcome
    ) -> None:
        """No API call, no quota: the placement is the whole act. With no
        account that goes for every feed, so the app keeps working and the
        videos are readable in De-Algo either way."""
        if self._full(playlist):
            self._owe(video, playlist, outcome)
            return
        placement = Placement(
            video_pk=video.id,
            playlist_pk=playlist.id,
            playlist_item_id=local_item_id(video, playlist),
            added_at=utcnow(),
        )
        self.session.add(placement)
        placed[playlist.id] = placement
        self._count(playlist)
        outcome.landed = True
        self.session.flush()

    def _place_published(
        self,
        video: Video,
        playlist: Playlist,
        targets: list[Playlist],
        placed: dict[int, Placement],
        outcome: _Outcome,
    ) -> bool:
        """Into a published playlist. False when the allowance has run out."""
        if self._full(playlist):
            # Record what this playlist still owes so the next run finishes
            # it, exactly as a quota stop does.
            self._owe(video, playlist, outcome)
            return True

        contents = self._contents_of(playlist)
        if contents is None:
            return True

        if video.video_id in contents:
            self.session.add(
                Placement(
                    video_pk=video.id,
                    playlist_pk=playlist.id,
                    playlist_item_id=contents[video.video_id],
                    added_at=utcnow(),
                    removal_reason=None,
                )
            )
            outcome.landed = True
            return True

        if not quota.can_afford(self.session, cost_of("add")):
            # Stop cleanly on our own ledger rather than being refused, and
            # leave a marker for every playlist this video still owes so the
            # next run finishes the job instead of forgetting it.
            outcome.deferred += defer(self.session, video, targets, placed)
            self._stop_on_quota(
                f"{names().publisher}'s allowance is spent today; {still_queued(self.session)} video(s) wait for the "
                f"reset {quota.describe_reset()}."
            )
            log.info("insert budget reached, pausing until quota resets")
            return False

        try:
            item_id = self.client.insert_playlist_item(playlist.playlist_id, video.video_id)
        except PublishError as exc:
            if exc.is_quota_error:
                quota.mark_exhausted(self.session)
                outcome.deferred += defer(self.session, video, targets, placed)
                self._stop_on_quota(
                    f"{names().publisher} refused further writes: today's allowance is spent. Queued items "
                    f"resume after the reset {quota.describe_reset()}."
                )
                log.warning("quota exhausted, stopping insert phase")
                return False
            outcome.errors += 1
            self.session.add(
                Placement(video_pk=video.id, playlist_pk=playlist.id, attempts=1, error=str(exc))
            )
            log.warning("insert failed for %s into %s: %s", video.video_id, playlist.title, exc)
            return True

        placement = Placement(
            video_pk=video.id,
            playlist_pk=playlist.id,
            playlist_item_id=item_id,
            added_at=utcnow(),
        )
        self.session.add(placement)
        placed[playlist.id] = placement
        contents[video.video_id] = item_id
        self._count(playlist)
        outcome.landed = True
        return True

    # -- the run's own bookkeeping -----------------------------------------

    def _full(self, playlist: Playlist) -> bool:
        """Whether this feed has taken as many as it takes in one run."""
        cap = playlist.max_per_run or 0
        return bool(cap) and self.added_per_playlist.get(playlist.id, 0) >= cap

    def _owe(self, video: Video, playlist: Playlist, outcome: _Outcome) -> None:
        """A placement with no item yet: the next run fills it."""
        self.session.add(Placement(video_pk=video.id, playlist_pk=playlist.id))
        outcome.deferred += 1
        self.session.flush()

    def _count(self, playlist: Playlist) -> None:
        """Count one item placed into a feed."""
        self.added_per_playlist[playlist.id] = self.added_per_playlist.get(playlist.id, 0) + 1
        self.result.added += 1

    def _stop_on_quota(self, message: str) -> None:
        """Note that the quota ran out, with why, which ends the filing."""
        self.result.stopped_on_quota = True
        self.result.messages.append(message)
        self.quota_spent = True

    def _contents_of(self, playlist: Playlist) -> dict[str, str] | None:
        """What a published playlist already holds, read once per run."""
        if playlist.is_generic:
            return {}  # nothing outside De-Algo to reconcile against
        if playlist.id in self._contents:
            return self._contents[playlist.id]
        if playlist.id in self._unreadable:
            return None
        try:
            items = self.client.playlist_items(playlist.playlist_id)
        except PublishError as exc:
            self._unreadable.add(playlist.id)
            playlist.last_error = str(exc)
            self.result.messages.append(f"Could not read {playlist.title!r}: {exc}")
            return None
        playlist.last_error = None
        self._contents[playlist.id] = {item.video_id: item.item_id for item in items}
        return self._contents[playlist.id]


def place_locally(
    session: Session,
    video: Video,
    channel: Channel,
    result: SyncResult,
    added_per_playlist: Tally,
    added_per_channel: Tally,
    targets: Sequence[Playlist] | None = None,
) -> None:
    """Put a community post into each of its channel's feeds.

    Posts never reach the service — there is no playlist that takes them — so this
    is the whole act: no API call, no quota, no deferral. What is left over
    after a cap is simply picked up by the next run, like anything else.
    """
    reachable = list(targets) if targets is not None else channel.targets
    ordered = sorted({p.id: p for p in reachable}.values(), key=lambda p: (p.priority, p.id))
    if not ordered:
        return  # stays pending until the channel is wired to a feed

    cap = channel.max_per_run or 0
    if cap and added_per_channel.get(channel.id, 0) >= cap:
        return

    placed = {p.playlist_pk for p in video.placements}
    landed = False
    for playlist in ordered:
        if playlist.id in placed:
            continue
        limit = playlist.max_per_run or 0
        if limit and added_per_playlist.get(playlist.id, 0) >= limit:
            continue
        session.add(
            Placement(
                video_pk=video.id,
                playlist_pk=playlist.id,
                playlist_item_id=local_item_id(video, playlist),
                added_at=utcnow(),
            )
        )
        added_per_playlist[playlist.id] = added_per_playlist.get(playlist.id, 0) + 1
        landed = True
        result.added += 1

    session.flush()
    if landed:
        video.status = "added"
        video.reason = None
        video.processed_at = utcnow()
        added_per_channel[channel.id] = added_per_channel.get(channel.id, 0) + 1
        session.flush()
