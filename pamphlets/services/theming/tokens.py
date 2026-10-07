"""Everything about the look a person may change, and what it starts as.

This is the other half of web/styles/tokens.css. The stylesheet declares the
variables and their defaults; this lists which of them an account may change
under Settings → Theming, in what terms, and between which limits. A test
holds the defaults here to the stylesheet's, so the two cannot drift.

Nobody writes CSS. A theme is made of three kinds of thing, each of which can
only ever produce a value of one known shape:

- a colour: one of the variables below, as a six-digit hex, per light and dark;
- a dial: a number between two limits, which the stylesheet multiplies by;
- a choice: one of a fixed set of options, such as a typeface from the list.
"""

from __future__ import annotations

from dataclasses import dataclass

MODES = ("light", "dark")


@dataclass(frozen=True)
class Group:
    """A heading the colours are listed under."""

    key: str
    label: str
    about: str


@dataclass(frozen=True)
class Colour:
    """One colour variable a theme may set.

    `dark` is None where the night value is the day one. `follows` names the
    variable this one is by default — the feed box wears the accent — and
    such a colour keeps following it until a theme gives it a value of its own.
    """

    name: str
    label: str
    group: str
    light: str
    dark: str | None = None
    about: str = ""
    follows: str | None = None

    def default(self, mode: str) -> str:
        """Its starting value in one mode, as the stylesheet has it."""
        return self.dark if mode == "dark" and self.dark is not None else self.light


@dataclass(frozen=True)
class Dial:
    """A number between two limits. `unit` is appended in the stylesheet."""

    name: str
    label: str
    group: str
    default: float
    minimum: float
    maximum: float
    step: float
    unit: str = ""
    about: str = ""
    #: Shown beside the slider: "%" reads 1.1 as 110%, "x" as ×1.1.
    show: str = "%"


@dataclass(frozen=True)
class Option:
    key: str
    label: str


@dataclass(frozen=True)
class Choice:
    """One of a fixed set of options."""

    name: str
    label: str
    group: str
    default: str
    options: tuple[Option, ...]
    about: str = ""
    #: Put on <html> as data-<name> when not the default, for the stylesheet
    #: to act on. The typefaces are not: they are variables instead.
    attribute: bool = True

    def keys(self) -> tuple[str, ...]:
        return tuple(option.key for option in self.options)


GROUPS: tuple[Group, ...] = (
    Group("surfaces", "Surfaces", "The page, the panels on it, and the lines between things."),
    Group("text", "Text", "Writing, and the quieter writing beside it."),
    Group("accent", "Accent and focus", "Whatever acts: buttons, links, the keyboard's ring."),
    Group("status", "Status", "What worked, what is waiting and what failed."),
    Group("garden", "Garden", "The colour blocks and the drawings, each with its own ink."),
    Group("stats", "Stat blocks", "The quiet block on the dashboard."),
    Group("canvas", "Canvas boxes", "One colour per kind of box on the Configuration canvas."),
    Group("plugins", "Plugin colours", "The seven colours a plugin may give its sources."),
    Group("background", "Background", "The light on the page behind everything."),
    Group("gradient", "Gradient", "A gradient background's colours."),
    Group("texture", "Pattern and texture", "The pattern's ink."),
    Group("drawings", "Drawings", "The scene at the page's edges and beside headings."),
)

