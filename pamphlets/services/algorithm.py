"""An algorithm of one's own: learning what you will want, on this install.

The algorithm a service runs on you learns from how you watch, and decides
what you see. This one does the same — for you, under your control, on this
machine, from nothing but what Focus mode saw you do here:

* **Interest** — would you open it at all, rather than skip straight past?
* **Retention** — how much of it would you take in?
* **Engagement** — would you stay with it, rather than stopping and starting?

For each, per account, a small linear model over an item's features — its
source, kind, tags, title words, length, and the time of day it went up —
trained by gradient descent in plain Python. It is small on purpose: what
it leans towards can be read back and shown, and nothing needs installing.

An **Aggregation** piece puts it to work. Under a Filter it holds back what
it predicts outside a range you set — a minimum and a maximum; under a Sort
it puts the batch in order of it, what is in the range first; under an
Expire box it lets what it predicts outside the range leave sooner. Until it has enough examples, or with algorithms switched off by the
admin or the account, a piece does nothing — and says why.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    AlgorithmModel,
    Consumption,
    GraphNode,
    Placement,
    Settings,
    SiteSetting,
    Video,
    utcnow,
)
from .scope import OwnerId, belongs_to, owned

#: What it can learn to predict, and what each is called.
SIGNALS: tuple[tuple[str, str], ...] = (
    ("interest", "Interest — would you open it at all"),
    ("retention", "Retention — how much of it you would take in"),
    ("engagement", "Engagement — how steadily you would stay with it"),
    ("saturation", "Saturation — whether a feed already has more of its source, or a tag, "
                   "than you take in"),
)

#: The signals learned as a model. Saturation is worked out as it goes,
#: from the feed and what you open: there is nothing to train.
LEARNED = ("interest", "retention", "engagement")

#: What saturation is measured by.
SATURATION_OF: tuple[tuple[str, str], ...] = (
    ("source", "Its source"),
    ("tag", "A tag"),
)

#: How often an account's algorithm learns again.
EVERY: tuple[tuple[str, str], ...] = (
    ("run", "Every run"),
    ("daily", "Once a day"),
)

#: Seconds on an item before it counts as opened rather than passed over.
OPENED_AFTER = 10.0

#: Days an item can sit in a feed unopened before that says "not interested".
UNOPENED_AFTER = 3

#: How long a post is expected to take, when nothing says otherwise.
READ_SECONDS = 30.0

#: Training: passes over the examples, step size, and how hard weights are
#: pulled back towards nothing, so a word seen once does not decide much.
EPOCHS = 20
STEP = 0.15
PULL = 1e-4

#: The most weights kept, largest first: enough to read, small to store.
MOST_WEIGHTS = 4000

#: An Expire box's Timer is never cut below this share of itself.
SHORTEST_LIFE = 0.1

_SITE_SWITCH = "algorithms"
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset(
    "the and for with from that this what your you are was were how why who when "
    "into over about after new not but have has had will can just more most its "
    "our out all one two video official episode part".split()
)


# -- the switches ----------------------------------------------------------------


def site_allows(session: Session) -> bool:
    """Whether the admin lets algorithms run on this install at all."""
    row = session.get(SiteSetting, _SITE_SWITCH)
    return row is None or row.value != "off"


def set_site_allows(session: Session, allowed: bool) -> None:
    row = session.get(SiteSetting, _SITE_SWITCH)
    if row is None:
        row = SiteSetting(name=_SITE_SWITCH)
        session.add(row)
    row.value = "on" if allowed else "off"
    session.flush()


def runs_for(session: Session, account: Settings) -> bool:
    """Whether this account's algorithm learns and predicts."""
    return site_allows(session) and bool(account.algorithm_on)


# -- remembering how things were watched -----------------------------------------


