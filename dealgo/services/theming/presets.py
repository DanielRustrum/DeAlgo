"""Themes to start from.

Each is an ordinary theme, the same shape as one a person makes or imports,
and picking one replaces what an account had. Every preset passes every
contrast pair in every mode it can show (a test says so), so starting from
one never starts from something unreadable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import palettes
from .theme import Theme, parse


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    about: str
    data: dict[str, Any]
    #: "own" for Pamphlets's, "popular" for a well-known editor theme.
    family: str = "own"

    def theme(self) -> Theme:
        return parse(self.data)


PRESETS: tuple[Preset, ...] = (
    Preset("garden", "Garden", "Pamphlets as it comes: paper, forest and terracotta.", {}),
    Preset("high-contrast", "High contrast",
           "Darker ink, firmer lines and a thicker focus ring, by day and by night.", {
               "colours": {
                   "light": {
                       "bg": "#fbf6ee", "panel": "#ffffff", "panel-2": "#f1e8da",
                       "line": "#8f7f68", "text": "#0d1a16", "muted": "#3b4640",
                       "accent": "#9a3412", "accent-dim": "#7c2a0e", "on-accent": "#ffffff",
                       "focus": "#0d1a16", "ok": "#255c34", "warn": "#6e4108",
                       "bad": "#9a2614", "sage-soft": "#cfe0cb",
                   },
                   "dark": {
                       "bg": "#070b0a", "panel": "#0f1714", "panel-2": "#18231f",
                       "line": "#6f8a80", "text": "#ffffff", "muted": "#d4dccf",
                       "accent": "#ff9b72", "accent-dim": "#ffb595", "on-accent": "#120c08",
                       "focus": "#ffffff", "ok": "#9be09a", "warn": "#ffc266",
                       "bad": "#ff9a85", "on-bad": "#120c08", "sage-soft": "#22382f",
                   },
               },
               "dials": {"focus-width": 3, "wash": 0},
           }),
    Preset("meadow", "Meadow", "Cooler: a blue-green accent over pale sage.", {
        "colours": {
            "light": {
                "bg": "#eef3ec", "panel": "#fbfdf9", "panel-2": "#e4ece0", "line": "#cfdcc9",
                "text": "#1c2b26", "muted": "#55635b", "accent": "#1f6a86",
                "accent-dim": "#18566d", "on-accent": "#ffffff", "sage-soft": "#d6e7dc",
                "peach": "#a9d1e0", "blush": "#e2eef2",
            },
            "dark": {
                "bg": "#101a1d", "panel": "#16242a", "panel-2": "#1d2f36", "line": "#2b434b",
                "text": "#e8f0ec", "muted": "#9fb2ab", "accent": "#6cc3df",
                "accent-dim": "#8fd3ea", "on-accent": "#0d1a1f", "sage-soft": "#1f3a3a",
                "blush": "#1d3038",
            },
        },
        "dials": {"roundness": 1.2},
    }),
    Preset("ink", "Ink", "Black and white, square corners and no decoration.", {
        "colours": {
            "light": {
                "bg": "#f4f4f1", "panel": "#ffffff", "panel-2": "#ebebe7", "line": "#d6d6d0",
                "text": "#161616", "muted": "#575752", "accent": "#161616",
                "accent-dim": "#3a3a3a", "on-accent": "#ffffff", "sage-soft": "#e2e2dc",
                "blush": "#efece4", "forest": "#2b2b2b", "on-forest": "#ffffff",
                "sage": "#c9c9c2", "on-sage": "#161616", "ochre": "#a3a39b",
                "on-ochre": "#161616", "peach": "#d8d8d2",
            },
            "dark": {
                "bg": "#111111", "panel": "#1a1a1a", "panel-2": "#242424", "line": "#333333",
                "text": "#ededed", "muted": "#a6a6a6", "accent": "#ededed",
                "accent-dim": "#cfcfcf", "on-accent": "#111111", "sage-soft": "#2a2a2a",
                "forest": "#3a3a3a", "blush": "#262626", "stat-quiet": "#242424",
            },
        },
        "dials": {"roundness": 0.3, "wash": 0, "depth": 0.5},
        "choices": {"font-body": "system-sans", "font-display": "system-sans",
                    "illustrations": "off"},
    }),
    Preset("compact", "Compact", "The stock colours, with more on the screen at once.", {
        "dials": {"density": 0.8, "text-scale": 0.95, "roundness": 0.6, "depth": 0.5},
    }),
)

#: Well-known editor and terminal themes, each with its day and night palette.
#: Built from the published palettes in palettes.py, settled for contrast.
POPULAR: tuple[Preset, ...] = (
    Preset("catppuccin", "Catppuccin", "Soothing pastels: Latte by day, Mocha by night.",
           palettes.theme(palettes.CATPPUCCIN), "popular"),
    Preset("dracula", "Dracula", "Vivid on deep purple-grey: Alucard by day, Dracula by night.",
           palettes.theme(palettes.DRACULA), "popular"),
    Preset("nord", "Nord", "Arctic blues: Snow Storm by day, Polar Night by night.",
           palettes.theme(palettes.NORD), "popular"),
    Preset("gruvbox", "Gruvbox", "Retro and warm, earthy browns and oranges.",
           palettes.theme(palettes.GRUVBOX), "popular"),
    Preset("solarized", "Solarized", "Precision colours on cream and deep teal.",
           palettes.theme(palettes.SOLARIZED), "popular"),
    Preset("tokyo-night", "Tokyo Night", "Neon city blues: Day and Night.",
           palettes.theme(palettes.TOKYO_NIGHT), "popular"),
    Preset("rose-pine", "Rosé Pine", "Muted rose and pine: Dawn by day, Main by night.",
           palettes.theme(palettes.ROSE_PINE), "popular"),
    Preset("everforest", "Everforest", "Soft forest greens, easy on the eyes.",
           palettes.theme(palettes.EVERFOREST), "popular"),
)

PRESETS = PRESETS + POPULAR

PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}