COLOURS: tuple[Colour, ...] = (
    Colour("bg", "Page", "surfaces", "#f6eee2", "#131d1a", "Behind everything."),
    Colour("panel", "Panel", "surfaces", "#fffaf3", "#1a2824",
           "Panels, inputs, buttons, toasts and canvas boxes."),
    Colour("panel-2", "Inset", "surfaces", "#f2e8da", "#22332e",
           "A recess inside a panel: code, counts and pills."),
    Colour("line", "Lines", "surfaces", "#e6d8c4", "#2f443d", "Borders and rules."),
    Colour("text", "Text", "text", "#22332e", "#f2e9db", "Body copy and headings."),
    Colour("muted", "Quiet text", "text", "#606a62", "#a2ad9f",
           "Hints, labels, dates and inactive tabs."),
    Colour("accent", "Accent", "accent", "#c04f2c", "#ee7a4f",
           "The main button, links on hover, feed boxes."),
    Colour("accent-dim", "Accent, pressed", "accent", "#a73f1d", "#f29170",
           "The accent under the pointer."),
    Colour("on-accent", "On the accent", "accent", "#fffaf3", "#1b1410",
           "Writing on an accent button."),
    Colour("focus", "Focus ring", "accent", "#c04f2c", "#ee7a4f",
           "The ring around whatever the keyboard is on.", follows="accent"),
    Colour("ok", "Worked", "status", "#397247", "#7fbf7c", "Added, connected, done."),
    Colour("warn", "Waiting", "status", "#975917", "#e3a24a", "Pending, paused, take care."),
    Colour("bad", "Failed", "status", "#bc3926", "#f07a63", "Failures and removing things."),
    Colour("on-bad", "On failed", "status", "#ffffff", "#1b1410",
           "Writing on the failures block."),
    Colour("forest", "Forest", "garden", "#23413a", "#2e544b",
           "The deep green block: what you follow."),
    Colour("on-forest", "On forest", "garden", "#fffaf3", None, "Writing on forest."),
    Colour("leaf", "Leaf", "garden", "#5f8a6a", None, "Leaves in the drawings, a hovered button's edge."),
    Colour("sage", "Sage", "garden", "#9fb8a1", None, "The watched block, the page's green wash."),
    Colour("on-sage", "On sage", "garden", "#23413a", None, "Writing on sage."),
    Colour("sage-soft", "Selected", "garden", "#dfe8dc", "#26382f",
           "The current tab and the chosen filter."),
    Colour("peach", "Peach", "garden", "#f2b196", None, "The page's warm wash and the drawings."),
    Colour("blush", "Notice", "garden", "#f8dccb", "#3a2a22", "Behind a standing notice."),
    Colour("ochre", "Ochre", "garden", "#e3a24a", None, "The pending block."),
    Colour("on-ochre", "On ochre", "garden", "#2a1b06", None, "Writing on ochre."),
    Colour("cream", "Cream", "garden", "#fffaf3", None, "Light ink in the drawings."),
    Colour("stat-quiet", "Quiet block", "stats", "#ece2d3", "#22332e",
           "Counts with nothing to act on."),
    Colour("stat-quiet-ink", "On the quiet block", "stats", "#4c5650", "#c3cbbd",
           "Writing on the quiet block."),
    Colour("kind-trigger", "Triggers", "canvas", "#7a5aa6", "#b59be0", "What starts a run."),
    Colour("kind-source", "Sources", "canvas", "#3f7d4e", "#7fbf7c",
           "Where items come from, unless its plugin chose a colour."),
    Colour("kind-filter", "Filters", "canvas", "#b8820f", "#e8b84a", "What decides."),
    Colour("kind-sort", "Sorts", "canvas", "#3f73a8", "#8fb4e0", "What orders."),
    Colour("kind-stamp", "Tags and timers", "canvas", "#2f8c86", "#5cc3bb",
           "What marks items without turning them away."),
    Colour("kind-store", "Repositories", "canvas", "#8a6440", "#c9a27a", "Deposits and withdrawals."),
    Colour("kind-feed", "Feeds", "canvas", "#c04f2c", "#ee7a4f", "Where items end up.",
           follows="accent"),
    Colour("kind-piece", "Pieces", "canvas", "#7c857f", "#8f9a92",
           "Conditions and rules before they are slotted in."),
    Colour("plugin-green", "Green", "plugins", "#3f7d4e", "#7fbf7c", follows="kind-source"),
    Colour("plugin-moss", "Moss", "plugins", "#697d21", "#b3c86a"),
    Colour("plugin-jade", "Jade", "plugins", "#1b8463", "#5cc9a0"),
    Colour("plugin-sky", "Sky", "plugins", "#257cac", "#7cc4ea"),
    Colour("plugin-pink", "Pink", "plugins", "#b8487c", "#ec8fbb"),
    Colour("plugin-red", "Red", "plugins", "#b5333a", "#f07a7e"),
    Colour("plugin-slate", "Slate", "plugins", "#5b6b78", "#a5b3bf"),
    Colour("on-plugin", "On a plugin colour", "plugins", "#ffffff", "#131d1a",
           "The initial on a plugin's mark."),
    Colour("wash-1", "First light", "background", "#9fb8a1", None,
           "The wash in the first corner, or the glow.", follows="sage"),
    Colour("wash-2", "Second light", "background", "#f2b196", None,
           "The wash in the other corner.", follows="peach"),
    Colour("bg-start", "Gradient's start", "gradient", "#f6eee2", "#131d1a",
           "Where a gradient begins.", follows="bg"),
    Colour("bg-mid", "Gradient's middle", "gradient", "#fffaf3", "#1a2824",
           "The colour between, for a gradient of three.", follows="panel"),
    Colour("bg-end", "Gradient's end", "gradient", "#f2e8da", "#22332e",
           "Where a gradient ends.", follows="panel-2"),
    Colour("pattern", "Pattern", "texture", "#e6d8c4", "#2f443d",
           "The dots, grid or lines.", follows="line"),
    Colour("art-stem", "Deepest", "drawings", "#23413a", "#2e544b",
           "Stems, branches, trunks and outlines.", follows="forest"),
    Colour("art-leaf", "Greenery", "drawings", "#5f8a6a", None,
           "Leaves, fronds, cacti, pines and seaweed.", follows="leaf"),
    Colour("art-leaf-soft", "Distant greenery", "drawings", "#9fb8a1", None,
           "Paler leaves and trees, further back.", follows="sage"),
    Colour("art-bloom", "Bright", "drawings", "#c04f2c", "#ee7a4f",
           "The boldest flowers, and coral.", follows="accent"),
    Colour("art-bloom-2", "Second bright", "drawings", "#e3a24a", None,
           "Flower centres and the sun.", follows="ochre"),
    Colour("art-bloom-3", "Soft bright", "drawings", "#f2b196", None,
           "Petals, shells and far dunes.", follows="peach"),
    Colour("art-water", "Water", "drawings", "#4f88a8", "#3f7391", "The sea's waves."),
    Colour("art-sky", "Sky and haze", "drawings", "#a9cfe2", "#2f4d5f",
           "Far waves, distant ranges and the shade under clouds."),
    Colour("art-sand", "Sand", "drawings", "#e3c48f", "#8c744c", "Near dunes."),
    Colour("art-rock", "Rock", "drawings", "#8a8f96", "#5d636b", "Mountainsides."),
    Colour("art-snow", "Snow and cloud", "drawings", "#f7f9fb", "#dfe6ec",
           "Snowcaps, clouds, foam and bubbles."),
)

