"""A source's player: the frame its videos play in, and how to talk to it.

A player used to be built in — YouTube's, with YouTube's own script loaded
into Content view. That put a service's code in the page every account signs
in to, and put a service in Pamphlets. Now a source plugin declares its
player, and declares it as data, never as code the browser runs:

    player = {
      frame = "https://player.example/embed/{key}?api=1&autoplay={autoplay}&origin={origin}",
      hello = { '{"event":"listening"}' },
      say = { pause = '{"command":"pause"}', stop = '{"command":"stop"}' },
      hears = {
        playing = { state = 1 }, paused = { state = 2 }, ended = { state = 0 },
        failed = { event = "error" },
        time = "info.currentTime", duration = "info.duration",
      },
      videos = function(address) return key_or_nil end,
    }

What keeps that safe:

* **The frame is another origin's page, sandboxed.** Its address must be
  https and its origin is fixed by what the plugin wrote: only `{key}`,
  `{autoplay}` and `{origin}` are filled in, each encoded, none of them
  before the path. A key is checked as a plain name besides.
* **No plugin code runs in the browser.** The page posts the plugin's own
  messages — JSON, checked here — to that one origin only, and listens only
  to messages from that frame and that origin. What it hears is read at the
  paths the plugin named, and compared; nothing heard is ever drawn as HTML
  or run.
* **Nothing of the session crosses.** The frame is cross-origin, so it can
  reach neither the page nor its cookies, and the sandbox takes away
  navigating the page it is in.

`videos(address)` — optional, run in the sandbox like any hook — says which
addresses are this source's videos, so a Video leaflet or a plugin's view
given one plays it in this frame too.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

from ..runtime import PluginError

#: What a frame's address may have filled in, and nothing else.
FILLED = ("{key}", "{autoplay}", "{origin}")
#: A video's key, as it goes into a frame's address.
KEY = re.compile(r"^[A-Za-z0-9_.~-]{1,128}$")
#: A path into what a frame says: `info.playerState`.
PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+){0,5}$")
#: The states a player is heard to be in, and the readings it gives.
STATES = ("ready", "playing", "paused", "ended", "failed")
READINGS = ("time", "duration")
#: What the page may ask a player to do.
SAYINGS = ("play", "pause", "stop")
#: What a player's frame is allowed, wherever one is drawn: to run its own
#: script on its own origin (which is not ours), go fullscreen and open its
#: own pages in a new tab — and not to navigate the page it is in, submit
#: forms on it, or open dialogs over it.
SANDBOX = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"
MOST_MESSAGE = 2000
MOST_FRAME = 500


@dataclass(frozen=True)
class Player:
    """One source's player, checked."""

    #: The frame's address, `{key}`, `{autoplay}` and `{origin}` still to fill.
    frame: str
    #: The one origin it is talked to at, and heard from.
    origin: str
    #: Said to the frame once it has loaded, until it answers.
    hello: tuple[str, ...] = ()
    #: What to say to it to play, pause or stop.
    say: dict[str, str] = field(default_factory=dict)
    #: What it says: each state as matchers (any one, all its fields equal),
    #: each reading as a path.
    hears: dict[str, Any] = field(default_factory=dict)

    def src(self, key: str, *, autoplay: bool, origin: str) -> str:
        """The frame's address for one video; "" for a key that is not one."""
        if not KEY.match(key) or key in (".", ".."):
            return ""
        return (
            self.frame.replace("{key}", quote(key, safe=""))
            .replace("{autoplay}", "1" if autoplay else "0")
            .replace("{origin}", quote(origin, safe=""))
        )

    def page(self) -> dict[str, Any]:
        """What the page is given to drive it: the same, as JSON."""
        return {"frame": self.frame, "origin": self.origin, "hello": list(self.hello),
                "say": dict(self.say), "hears": dict(self.hears)}


