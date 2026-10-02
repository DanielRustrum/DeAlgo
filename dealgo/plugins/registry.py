"""What plugins there are, what each one offers, and what went wrong.

A plugin is a folder of its own — ``<id>/plugin.lua`` — in the shipped
plugins folder or in the data folder's. This reads them all on start, judges
what each returned, and keeps the ones that make sense — with a note against
the ones that do not, because a plugin that quietly fails to load is worse
than one that says why. Its id is its folder's name, never anything its file
says about itself.

Nothing is thrown away on a bad plugin. A file that will not parse, or comes
back without the fields it needs, becomes a row on the Admin page saying so;
the rest of the app carries on with the plugins that did load.

Held in memory and rebuilt on demand rather than stored: the folder is the
truth, and a registry that could disagree with it would be a second place to
look when something is missing.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from collections.abc import Callable
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from . import capabilities, permissions
# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from .runtime import PluginError as PluginError
from .runtime import Sandbox, load

log = logging.getLogger(__name__)

#: What a plugin's own file is called inside its folder. A plugin is a folder
#: of its own so that it can grow more than one file without the folder above
#: it becoming a heap.
ENTRY = "plugin.lua"

#: The version of the plugin API this host speaks. A plugin says which it was
#: written against, and one written against a later version is refused rather
#: than half-run.
API = 1

#: How many extras one source may hand back in one poll. A page holds a
#: dozen; a plugin answering with thousands is answering with something else.
MOST_POSTS = 200

#: A plugin id has to survive being a filename, a form field and a CSS class.
PLAIN = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


@dataclass(frozen=True)
class Recognised:
    """What a reference turned out to be, according to a plugin."""

    kind: str
    key: str
    feed_url: str
    title: str
    plugin: str
    #: True when the plugin knows the kind but cannot finish alone — the one
    #: case being a YouTube handle, which needs the Google connection.
    needs_host: bool = False
    #: True when the plugin is offering rather than asserting. A certain
    #: answer from anybody beats every guess.
    guess: bool = False


@dataclass(frozen=True)
class SourceKind:
    """A kind of somewhere to watch, as a plugin describes it."""

    kind: str
    label: str
    example: str
    playlistable: bool
    #: Which plugin this came from, for the Admin page and for errors.
    plugin: str
    #: What its box is called on the canvas — "YouTube channel", not
    #: "YouTube". You drag out the kind you want, so the box has to say
    #: which kind that is.
    noun: str = ""
    #: The line under that name in the palette.
    blurb: str = ""
    _recognise: Any = None
    _accept: Any = None
    _item_url: Any = None
    _mirror: Any = None
    _refine: Any = None
    _posts: Any = None
    _home: Any = None

    @property
    def has_posts(self) -> bool:
        """Whether this kind has anything beyond its feed.

        YouTube does — community posts live on a page with no feed and no API
        behind them. Most sources do not, and asking would only be a request
        nobody answers.
        """
        return self._posts is not None


@dataclass(frozen=True)
class Asked:
    """One permission a plugin wants, and the reason it gave.

    The reason is the plugin's own words. It is shown to the person deciding
    and never acted on: a plugin explaining itself is not a plugin being
    believed.
    """

    name: str
    why: str

    @property
    def known(self) -> bool:
        return self.name in permissions.BY_NAME

    @property
    def detail(self) -> permissions.Permission:
        return permissions.describe(self.name)


@dataclass(frozen=True)
class Field:
    """One setting on a plugin's box, as its popover will draw it."""

    name: str
    label: str
    #: "text" or "number". Anything else is drawn as text, because a field
    #: nobody can fill in is worse than one drawn plainly.
    type: str = "text"
    default: str = ""
    placeholder: str = ""


#: Which of the app's boxes a plugin may add an augmentation to, and what
#: that augmentation has to answer to be one.
#:
#: Only these two, because only these two ask a question a sandbox can
#: answer: something about one item, worked out from what it was handed. A
#: Timer or an Alive is about clocks and sittings, which is the host's own
#: machinery and nothing a plugin could implement.
AUGMENTS: dict[str, str] = {"filter": "keep", "sort": "rank"}


