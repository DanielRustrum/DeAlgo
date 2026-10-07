"""Writing with a language model: what a Text box does.

A Text box is wired items or data, and gives out words for a Text leaflet:
what a model wrote from them, told what to write by the box. Which model is
the account's own choice, under Settings → AI model:

* **Claude**, through Anthropic's own SDK;
* **OpenAI**, or **an open-weight model** on a server of one's own — Ollama,
  vLLM, LM Studio, anything that speaks the same chat API — over that API.

A box writes when somebody presses Write now, or by itself on a run, hourly
or daily as it is told. Never when a page is opened: a page that waited on a
model to load would be a slow page, and one that cost money every time it
was looked at.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx
from sqlalchemy.orm import Session

from ..models import GraphNode, Settings, utcnow

log = logging.getLogger(__name__)

#: The kinds of service a model can be reached at, and what each is called.
PROVIDERS: tuple[tuple[str, str], ...] = (
    ("anthropic", "Claude, from Anthropic"),
    ("openai", "OpenAI"),
    ("compatible", "An open-weight model on a server of your own (Ollama, vLLM, LM Studio…)"),
)

#: The model each kind of service uses when none is named.
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "", "compatible": ""}

#: Where OpenAI is, when no other address is given.
OPENAI_URL = "https://api.openai.com/v1"

#: How often a box writes again by itself.
REFRESHES: tuple[tuple[str, str], ...] = (
    ("manual", "Only when I press Write now"),
    ("hourly", "Every hour, on a run"),
    ("daily", "Every day, on a run"),
)
_EVERY = {"hourly": dt.timedelta(hours=1), "daily": dt.timedelta(days=1)}

DEFAULTS: dict[str, Any] = {
    "instructions": "Write a short morning briefing of what came in: a few sentences on what "
                    "stands out, then a list of the most interesting ones and why.",
    "items": 30,
    "refresh": "manual",
}

#: The most items a box sends, and how much of each one's own text goes with it.
MOST_ITEMS = 100
TEXT_PER_ITEM = 600

#: What every model is told, before what the box asks.
SYSTEM = (
    "You write for one person's private newspaper page, from items their own feeds collected. "
    "Write only from the material given: do not invent items, facts, numbers or links. "
    "Write plain prose. You may use short paragraphs separated by blank lines, lines starting "
    "with '## ' for a subheading, and lines starting with '- ' for a list. No other formatting."
)


class WritingError(Exception):
    """Writing did not happen, in words a person can act on."""


@dataclass(frozen=True)
class Model:
    provider: str
    model: str
    base_url: str
    key: str

    @property
    def named(self) -> str:
        return f"{dict(PROVIDERS).get(self.provider, self.provider)} — {self.model}"


def model_for(settings: Settings) -> Model | None:
    """The model an account writes with, or None if it has not chosen one."""
    provider = (settings.ai_provider or "").strip()
    if provider not in dict(PROVIDERS):
        return None
    model = (settings.ai_model or "").strip() or DEFAULT_MODELS.get(provider, "")
    if not model:
        return None
    return Model(provider, model, (settings.ai_base_url or "").strip(), settings.ai_key or "")


# -- what a box is told ------------------------------------------------------------


def settings(node: GraphNode) -> dict[str, Any]:
    said = dict(DEFAULTS)
    try:
        stored = json.loads(node.writing or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
    return said


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a Text box from its panel's `writing_<setting>` fields."""
    said = settings(node)
    instructions = form.get("writing_instructions")
    if instructions is not None:
        said["instructions"] = str(instructions).strip()[:4000] or DEFAULTS["instructions"]
    items = form.get("writing_items")
    if items is not None and str(items).strip():
        if not str(items).strip().isdigit():
            raise WritingError("How many items has to be a whole number.")
        said["items"] = max(1, min(MOST_ITEMS, int(str(items).strip())))
    refresh = form.get("writing_refresh")
    if refresh is not None:
        if refresh not in dict(REFRESHES):
            raise WritingError("That is not how often a box can write.")
        said["refresh"] = refresh
    node.writing = json.dumps(said, sort_keys=True)


