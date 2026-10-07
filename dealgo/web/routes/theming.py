"""Settings → Theming: how Pamphlets looks to the account signed in.

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

from ...db import session_scope
from ...services.theming import contrast, images, store
from ...services.scope import OwnerId
from ...services.theming.css import image_url, own_font_stack
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
    SECTION_COLOURS,
    SETTING_GROUPS,
    SHADOW,
)
from ..responses import owner_of, redirect, render

router = APIRouter()

PAGE = "/settings/theming"

#: The parts of a theme that can be put back on their own, and what is said
#: once one has been.
PARTS = {
    "all": "Everything is back as Pamphlets comes.",
    "colours": "The colours are back as Pamphlets comes.",
    "page": "Light or dark and movement are back as Pamphlets comes.",
    "type": "The type is back as Pamphlets comes.",
    "shape": "Corners, spacing, shadows and the focus ring are back as Pamphlets comes.",
    "background": "The background is back as Pamphlets comes.",
    "gradient": "The gradient is back as Pamphlets comes.",
    "texture": "The pattern and texture are back as Pamphlets comes.",
    "drawings": "The drawings are back as Pamphlets comes.",
}


def _swatches(theme: Theme) -> dict[str, list[str]]:
    """A preset's face on its card: its page, panel, ink, accent and green, per mode."""
    names = ("bg", "panel", "text", "accent", "forest", "sage")
    return {mode: [theme.colour(mode, name) for name in names] for mode in MODES}


def _script_data(theme: Theme, owner: OwnerId) -> dict[str, Any]:
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
        # One's own fonts, by setting, for when "My own font" is chosen.
        "own_fonts": {
            slot: own_font_stack(slot)
            for slot in images.FONT_SLOTS if slot in store.versions(owner)
        },
        # The choices the preview mirrors as data-* on itself, as the page does.
        "choices": [c.name for c in CHOICES if c.attribute and c.name != "mode"],
        "pairs": [
            {"ink": p.ink, "ground": p.ground, "minimum": p.minimum, "where": p.where}
            for p in contrast.PAIRS
        ],
        "shadow": {mode: list(values) for mode, values in SHADOW.items()},
    }


def _shown(value: float, show: str, unit: str = "") -> str:
    """A dial's value the way its slider reads it."""
    if show == "%":
        return f"{round(value * 100)}%"
    if show == "x":
        return f"{value:.2f}"
    if show == "px":
        return f"{value:g}px"
    if show == "deg":
        return f"{value:g}°"
    if show == "unit":
        return f"{value:g}{unit}"
    return f"{value:g}"


@router.get(PAGE, response_class=HTMLResponse)
def theming_page(request: Request) -> HTMLResponse:
    """The Theming page: presets, every setting, a live preview and a contrast check."""
    current = store.load(owner_of(request))
    groups = [
        (group, [c for c in COLOURS if c.group == group.key])
        for group in GROUPS if group.key not in SECTION_COLOURS
    ]
    settings = [
        (
            group,
            [c for c in CHOICES if c.group == group.key],
            [
                (d, current.dial(d.name), _shown(current.dial(d.name), d.show, d.unit))
                for d in DIALS if d.group == group.key
            ],
            # Background and drawings carry their own colours with them.
            [c for c in COLOURS if c.group == group.key],
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
        "script_data": _script_data(current, owner_of(request)),
        # The account's own pictures, slot to address, and what each slot is.
        "pictures": {
            slot: image_url(slot, version)
            for slot, version in store.versions(owner_of(request)).items()
        },
        "slots": images.THEME_SLOTS,
        "font_families": images.FONT_FAMILIES,
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
        # A section's own colours go back with it.
        data["colours"] = {
            mode: {k: v for k, v in values.items() if COLOUR_BY_NAME[k].group != part}
            for mode, values in data.get("colours", {}).items()
        }
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


# -- pictures -----------------------------------------------------------------

#: Served as a picture and nothing else: no sniffing it into something that
#: runs, and a policy under which an SVG opened by itself still runs nothing.
_PICTURE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    # The address carries the picture's fingerprint, so a copy never goes stale.
    "Cache-Control": "private, max-age=31536000, immutable",
}


@router.get("/settings/picture/{slot}")
def serve_picture(request: Request, slot: str) -> Response:
    """One of the signed-in account's own pictures — a theme's, or its account
    picture. Nobody else's: there is no address that names another account."""
    kept = store.picture(owner_of(request), slot) if slot in images.ALL_SLOTS else None
    if kept is None:
        return Response(status_code=404)
    return Response(content=kept.data, media_type=kept.media_type, headers=_PICTURE_HEADERS)


@router.post(PAGE + "/image/{slot}")
def upload_picture(
    request: Request, slot: str, picture: UploadFile = File(...)
) -> RedirectResponse:
    """Put a picture or a font in a slot, and switch to using it."""
    if slot not in images.THEME_SLOTS:
        return redirect(PAGE, err="There is no such place for a picture.")
    raw = picture.file.read(max(images.MAX_RASTER, images.MAX_FONT) + 1)
    try:
        kept = images.accept_for(slot, raw)
    except images.ImageError as exc:
        return redirect(PAGE + _section(slot), err=str(exc))
    owner = owner_of(request)
    theme = store.load(owner)
    # Uploading one is choosing it: a picture that sits unused until a second
    # setting is found would look like an upload that did not work.
    if slot == "background":
        theme.choices["background"] = "image"
    elif slot == "texture":
        theme.choices["texture"] = "own"
    elif slot in images.FONT_SLOTS:
        theme.choices[slot] = "own"
    else:
        theme.choices["drawings"] = "own"
    with session_scope() as session:
        store.put_picture(session, owner, slot, kept)
        store.write(session, owner, theme)
    store.drop_held()
    what = images.THEME_SLOTS[slot] if slot in images.FONT_SLOTS else f"{images.SLOTS[slot]} picture"
    return redirect(PAGE + _section(slot), ok=f"{what} in place, and in use.")


def _section(slot: str) -> str:
    """The part of the page a slot is in, to come back to."""
    if slot in ("background", "texture"):
        return "#" + slot
    return "#type" if slot in images.FONT_SLOTS else "#drawings"


@router.post(PAGE + "/image/{slot}/remove")
def remove_picture(request: Request, slot: str) -> RedirectResponse:
    """Take a picture or font away. Without it, the choice that used it goes back too."""
    if slot not in images.THEME_SLOTS:
        return redirect(PAGE, err="There is no such place for a picture.")
    owner = owner_of(request)
    left = set(store.versions(owner)) - {slot}
    theme = store.load(owner)
    if slot == "background" and theme.choice("background") == "image":
        theme.choices.pop("background", None)
    elif slot == "texture":
        if theme.choice("texture") == "own":
            theme.choices.pop("texture", None)
    elif slot in images.FONT_SLOTS:
        if theme.choice(slot) == "own":
            theme.choices.pop(slot, None)
    elif (
        slot in images.DRAWING_SLOTS
        and theme.choice("drawings") == "own"
        and not left & set(images.DRAWING_SLOTS)
    ):
        theme.choices.pop("drawings", None)
    with session_scope() as session:
        store.put_picture(session, owner, slot, None)
        store.write(session, owner, theme)
    store.drop_held()
    return redirect(PAGE + _section(slot), ok=f"{images.THEME_SLOTS[slot]} removed.")