def _message(source: str, what: str, given: object) -> str:
    """One message to a frame: JSON text, short, checked as JSON."""
    if not isinstance(given, str) or not given.strip() or len(given) > MOST_MESSAGE:
        raise PluginError(f"source “{source}”: `player.{what}` has to be JSON text, under {MOST_MESSAGE} characters")
    try:
        json.loads(given)
    except ValueError as exc:
        raise PluginError(f"source “{source}”: `player.{what}` is not JSON: {exc}") from exc
    return given


def _listed(given: object) -> list[object]:
    """A list, or a single value, as a list."""
    if given is None:
        return []
    return list(given) if isinstance(given, list) else [given]


def _matcher(source: str, state: str, given: object) -> dict[str, object]:
    """One way a state is heard: fields, by path, and the plain value each has."""
    if not isinstance(given, dict) or not given:
        raise PluginError(f"source “{source}”: `player.hears.{state}` has to be a table of fields and values")
    made: dict[str, object] = {}
    for path, value in given.items():
        if not isinstance(path, str) or not PATH.match(path):
            raise PluginError(f"source “{source}”: `player.hears.{state}` names “{path}”, not a field path")
        if not isinstance(value, (str, int, float, bool)):
            raise PluginError(f"source “{source}”: `player.hears.{state}.{path}` has to be a plain value")
        made[path] = value
    return made


def _frame(source: str, given: object) -> tuple[str, str]:
    """The frame's address, and the origin it fixes."""
    if not isinstance(given, str) or len(given) > MOST_FRAME:
        raise PluginError(f"source “{source}”: `player.frame` has to be an address")
    frame = given.strip()
    parts = urlparse(frame.replace("{key}", "k").replace("{autoplay}", "0").replace("{origin}", "o"))
    if parts.scheme != "https" or not parts.hostname:
        raise PluginError(f"source “{source}”: `player.frame` has to be an https address")
    head = frame[: len("https://") + len(parts.netloc)]
    if "{" in head or "@" in head or head != f"https://{parts.netloc}":
        raise PluginError(f"source “{source}”: `player.frame` cannot fill in anything before its path")
    leftover = frame
    for one in FILLED:
        leftover = leftover.replace(one, "")
    if "{" in leftover or "}" in leftover:
        raise PluginError(f"source “{source}”: `player.frame` fills in only {', '.join(FILLED)}")
    if "{key}" not in frame:
        raise PluginError(f"source “{source}”: `player.frame` has to say where the video's {{key}} goes")
    return frame, f"https://{parts.netloc}".lower()


def read_player(source: str, given: object) -> Player | None:
    """A source's `player`, checked, or None for a source with none."""
    if given is None or given == "":
        return None
    if isinstance(given, str):
        raise PluginError(
            f"source “{source}”: `player` is a table now — the frame its videos play in, and how to talk to it "
            "— since Pamphlets has no players of its own"
        )
    if not isinstance(given, dict):
        raise PluginError(f"source “{source}”: `player` has to be a table")
    frame, origin = _frame(source, given.get("frame"))
    hello = tuple(_message(source, "hello", one) for one in _listed(given.get("hello"))[:8])
    said = given.get("say") or {}
    if not isinstance(said, dict):
        raise PluginError(f"source “{source}”: `player.say` has to be a table")
    say = {name: _message(source, f"say.{name}", said[name]) for name in SAYINGS if said.get(name) is not None}
    heard = given.get("hears") or {}
    if not isinstance(heard, dict):
        raise PluginError(f"source “{source}”: `player.hears` has to be a table")
    hears: dict[str, Any] = {}
    for state in STATES:
        if heard.get(state) is not None:
            # One matcher, or a list of them: `{ state = 0 }` or `{ {…}, {…} }`.
            hears[state] = [_matcher(source, state, one) for one in _listed(heard[state])[:8]]
    for reading in READINGS:
        path = heard.get(reading)
        if path is not None:
            if not isinstance(path, str) or not PATH.match(path):
                raise PluginError(f"source “{source}”: `player.hears.{reading}` has to be a field path")
            hears[reading] = path
    return Player(frame=frame, origin=origin, hello=hello, say=say, hears=hears)
