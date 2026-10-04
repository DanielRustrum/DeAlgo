# Theming

**Settings → Theming** changes how De-Algo looks to you. Each account has its own theme, and nobody
else sees yours. Nothing on the page asks for code: every setting is a colour picker, a slider or a
list. A preview on the right shows your changes before you save, and a list under it names anything
that has become hard to read.

Press **Save theme** to keep your changes. The page reloads in the new look.

## Start from

Pick one of these themes, then change anything you like:

| Theme | What it is |
| --- | --- |
| Garden | De-Algo as it comes. |
| High contrast | Darker text, firmer lines and a thicker focus ring, by day and by night. |
| Meadow | A cooler blue-green accent over pale sage. |
| Ink | Black and white, nearly square corners, your device's own typeface and no plants. |
| Compact | The usual colours, with tighter spacing, slightly smaller text and less rounding. |

Picking one replaces your changes. Your choice of light or dark stays, unless the theme you pick sets it.

## Page

- **Light or dark:** follow your device, or always use one. Choosing always light or always dark also
  sets the browser's own bar to match.
- **Movement:** *As little as possible* stops slides, fades and lifts, even if your device doesn't
  ask for that.

## Type

- **Body typeface** and **Heading typeface:** DM Sans and Fraunces, which De-Algo serves itself, or
  one of your device's own fonts: sans-serif, serif, humanist, rounded or monospace. A device font
  depends on what the device has installed.
- **Text size:** every piece of writing scales together, from 85% to 140%.
- **Line spacing:** the space between lines of body text.
- **Heading weight:** how heavy headings and big numbers are.

## Shape and space

- **Roundness:** every corner, from square (0%) to extra soft (160%).
- **Spacing:** padding and gaps. Below 100% fits more on the screen.
- **Shadows:** how far raised panels lift off the page; 0% turns shadows off.
- **Focus ring:** how thick the ring is around whatever the keyboard is on, from 2px to 5px.

## Background

What lies behind the panels:

- **Background:** light in two corners (as De-Algo comes), a glow from above, a gradient from top
  to bottom, or plain.
- **Where the light falls:** top right and bottom left, along the top, along the bottom, or either
  side. This applies to light in two corners.
- **Strength** and **spread of the light:** how strongly the light shows and how far it reaches.
  Strength 0 gives plain paper.
- **Pattern:** none, dots, a grid or diagonal lines, drawn over the light and under everything else.
  Its **size** and **strength** have sliders of their own.
- **When the page scrolls:** the background stays put, or scrolls with the page.
- **Colours:** the two lights, where a gradient ends, and the pattern, by day and by night. Each
  starts as one of the garden colours (sage, peach, the inset and the lines) until you untick
  **Same as …**.

## Drawings

The plants drawn at the page's edges and beside each page's heading:

- **Plants:** *Garden* (leafy sprigs and round blooms, as De-Algo comes), *Meadow* (grasses and
  wildflowers), *Fern* (arching fronds) or *Blossom* (a flowering branch).
- **Where they grow:** at the edges and beside headings, at the edges only, beside headings only,
  or nowhere. Narrow screens never show the edges, where the plants would sit under the text.
- **Which edges:** both sides, left only or right only.
- **Size** and **strength:** how big the edge plants are, and how strongly they show.
- **Colours:** stems, leaves, softer leaves, and three flower colours, by day and by night. Each
  follows a garden colour until you give it its own, so changing the leaf colour under
  Colours changes the drawn leaves too, unless you have set theirs.

**Reset** on Background or Drawings also puts back that section's colours.

## Colours

Every colour De-Algo paints with, in two sets: **By day** and **By night**. Switching between the
two tabs also switches the preview. The colours are grouped:

- **Surfaces:** the page, panels, insets and lines.
- **Text:** body text and quiet text.
- **Accent and focus:** buttons and links, the text written on them, and the focus ring.
- **Status:** worked, waiting and failed, and the text on the failures block.
- **Garden:** the colour blocks and drawings, each with the colour of the text written on it.
- **Stat blocks:** the quiet block on the dashboard.
- **Canvas boxes:** one colour for each kind of box on the [canvas](The%20Configuration%20Canvas.md).
- **Plugin colours:** the seven colours a plugin can choose for its sources, and the letter on a plugin's badge.

The background's and drawings' colours are in their own sections, above.

Some colours follow another one by default. The focus ring and feed boxes follow the accent, for
example, and *green* follows the colour of source boxes. Untick **Same as …** to give one a colour of
its own. **Reset** beside a colour puts that colour back. **Reset** on a section puts back the
whole section.

A colour you leave unchanged keeps up with De-Algo: if a later version changes it, you get the new one.

## Hard to read

The list under the preview checks every pairing De-Algo actually uses, such as text on a panel, a
button's label on the accent, a pill on an inset, or the focus ring on the page. It uses the WCAG
guidelines: text needs a contrast of 4.5:1, and a mark that carries meaning, like a box's coloured
bar, needs 3:1. It only checks the modes your theme can show.

A theme that falls short is still saved, because the look is yours. Saving tells you how many
pairings fall short. The stock look and every theme under Start from pass every check.

## Share or start again

- **Download theme:** saves your theme as a small JSON file holding only what you changed. It
  contains nothing else of yours.
- **Load a theme:** choose a file, or paste one. Anything in it that isn't a known setting with a
  value of the right kind is refused, and the reason is named.
- **Reset everything:** goes back to the look De-Algo comes with.

Your theme is also part of your [setup file](Backup%20and%20Restore.md), so it comes back when you
restore one.

**Related:** [Settings](Settings.md) · [Installing as an App](Installing%20as%20an%20App.md)
