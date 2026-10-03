"""Adding a source from whatever somebody typed, and how much of its history to take."""

from __future__ import annotations

from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import sources
from ...models import Channel
from ...plugins.publisher import ChannelInfo, PublishError, names, publishing_plugin
from ...sources import newsletter, syndication
from .. import ordering
from ..connections import build_client
from ..scope import OwnerId, owned
from .listing import ChannelError
from .switches import default_left_out


def resolve(session: Session, reference: str, http: httpx.Client) -> ChannelInfo:
    """Turn a reference into a channel, for the references that need asking.

    Only those. Anything a plugin can work out on its own — a UC… id, a
    /channel/ URL, an r/ community — never reaches here: `add_source` has its
    feed address already and finds the title by reading it, which costs
    nothing and needs nobody's permission.

    What is left is the handle, and a handle needs the account's
    connection to become a channel id.
    """
    client = build_client(session, http)
    if not client.can_read:
        service = names().service or "the service"
        raise ChannelError(
            f"That needs looking up, which needs a {service} account connected under Settings, "
            "or an API key on the plugin's card — or paste the id itself, which needs neither."
        )
    try:
        info = client.resolve_channel(reference)
    except PublishError as exc:
        raise ChannelError(f"{names().publisher} refused: {exc}") from exc
    if info is None or not info.channel_id:
        raise ChannelError(f"no channel found for {reference!r}")
    return info


def publisher_kind() -> str:
    """The source kind the publishing plugin can put into its playlists."""
    plugin = publishing_plugin()
    kinds = [one.kind for one in plugin.sources if one.playlistable] if plugin else []
    if not kinds:
        raise ChannelError("No plugin here can look that up.")
    return kinds[0]


def add_source(
    session: Session,
    reference: str,
    http: httpx.Client,
    *,
    backfill_days: int | None = None,
    within: str = "",
    owner: OwnerId = None,
) -> Channel:
    """Start watching something, whatever kind of somewhere it is.

    A plugin says what a reference is and where its feed lives. It is taken
    at its word and checked by being read, which is the only honest test of a
    feed anyway — the exception being an @handle, which no plugin can
    finish because resolving one needs the account's sign-in.

    ``within`` is the kind of box it was typed into, when it was typed into
    one. That box was dragged out on purpose, so its kind is asked first and
    asked more generously than a reference nobody has placed.
    """
    typed = (reference or "").strip()
    try:
        found = sources.resolve(typed, within=within)
    except sources.UnknownSource as exc:
        raise ChannelError(str(exc)) from exc

    # A plugin may know what something is without being able to finish. The
    # one case is an @handle: turning it into a channel id needs this
    # account's sign-in, which is not a plugin's to hold, so the
    # code that does hold it takes over here.
    if found.needs_host:
        return add_channel(session, typed, http, backfill_days=backfill_days, owner=owner)

    existing = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == found.key)
    )
    if existing is not None:
        raise ChannelError(f"{existing.title or found.key} is already being watched")

    if found.needs_finding:
        # A place rather than a feed: a newsletter is known by where it
        # lives, and every platform puts its feed somewhere slightly
        # different. So the site is asked, which also reads it — there is
        # nothing left to confirm afterwards.
        said = newsletter.find(found.key, http)
        if said is None:
            raise ChannelError(
                f"{found.title} does not publish a feed that could be found. "
                "If you know where it is, a Feed address box takes it directly."
            )
        return _keep(
            session, found, feed_url=said.feed_url, title=said.title,
            backfill_days=backfill_days, owner=owner,
        )

    # Read once before keeping it: a feed that cannot be read is a source that
    # would sit there failing quietly every sync.
    try:
        feed = syndication.fetch(found.feed_url, http)
    except httpx.HTTPError as exc:
        raise ChannelError(f"could not read that feed: {exc}") from exc
    except ElementTree.ParseError as exc:
        raise ChannelError(f"that address did not give back a feed: {exc}") from exc

    return _keep(
        session, found, feed_url=found.feed_url, title=feed.title or found.title,
        backfill_days=backfill_days, owner=owner,
    )


def _keep(
    session: Session,
    found: sources.Resolved,
    *,
    feed_url: str,
    title: str,
    backfill_days: int | None,
    owner: OwnerId,
) -> Channel:
    """File a source whose feed has been read and found to be one."""
    channel = Channel(
        owner_pk=owner,
        channel_id=found.key,
        title=title or found.title,
        source_kind=found.kind,
        source_url=feed_url,
        # The kinds its plugin keeps off until asked, like YouTube's Shorts.
        left_out=default_left_out(found.kind),
        # Nothing to send items to yet, so it waits rather than quietly
        # queueing things that have nowhere to go.
        enabled=False,
        backfill_days=backfill_days,
    )
    session.add(channel)
    session.flush()
    ordering.append(session, channel)
    return channel


def add_channel(
    session: Session,
    reference: str,
    http: httpx.Client,
    *,
    backfill_days: int | None = None,
    owner: OwnerId = None,
) -> Channel:
    """Watch a source only the publishing plugin's service can name, like an `@handle`.

    Resolving one needs the account's sign-in, which a plugin is never
    handed, so the host asks the publishing plugin's `resolve` here. The
    source is that plugin's own kind. Starts paused.
    """
    info = resolve(session, reference, http)
    kind = publisher_kind()
    existing = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == info.channel_id)
    )
    if existing is not None:
        raise ChannelError(f"{existing.title or info.channel_id} is already being watched")

    channel = Channel(
        owner_pk=owner,
        channel_id=info.channel_id,
        title=info.title or info.channel_id,
        handle=info.handle,
        thumbnail_url=info.thumbnail_url,
        description=info.description,
        # Found through the publishing plugin, so it is that plugin's kind.
        source_kind=kind,
        left_out=default_left_out(kind),
        # Nothing to send videos to yet, so it waits rather than quietly
        # queueing uploads that have nowhere to go.
        enabled=False,
        backfill_days=backfill_days,
    )
    session.add(channel)
    session.flush()
    ordering.append(session, channel)
    return channel


# Offered when a channel is first tracked. None means "use the global count".
BACKFILL_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "Default — the newest few"),
    ("0", "Nothing — only uploads from now on"),
    ("7", "The last week"),
    ("30", "The last month"),
    ("90", "The last three months"),
    ("3650", "Everything the feed still lists"),
)


def parse_backfill(raw: str | None) -> int | None:
    """An empty choice means the global default; anything else is a day count."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return max(0, int(text))
    except ValueError:
        return None
