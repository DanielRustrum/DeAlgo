"""Compile the SCSS sources into the stylesheet the app serves.

The compiled CSS is committed and shipped inside the package, so running or
containerising De-Algo needs no compiler — only editing the styles does. A
test compares the two, so the committed file cannot quietly fall behind.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parent
SOURCE = WEB / "scss" / "app.scss"
TARGET = WEB / "static" / "app.css"

# Kept short: it is the one part of this file that is not minified.
BANNER = "/* Generated from web/scss/ by `make css` — do not edit. */\n"


def compile_css() -> str:
    """The stylesheet the sources describe, banner and all."""
    import sass  # a build-time dependency; the app never imports it

    # Minified: this file is served, not read. The SCSS partials are the
    # readable copy, and they are what anyone editing the styles works from.
    css = sass.compile(
        filename=str(SOURCE),
        output_style="compressed",
        include_paths=[str(SOURCE.parent)],
    )
    # Whatever marks the encoding — a BOM when minified, an @charset rule
    # otherwise — only counts as the very first thing in the file. Pushing it
    # down with a banner would leave a stray character glued to the opening
    # selector, so the banner goes after it instead.
    if css.startswith("\ufeff"):
        return "\ufeff" + BANNER + css[1:]
    if css.startswith("@charset"):
        first, _, rest = css.partition("\n")
        return f"{first}\n{BANNER}{rest}"
    return BANNER + css


def build() -> Path:
    """Write the compiled stylesheet, and say where it went."""
    TARGET.write_text(compile_css())
    return TARGET


if __name__ == "__main__":  # `python -m dealgo.web.styles`
    print(build())
