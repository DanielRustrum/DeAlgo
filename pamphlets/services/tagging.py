"""Tag boxes that choose: which of several tags fit each item, by what it is.

A Tag box puts one tag on everything that passes. Told to choose instead,
it is given a few tags — each with a few words on what it means — and puts
on each item the ones that fit it: for a source that sends more than one
kind of thing, a channel of both reviews and news, say.

It chooses one of two ways:

* With a model chosen under Settings → AI model, it asks that model — a
  batch of items at a time, once per run, not once per item.
* Otherwise, on this machine: from the tags' own words, and from what it
  learns of the items already carrying them — the same small model the
  algorithm of one's own uses, one per tag.

What it chose is kept on the item, by box, so an item is judged once.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GraphNode, Settings, Video, utcnow
from . import algorithm, writing
from .graph.names import tag_name
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

MODES: tuple[tuple[str, str], ...] = (
    ("fixed", "Mark everything with one tag"),
    ("choose", "Choose from these tags, by what each item is"),
)
ENGINES: tuple[tuple[str, str], ...] = (
    ("auto", "Your AI model, if you have chosen one; otherwise on this machine"),
    ("local", "On this machine only"),
)
DEFAULTS: dict[str, Any] = {"mode": "fixed", "tags": [], "least": 0, "most": 2, "engine": "auto"}

#: How sure it has to be, 0 to 1, to put a tag on.
SURE = 0.6

#: Items asked about in one request to a model.
BATCH = 40

#: Examples a tag needs, each way, before it is learned rather than matched by its words.
LEARN_FROM = 5

_WORD = re.compile(r"[a-z0-9]{3,}")

SYSTEM = (
    "You sort items from someone's feeds into tags they have defined. For each item, choose "
    "only from the tags given, only those that clearly fit, at most the number allowed — "
    "possibly none. Answer with JSON only: an object mapping each item's id to a list of tag "
    "names. No other text."
)


@dataclass(frozen=True)
class Choice:
    name: str
    about: str


def settings(node: GraphNode) -> dict[str, Any]:
    said = dict(DEFAULTS)
    try:
        stored = json.loads(node.tag_choices or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
    return said


def choosing(node: GraphNode) -> bool:
    return node.kind == "tag" and settings(node)["mode"] == "choose"


def choices(node: GraphNode) -> list[Choice]:
    found = []
    for entry in settings(node)["tags"]:
        if isinstance(entry, dict) and tag_name(str(entry.get("name") or "")):
            found.append(Choice(tag_name(str(entry["name"])), str(entry.get("about") or "")[:300]))
    return found


def read_lines(text: str) -> list[dict[str, str]]:
    """Tags as typed, one per line: `name — what it means` (or `name: …`)."""
    found: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = re.split(r"\s+[—–-]\s+|:\s*", line.strip(), maxsplit=1)
        name, about = parts[0], (parts[1] if len(parts) > 1 else "")
        named = tag_name(name)
        if named and all(one["name"] != named for one in found):
            found.append({"name": named, "about": about.strip()[:300]})
    return found[:20]


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a Tag box's choosing from its panel's `tagging_<setting>` fields."""
    said = settings(node)
    mode = form.get("tagging_mode")
    if mode is not None:
        if mode not in dict(MODES):
            raise ValueError("A Tag box marks with one tag, or chooses.")
        said["mode"] = mode
    tags = form.get("tagging_tags")
    if tags is not None:
        said["tags"] = read_lines(tags)
    most = form.get("tagging_most")
    if most is not None and str(most).strip():
        if not str(most).strip().isdigit():
            raise ValueError("How many tags is a whole number.")
        said["most"] = max(1, min(10, int(str(most).strip())))
    least = form.get("tagging_least")
    if least is not None and str(least).strip():
        if not str(least).strip().isdigit():
            raise ValueError("How many tags is a whole number.")
        said["least"] = max(0, min(10, int(str(least).strip())))
    if int(said["least"]) > int(said["most"]):
        raise ValueError("At least is more than at most: no item could have that many.")
    engine = form.get("tagging_engine")
    if engine is not None:
        if engine not in dict(ENGINES):
            raise ValueError("That is not a way it can choose.")
        said["engine"] = engine
    if said["mode"] == "choose" and not said["tags"]:
        raise ValueError("Give it at least one tag to choose from, one per line.")
    node.tag_choices = json.dumps(said, sort_keys=True)


