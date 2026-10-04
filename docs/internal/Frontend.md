# Frontend

Server-rendered HTML, one stylesheet, a handful of small scripts, and one rich client: the canvas.
No framework, no bundler, no Node at runtime.

## Files

| Source | Compiled to (committed) | Does |
| --- | --- | --- |
| `web/styles/app.css` + files, and the templates' utility classes | `web/static/app.css` | All styles; `tokens.css` holds the theme and dark mode; `graph/` the canvas |
| `@fontsource-variable/*` in `node_modules` | `static/fonts/*.woff2` | The two typefaces, served by the app (`make fonts`) |
| `web/ts/graph/` (18 parts) | `static/graph.js` | The Configuration canvas |
| `web/ts/focus/` (8 parts) | `static/focus.js` | Focus mode: one item at a time, timers |
| `web/ts/sections.ts` | `static/sections.js` | Collapsible sections |
| `web/ts/menu.ts` | `static/menu.js` | Menus |
| `web/ts/toast.ts` | `static/toast.js` | Flash messages as toasts |
| `web/ts/theming.ts` | `static/theming.js` | Settings → Theming: live preview and contrast check |
| `web/ts/shelf.ts` | `static/shelf.js` | The Feed shelf: dragging tiles into your own order |
| `web/ts/pwa.ts` | `static/pwa.js` | Service-worker registration, install prompt, offline banner |
| `web/ts/sw.ts` | `static/sw.js` | Service worker (separate `tsconfig.sw.json`, WebWorker lib) |
| — | `static/htmx.min.js` | htmx, vendored |

Build: `make css` (Tailwind via `ops/build_css.py`), `make js`, `make fonts`, `make assets` (all
three). Tests fail if committed output differs from sources (`test_styles.py`, `test_scripts.py`).

`make js` runs three TypeScript programs: the single-file page scripts (`tsconfig.json`), the
service worker (`tsconfig.sw.json`), and the scripts written as a folder of parts
(`tsconfig.parts.json`, into `build/scripts/`). `ops/join_scripts.py` then joins each
folder's parts into the one file its page loads, `main.js` last.

## Styles — Tailwind, `web/styles/`

`web/styles/app.css` is the entry point Tailwind (v4, pinned in `package.json`) compiles. It is
plain CSS with native nesting, plus a few Tailwind directives:

- **Two kinds of style.** Component classes (`.panel`, `.btn`, `.graph-node`…) live in the files
  under `web/styles/`, one file per area, and are what most markup uses. Tailwind utility classes
  (`flex`, `text-muted`, `fill-sage`…) are written straight into templates for one-off layout and
  for the illustrations. Only `web/templates/` is scanned for them; scripts use component classes.
- **Layers.** Every file is imported into the `components` layer and the utilities come after, so
  a utility in a template always beats a component rule. Tailwind's preflight reset is not used:
  `base.css` is the app's own reset.
- **The theme** is `tokens.css`: the colours as custom properties (`--bg`, `--panel`, `--accent`…,
  the garden colours `--forest`, `--sage`, `--peach`…, each fill with its own ink `--on-accent`,
  `--on-forest`, `--on-sage`, `--on-ochre`, `--on-bad`, `--on-plugin`), a dark palette under
  `prefers-color-scheme: dark` (skipped when the root has `data-mode="light"`), and `@theme inline`,
  which exposes the same tokens to Tailwind as `bg-panel`, `text-ink`, `fill-forest`,
  `font-display`. Colours are never written anywhere else. Every text colour reads at 4.5:1 on the
  grounds it is used on, in both modes (`tests/test_theming.py`).
- **Dials, not literals.** Sizes are written against the theme's dials so one setting moves a whole
  family: `font-size: calc(13px * var(--text-scale))`, `line-height: var(--leading)`,
  `font-weight: var(--display-weight)`, radii from `--radius`, `--radius-lg`, `--radius-control`,
  `--radius-md`, `--radius-sm`, `--radius-xs`, `--radius-pill` (all × `--roundness`), layout spacing
  from `--gap*` and `--pad-*` (× `--density`), focus outlines as
  `var(--focus-width) solid var(--focus)`. Write new rules the same way. Only a hairline bar
  (2–3px) keeps a literal radius. The derived tokens are declared on `:root, .theme-scope`, so the
  Theming preview, which sets its own dials, recomputes them.