@dataclass(frozen=True)
class Augmentation:
    """Something a plugin adds to one of the app's boxes.

    It is slotted under a box on the canvas and changes what that box does.
    A plugin has no box of its own: it widens what the app's Filter and Sort
    can be told, rather than standing a second kind of either beside them.

    Two jobs, and which one it is, is which box it goes under:

    * **Under a Filter it narrows.** Given an item and whatever its fields
      were set to, `keep` answers whether that item may carry on.
    * **Under a Sort it orders.** `rank` answers with a number, and the batch
      is put in order of it.

    Both are pure questions about one item, which is the one shape that fits
    inside the sandbox — no network, no database, nothing to be trusted with.
    """

    #: Unique across every plugin, because one has to be found again from
    #: what is stored against it. Written "<plugin>:<augmentation>".
    ref: str
    kind: str
    label: str
    blurb: str
    fields: tuple[Field, ...]
    plugin: str
    plugin_id: str
    #: Which of the app's boxes it slots under: "filter" or "sort".
    under: str = "filter"
    _keep: Any = None
    _rank: Any = None

    @property
    def orders(self) -> bool:
        return self.under == "sort"


@dataclass
class Plugin:
    """One file in the plugins folder, loaded or not."""

    id: str
    path: Path
    name: str = ""
    version: str = ""
    #: None while it is fine. A sentence when it is not, and then nothing
    #: else on this object is to be trusted.
    trouble: str | None = None
    sources: list[SourceKind] = field(default_factory=list)
    #: What it adds to the app's boxes. Named for what they are rather than
    #: for what they were: a plugin declared boxes of its own once.
    augments: list[Augmentation] = field(default_factory=list)
    #: How it writes back to its own service, if it can. The functions are
    #: the plugin's; what they are called is the host's vocabulary.
    publishes: dict[str, Any] = field(default_factory=dict)
    #: What each of those calls costs against the day's allowance. The
    #: service's own price list, which is the service's to keep.
    costs: dict[str, int] = field(default_factory=dict)
    #: What it asked for, in the order it asked.
    wants: list[Asked] = field(default_factory=list)
    #: What it actually has. Never more than it asked for, and never anything
    #: this version does not understand.
    granted: frozenset[str] = frozenset()
    box: Sandbox | None = None
    #: What the file said it was, for showing on the Admin page even when the
    #: rest of it was refused.
    api: int = 0
    #: The shipped plugin this one stands in for, when somebody has put their
    #: own copy in the data folder. Worth saying out loud: a stale override is
    #: otherwise indistinguishable from a bug in De-Algo.
    replaces: Path | None = None

    @property
    def home(self) -> Path:
        """The folder this plugin lives in. What is beside its file is its."""
        return home_of(self.path)
    #: Switched off by hand. It still loaded, and everything about it is
    #: still readable — it simply offers nothing while it is off, which is
    #: the only way to turn off a plugin that ships in the image.
    paused: bool = False

    @property
    def ok(self) -> bool:
        """Loaded, and switched on. The two are different questions and the
        page asks them separately: a paused plugin is not a broken one."""
        return self.trouble is None and not self.paused

    @property
    def loaded(self) -> bool:
        """It made sense, whether or not it is switched on."""
        return self.trouble is None

    @property
    def title(self) -> str:
        return self.name or self.id

    @property
    def wanting(self) -> list[Asked]:
        """What it asked for and has not been given.

        Shown on its row, because a plugin quietly doing less than it was
        written to do is the hardest kind of broken to notice.
        """
        return [want for want in self.wants if want.name not in self.granted]


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


_lock = threading.Lock()
_loaded: Registry | None = None


def shipped() -> Path:
    """The plugins that come with De-Algo. Read-only, and replaced wholesale
    by an upgrade, so a new version's YouTube plugin arrives with it."""
    return Path(__file__).resolve().parent / "builtin"


def folder() -> Path:
    """Where a person's own plugins live. Beside the database, so they
    survive an upgrade and travel with a backup of the data volume."""
    from ..config import CONFIG

    return CONFIG.data_dir / "plugins"