def words(node: GraphNode) -> str:
    named = ", ".join(choice.name for choice in choices(node))
    if not named:
        return "give it tags to choose from"
    said = settings(node)
    least, most = int(said["least"]), int(said["most"])
    how_many = f"{least}–{most} " if least > 0 and least != most else (f"{most} " if least == most else "")
    return f"chooses {how_many}from {named}"


def engine_for(session: Session, node: GraphNode, account: Settings) -> writing.Model | None:
    """The model a box asks, or None when it chooses on this machine."""
    if settings(node)["engine"] == "local":
        return None
    return writing.model_for(account)


# -- what an item was given --------------------------------------------------------


def chosen(session: Session, video: Video, node: GraphNode) -> list[str]:
    """The tags a choosing box put — or will put — on an item.

    Kept on the item by box. Not chosen yet, it is chosen now, on this
    machine: a model is only asked in the batch before a run fills its feeds.
    """
    kept = _kept(video).get(str(node.id))
    if kept is not None:
        return kept
    picked = _local(session, video.owner_pk, node, [video]).get(video.id, [])
    _keep(video, node, picked)
    return picked


def _kept(video: Video) -> dict[str, list[str]]:
    try:
        stored = json.loads(video.classified or "{}")
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


def _keep(video: Video, node: GraphNode, tags: list[str]) -> None:
    kept = _kept(video)
    kept[str(node.id)] = tags
    video.classified = json.dumps(kept, sort_keys=True)


# -- choosing, a batch at a time ----------------------------------------------------


def choose_before_filling(
    session: Session, owner: OwnerId, account: Settings, routes: Iterable[Any]
) -> int:
    """Have every choosing box choose for the items waiting to go down its
    paths, before they are judged: a model is asked once per batch, not once
    per item. Answers how many items were tagged."""
    boxes: dict[int, tuple[GraphNode, set[int]]] = {}
    for route in routes:
        for stamp in route.stamps:
            if choosing(stamp) and stamp.enabled:
                boxes.setdefault(stamp.id, (stamp, set()))[1].add(route.channel.id)
    done = 0
    for node, channels in boxes.values():
        waiting = [
            video for video in session.scalars(
                owned(select(Video), Video, owner).where(
                    Video.status == "pending", Video.channel_pk.in_(channels)
                )
            )
            if str(node.id) not in _kept(video)
        ]
        if not waiting:
            continue
        model = engine_for(session, node, account)
        picked: dict[int, list[str]] = {}
        if model is not None:
            for start in range(0, len(waiting), BATCH):
                part = waiting[start:start + BATCH]
                try:
                    picked.update(_asked(model, node, part))
                except writing.WritingError as exc:
                    log.warning("Tag box %s could not ask its model: %s", node.id, exc)
                    picked.update(_local(session, owner, node, part))
        else:
            picked = _local(session, owner, node, waiting)
        for video in waiting:
            _keep(video, node, picked.get(video.id, []))
            done += 1
    session.flush()
    return done


