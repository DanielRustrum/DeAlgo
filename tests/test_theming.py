"""Settings → Theming: each account changes the design system's own values.

Nobody writes CSS. A theme is colours, numbers between limits and choices
from fixed lists; everything else is refused by name. The stylesheet and the
registry agree on every default, the stock look and every preset can be
read, and one account's look is nobody else's.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from fakes import use_config
from dealgo.services import accounts
from dealgo.services.theming import contrast, store
from dealgo.services.theming.css import page_theme
from dealgo.services.theming.presets import PRESETS
from dealgo.services.theming.theme import Theme, ThemeError, from_form, loads, parse
from dealgo.services.theming.tokens import CHOICES, COLOURS, DIALS, FONTS
from dealgo.web.templates import BASE_DIR

ADMIN = ("admin", "admin")
MEMBER = ("sam", "member-password")

TOKENS_CSS = (BASE_DIR / "styles" / "tokens.css").read_text(encoding="utf-8")


def _declared(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", block))


def _stylesheet_defaults() -> tuple[dict[str, str], dict[str, str]]:
    """tokens.css's own light and dark values, as written."""
    light = _declared(TOKENS_CSS.split(":root {", 1)[1].split("\n}", 1)[0])
    dark = _declared(TOKENS_CSS.split(':root:not([data-mode="light"]) {', 1)[1].split("\n  }", 1)[0])
    return light, dark


# -- the registry is the stylesheet ---------------------------------------------


def test_every_colour_a_theme_may_change_has_the_stylesheets_default():
    light, dark = _stylesheet_defaults()
    for colour in COLOURS:
        assert colour.name in light, f"--{colour.name} is not in tokens.css"
        if colour.follows:
            assert light[colour.name] == f"var(--{colour.follows})"
            continue
        assert light[colour.name] == colour.light, colour.name
        assert dark.get(colour.name, colour.light) == colour.default("dark"), colour.name


def test_every_colour_the_stylesheet_changes_by_night_is_one_a_theme_can_change():
    _, dark = _stylesheet_defaults()
    names = {colour.name for colour in COLOURS}
    # The two that are not colours a person picks: the overlay and the shadow,
    # which the depth dial works on instead.
    assert set(dark) - names <= {"scrim", "shadow"}


def test_every_dial_is_a_stylesheet_variable_with_its_default():
    light, _ = _stylesheet_defaults()
    for dial in DIALS:
        if dial.name == "depth":
            continue
        assert light[dial.name] == f"{dial.default:g}{dial.unit}", dial.name


def test_the_stock_typefaces_are_the_stylesheets():
    light, _ = _stylesheet_defaults()
    assert light["font-body"] == FONTS["dm-sans"][1]
    assert light["font-display"] == FONTS["fraunces"][1]


# -- legible ----------------------------------------------------------------------


def test_the_stock_look_reads_at_the_recommended_contrast_by_day_and_night():
    assert [s.describe() for s in contrast.shortfalls(Theme())] == []


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.key)
def test_every_preset_reads_at_the_recommended_contrast(preset):
    assert [s.describe() for s in contrast.shortfalls(preset.theme())] == []


def test_a_hard_to_read_theme_is_kept_but_named():
    theme = parse({"colours": {"light": {"muted": "#d0d0d0"}}})
    found = contrast.shortfalls(theme)

    assert found and all(s.pair.ink == "muted" and s.mode == "light" for s in found)
    assert "Quiet text on a panel (light)" in " ".join(s.describe() for s in found)


def test_a_mode_that_is_never_shown_is_not_checked():
    theme = parse({"colours": {"dark": {"text": "#1a2824"}}, "choices": {"mode": "light"}})
    assert contrast.shortfalls(theme) == []


def test_contrast_is_the_wcag_ratio():
    assert round(contrast.ratio("#000000", "#ffffff"), 1) == 21.0
    assert round(contrast.ratio("#777777", "#ffffff"), 2) == 4.48