def record(
    session: Session,
    owner: OwnerId,
    video: Video,
    account: Settings,
    *,
    seconds: float,
    reached: float | None,
    duration: float | None,
    pauses: int,
    clicked: bool,
    skipped: bool,
    finished: bool,
) -> Consumption | None:
    """Remember one time something was open — if the account lets it learn."""
    if not account.algorithm_on:
        return None
    row = Consumption(
        owner_pk=owner,
        video_pk=video.id,
        seconds=max(0.0, min(seconds, 24 * 3600.0)),
        reached=None if reached is None else max(0.0, reached),
        duration=None if not duration else max(0.0, duration),
        pauses=max(0, min(pauses, 1000)),
        clicked=clicked,
        skipped=skipped,
        finished=finished,
    )
    session.add(row)
    session.flush()
    return row


def forget(session: Session, owner: OwnerId) -> None:
    """Forget everything it saw and learned for this account."""
    session.execute(delete(Consumption).where(belongs_to(Consumption, owner)))
    session.execute(delete(AlgorithmModel).where(belongs_to(AlgorithmModel, owner)))
    _MODELS.clear()
    session.flush()


# -- what an item is, to it -------------------------------------------------------


def features(video: Video) -> list[str]:
    """An item as the algorithm sees it: names it can weigh."""
    said = [f"source:{video.channel_pk}", f"kind:{video.kind}"]
    said += [f"tag:{tag}" for tag in video.tag_list]
    words = {
        word for word in _WORD.findall((video.title or "").lower()) if word not in _STOP
    }
    said += [f"word:{word}" for word in sorted(words)][:20]
    length = video.duration_sec
    if length is None:
        said.append("length:unknown")
    else:
        bands = ((120, "under 2 min"), (600, "2–10 min"), (1800, "10–30 min"), (3600, "30–60 min"))
        said.append("length:" + next((name for edge, name in bands if length < edge), "over an hour"))
    if video.published_at is not None:
        said.append(f"hour:{video.published_at.hour // 3 * 3:02d}")
    return said


# -- what it learns from ----------------------------------------------------------


def labels(
    session: Session, owner: OwnerId, account: Settings, signal: str
) -> list[tuple[Video, float]]:
    """Every item it has something to say about, and what that is: 0 to 1."""
    since = utcnow() - dt.timedelta(days=max(1, account.algorithm_days))
    seen: dict[int, list[Consumption]] = {}
    for row in session.scalars(
        owned(select(Consumption), Consumption, owner).where(Consumption.at >= since)
    ):
        seen.setdefault(row.video_pk, []).append(row)
    videos = {
        video.id: video
        for video in session.scalars(owned(select(Video), Video, owner).where(Video.id.in_(seen)))
    } if seen else {}

    found: list[tuple[Video, float]] = []
    for pk, rows in seen.items():
        video = videos.get(pk)
        if video is None:
            continue
        value = _label(video, rows, account, signal)
        if value is not None:
            found.append((video, value))

    if signal == "interest":
        # What sat in a feed for days and was never opened says "no" too.
        cutoff = utcnow() - dt.timedelta(days=UNOPENED_AFTER)
        for video in session.scalars(
            owned(select(Video), Video, owner)
            .join(Placement, Placement.video_pk == Video.id)
            .where(
                Placement.added_at.is_not(None),
                Placement.added_at >= since,
                Placement.added_at <= cutoff,
                Video.watched_at.is_(None),
                Video.id.not_in(seen) if seen else Video.id.is_not(None),
            )
            .distinct()
        ):
            found.append((video, 0.0))
    return found


def _label(video: Video, rows: list[Consumption], account: Settings, signal: str) -> float | None:
    longest = max(rows, key=lambda row: row.seconds)
    opened = any(row.clicked or row.finished or row.seconds >= OPENED_AFTER for row in rows)
    if signal == "interest":
        if opened or video.watched_at is not None:
            return 1.0
        return 0.0 if any(row.skipped for row in rows) else None
    if not opened:
        return None
    taken = _retention(video, rows, account)
    if signal == "retention":
        return taken
    pauses = sum(row.pauses for row in rows)
    return round(taken / (1.0 + pauses / 2.0), 4) if longest.seconds > 0 else None


