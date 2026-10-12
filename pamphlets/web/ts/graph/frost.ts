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

/** A cap of snow lying along an edge, from `from` to `to`, the edge at
 *  `edge(x)` — so it can follow a box's rounded corners down: low rounded
 *  bumps on top, a pale blue band along its underside, short rounded drips
 *  below, and a few specks. `taper` thins it towards an end. Answers where
 *  its underside is at each `x`, for icicles to hang from. */
function graphSnowCap(
  svg: SVGElement, seed: number, salt: number, from: number, to: number, edge: (x: number) => number,
  scale: number, tall: number, taper: (x: number) => number = (): number => 1,
): (x: number) => number {
  const n = (value: number): string => value.toFixed(1);
  const noise = (k: number): number => graphFrostNoise(seed, salt + k);
  // The underside: a little below the edge, thicker where the snow is.
  const under = (x: number): number =>
    edge(x) + (2.2 + Math.sin(x / (9 * scale) + seed + salt) * 0.8 + noise(Math.round(x / (7 * scale))) * 0.9) * scale * Math.max(0.15, taper(x));

  // The top: rounded bumps, each its own width and height.
  // Its ends round off, as far out as the snow there is thick: a cap that
  // thins to nothing at its ends meets the edge without a blunt end.
  const endFrom = 3 * scale * taper(from);
  const endTo = 3 * scale * taper(to);
  let top = `M${n(from)},${n(under(from))}`;
  top += `C${n(from - endFrom)},${n(under(from))} ${n(from - endFrom * 0.7)},${n(edge(from))} ${n(from + 1 * scale)},${n(edge(from) - endFrom / 3)}`;
  let x = from + 1 * scale;
  let bump = 0;
  while (x < to - 2 * scale) {
    const wide = Math.min(to - 1 * scale - x, (16 + noise(100 + bump) * 26) * scale);
    const mid = x + wide / 2;
    const high = tall * (0.45 + noise(200 + bump) * 0.55) * taper(mid);
    const rest = edge(x + wide) - Math.min(high * 0.35, 3 * scale);
    // Each side of the bump rises from the edge beneath it, so round a
    // corner the snow follows the curve rather than bulging over it.
    const left = edge(x + wide * 0.08) - high * 1.25;
    const right = edge(x + wide * 0.92) - high * 1.25;
    top += `C${n(x + wide * 0.08)},${n(left)} ${n(x + wide * 0.92)},${n(right)} ${n(x + wide)},${n(rest)}`;
    x += wide;
    bump += 1;
  }
  top += `C${n(to + endTo * 0.7)},${n(edge(to))} ${n(to + endTo)},${n(under(to))} ${n(to)},${n(under(to))}`;

  // The underside, back the other way, with a drip now and then.
  let bottom = "";
  const drips: [number, number, number][] = [];
  for (let at = to; at > from; at -= 4 * scale) {
    bottom += `L${n(at)},${n(under(at))}`;
    const k = Math.round(at / (4 * scale));
    if (noise(300 + k) > 0.86 && at - from > 10 * scale && to - at > 10 * scale) {
      const wide = (4 + noise(400 + k) * 4) * scale;
      const long = (4 + noise(500 + k) * 9) * scale * taper(at);
      if (long > 2.5 * scale) {
        const y = under(at);
        bottom += `C${n(at)},${n(y + long * 1.3)} ${n(at - wide)},${n(y + long * 1.3)} ${n(at - wide)},${n(y)}`;
        drips.push([at, wide, long]);
        at -= wide;
      }
    }
  }
  const body = `${top}${bottom}Z`;

  // A deeper blue just under the snow, as its shadow on the edge.
  const shadow = graphFrostShape("path", { d: body, class: "graph-snow-shade" });
  shadow.setAttribute("transform", `translate(0 ${n(2.2 * scale)})`);
  svg.appendChild(shadow);
  svg.appendChild(graphFrostShape("path", { d: body, class: "graph-snow" }));
  // The pale band along its underside, drips and all.
  let band = `M${n(to)},${n(under(to) - 3 * scale)}`;
  for (let at = to; at >= from; at -= 4 * scale) band += `L${n(at)},${n(under(at) - 2.6 * scale * Math.max(0.4, taper(at)))}`;
  band += `L${n(from)},${n(under(from))}`;
  for (let at = from; at <= to; at += 4 * scale) band += `L${n(at)},${n(under(at))}`;
  band += "Z";
  for (const [at, wide, long] of drips) {
    const y = under(at);
    band += `M${n(at)},${n(y)}C${n(at)},${n(y + long * 1.3)} ${n(at - wide)},${n(y + long * 1.3)} ${n(at - wide)},${n(y)}`
      + `C${n(at - wide * 0.8)},${n(y + long * 0.5)} ${n(at - wide * 0.2)},${n(y + long * 0.5)} ${n(at)},${n(y)}Z`;
  }
  svg.appendChild(graphFrostShape("path", { d: band, class: "graph-snow-band" }));
  // A few specks.
  let specks = "";
  for (let k = 0; k < Math.max(2, (to - from) / (40 * scale)); k += 1) {
    const sx = from + noise(600 + k) * (to - from);
    const sy = edge(sx) - tall * 0.25 * taper(sx) * noise(700 + k);
    specks += `M${n(sx)},${n(sy)}h0.01`;
  }
  svg.appendChild(graphFrostShape("path", { d: specks, class: "graph-snow-speck", "stroke-width": (1.6 * scale).toFixed(2) }));
  return (at: number): number => under(at);
}

