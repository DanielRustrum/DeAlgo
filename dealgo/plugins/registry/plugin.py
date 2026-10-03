"""What a loaded plugin is, and the things it can offer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import permissions

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ..runtime import Sandbox
from .connect import Connect
from .settings import Settings
from .storage import home_of

#: The version of the plugin API this host speaks. A plugin says which it was
#: written against, and one written against a later version is refused rather
#: than half-run.
API = 1


#: How many extras one source may hand back in one poll. A page holds a
#: dozen; a plugin answering with thousands is answering with something else.
MOST_POSTS = 200


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
class Take:
    """One kind of content a source publishes, with a switch of its own.

    YouTube's are videos, Shorts, broadcasts and community posts. Most
    sources publish one kind of thing and declare none: they take all of it.
    """

    name: str
    label: str
    #: Left out of a new source until somebody switches it on.
    off: bool = False
    #: Comes from the source's `posts` hook rather than its feed, so leaving
    #: every such kind out also stops that fetch.
    extras: bool = False


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
    #: What its box, palette row and pills wear: one of `SOURCE_COLOURS`.
    colour: str = "green"
    #: The kinds of content it publishes, each with a switch. Empty when it
    #: publishes one kind of thing and takes all of it.
    takes: tuple[Take, ...] = ()
    #: Whether a second address for its feed is worth offering. False for a
    #: service that never refuses a reader.
    mirrors: bool = True
    _recognise: Any = None
    _accept: Any = None
    _item_url: Any = None
    _mirror: Any = None
    _refine: Any = None
    _posts: Any = None
    _home: Any = None
    #: Which of `takes` one item is.
    _classify: Any = None

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
        """Whether this version of De-Algo knows the permission asked for."""
        return self.name in permissions.BY_NAME

    @property
    def detail(self) -> permissions.Permission:
        """What the permission asked for means."""
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


#: The colours a plugin may give its source boxes, the first being what a
#: source wears when its plugin names none. A list rather than any colour,
#: so every one is drawn for both themes and none is a colour the canvas
#: already uses to mean another kind of box — violet triggers, amber
#: filters, blue sorts, teal stamps, brown stores, terracotta feeds.
SOURCE_COLOURS: tuple[str, ...] = ("green", "moss", "jade", "sky", "pink", "red", "slate")


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
        """Whether this is an ordering (under a Sort) rather than a condition."""
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
    #: What it asked to be configured with: the admin's settings and each
    #: account's own.
    settings: Settings = field(default_factory=Settings)
    #: How it signs somebody in to its service, when it does: the host does
    #: the sign-in and keeps the token (registry/connect.py).
    connect: Connect | None = None
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
        """What to call the plugin: its name, or its id if it gave none."""
        return self.name or self.id

    @property
    def colour(self) -> str:
        """The colour that marks this plugin wherever it is spoken of: its
        first source's, or slate for a plugin with no sources of its own."""
        return self.sources[0].colour if self.sources else "slate"

    @property
    def wanting(self) -> list[Asked]:
        """What it asked for and has not been given.

        Shown on its row, because a plugin quietly doing less than it was
        written to do is the hardest kind of broken to notice.
        """
        return [want for want in self.wants if want.name not in self.granted]
