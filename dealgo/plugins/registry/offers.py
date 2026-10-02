"""The plugins that loaded, asked as one.

Everything the rest of the app wants from a plugin is asked here, by source
kind or by augmentation ref. A plugin that throws is treated as having no
opinion: one broken plugin must not stop a sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ..runtime import PluginError, Sandbox
from .plugin import MOST_POSTS, Recognised

if TYPE_CHECKING:
    from .plugin import Augmentation, Plugin, SourceKind

log = logging.getLogger(__name__)


@dataclass
class Registry:
    """Every plugin the folder held, in the order they were read."""

    plugins: list[Plugin] = field(default_factory=list)

    @property
    def working(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if plugin.ok]

    @property
    def broken(self) -> list[Plugin]:
        """Ones that did not load. A paused plugin is not among them: it is
        working fine and has been asked to stand down."""
        return [plugin for plugin in self.plugins if plugin.trouble is not None]

    @property
    def paused(self) -> list[Plugin]:
        return [plugin for plugin in self.plugins if plugin.paused]

    def source_kinds(self) -> list[SourceKind]:
        return [kind for plugin in self.working for kind in plugin.sources]

    def augmentations(self) -> list[Augmentation]:
        return [one for plugin in self.working for one in plugin.augments]

    def augmentation(self, ref: str) -> Augmentation | None:
        return next((one for one in self.augmentations() if one.ref == ref), None)

    def _asking(self, ref: str, hook: str) -> tuple[Augmentation, "Sandbox", Any] | None:
        """One augmentation's function, and the sandbox to call it in.

        None where there is nothing to call: the plugin is switched off, or
        gone, or this is not the kind of augmentation being asked for.
        """
        found = self.augmentation(ref)
        if found is None:
            return None
        asking = getattr(found, hook, None)
        if asking is None:
            return None
        plugin = next((p for p in self.working if p.id == found.plugin_id), None)
        if plugin is None or plugin.box is None:
            return None
        return found, plugin.box, asking

    def keeps(self, ref: str, item: dict[str, object], settings: dict[str, str]) -> bool:
        """Whether a plugin's condition lets this item carry on.

        One that throws, or answers with something that is not a yes or a no,
        lets the item by. A filter nobody can read the mind of should not
        silently swallow a feed: the failure belongs in the log, and the item
        belongs wherever it was going.
        """
        asking = self._asking(ref, "_keep")
        if asking is None:
            return True
        found, box, keep = asking
        try:
            said = box.call(keep, box.table(**item), box.table(**settings))
        except PluginError as exc:
            log.warning("%s could not judge an item: %s", found.plugin, exc)
            return True
        return said is not False

    def ranks(
        self, ref: str, item: dict[str, object], settings: dict[str, str]
    ) -> float | None:
        """Where a plugin's ordering puts this item. Bigger comes first.

        None where it could not say — it threw, or answered with something
        that is not a number. The batch then falls back to the order it
        arrived in for that item rather than to an invented position, because
        a made-up number would quietly reorder a feed and look deliberate.
        """
        asking = self._asking(ref, "_rank")
        if asking is None:
            return None
        found, box, rank = asking
        try:
            said = box.call(rank, box.table(**item), box.table(**settings))
        except PluginError as exc:
            log.warning("%s could not order an item: %s", found.plugin, exc)
            return None
        if isinstance(said, bool) or not isinstance(said, (int, float)):
            return None
        return float(said)

    def kind(self, name: str) -> SourceKind | None:
        return next((k for k in self.source_kinds() if k.kind == name), None)

    def recognise(self, reference: str) -> "Recognised | None":
        """Ask every plugin whose reference this is.

        A certain answer beats a guess, whoever answered first. Some kinds
        are recognisable outright — "r/python" is a subreddit and nothing
        else — while others can only be guessed at: a Bluesky handle may be
        any domain at all, so "example.com" *might* be one and might equally
        be a newsletter nobody has written a plugin for yet.

        Without that distinction the answer would depend on filename order,
        and "name.substack.com" would be read as a Bluesky account because
        B comes before S.

        A plugin that throws while recognising has failed at the one thing it
        was asked; it is left out of the answer rather than taking the whole
        attempt down with it.
        """
        typed = (reference or "").strip()
        if not typed:
            return None
        guess: Recognised | None = None
        for plugin in self.working:
            for kind in plugin.sources:
                if plugin.box is None or kind._recognise is None:
                    continue
                try:
                    said = plugin.box.call(kind._recognise, typed)
                except PluginError as exc:
                    log.warning("%s could not read %r: %s", plugin.title, typed, exc)
                    continue
                if not isinstance(said, dict):
                    continue
                answer = self._read(kind, said)
                if answer is None:
                    continue
                if not answer.guess:
                    return answer
                guess = guess or answer
        return guess

    def refine(self, kind: str, item: dict[str, object]) -> dict[str, object]:
        """What this kind's plugin says is particular about one of its items.

        The host reads the feed — it has a real XML parser and a plugin does
        not — and this is where the kind adds what only it knows: which id a
        video is filed under, whether it is a Short, what sort of thing it is
        at all.

        Whatever comes back is merged over what was read, so a plugin with no
        `refine` changes nothing and a plugin that answers with rubbish
        changes only what it named.
        """
        said = self._ask(kind, "_refine", item)
        return said if isinstance(said, dict) else {}

    def _read(self, kind: SourceKind, said: dict[str, object]) -> "Recognised | None":
        """A plugin's answer about a reference, whichever way it was asked."""
        key = str(said.get("key") or "").strip()
        if not key:
            return None
        return Recognised(
            kind=kind.kind,
            key=key,
            feed_url=str(said.get("feed") or "").strip(),
            title=str(said.get("title") or key),
            plugin=kind.plugin,
            # A plugin may know what something is without being able to
            # finish: a YouTube @handle needs this account's Google
            # connection, which is not a plugin's to hold.
            needs_host=said.get("needs_host") is True,
            guess=said.get("guess") is True,
        )

    def accept(self, kind: str, reference: str) -> Recognised | None:
        """What this kind makes of something typed into one of its own boxes.

        Different from `recognise`, which is asked of every plugin about a
        reference nobody has placed yet and must therefore be sure. Here the
        kind is already settled — somebody dragged out a Subreddit box — so
        a bare "python" is a subreddit and not a guess about one.

        A kind with nothing to add falls back to recognising, so this is
        never worse than the old way round.
        """
        found = self.kind(kind)
        if found is None:
            return None
        said = self._ask(kind, "_accept", reference)
        made = self._read(found, said) if isinstance(said, dict) else None
        if made is not None:
            return made
        known = self.recognise(reference)
        return known if known is not None and known.kind == kind else None

    def home(self, kind: str, key: str) -> str | None:
        """Where a source itself lives, for a link out to it.

        Built from the key rather than stored, because it is the plugin's
        address to build: a channel id becomes one address, a subreddit
        another, and neither is the host's to spell.
        """
        said = self._ask(kind, "_home", key)
        return said if isinstance(said, str) and said else None

    def has_extras(self, kind: str) -> bool:
        """Whether this kind keeps anything its feed does not carry.

        Asked before fetching, so a source with nothing beyond its feed is
        not made to load a page to find that out.
        """
        found = self.kind(kind)
        return found is not None and found.has_posts

    def posts(self, kind: str, key: str) -> list[dict[str, object]]:
        """Whatever this kind publishes that its feed does not carry.

        Scraped rather than fetched from an API, wherever a plugin offers it,
        so it is wrapped the way everything optional is: a source whose extras
        cannot be read still has everything its feed gave.
        """
        said = self._ask(kind, "_posts", key)
        if not isinstance(said, list):
            return []
        return [row for row in said[:MOST_POSTS] if isinstance(row, dict)]

    def mirror(self, kind: str, key: str) -> str | None:
        """A second address for the same feed, where the plugin offers one."""
        said = self._ask(kind, "_mirror", key)
        return said if isinstance(said, str) and said else None

    def _ask(self, kind: str, hook: str, *args: object) -> object:
        """Call one of a kind's optional functions, or give back None.

        A plugin that throws here has failed at something optional; it is
        worth a line in the log and nothing more, because the caller has a
        perfectly good answer without it.
        """
        found = self.kind(kind)
        if found is None:
            return None
        fn = getattr(found, hook, None)
        if fn is None:
            return None
        plugin = next((p for p in self.working if p.title == found.plugin), None)
        if plugin is None or plugin.box is None:
            return None
        try:
            # Dictionaries become Lua tables on the way in. A Python object
            # handed across is one a plugin cannot read a single field of,
            # now that only declared names are reachable on one — and that is
            # a mistake worth making impossible rather than remembering.
            handing = [
                plugin.box.table(**value) if isinstance(value, dict) else value
                for value in args
            ]
            return plugin.box.call(fn, *handing)
        except PluginError as exc:
            log.warning("%s could not answer %s: %s", found.plugin, hook.strip("_"), exc)
            return None

    def item_url(self, kind: str, key: str, link: str | None) -> str | None:
        """Where one of this kind's items lives, if its plugin says so."""
        said = self._ask(kind, "_item_url", key, link)
        return said if isinstance(said, str) and said else link