def _retention(video: Video, rows: list[Consumption], account: Settings) -> float:
    """How much of it was taken in, 0 to 1: as far as a video got, or how
    long a post was read against how long it takes."""
    if any(row.finished for row in rows):
        return 1.0
    best = 0.0
    for row in rows:
        if row.reached is not None and row.duration:
            best = max(best, row.reached / row.duration)
        else:
            expected = float(video.view_seconds or account.post_seconds or READ_SECONDS)
            best = max(best, row.seconds / max(1.0, expected))
    return round(min(1.0, best), 4)


# -- learning ----------------------------------------------------------------------


@dataclass
class Learned:
    signal: str
    bias: float
    weights: dict[str, float]
    examples: int
    quality: float | None
    trained_at: dt.datetime

    def predict(self, video: Video) -> float:
        """What it predicts for an item, 0 to 1."""
        total = self.bias + sum(self.weights.get(name, 0.0) for name in features(video))
        return _sigmoid(total)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    shrunk = math.exp(value)
    return shrunk / (1.0 + shrunk)


def fit(examples: list[tuple[list[str], float]], *, seed: int = 7) -> tuple[float, dict[str, float]]:
    """Logistic regression by stochastic gradient descent, on 0-to-1 targets."""
    weights: dict[str, float] = {}
    bias = 0.0
    order = list(range(len(examples)))
    shuffle = random.Random(seed)
    for epoch in range(EPOCHS):
        shuffle.shuffle(order)
        step = STEP / (1.0 + epoch * 0.1)
        for index in order:
            names, target = examples[index]
            guess = _sigmoid(bias + sum(weights.get(name, 0.0) for name in names))
            error = guess - target
            bias -= step * error
            for name in names:
                current = weights.get(name, 0.0)
                weights[name] = current - step * (error + PULL * current)
    kept = sorted(weights.items(), key=lambda pair: -abs(pair[1]))[:MOST_WEIGHTS]
    return bias, {name: round(weight, 5) for name, weight in kept if abs(weight) >= 1e-4}


def train(session: Session, owner: OwnerId, account: Settings, signal: str) -> Learned | None:
    """Learn one signal for an account, keep it, and say what it learned.

    None when there are fewer examples than the account asks for: a model
    from a handful of items would say more about chance than about you.
    """
    found = labels(session, owner, account, signal)
    if len(found) < max(2, account.algorithm_min):
        return None
    examples = [(features(video), value) for video, value in found]

    # A fifth held back to say how well it does, when there are enough.
    quality: float | None = None
    if len(examples) >= 25:
        mixed = list(examples)
        random.Random(11).shuffle(mixed)
        cut = len(mixed) // 5
        held, learn_from = mixed[:cut], mixed[cut:]
        bias, weights = fit(learn_from)
        probe = Learned(signal, bias, weights, len(learn_from), None, utcnow())
        quality = _quality(probe, held, signal)

    bias, weights = fit(examples)
    row = session.scalar(
        owned(select(AlgorithmModel), AlgorithmModel, owner).where(AlgorithmModel.signal == signal)
    )
    if row is None:
        row = AlgorithmModel(owner_pk=owner, signal=signal)
        session.add(row)
    row.weights = json.dumps({"bias": bias, "weights": weights}, sort_keys=True)
    row.examples = len(examples)
    row.quality = quality
    row.trained_at = utcnow()
    session.flush()
    _MODELS.pop((owner, signal), None)
    return Learned(signal, bias, weights, len(examples), quality, row.trained_at)