COLOUR_BY_NAME = {colour.name: colour for colour in COLOURS}

#: The shadow each mode casts at depth 1: tokens.css's --shadow.
SHADOW = {"light": (92, 64, 34, 0.18), "dark": (0, 0, 0, 0.45)}

DIALS: tuple[Dial, ...] = (
    Dial("text-scale", "Text size", "type", 1, 0.85, 1.4, 0.05,
         about="Every piece of writing, together."),
    Dial("leading", "Line spacing", "type", 1.55, 1.3, 1.9, 0.05,
         about="The room between lines of body text.", show="x"),
    Dial("display-weight", "Heading weight", "type", 600, 400, 800, 50,
         about="How heavy headings and big numbers are.", show=""),
    Dial("roundness", "Roundness", "shape", 1, 0, 1.6, 0.1,
         about="Every corner, from square to soft."),
    Dial("density", "Spacing", "shape", 1, 0.75, 1.35, 0.05,
         about="Padding and gaps: tighter fits more on the screen."),
    Dial("depth", "Shadows", "shape", 1, 0, 2, 0.25,
         about="How far raised things lift off the page."),
    Dial("focus-width", "Focus ring", "shape", 2, 2, 5, 1, unit="px",
         about="How thick the ring around the keyboard's place is.", show="px"),
    Dial("wash", "Strength of the light", "background", 1, 0, 1.5, 0.1,
         about="How strongly the wash or glow shows: 0 is plain paper."),
    Dial("wash-size", "Spread of the light", "background", 1, 0.5, 1.8, 0.1,
         about="How far the wash or glow reaches across the page."),
    Dial("gradient-angle", "Direction", "gradient", 180, 0, 360, 5, unit="deg",
         about="Which way a linear gradient runs, or where a conic one starts.", show="deg"),
    Dial("gradient-balance", "Where the colours meet", "gradient", 50, 5, 95, 5, unit="%",
         about="Further along, more of the first colour.", show="unit"),
    Dial("pattern-size", "Pattern size", "texture", 24, 12, 48, 2, unit="px",
         about="How far apart the dots, lines or squares are.", show="px"),
    Dial("pattern-strength", "Pattern strength", "texture", 0.6, 0.1, 1, 0.05,
         about="How strongly the pattern shows."),
    Dial("texture-strength", "Texture strength", "texture", 0.35, 0.05, 1, 0.05,
         about="How strongly the texture shows."),
    Dial("texture-scale", "Texture scale", "texture", 1, 0.5, 3, 0.1,
         about="How coarse the texture is: higher is larger grain.", show="x"),
    Dial("image-veil", "Veil over the picture", "background", 0.25, 0, 0.9, 0.05,
         about="The page colour laid over your picture, so writing on it stays readable."),
    Dial("art-size", "Size", "drawings", 1, 0.6, 1.6, 0.1,
         about="How big the scene at the edges is."),
    Dial("art-opacity", "Strength", "drawings", 1, 0.2, 1, 0.05,
         about="How strongly they show against the page."),
)

