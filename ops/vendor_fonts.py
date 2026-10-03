"""Copy the app's typefaces out of node_modules into static/fonts.

The fonts come from npm (@fontsource-variable), at the exact version
package.json names, and are committed under static/fonts so the app serves them
itself — an installed copy then has them offline, and nothing is fetched from
a font CDN. `web/styles/fonts.css` names exactly these files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "dealgo" / "web" / "static" / "fonts"
PACKAGES = ROOT / "node_modules" / "@fontsource-variable"

#: Each font file, by the package it comes from. Latin only, weight axis only.
FONTS = {
    "dm-sans": ["dm-sans-latin-wght-normal.woff2", "dm-sans-latin-wght-italic.woff2"],
    "fraunces": ["fraunces-latin-wght-normal.woff2"],
}


def source(package: str, name: str) -> Path:
    """Where npm put one font file."""
    return PACKAGES / package / "files" / name


def copy() -> list[Path]:
    """Copy every font file, and say where each went."""
    TARGET.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for package, names in FONTS.items():
        for name in names:
            found = source(package, name)
            if not found.exists():
                raise SystemExit(f"{found} is missing: run `npm install` first.")
            copied.append(Path(shutil.copyfile(found, TARGET / name)))
    return copied


if __name__ == "__main__":  # `python ops/vendor_fonts.py`, which `make fonts` runs
    for path in copy():
        print(path)