def _quality(model: Learned, held: list[tuple[list[str], float]], signal: str) -> float:
    def guess(names: list[str]) -> float:
        return _sigmoid(model.bias + sum(model.weights.get(name, 0.0) for name in names))

    if signal == "interest":
        right = sum(1 for names, target in held if (guess(names) >= 0.5) == (target >= 0.5))
        return round(right / len(held), 3)
    error = sum(abs(guess(names) - target) for names, target in held) / len(held)
    return round(1.0 - error, 3)


def due(session: Session, owner: OwnerId, account: Settings) -> bool:
    """Whether an account's algorithm should learn again on this run."""
    if not runs_for(session, account):
        return False
    if account.algorithm_every == "run":
        return True
    newest = session.scalar(
        owned(select(AlgorithmModel.trained_at), AlgorithmModel, owner)
        .order_by(AlgorithmModel.trained_at.desc())
    )
    return newest is None or utcnow() - newest >= dt.timedelta(days=1)


def train_all(session: Session, owner: OwnerId, account: Settings) -> dict[str, Learned | None]:
    return {signal: train(session, owner, account, signal) for signal in LEARNED}


# -- predicting --------------------------------------------------------------------

#: What each account learned, read once and kept until it learns again.
_MODELS: dict[tuple[OwnerId, str], tuple[dt.datetime, Learned]] = {}


def learned(session: Session, owner: OwnerId, signal: str) -> Learned | None:
    """The model an account learned for a signal, if it has one."""
    row = session.scalar(
        owned(select(AlgorithmModel), AlgorithmModel, owner).where(AlgorithmModel.signal == signal)
    )
    if row is None:
        return None
    kept = _MODELS.get((owner, signal))
    if kept is not None and kept[0] == row.trained_at:
        return kept[1]
    try:
        stored = json.loads(row.weights or "{}")
    except ValueError:
        return None
    model = Learned(
        signal=signal,
        bias=float(stored.get("bias", 0.0)),
        weights={str(k): float(v) for k, v in (stored.get("weights") or {}).items()},
        examples=row.examples,
        quality=row.quality,
        trained_at=row.trained_at,
    )
    _MODELS[(owner, signal)] = (row.trained_at, model)
    return model


def score(
    session: Session,
    video: Video,
    piece: GraphNode,
    playlist_pk: int | None = None,
    tags: Iterable[str] = (),
) -> float | None:
    """What an Aggregation piece's algorithm says about an item, 0 to 1 —
    or None when it has nothing to say: switched off, not learned yet, or
    (for saturation) no feed to measure it in.

    `playlist_pk` is the feed the item is on its way to; `tags` are the ones
    a Tag box on its way will put on it, which it does not carry yet.
    """
    from ..db import get_settings

    owner = video.owner_pk
    account = get_settings(session, owner)
    if not runs_for(session, account):
        return None
    said = settings(piece)
    if said["signal"] == "saturation":
        return saturation(session, video, account, said, playlist_pk, tags)
    model = learned(session, owner, str(said["signal"]))
    return None if model is None else model.predict(video)