DIAL_BY_NAME = {dial.name: dial for dial in DIALS}

#: Typefaces a theme may use. The first two are served by Pamphlets itself;
#: the rest are what the device already has, so nothing is fetched for them.
FONTS: dict[str, tuple[str, str]] = {
    "dm-sans": ("DM Sans", '"DM Sans Variable", ui-sans-serif, system-ui, -apple-system, '
                           '"Segoe UI", Roboto, sans-serif'),
    "fraunces": ("Fraunces", '"Fraunces Variable", ui-serif, Georgia, "Times New Roman", serif'),
    "system-sans": ("Your device's sans-serif",
                    'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'),
    "system-serif": ("Your device's serif",
                     'ui-serif, Charter, "Bitstream Charter", Cambria, Georgia, serif'),
    "humanist": ("Humanist sans",
                 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "DejaVu Sans", source-sans-pro, '
                 "sans-serif"),
    "rounded": ("Rounded sans",
                'ui-rounded, "SF Pro Rounded", "Hiragino Maru Gothic ProN", Quicksand, Comfortaa, '
                'Manjari, "Arial Rounded MT", Calibri, sans-serif'),
    "mono": ("Monospace",
             'ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, '
             '"DejaVu Sans Mono", monospace'),
}

_FONT_OPTIONS = tuple(Option(key, label) for key, (label, _) in FONTS.items()) + (
    # Uploaded under the Type section; without one, the stock face is used.
    Option("own", "My own font"),
)

