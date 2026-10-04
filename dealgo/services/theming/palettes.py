"""Popular editor and terminal themes, as De-Algo themes.

Each is its published palette, by day and by night, set out once below in
the palette's own terms: its page, its surfaces, its ink and its named hues.
`theme()` maps those onto De-Algo's roles — which hue is the accent, which
is "worked", which paints a trigger box — and derives the few colours a
palette has no word for (the accent under the pointer, the selected tab's
tint) by mixing its own.

A palette is made for an editor, not for this app's pairings, so one may
put quiet text a shade too faint or white on a yellow. Where a pairing that
the app paints (contrast.PAIRS) reads below its minimum, `settle` nudges the
colour that should give way — the text over its ground, a fill under the
ink written on it — a few percent darker or lighter until it passes, and
leaves everything else exactly as published.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import contrast
from .theme import Theme, parse
from .tokens import MODES


@dataclass(frozen=True)
class Palette:
    """One mode of a published theme, in its own terms."""

    bg: str  # the page
    panel: str  # a raised surface
    inset: str  # a recess within one
    line: str
    text: str
    muted: str
    accent: str
    green: str
    yellow: str
    red: str
    orange: str
    blue: str
    cyan: str
    teal: str
    purple: str
    pink: str
    grey: str


# -- the palettes ------------------------------------------------------------

CATPPUCCIN = {
    # Latte and Mocha (catppuccin.com/palette). Panels are base, the page mantle.
    "light": Palette(
        bg="#e6e9ef", panel="#eff1f5", inset="#dce0e8", line="#ccd0da", text="#4c4f69",
        muted="#6c6f85", accent="#8839ef", green="#40a02b", yellow="#df8e1d", red="#d20f39",
        orange="#fe640b", blue="#1e66f5", cyan="#04a5e5", teal="#179299", purple="#7287fd",
        pink="#ea76cb", grey="#7c7f93"),
    "dark": Palette(
        bg="#181825", panel="#1e1e2e", inset="#313244", line="#45475a", text="#cdd6f4",
        muted="#a6adc8", accent="#cba6f7", green="#a6e3a1", yellow="#f9e2af", red="#f38ba8",
        orange="#fab387", blue="#89b4fa", cyan="#89dceb", teal="#94e2d5", purple="#b4befe",
        pink="#f5c2e7", grey="#9399b2"),
}

DRACULA = {
    # Alucard by day, Dracula by night (draculatheme.com/spec).
    "light": Palette(
        bg="#f5f1e1", panel="#fffbeb", inset="#ece8d8", line="#cfcfde", text="#1f1f1f",
        muted="#635d97", accent="#644ac9", green="#14710a", yellow="#846e15", red="#cb3a2a",
        orange="#a34d14", blue="#036a96", cyan="#036a96", teal="#14710a", purple="#644ac9",
        pink="#a3144d", grey="#635d97"),
    "dark": Palette(
        bg="#21222c", panel="#282a36", inset="#343746", line="#44475a", text="#f8f8f2",
        muted="#bfbfc8", accent="#bd93f9", green="#50fa7b", yellow="#f1fa8c", red="#ff5555",
        orange="#ffb86c", blue="#6272a4", cyan="#8be9fd", teal="#8be9fd", purple="#bd93f9",
        pink="#ff79c6", grey="#6272a4"),
}

NORD = {
    # Snow Storm by day, Polar Night by night; Frost and Aurora for the hues (nordtheme.com).
    "light": Palette(
        bg="#e5e9f0", panel="#eceff4", inset="#d8dee9", line="#c7d0dd", text="#2e3440",
        muted="#4c566a", accent="#5e81ac", green="#a3be8c", yellow="#ebcb8b", red="#bf616a",
        orange="#d08770", blue="#5e81ac", cyan="#88c0d0", teal="#8fbcbb", purple="#b48ead",
        pink="#b48ead", grey="#4c566a"),
    "dark": Palette(
        bg="#2e3440", panel="#3b4252", inset="#434c5e", line="#4c566a", text="#eceff4",
        muted="#d8dee9", accent="#88c0d0", green="#a3be8c", yellow="#ebcb8b", red="#bf616a",
        orange="#d08770", blue="#81a1c1", cyan="#88c0d0", teal="#8fbcbb", purple="#b48ead",
        pink="#b48ead", grey="#a0a8b7"),
}

GRUVBOX = {
    # The light and dark palettes (github.com/morhetz/gruvbox).
    "light": Palette(
        bg="#f2e5bc", panel="#fbf1c7", inset="#ebdbb2", line="#d5c4a1", text="#3c3836",
        muted="#7c6f64", accent="#af3a03", green="#79740e", yellow="#b57614", red="#9d0006",
        orange="#af3a03", blue="#076678", cyan="#076678", teal="#427b58", purple="#8f3f71",
        pink="#8f3f71", grey="#928374"),
    "dark": Palette(
        bg="#1d2021", panel="#282828", inset="#3c3836", line="#504945", text="#ebdbb2",
        muted="#a89984", accent="#fe8019", green="#b8bb26", yellow="#fabd2f", red="#fb4934",
        orange="#fe8019", blue="#83a598", cyan="#83a598", teal="#8ec07c", purple="#d3869b",
        pink="#d3869b", grey="#928374"),
}

SOLARIZED = {
    # base3/base2 by day, base03/base02 by night, and the eight accents (ethanschoonover.com).
    "light": Palette(
        bg="#eee8d5", panel="#fdf6e3", inset="#e6dfca", line="#d6cfb9", text="#073642",
        muted="#586e75", accent="#268bd2", green="#859900", yellow="#b58900", red="#dc322f",
        orange="#cb4b16", blue="#268bd2", cyan="#2aa198", teal="#2aa198", purple="#6c71c4",
        pink="#d33682", grey="#657b83"),
    "dark": Palette(
        bg="#002b36", panel="#073642", inset="#0d4352", line="#1c5361", text="#eee8d5",
        muted="#93a1a1", accent="#268bd2", green="#859900", yellow="#b58900", red="#dc322f",
        orange="#cb4b16", blue="#268bd2", cyan="#2aa198", teal="#2aa198", purple="#6c71c4",
        pink="#d33682", grey="#839496"),
}

TOKYO_NIGHT = {
    # Tokyo Night Day and Night (github.com/folke/tokyonight.nvim).
    "light": Palette(
        bg="#d0d5e3", panel="#e1e2e7", inset="#c4c8da", line="#b6bfe2", text="#3760bf",
        muted="#6172b0", accent="#2e7de9", green="#587539", yellow="#8c6c3e", red="#f52a65",
        orange="#b15c00", blue="#2e7de9", cyan="#007197", teal="#118c74", purple="#9854f1",
        pink="#9854f1", grey="#848cb5"),
    "dark": Palette(
        bg="#16161e", panel="#1a1b26", inset="#292e42", line="#3b4261", text="#c0caf5",
        muted="#a9b1d6", accent="#7aa2f7", green="#9ece6a", yellow="#e0af68", red="#f7768e",
        orange="#ff9e64", blue="#7aa2f7", cyan="#7dcfff", teal="#73daca", purple="#bb9af7",
        pink="#bb9af7", grey="#737aa2"),
}

ROSE_PINE = {
    # Rosé Pine Dawn and Rosé Pine (rosepinetheme.com/palette).
    "light": Palette(
        bg="#f2e9e1", panel="#fffaf3", inset="#f4ede8", line="#dfdad9", text="#575279",
        muted="#797593", accent="#d7827e", green="#286983", yellow="#ea9d34", red="#b4637a",
        orange="#d7827e", blue="#286983", cyan="#56949f", teal="#56949f", purple="#907aa9",
        pink="#b4637a", grey="#9893a5"),
    "dark": Palette(
        bg="#191724", panel="#1f1d2e", inset="#26233a", line="#403d52", text="#e0def4",
        muted="#908caa", accent="#ebbcba", green="#9ccfd8", yellow="#f6c177", red="#eb6f92",
        orange="#ebbcba", blue="#31748f", cyan="#9ccfd8", teal="#9ccfd8", purple="#c4a7e7",
        pink="#eb6f92", grey="#6e6a86"),
}

EVERFOREST = {
    # Everforest medium, light and dark (github.com/sainnhe/everforest).
    "light": Palette(
        bg="#f4f0d9", panel="#fdf6e3", inset="#efebd4", line="#e0dcc7", text="#5c6a72",
        muted="#829181", accent="#8da101", green="#8da101", yellow="#dfa000", red="#f85552",
        orange="#f57d26", blue="#3a94c5", cyan="#35a77c", teal="#35a77c", purple="#df69ba",
        pink="#df69ba", grey="#939f91"),
    "dark": Palette(
        bg="#272e33", panel="#2d353b", inset="#343f44", line="#475258", text="#d3c6aa",
        muted="#9da9a0", accent="#a7c080", green="#a7c080", yellow="#dbbc7f", red="#e67e80",
        orange="#e69875", blue="#7fbbb3", cyan="#83c092", teal="#83c092", purple="#d699b6",
        pink="#d699b6", grey="#859289"),
}


# -- from a palette to a theme ----------------------------------------------------


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16)


def mix(one: str, other: str, amount: float) -> str:
    """`amount` of `other` into `one`, in plain sRGB: enough for a tint."""
    a, b = _rgb(one), _rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def _inks(palette: Palette) -> tuple[str, str]:
    """The palette's own darkest and lightest colours, to write on its fills with."""
    by_light = sorted((palette.bg, palette.panel, palette.text), key=contrast.luminance)
    return by_light[0], by_light[-1]