def current() -> Registry:
    """The registry as it stands, reading the folders on first use."""
    global _loaded
    with _lock:
        if _loaded is None:
            _loaded = _everything()
        return _loaded


def forget() -> None:
    """Drop what was read, so the next question reads the folders again.

    The registry is built from the plugins folder *and* from the database
    rows saying what is switched off and what is granted. A test that swaps
    the database underneath it would otherwise keep answering from the last
    one — which is how a plugin paused in one test stayed paused for the
    rest of the run.
    """
    global _loaded
    with _lock:
        _loaded = None


def reload() -> Registry:
    """Read the folders again. What the Admin page's button does, what an
    upload does once the file has landed, and what switching one on or off
    does — the switch changes what the registry offers, so the registry has
    to be built again to offer it."""
    global _loaded
    with _lock:
        _loaded = _everything()
        return _loaded


def _everything() -> Registry:
    """Both folders, with the switches and the grants applied."""
    from ..services.sync import http_client

    # A plugins folder written by an older version holds loose files. Moved
    # before it is read, so what loads is what will still be there next time.
    settle(folder())
    off, granted = _state()
    return read(
        shipped(), folder(),
        paused=off, granted=granted, trusted=shipped(), http=http_client,
    )


def _state() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Which plugins are off, and what each has been granted.

    One read for both, because they live in one row. A database that cannot
    be reached is read as "everything on, nothing granted": the safe way
    round, since a plugin quietly keeping a capability through a failed query
    is the one outcome nobody would want.
    """
    import json

    from ..db import session_scope
    from ..models import PluginState

    try:
        with session_scope() as session:
            off: set[str] = set()
            granted: dict[str, frozenset[str]] = {}
            for row in session.query(PluginState):
                if not row.enabled:
                    off.add(row.plugin_id)
                granted[row.plugin_id] = _names(row.granted)
            return frozenset(off), granted
    except Exception:  # pragma: no cover - a database that is not there yet
        log.warning("could not read plugin state; nothing is granted")
        return frozenset(), {}


def _names(stored: str | None) -> frozenset[str]:
    import json

    if not stored:
        return frozenset()
    try:
        loaded = json.loads(stored)
    except (TypeError, ValueError):
        return frozenset()
    if not isinstance(loaded, list):
        return frozenset()
    return frozenset(str(name) for name in loaded)


def paused_ids() -> frozenset[str]:
    """Which plugins have been switched off."""
    return _state()[0]


def set_granted(plugin_id: str, names: frozenset[str]) -> None:
    """Record what a person granted a plugin, and hand it over.

    Only names this version understands are kept: a grant for a permission
    that has since been removed from the vocabulary would be a row nobody can
    read, and quietly dropping it is better than storing a promise that
    cannot be honoured.
    """
    import json

    from ..db import session_scope
    from ..models import PluginState, utcnow

    kept = sorted(name for name in names if name in permissions.BY_NAME)
    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.granted = json.dumps(kept)
        row.changed_at = utcnow()
    reload()


@dataclass(frozen=True)
class Origin:
    """Where a plugin was fetched from, and when."""

    url: str
    ref: str
    when: Any = None


def set_origin(plugin_id: str, url: str, ref: str) -> None:
    """Remember where a plugin was fetched from, so it can be fetched again."""
    from ..db import session_scope
    from ..models import PluginState, utcnow

    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.origin = url or None
        row.origin_ref = ref or None
        row.fetched_at = utcnow()
        row.changed_at = utcnow()


def origins() -> dict[str, Origin]:
    """Where each fetched plugin came from, by id.

    Read as a whole rather than per plugin: the Admin page draws every row at
    once, and one query beats one per plugin.
    """
    from ..db import session_scope
    from ..models import PluginState

    try:
        with session_scope() as session:
            return {
                row.plugin_id: Origin(row.origin, row.origin_ref or "", row.fetched_at)
                for row in session.query(PluginState)
                if row.origin
            }
    except Exception:  # pragma: no cover - a database that is not there yet
        return {}


def read(
    *folders: Path,
    given: dict[str, object] | None = None,
    paused: frozenset[str] = frozenset(),
    granted: dict[str, frozenset[str]] | None = None,
    trusted: Path | None = None,
    http: Callable[[], Any] | None = None,
) -> Registry:
    """Load every plugin in each folder, in name order.

    A plugin is a folder of its own — ``<id>/plugin.lua`` — so that it can
    grow more than one file without the folder above it becoming a heap.
    A loose ``<id>.lua`` is still read, because that is the shape every
    plugin had until now and nobody's should stop loading; `settle` moves
    one into a folder of its own the next time De-Algo starts.

    Name order so the list is the same on every start: which plugin owns a
    source kind should not depend on how the filesystem feels.

    Later folders win. The shipped plugins are read first and a person's own
    second, so dropping a `youtube.lua` into the data folder replaces the one
    that came with De-Algo rather than fighting it — which is the only way to
    change a shipped plugin without editing the image.

    ``trusted`` is the folder whose plugins start with what they asked for.
    That is the shipped folder and nothing else: those arrive inside the
    image, they are how De-Algo does the things it has always done, and
    nobody chose to install them — so there is no moment at which a consent
    popup would have been shown. They are still listed with everything they
    hold, and every one of them can be revoked on the Admin page.
    """
    found = Registry()
    by_id: dict[str, Plugin] = {}
    for where in folders:
        if not where.is_dir():
            continue
        for path in inside(where):
            plugin = _one(path, given or {})
            stored = (granted or {}).get(plugin.id)
            if stored is None and trusted is not None and where == trusted:
                # Never decided on, and shipped: it holds what it asked for
                # until somebody says otherwise. A stored empty set is a
                # decision and is left alone.
                stored = frozenset(want.name for want in plugin.wants)
            _grant(plugin, stored or frozenset(), http)
            earlier = by_id.get(plugin.id)
            if earlier is not None:
                found.plugins.remove(earlier)
                plugin.replaces = earlier.path
            by_id[plugin.id] = plugin
            found.plugins.append(plugin)

    for plugin in found.plugins:
        plugin.paused = plugin.id in paused

    claimed: dict[str, str] = {}
    for plugin in found.plugins:
        if plugin.paused:
            # It offers nothing while it is off, so it claims nothing either
            # — which is what makes a paused plugin the way to hand a source
            # kind over to a replacement.
            continue
        # Two plugins cannot both own a source kind: the second to ask is
        # refused, and told which one has it.
        for kind in list(plugin.sources):
            owner = claimed.get(kind.kind)
            if owner is not None:
                plugin.sources.remove(kind)
                plugin.trouble = f"“{kind.kind}” is already provided by {owner}"
            else:
                claimed[kind.kind] = plugin.title
    return found


def set_paused(plugin_id: str, *, paused: bool) -> None:
    """Switch a plugin off, or back on, and rebuild what is offered."""
    from ..db import session_scope
    from ..models import PluginState, utcnow

    with session_scope() as session:
        row = (
            session.query(PluginState)
            .filter(PluginState.plugin_id == plugin_id)
            .one_or_none()
        )
        if row is None:
            row = PluginState(plugin_id=plugin_id)
            session.add(row)
        row.enabled = not paused
        row.changed_at = utcnow()
    reload()


def judge(stem: str, source: str) -> Plugin:
    """Load a plugin from text, without keeping it.

    What an upload is checked with: a file that will not load is one nobody
    wants in the folder, and saying so before it lands beats a broken row on
    the page afterwards.
    """
    # A path it does not have yet: it is being read, not kept, and where it
    # would land is the caller's to decide once somebody has agreed to it.
    plugin = Plugin(id=stem, path=Path(stem) / ENTRY)
    return _judge(plugin, source, {})


def inside(where: Path) -> list[Path]:
    """Every plugin file in a folder, by the id it will load under.

    Both shapes: a folder of its own with `plugin.lua` in it, and the loose
    `<id>.lua` that every plugin was until now. A folder wins over a loose
    file of the same name, because that is the shape being moved to and
    `settle` leaves nothing behind when it moves one.
    """
    found: dict[str, Path] = {}
    for path in sorted(where.glob("*.lua")):
        if path.is_file():
            found[path.stem] = path
    for child in sorted(where.iterdir()):
        # A dot is the app's own, not somebody's plugin: a fetch waiting to
        # be agreed to lives in one, and must not load while it waits.
        if child.name.startswith("."):
            continue
        entry = child / ENTRY
        if child.is_dir() and entry.is_file():
            found[child.name] = entry
    return [found[name] for name in sorted(found)]


def home_of(path: Path) -> Path:
    """The folder a plugin lives in, whichever shape it is in.

    Its own folder, or the plugins folder for one that is still a loose
    file. What is beside it is the plugin's; what is above it is not.
    """
    return path.parent if path.name == ENTRY else path.parent / path.stem


def settle(where: Path) -> int:
    """Move every loose ``<id>.lua`` into a folder of its own.

    Run on start, so a plugins folder written by an older version becomes the
    shape this one keeps without anybody being asked to do anything. Moved
    rather than copied, so there is one file and not two claiming the same id.

    A loose file whose folder already exists is left where it is: something
    has already put a plugin there, and deciding which of the two somebody
    meant is not this function's to do.
    """
    if not where.is_dir():
        return 0
    moved = 0
    for path in sorted(where.glob("*.lua")):
        if not path.is_file() or path.name.startswith("."):
            continue
        home = where / path.stem
        if home.exists():
            log.warning(
                "%s and %s/ are both here; leaving the loose file alone",
                path.name, path.stem,
            )
            continue
        try:
            home.mkdir(parents=True)
            path.replace(home / ENTRY)
        except OSError as exc:  # pragma: no cover - a full or unwritable volume
            log.warning("could not move %s into a folder of its own: %s", path.name, exc)
            continue
        moved += 1
    if moved:
        log.info("moved %d plugin(s) into folders of their own", moved)
    return moved


#: Where a fetch puts what it downloaded while somebody decides about it.
#: A dot so that `inside` never mistakes it for a plugin, and inside the
#: plugins folder so that moving one into place is a rename rather than a
#: copy across a filesystem.
STAGING = ".staged"


def stage(plugin_id: str, source: str, extras: dict[str, bytes] | None = None) -> Path:
    """Hold a fetched plugin until somebody has agreed to it.

    Written down rather than carried through the form, for two reasons. A
    plugin may be more than one file, and a form field is a poor way to
    carry bytes somebody else chose. And what was read and judged is then
    exactly what lands — re-fetching on the way past consent would leave a
    gap in which the repository could become something else.
    """
    _staged(plugin_id)  # cleared, so a second fetch is not layered on a first
    return keep(plugin_id, source, extras, where=_staging())


def take_staged(plugin_id: str) -> bool:
    """Move what was staged into place, replacing whatever was there.

    Answers False where there is nothing staged, which is the ordinary case
    for a plugin that was uploaded rather than fetched.
    """
    held = _staged(plugin_id, clear=False)
    if held is None:
        return False
    home = folder() / plugin_id
    if home.exists():
        shutil.rmtree(home)
    held.replace(home)
    return True


def _staging() -> Path:
    return folder() / STAGING


def _staged(plugin_id: str, *, clear: bool = True) -> Path | None:
    """Where a fetch of this plugin is being held, if anywhere.

    Only ever one directory directly inside the staging folder, named as a
    plugin id: this removes a tree, and the one thing it must never do is
    remove a tree somebody meant to keep.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        return None
    held = _staging() / plugin_id
    if not held.is_dir() or held.resolve().parent != _staging().resolve():
        return None
    if clear:
        shutil.rmtree(held)
        return None
    return held


