// The ice over a frozen Canvas box: a cap of snow along its top, icicles
// hanging from its bottom edge, frost in its corners and a few flakes.
//
// Drawn to the box's own size, so it fits however the box was resized, and
// the same every time for the same box: each icicle's length comes from the
// box's id, not from chance, so a redraw does not make the ice twitch.
//
// Part of the Configuration canvas; see main.ts.

/** A number from 0 to 1 that is always the same for the same two. */
function graphFrostNoise(seed: number, index: number): number {
  const value = Math.sin(seed * 12.9898 + index * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

function graphFrostShape(tag: string, attributes: Record<string, string>): SVGElement {
  const shape = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) shape.setAttribute(name, value);
  return shape;
}

/** The ice for one frozen box, `width` by `height`, laid over it. */
function graphFrost(seed: number, width: number, height: number): HTMLElement {
  const frost = graphElement("div", "graph-frost");
  frost.setAttribute("aria-hidden", "true");
  const scale = Math.max(0.75, Math.min(4, Math.min(width / 220, height / 104)));
  const svg = graphFrostShape("svg", {
    class: "graph-frost-art",
    viewBox: `0 0 ${width} ${height}`,
    width: String(width),
    height: String(height),
  });

  // Each box's gradients its own: two frozen boxes on the canvas at once
  // must not share ids.
  const iceId = `graph-ice-${seed}`;
  const defs = graphFrostShape("defs", {});
  const ice = graphFrostShape("linearGradient", { id: iceId, x1: "0", y1: "0", x2: "0", y2: "1" });
  ice.appendChild(graphFrostShape("stop", { offset: "0", class: "graph-ice-top" }));
  ice.appendChild(graphFrostShape("stop", { offset: "1", class: "graph-ice-tip" }));
  defs.appendChild(ice);
  svg.appendChild(defs);

  // Frost creeping in from the corners: a few crystal branches in each.
  const corners: [number, number, number, number][] = [[0, 0, 1, 1], [width, 0, -1, 1], [0, height, 1, -1], [width, height, -1, -1]];
  corners.forEach(([x, y, dx, dy], corner): void => {
    const reach = (26 + graphFrostNoise(seed, corner) * 16) * scale;
    let path = "";
    for (let branch = 0; branch < 4; branch += 1) {
      const angle = (branch + 0.5) * (Math.PI / 2) / 4;
      const long = reach * (0.55 + graphFrostNoise(seed, corner * 10 + branch) * 0.45);
      const ex = x + dx * Math.cos(angle) * long;
      const ey = y + dy * Math.sin(angle) * long;
      path += `M${x},${y}L${ex.toFixed(1)},${ey.toFixed(1)}`;
      // Two twigs off each branch, the way frost feathers.
      for (const at of [0.45, 0.72]) {
        const bx = x + (ex - x) * at;
        const by = y + (ey - y) * at;
        const twig = long * 0.22;
        path += `M${bx.toFixed(1)},${by.toFixed(1)}l${(dx * twig * 0.9).toFixed(1)},${(-dy * twig * 0.2).toFixed(1)}`;
        path += `M${bx.toFixed(1)},${by.toFixed(1)}l${(-dx * twig * 0.2).toFixed(1)},${(dy * twig * 0.9).toFixed(1)}`;
      }
    }
    svg.appendChild(graphFrostShape("path", { d: path, class: "graph-frost-crystal", "stroke-width": String(1.1 * scale) }));
  });

  // A few flakes, scattered the same way every time.
  for (let flake = 0; flake < 5; flake += 1) {
    const cx = width * (0.15 + graphFrostNoise(seed, 50 + flake) * 0.7);
    const cy = height * (0.2 + graphFrostNoise(seed, 60 + flake) * 0.6);
    const r = (3 + graphFrostNoise(seed, 70 + flake) * 3) * scale;
    let arms = "";
    for (let arm = 0; arm < 3; arm += 1) {
      const a = (arm * Math.PI) / 3;
      const ax = Math.cos(a) * r;
      const ay = Math.sin(a) * r;
      arms += `M${(cx - ax).toFixed(1)},${(cy - ay).toFixed(1)}L${(cx + ax).toFixed(1)},${(cy + ay).toFixed(1)}`;
    }
    svg.appendChild(graphFrostShape("path", { d: arms, class: "graph-frost-flake", "stroke-width": String(0.9 * scale) }));
  }

  // Icicles hanging off the bottom edge: thick at the root, tapering to a
  // point, longer and shorter by turns, with a glint down one side.
  const step = 15 * scale;
  const count = Math.max(3, Math.floor((width - 16 * scale) / step));
  const start = (width - count * step) / 2;
  for (let one = 0; one < count; one += 1) {
    const left = start + one * step + graphFrostNoise(seed, 100 + one) * 3 * scale;
    const wide = (8 + graphFrostNoise(seed, 200 + one) * 6) * scale;
    const long = (8 + graphFrostNoise(seed, 300 + one) ** 1.6 * 26) * scale;
    const mid = left + wide / 2 + (graphFrostNoise(seed, 400 + one) - 0.5) * 2 * scale;
    const top = height - 2 * scale;
    const d = `M${left.toFixed(1)},${top.toFixed(1)}`
      + `Q${(left + wide * 0.18).toFixed(1)},${(top + long * 0.55).toFixed(1)} ${mid.toFixed(1)},${(top + long).toFixed(1)}`
      + `Q${(left + wide * 0.82).toFixed(1)},${(top + long * 0.55).toFixed(1)} ${(left + wide).toFixed(1)},${top.toFixed(1)}Z`;
    svg.appendChild(graphFrostShape("path", { d, fill: `url(#${iceId})`, class: "graph-icicle", "stroke-width": String(0.8 * scale) }));
    svg.appendChild(graphFrostShape("path", {
      d: `M${(left + wide * 0.3).toFixed(1)},${(top + 1.5 * scale).toFixed(1)}Q${(left + wide * 0.36).toFixed(1)},${(top + long * 0.45).toFixed(1)} ${(mid - wide * 0.05).toFixed(1)},${(top + long * 0.78).toFixed(1)}`,
      class: "graph-icicle-glint", "stroke-width": String(1.1 * scale),
    }));
  }

  // The cap of snow along the top: lumpy, and lapping over the edge.
  const lumps = Math.max(4, Math.round(width / (26 * scale)));
  let cap = `M${(-2 * scale).toFixed(1)},${(6 * scale).toFixed(1)}`;
  for (let lump = 0; lump <= lumps; lump += 1) {
    const x = (width + 4 * scale) * (lump / lumps) - 2 * scale;
    const rise = (3 + graphFrostNoise(seed, 500 + lump) * 5) * scale;
    const dip = (5 + graphFrostNoise(seed, 600 + lump) * 5) * scale;
    cap += `Q${(x - (width / lumps) / 2).toFixed(1)},${(-rise).toFixed(1)} ${x.toFixed(1)},${(dip * 0.6).toFixed(1)}`;
  }
  cap += `L${(width + 2 * scale).toFixed(1)},${(9 * scale).toFixed(1)}`;
  for (let lump = lumps; lump >= 0; lump -= 1) {
    const x = (width + 4 * scale) * (lump / lumps) - 2 * scale;
    const hang = (7 + graphFrostNoise(seed, 700 + lump) * 7) * scale;
    cap += `Q${(x + (width / lumps) / 2).toFixed(1)},${(hang + 3 * scale).toFixed(1)} ${x.toFixed(1)},${(hang * 0.7).toFixed(1)}`;
  }
  cap += "Z";
  svg.appendChild(graphFrostShape("path", { d: cap, class: "graph-snow", "stroke-width": String(0.8 * scale) }));

  frost.appendChild(svg);
  frost.appendChild(graphElement("span", "graph-frost-badge", "❄ Frozen"));
  return frost;
}
