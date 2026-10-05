"""A REST API as a source: any JSON endpoint that answers with a list of things.

The host's third kind of its own, beside RSS and Newsletter, and for the same
reason: it belongs to no service. Somebody gives the address of an endpoint
and says, if it needs saying, where in the answer the items are and which of
each item's fields is its title, its link, its date. What comes back is read
into the same `Feed` an RSS feed is, so everything after — filters, sorts,
feeds, Focus — treats it like any other source.

Each of those is a path into the JSON, dots between the steps and numbers for
a place in a list: `data.children`, `images.0.url`. Anything left blank is
looked for under the names APIs usually give it, which is enough for most.

An endpoint that wants a key gets it as one header, sent only to its own
address: with a header set, a redirect is refused rather than followed, so
the key never travels on to wherever the redirect points.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from . import patience
from .syndication import Feed, Item
from .syndication.text import clean_text

#: The most of an answer read. An API that returns more than this in one go
#: is not one to poll every half hour.
MOST_BYTES = 5 * 1024 * 1024

#: The most items kept from one answer: the newest, once sorted.
MOST_ITEMS = 200

#: Where APIs usually put things, tried in order when a path is left blank.
LISTS = ("items", "results", "data", "entries", "posts", "articles", "stories",
         "children", "records", "hits", "list", "feed", "value")
GUESSES: dict[str, tuple[str, ...]] = {
    "id": ("id", "guid", "uuid", "uid", "objectID", "item_id", "key", "slug", "_id"),
    "title": ("title", "name", "headline", "subject", "label", "text"),
    "link": ("url", "link", "href", "permalink", "html_url", "web_url", "uri"),
    "published": ("published_at", "published", "created_at", "created_at_i", "created_utc",
                  "created", "date", "pubDate", "timestamp", "updated_at", "time"),
    "image": ("image", "image_url", "thumbnail", "thumbnail_url", "picture", "cover",
              "photo", "img"),
    "summary": ("summary", "description", "excerpt", "body", "content", "selftext", "abstract"),
}
#: A wrapper some APIs put each item inside: Reddit's `{"kind", "data"}`.
WRAPPERS = ("data", "attributes", "node", "fields", "item")


#: Markup in a summary: shown in a card as words, never as HTML.
_TAG = re.compile(r"<[^>]+>")


def plain_text(raw: str) -> str:
    """Words with any markup taken out, as a feed's summary is."""
    return clean_text(html.unescape(_TAG.sub(" ", raw)))


class RestError(ValueError):
    """What came back is not something a REST source can read, in words."""


@dataclass(frozen=True)
class Mapping:
    """Where in an answer the items are, and which field of each is what."""

    items: str = ""
    id: str = ""
    title: str = ""
    link: str = ""
    published: str = ""
    image: str = ""
    summary: str = ""
    #: One header to send with the request, for an API that wants a key.
    header_name: str = ""
    header_value: str = ""

    @classmethod
    def loads(cls, text: str | None) -> Mapping:
        """A mapping as stored on the channel; an empty one if none is."""
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except ValueError:
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {one.name for one in fields(cls)}
        return cls(**{k: str(v) for k, v in data.items() if k in known and v is not None})

    def dumps(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v}, sort_keys=True)

    def public(self) -> dict[str, str]:
        """Everything but the header's value, which is a secret once set."""
        said = asdict(self)
        said.pop("header_value")
        return said

    def with_header_kept(self, earlier: Mapping) -> Mapping:
        """This mapping, keeping the earlier header value when none was given:
        a secret is not sent back to the page, so a blank field means unchanged."""
        if self.header_name and not self.header_value and earlier.header_name == self.header_name:
            return replace(self, header_value=earlier.header_value)
        return self


@dataclass(frozen=True)
class Found:
    """What a read worked out, for the panel to show: the paths it used."""

    feed: Feed
    paths: dict[str, str]


def fetch(url: str, mapping: Mapping, client: httpx.Client) -> Feed:
    """Read the endpoint at `url` into a feed."""
    return read(url, mapping, client).feed


def read(url: str, mapping: Mapping, client: httpx.Client) -> Found:
    """Read the endpoint, and say which paths it used — guessed ones included."""
    patience.hold(url)
    headers = {"Accept": "application/json"}
    secret = bool(mapping.header_name and mapping.header_value)
    if secret:
        name = mapping.header_name.strip()
        if not name or any(c in name for c in ":\r\n "):
            raise RestError(f"“{mapping.header_name}” is not a header name.")
        if any(c in mapping.header_value for c in "\r\n"):
            raise RestError("A header's value cannot run over more than one line.")
        headers[name] = mapping.header_value
    response = client.get(url, headers=headers, follow_redirects=not secret)
    patience.note(response)
    if secret and response.is_redirect:
        went = response.headers.get("location", "somewhere else")
        raise RestError(
            f"The API answered with a redirect to {went}. With a key set, a redirect is not "
            "followed, so the key cannot travel on: give the address it redirects to."
        )
    response.raise_for_status()
    if len(response.content) > MOST_BYTES:
        raise RestError(f"The answer is over {MOST_BYTES // (1024 * 1024)} MB, too much to poll.")
    try:
        data = response.json()
    except ValueError:
        kind = response.headers.get("content-type", "something else").split(";")[0]
        raise RestError(f"The answer is not JSON (it is {kind}).") from None
    return parse(data, mapping, base=url)


