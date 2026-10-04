"""Whether a theme can still be read.

A theme may make any colour anything, so it can also make writing vanish into
what it is written on. That is not refused — a person may want a low-contrast
look, and the page is theirs — but it is said, pair by pair, with how far
short each one falls, on the Theming page and as they change things.

The pairs are the ones the app actually paints: each foreground here is drawn
on each ground it is listed with. Text needs 4.5:1 (WCAG 2.1 AA); a mark that
carries meaning but is not text — a focus ring, a box's coloured bar — 3:1.
"""

from __future__ import annotations

from dataclasses import dataclass

from .theme import Theme
from .tokens import MODES

TEXT = 4.5
MARK = 3.0


@dataclass(frozen=True)
class Pair:
    ink: str
    ground: str
    minimum: float
    where: str


_PLUGINS = ("green", "moss", "jade", "sky", "pink", "red", "slate")
_KINDS = ("trigger", "source", "filter", "sort", "stamp", "store", "feed", "piece")

PAIRS: tuple[Pair, ...] = (
    Pair("text", "bg", TEXT, "Text on the page"),
    Pair("text", "panel", TEXT, "Text on a panel"),
    Pair("text", "panel-2", TEXT, "Text on an inset"),
    Pair("text", "sage-soft", TEXT, "The selected tab"),
    Pair("text", "blush", TEXT, "A notice"),
    Pair("muted", "bg", TEXT, "Quiet text on the page"),
    Pair("muted", "panel", TEXT, "Quiet text on a panel"),
    Pair("muted", "panel-2", TEXT, "Quiet text on an inset"),
    Pair("on-accent", "accent", TEXT, "A main button"),
    Pair("on-accent", "accent-dim", TEXT, "A main button, pressed"),
    Pair("accent", "panel", MARK, "The accent on a panel"),
    Pair("focus", "bg", MARK, "The focus ring on the page"),
    Pair("focus", "panel", MARK, "The focus ring on a panel"),
    Pair("ok", "panel-2", TEXT, "An “added” pill"),
    Pair("warn", "panel-2", TEXT, "A “pending” pill"),
    Pair("bad", "panel-2", TEXT, "A “failed” pill"),
    Pair("bad", "panel", TEXT, "A remove button"),
    Pair("on-bad", "bad", TEXT, "The failures block"),
    Pair("on-forest", "forest", TEXT, "The forest block"),
    Pair("on-sage", "sage", TEXT, "The sage block"),
    Pair("on-ochre", "ochre", TEXT, "The ochre block"),
    Pair("stat-quiet-ink", "stat-quiet", TEXT, "The quiet block"),
    *(Pair(f"kind-{kind}", "panel", MARK, f"The bar on a {kind} box") for kind in _KINDS),
    *(Pair("on-plugin", f"plugin-{name}", TEXT, f"A {name} plugin's mark") for name in _PLUGINS),
)


@dataclass(frozen=True)
class Shortfall:
    """One pair that falls short, in one mode."""

    mode: str
    pair: Pair
    ratio: float

    def describe(self) -> str:
        return (
            f"{self.pair.where} ({self.mode}): {self.ratio:.1f}:1, "
            f"needs {self.pair.minimum:g}:1"
        )


def luminance(hex_colour: str) -> float:
    """Relative luminance of `#rrggbb`, as WCAG defines it."""
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(one: str, other: str) -> float:
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def shortfalls(theme: Theme) -> list[Shortfall]:
    """Every pair that reads below its minimum, in either mode.

    Only the modes the theme can show: one that is always light is never
    read by night, and its dark colours are nobody's problem.
    """
    mode_choice = theme.choice("mode")
    modes = MODES if mode_choice == "system" else (mode_choice,)
    found = []
    seen = set()
    for mode in modes:
        colours = theme.resolved(mode)
        for pair in PAIRS:
            key = (mode, pair.ink, pair.ground)
            if key in seen:
                continue
            seen.add(key)
            value = ratio(colours[pair.ink], colours[pair.ground])
            # Rounded as it is shown: 4.49 is not reported as "4.5, needs 4.5".
            if round(value, 2) < pair.minimum:
                found.append(Shortfall(mode, pair, value))
    return found
