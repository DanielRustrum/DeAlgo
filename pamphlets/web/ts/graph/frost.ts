// The ice on a frozen Canvas box, part of the box rather than laid on it.
//
// Inside, clipped to the box's own rounded shape: a frost that fades down
// from the top, and a cap of ice across the top whose lower edge a fringe of
// icicles hangs from. Outside: the bottom edge iced over, round its corners
// as the box's border is, with longer icicles hanging from it between them.
// Every icicle has a lit side, a shaded side and a glint, and some fork.
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

function graphFrostSvg(width: number, height: number, kind: string): SVGElement {
  return graphFrostShape("svg", {
    class: kind, viewBox: `0 0 ${width} ${height}`, width: String(width), height: String(height),
  });
}

/** How far down the ice along the top reaches, so the words sit below it. */
function graphFrostFringe(scale: number): number {
  return 24 * scale;
}

/** The theme's corner radius, which the ice follows round. */
function graphFrostRadius(): number {
  const said = getComputedStyle(document.documentElement).getPropertyValue("--radius");
  const radius = Number.parseFloat(said);
  return Number.isFinite(radius) ? radius : 12;
}

/** One icicle hanging from `top`: its shape, its shaded side, its glint. */
function graphIcicle(left: number, wide: number, long: number, top: number, lean: number): string[] {
  const n = (value: number): string => value.toFixed(1);
  const tipX = left + wide / 2 + lean;
  const tipY = top + long;
  const right = left + wide;
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

/** Icicles from `from` to `to` across, each hanging from `edge(x)`, the
 *  longest `reach` long, drawn into `svg`. */
function graphIcicleRow(
  svg: SVGElement, seed: number, salt: number, from: number, to: number,
  edge: (x: number) => number, scale: number, reach: number,
  taper: (x: number) => number = (): number => 1,
): void {
  const bodies: string[] = [];
  const shades: string[] = [];
  const glints: string[] = [];
  let x = from;
  let index = 0;
  while (x < to - 3 * scale) {
    const noise = (k: number): number => graphFrostNoise(seed, salt + index * 7 + k);
    // Wider and longer where `taper` says the ice is thickest.
    const thick = taper(x);
    const wide = Math.min(to - x, (5 + noise(1) * 7) * scale * (0.6 + thick * 0.6));
    // Every length from a nub to the whole reach, the wider the longer.
    const long = (reach * 0.2 + noise(2) ** 1.3 * reach * 0.8) * (wide / (9 * scale)) ** 0.5 * thick;
    const lean = (noise(3) - 0.5) * wide * 0.3;
    // Rooted a little inside the ice it hangs from, so there is no seam.
    const top = edge(x + wide / 2) - 1.5 * scale;
    const [body, shade, glint] = graphIcicle(x, wide, long, top, lean);
    bodies.push(body ?? "");
    shades.push(shade ?? "");
    if (long > 9 * scale) glints.push(glint ?? "");
    if (noise(4) > 0.62 && wide > 9 * scale) {
      const small = graphIcicle(x + wide * (noise(5) > 0.5 ? 0.55 : 0.05), wide * 0.4, long * 0.45, top + long * 0.18, 0);
      bodies.push(small[0] ?? "");
      shades.push(small[1] ?? "");
    }
    x += wide * (0.7 + noise(6) * 0.35);
    index += 1;
  }
  svg.appendChild(graphFrostShape("path", { d: bodies.join(""), class: "graph-icicle" }));
  svg.appendChild(graphFrostShape("path", { d: shades.join(""), class: "graph-icicle-shade" }));
  svg.appendChild(graphFrostShape("path", {
    d: glints.join(""), class: "graph-icicle-glint", "stroke-width": (1.1 * scale).toFixed(2),
  }));
}

/** The ice for one frozen box, `width` by `height`. */
function graphFrost(seed: number, width: number, height: number, scale: number): HTMLElement {
  const frost = graphElement("div", "graph-frost");
  frost.setAttribute("aria-hidden", "true");
  const n = (value: number): string => value.toFixed(1);

  // Inside the box, clipped to its corners by the layer it is drawn in.
  const inside = graphElement("div", "graph-frost-inside");
  const within = graphFrostSvg(width, height, "graph-frost-art");
  const capEdge = (x: number): number =>
    (5 + Math.sin(x / (11 * scale) + seed) * 1.6 + graphFrostNoise(seed, Math.round(x / (6 * scale))) * 1.4) * scale;
  let cap = `M0,0H${width}V${n(capEdge(width))}`;
  for (let x = width; x >= 0; x -= 4 * scale) cap += `L${n(x)},${n(capEdge(x))}`;
  cap += `L0,${n(capEdge(0))}Z`;
  within.appendChild(graphFrostShape("path", { d: cap, class: "graph-ice-cap" }));
  graphIcicleRow(within, seed, 0, -2 * scale, width + 2 * scale, capEdge, scale, graphFrostFringe(scale) - 4 * scale);
  inside.appendChild(within);
  frost.appendChild(inside);

  // Outside: the bottom edge iced round its corners, and icicles below.
  const radius = Math.min(graphFrostRadius(), width / 2, height / 2);
  const outside = graphFrostSvg(width, height, "graph-frost-art");
  const rim = `M0,${n(height - radius)}A${n(radius)},${n(radius)} 0 0 0 ${n(radius)},${height}`
    + `H${n(width - radius)}A${n(radius)},${n(radius)} 0 0 0 ${width},${n(height - radius)}`;
  graphIcicleRow(outside, seed, 5000, radius * 0.6, width - radius * 0.6, (): number => height, scale, 44 * scale);
  outside.appendChild(graphFrostShape("path", {
    d: rim, class: "graph-ice-rim", "stroke-width": (3.5 * scale).toFixed(2),
  }));
  frost.appendChild(outside);

  frost.appendChild(graphElement("span", "graph-frost-badge", "❄ Frozen"));
  return frost;
}

/** Inside a frozen canvas, a touch of ice on about a third of the boxes —
 *  picked by id, so the same ones every time. A box and the pieces slotted
 *  under it are one stack, and the ice hangs from the bottom of the stack,
 *  where it hangs free. */
function touchGraphWithFrost(state: GraphState): void {
  if (!(state.trail ?? []).some((step): boolean => step.frozen)) return;
  const below = new Map<number, number>();
  for (const one of state.nodes) {
    if (one.piece?.under != null && one.piece.side === "below") below.set(one.piece.under, one.id);
  }
  for (const node of state.nodes) {
    if (node.piece !== null) continue;  // a stack is picked by the box at its top
    if (["comment", "relay", "group", "canvas"].includes(node.kind)) continue;
    if (graphFrostNoise(node.id, 999) >= 0.35) continue;
    let bottom = node.id;
    const seen = new Set<number>([bottom]);
    for (let next = below.get(bottom); next !== undefined && !seen.has(next); next = below.get(next)) {
      seen.add(next);
      bottom = next;
    }
    state.boxes.get(bottom)?.appendChild(graphFrostTouch(node.id));
  }
}

/** A touch of ice along part of a box's bottom edge: a short rim, and a
 *  few small icicles hanging from it. */
function graphFrostTouch(seed: number): HTMLElement {
  const touch = graphElement("div", "graph-frost-touch");
  touch.setAttribute("aria-hidden", "true");
  // Drawn as wide as a box usually is; stretched a little on one that is not.
  const width = 212;
  const svg = graphFrostShape("svg", { viewBox: `0 0 ${width} 18`, preserveAspectRatio: "none" });
  const span = width * (0.3 + graphFrostNoise(seed, 1001) * 0.25);
  const from = 14 + graphFrostNoise(seed, 1002) * (width - 28 - span);
  graphIcicleRow(svg, seed, 9000, from, from + span, (): number => 0, 0.8, 14);
  svg.appendChild(graphFrostShape("path", {
    d: `M${from.toFixed(1)},0H${(from + span).toFixed(1)}`, class: "graph-ice-rim", "stroke-width": "2.5",
  }));
  touch.appendChild(svg);
  return touch;
}

/** Inside a frozen canvas, the view itself iced in its two top corners:
 *  a cap of ice thinning away from each corner, and big icicles hanging
 *  from it, longest at the corner. They stay put while the drawing pans
 *  under them; gone again outside one. Drawn to the view's width. */
function iceGraphView(state: GraphState, frozen: boolean): void {
  const view = state.parts.canvas;
  const was = view.querySelector<HTMLElement>(":scope > .graph-view-frost");
  const width = Math.round(view.clientWidth);
  snowGraphView(state, frozen ? width : 0);
  if (!frozen || width <= 0) {
    was?.remove();
    return;
  }
  // Already iced at this width: the same ice, so nothing to redraw.
  if (was !== null && was.dataset["width"] === String(width)) return;
  const ice = graphElement("div", "graph-view-frost");
  ice.setAttribute("aria-hidden", "true");
  ice.dataset["width"] = String(width);
  const height = 130;
  const svg = graphFrostSvg(width, height, "graph-frost-art");
  const seed = state.inside ?? 1;
  const span = Math.min(260, width * 0.22);
  // How thick the ice is across the view: all at a corner, none past `span`.
  const thick = (x: number): number => {
    const from = Math.min(x, width - x);
    return Math.max(0, 1 - from / span) ** 0.8;
  };
  const capEdge = (x: number): number =>
    (7 + Math.sin(x / 15 + seed) * 2.2 + graphFrostNoise(seed, 7000 + Math.round(x / 8)) * 2) * thick(x);
  // Each corner: the cap across all of its span, the icicles over the part
  // nearest the corner, where the ice is thick enough to drip.
  const corners: [number, number, number, number][] = [
    [-2, span, -2, span * 0.85],
    [width - span, width + 2, width - span * 0.85, width + 2],
  ];
  for (const [from, to, dripFrom, dripTo] of corners) {
    let cap = `M${from},0H${to}`;
    for (let x = to; x >= from; x -= 5) cap += `L${x.toFixed(1)},${capEdge(x).toFixed(1)}`;
    cap += "Z";
    svg.appendChild(graphFrostShape("path", { d: cap, class: "graph-ice-cap" }));
    graphIcicleRow(svg, seed, 8000 + Math.round(from), dripFrom, dripTo, capEdge, 1.6, 95, thick);
  }
  ice.appendChild(svg);
  if (was !== null) was.replaceWith(ice);
  else view.appendChild(ice);
}

/** Snow piled in a frozen canvas's two bottom corners: a drift deepest in
 *  each corner and thinning away from it, a shaded mound behind a brighter
 *  one, with the light along its top. `width` 0 takes them away. */
function snowGraphView(state: GraphState, width: number): void {
  const view = state.parts.canvas;
  const was = view.querySelector<HTMLElement>(":scope > .graph-view-snow");
  if (width <= 0) {
    was?.remove();
    return;
  }
  if (was !== null && was.dataset["width"] === String(width)) return;
  const snow = graphElement("div", "graph-view-snow");
  snow.setAttribute("aria-hidden", "true");
  snow.dataset["width"] = String(width);
  const height = 110;
  const svg = graphFrostSvg(width, height, "graph-frost-art");
  const seed = (state.inside ?? 1) + 31;
  const span = Math.min(300, width * 0.25);
  const n = (value: number): string => value.toFixed(1);

  // How deep the drift is at `x`: all of `tall` in the corner, nothing past
  // `reach`, lumpy on the way.
  const depth = (x: number, reach: number, tall: number, salt: number): number => {
    const from = Math.min(x, width - x);
    const fall = Math.max(0, 1 - from / reach);
    const lumps = Math.sin(x / 23 + seed + salt) * 0.08 + graphFrostNoise(seed, salt + Math.round(x / 30)) * 0.07;
    return tall * fall ** 1.6 * (1 + lumps);
  };
  const mound = (reach: number, tall: number, salt: number, left: boolean): { fill: string; top: string } => {
    const from = left ? 0 : width - reach;
    const to = left ? reach : width;
    let top = "";
    for (let x = from; x <= to; x += 4) {
      top += `${top === "" ? "M" : "L"}${n(x)},${n(height - depth(x, reach, tall, salt))}`;
    }
    const fill = `${top}L${n(to)},${height}L${n(from)},${height}Z`;
    return { fill, top };
  };

  for (const left of [true, false]) {
    const back = mound(span, 70, 11, left);
    const front = mound(span * 0.78, 52, 23, left);
    svg.appendChild(graphFrostShape("path", { d: back.fill, class: "graph-snow-back" }));
    svg.appendChild(graphFrostShape("path", { d: front.fill, class: "graph-snow-front" }));
    svg.appendChild(graphFrostShape("path", { d: front.top, class: "graph-snow-light", "stroke-width": "2" }));
  }
  snow.appendChild(svg);
  if (was !== null) was.replaceWith(snow);
  else view.appendChild(snow);
}