def saturation(
    session: Session,
    video: Video,
    account: Settings,
    said: Mapping[str, Any],
    playlist_pk: int | None,
    tags: Iterable[str] = (),
) -> float | None:
    """How much room a feed has left for more like this item, 0 to 1.

    "Like it" is its source, or carrying a tag. Room is the share of what you
    open in Focus mode that is like it, against the share of what is waiting
    in this feed that is: a feed already fuller of it than you take in has
    less room, and 1 means as much as you like, or less. Shares are smoothed
    so that a source you have opened once is not taken as all you want.
    """
    if playlist_pk is None:
        return None
    owner = video.owner_pk
    by_tag = said.get("of") == "tag"
    wanted = tag_name_of(str(said.get("tag") or ""))
    if by_tag and not wanted:
        return None
    carried = set(video.tag_list) | {tag_name_of(one) for one in tags}
    if by_tag and wanted not in carried:
        return 1.0  # not like it at all: nothing to crowd

    def alike(one: Video) -> bool:
        return wanted in one.tag_list if by_tag else one.channel_pk == video.channel_pk

    since = utcnow() - dt.timedelta(days=max(1, account.algorithm_days))
    opened = {
        row.video_pk
        for row in session.scalars(
            owned(select(Consumption), Consumption, owner).where(Consumption.at >= since)
        )
        if row.clicked or row.finished or row.seconds >= OPENED_AFTER
    }
    if len(opened) < max(2, account.algorithm_min):
        return None  # too little to know what you like
    seen = list(session.scalars(owned(select(Video), Video, owner).where(Video.id.in_(opened))))
    liked = (sum(1 for one in seen if alike(one)) + 1) / (len(seen) + 2)

    waiting = list(session.scalars(
        owned(select(Video), Video, owner)
        .join(Placement, Placement.video_pk == Video.id)
        .where(
            Placement.playlist_pk == playlist_pk,
            Placement.playlist_item_id.is_not(None),
            Placement.removed_at.is_(None),
            Video.watched_at.is_(None),
        )
    ))
    here = any(one.id == video.id for one in waiting)
    total = len(waiting) + (0 if here else 1)
    crowding = (sum(1 for one in waiting if alike(one)) + (0 if here else 1)) / total
    return round(min(1.0, liked / crowding), 4)


def tag_name_of(raw: str) -> str:
    from .graph.names import tag_name

    return tag_name(raw)


# -- the piece -----------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {"signal": "interest", "least": 50, "most": 100, "of": "source", "tag": ""}