# -- only values of the right shape -------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"colours": {"light": {"bg": "red"}}},
    {"colours": {"light": {"bg": "#fff;} body { display: none"}}},
    {"colours": {"light": {"bg": "url(https://example.com/x)"}}},
    {"colours": {"light": {"nonsense": "#ffffff"}}},
    {"colours": {"sepia": {"bg": "#ffffff"}}},
    {"dials": {"text-scale": 9}},
    {"dials": {"text-scale": "1; color: red"}},
    {"dials": {"roundness": True}},
    {"choices": {"font-body": "Comic Sans MS"}},
    {"choices": {"mode": "</style><script>"}},
    {"css": "body { display: none }"},
    {"dealgo-theme": 99},
    ["not", "a", "theme"],
])
def test_anything_but_a_known_setting_of_the_right_shape_is_refused(bad):
    with pytest.raises(ThemeError):
        parse(bad)


def test_every_problem_is_named_at_once():
    with pytest.raises(ThemeError) as caught:
        parse({"colours": {"light": {"bg": "nope", "text": "nope"}}, "dials": {"wash": 7}})
    assert len(caught.value.problems) == 3


def test_colours_are_written_one_way_and_defaults_are_not_kept():
    theme = parse({
        "colours": {"light": {"accent": "#ABC", "bg": "#f6eee2"}},
        "dials": {"text-scale": 1, "density": "0.9"},
        "choices": {"mode": "system", "illustrations": "off"},
    })

    assert theme.colours["light"] == {"accent": "#aabbcc"}
    assert theme.dials == {"density": 0.9}
    assert theme.choices == {"illustrations": "off"}


def test_a_colour_that_follows_another_keeps_following_it():
    theme = parse({"colours": {"light": {"accent": "#112233"}}})

    assert theme.colour("light", "focus") == "#112233"
    assert theme.colour("light", "kind-feed") == "#112233"
    # Set to what it would be anyway, it is not a change of its own.
    same = parse({"colours": {"light": {"accent": "#112233", "focus": "#112233"}}})
    assert "focus" not in same.colours["light"]


def test_a_theme_goes_out_and_comes_back_the_same():
    theme = parse({
        "colours": {"light": {"accent": "#112233"}, "dark": {"bg": "#000000"}},
        "dials": {"roundness": 0.4},
        "choices": {"font-display": "mono", "mode": "dark"},
    })
    again = loads(json.dumps(theme.to_json()))

    assert again == theme
    assert theme.to_json()["dealgo-theme"] == 1


def test_the_form_follows_unless_told_otherwise():
    form = {
        "light.accent": "#112233", "light.focus": "#445566", "follow.light.focus": "1",
        "dark.focus": "#778899",
        "text-scale": "1.2", "mode": "dark", "font-body": "humanist",
    }
    theme = from_form(form)

    assert theme.colours["light"] == {"accent": "#112233"}
    assert theme.colours["dark"] == {"focus": "#778899"}
    assert theme.dials == {"text-scale": 1.2}
    assert theme.choices == {"mode": "dark", "font-body": "humanist"}


# -- the CSS it makes ---------------------------------------------------------------


def test_the_stock_look_adds_nothing_to_a_page():
    stock = page_theme(Theme())
    assert stock.css == "" and stock.attributes == ()
    assert (stock.chrome_light, stock.chrome_dark) == ("#f6eee2", "#131d1a")