def due(node: GraphNode, now: dt.datetime) -> bool:
    """Whether a box should write again by itself on this run."""
    every = _EVERY.get(str(settings(node).get("refresh")))
    if every is None or not node.enabled:
        return False
    return node.written_at is None or now - node.written_at >= every


# -- what it is given -------------------------------------------------------------


def material(value: Any, most: int) -> tuple[str, int, int]:
    """What goes to the model: the first `most` rows, each cut to what is
    worth reading, as JSON — and how many there were, and how many went.

    Cut on purpose and said so, to the model and on the box: a feed of a
    thousand items is not one request's worth of reading.
    """
    from .graph.formatting import rows_of

    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return json.dumps(value), 1, 1
    rows = rows_of(value) if value is not None else []
    sent = [_trim(row) for row in rows[:most]]
    return json.dumps(sent, ensure_ascii=False, indent=1), len(rows), len(sent)


def _trim(row: Any) -> Any:
    """One row with long text cut and empty fields left out."""
    if not isinstance(row, dict):
        return row
    kept: dict[str, Any] = {}
    for key, value in row.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str) and len(value) > TEXT_PER_ITEM:
            value = value[:TEXT_PER_ITEM] + "…"
        elif isinstance(value, dict):
            value = _trim(value)
        kept[key] = value
    return kept


# -- asking the model --------------------------------------------------------------


def write(
    model: Model, instructions: str, material_json: str, *, counted: tuple[int, int],
    system: str = SYSTEM,
) -> str:
    """What the model writes from the material, told what to write."""
    total, sent = counted
    note = (
        f"There are {total} items; the first {sent} are below."
        if total > sent else f"There are {total} items, all below."
    )
    asked = (
        f"{instructions.strip()}\n\n{note}\n\n<material>\n{material_json}\n</material>"
    )
    if model.provider == "anthropic":
        return _claude(model, asked, system)
    return _chat(model, asked, system=system)


def _claude(model: Model, asked: str, system: str = SYSTEM) -> str:
    """Claude, through Anthropic's SDK."""
    client = anthropic.Anthropic(
        api_key=model.key or None,
        base_url=model.base_url or None,
        timeout=180.0,
        max_retries=2,
    )
    extra: dict[str, Any] = {}
    if not model.base_url:
        # If the model declines on safety grounds, Anthropic re-runs the
        # request on a fallback model chosen for that kind of refusal. Only
        # on Anthropic's own API: a proxy at another address may not know it.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        response = client.beta.messages.create(
            model=model.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": asked}],
            output_config={"effort": "medium"},
            **extra,
        )
    except anthropic.AuthenticationError:
        raise WritingError("Anthropic refused the key. Check it under Settings → AI model.") from None
    except anthropic.PermissionDeniedError:
        raise WritingError("That key may not use this model.") from None
    except anthropic.NotFoundError:
        raise WritingError(f"Anthropic has no model called “{model.model}”.") from None
    except anthropic.RateLimitError:
        raise WritingError("Anthropic asked us to slow down. Try again in a minute.") from None
    except anthropic.BadRequestError as exc:
        raise WritingError(f"Anthropic could not take the request: {exc.message}") from None
    except anthropic.APIStatusError as exc:
        raise WritingError(f"Anthropic had a problem ({exc.status_code}). Try again later.") from None
    except anthropic.APIConnectionError:
        raise WritingError("Could not reach Anthropic.") from None
    if response.stop_reason == "refusal":
        raise WritingError("The model declined to write this.")
    text = "\n".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise WritingError("The model wrote nothing.")
    if response.stop_reason == "max_tokens":
        text += "\n\n(It ran out of room before it finished.)"
    return text


