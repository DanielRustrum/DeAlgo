// The ice on a frozen Canvas box: a fringe of icicles hanging from its top
// edge, and longer ones from its bottom edge, each grown from a band of ice
// along the edge. Every icicle is drawn the way ice catches light — a lit
// side, a shaded side, a glint — and some fork into a second, smaller drip.
//
// Drawn to the box's own size, and the same on every redraw: each icicle's
// width and length come from the box's id, not from chance.
//
// Part of the Configuration canvas; see main.ts.

/** A number from 0 to 1 that is always the same for the same two. */
function graphFrostNoise(seed: number, index: number): number {
  const value = Math.sin(seed * 12.9898 + index * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

function graphFrostShape(tag: string, attributes: Record<string, string>): SVGElement {
  const shape = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const name of Object.keys(attributes)) shape.setAttribute(name, attributes[name] ?? "");
  return shape;
}

/** How tall the fringe along the top is, so the words can sit below it. */
function graphFrostFringe(scale: number): number {
  return 26 * scale;
}

/** One icicle hanging from `top`: its whole shape, its shaded side and its
 *  glint, as three paths. */
function graphIcicle(left: number, wide: number, long: number, top: number, lean: number): string[] {
  const n = (value: number): string => value.toFixed(1);
  const tipX = left + wide / 2 + lean;
  const tipY = top + long;
  const right = left + wide;
  // Pinched in a little a third of the way down, as ice drips do.
  const waist = top + long * 0.35;
  const body = `M${n(left)},${n(top)}`
    + `C${n(left - wide * 0.05)},${n(waist)} ${n(left + wide * 0.22)},${n(top + long * 0.6)} ${n(tipX)},${n(tipY)}`
    + `C${n(right - wide * 0.2)},${n(top + long * 0.6)} ${n(right + wide * 0.04)},${n(waist)} ${n(right)},${n(top)}Z`;
  const middle = left + wide * 0.55;
  const shade = `M${n(middle)},${n(top)}`
    + `C${n(middle + wide * 0.05)},${n(waist)} ${n(tipX + wide * 0.08)},${n(top + long * 0.7)} ${n(tipX)},${n(tipY)}`
    + `C${n(right - wide * 0.2)},${n(top + long * 0.6)} ${n(right + wide * 0.04)},${n(waist)} ${n(right)},${n(top)}Z`;
  const glint = `M${n(left + wide * 0.28)},${n(top + 1)}`
    + `Q${n(left + wide * 0.3)},${n(top + long * 0.4)} ${n(tipX - wide * 0.06)},${n(top + long * 0.78)}`;
  return [body, shade, glint];
}

/** A row of icicles along one edge, from `top`, `count` of them across
 *  `width`, the longest `reach` long. */
function graphIcicleRow(
  svg: SVGElement, seed: number, salt: number, width: number, top: number,
  scale: number, reach: number,
): void {
  const bodies: string[] = [];
  const shades: string[] = [];
  const glints: string[] = [];
  let x = -1 * scale;
  let index = 0;
  while (x < width - 2 * scale) {
    const noise = (k: number): number => graphFrostNoise(seed, salt + index * 7 + k);
    const wide = Math.min(width - x, (5 + noise(1) * 7) * scale);
    // Every length from a nub to the whole reach, longer ones the wider
    // they are: a fringe, not a comb.
    const long = (reach * 0.2 + noise(2) ** 1.3 * reach * 0.8) * (wide / (9 * scale)) ** 0.5;
    const lean = (noise(3) - 0.5) * wide * 0.3;
    const [body, shade, glint] = graphIcicle(x, wide, long, top, lean);
    bodies.push(body ?? "");
    shades.push(shade ?? "");
    if (long > 9 * scale) glints.push(glint ?? "");
    // Some fork: a smaller drip off one shoulder.
    if (noise(4) > 0.62 && wide > 9 * scale) {
      const small = graphIcicle(x + wide * (noise(5) > 0.5 ? 0.55 : 0.05), wide * 0.4, long * 0.45, top + long * 0.18, 0);
      bodies.push(small[0] ?? "");
      shades.push(small[1] ?? "");
    }
    // Packed close, overlapping a little, as a fringe of ice is.
    x += wide * (0.7 + noise(6) * 0.35);
    index += 1;
  }
  svg.appendChild(graphFrostShape("path", { d: bodies.join(""), class: "graph-icicle" }));
  svg.appendChild(graphFrostShape("path", { d: shades.join(""), class: "graph-icicle-shade" }));
  svg.appendChild(graphFrostShape("path", { d: glints.join(""), class: "graph-icicle-glint", "stroke-width": (1.1 * scale).toFixed(2) }));
  // The band of ice along the edge they grow from.
  const band = 3 * scale;
  svg.appendChild(graphFrostShape("rect", {
    x: String(-1 * scale), y: (top - band * 0.6).toFixed(1), width: (width + 2 * scale).toFixed(1),
    height: band.toFixed(1), rx: (band / 2).toFixed(1), class: "graph-ice-band",
  }));
}

/** The ice for one frozen box, `width` by `height`, laid over it. */
function graphFrost(seed: number, width: number, height: number, scale: number): HTMLElement {
  const frost = graphElement("div", "graph-frost");
  frost.setAttribute("aria-hidden", "true");
  const svg = graphFrostShape("svg", {
    class: "graph-frost-art",
    viewBox: `0 0 ${width} ${height}`,
    width: String(width),
    height: String(height),
  });
  // Short ones inside along the top; longer ones below the bottom edge.
  graphIcicleRow(svg, seed, 0, width, 1 * scale, scale, graphFrostFringe(scale));
  graphIcicleRow(svg, seed, 5000, width, height - 1 * scale, scale, 44 * scale);
  frost.appendChild(svg);
  frost.appendChild(graphElement("span", "graph-frost-badge", "❄ Frozen"));
  return frost;
}
