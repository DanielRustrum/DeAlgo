"""Take the screenshots the docs and the README show, from a demo instance.

Nothing of anybody's own appears in them: a fresh data folder is seeded with
made-up sources, feeds, a canvas, a pamphlet and a small plugin, the app is
started on it, and headless Chrome is driven over its DevTools protocol to
take each page. The pictures items carry are drawn here, as SVG, and the
pamphlet's video made by ffmpeg, both served from a little server of this
script's own, so nothing is fetched from anywhere else.

Writes `docs/wiki/images/<name>.png`, one per shot, and
`docs/wiki/images/carousel.svg`: every highlight cross-faded in turn by CSS
keyframes inside the SVG, which is the one way to animate a README — forges
strip `<style>` and scripts from Markdown, but draw an SVG as it is.

Chrome is the one at `--chrome` (default http://127.0.0.1:9222); if nothing
answers there, a `zenika/alpine-chrome` container is started for the run and
removed after it.

Run with `make screenshots`, after changing anything a shot shows.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import html
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "wiki" / "images"
WIDTH, HEIGHT = 1400, 875
#: How much smaller each shot is in the carousel, and how good its JPEG.
CAROUSEL_SCALE = 0.6
CAROUSEL_QUALITY = 68
#: Seconds each slide of the carousel is shown.
SLIDE_SECONDS = 4
CHROME_IMAGE = "zenika/alpine-chrome"
CHROME_NAME = "pamphlets-screenshots-chrome"


def free_port() -> int:
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return int(one.getsockname()[1])


# -- the pictures items carry -----------------------------------------------------

PALETTES = (
    ("#264653", "#2a9d8f", "#e9c46a"),
    ("#3d405b", "#81b29a", "#f2cc8f"),
    ("#22223b", "#4a4e69", "#c9ada7"),
    ("#2b2d42", "#8d99ae", "#ef233c"),
    ("#283618", "#606c38", "#dda15e"),
    ("#1d3557", "#457b9d", "#f1faee"),
    ("#582f0e", "#936639", "#c2c5aa"),
    ("#0b132b", "#3a506b", "#5bc0be"),
)


def picture(number: int, motif: str) -> str:
    """A made-up picture: a gradient, a horizon and a shape, as SVG."""
    deep, middle, light = PALETTES[number % len(PALETTES)]
    shapes = {
        "stars": "".join(
            f'<circle cx="{(37 * i + number * 53) % 480}" cy="{(23 * i * i + number * 7) % 160}" r="{1 + i % 3}" fill="#fff" opacity=".8"/>'
            for i in range(28)
        ) + '<circle cx="380" cy="70" r="34" fill="#f1faee"/>',
        "bowl": f'<ellipse cx="240" cy="200" rx="150" ry="46" fill="{light}"/><path d="M90 196 Q240 330 390 196 Z" fill="{middle}"/>'
                '<circle cx="200" cy="178" r="18" fill="#e76f51"/><circle cx="250" cy="170" r="14" fill="#90be6d"/>'
                '<circle cx="290" cy="182" r="16" fill="#f9c74f"/>',
        "page": f'<rect x="150" y="40" width="180" height="200" rx="6" fill="{light}"/>'
                + "".join(f'<rect x="170" y="{70 + 18 * i}" width="{140 - (i % 3) * 25}" height="7" rx="3" fill="{deep}" opacity=".55"/>' for i in range(8)),
        "hills": f'<circle cx="360" cy="80" r="40" fill="{light}"/><path d="M0 220 Q120 120 240 200 T480 170 V270 H0 Z" fill="{middle}"/>'
                 f'<path d="M0 250 Q160 180 300 240 T480 230 V270 H0 Z" fill="{deep}" opacity=".7"/>',
    }
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 270" width="480" height="270">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{deep}"/>'
        f'<stop offset="1" stop-color="{middle}"/></linearGradient></defs>'
        f'<rect width="480" height="270" fill="url(#g)"/>{shapes[motif]}</svg>'
    )


def clip(into: Path) -> None:
    """A made-up video for the pamphlet's Video leaflet: a few seconds of a
    fractal, made by ffmpeg — no video service, and nothing of anybody's.
    Without ffmpeg the leaflet shows a link instead."""
    if shutil.which("ffmpeg") is None:
        return
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=12",
         "-t", "4", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "30", str(into / "clip.mp4")],
        check=False, capture_output=True,
    )


@contextlib.contextmanager
def serving(folder: Path) -> Iterator[str]:
    """Serve a folder over HTTP for the run, answering its address."""
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), partial(_Quiet, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
        pass


# -- the demo -------------------------------------------------------------------------

KITCHEN = r'''
-- A demo source plugin whose items lay themselves out in Content view.
local function esc(text)
  return (tostring(text or ""):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

local function card(item, rated)
  local about, steps = {}, {}
  for line in (item.words .. "\n"):gmatch("(.-)\n") do
    if line:sub(1, 2) == "- " then steps[#steps + 1] = '<item>' .. esc(line:sub(3)) .. '</item>'
    elseif line ~= "" then about[#about + 1] = esc(line) end
  end
  local picture = item.images[1] or item.thumbnail
  return '<view><box class="art"><image src="' .. esc(picture) .. '" alt=""/></box><column>'
    .. '<small class="from">' .. esc(item.author) .. '</small>'
    .. '<heading level="1">' .. esc(item.title) .. '</heading>'
    .. '<row class="meta"><badge>' .. math.floor(item.duration / 60) .. ' min</badge>'
    .. '<badge>serves 4</badge><badge>vegetarian</badge></row>'
    .. '<paragraph>' .. table.concat(about, " ") .. '</paragraph>'
    .. '<heading level="2">You need</heading><list>' .. table.concat(steps) .. '</list>'
    .. (rated and ('<paragraph class="rated">Rated ' .. esc(rated) .. ' of 5 — saved for next week.</paragraph>')
        or ('<form><label>How was it? <input name="stars" type="range" min="1" max="5" value="4"/></label>'
            .. '<button>Rate it</button></form>'))
    .. '</column></view>'
end

return { api = 1, id = "kitchen", name = "Kitchen Table", sources = { {
  kind = "kitchen", label = "Kitchen Table", example = "a cookbook's name",
  recognise = function(ref) return nil end,
  style = [[
    view { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 2rem; align-items: start }
    .art image { width: 100%; border-radius: 14px; box-shadow: 0 10px 30px rgba(0, 0, 0, .18) }
    .from { text-transform: uppercase; letter-spacing: .12em; color: var(--muted) }
    heading { margin: .2rem 0 .6rem }
    .meta { display: flex; gap: .5rem; margin-bottom: 1rem }
    badge { background: var(--sage-soft); color: var(--text); border-radius: 999px; padding: .2rem .7rem; font-size: .8rem }
    list { padding-left: 1.2rem; line-height: 1.8 }
    form { display: flex; gap: 1rem; align-items: center; margin-top: 1.2rem }
    .rated { font-weight: 600; color: var(--accent) }
  ]],
  view = function(item, settings) return card(item, nil) end,
  act = function(item, values, settings) return card(item, values.stars) end,
} } }
'''

LUA = """-- How much of each source is read, as a share.
local per = {}
for _, row in ipairs(data) do
  local one = per[row.source] or { total = 0, read = 0 }
  one.total = one.total + 1
  if row.watched then one.read = one.read + 1 end
  per[row.source] = one