def _chat(
    model: Model, asked: str, client: httpx.Client | None = None, *, system: str = SYSTEM,
) -> str:
    """OpenAI, or a server of one's own speaking the same chat API."""
    base = (model.base_url or (OPENAI_URL if model.provider == "openai" else "")).rstrip("/")
    if not base:
        raise WritingError("Say where your model's server is, under Settings → AI model.")
    headers = {"Content-Type": "application/json"}
    if model.key:
        headers["Authorization"] = f"Bearer {model.key}"
    body = {
        "model": model.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": asked},
        ],
    }
    own = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
    try:
        answer = http.post(f"{base}/chat/completions", headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise WritingError(f"Could not reach {base}: {exc}") from None
    finally:
        if own:
            http.close()
    if answer.status_code in (401, 403):
        raise WritingError("The server refused the key. Check it under Settings → AI model.")
    if answer.status_code == 404:
        raise WritingError(f"Nothing answered at {base}/chat/completions, or there is no model "
                           f"called “{model.model}” there.")
    if answer.status_code >= 400:
        raise WritingError(f"The server could not take the request ({answer.status_code}): "
                           f"{answer.text[:300]}")
    try:
        said = answer.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise WritingError("The server's answer was not one this can read.") from None
    text = str(said or "").strip()
    if not text:
        raise WritingError("The model wrote nothing.")
    return text


# -- a box, writing ---------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    text: str
    error: str


def run(session: Session, node: GraphNode, owner: Any, account: Settings) -> Written:
    """Have a Text box write now, keeping what it wrote — or why it could not."""
    from .graph.formatting import data_into, items_into

    model = model_for(account)
    if model is None:
        return _keep(node, "", "Choose a model under Settings → AI model first.")
    said = settings(node)
    has_data = any(edge for edge in _inputs(session, node, owner) if edge == "data")
    value: Any = data_into(session, node, owner) if has_data else items_into(session, node, owner)
    if value is None or value == []:
        return _keep(node, "", "Nothing has come in to write about yet.")
    text_in, total, sent = material(value, int(said["items"]))
    try:
        text = write(model, str(said["instructions"]), text_in, counted=(total, sent))
    except WritingError as exc:
        return _keep(node, "", str(exc))
    return _keep(node, text, "")


def _inputs(session: Session, node: GraphNode, owner: Any) -> list[str]:
    from .graph.reading import edges

    return [edge.carries for edge in edges(session, owner, every=True) if edge.target_pk == node.id]


def _keep(node: GraphNode, text: str, error: str) -> Written:
    """What a box wrote stays until it writes again; a failure keeps the
    last good writing, and says why beside it."""
    said = settings(node)
    if text:
        node.written = text
        node.written_at = utcnow()
        said.pop("error", None)
    node.writing = json.dumps({**said, "error": error} if error else said, sort_keys=True)
    return Written(text=text or (node.written or ""), error=error)


def last_error(node: GraphNode) -> str:
    try:
        stored = json.loads(node.writing or "{}")
    except ValueError:
        return ""
    return str(stored.get("error") or "") if isinstance(stored, dict) else ""


# -- as a page shows it -----------------------------------------------------------


def blocks(text: str) -> list[tuple[str, Any]]:
    """Written text as blocks to set: paragraphs, subheadings and lists."""
    shown: list[tuple[str, Any]] = []
    for chunk in text.replace("\r\n", "\n").split("\n\n"):
        lines = [line.rstrip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        listed: list[str] = []
        prose: list[str] = []
        for line in lines:
            if line.startswith("## "):
                if prose:
                    shown.append(("p", " ".join(prose)))
                    prose = []
                shown.append(("h", line[3:].strip()))
            elif line.lstrip().startswith(("- ", "* ")):
                if prose:
                    shown.append(("p", " ".join(prose)))
                    prose = []
                listed.append(line.lstrip()[2:].strip())
            else:
                if listed:
                    shown.append(("ul", listed))
                    listed = []
                prose.append(line.strip())
        if listed:
            shown.append(("ul", listed))
        if prose:
            shown.append(("p", " ".join(prose)))
    return shown