def _asked(model: writing.Model, node: GraphNode, videos: list[Video]) -> dict[int, list[str]]:
    """Ask the account's model which tags fit each of a batch of items."""
    allowed = choices(node)
    least, most = int(settings(node)["least"]), int(settings(node)["most"])
    listing = "\n".join(f"- {one.name}: {one.about or '(no description)'}" for one in allowed)
    items = [
        {"id": video.id, "title": video.title, "source": video.channel.title if video.channel else "",
         "kind": video.kind, "text": (video.body or "")[:400]}
        for video in videos
    ]
    answer = writing.write(
        model,
        f"Tags, with what each means:\n{listing}\n\n"
        + (f"At least {least} and at most {most} tags per item: the best fitting." if least
           else f"At most {most} tags per item."),
        json.dumps(items, ensure_ascii=False),
        counted=(len(items), len(items)),
        system=SYSTEM,
    )
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        raise writing.WritingError("The model's answer was not JSON.")
    try:
        said = json.loads(answer[start:end + 1])
    except ValueError:
        raise writing.WritingError("The model's answer was not JSON.") from None
    names = {one.name for one in allowed}
    picked: dict[int, list[str]] = {}
    for key, tags in (said.items() if isinstance(said, dict) else []):
        if not str(key).isdigit() or not isinstance(tags, list):
            continue
        kept = [tag_name(str(tag)) for tag in tags if tag_name(str(tag)) in names]
        picked[int(key)] = list(dict.fromkeys(kept))[:most]
    if least:
        # Short of the least it was told: made up from the best guesses here.
        short = [video for video in videos if len(picked.get(video.id, [])) < least]
        if short:
            guessed = _local(session_of(short[0]), short[0].owner_pk, node, short)
            for video in short:
                have = picked.get(video.id, [])
                extra = [tag for tag in guessed.get(video.id, []) if tag not in have]
                picked[video.id] = (have + extra)[:max(least, len(have))]
    return picked


def session_of(video: Video) -> Session:
    from sqlalchemy.orm import object_session

    session = object_session(video)
    if session is None:
        raise writing.WritingError("That item is not in a session.")
    return session


def _local(session: Session, owner: OwnerId, node: GraphNode, videos: list[Video]) -> dict[int, list[str]]:
    """Which tags fit, judged here: by the tags' own words, and — where there
    are enough items carrying a tag already — by what it learned from them."""
    allowed = choices(node)
    least, most = int(settings(node)["least"]), int(settings(node)["most"])
    learned = {one.name: _learn(session, owner, one, allowed) for one in allowed}
    picked: dict[int, list[str]] = {}
    for video in videos:
        text = set(_WORD.findall(f"{video.title or ''} {video.body or ''}".lower()))
        scores = []
        for one in allowed:
            cue = _cues(one)
            matched = 0.9 if cue & text else 0.0
            model = learned.get(one.name)
            predicted = model.predict(video) if model is not None else 0.0
            scores.append((max(matched, predicted), one.name))
        ranked = sorted(scores, key=lambda pair: (-pair[0], [o.name for o in allowed].index(pair[1])))
        # The sure ones, up to the most; then, if that is fewer than the
        # least, the likeliest of the rest until there are enough.
        sure = [name for value, name in ranked if value >= SURE][:most]
        rest = [name for _, name in ranked if name not in sure]
        picked[video.id] = sure + rest[: max(0, least - len(sure))]
    return picked


def _cues(choice: Choice) -> set[str]:
    """The words that, in an item's title or text, say a tag fits."""
    said = set(_WORD.findall(f"{choice.name} {choice.about}".lower()))
    return {word for word in said if word not in algorithm._STOP}


def _learn(session: Session, owner: OwnerId, choice: Choice, allowed: list[Choice]) -> algorithm.Learned | None:
    """A model of one tag, from items carrying it against items carrying
    another of the box's tags and not it. None with too few of either."""
    others = {one.name for one in allowed if one.name != choice.name}
    positives: list[Video] = []
    negatives: list[Video] = []
    for video in session.scalars(
        owned(select(Video), Video, owner).where(Video.tags.is_not(None)).order_by(Video.id.desc()).limit(3000)
    ):
        carried = set(video.tag_list)
        if choice.name in carried:
            positives.append(video)
        elif carried & others:
            negatives.append(video)
    if len(positives) < LEARN_FROM or len(negatives) < LEARN_FROM:
        return None
    examples = [(algorithm.features(video), 1.0) for video in positives]
    examples += [(algorithm.features(video), 0.0) for video in negatives]
    bias, weights = algorithm.fit(examples)
    return algorithm.Learned(choice.name, bias, weights, len(examples), None, utcnow())


def tags_for(session: Session, video: Video, stamps: Iterable[GraphNode]) -> list[str]:
    """Every tag the Tag boxes on a path put on an item: the fixed ones, and
    the ones a choosing box chose for it."""
    from . import graph

    boxes = list(stamps)
    found = list(graph.stamped_tags(boxes))
    for node in boxes:
        if choosing(node) and node.enabled:
            found += [tag for tag in chosen(session, video, node) if tag not in found]
    return found
