"""Settings → Theming: how De-Algo looks to the account signed in.

A person changes the design system's own variables here — colours by day and
by night, typefaces, the size of things, corners, spacing — through a form of
fixed controls. Nothing they send is CSS: services/theming checks every value
against what that one setting may be, and writes the stylesheet overrides
itself.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...services.theming import contrast, store
from ...services.theming.presets import PRESET_BY_KEY, PRESETS
from ...services.theming.theme import Theme, ThemeError, from_form, loads, parse
from ...services.theming.tokens import (
    CHOICES,
    COLOUR_BY_NAME,
    COLOURS,
    DIALS,
    FONTS,
    GROUPS,
    MODES,
    SETTING_GROUPS,
    SHADOW,
)
from ..responses import owner_of, redirect, render

router = APIRouter()

PAGE = "/settings/theming"

#: The parts of a theme that can be put back on their own, and what is said
#: once one has been.
PARTS = {
    "all": "Everything is back as De-Algo comes.",
    "colours": "The colours are back as De-Algo comes.",
    "page": "Light or dark, movement and decoration are back as De-Algo comes.",
    "type": "The type is back as De-Algo comes.",
    "shape": "Corners, spacing, shadows and the focus ring are back as De-Algo comes.",
}


def _swatches(theme: Theme) -> dict[str, list[str]]:
    """A preset's face on its card: its page, panel, ink, accent and green, per mode."""
    names = ("bg", "panel", "text", "accent", "forest", "sage")
    return {mode: [theme.colour(mode, name) for name in names] for mode in MODES}


def _script_data(theme: Theme) -> dict[str, Any]:
    """What theming.js needs to redraw the preview and recheck contrast as
    things change, without asking the server."""
    return {
        "colours": [
            {"name": c.name, "light": c.light, "dark": c.default("dark"), "follows": c.follows}
            for c in COLOURS
        ],
        "dials": [
            {"name": d.name, "unit": d.unit, "show": d.show, "default": d.default}
            for d in DIALS
        ],
        "fonts": {key: stack for key, (_, stack) in FONTS.items()},
        "pairs": [
            {"ink": p.ink, "ground": p.ground, "minimum": p.minimum, "where": p.where}
            for p in contrast.PAIRS
        ],
        "shadow": {mode: list(values) for mode, values in SHADOW.items()},
    }


def _shown(value: float, show: str) -> str:
    """A dial's value the way its slider reads it."""
    if show == "%":
        return f"{round(value * 100)}%"
    if show == "x":
        return f"{value:.2f}"
    if show == "px":
        return f"{value:g}px"
    return f"{value:g}"


@router.get(PAGE, response_class=HTMLResponse)
def theming_page(request: Request) -> HTMLResponse:
    """The Theming page: presets, every setting, a live preview and a contrast check."""
    current = store.load(owner_of(request))
    groups = [
        (group, [c for c in COLOURS if c.group == group.key]) for group in GROUPS
    ]
    settings = [
        (
            group,
            [c for c in CHOICES if c.group == group.key],
            [
                (d, current.dial(d.name), _shown(current.dial(d.name), d.show))
                for d in DIALS if d.group == group.key
            ],
        )
        for group in SETTING_GROUPS
    ]
    context = {
        # Not "theme": base.html already has that, for the page's own look.
        "current": current,
        "modes": MODES,
        "colour_groups": groups,
        "colour_by_name": COLOUR_BY_NAME,
        "setting_groups": settings,
        "presets": [(p, _swatches(p.theme())) for p in PRESETS],
        "shortfalls": contrast.shortfalls(current),
        "script_data": _script_data(current),
        "parts": PARTS,
    }
    return render(request, "theming.html", context)


def _saved(theme: Theme) -> str:
    """What to say once a theme is kept, with a word about anything hard to read."""
    short = contrast.shortfalls(theme)
    if not short:
        return "Theme saved."
    return (
        f"Theme saved. {len(short)} pairing{'s' if len(short) != 1 else ''} "
        "now read below the recommended contrast: the list is under the preview."
    )


@router.post(PAGE)
async def save_theme(request: Request) -> RedirectResponse:
    """Keep what the form says."""
    form = await request.form()
    try:
        theme = from_form(form)
    except ThemeError as exc:
        return redirect(PAGE, err=" ".join(exc.problems))
    store.save(owner_of(request), theme)
    return redirect(PAGE, ok=_saved(theme))


@router.post(PAGE + "/preset")
def use_preset(request: Request, preset: str = Form(...)) -> RedirectResponse:
    """Start again from one of the presets, keeping only whether it is light or dark."""
    chosen = PRESET_BY_KEY.get(preset)
    if chosen is None:
        return redirect(PAGE, err="There is no such preset.")
    owner = owner_of(request)
    theme = chosen.theme()
    # Light or dark is about the person's screen and room, not the palette;
    # a preset that does not say otherwise leaves it as it was.
    mode = store.load(owner).choices.get("mode")
    if mode and "mode" not in theme.choices:
        theme.choices["mode"] = mode
    store.save(owner, theme)
    return redirect(PAGE, ok=f"Now using {chosen.label}. Change anything from here.")


@router.post(PAGE + "/reset")
def reset_part(request: Request, part: str = Form("all")) -> RedirectResponse:
    """Put one part of the theme, or all of it, back as it comes."""
    if part not in PARTS:
        return redirect(PAGE, err="There is no such part of a theme.")
    owner = owner_of(request)
    theme = store.load(owner)
    data = theme.to_json()
    if part == "all":
        data = {}
    elif part == "colours":
        data.pop("colours", None)
    else:
        group = {d.name for d in DIALS if d.group == part} | {
            c.name for c in CHOICES if c.group == part
        }
        data["dials"] = {k: v for k, v in data.get("dials", {}).items() if k not in group}
        data["choices"] = {k: v for k, v in data.get("choices", {}).items() if k not in group}
    store.save(owner, parse(data))
    return redirect(PAGE, ok=PARTS[part])


@router.get(PAGE + "/export")
def export_theme(request: Request) -> Response:
    """The theme as a file, to keep or to hand to somebody else."""
    body = json.dumps(store.load(owner_of(request)).to_json(), indent=2, sort_keys=True)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="de-algo-theme.json"'},
    )


@router.post(PAGE + "/import")
def import_theme(
    request: Request,
    theme_file: UploadFile | None = File(None),
    theme_text: str = Form(""),
) -> RedirectResponse:
    """Use a theme somebody exported: from a file, or pasted."""
    raw = theme_file.file.read(65_536 + 1) if theme_file and theme_file.filename else b""
    if len(raw) > 65_536:
        return redirect(PAGE, err="That file is too large to be a theme.")
    try:
        text = raw.decode("utf-8") if raw else theme_text
    except UnicodeDecodeError:
        return redirect(PAGE, err="That file is not readable text.")
    if not text.strip():
        return redirect(PAGE, err="Choose a theme file, or paste one.")
    try:
        theme = loads(text)
    except ThemeError as exc:
        return redirect(PAGE, err="That theme could not be used. " + " ".join(exc.problems[:5]))
    store.save(owner_of(request), theme)
    return redirect(PAGE, ok=_saved(theme).replace("saved", "loaded"))