def test_only_what_changed_is_written_and_only_as_variables():
    theme = parse({
        "colours": {"light": {"accent": "#112233"}, "dark": {"accent": "#ddeeff"}},
        "dials": {"text-scale": 1.1, "focus-width": 3, "depth": 0.5},
        "choices": {"font-body": "mono", "motion": "reduce", "illustrations": "off"},
    })
    page = page_theme(theme)

    assert "--accent: #112233" in page.css and "--accent: #ddeeff" in page.css
    assert "--text-scale: 1.1;" in page.css and "--focus-width: 3px;" in page.css
    assert "--shadow: rgba(92, 64, 34, 0.09)" in page.css
    assert FONTS["mono"][1] in page.css
    assert dict(page.attributes) == {"data-motion": "reduce", "data-illustrations": "off"}
    # Every declaration is a custom property: a theme sets variables, never rules.
    for line in page.css.splitlines():
        line = line.strip()
        if line.endswith(";"):
            assert line.startswith("--"), line


def test_a_colour_changed_by_day_does_not_carry_into_the_night():
    page = page_theme(parse({"colours": {"light": {"leaf": "#000000", "focus": "#123456"}}}))
    night = page.css.split("@media (prefers-color-scheme: dark)", 1)[1]

    assert "--leaf: #5f8a6a" in night
    assert "--focus: var(--accent)" in night


def test_always_dark_states_every_colour_and_beats_the_device():
    page = page_theme(parse({"choices": {"mode": "dark"}}))

    assert page.css.startswith(':root[data-mode="dark"]')
    assert "color-scheme: dark" in page.css and "--bg: #131d1a" in page.css
    assert ("data-mode", "dark") in page.attributes
    assert page.chrome_light == page.chrome_dark == "#131d1a"


def test_always_light_keeps_the_stylesheets_night_away():
    page = page_theme(parse({"choices": {"mode": "light"}}))
    assert ("data-mode", "light") in page.attributes
    assert ':root:not([data-mode="light"])' in TOKENS_CSS


def test_every_choice_and_dial_has_a_label_and_sensible_limits():
    for dial in DIALS:
        assert dial.label and dial.minimum <= dial.default <= dial.maximum
    for choice in CHOICES:
        assert choice.default in choice.keys()


# -- the page ----------------------------------------------------------------------


@pytest.fixture
def site(db, monkeypatch):
    from dealgo import config, scheduler
    from dealgo.web import app as web_app

    secured = config.Config(
        **{**config.CONFIG.__dict__, "admin_user": ADMIN[0], "admin_password": ADMIN[1]}
    )
    use_config(monkeypatch, secured)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with db.session_scope() as session:
        accounts.ensure_admin(session)
        accounts.create_user(session, *MEMBER)
    return web_app.app


def signed_in(app, who):
    client = TestClient(app)
    client.post("/login", data=dict(zip(("username", "password"), who)))
    return client


def test_settings_leads_to_theming(site):
    page = signed_in(site, MEMBER).get("/settings").text
    assert 'href="/settings/theming"' in page


def test_the_theming_page_has_every_setting_a_preview_and_the_presets(site):
    page = signed_in(site, MEMBER).get("/settings/theming").text

    for colour in COLOURS:
        assert f'name="light.{colour.name}"' in page and f'name="dark.{colour.name}"' in page
    for dial in DIALS:
        assert f'name="{dial.name}"' in page
    for preset in PRESETS:
        assert f'value="{preset.key}"' in page
    assert 'id="theme-preview"' in page and "theme-scope" in page
    assert "/static/theming.js" in page
    assert "Everything reads at the recommended contrast." in page


def test_a_saved_theme_is_on_every_page_for_that_account_only(site):
    sam = signed_in(site, MEMBER)
    admin = signed_in(site, ADMIN)

    saved = sam.post("/settings/theming", data={
        "light.accent": "#112233", "text-scale": "1.2", "mode": "dark",
        "illustrations": "off",
    }, follow_redirects=False)
    assert saved.status_code == 303 and "ok=" in saved.headers["location"]

    feed = sam.get("/feed").text
    assert '<style id="user-theme">' in feed and "--text-scale: 1.2;" in feed
    assert 'data-mode="dark"' in feed and 'data-illustrations="off"' in feed
    assert 'content="#131d1a"' in feed

    assert 'id="user-theme"' not in admin.get("/feed").text
    # Nor on the sign-in page, which belongs to nobody yet.
    assert 'id="user-theme"' not in TestClient(site).get("/login").text


