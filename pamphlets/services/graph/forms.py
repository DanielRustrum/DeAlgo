"""Forms: a Form leaflet, the Input pieces under it, and the queue it sends into.

A **Form leaflet** shows a form on its pamphlet's page. Its fields are the
**Input** pieces stacked under it on the canvas — text, long text, number,
date, choice, checkbox — asked in the order they are stacked. Each has a
name (what it is filed under, and read as `{{ name }}`), a label, whether it
must be filled in, and a pattern it must match: a regular expression, so
`[A-Z]{2}\\d{4}` asks for two capitals and four digits.

What is sent is checked against every field — here, whatever the browser
already checked — and goes into a **queue**, named on the Form leaflet. An
**Input source** of the same name takes what is waiting each time it is
polled, once each, and sends it down its paths as an item: its title is the
field the source says, and every field is listed in its words. Several forms
can send into one queue, and each queue is its own source.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import FormSubmission, GraphNode, utcnow
from ..scope import OwnerId, owned
from .errors import GraphError
from .names import store_name
from .vocabulary import INPUT_KINDS

#: What a field may be called: what it is filed under and read by.
NAME = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
#: How long a pattern, and a value, may be.
MOST_PATTERN = 300
MOST_VALUE = {"input-long": 10000}
MOST_SHORT = 1000

#: Every field's settings, and what each starts as.
DEFAULTS: dict[str, Any] = {
    "name": "", "label": "", "required": False, "pattern": "", "hint": "",
    "placeholder": "", "options": "", "min": "", "max": "",
}

#: What each kind of input is, in words, for the canvas.
KIND_WORDS = {
    "input-text": "text", "input-long": "long text", "input-number": "number",
    "input-date": "date", "input-choice": "choice", "input-check": "checkbox",
}


def is_input(node: GraphNode) -> bool:
    return node.kind in INPUT_KINDS


def field(node: GraphNode) -> dict[str, Any]:
    """An Input piece's settings, every one filled in; its name falls back to
    one made from its id, so a field nobody named is still filed somewhere."""
    said: dict[str, Any] = dict(DEFAULTS)
    try:
        stored = json.loads(node.form_field or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
    said["name"] = said["name"] or f"field_{node.id}"
    said["label"] = said["label"] or said["name"].replace("_", " ").capitalize()
    said["kind"] = node.kind
    return said


def options(said: Mapping[str, Any]) -> list[str]:
    """A choice's options: a line each, blank lines dropped."""
    return [line.strip() for line in str(said.get("options") or "").splitlines() if line.strip()]