def keep(
    plugin_id: str,
    source: str,
    extras: dict[str, bytes] | None = None,
    *,
    where: Path | None = None,
) -> Path:
    """Write a plugin into a folder of its own, and answer where it landed.

    Everything about the shape of a plugin on disk is decided here, so that
    adding one, fetching one and replacing one all produce the same thing.

    `extras` are whatever else came with it, by path relative to its folder.
    Checked here rather than trusted from wherever they came: a name with a
    separator or a `..` in it is refused outright rather than reduced to
    something safe, because a file landing somewhere nobody chose is worse to
    be surprised by than an error.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        raise PluginError(f"“{plugin_id}” is not a usable plugin name")
    home = (where or folder()) / plugin_id
    home.mkdir(parents=True, exist_ok=True)
    (home / ENTRY).write_text(source, encoding="utf-8")
    for name, body in (extras or {}).items():
        if not _beside(name):
            raise PluginError(f"“{name}” is not a name a plugin may bring with it")
        where = home / name
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes(body)
    return home / ENTRY


def _beside(name: str) -> bool:
    """Whether a name is somewhere inside a plugin's own folder.

    Said of the name rather than of the path it makes, so a name is refused
    before anything is created: no absolute paths, no walking up, no drive
    letters, and nothing reserved by the shape itself.
    """
    if not name or name == ENTRY or name.startswith((" ", "/", "\\")):
        return False
    if ":" in name or "\\" in name:
        return False
    inside = PurePosixPath(name)
    parts = inside.parts
    if not parts or any(part in ("..", ".", "") for part in parts):
        return False
    if inside.is_absolute():
        return False
    # And nothing that means something other than what it says: "./x" and
    # "a//b" both land somewhere safe and somewhere other than written, and
    # a file arriving under a name nobody chose is the thing being avoided.
    return str(inside) == name


def discard(plugin_id: str) -> bool:
    """Take one of somebody's own plugins off the disk, folder and all.

    Only ever inside the plugins folder, and only ever a name that could be a
    plugin id: this deletes a directory tree, and the one thing it must never
    do is take a tree somebody meant to keep.
    """
    if not plugin_id or not set(plugin_id) <= PLAIN:
        return False
    where = folder()
    home = where / plugin_id
    loose = where / f"{plugin_id}.lua"
    # Resolved and checked, so a name that somehow got past the character
    # test still cannot point out of the folder.
    if home.is_dir() and home.resolve().parent == where.resolve():
        shutil.rmtree(home)
        return True
    if loose.is_file():
        loose.unlink()
        return True
    return False


def _one(path: Path, given: dict[str, object]) -> Plugin:
    """Read one file, and turn anything that goes wrong into a sentence.

    Twice, when it has been granted something. The first pass is with an
    empty world, which is how its manifest is read without its own code ever
    having had a capability in scope; only then is it loaded again with what
    it was actually granted. A plugin cannot talk its way into a permission
    by what it does while being read.
    """
    plugin = Plugin(id=home_of(path).name, path=path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        plugin.trouble = f"could not be read: {exc}"
        return plugin
    except UnicodeDecodeError:
        plugin.trouble = "is not text"
        return plugin

    return _judge(plugin, source, given)


def _judge(plugin: Plugin, source: str, given: dict[str, object]) -> Plugin:
    """Run a plugin's file and decide what it turned out to be.

    With a `dealgo` that has been granted nothing. It is in scope so that a
    plugin can be written against it unconditionally, and it answers nothing
    about anybody — the capabilities that actually do something arrive on the
    second pass, once there is a manifest to weigh them against.
    """
    path = plugin.path

    def nothing_yet(lua: Any) -> dict[str, object]:
        return {**given, **capabilities.granted_to(plugin.id, frozenset(), None, lua)}

    try:
        box, made = load(plugin.id, source, given=nothing_yet)
    except PluginError as exc:
        plugin.trouble = str(exc).split(": ", 1)[-1]
        return plugin

    if not isinstance(made, dict):
        plugin.trouble = "did not end with `return { … }`"
        return plugin

    plugin.box = box
    # Its folder's name when it gives none. Not the file's: every plugin's
    # file is called plugin.lua, so that would title them all "plugin".
    plugin.name = str(made.get("name") or plugin.id)
    plugin.version = str(made.get("version") or "")
    plugin.api = int(made.get("api") or 0)

    if plugin.api != API:
        plugin.trouble = (
            f"is written for plugin API {plugin.api or 'none'}, and this is {API}"
        )
        return plugin
    if not set(plugin.id) <= PLAIN:
        plugin.trouble = "has a name outside a-z, 0-9, dash and underscore"
        return plugin

    try:
        plugin.wants = _wants(made.get("permissions"))
        plugin.sources = _sources(plugin, made.get("sources"))
        plugin.augments = _augmentations(plugin, _declared(made))
        plugin.publishes, plugin.costs = _publisher(made.get("publisher"))
    except PluginError as exc:
        plugin.trouble = str(exc)
        return plugin
    return plugin


def _grant(plugin: Plugin, allowed: frozenset[str], http: Callable[[], Any] | None) -> None:
    """Hand a plugin what it was granted, by loading it again with it.

    Only what it asked for, and only what this version understands: a grant
    stored against a permission that has since been removed from the
    vocabulary gives nothing, rather than giving something nobody can name.
    """
    wanted = {want.name for want in plugin.wants if want.known}
    plugin.granted = frozenset(allowed & wanted)
    if plugin.trouble is not None:
        return
    # Nothing to hand over and nothing to read back: a plugin that asked for
    # nothing already has the `dealgo` it will ever have, and loading it a
    # second time to give it the same thing would only cost a start-up.
    if not plugin.wants:
        return

    asked = tuple((want.name, want.why) for want in plugin.wants)

    def able(lua: Any) -> dict[str, object]:
        return capabilities.granted_to(plugin.title, plugin.granted, http, lua, asked)

    try:
        source = plugin.path.read_text(encoding="utf-8")
        box, made = load(plugin.id, source, given=able)
    except (OSError, UnicodeDecodeError, PluginError) as exc:
        # It loaded a moment ago with nothing, so this is something about the
        # capabilities themselves. It keeps what it had and is left with none.
        log.warning("%s could not be given what it was granted: %s", plugin.title, exc)
        plugin.granted = frozenset()
        return
    if not isinstance(made, dict):  # pragma: no cover - it was a dict a moment ago
        plugin.granted = frozenset()
        return

    plugin.box = box
    try:
        plugin.sources = _sources(plugin, made.get("sources"))
        plugin.augments = _augmentations(plugin, _declared(made))
        plugin.publishes, plugin.costs = _publisher(made.get("publisher"))
    except PluginError as exc:  # pragma: no cover - it parsed a moment ago
        plugin.trouble = str(exc)


def _wants(given: object) -> list[Asked]:
    """The permissions a plugin asks for, and why.

    A reason is required. "network" with no explanation is a request nobody
    can weigh, and refusing it here means the person deciding always has
    something to decide on.
    """
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`permissions` has to be a list of tables")

    asked: list[Asked] = []
    seen: set[str] = set()
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `permissions` has to be a table")
        name = str(entry.get("name") or "").strip()
        why = " ".join(str(entry.get("why") or "").split())
        if not name:
            raise PluginError("a permission needs a `name`")
        if not why:
            raise PluginError(f"permission “{name}” needs a `why` — say what it is for")
        if name in seen:
            raise PluginError(f"permission “{name}” is asked for twice")
        seen.add(name)
        asked.append(Asked(name=name, why=why[:400]))
    return asked


def _publisher(given: object) -> tuple[dict[str, Any], dict[str, int]]:
    """How a plugin writes back to its own service.

    Only the names the host asks by. A plugin offering something nobody here
    calls is offering nothing, and a plugin missing one simply cannot do that
    — the host says so rather than failing at the call.
    """
    if given is None:
        return {}, {}
    if not isinstance(given, dict):
        raise PluginError("`publisher` has to be a table")

    doing = {
        name: given[name]
        for name in (
            "resolve", "describe", "details", "whoami",
            "playlists", "playlist", "create", "rename",
            "contents", "add", "remove",
        )
        if callable(given.get(name))
    }
    prices: dict[str, int] = {}
    asked = given.get("costs")
    if isinstance(asked, dict):
        for name, value in asked.items():
            try:
                prices[str(name)] = max(1, int(float(str(value))))
            except (TypeError, ValueError):
                continue
    return doing, prices


def _augmentations(plugin: Plugin, given: object) -> list[Augmentation]:
    """What a plugin adds to the app's boxes, checked before it is drawn.

    Each says which box it slots under and answers the question that box
    asks: `keep` for a Filter, `rank` for a Sort. Both are checked here, so
    an augmentation that could never do anything is a plugin that does not
    load rather than a piece that quietly sits there.
    """
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`augmentations` has to be a list of tables")

    made: list[Augmentation] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `augmentations` has to be a table")
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("an augmentation needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable augmentation kind")

        under = str(entry.get("under") or "filter").strip().lower()
        wanted = AUGMENTS.get(under)
        if wanted is None:
            named = " or ".join(f"“{one}”" for one in AUGMENTS)
            raise PluginError(
                f"augmentation “{name}”: `under` has to be {named}, not “{under}”"
            )
        if not callable(entry.get(wanted)):
            raise PluginError(
                f"augmentation “{name}” goes under a {under}, "
                f"so it needs a `{wanted}` function"
            )
        made.append(
            Augmentation(
                ref=f"{plugin.id}:{name}",
                kind=name,
                label=str(entry.get("label") or name.title()),
                blurb=str(entry.get("blurb") or ""),
                fields=_fields(name, entry.get("fields")),
                plugin=plugin.title,
                plugin_id=plugin.id,
                under=under,
                _keep=entry.get("keep"),
                _rank=entry.get("rank"),
            )
        )
    return made


def _declared(made: dict[str, object]) -> object:
    """What a plugin's file offered, under either name.

    `nodes` was the name when what a plugin declared was a box of its own.
    It is an augmentation of one of the app's boxes now, and `augmentations`
    is what to call it — but a plugin written against the old name still
    reads, because nothing about what it declares has changed.
    """
    offered = made.get("augmentations")
    return made.get("nodes") if offered is None else offered


def _fields(node: str, given: object) -> tuple[Field, ...]:
    if given is None:
        return ()
    if not isinstance(given, list):
        raise PluginError(f"augmentation “{node}”: `fields` has to be a list of tables")
    made: list[Field] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError(f"augmentation “{node}”: every field has to be a table")
        name = str(entry.get("name") or "").strip()
        if not name or not set(name) <= PLAIN:
            raise PluginError(f"augmentation “{node}”: a field needs a plain `name`")
        made.append(
            Field(
                name=name,
                label=str(entry.get("label") or name.replace("_", " ").title()),
                type="number" if entry.get("type") == "number" else "text",
                default=str(entry.get("default") or ""),
                placeholder=str(entry.get("placeholder") or ""),
            )
        )
    return tuple(made)


def _sources(plugin: Plugin, given: object) -> list[SourceKind]:
    """The source kinds a plugin declares, checked before they are believed."""
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError("`sources` has to be a list of tables")

    kinds: list[SourceKind] = []
    for entry in given:
        if not isinstance(entry, dict):
            raise PluginError("every entry in `sources` has to be a table")
        name = str(entry.get("kind") or "").strip()
        if not name:
            raise PluginError("a source needs a `kind`")
        if not set(name) <= PLAIN:
            raise PluginError(f"“{name}” is not a usable kind name")
        if not callable(entry.get("recognise")):
            raise PluginError(f"“{name}” needs a `recognise` function")
        kinds.append(
            SourceKind(
                kind=name,
                label=str(entry.get("label") or name.title()),
                example=str(entry.get("example") or ""),
                playlistable=entry.get("playlistable") is True,
                plugin=plugin.title,
                noun=str(entry.get("noun") or entry.get("label") or name.title()),
                blurb=str(entry.get("blurb") or ""),
                _recognise=entry.get("recognise"),
                _accept=entry.get("accept"),
                _item_url=entry.get("item_url"),
                _mirror=entry.get("mirror"),
                _refine=entry.get("refine"),
                _posts=entry.get("posts"),
                _home=entry.get("home"),
            )
        )
    return kinds