def settings(piece: GraphNode) -> dict[str, Any]:
    """An Aggregation piece's settings: which signal, and the range of it — a
    minimum and a maximum, 0 to 100 — that counts as within."""
    said = dict(DEFAULTS)
    try:
        stored = json.loads(piece.aggregation or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
        # A piece set before ranges had one threshold: that is its minimum.
        if "least" not in stored and isinstance(stored.get("threshold"), int):
            said["least"] = stored["threshold"]
    return said


def _percent(said: str, named: str) -> int:
    if not said.strip().isdigit():
        raise ValueError(f"The {named} is a whole number, 0 to 100.")
    return max(0, min(100, int(said.strip())))


def save(piece: GraphNode, form: Mapping[str, str]) -> None:
    """Set an Aggregation piece from its panel's `aggregation_<setting>` fields."""
    said = settings(piece)
    signal = form.get("aggregation_signal")
    if signal is not None:
        if signal not in dict(SIGNALS):
            raise ValueError("That is not something the algorithm learns.")
        said["signal"] = signal
    of = form.get("aggregation_of")
    if of is not None:
        if of not in dict(SATURATION_OF):
            raise ValueError("Saturation is of a source or a tag.")
        said["of"] = of
    tag = form.get("aggregation_tag")
    if tag is not None:
        said["tag"] = tag_name_of(tag)
    if said["signal"] == "saturation" and said["of"] == "tag" and not said["tag"]:
        raise ValueError("Say which tag's saturation to watch.")
    # The range; `aggregation_threshold` is what a minimum was called before.
    least = form.get("aggregation_least", form.get("aggregation_threshold"))
    if least is not None and str(least).strip():
        said["least"] = _percent(str(least), "minimum")
    most = form.get("aggregation_most")
    if most is not None and str(most).strip():
        said["most"] = _percent(str(most), "maximum")
    if int(said["least"]) > int(said["most"]):
        raise ValueError("The minimum is more than the maximum: nothing could be within it.")
    piece.aggregation = json.dumps(said, sort_keys=True)


def within(predicted: float, said: Mapping[str, Any]) -> bool:
    """Whether a prediction, 0 to 1, is inside a piece's range."""
    return int(said["least"]) <= predicted * 100 <= int(said["most"])


def range_words(said: Mapping[str, Any]) -> str:
    """A piece's range, as said on the canvas: "50% or more", "under 90%", "40–90%"."""
    least, most = int(said["least"]), int(said["most"])
    if most >= 100:
        return f"{least}% or more"
    if least <= 0:
        return f"{most}% or less"
    return f"{least}–{most}%"


def outside_words(said: Mapping[str, Any]) -> str:
    """Outside a range, as said on the canvas: "under 50%", "over 90%", "outside 40–90%"."""
    least, most = int(said["least"]), int(said["most"])
    if most >= 100:
        return f"under {least}%"
    if least <= 0:
        return f"over {most}%"
    return f"outside {least}–{most}%"


def words(piece: GraphNode, host: GraphNode | None) -> str:
    """What an Aggregation piece does, in the terms of the box it is in."""
    said = settings(piece)
    signal, span, outside = str(said["signal"]), range_words(said), outside_words(said)
    if signal == "saturation":
        what = f"“{said['tag']}”" if said["of"] == "tag" else "a source"
        if host is None:
            return f"room for {what}, {span}"
        if host.kind == "filter":
            return f"lets {what} in while this feed has {span} room for it"
        if host.kind == "sort":
            return f"puts {what} later the more it fills this feed ({span} room first)"
        if host.kind == "expire":
            return f"{what} leaves sooner with {outside} room in this feed"
    if host is None:
        return f"{signal}, {span}"
    if host.kind == "filter":
        least, most = int(said["least"]), int(said["most"])
        if most >= 100:
            return f"only what it predicts at {least}% {signal} or more"
        if least <= 0:
            return f"only what it predicts at {most}% {signal} or less"
        return f"only what it predicts at {least}–{most}% {signal}"
    if host.kind == "sort":
        return f"most predicted {signal} first, {span} ahead of the rest"
    if host.kind == "expire":
        return f"{outside} predicted {signal} leaves sooner"
    return f"{signal}, {span}"


def expiry_share(predicted: float | None, said: Mapping[str, Any]) -> float:
    """How much of an Expire box's Timer an item gets: all of it inside the
    range, less the further outside it — under the minimum or over the
    maximum — the prediction falls."""
    if predicted is None:
        return 1.0
    least, most = int(said["least"]) / 100.0, int(said["most"]) / 100.0
    if predicted < least:
        return max(SHORTEST_LIFE, predicted / least) if least > 0 else 1.0
    if predicted > most:
        return max(SHORTEST_LIFE, (1.0 - predicted) / (1.0 - most)) if most < 1 else 1.0
    return 1.0


# -- what it learned, for a person to read -----------------------------------------


@dataclass(frozen=True)
class Leaning:
    named: str
    weight: float


def leanings(
    model: Learned, names: Mapping[int, str], most: int = 6
) -> tuple[list[Leaning], list[Leaning]]:
    """What it leans towards and away from, said in words."""

    def say(feature: str) -> str:
        kind, _, value = feature.partition(":")
        if kind == "source":
            return names.get(int(value), "a source that has gone") if value.isdigit() else value
        if kind == "word":
            return f"“{value}” in the title"
        if kind == "tag":
            return f"tagged {value}"
        if kind == "length":
            return f"{value} long" if value != "unknown" else "length unknown"
        if kind == "hour":
            return f"put up around {value}:00"
        if kind == "kind":
            return {"video": "videos", "post": "posts", "link": "articles and links"}.get(value, value)
        return f"{kind}: {value}"

    ranked = sorted(model.weights.items(), key=lambda pair: -pair[1])
    toward = [Leaning(say(name), weight) for name, weight in ranked[:most] if weight > 0.05]
    away = [Leaning(say(name), weight) for name, weight in reversed(ranked[-most:]) if weight < -0.05]
    return toward, away


def counts(session: Session, owner: OwnerId) -> int:
    """How many times it has seen something opened, for this account."""
    return len(list(session.scalars(owned(select(Consumption.id), Consumption, owner))))


def pieces_in(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    return [node for node in nodes if node.kind == "aggregation"]