/** A drift of snow on the ground at `ground`, deepest at `corner` and
 *  nothing `reach` away from it: puffy rounded humps, a pale blue band low
 *  along its front, and specks. */
function graphSnowPile(
  svg: SVGElement, seed: number, salt: number, corner: number, reach: number, ground: number, tall: number,
): void {
  const n = (value: number): string => value.toFixed(1);
  const noise = (k: number): number => graphFrostNoise(seed, salt + k);
  const toward = corner === 0 ? 1 : -1;
  const far = corner + toward * reach;
  const depth = (x: number): number => Math.max(0, 1 - Math.abs(x - corner) / reach) ** 1.25;
  // Humps from the far end to the corner and past it, each rounded.
  let top = `M${n(far)},${n(ground)}`;
  let x = far;
  let hump = 0;
  while ((x - corner) * toward > -4) {
    // Low, wide humps, gently uneven: a drift, not a row of puffs.
    const wide = (60 + noise(10 + hump) * 60) * (0.7 + depth(x) * 0.5);
    const next = x - toward * wide;
    const mid = (x + next) / 2;
    const high = tall * depth(mid) * (0.92 + noise(20 + hump) * 0.16) + 4;
    const end = ground - tall * depth(next) * (0.86 + noise(30 + hump) * 0.08);
    top += `C${n(x - toward * wide * 0.3)},${n(ground - high * 1.08)} ${n(next + toward * wide * 0.3)},${n(ground - high * 1.08)} ${n(next)},${n(Math.min(ground, end))}`;
    x = next;
    hump += 1;
  }
  const body = `${top}L${n(x)},${n(ground + 2)}L${n(far)},${n(ground + 2)}Z`;
  svg.appendChild(graphFrostShape("path", { d: body, class: "graph-snow" }));
  // The pale band low along its front, wavy.
  let band = `M${n(far)},${n(ground)}`;
  for (let at = far; (at - corner) * toward > -4; at -= toward * 6) {
    const lift = (6 + Math.sin(at / 17 + seed) * 3) * depth(at) + 2;
    band += `L${n(at)},${n(ground - lift)}`;
  }
  band += `L${n(x)},${n(ground + 2)}L${n(far)},${n(ground + 2)}Z`;
  svg.appendChild(graphFrostShape("path", { d: band, class: "graph-snow-band" }));
  let specks = "";
  for (let k = 0; k < 7; k += 1) {
    const sx = corner + toward * noise(40 + k) * reach * 0.8;
    const sy = ground - tall * depth(sx) * (0.25 + noise(50 + k) * 0.5);
    specks += `M${n(sx)},${n(sy)}h0.01`;
  }
  svg.appendChild(graphFrostShape("path", { d: specks, class: "graph-snow-speck", "stroke-width": "2" }));
}