def test_a_bad_value_from_the_form_is_refused_with_its_name(site):
    sam = signed_in(site, MEMBER)
    answer = sam.post("/settings/theming", data={"light.bg": "javascript:alert(1)"},
                      follow_redirects=False)

    assert "err=" in answer.headers["location"]
    assert store.load(accounts_id(site, MEMBER[0])).is_empty()


def accounts_id(site, username):
    from dealgo.db import session_scope
    from dealgo.models import User
    from sqlalchemy import select

    with session_scope() as session:
        return session.scalar(select(User.id).where(User.username == username))


def test_a_preset_replaces_the_theme_but_keeps_light_or_dark(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={"light.accent": "#112233", "mode": "light"})
    sam.post("/settings/theming/preset", data={"preset": "compact"})

    theme = store.load(accounts_id(site, MEMBER[0]))
    assert theme.colours["light"] == {}
    assert theme.dials["density"] == 0.8
    assert theme.choices["mode"] == "light"


def test_one_part_can_be_put_back_and_then_all_of_it(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={"light.accent": "#112233", "roundness": "0.5"})
    owner = accounts_id(site, MEMBER[0])

    sam.post("/settings/theming/reset", data={"part": "shape"})
    assert store.load(owner).dials == {}
    assert store.load(owner).colours["light"] == {"accent": "#112233"}

    sam.post("/settings/theming/reset", data={"part": "all"})
    assert store.load(owner).is_empty()


def test_a_theme_goes_to_a_file_and_back(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={"dark.accent": "#ffaa00", "font-display": "mono"})
    exported = sam.get("/settings/theming/export")
    assert exported.headers["content-disposition"].startswith("attachment")

    sam.post("/settings/theming/reset", data={"part": "all"})
    loaded = sam.post("/settings/theming/import",
                      files={"theme_file": ("t.json", exported.content, "application/json")},
                      follow_redirects=False)

    assert "ok=" in loaded.headers["location"]
    theme = store.load(accounts_id(site, MEMBER[0]))
    assert theme.colours["dark"] == {"accent": "#ffaa00"}
    assert theme.choices == {"font-display": "mono"}


def test_a_pasted_theme_with_anything_unknown_is_refused(site):
    sam = signed_in(site, MEMBER)
    answer = sam.post("/settings/theming/import",
                      data={"theme_text": '{"css": "body{}"}'}, follow_redirects=False)
    assert "err=" in answer.headers["location"]


def test_a_backup_carries_the_theme_and_a_restore_brings_it_back(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={"light.accent": "#112233"})
    backup = sam.get("/settings/backup").json()
    assert backup["theme"]["colours"]["light"] == {"accent": "#112233"}

    sam.post("/settings/theming/reset", data={"part": "all"})
    restored = sam.post("/settings/restore", files={
        "backup_file": ("b.json", json.dumps(backup).encode(), "application/json"),
    }, follow_redirects=False)

    assert "your+theme" in restored.headers["location"]
    assert store.load(accounts_id(site, MEMBER[0])).colours["light"] == {"accent": "#112233"}


# -- background and drawings ----------------------------------------------------


def test_every_choice_but_the_typefaces_reaches_the_page_when_changed():
    theme = parse({"choices": {
        "background": "gradient", "pattern": "grid", "wash-at": "sides",
        "background-moves": "scrolls", "drawings": "fern", "illustrations": "edges",
        "drawings-side": "left", "font-body": "mono",
    }})
    page = page_theme(theme)

    assert dict(page.attributes) == {
        "data-background": "gradient", "data-pattern": "grid", "data-wash-at": "sides",
        "data-background-moves": "scrolls", "data-drawings": "fern",
        "data-illustrations": "edges", "data-drawings-side": "left",
    }
    assert page.drawings == "fern"


