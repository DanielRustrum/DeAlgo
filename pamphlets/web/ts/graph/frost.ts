// The ice over a frozen Canvas box: one plain SVG — a cap of snow along its
// top and a row of icicles along its bottom — in two flat colours.
//
// Drawn to the box's own width, so it fits however the box was resized, and
// the same on every redraw: the icicles go long, short, medium in turn.
//
// Part of the Configuration canvas; see main.ts.

function graphFrostShape(tag: string, attributes: Record<string, string>): SVGElement {
  const shape = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const name of Object.keys(attributes)) shape.setAttribute(name, attributes[name] ?? "");
  return shape;
}

/** The ice for one frozen box, `width` by `height`, laid over it. */
function graphFrost(width: number, height: number): HTMLElement {
  const frost = graphElement("div", "graph-frost");
  frost.setAttribute("aria-hidden", "true");
  const svg = graphFrostShape("svg", {
    class: "graph-frost-art",
    viewBox: `0 0 ${width} ${height}`,
    width: String(width),
    height: String(height),
  });

  // Snow along the top: even scallops, lying on the edge.
  const bumps = Math.max(3, Math.round(width / 28));
  const across = width / bumps;
  let cap = "M0,6";
  for (let bump = 0; bump < bumps; bump += 1) {
    cap += `a${(across / 2).toFixed(1)},6 0 0 1 ${across.toFixed(1)},0`;
  }
  cap += `V10H0Z`;
  svg.appendChild(graphFrostShape("path", { d: cap, class: "graph-snow" }));

  // Icicles along the bottom: plain points, evenly spaced, in three lengths.
  const lengths = [14, 7, 10];
  const gap = 18;
  const count = Math.max(2, Math.floor((width - 20) / gap));
  const start = (width - (count - 1) * gap) / 2;
  let icicles = "";
  for (let one = 0; one < count; one += 1) {
    const middle = start + one * gap;
    const long = lengths[one % lengths.length] ?? 10;
    icicles += `M${(middle - 4).toFixed(1)},${height}L${middle.toFixed(1)},${height + long}L${(middle + 4).toFixed(1)},${height}Z`;
  }
  svg.appendChild(graphFrostShape("path", { d: icicles, class: "graph-icicle" }));

  frost.appendChild(svg);
  frost.appendChild(graphElement("span", "graph-frost-badge", "❄ Frozen"));
  return frost;
}