CHOICES: tuple[Choice, ...] = (
    Choice("mode", "Light or dark", "page", "system", (
        Option("system", "Follow my device"),
        Option("light", "Always light"),
        Option("dark", "Always dark"),
    )),
    Choice("font-body", "Body typeface", "type", "dm-sans", _FONT_OPTIONS,
           about="Everything but headings.", attribute=False),
    Choice("font-display", "Heading typeface", "type", "fraunces", _FONT_OPTIONS,
           about="Page and panel titles, big numbers, the name in the corner.",
           attribute=False),
    Choice("motion", "Movement", "page", "device", (
        Option("device", "As my device prefers"),
        Option("reduce", "As little as possible"),
    ), about="Slides, fades and lifts."),
    Choice("background", "Background", "background", "wash", (
        Option("wash", "Light in two corners"),
        Option("glow", "A glow from above"),
        Option("gradient", "A gradient, top to bottom"),
        Option("plain", "Plain"),
        Option("image", "My own picture"),
    ), about="What lies behind the panels. Your own picture is uploaded below."),
    Choice("image-fit", "How the picture fills the page", "background", "cover", (
        Option("cover", "Fill the page, cropping the edges"),
        Option("contain", "Show all of it"),
        Option("tile", "Repeat it as tiles"),
    ), about="For your own picture."),
    Choice("image-at", "Which part stays in view", "background", "center", (
        Option("center", "The middle"),
        Option("top", "The top"),
        Option("bottom", "The bottom"),
    ), about="When the picture is cropped to fill the page."),
    Choice("wash-at", "Where the light falls", "background", "corners", (
        Option("corners", "Top right and bottom left"),
        Option("top", "Along the top"),
        Option("bottom", "Along the bottom"),
        Option("sides", "Either side"),
    ), about="For light in two corners."),
    Choice("gradient-type", "Kind of gradient", "gradient", "linear", (
        Option("linear", "Linear: in a straight line"),
        Option("radial", "Radial: out from a point"),
        Option("conic", "Conic: round a point"),
    ), about="For a gradient background."),
    Choice("gradient-at", "Centred on", "gradient", "center", (
        Option("center", "The middle"),
        Option("top", "The top"),
        Option("bottom", "The bottom"),
        Option("top-left", "Top left"),
        Option("top-right", "Top right"),
        Option("bottom-left", "Bottom left"),
        Option("bottom-right", "Bottom right"),
    ), about="For a radial or conic gradient."),
    Choice("gradient-stops", "Colours", "gradient", "two", (
        Option("two", "Two: start and end"),
        Option("three", "Three: start, middle and end"),
    )),
    Choice("pattern", "Pattern", "texture", "none", (
        Option("none", "None"),
        Option("dots", "Dots"),
        Option("grid", "Grid"),
        Option("lines", "Diagonal lines"),
    ), about="Laid over the background, under everything else."),
    Choice("texture", "Texture", "texture", "none", (
        Option("none", "None"),
        Option("paper", "Paper"),
        Option("grain", "Fine grain"),
        Option("linen", "Linen"),
        Option("canvas", "Canvas"),
        Option("concrete", "Concrete"),
        Option("watercolour", "Watercolour"),
        Option("own", "My own texture"),
    ), about="A surface over whatever background you chose. Your own is uploaded below."),
    Choice("texture-blend", "How the texture lies", "texture", "soft", (
        Option("soft", "Softly, light and dark"),
        Option("darken", "Darkening"),
        Option("lighten", "Lightening"),
    ), about="Darkening shows best by day, lightening by night."),
    Choice("background-moves", "When the page scrolls", "background", "still", (
        Option("still", "The background stays put"),
        Option("scrolls", "It scrolls with the page"),
    )),
    Choice("drawings", "Scene", "drawings", "garden", (
        Option("garden", "Garden: leafy sprigs and round blooms"),
        Option("meadow", "Meadow: grasses and wildflowers"),
        Option("fern", "Fern: arching fronds"),
        Option("blossom", "Blossom: a flowering branch"),
        Option("woodland", "Woodland: stands of pines"),
        Option("ocean", "Ocean: waves, coral and seaweed"),
        Option("mountains", "Mountains: snowy peaks and pines"),
        Option("sky", "Sky: clouds, the sun and birds"),
        Option("desert", "Desert: dunes, cacti and the sun"),
        Option("own", "My own pictures"),
    ), about="What is drawn. Your own pictures are uploaded below."),
    Choice("illustrations", "Where it is drawn", "drawings", "on", (
        Option("on", "At the edges and beside headings"),
        Option("edges", "At the edges only"),
        Option("headings", "Beside headings only"),
        Option("off", "Nowhere"),
    ), about="The edges are left bare on narrow screens, where a scene would sit under the text."),
    Choice("drawings-side", "Which edges", "drawings", "both", (
        Option("both", "Both sides"),
        Option("left", "Left only"),
        Option("right", "Right only"),
    )),
)

CHOICE_BY_NAME = {choice.name: choice for choice in CHOICES}

#: The headings the dials and choices are listed under, in order.
SETTING_GROUPS: tuple[Group, ...] = (
    Group("page", "Page", "Light or dark, and movement."),
    Group("type", "Type", "Typefaces, size and spacing of text."),
    Group("shape", "Shape and space", "Corners, padding, shadows and the focus ring."),
    Group("background", "Background",
          "What lies behind the panels: light, a gradient, a picture of your own, or nothing."),
    Group("gradient", "Gradient", "How a gradient background runs, and its colours."),
    Group("texture", "Pattern and texture", "A pattern and a surface laid over the background."),
    Group("drawings", "Drawings",
          "The scene at the page's edges: plants, sea, mountains, sky or desert; where, how big, and its colours."),
)

#: Colour groups shown in their own setting sections rather than under Colours.
SECTION_COLOURS = ("background", "gradient", "texture", "drawings")
