"""Copy the browser libraries the app uses out of node_modules into static/vendor.

Each comes from npm at the exact version package.json names, and is committed
under static/vendor with its licence beside it, so the app serves it itself:
an installed copy then has it offline, and nothing is fetched from a CDN.

- Chart.js draws the chart leaflets, on a pamphlet and in the canvas's editor
  (web/ts/charts.ts sets it up with the theme's colours).
- Leaflet draws the Map leaflet's map (web/ts/maps.ts). Only its script and
  stylesheet: the map's dots are drawn, not pictures, so its images are not
  needed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "pamphlets" / "web" / "static" / "vendor"
MODULES = ROOT / "node_modules"

#: Each file copied: where npm put it, and what it is called here.
LIBRARIES = {
    "chart.js/dist/chart.umd.min.js": "chart.umd.min.js",
    "chart.js/LICENSE.md": "chart.js.LICENSE.md",
    "leaflet/dist/leaflet.js": "leaflet.js",
    "leaflet/dist/leaflet.css": "leaflet.css",
    "leaflet/LICENSE": "leaflet.LICENSE",
}


def copy() -> list[Path]:
    """Copy every library file, and say where each went."""
    TARGET.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for found, name in LIBRARIES.items():
        source = MODULES / found
        if not source.exists():
            raise SystemExit(f"{source} is missing: run `npm install` first.")
        copied.append(Path(shutil.copyfile(source, TARGET / name)))
    return copied


if __name__ == "__main__":  # `python ops/vendor_libraries.py`, which `make vendor` runs
    for path in copy():
        print(path)