def save_field(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set an Input piece from its panel's `field_<setting>` fields. Refused,
    in words, for a name it cannot be read by or a pattern that is not one."""
    if not is_input(node):
        raise GraphError("Only an Input piece is a form's field.")
    # What is stored, not what is shown: a name or label filled in for
    # showing must not be saved as though somebody had typed it.
    said: dict[str, Any] = dict(DEFAULTS)
    try:
        stored = json.loads(node.form_field or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})

    def given(name: str) -> str | None:
        value = form.get(f"field_{name}")
        return None if value is None else str(value)

    name = given("name")
    if name is not None:
        name = name.strip().lower()
        if name and not NAME.match(name):
            raise GraphError(f"“{name}” cannot be a field's name: letters, digits and _, starting with a letter.")
        said["name"] = name
    for key, most in (("label", 120), ("hint", 300), ("placeholder", 120), ("options", 4000)):
        value = given(key)
        if value is not None:
            said[key] = value.strip()[:most]
    if form.get("field_form") == "1":
        # An unticked box is not sent at all: the panel says it carried one.
        said["required"] = form.get("field_required") == "1"
    pattern = given("pattern")
    if pattern is not None:
        pattern = pattern.strip()[:MOST_PATTERN]
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise GraphError(f"That pattern is not a regular expression: {exc}.") from exc
        said["pattern"] = pattern
    for bound in ("min", "max"):
        value = given(bound)
        if value is not None:
            value = value.strip()
            if value:
                try:
                    float(value)
                except ValueError as exc:
                    raise GraphError(f"The {bound}imum is a number.") from exc
            said[bound] = value
    if node.kind == "input-choice" and given("options") is not None and not options(said):
        raise GraphError("A choice needs something to choose: an option on each line.")
    node.form_field = json.dumps(said, sort_keys=True)


def words(node: GraphNode) -> str:
    """An Input piece on the canvas: its label, its kind, and what it asks."""
    said = field(node)
    parts = [f"“{said['label']}”", KIND_WORDS.get(node.kind, "input")]
    if said["required"]:
        parts.append("required")
    if said["pattern"]:
        parts.append(f"matches /{said['pattern']}/")
    return " · ".join(parts)


def fields_of(all_nodes: list[GraphNode], form: GraphNode) -> list[GraphNode]:
    """A Form leaflet's fields, in the order they are stacked under it."""
    under: dict[int, list[GraphNode]] = {}
    for node in sorted(all_nodes, key=lambda one: one.id):
        if is_input(node) and node.attached_to is not None:
            under.setdefault(node.attached_to, []).append(node)
    found: list[GraphNode] = []
    seen: set[int] = set()

    def walk(host: int) -> None:
        for one in under.get(host, []):
            if one.id in seen:
                continue
            seen.add(one.id)
            found.append(one)
            walk(one.id)

    walk(form.id)
    return [one for one in found if one.enabled]


def form_of(all_nodes: list[GraphNode], node: GraphNode) -> GraphNode | None:
    """The Form leaflet an Input piece — or a chain of them — hangs from."""
    by_id = {one.id: one for one in all_nodes}
    walk: GraphNode | None = node
    seen: set[int] = set()
    while walk is not None and walk.id not in seen:
        seen.add(walk.id)
        if walk.kind == "leaflet-form":
            return walk
        if not is_input(walk):
            return None
        walk = by_id.get(walk.attached_to) if walk.attached_to else None
    return None


def check(fields: list[GraphNode], given: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """What was sent, checked against every field: the values to keep, and
    what is wrong with each field that is wrong, in words."""
    values: dict[str, str] = {}
    wrong: dict[str, str] = {}
    for node in fields:
        said = field(node)
        name = said["name"]
        raw = given.get(name)
        value = "" if raw is None else str(raw).strip()
        if node.kind == "input-check":
            value = "yes" if value in ("1", "on", "yes", "true") else "no"
            if said["required"] and value != "yes":
                wrong[name] = "Tick this to send the form."
            values[name] = value
            continue
        if len(value) > MOST_VALUE.get(node.kind, MOST_SHORT):
            wrong[name] = "That is too long."
        elif value == "":
            if said["required"]:
                wrong[name] = "This needs filling in."
        elif node.kind == "input-number":
            try:
                number = float(value)
            except ValueError:
                wrong[name] = "That is not a number."
            else:
                if said["min"] and number < float(said["min"]):
                    wrong[name] = f"At least {said['min']}."
                elif said["max"] and number > float(said["max"]):
                    wrong[name] = f"At most {said['max']}."
        elif node.kind == "input-date":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                wrong[name] = "That is not a date."
        elif node.kind == "input-choice" and value not in options(said):
            wrong[name] = "Choose one of these."
        if name not in wrong and value and said["pattern"]:
            try:
                matched = re.fullmatch(said["pattern"], value) is not None
            except re.error:
                matched = True  # a pattern saved before it was checked: no opinion
            if not matched:
                wrong[name] = said["hint"] or "That is not in the form this asks for."
        values[name] = value
    return values, wrong


def submit(session: Session, owner: OwnerId, form: GraphNode, values: Mapping[str, str]) -> FormSubmission:
    """Put a checked form into its queue."""
    from .leaflets import settings

    queue = store_name(str(settings(form).get("queue") or ""))
    if not queue:
        raise GraphError("This form sends nowhere yet: name its queue on the canvas.")
    sent = FormSubmission(owner_pk=owner, queue=queue, form_pk=form.id, fields=json.dumps(dict(values)))
    session.add(sent)
    session.flush()
    return sent


# -- the Input source's side --------------------------------------------------


def queue_of_key(key: str) -> str:
    """The queue an Input source takes from, from its key (`input:<queue>`)."""
    return store_name(key.split(":", 1)[1] if key.startswith("input:") else key)


def take(session: Session, owner: OwnerId, queue: str) -> list[FormSubmission]:
    """Everything waiting in a queue, oldest first, marked taken."""
    waiting = list(session.scalars(
        owned(select(FormSubmission), FormSubmission, owner)
        .where(FormSubmission.queue == queue, FormSubmission.taken_at.is_(None))
        .order_by(FormSubmission.submitted_at, FormSubmission.id)
    ))
    now = utcnow()
    for one in waiting:
        one.taken_at = now
    session.flush()
    return waiting


def values_of(sent: FormSubmission) -> dict[str, str]:
    try:
        said = json.loads(sent.fields or "{}")
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in said.items()} if isinstance(said, dict) else {}


def rows(session: Session, owner: OwnerId, queue: str, most: int = 500) -> list[dict[str, Any]]:
    """Every submission to a queue, newest first, as rows of data: its
    fields, and when it was sent."""
    found = session.scalars(
        owned(select(FormSubmission), FormSubmission, owner)
        .where(FormSubmission.queue == queue)
        .order_by(FormSubmission.submitted_at.desc(), FormSubmission.id.desc())
        .limit(most)
    )
    return [{**values_of(one), "submitted": one.submitted_at.isoformat()} for one in found]
