"""Compile the stylesheet sources into the one stylesheet the app serves.

Tailwind does the work: it bundles `web/styles/` into one file, adds the
utility classes the templates use, and minifies the lot. The compiled CSS is
committed and shipped inside the package, so running or containerising
Pamphlets needs no Node — only editing the styles does (`npm install` first).
A test compares the two, so the committed file cannot quietly fall behind —
which is also why package.json pins Tailwind to an exact version: another
release may minify the same sources a little differently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "pamphlets" / "web"
SOURCE = WEB / "styles" / "app.css"
TARGET = WEB / "static" / "app.css"
TAILWIND = ROOT / "node_modules" / ".bin" / "tailwindcss"

# Kept short: it is the one part of this file that is not minified.
BANNER = "/* Generated from web/styles/ by `make css` — do not edit. */\n"


def compile_css() -> str:
    """The stylesheet the sources describe, banner and all."""
    if not TAILWIND.exists():
        raise SystemExit("Tailwind is not installed: run `npm install` first.")
    # Run from the repository root, so the paths in its messages are short;
    # `@source` and `@import` resolve against the source file either way.
    built = subprocess.run(
        [str(TAILWIND), "--input", str(SOURCE), "--output", "-", "--minify"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return BANNER + built.stdout


def build() -> Path:
    """Write the compiled stylesheet, and say where it went."""
    TARGET.write_text(compile_css())
    return TARGET


if __name__ == "__main__":  # `python ops/build_css.py`, which `make css` runs
    print(build())
