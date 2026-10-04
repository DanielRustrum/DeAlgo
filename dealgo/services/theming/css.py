"""A theme as the few lines of CSS that put it on the page.

The stylesheet already declares every variable with its default (tokens.css).
This writes only the overrides, in a `<style>` after it, plus the attributes
the root element needs for the choices that are not variables at all.

Safe to put into a page as it stands: every value comes through theme.parse,
so each is a `#rrggbb`, a number formatted here, or a font stack from the
fixed list in tokens.py. Nothing a person typed reaches this text unchecked.
"""

from __future__ import annotations

from dataclasses import dataclass

from .theme import Theme
from .tokens import CHOICES, COLOURS, DIALS, FONTS, SHADOW

#: The dials that are stylesheet variables. Depth is not one: it is worked
#: into the shadow colour.
_VARIABLE_DIALS = tuple(dial for dial in DIALS if dial.name != "depth")


@dataclass(frozen=True)
class PageTheme:
    """What base.html puts on every page for one account."""

    css: str
    #: data-* attributes for <html>, in order.
    attributes: tuple[tuple[str, str], ...]
    #: The browser's own chrome colour (`theme-color`) by day and by night.
    chrome_light: str
    chrome_dark: str
    #: Which set of plants the page draws (tokens.py's "drawings" choice).
    drawings: str = "garden"


def _number(value: float) -> str:
    """A number as CSS wants it: no exponent, no trailing zeros."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _shadow(mode: str, depth: float) -> str:
    red, green, blue, alpha = SHADOW[mode]
    return f"rgba({red}, {green}, {blue}, {_number(min(alpha * depth, 0.9))})"


def _block(selector: str, declarations: list[str]) -> str:
    if not declarations:
        return ""
    return selector + " {\n  " + ";\n  ".join(declarations) + ";\n}\n"


def declarations(theme: Theme, mode: str, *, every_colour: bool = False) -> list[str]:
    """One mode's colour declarations.

    Only the colours this theme changes, unless `every_colour`: a mode that
    is forced has no stylesheet block of its own to fall back on, so it
    states them all.
    """
    out = []
    for token in COLOURS:
        own = theme.colours[mode].get(token.name)
        if own is not None:
            out.append(f"--{token.name}: {own}")
        elif every_colour and not token.follows:
            out.append(f"--{token.name}: {token.default(mode)}")
        elif mode == "dark" and token.name in theme.colours["light"]:
            # Changed by day only. The day's value is on the root, and the
            # stylesheet's night block names only the colours that differ by
            # night — so without this, a day colour would carry into the night.
            out.append(f"--{token.name}: " + (
                f"var(--{token.follows})" if token.follows else token.default("dark")
            ))
    if theme.dial("depth") != 1 or every_colour:
        out.append(f"--shadow: {_shadow(mode, theme.dial('depth'))}")
    return out


def settings(theme: Theme) -> list[str]:
    """The dials and the typefaces, which are the same by day and by night."""
    out = []
    for dial in _VARIABLE_DIALS:
        if dial.name in theme.dials:
            out.append(f"--{dial.name}: {_number(theme.dials[dial.name])}{dial.unit}")
    for name in ("font-body", "font-display"):
        if name in theme.choices:
            out.append(f"--{name}: {FONTS[theme.choices[name]][1]}")
    return out


def page_theme(theme: Theme) -> PageTheme:
    mode = theme.choice("mode")
    parts = []
    shared = settings(theme)
    if mode == "dark":
        # Specific enough to beat the stylesheet's own night block, which a
        # dark device would otherwise still apply on top of this.
        parts.append(_block(
            ':root[data-mode="dark"]',
            ["color-scheme: dark", *declarations(theme, "dark", every_colour=True), *shared],
        ))
    else:
        parts.append(_block(":root", [*declarations(theme, "light"), *shared]))
        night = declarations(theme, "dark")
        if mode == "system" and night:
            parts.append(
                "@media (prefers-color-scheme: dark) {\n"
                + _block(':root:not([data-mode="light"])', night)
                + "}\n"
            )

    # Every choice the stylesheet acts on, when it is not the default: the
    # stylesheet's own rules are the default, so it needs no attribute.
    attributes = [
        (f"data-{choice.name}", theme.choice(choice.name))
        for choice in CHOICES
        if choice.attribute and theme.choice(choice.name) != choice.default
    ]

    light_bg = theme.colour("light", "bg")
    dark_bg = theme.colour("dark", "bg")
    if mode == "light":
        dark_bg = light_bg
    elif mode == "dark":
        light_bg = dark_bg
    return PageTheme(
        css="".join(parts),
        attributes=tuple(attributes),
        chrome_light=light_bg,
        chrome_dark=dark_bg,
        drawings=theme.choice("drawings"),
    )