def test_every_attribute_a_theme_can_set_has_a_rule_in_the_stylesheet():
    """A choice with no rule behind it would be a setting that does nothing."""
    backdrop = (BASE_DIR / "styles" / "backdrop.css").read_text(encoding="utf-8")
    theming_css = (BASE_DIR / "styles" / "theming.css").read_text(encoding="utf-8")
    handled_elsewhere = {"mode", "motion", "drawings"}
    for choice in CHOICES:
        if not choice.attribute or choice.name in handled_elsewhere:
            continue
        for option in choice.options:
            if option.key == choice.default:
                continue
            assert f'[data-{choice.name}="{option.key}"]' in backdrop, (choice.name, option.key)
    for option in [c for c in CHOICES if c.name == "drawings"][0].options:
        assert f'[data-drawings="{option.key}"]' in theming_css


@pytest.mark.parametrize("plants", [
    "garden", "meadow", "fern", "blossom", "woodland", "ocean", "mountains", "sky", "desert",
])
def test_each_set_of_plants_is_drawn_at_the_edges_and_beside_headings(site, plants):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={"drawings": plants})
    page = sam.get("/settings").text

    edges = page.split('class="garden-art garden-edges', 1)[1].split("</div>", 1)[0]
    assert "garden-edge-left" in edges and "garden-edge-right" in edges
    heading = page.split("<header class=\"relative mb-6", 1)[1].split("</header>", 1)[0]
    assert "garden-heading" in heading
    # Coloured by the drawing tokens, not the palette's own.
    assert "art-" in edges and "fill-leaf" not in edges


def test_the_drawings_are_coloured_by_their_own_tokens_which_follow_the_garden():
    theme = parse({"colours": {"light": {"leaf": "#123456"}}})
    assert theme.colour("light", "art-leaf") == "#123456"
    own = parse({"colours": {"light": {"leaf": "#123456", "art-leaf": "#abcdef"}}})
    assert own.colour("light", "art-leaf") == "#abcdef"


def test_resetting_a_section_takes_its_colours_with_it(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming", data={
        "drawings": "meadow", "art-size": "1.4", "light.art-leaf": "#123456",
        "follow.light.art-leaf": "", "light.accent": "#112233",
    })
    owner = accounts_id(site, MEMBER[0])
    assert store.load(owner).colours["light"] == {"art-leaf": "#123456", "accent": "#112233"}

    sam.post("/settings/theming/reset", data={"part": "drawings"})
    theme = store.load(owner)
    assert theme.colours["light"] == {"accent": "#112233"}
    assert theme.dials == {} and theme.choices == {}


def test_the_theming_page_has_the_background_and_drawings_sections(site):
    page = signed_in(site, MEMBER).get("/settings/theming").text
    for name in ("background", "pattern", "wash-at", "drawings", "illustrations",
                 "drawings-side", "wash-size", "pattern-size", "art-size", "art-opacity"):
        assert f'name="{name}"' in page, name
    # Their colours live in their sections, day beside night.
    assert page.count('name="light.wash-1"') == 1 and 'name="dark.art-bloom"' in page
    # And the preview carries every set, to show whichever is chosen.
    for plants in ("garden", "meadow", "fern", "blossom", "woodland", "ocean", "mountains",
                   "sky", "desert", "own"):
        assert f'data-set="{plants}"' in page


# -- your own pictures --------------------------------------------------------------

from dealgo.services.theming import images  # noqa: E402

#: A real one-pixel PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf0000000301010018dd8db00000000049454e44ae426082"
)