def _ink_for(palette: Palette, *fills: str) -> str:
    """Whichever of the palette's darkest and lightest inks reads better on
    these fills — on the worst of them, when one ink serves several."""
    dark, light = _inks(palette)
    return max((dark, light), key=lambda ink: min(contrast.ratio(ink, f) for f in fills))


def roles(palette: Palette, mode: str) -> dict[str, str]:
    """A palette's colours in De-Algo's roles."""
    night = mode == "dark"
    deeper = "#ffffff" if night else "#000000"
    # The accent and the failure red are also written as text on the page's
    # surfaces, so they are light by night and dark by day — and what is
    # written on them is therefore the other way round. Fills that are never
    # text take whichever of the palette's inks reads better on them.
    dark_ink, light_ink = _inks(palette)
    on_text_colour = dark_ink if night else light_ink
    forest = mix(palette.bg, palette.teal, 0.45) if night else mix(palette.teal, "#000000", 0.35)
    sage = palette.cyan if night else mix(palette.panel, palette.cyan, 0.55)
    plugins = {
        "plugin-moss": mix(palette.green, palette.yellow, 0.5),
        "plugin-jade": palette.teal,
        "plugin-sky": palette.cyan,
        "plugin-pink": palette.pink,
        "plugin-red": palette.red,
        "plugin-slate": palette.grey,
    }
    return {
        "bg": palette.bg,
        "panel": palette.panel,
        "panel-2": palette.inset,
        "line": palette.line,
        "text": palette.text,
        "muted": palette.muted,
        "accent": palette.accent,
        "accent-dim": mix(palette.accent, deeper, 0.18),
        "on-accent": on_text_colour,
        "ok": palette.green,
        "warn": palette.yellow,
        "bad": palette.red,
        "on-bad": on_text_colour,
        "forest": forest,
        "on-forest": _ink_for(palette, forest),
        "leaf": palette.green,
        "sage": sage,
        "on-sage": _ink_for(palette, sage),
        "sage-soft": mix(palette.panel, palette.accent, 0.18),
        "peach": mix(palette.panel, palette.orange, 0.55),
        "blush": mix(palette.panel, palette.yellow, 0.2),
        "ochre": palette.yellow,
        "on-ochre": _ink_for(palette, palette.yellow),
        "cream": palette.text if night else palette.panel,
        "stat-quiet": palette.inset,
        "stat-quiet-ink": palette.muted,
        "kind-trigger": palette.purple,
        "kind-source": palette.green,
        "kind-filter": palette.yellow,
        "kind-sort": palette.blue,
        "kind-stamp": palette.teal,
        "kind-store": palette.orange,
        "kind-piece": palette.grey,
        **plugins,
        # The scenes: sea from its blue, sky from its cyan, sand from its yellow.
        "art-water": palette.blue,
        "art-sky": mix(palette.panel, palette.cyan, 0.45),
        "art-sand": mix(palette.panel, palette.yellow, 0.5),
        "art-rock": palette.grey,
        "art-snow": palette.text if night else palette.panel,
        "on-plugin": _ink_for(palette, palette.green, *plugins.values()),
    }