def parse(data: Any, mapping: Mapping, *, base: str = "") -> Found:
    """An answer already read, into a feed. Kept apart from the request so
    the panel's preview and the tests can hand one in."""
    items, items_path = _locate(data, mapping.items)
    paths: dict[str, str] = {"items": items_path}
    read_items: list[Item] = []
    for raw in items[:MOST_ITEMS * 2]:
        if not isinstance(raw, (dict, list)):
            continue
        item, used = _item(raw, mapping, base)
        for name, path in used.items():
            paths.setdefault(name, path)
        if item is not None:
            read_items.append(item)
    if not read_items:
        raise RestError(
            f"Found a list at “{items_path or 'the top'}”, but nothing in it had a title or a link."
            if items else
            f"There is no list of items at “{items_path or 'the top'}”."
        )
    read_items.sort(
        key=lambda one: one.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
    title = ""
    if isinstance(data, dict):
        for name in ("title", "name"):
            if isinstance(data.get(name), str):
                title = data[name]
                break
    return Found(
        feed=Feed(title=title or (urlparse(base).hostname or "REST API"),
                  items=read_items[:MOST_ITEMS]),
        paths=paths,
    )


def walk(data: Any, path: str) -> Any:
    """Follow a dotted path into JSON: `data.children`, `images.0.url`. None if it leads nowhere."""
    here = data
    for step in (part for part in path.split(".") if part != ""):
        if isinstance(here, dict):
            here = here.get(step)
        elif isinstance(here, list) and step.lstrip("-").isdigit():
            index = int(step)
            here = here[index] if -len(here) <= index < len(here) else None
        else:
            return None
        if here is None:
            return None
    return here


def _locate(data: Any, path: str) -> tuple[list[Any], str]:
    """The list of items, at the path given or wherever it most likely is."""
    if path.strip():
        found = walk(data, path.strip())
        if not isinstance(found, list):
            raise RestError(f"“{path}” does not lead to a list in the answer.")
        return found, path.strip()
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        # The usual names first, then one level further in (Reddit's
        # `data.children`), then any list of objects at all.
        for name in LISTS:
            if _is_items(data.get(name)):
                return data[name], name
        for outer, inner in data.items():
            if isinstance(inner, dict):
                for name in LISTS:
                    if _is_items(inner.get(name)):
                        return inner[name], f"{outer}.{name}"
        for name, value in data.items():
            if _is_items(value):
                return value, name
    raise RestError("No list of items could be found in the answer. Say where it is.")


def _is_items(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(one, dict) for one in value)


def _field(raw: Any, name: str, given: str) -> tuple[Any, str]:
    """One field of an item: from its path, or from where it usually is."""
    if given.strip():
        return walk(raw, given.strip()), given.strip()
    if not isinstance(raw, dict):
        return None, ""
    places: list[tuple[dict[str, Any], str]] = [(raw, "")]
    for wrapper in WRAPPERS:
        if isinstance(raw.get(wrapper), dict):
            places.append((raw[wrapper], f"{wrapper}."))
    for place, prefix in places:
        for candidate in GUESSES[name]:
            value = place.get(candidate)
            if value not in (None, "", [], {}):
                return value, prefix + candidate
    return None, ""


def _item(raw: Any, mapping: Mapping, base: str) -> tuple[Item | None, dict[str, str]]:
    used: dict[str, str] = {}
    values: dict[str, Any] = {}
    for name in GUESSES:
        value, path = _field(raw, name, getattr(mapping, name))
        if path:
            used[name] = path
        values[name] = value

    title = _text(values["title"])
    link = _link(values["link"], base)
    if not title and not link:
        return None, used
    published = _when(values["published"])
    image = _link(_picture(values["image"]), base)
    summary = _text(values["summary"])
    ident = _text(values["id"]) or link or hashlib.sha1(
        f"{title}|{published.isoformat() if published else ''}".encode()
    ).hexdigest()
    return Item(
        guid=ident[:500],
        title=(title or link or "")[:500],
        link=link,
        published_at=published,
        summary=plain_text(summary)[:5000] if summary else None,
        thumbnail_url=image,
        images=[image] if image else [],
    ), used


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        # APIs often send titles HTML-escaped: Reddit's "&amp;".
        return html.unescape(value).strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        # A rendered/raw pair, as WordPress gives a title.
        for name in ("rendered", "text", "value", "raw"):
            if isinstance(value.get(name), str):
                return plain_text(value[name]).strip()
    return ""


def _picture(value: Any) -> Any:
    """A picture field can be an address, a list of them, or an object with one."""
    if isinstance(value, list) and value:
        return _picture(value[0])
    if isinstance(value, dict):
        for name in ("url", "src", "href", "source"):
            if isinstance(value.get(name), str):
                return value[name]
        return None
    return value


def _link(value: Any, base: str) -> str | None:
    """An http(s) address, made whole against the endpoint's own."""
    text = _text(value)
    if not text:
        return None
    whole = urljoin(base, text) if base else text
    return whole if urlparse(whole).scheme in ("http", "https") else None


def _when(value: Any) -> dt.datetime | None:
    """A date as APIs give one: ISO text, an email-style date, or seconds or
    milliseconds since 1970."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    numeric = isinstance(value, str) and value.strip().replace(".", "", 1).isdigit()
    if isinstance(value, (int, float)) or numeric:
        number = float(value)
        if number > 1e11:  # milliseconds
            number /= 1000
        try:
            return dt.datetime.fromtimestamp(number, tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None