/** The ice for one frozen box, `width` by `height`. */
function graphFrost(seed: number, width: number, height: number, scale: number): HTMLElement {
  const frost = graphElement("div", "graph-frost");
  frost.setAttribute("aria-hidden", "true");
  const n = (value: number): string => value.toFixed(1);

  // Inside the box, clipped to its corners by the layer it is drawn in.
  const inside = graphElement("div", "graph-frost-inside");
  const within = graphFrostSvg(width, height, "graph-frost-art");
  const outside = graphFrostSvg(width, height, "graph-frost-art");
  // The box's own outline, round its corners: how far down from its top
  // edge, and up from its bottom one, the border is at each `x`.
  const radius = Math.min(graphFrostRadius(), width / 2, height / 2);
  const corner = (x: number): number => {
    const into = x < radius ? radius - x : x > width - radius ? x - (width - radius) : 0;
    return radius - Math.sqrt(Math.max(0, radius * radius - into * into));
  };
  // Snow lying low along the top, on the border and round its corners, the
  // icicles hanging inside the box from its underside.
  const topUnder = graphSnowCap(outside, seed, 0, 0, width, (x: number): number => corner(x), scale, 3.5 * scale);
  graphIcicleRow(within, seed, 0, -2 * scale, width + 2 * scale, topUnder, scale, graphFrostFringe(scale) - 4 * scale);
  inside.appendChild(within);
  frost.appendChild(inside);

  // And along the bottom, round its corners, the long icicles hanging
  // below from its underside. Icicles first, so the snow covers their roots.
  const hanging = graphFrostShape("g", {});
  outside.appendChild(hanging);
  // Thinning to nothing as it goes round the corners, so it melts into the
  // border there rather than ending in a slab.
  const melt = (x: number): number => {
    const t = Math.min(1, Math.max(0, Math.min(x, width - x) / (radius * 1.8)));
    return t * t * (3 - 2 * t);
  };
  const bottomUnder = graphSnowCap(
    outside, seed, 3000, 0, width, (x: number): number => height - corner(x), scale, 3.5 * scale, melt,
  );
  graphIcicleRow(hanging, seed, 5000, radius * 0.6, width - radius * 0.6,
    (x: number): number => bottomUnder(x) - 1.5 * scale, scale, 44 * scale);
  frost.appendChild(outside);

  frost.appendChild(graphElement("span", "graph-frost-badge", "❄ Frozen"));
  return frost;
}

/** Inside a frozen canvas, a touch of frost on about a third of the boxes —
 *  picked by id, so the same ones every time: either snow on top or
 *  icicles below, never both. A box and the pieces slotted under it are one
 *  stack: snow lies on the box at its top, icicles hang from its bottom. */
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
    // Laid out by now, so it is drawn to the box's own width. One or the
    // other, never both — a Canvas box is the one that is snowed in: snow
    // on the top of the stack, or icicles from the bottom of it.
    if (graphFrostNoise(node.id, 998) < 0.5) {
      const top = state.boxes.get(node.id);
      if (top !== undefined) top.appendChild(graphFrostSnowfall(node.id, top.offsetWidth));
    } else {
      const box = state.boxes.get(bottom);
      if (box !== undefined) box.appendChild(graphFrostTouch(node.id, box.offsetWidth));
    }
  }
}

/** A touch of ice on part of a box's bottom edge, `width` wide: a ridge of
 *  ice along the border, thickest where it drips and thinning to nothing
 *  at its ends, and a few icicles of any length growing out of it, with
 *  gaps between. No slab of its own: the box's own edge is what it is on. */