def _nudge(colour: str, away_from: str) -> str:
    """A step further from another colour in lightness: darker if that one is lighter."""
    darker = contrast.luminance(away_from) >= contrast.luminance(colour)
    return mix(colour, "#000000" if darker else "#ffffff", 0.04)


def settle(theme: Theme) -> Theme:
    """Nudge whatever reads below its minimum until nothing does.

    The text gives way to its ground; a fill gives way to the ink written on
    it, since one ink may sit on several fills and each fill can move alone.
    """
    for _ in range(200):
        short = contrast.shortfalls(theme)
        if not short:
            return theme
        for found in short:
            pair = found.pair
            ink_moves = not pair.ink.startswith("on-")
            mover, other = (pair.ink, pair.ground) if ink_moves else (pair.ground, pair.ink)
            values = theme.colours[found.mode]
            values[mover] = _nudge(theme.colour(found.mode, mover), theme.colour(found.mode, other))
    raise ValueError("A palette could not be brought up to the contrast minimums.")


def theme(palettes: dict[str, Palette]) -> dict[str, object]:
    """A popular theme as a preset's data: its roles by day and night, settled."""
    made = parse({"colours": {mode: roles(palettes[mode], mode) for mode in MODES}})
    settled = settle(made)
    return {
        "colours": settled.to_json().get("colours", {}),
        # These are flat palettes: a little less of the garden's light.
        "dials": {"wash": 0.5},
    }