- **Theming** (`services/theming/`, Settings → Theming). `tokens.py` lists every variable an account
  may change, with its label and default: colours per mode, dials with limits, and choices from
  fixed lists. A test holds it to `tokens.css`, so a token added to one must be added to the other.
  `theme.py` refuses anything else by name. `css.py` writes only the changed values, as
  custom-property overrides, into `<style id="user-theme">` after the stylesheet (`base.html`), plus
  `data-mode`, `data-motion` and `data-illustrations` on `<html>`. Forced dark states every colour
  under `:root[data-mode="dark"]`, because it has no stylesheet block to fall back on.
  `contrast.py` lists the pairings the app paints and their minimums. `ts/theming.ts` runs the same
  check live and copies the form onto the preview. `presets.py` has De-Algo's own presets and
  the popular ones. Those are built from published palettes in `palettes.py`, mapped onto the
  roles by `roles()`, then `settle()`d: each pairing below its minimum moves its mover (text over
  its ground, a fill under its ink) 4% at a time toward black or white until it passes. The accent
  and the failure red are also text on surfaces, so their ink is fixed by mode; other fills take
  whichever of the palette's darkest and lightest colours reads better. Theme saves are full posts, not boosted swaps:
  the theme lives in `<head>`, which an htmx swap leaves alone.
- **Widths and input.** `@variant phone { … }` (≤ 640px) and `@variant tablet { … }` (≤ 860px) are
  custom variants; `pointer-coarse` and `motion-reduce` are Tailwind's. Write them at the top
  level of a file or at the end of a rule, never between a rule's declarations: the compiler
  hoists a nested block above the declarations that follow it.
- **Canvas colours.** `graph/kinds.css` maps every box kind to one of eight category colours
  (`--kind-trigger`, `--kind-source`, `--kind-filter`, `--kind-sort`, `--kind-stamp`, `--kind-store`,
  `--kind-feed`, `--kind-piece`) as `--kind-colour`, which the box's bar, the palette swatch and the
  palette pill read. A slotted piece gets `data-host` (the kind of the box at the top of its stack)
  from `placeGraphPieces`, and wears that box's colour. A source box, its palette swatch and its
  pills carry `data-colour` (the colour its plugin chose); `plugin-colours.css` turns that into
  `--plugin-colour`.
- **`@apply surface`** is the raised-panel look (background, border, radius, shadow).
- **Type.** DM Sans for text, Fraunces for headings (`h1`, `h2`, `.display`), both variable fonts
  served from `static/fonts/` so an installed copy has them offline.
- **Illustrations** are inline SVG macros in `templates/_garden.html`: four sets of plants
  (`sprig` and `bloom` for garden, `grass` and `wildflowers` for meadow, `fern`, `branch` for
  blossom, all built from `#g-leaf` and `flower`), `edges(set)` for the page's edges and
  `heading_art(set)` beside `page_head`. The set comes from the theme (`theme.drawings`), which is
  why `page_head` is imported `with context`. They are decoration (`aria-hidden`), coloured by
  the drawing tokens (`fill-art-leaf`, `stroke-art-stem`…), not the palette's own. An edge piece
  is `.garden-edge` plus `-left` or `-right`. A piece standing in a corner grows from it
  (`origin-bottom-left`); a hanging, rotated one grows about its centre.
- **Backdrop** (`backdrop.css`): the body background is four layers held in variables
  (`--layer-pattern`, `--layer-wash-a`, `--layer-wash-b` and `--layer-ground`) built from tokens
  and dials. Theme choices arrive as `data-background`, `data-wash-at`, `data-pattern` and
  `data-background-moves` on the root, and swap a layer rather than restyling the body. Drawing
  visibility (`data-illustrations`, `data-drawings-side`) is there too. The root's rules skip
  `.theme-scope *`, so the Theming preview shows the form, not the saved theme. The layers are
  declared on `:root, .theme-scope` like the radii. With a picture background (`data-background=
  "image"`), the ground layer is `var(--user-image)` under a veil of `--bg`.
  - `--user-image` is written by `css.py` only when the account has a background picture.
  - `data-image-fit` and `data-image-at` size and place it.
  - Choosing a picture that isn't there falls back to the stock layer and plants, rather than
    showing nothing.
  - The `own` drawing set draws `<img>` from `theme.images`, slot to address.
  - A gradient is `--gradient-stops` (two colours with `--gradient-balance` as a colour hint, or
    three with the middle colour at the balance), put into `linear-`, `radial-` or
    `conic-gradient()` by `data-gradient-type`, `--gradient-angle` and `--gradient-at`.
  - A texture is `body::before`, a fixed layer between the page background and the plants.
    It's a grey noise tile from `static/textures/`, blended in with `--texture-blend`. For
    darkening or lightening, the tile is first brought near white or near black
    (`--texture-tone`), so only its grain shows. The preview draws the same thing as its own
    `::before`, inside `isolation: isolate`.
  - The account picture (`theme.images.avatar`) replaces the letter in the bar and on Settings.

The compiled file is minified by Lightning CSS, which rewrites some values: `translateX(100%)`
becomes `translate(100%)`, `120ms` becomes `.12s`, `transparent` becomes `#0000`, `::before`
becomes `:before`, and declarations within a rule may be reordered. Tests that read the compiled
CSS match on those forms.

