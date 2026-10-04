"""A theme: what one account changed, checked.

Only what differs from the defaults is kept. A theme that changes nothing is
empty, and a default changed in a later release reaches everyone who never
touched it.

Everything here is a gate. A theme arrives from a form, from an imported file
or from the database, and each path goes through `parse`, which accepts a
known name with a value of the one shape that name allows and refuses
anything else by name. Nothing that leaves here can be anything but a hex
colour, a number between known limits, or a key from a fixed list — which is
what lets css.py write it into a stylesheet.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .tokens import CHOICE_BY_NAME, COLOUR_BY_NAME, COLOURS, DIAL_BY_NAME, DIALS, MODES

#: What an exported theme file says it is, and which shape it is in.
FORMAT = "dealgo-theme"
VERSION = 1

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


class ThemeError(ValueError):
    """A theme that cannot be used, with every reason why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Theme:
    """One account's changes. Empty is the stock look."""

    #: Per mode, colour name to `#rrggbb`.
    colours: dict[str, dict[str, str]] = field(
        default_factory=lambda: {mode: {} for mode in MODES}
    )
    dials: dict[str, float] = field(default_factory=dict)
    choices: dict[str, str] = field(default_factory=dict)

    def colour(self, mode: str, name: str) -> str:
        """What a colour is in one mode, following another where it does by default."""
        own = self.colours[mode].get(name)
        if own is not None:
            return own
        token = COLOUR_BY_NAME[name]
        if token.follows:
            return self.colour(mode, token.follows)
        return token.default(mode)

    def resolved(self, mode: str) -> dict[str, str]:
        """Every colour in one mode, changed or not."""
        return {token.name: self.colour(mode, token.name) for token in COLOURS}

    def dial(self, name: str) -> float:
        return self.dials.get(name, DIAL_BY_NAME[name].default)

    def choice(self, name: str) -> str:
        return self.choices.get(name, CHOICE_BY_NAME[name].default)

    def is_empty(self) -> bool:
        return not (any(self.colours.values()) or self.dials or self.choices)

    def to_json(self) -> dict[str, Any]:
        """The theme as a file: only what it changes, under a name that says what it is."""
        out: dict[str, Any] = {FORMAT: VERSION}
        colours = {mode: dict(sorted(values.items())) for mode, values in self.colours.items() if values}
        if colours:
            out["colours"] = colours
        if self.dials:
            out["dials"] = dict(sorted(self.dials.items()))
        if self.choices:
            out["choices"] = dict(sorted(self.choices.items()))
        return out

    def dumps(self) -> str:
        return json.dumps(self.to_json(), sort_keys=True)


def normal_hex(value: str) -> str | None:
    """`#abc`, `ABCDEF` or `#a1b2c3` as `#a1b2c3`; None for anything else."""
    match = _HEX.match(value.strip())
    if not match:
        return None
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def parse(data: Any) -> Theme:
    """A theme from its JSON shape, or ThemeError naming everything wrong with it.

    Values equal to the default are dropped rather than kept: a theme holds
    only what it changes.
    """
    if not isinstance(data, Mapping):
        raise ThemeError(["A theme is a JSON object."])
    problems: list[str] = []
    theme = Theme()

    known = {FORMAT, "colours", "dials", "choices", "name"}
    for key in data:
        if key not in known:
            problems.append(f"“{key}” is not part of a theme.")
    if FORMAT in data and data[FORMAT] != VERSION:
        problems.append(f"This theme is version {data[FORMAT]!r}; this De-Algo reads version {VERSION}.")

    colours = data.get("colours", {})
    if not isinstance(colours, Mapping):
        problems.append("“colours” must map light and dark to colours.")
        colours = {}
    for mode, values in colours.items():
        if mode not in MODES:
            problems.append(f"“{mode}” is not light or dark.")
            continue
        if not isinstance(values, Mapping):
            problems.append(f"The {mode} colours must map names to colours.")
            continue
        for name, value in values.items():
            token = COLOUR_BY_NAME.get(name)
            if token is None:
                problems.append(f"There is no colour called “{name}”.")
                continue
            hex_value = normal_hex(value) if isinstance(value, str) else None
            if hex_value is None:
                problems.append(f"{token.label} ({mode}) is not a colour like #1a2b3c.")
                continue
            theme.colours[mode][name] = hex_value

    dials = data.get("dials", {})
    if not isinstance(dials, Mapping):
        problems.append("“dials” must map names to numbers.")
        dials = {}
    for name, value in dials.items():
        dial = DIAL_BY_NAME.get(name)
        if dial is None:
            problems.append(f"There is no setting called “{name}”.")
            continue
        number = _number(value)
        if number is None or number != number:  # NaN is not a number worth keeping
            problems.append(f"{dial.label} must be a number.")
            continue
        if not dial.minimum <= number <= dial.maximum:
            problems.append(
                f"{dial.label} must be between {dial.minimum:g} and {dial.maximum:g}."
            )
            continue
        if number != dial.default:
            theme.dials[name] = round(number, 4)

    choices = data.get("choices", {})
    if not isinstance(choices, Mapping):
        problems.append("“choices” must map names to options.")
        choices = {}
    for name, value in choices.items():
        choice = CHOICE_BY_NAME.get(name)
        if choice is None:
            problems.append(f"There is no setting called “{name}”.")
            continue
        if value not in choice.keys():
            problems.append(f"{choice.label} cannot be “{value}”.")
            continue
        if value != choice.default:
            theme.choices[name] = value

    if problems:
        raise ThemeError(problems)

    # A colour set to what it would be anyway is not a change. Done after the
    # rest, so one that follows another compares against that one's new value.
    for mode in MODES:
        for name in list(theme.colours[mode]):
            value = theme.colours[mode].pop(name)
            if theme.colour(mode, name) != value:
                theme.colours[mode][name] = value
    return theme


def loads(text: str) -> Theme:
    """A theme from JSON text, as stored or as a file someone shared."""
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        raise ThemeError(["That is not readable JSON."]) from None
    return parse(data)


def from_form(form: Mapping[str, Any]) -> Theme:
    """A theme from the Theming page's form.

    Colours arrive as `light.<name>` and `dark.<name>`; a colour that follows
    another by default comes with a `follow.<mode>.<name>` box, and while that
    is ticked its own value is ignored. Dials arrive under their own names,
    and choices likewise.
    """
    colours: dict[str, dict[str, str]] = {mode: {} for mode in MODES}
    for token in COLOURS:
        for mode in MODES:
            value = form.get(f"{mode}.{token.name}")
            if not isinstance(value, str) or not value:
                continue
            if token.follows and form.get(f"follow.{mode}.{token.name}"):
                continue
            colours[mode][token.name] = value
    dials = {dial.name: form[dial.name] for dial in DIALS if form.get(dial.name) not in (None, "")}
    choices = {
        name: form[name] for name in CHOICE_BY_NAME if form.get(name) not in (None, "")
    }
    return parse({"colours": colours, "dials": dials, "choices": choices})
