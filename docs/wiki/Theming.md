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

- **Background:** light in two corners (as De-Algo comes), a glow from above, a gradient (see
  below), your own picture, or plain.
- **Where the light falls:** top right and bottom left, along the top, along the bottom, or either
  side. This applies to light in two corners.
- **Strength** and **spread of the light:** how strongly the light shows and how far it reaches.
  Strength 0 gives plain paper.
- **When the page scrolls:** the background stays put, or scrolls with the page.
- **Your own picture:** upload one under the section's *Your own picture* and the background
  becomes it. Choose whether it fills the page (cropping the edges), shows whole, or repeats as
  tiles, and which part stays in view when cropped. **Veil over the picture** lays the page
  colour over it, so writing stays readable. The contrast check can't see into a picture, so
  raise the veil if text gets hard to read.
- **Colours:** the two lights, by day and by night. Each starts as one of the garden colours (sage
  and peach) until you untick **Same as …**.

## Gradient

For a gradient background:

- **Kind of gradient:** *linear*, in a straight line; *radial*, out from a point to the furthest
  corner; or *conic*, sweeping round a point and closing where it began.
- **Direction:** which way a linear gradient runs (180° is top to bottom), or where a conic one
  starts.
- **Centred on:** the middle, the top or bottom, or a corner. This is where a radial or conic
  gradient is centred.
- **Colours:** two (start and end) or three (start, middle and end), each by day and by night.
  They start as the page, panel and inset colours.
- **Where the colours meet:** with two colours, the point where they're half-blended; with three,
  where the middle colour sits.

## Pattern and texture

Laid over whatever background you chose, under everything else:

- **Pattern:** none, dots, a grid or diagonal lines, with its own **size**, **strength** and colour.
- **Texture:** paper, fine grain, linen, canvas, concrete or watercolour. It's a surface rather
  than a shape, and it works over light, a gradient or your own picture.
  - **Texture strength** and **texture scale** set how strongly it shows and how coarse it is.
  - **How the texture lies:** *softly* lightens and darkens alike and suits either mode;
    *darkening* shows best by day; *lightening* shows best by night.

## Drawings

The plants drawn at the page's edges and beside each page's heading:

- **Plants:** *Garden* (leafy sprigs and round blooms, as De-Algo comes), *Meadow* (grasses and
  wildflowers), *Fern* (arching fronds), *Blossom* (a flowering branch), or *My own pictures*.
  Your own pictures fill three places: the left edge, the right edge, and beside headings.
  A place you leave empty stays bare. They keep their own colours; the drawing colours below
  only apply to the drawn plants.
- **Where they grow:** at the edges and beside headings, at the edges only, beside headings only,
  or nowhere. Narrow screens never show the edges, where the plants would sit under the text.
- **Which edges:** both sides, left only or right only.
- **Size** and **strength:** how big the edge plants are, and how strongly they show.
- **Colours:** stems, leaves, softer leaves, and three flower colours, by day and by night. Each
  follows a garden colour until you give it its own, so changing the leaf colour under
  Colours changes the drawn leaves too, unless you have set theirs.

**Reset** on Background or Drawings also puts back that section's colours.

## Your own pictures

Your **account picture** is set under Settings, on your account's panel. It replaces your letter
in the bar, is cropped to a square, and only you see it.

PNG, JPEG, GIF or WebP files up to 3 MB, or SVG up to 512 KB. Uploading one puts it in use straight
away, so save any other changes first. **Remove** takes it away. Removing your background picture,
or your last plant picture, also switches that section back to how it comes.

An SVG is cleaned before it is kept. The drawing stays (shapes, paths, gradients and text), and
anything that isn't drawing goes: scripts, styles, links, embedded pages and references to
anything outside the file. If a picture comes out looking different, that is usually why.
Your pictures are only shown to you.

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
  contains nothing else of yours, and none of your pictures.
- **Load a theme:** choose a file, or paste one. Anything in it that isn't a known setting with a
  value of the right kind is refused, and the reason is named.
- **Reset everything:** goes back to the look De-Algo comes with.

Your theme and your pictures are also part of your [setup file](Backup%20and%20Restore.md), so they
come back when you restore one.

**Related:** [Settings](Settings.md) · [Installing as an App](Installing%20as%20an%20App.md)