## Scripts written as parts

A script too large to read as one file is a folder: `web/ts/graph/`, `web/ts/focus/`. Each part
holds one area (drawing, the panel, dragging, the timer, the player…) and only declares; `main.ts`
holds the one entry call. The parts share one global scope, as plain scripts on a page do, so a part
calls another's functions with no import.

They are **joined, not loaded separately**: htmx re-inserts a swapped page's scripts, and
re-inserted external scripts are not guaranteed to run in order. One file is the one order that
cannot be lost. To add a script written as parts, add its folder to `tsconfig.parts.json` and to
`JOINED` in `ops/join_scripts.py`.

## Script rules (enforced by `tests/test_scripts.py`)

The scripts are **plain scripts, not modules**, and htmx re-executes them when it swaps a page in
with `hx-boost`. So:

- **Top-level `function` declarations only.** A top-level `const`/`let`/`class` throws
  "already declared" on the second run.
- **No IIFEs.** Logic lives in named functions that can be found and tested.
- **One entry call at the bottom** (`initGraph();`, `initFocusMode();`, …), and nothing else at the
  top level. In a script written as parts, that call is in `main.ts`.
- **No `!` non-null assertions.** The one permitted cast is server JSON.
- Strict TypeScript: `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and the rest.
- Every CSS class a script queries must exist in the stylesheet.

## The canvas — `web/ts/graph/`

**The server owns the graph.** Every change is a POST that answers with the whole graph; the
drawing is thrown away and rebuilt from that answer. A refused wire simply never appears.

The only local state is in-flight interaction:

- **Dragging** moves a box locally and saves on release (one POST, not one per pixel).
- **Wiring** draws a provisional wire from a port to the pointer until dropped.
- **Slotting** a piece previews where it would land; the server's `attach` decides.

| Part | Holds |
| --- | --- |
| `model.ts` | The kinds of box and piece, and what each may do |
| `reading.ts` | Checked shapes for the server's JSON — `asGraph`, `asGraphNode`, … (the only casts) |
| `server.ts` | `askGraph`: every change is a POST answered with the whole graph |
| `drawing.ts` | `renderGraph`, `drawGraphNodes`, `drawGraphWires`, `placeGraphPieces` |
| `panel.ts` | The panel beside a picked box: tabs, `graphNodeForm`, removing |
| `piece-fields.ts`, `source-fields.ts`, `box-fields.ts` | The panel's fields, per kind |
| `dragging.ts` | Pointer: pan, wire, move, marquee, resize |
| `picking.ts` | Picking boxes and wires, keys, clicks |
| `filtered.ts`, `trying.ts` | What a Filter held; Test without running |
| `running.ts` | `followGraphRun`, `paintGraphRun` — polls `/api/graph/run` |
| `undo.ts` | `rememberGraphUndo`, `undoGraph` |
| `palette.ts`, `dialogs.ts` | The palette and slotting; the log, reach-back and load-group dialogs |
| `finder.ts` | Finding a group on a large canvas |
| `main.ts` | `initGraph` → `findGraphs` → `startGraph`, and the entry call |

The palette lists host boxes and pieces, plus each loaded plugin's augmentations with the boxes
they fit under (as pills).

## Focus mode — `web/ts/focus/`

Shows one item at a time. A Decay timer counts down per item (`view_seconds`); the reader can pause
it unless a Lock piece set `view_locked`. When it runs out, or the reader moves on, it POSTs
`/focus/{id}/finished`. Parts: `model`, `page`, `timer`, `showing`, `queue`, `advancing`, `player`,
`main`.

**Players are built in.** An item is played only when its source's plugin named one of
`registry.plugin.PLAYERS` (`player = "youtube"`); every other item is read. A player is browser code
running with the signed-in session, which a plugin is never handed, so each lives here: the
`youtube` player is the iframe in `focus.html`, the embed in `showing.ts` and the IFrame API in
`player.ts`. Adding a player means adding its name to `PLAYERS` and its code in those three places.

## Service worker — `sw.ts`

Offline means **reading what was already loaded**: the shell, styles, visited pages and their
pictures. Any cross-origin request with `destination === "image"` goes into a separate image cache,
capped at 300 — whichever service it came from, since that is the plugins' business. Writes need the server and fail visibly offline. The cache name includes the version
query the worker was registered with, so a deploy refreshes everything.

## Harnesses

`tests/graph_harness.js`, `toast_harness.js`, `sw_harness.js` load the compiled scripts into Node's
`vm` with a stub DOM and print decisions as JSON for pytest to assert on. See [Testing](Testing.md).

**Related:** [Web Layer](Web%20Layer.md) · [Building and Releasing](Building%20and%20Releasing.md)