end
local out = {}
for source, one in pairs(per) do
  out[#out + 1] = { source = source, read = math.floor(100 * one.read / one.total) }
end
table.sort(out, function(a, b) return a.read > b.read end)
return out
"""

COMMENT = """### Evening routine

Everything long-form lands in **Evening Reading**, newest first,
with *sponsored* posts held back.

- Stargazing fills itself straight from the newsletter
- Recipes get **20 minutes** each, then move on"""

#: Each source: its name, its kind, the picture its items carry, and its items.
SOURCES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("The Long Read Quarterly", "rss", "page", (
        "The quiet economics of public libraries",
        "What the river remembers: a year on the Severn",
        "Sponsored: ten gadgets for a smarter home",
        "Why every city needs a night mayor",
        "The last typewriter repair shop in Leeds",
        "On learning a language at sixty",
        "How tide tables are still made by hand",
    )),
    ("Field Notes Weekly", "rss", "hills", (
        "Lichens are older than you think",
        "A field guide to autumn mushrooms",
        "The return of the white stork",
        "Walking the old drove roads",
        "Sponsored: the hiking boot of the year",
        "Hedgerows, measured",
    )),
    ("Night Sky Weekly", "rss", "stars", (
        "The Orionids peak this week",
        "Finding the Andromeda galaxy with binoculars",
        "Saturn at opposition: what to look for",
        "Dark-sky parks within a day's drive",
        "A beginner's map of the winter sky",
    )),
    ("Kitchen Table", "kitchen", "bowl", (
        "Roasted squash and miso soup",
        "Lemon and herb barley salad",
        "Slow-cooked chickpea stew",
        "Brown butter apple cake",
        "Charred leeks with romesco",
    )),
)

INGREDIENTS = (
    "- 1 small squash, peeled and cubed\n- 2 tbsp white miso\n- 1 onion, sliced\n- 2 cloves garlic\n"
    "- 750 ml vegetable stock\n- A handful of toasted seeds, to finish"
)


@dataclass
class Demo:
    """What the shots need to find again: ids of what was made."""

    canvas: dict[str, int] = field(default_factory=dict)
    feeds: dict[str, int] = field(default_factory=dict)
    items: dict[str, int] = field(default_factory=dict)


def seed(data_dir: Path, assets: str) -> Demo:
    """Fill a fresh data folder with the demo. Runs in a process of its own,
    since the app reads its data folder once, as it is imported."""
    os.environ["PAMPHLETS_DATA_DIR"] = str(data_dir)
    from pamphlets import db
    from pamphlets.models import CURRENT_INSIDE, Channel, Placement, Video, utcnow
    from pamphlets.services import graph
    from pamphlets.services.graph import comments, forms, insides, leaflets, scripting
    from pamphlets.services.playlists.creating import create_generic

    (data_dir / "plugins").mkdir(exist_ok=True)
    (data_dir / "plugins" / "kitchen.lua").write_text(KITCHEN, encoding="utf-8")
    db.init_db()
    demo = Demo()
    now = utcnow()
    with db.session_scope() as session:
        feeds = {title: create_generic(session, title) for title in ("Evening Reading", "Stargazing", "Weekend Cooking")}
        demo.feeds = {title: feed.id for title, feed in feeds.items()}
        # Their boxes first: anything that reads the canvas adds a box for a
        # feed that has none, wherever it likes.
        feed_boxes = {title: graph.add_feed(session, feed, x=1200, y=y)
                      for (title, feed), y in zip(feeds.items(), (40, 290, 400))}
        boxes: dict[str, Any] = {}
        number = 0
        for row, (title, kind, motif, items) in enumerate(SOURCES):
            channel = Channel(
                channel_id=title.lower().replace(" ", "-"), title=title, source_kind=kind,
                source_url=f"https://example.org/{title.lower().replace(' ', '-')}/feed.xml",
                last_checked_at=now,
            )
            session.add(channel)
            session.flush()
            boxes[title] = graph.add_source(session, channel=channel, x=300, y=40 + row * 115)
            for age, headline in enumerate(items):
                number += 1
                (IMAGES_TMP / f"{number}.svg").write_text(picture(number, motif), encoding="utf-8")
                picture_url = f"{assets}/{number}.svg"
                words = (
                    f"A short note on how it is made, from {title}.\n{INGREDIENTS}" if kind == "kitchen"
                    else f"{headline}. A made-up article for the screenshots: nothing here is real, but it reads like "
                         "the kind of thing a feed brings in of an evening."
                )
                item = Video(
                    video_id=f"demo-{number}", channel_pk=channel.id, kind="post", title=headline,
                    published_at=now - dt.timedelta(hours=23 * age + row * 5 + 1),
                    discovered_at=now - dt.timedelta(hours=23 * age + row * 5),
                    duration_sec=(25 + 5 * age) * 60 if kind == "kitchen" else (6 + 3 * (age % 4)) * 60,
                    thumbnail_url=picture_url, images=json.dumps([picture_url]), body=words,
                    link=f"https://example.org/{number}", status="added",
                    watched_at=now - dt.timedelta(hours=7 * age) if (age + row) % 3 == 0 and age else None,
                )
                session.add(item)
                session.flush()
                demo.items[headline] = item.id
                feed = feeds["Stargazing" if title == "Night Sky Weekly" else
                             "Weekend Cooking" if kind == "kitchen" else "Evening Reading"]
                if not headline.startswith("Sponsored"):
                    session.add(Placement(video_pk=item.id, playlist_pk=feed.id, playlist_item_id=f"p{number}",
                                          added_at=item.discovered_at))
        session.flush()

        # The canvas: a trigger, the sources, the rules between them and the feeds.
        pulse = graph.add_trigger(session, trigger_kind="pulse", label="Every six hours", every_minutes=360, x=20, y=170)
        for box in boxes.values():
            graph.connect(session, pulse, box)
        keep = graph.add_filter(session, label="No sponsored posts", x=600, y=40)
        graph.add_piece(session, kind="lacks-words", host=keep).title_exclude = "sponsored"
        order = graph.add_sort(session, label="Newest first", x=900, y=40)
        graph.add_piece(session, kind="order", host=order, sort_by="published")
        decay = graph.add_stamp(session, kind="decay", x=900, y=385)
        graph.add_piece(session, kind="timer", host=decay, duration_minutes=20)
        for title in ("The Long Read Quarterly", "Field Notes Weekly"):
            graph.connect(session, boxes[title], keep)
        graph.connect(session, keep, order)
        graph.connect(session, order, feed_boxes["Evening Reading"])
        graph.connect(session, boxes["Night Sky Weekly"], feed_boxes["Stargazing"])
        graph.connect(session, boxes["Kitchen Table"], decay)
        graph.connect(session, decay, feed_boxes["Weekend Cooking"])

        # A transformation written in Lua, charted on a pamphlet.
        share = graph.add_transform(session, label="Share read", x=1200, y=140)
        graph.connect(session, order, share)
        lua = graph.add_piece(session, kind="lua", host=share)
        scripting.save(lua, LUA)

        paper = graph.add_pamphlet(session, label="Morning Brief", x=300, y=560)
        listing = graph.add_piece(session, kind="leaflet-feed", host=paper)
        leaflets.save(listing, {"leaflet_title": "Tonight's reading", "leaflet_feed": str(feeds["Evening Reading"].id),
                                "leaflet_count": "4"}, set(demo.feeds.values()))
        chart = graph.add_piece(session, kind="leaflet-bar", host=listing, side="beside")
        leaflets.save(chart, {"leaflet_title": "Share read, by source (%)", "leaflet_label": "source",
                              "leaflet_value": "read", "leaflet_combine": "sum", "leaflet_direction": "horizontal",
                              "leaflet_sort": "value-desc"}, set())
        graph.connect(session, share, chart)
        arrived = graph.add_piece(session, kind="leaflet-line", host=chart)
        leaflets.save(arrived, {"leaflet_title": "Arrived each day", "leaflet_chart": "arrived-daily",
                                "leaflet_days": "10", "leaflet_fill": "area", "leaflet_curve": "smooth"}, set())
        video = graph.add_piece(session, kind="leaflet-video", host=chart, side="beside")
        leaflets.save(video, {"leaflet_heading": "Something to watch",
                              "leaflet_url": f"{assets}/clip.mp4"}, set())
        form = graph.add_piece(session, kind="leaflet-form", host=video)
        leaflets.save(form, {"leaflet_heading": "Suggest a source", "leaflet_queue": "suggestions",
                             "leaflet_button": "Suggest it", "leaflet_thanks": "Thanks — it's in the queue."}, set())
        name = graph.add_piece(session, kind="input-text", host=form)
        forms.save_field(name, {"field_form": "1", "field_name": "address", "field_label": "Feed address",
                                "field_required": "1", "field_pattern": r"https?://.+",
                                "field_hint": "Starts with http:// or https://"})
        why = graph.add_piece(session, kind="input-choice", host=name)
        forms.save_field(why, {"field_form": "1", "field_name": "topic", "field_label": "Topic",
                               "field_options": "Reading\nNature\nThe sky\nCooking"})
        note = graph.add_piece(session, kind="input-long", host=why)
        forms.save_field(note, {"field_form": "1", "field_name": "note", "field_label": "Why it's worth it"})

        said = graph.add_comment(session, text=COMMENT, x=1200, y=560)
        comments.save(said, {"comment_colour": "sage"})

        # A canvas of experiments, frozen while it is thought about.
        trial = graph.add_canvas(session, label="Experiments", x=20, y=560)
        trial.width, trial.height = 220, 150
        session.flush()
        token = CURRENT_INSIDE.set(trial.id)
        try:
            pulse2 = graph.add_trigger(session, trigger_kind="schedule", label="Mornings", cron="0 7 * * *", x=60, y=60)
            sky = Channel(channel_id="aurora-alerts", title="Aurora Alerts", source_kind="rss",
                          source_url="https://example.org/aurora.xml", last_checked_at=now)
            session.add(sky)
            session.flush()
            alerts = graph.add_source(session, channel=sky, x=340, y=60)
            alerts.inside_pk = trial.id
            loud = graph.add_filter(session, label="Only strong storms", x=640, y=60)
            graph.add_piece(session, kind="has-words", host=loud).title_include = "/kp ?[7-9]/"
            tag = graph.add_stamp(session, kind="tag", marks="aurora", x=640, y=240)
            held = graph.add_store(session, kind="deposit", repository="aurora", x=940, y=60)
            for box in (pulse2, alerts, loud, tag, held):
                box.inside_pk = trial.id
            graph.connect(session, pulse2, alerts)
            graph.connect(session, alerts, loud)
            graph.connect(session, loud, tag)
            graph.connect(session, tag, held)
        finally:
            CURRENT_INSIDE.reset(token)
        insides.freeze(session, trial.id, True)
        demo.canvas = {"share": share.id, "lua": lua.id, "paper": paper.id, "trial": trial.id, "keep": keep.id}
    return demo


#: Where the drawn pictures go; set before seeding.
IMAGES_TMP = Path()


# -- driving Chrome ------------------------------------------------------------------


@contextlib.contextmanager
def chrome(address: str) -> Iterator[str]:
    """Chrome's DevTools address: the one given if it answers, or a container
    started for the run."""
    def answers() -> bool:
        try:
            urllib.request.urlopen(f"{address}/json/version", timeout=2)
            return True
        except OSError:
            return False

    if answers():
        yield address
        return
    if shutil.which("docker") is None:
        sys.exit(f"Nothing answers at {address}, and there is no docker to start Chrome with.")
    port = address.rsplit(":", 1)[-1]
    subprocess.run(["docker", "rm", "-f", CHROME_NAME], capture_output=True)
    subprocess.run(
        ["docker", "run", "-d", "--name", CHROME_NAME, "--network", "host", "--shm-size=1g", CHROME_IMAGE,
         "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
         "--remote-debugging-address=0.0.0.0", f"--remote-debugging-port={port}", "about:blank"],
        check=True, capture_output=True,
    )
    try:
        for _ in range(40):
            if answers():
                break
            time.sleep(0.5)
        yield address
    finally:
        subprocess.run(["docker", "rm", "-f", CHROME_NAME], capture_output=True)


class Tab:
    """One Chrome tab, talked to over the DevTools protocol."""

    def __init__(self, chrome_at: str, dark: bool = False) -> None:
        from websockets.sync.client import connect

        request = urllib.request.Request(f"{chrome_at}/json/new?about:blank", method="PUT")
        self.target = json.load(urllib.request.urlopen(request))
        self.chrome_at = chrome_at
        self.ws = connect(self.target["webSocketDebuggerUrl"], max_size=200_000_000, open_timeout=10)
        self.count = 0
        # What this checkout serves, not what a service worker or the cache
        # kept from a run before.
        self.call("Network.enable")
        self.call("Network.setBypassServiceWorker", bypass=True)
        self.call("Network.setCacheDisabled", cacheDisabled=True)
        self.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT, deviceScaleFactor=1, mobile=False)
        self.call("Emulation.setEmulatedMedia",
                  features=[{"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
                            {"name": "prefers-reduced-motion", "value": "reduce"}])

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.count += 1
        self.ws.send(json.dumps({"id": self.count, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=60))
            if message.get("id") == self.count:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return dict(message.get("result", {}))

    def js(self, expression: str) -> Any:
        found = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in found:
            raise RuntimeError(f"{expression[:80]}…: {found['exceptionDetails']}")
        return found.get("result", {}).get("value")

    def open(self, url: str, settle: float = 2.5) -> None:
        self.call("Page.navigate", url=url)
        time.sleep(settle)
        self.js("document.querySelectorAll('.toast').forEach(t => t.remove())")

    def click(self, x: float, y: float, count: int = 1) -> None:
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=count)

    def centre_of(self, selector: str, top: float | None = None) -> tuple[float, float]:
        box = self.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                      " return [r.x, r.y, r.width, r.height]; })()")
        return box[0] + box[2] / 2, box[1] + (box[3] / 2 if top is None else top)

    def shot(self, name: str) -> tuple[bytes, bytes]:
        """The page as it is: a PNG for the docs, and a smaller JPEG for the carousel."""
        self.js("document.activeElement && document.activeElement.blur()")
        time.sleep(0.4)
        full = base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"])
        # A clip is placed on the page, not the window: where it is scrolled to.
        x, y = self.js("[scrollX, scrollY]")
        small = base64.b64decode(self.call(
            "Page.captureScreenshot", format="jpeg", quality=CAROUSEL_QUALITY,
            clip={"x": x, "y": y, "width": WIDTH, "height": HEIGHT, "scale": CAROUSEL_SCALE},
        )["data"])
        (IMAGES / f"{name}.png").write_bytes(full)
        return full, small

    def close(self) -> None:
        self.ws.close()
        urllib.request.urlopen(f"{self.chrome_at}/json/close/{self.target['id']}")


# -- the shots ---------------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    """One screenshot: its file name, its caption, and how to get there."""

    name: str
    caption: str
    take: Callable[[Tab, str, Demo], None]
    dark: bool = False
    #: Whether the README's carousel shows it.
    highlight: bool = True


def _canvas(tab: Tab, app: str, demo: Demo, inside: int | None = None,
            view: tuple[int, int, float] = (10, 10, 0.8)) -> None:
    """The canvas, or a Canvas node's inside, panned and zoomed to `view`."""
    tab.open(f"{app}/channels", settle=1)
    key = "pamphlets-canvas-view" if inside is None else f"pamphlets-canvas-view-{inside}"
    kept = json.dumps({"x": view[0], "y": view[1], "zoom": view[2]})
    tab.js("localStorage.clear();"
           + ("" if inside is None else f"localStorage.setItem('pamphlets-canvas-inside', '{inside}');")
           + f"localStorage.setItem('{key}', {json.dumps(kept)})")
    tab.open(f"{app}/channels", settle=3)
    tab.js("document.querySelector('[data-graph]').scrollIntoView({block: 'start'})")
    time.sleep(0.5)


def take_canvas(tab: Tab, app: str, demo: Demo) -> None:
    _canvas(tab, app, demo)


def take_frozen(tab: Tab, app: str, demo: Demo) -> None:
    _canvas(tab, app, demo, inside=demo.canvas["trial"], view=(10, 30, 1))


def take_lua(tab: Tab, app: str, demo: Demo) -> None:
    # The Transform near the top left, so the Lua piece's panel opens in full.
    _canvas(tab, app, demo, view=(-880, -110, 1))
    x, y = tab.centre_of(f'[data-node="{demo.canvas["lua"]}"]', top=16)
    tab.click(x, y)
    time.sleep(1.5)


def take_pamphlet(tab: Tab, app: str, demo: Demo) -> None:
    tab.open(f"{app}/pamphlets/{demo.canvas['paper']}", settle=4)


def take_list(tab: Tab, app: str, demo: Demo) -> None:
    tab.open(f"{app}/feed", settle=3)


def take_content(tab: Tab, app: str, demo: Demo) -> None:
    item = demo.items["Roasted squash and miso soup"]
    tab.open(f"{app}/focus?playlist={demo.feeds['Weekend Cooking']}&start={item}", settle=4)


def take_theming(tab: Tab, app: str, demo: Demo) -> None:
    tab.open(f"{app}/settings/theming", settle=3)


def take_plugins(tab: Tab, app: str, demo: Demo) -> None:
    tab.open(f"{app}/admin/plugins", settle=3)
    # Where the demo's data happens to be, said as the container's volume.
    tab.js("document.querySelectorAll('.plugin-list *').forEach(e => { if (e.children.length === 0)"
           " e.textContent = e.textContent.replace(/\\S*pamphlets-shots-[^/]+\\/data/, '/data') })")


SHOTS: tuple[Shot, ...] = (
    Shot("canvas", "Wire sources to feeds on the Configuration canvas", take_canvas),
    Shot("pamphlet", "Pamphlets: pages of your own, with feeds, charts, video and forms", take_pamphlet),
    Shot("list", "List view: every feed on one shelf", take_list),
    Shot("content", "Content view, laid out by the source's own plugin", take_content, dark=True),
    Shot("lua", "Transform data with Lua of your own", take_lua),
    Shot("frozen", "Freeze a canvas while you think it over", take_frozen),
    Shot("theming", "Your own colours, type and corners", take_theming, highlight=False),
    Shot("plugins", "Plugins, installed from a repository and granted only what you allow", take_plugins, highlight=False),
)


# -- the carousel --------------------------------------------------------------------


def carousel(slides: list[tuple[str, bytes]]) -> str:
    """An SVG showing each slide in turn, cross-faded by CSS keyframes, a
    caption under each and a dot for each along the bottom."""
    width, height = round(WIDTH * CAROUSEL_SCALE), round(HEIGHT * CAROUSEL_SCALE)
    band = 56
    total = SLIDE_SECONDS * len(slides)
    share = 100 / len(slides)
    fade = min(2.5, share / 4)
    style = (
        f"@keyframes show {{ 0% {{ opacity: 0 }} {fade:.2f}% {{ opacity: 1 }} {share:.2f}% {{ opacity: 1 }}"
        f" {share + fade:.2f}% {{ opacity: 0 }} 100% {{ opacity: 0 }} }}"
        f" @keyframes dot {{ 0% {{ fill: #c9c2b4 }} {fade:.2f}% {{ fill: #2f5d50 }} {share:.2f}% {{ fill: #2f5d50 }}"
        f" {share + fade:.2f}% {{ fill: #c9c2b4 }} 100% {{ fill: #c9c2b4 }} }}"
        f" .slide, .dot {{ animation-duration: {total}s; animation-iteration-count: infinite; animation-timing-function: linear }}"
        " .slide { opacity: 0; animation-name: show } .dot { fill: #c9c2b4; animation-name: dot }"
        " text { font-family: -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; font-size: 17px; fill: #2b2a27 }"
        " @media (prefers-reduced-motion: reduce) { .slide, .dot { animation: none } .slide:first-of-type { opacity: 1 } }"
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width} {height + band}" width="{width}" height="{height + band}" role="img" '
        f'aria-label="Screenshots of Pamphlets">',
        f"<style>{style}</style>",
        f'<rect width="{width}" height="{height + band}" rx="10" fill="#f6f2ea"/>',
        f'<clipPath id="frame"><rect width="{width}" height="{height}" rx="10"/></clipPath>',
    ]
    for index, (caption, jpeg) in enumerate(slides):
        delay = index * SLIDE_SECONDS
        data = base64.b64encode(jpeg).decode("ascii")
        parts.append(
            f'<g class="slide" style="animation-delay: {delay}s"><title>{html.escape(caption)}</title>'
            f'<image clip-path="url(#frame)" width="{width}" height="{height}" href="data:image/jpeg;base64,{data}"/>'
            f'<text x="20" y="{height + 34}">{html.escape(caption)}</text></g>'
        )
    for index in range(len(slides)):
        x = width - 20 - (len(slides) - 1 - index) * 18
        parts.append(f'<circle class="dot" style="animation-delay: {index * SLIDE_SECONDS}s" cx="{x}" cy="{height + 28}" r="5"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# -- running it --------------------------------------------------------------------


def clean_environment(data_dir: Path, port: int) -> dict[str, str]:
    """The environment the demo runs in: none of this machine's own settings."""
    kept = {name: value for name, value in os.environ.items() if not name.startswith(("PAMPHLETS_", "DEALGO_"))}
    return kept | {
        "PAMPHLETS_DATA_DIR": str(data_dir), "PAMPHLETS_PORT": str(port), "PAMPHLETS_HOST": "127.0.0.1",
        "PAMPHLETS_ADMIN_USER": "", "PAMPHLETS_LOG_LEVEL": "WARNING",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chrome", default="http://127.0.0.1:9222", help="Chrome's DevTools address")
    parser.add_argument("--only", nargs="*", default=[], help="take only these shots (no carousel)")
    parser.add_argument("--keep", action="store_true", help="keep the demo's data folder, and say where")
    args = parser.parse_args(argv)

    global IMAGES_TMP
    IMAGES.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pamphlets-shots-"))
    data_dir, IMAGES_TMP = work / "data", work / "pictures"
    data_dir.mkdir()
    IMAGES_TMP.mkdir()
    clip(IMAGES_TMP)
    port = free_port()
    environment = clean_environment(data_dir, port)
    server: subprocess.Popen[bytes] | None = None
    try:
        with serving(IMAGES_TMP) as assets:
            # Seeded in a process of its own: the app reads where its data is
            # once, when it is first imported.
            seeded = subprocess.run(
                [sys.executable, __file__, "--seed", str(data_dir), assets],
                env=environment, cwd=ROOT, capture_output=True, text=True,
            )
            if seeded.returncode:
                sys.stderr.write(seeded.stderr)
                return 1
            demo = Demo(**json.loads(seeded.stdout.strip().splitlines()[-1]))
            server = subprocess.Popen(
                [sys.executable, "-m", "pamphlets", "serve"], env=environment, cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=(work / "server.log").open("wb"),
            )
            app = f"http://127.0.0.1:{port}"
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"{app}/healthz", timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                sys.stderr.write((work / "server.log").read_text())
                return 1
            slides: list[tuple[str, bytes]] = []
            with chrome(args.chrome) as chrome_at:
                for shot in SHOTS:
                    if args.only and shot.name not in args.only:
                        continue
                    tab = Tab(chrome_at, dark=shot.dark)
                    try:
                        shot.take(tab, app, demo)
                        _, small = tab.shot(shot.name)
                    finally:
                        tab.close()
                    print(f"docs/wiki/images/{shot.name}.png")
                    if shot.highlight:
                        slides.append((shot.caption, small))
            if not args.only:
                (IMAGES / "carousel.svg").write_text(carousel(slides), encoding="utf-8")
                print("docs/wiki/images/carousel.svg")
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        if args.keep:
            print(f"The demo's data is in {data_dir}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--seed"]:
        IMAGES_TMP = Path(sys.argv[2]).parent / "pictures"
        made = seed(Path(sys.argv[2]), sys.argv[3])
        print(json.dumps(made.__dict__))
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