function graphFrostTouch(seed: number, width: number): HTMLElement {
  const touch = graphElement("div", "graph-frost-touch");
  touch.setAttribute("aria-hidden", "true");
  const n = (value: number): string => value.toFixed(1);
  const noise = (k: number): number => graphFrostNoise(seed, 9000 + k);
  // The edge is `above` down the drawing.
  const above = 8;
  const svg = graphFrostSvg(width, 30, "graph-frost-art");
  const radius = Math.min(graphFrostRadius(), width / 2);
  const span = Math.min(width - radius * 2, width * (0.3 + noise(1) * 0.25));
  const from = radius + noise(2) * Math.max(0, width - radius * 2 - span);
  const to = from + span;
  const melt = (x: number): number => {
    const t = Math.min(1, Math.max(0, Math.min(x - from, to - x) / (span * 0.3)));
    return t * t * (3 - 2 * t);
  };

  // Where each icicle hangs: spaced out, never touching, smaller to the ends.
  const icicles: [number, number, number][] = [];
  for (let x = from + span * 0.1, k = 0; x < to - span * 0.1; k += 1) {
    const m = melt(x);
    const wide = (3.5 + noise(10 + k) * 4) * (0.55 + m * 0.45);
    const long = (3 + noise(20 + k) ** 1.4 * 16) * m + 2;
    icicles.push([x, wide, long]);
    x += wide + (3 + noise(30 + k) * 9);
  }
  // How far below the border the ridge reaches at `x`: a little everywhere
  // it is thick, more where an icicle grows from it.
  const sag = (x: number): number => {
    let most = 0;
    for (const [at, wide] of icicles) {
      const into = Math.abs(x - (at + wide / 2)) / (wide * 0.9);
      if (into < 1) most = Math.max(most, (1 - into * into) * 2.2);
    }
    return (0.9 + most) * melt(x);
  };

  const bodies: string[] = [];
  const shades: string[] = [];
  const glints: string[] = [];
  for (const [at, wide, long] of icicles) {
    const [body, shade, glint] = graphIcicle(at, wide, long, above + sag(at + wide / 2) - 1.2, (noise(at) - 0.5) * wide * 0.25);
    bodies.push(body ?? "");
    shades.push(shade ?? "");
    if (long > 8) glints.push(glint ?? "");
  }
  svg.appendChild(graphFrostShape("path", { d: bodies.join(""), class: "graph-icicle" }));
  svg.appendChild(graphFrostShape("path", { d: shades.join(""), class: "graph-icicle-shade" }));
  svg.appendChild(graphFrostShape("path", { d: glints.join(""), class: "graph-icicle-glint", "stroke-width": "0.9" }));

  // The ridge over the border, lying on it: over the icicles' roots.
  let ridge = `M${n(from)},${above}`;
  for (let x = from; x <= to; x += 2) ridge += `L${n(x)},${n(above - 1.1 * melt(x))}`;
  for (let x = to; x >= from; x -= 2) ridge += `L${n(x)},${n(above + sag(x))}`;
  ridge += "Z";
  svg.appendChild(graphFrostShape("path", { d: ridge, class: "graph-frost-ridge" }));
  touch.appendChild(svg);
  return touch;
}

/** A little snow lying on part of a box's top edge, `width` wide, thinning
 *  to nothing at both ends so it settles into the border. */
function graphFrostSnowfall(seed: number, width: number): HTMLElement {
  const fall = graphElement("div", "graph-frost-fall");
  fall.setAttribute("aria-hidden", "true");
  // The edge is `above` down the drawing, so the snow on it has room.
  const above = 10;
  const svg = graphFrostSvg(width, 18, "graph-frost-art");
  const radius = Math.min(graphFrostRadius(), width / 2);
  const span = Math.min(width - radius * 2, width * (0.35 + graphFrostNoise(seed, 1101) * 0.3));
  const from = radius + graphFrostNoise(seed, 1102) * Math.max(0, width - radius * 2 - span);
  const to = from + span;
  const melt = (x: number): number => {
    const t = Math.min(1, Math.max(0, Math.min(x - from, to - x) / (span * 0.3)));
    return t * t * (3 - 2 * t);
  };
  graphSnowCap(svg, seed, 9100, from, to, (): number => above, 0.9, 4.5, melt);
  fall.appendChild(svg);
  return fall;
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

  graphSnowPile(svg, seed, 0, 0, span, height, 50);
  graphSnowPile(svg, seed, 90, width, span, height, 50);
  snow.appendChild(svg);
  if (was !== null) was.replaceWith(snow);
  else view.appendChild(snow);
}