HOSTILE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
  onload="alert(1)" viewBox="0 0 10 10">
  <script>alert(1)</script>
  <style>@import url(https://example.com/x.css);</style>
  <foreignObject><iframe xmlns="http://www.w3.org/1999/xhtml" src="javascript:alert(1)"/></foreignObject>
  <a href="javascript:alert(1)"><circle r="5"/></a>
  <use xlink:href="https://example.com/x.svg#a"/>
  <image href="https://example.com/y.png"/>
  <animate attributeName="href" to="javascript:alert(1)"/>
  <path id="leaf" d="M0 0L10 10" fill="url(#g)" stroke="url(https://example.com)" style="fill:red"/>
  <use href="#leaf"/>
  <linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>
</svg>"""


def test_an_svg_keeps_its_drawing_and_loses_everything_else():
    cleaned = images.accept(HOSTILE_SVG).data.decode()

    for gone in ("script", "onload", "style", "foreignObject", "iframe", "javascript",
                 "example.com", "<image", "<animate", "<a "):
        assert gone not in cleaned, gone
    assert '<path id="leaf" d="M0 0L10 10" fill="url(#g)"' in cleaned
    assert '<use href="#leaf"' in cleaned and "<linearGradient" in cleaned


@pytest.mark.parametrize("sent", [
    b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "x">]><svg/>',
    b"<html><body><script>alert(1)</script></body></html>",
    b"just some text",
    b"",
    b"<svg><unclosed",
    b'<svg xmlns="http://www.w3.org/1999/xhtml"/>',
])
def test_anything_that_is_not_a_picture_is_refused(sent):
    with pytest.raises(images.ImageError):
        images.accept(sent)


def test_a_picture_is_known_by_its_first_bytes_not_its_name():
    assert images.accept(PNG).media_type == "image/png"
    assert images.accept(b"\xff\xd8\xff\xe0" + b"0" * 20).media_type == "image/jpeg"
    assert images.accept(b"RIFF\x00\x00\x00\x00WEBPVP8 ").media_type == "image/webp"
    with pytest.raises(images.ImageError):
        images.accept(b"\x89PNG\r\n\x1a\n" + b"0" * images.MAX_RASTER)


def test_an_uploaded_background_is_used_served_and_private(site):
    sam = signed_in(site, MEMBER)
    sent = sam.post("/settings/theming/image/background",
                    files={"picture": ("me.png", PNG, "image/png")}, follow_redirects=False)
    assert "ok=" in sent.headers["location"]

    page = sam.get("/feed").text
    assert 'data-background="image"' in page
    address = re.search(r'--user-image: url\("([^"]+)"\)', page).group(1)
    assert address.startswith("/settings/picture/background?v=")

    served = sam.get(address)
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]

    # Another account's address is its own, and holds nothing.
    assert signed_in(site, ADMIN).get(address).status_code == 404
    assert TestClient(site).get(address, follow_redirects=False).status_code in (303, 401, 404)


def test_an_svg_is_served_as_cleaned_not_as_sent(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming/image/heading",
             files={"picture": ("plant.svg", HOSTILE_SVG, "image/svg+xml")})
    served = sam.get("/settings/picture/heading")

    assert served.headers["content-type"].startswith("image/svg+xml")
    assert b"script" not in served.content and b"onload" not in served.content


def test_a_hostile_upload_is_refused_and_nothing_changes(site):
    sam = signed_in(site, MEMBER)
    answer = sam.post("/settings/theming/image/background",
                      files={"picture": ("x.svg", b"<html><script/></html>", "image/svg+xml")},
                      follow_redirects=False)
    assert "err=" in answer.headers["location"]
    owner = accounts_id(site, MEMBER[0])
    assert store.versions(owner) == {} and store.load(owner).is_empty()


def test_own_pictures_are_drawn_as_the_plants(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming/image/edge-left", files={"picture": ("l.png", PNG, "image/png")})
    page = sam.get("/settings").text

    edges = page.split('class="garden-art garden-edges', 1)[1].split("</div>", 1)[0]
    assert '<img class="garden-edge garden-edge-left' in edges
    assert 'src="/settings/picture/edge-left?v=' in edges
    # Only the slots that hold one: no right edge, no heading picture.
    assert "garden-edge-right" not in edges


def test_removing_the_last_picture_puts_the_choice_back(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming/image/background", files={"picture": ("b.png", PNG, "image/png")})
    owner = accounts_id(site, MEMBER[0])
    assert store.load(owner).choice("background") == "image"

    sam.post("/settings/theming/image/background/remove")
    assert store.versions(owner) == {}
    assert store.load(owner).choice("background") == "wash"


def test_choosing_ones_own_picture_with_none_uploaded_falls_back():
    page = page_theme(parse({"choices": {"background": "image", "drawings": "own"}}))
    assert page.attributes == () and page.drawings == "garden"
    assert "--user-image" not in page.css


def test_a_backup_carries_the_pictures_checked_again_on_the_way_back(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/theming/image/background", files={"picture": ("b.png", PNG, "image/png")})
    backup = sam.get("/settings/backup").json()
    assert set(backup["theme_pictures"]) == {"background"}

    sam.post("/settings/theming/image/background/remove")
    backup["theme_pictures"]["heading"] = {
        "type": "image/svg+xml",
        "data": __import__("base64").b64encode(b"<html><script/></html>").decode(),
    }
    restored = sam.post("/settings/restore", files={
        "backup_file": ("b.json", json.dumps(backup).encode(), "application/json"),
    }, follow_redirects=False)

    owner = accounts_id(site, MEMBER[0])
    assert set(store.versions(owner)) == {"background"}
    assert "beside+headings+picture" in restored.headers["location"]


# -- gradients and textures -----------------------------------------------------------


def test_a_gradient_is_built_from_its_settings():
    page = page_theme(parse({
        "choices": {"background": "gradient", "gradient-type": "conic", "gradient-at": "top-left",
                    "gradient-stops": "three"},
        "dials": {"gradient-angle": 90, "gradient-balance": 30},
        "colours": {"light": {"bg-mid": "#123456"}},
    }))
    attributes = dict(page.attributes)
    assert attributes["data-gradient-type"] == "conic"
    assert attributes["data-gradient-at"] == "top-left"
    assert "--gradient-angle: 90deg;" in page.css and "--gradient-balance: 30%;" in page.css
    assert "--bg-mid: #123456" in page.css


def test_every_texture_has_its_tile():
    for option in [c for c in CHOICES if c.name == "texture"][0].options:
        if option.key == "none":
            continue
        tile = BASE_DIR / "static" / "textures" / f"{option.key}.svg"
        assert tile.exists(), option.key
        # Drawn by a filter and nothing else: no script, nothing fetched.
        text = tile.read_text(encoding="utf-8")
        assert "<feTurbulence" in text and "script" not in text and "href" not in text


def test_a_texture_is_laid_over_the_page_only_when_chosen(site):
    sam = signed_in(site, MEMBER)
    assert "data-texture" not in sam.get("/feed").text.split("<head>", 1)[0]
    sam.post("/settings/theming", data={"texture": "linen", "texture-strength": "0.5"})
    page = sam.get("/feed").text
    assert 'data-texture="linen"' in page and "--texture-strength: 0.5;" in page


# -- the account picture ------------------------------------------------------------


def test_an_account_picture_replaces_the_letter_for_its_account_only(site):
    sam = signed_in(site, MEMBER)
    sent = sam.post("/settings/avatar", files={"picture": ("me.png", PNG, "image/png")},
                    follow_redirects=False)
    assert "ok=" in sent.headers["location"]

    bar = sam.get("/feed").text.split('class="account-icon"', 1)[1].split("</a>", 1)[0]
    assert 'class="avatar-letter avatar-picture"' in bar
    address = re.search(r'src="(/settings/picture/avatar\?v=[0-9a-f]+)"', bar).group(1)
    assert sam.get(address).content == PNG
    assert signed_in(site, ADMIN).get(address).status_code == 404
    # It is the account's, not the theme's: no theme setting changed.
    assert store.load(accounts_id(site, MEMBER[0])).is_empty()

    sam.post("/settings/avatar/remove")
    bar = sam.get("/feed").text.split('class="account-icon"', 1)[1].split("</a>", 1)[0]
    assert "avatar-picture" not in bar and "avatar-letter" in bar


def test_a_hostile_account_picture_is_refused(site):
    sam = signed_in(site, MEMBER)
    answer = sam.post("/settings/avatar",
                      files={"picture": ("x.svg", b"<html><script/></html>", "image/svg+xml")},
                      follow_redirects=False)
    assert "err=" in answer.headers["location"]
    assert store.versions(accounts_id(site, MEMBER[0])) == {}


def test_the_account_picture_travels_in_the_backup(site):
    sam = signed_in(site, MEMBER)
    sam.post("/settings/avatar", files={"picture": ("me.png", PNG, "image/png")})
    backup = sam.get("/settings/backup").json()
    assert "avatar" in backup["theme_pictures"]

    sam.post("/settings/avatar/remove")
    sam.post("/settings/restore", files={
        "backup_file": ("b.json", json.dumps(backup).encode(), "application/json"),
    })
    assert "avatar" in store.versions(accounts_id(site, MEMBER[0]))


# -- popular themes -------------------------------------------------------------------

from dealgo.services.theming import palettes  # noqa: E402
from dealgo.services.theming.presets import POPULAR  # noqa: E402


@pytest.mark.parametrize("preset", POPULAR, ids=lambda p: p.key)
def test_a_popular_theme_has_its_own_day_and_night(preset):
    theme = preset.theme()
    published = {
        "catppuccin": palettes.CATPPUCCIN, "dracula": palettes.DRACULA, "nord": palettes.NORD,
        "gruvbox": palettes.GRUVBOX, "solarized": palettes.SOLARIZED,
        "tokyo-night": palettes.TOKYO_NIGHT, "rose-pine": palettes.ROSE_PINE,
        "everforest": palettes.EVERFOREST,
    }[preset.key]
    # Its page and surfaces are the palette's own, by day and by night. (One
    # that happens to match De-Algo's own colour is simply not stored.)
    for mode in ("light", "dark"):
        assert theme.colour(mode, "bg") == published[mode].bg
        assert theme.colour(mode, "panel") == published[mode].panel
    assert theme.colour("light", "bg") != theme.colour("dark", "bg")
    # Light or dark stays the person's to choose.
    assert "mode" not in theme.choices


def test_a_published_palette_that_already_reads_is_left_as_published():
    mocha = palettes.roles(palettes.CATPPUCCIN["dark"], "dark")
    theme = [p for p in POPULAR if p.key == "catppuccin"][0].theme()
    for name in ("bg", "panel", "text", "accent", "ok", "warn", "bad", "kind-trigger"):
        assert theme.colour("dark", name) == mocha[name], name


def test_settling_nudges_only_what_falls_short_and_only_as_far_as_it_must():
    faint = parse({"colours": {"light": {"muted": "#c8c8c8"}}})
    settled = palettes.settle(faint)

    assert contrast.shortfalls(settled) == []
    assert settled.colours["light"].keys() == {"muted"}
    # Darker, but no darker than it needed to be to reach 4.5:1 on the inset.
    assert 4.5 <= contrast.ratio(settled.colour("light", "muted"), "#f2e8da") < 4.9


def test_the_popular_themes_have_a_heading_of_their_own(site):
    page = signed_in(site, MEMBER).get("/settings/theming").text
    own, popular = page.split("Popular themes", 1)
    assert 'value="garden"' in own and 'value="catppuccin"' not in own
    for preset in POPULAR:
        assert f'value="{preset.key}"' in popular
