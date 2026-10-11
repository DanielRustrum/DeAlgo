// How a wire is drawn from one port to another: a curve, a straight line,
// square elbows, or a path found round the boxes in its way (A*).
//
// Each end of a wire has a place and a way it faces — out of the right of a
// box, into the left; a Relay can face any way round — and every way of
// drawing leaves and arrives along those. A box folded away inside a group
// has its wires end on the edge of the folded group instead.
//
// Part of the Configuration canvas; see main.ts.

/** One end of a wire: where it is, the way it leaves (pointing away from its
 *  box), and the folded group it has been gathered into, if any. */
interface GraphWireEnd {
  x: number;
  y: number;
  dx: number;
  dy: number;
  folded: number | null;
}

/** Where a wire starts or ends, and which way it faces there. */
function graphWireEnd(
  state: GraphState, nodeId: number, where: "in" | "out", carries: GraphCarries,
): GraphWireEnd | null {
  // Folded away: the wire ends on the edge of the group it is folded into.
  const group = state.hiddenIn?.get(nodeId);
  if (group !== undefined) {
    const frame = state.boxes.get(group);
    const holder = state.nodes.find((one): boolean => one.id === group);
    if (frame === undefined || holder === undefined) return null;
    const y = holder.y + frame.offsetHeight / 2;
    return where === "out"
      ? { x: holder.x + frame.offsetWidth, y, dx: 1, dy: 0, folded: group }
      : { x: holder.x, y, dx: -1, dy: 0, folded: group };
  }
  const node = state.nodes.find((one): boolean => one.id === nodeId);
  const box = state.boxes.get(nodeId);
  if (node === undefined || box === undefined) return null;
  if (node.kind === "relay") {
    // A relay faces as it was told: in on one side, out on the opposite.
    const w = box.offsetWidth;
    const h = box.offsetHeight;
    const faces = node.relay?.faces ?? "right";
    const side = where === "in"
      ? { right: "left", left: "right", down: "top", up: "bottom" }[faces] ?? "left"
      : { right: "right", left: "left", down: "bottom", up: "top" }[faces] ?? "right";
    if (side === "left") return { x: node.x, y: node.y + h / 2, dx: -1, dy: 0, folded: null };
    if (side === "right") return { x: node.x + w, y: node.y + h / 2, dx: 1, dy: 0, folded: null };
    if (side === "top") return { x: node.x + w / 2, y: node.y, dx: 0, dy: -1, folded: null };
    return { x: node.x + w / 2, y: node.y + h, dx: 0, dy: 1, folded: null };
  }
  const point = graphPortPoint(state, nodeId, where, carries);
  if (point === null) return null;
  return { x: point.x, y: point.y, dx: where === "out" ? 1 : -1, dy: 0, folded: null };
}

/** A wire's path, drawn the way it was told to be. */
function graphWirePath(state: GraphState, route: string, a: GraphWireEnd, b: GraphWireEnd): string {
  if (route === "straight") return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
  if (route === "square") return graphRounded(graphSquarePoints(a, b));
  if (route === "astar") return graphRounded(graphFoundPoints(state, a, b) ?? graphSquarePoints(a, b));
  return graphBend(a, b);
}

/** A curve that leaves and arrives along each end's way. Out of a right
 *  side into a left one, the same gentle S the canvas has always drawn. */
function graphBend(a: GraphWireEnd, b: GraphWireEnd): string {
  const reach = (end: GraphWireEnd): number =>
    Math.max(40, (end.dx !== 0 ? Math.abs(b.x - a.x) : Math.abs(b.y - a.y)) * 0.5);
  const ra = reach(a);
  const rb = reach(b);
  return `M ${a.x} ${a.y} C ${a.x + a.dx * ra} ${a.y + a.dy * ra}, ${b.x + b.dx * rb} ${b.y + b.dy * rb}, ${b.x} ${b.y}`;
}

/** How far a wire runs straight out of a port before it turns. */
function graphLead(): number {
  return 18;
}

/** Square elbows: straight out of each port, then across and along. */
function graphSquarePoints(a: GraphWireEnd, b: GraphWireEnd): [number, number][] {
  const lead = graphLead();
  const a1: [number, number] = [a.x + a.dx * lead, a.y + a.dy * lead];
  const b1: [number, number] = [b.x + b.dx * lead, b.y + b.dy * lead];
  const across = (end: GraphWireEnd): boolean => end.dx !== 0;
  let middle: [number, number][];
  if (across(a) && across(b)) {
    const mx = (a1[0] + b1[0]) / 2;
    middle = [[mx, a1[1]], [mx, b1[1]]];
  } else if (!across(a) && !across(b)) {
    const my = (a1[1] + b1[1]) / 2;
    middle = [[a1[0], my], [b1[0], my]];
  } else if (across(a)) {
    middle = [[b1[0], a1[1]]];
  } else {
    middle = [[a1[0], b1[1]]];
  }
  return [[a.x, a.y], a1, ...middle, b1, [b.x, b.y]];
}

/** A path round the boxes in the way: A* over a grid, every box an
 *  obstacle with a margin round it, turning costing more than going on so
 *  the path keeps to few, clean elbows. Null if there is no way within
 *  reach, for the caller to fall back on square elbows. */
function graphFoundPoints(state: GraphState, a: GraphWireEnd, b: GraphWireEnd): [number, number][] | null {
  const cell = 16;
  const margin = 10;
  const lead = graphLead();
  const start: [number, number] = [a.x + a.dx * lead, a.y + a.dy * lead];
  const goal: [number, number] = [b.x + b.dx * lead, b.y + b.dy * lead];

  // The grid: round both ends, with room to go round what is between.
  const room = 320;
  const left = Math.min(start[0], goal[0]) - room;
  const top = Math.min(start[1], goal[1]) - room;
  const cols = Math.ceil((Math.abs(start[0] - goal[0]) + 2 * room) / cell) + 1;
  const rows = Math.ceil((Math.abs(start[1] - goal[1]) + 2 * room) / cell) + 1;
  if (cols * rows > 120000) return null;
  const blocked = new Uint8Array(cols * rows);
  for (const node of state.nodes) {
    if (node.kind === "group" || node.kind === "comment" || state.hiddenIn?.has(node.id) === true) continue;
    const box = state.boxes.get(node.id);
    if (box === undefined) continue;
    const x0 = Math.floor((node.x - margin - left) / cell);
    const y0 = Math.floor((node.y - margin - top) / cell);
    const x1 = Math.ceil((node.x + box.offsetWidth + margin - left) / cell);
    const y1 = Math.ceil((node.y + box.offsetHeight + margin - top) / cell);
    for (let gy = Math.max(0, y0); gy <= Math.min(rows - 1, y1); gy += 1) {
      for (let gx = Math.max(0, x0); gx <= Math.min(cols - 1, x1); gx += 1) blocked[gy * cols + gx] = 1;
    }
  }
  const at = (point: [number, number]): [number, number] => [
    Math.max(0, Math.min(cols - 1, Math.round((point[0] - left) / cell))),
    Math.max(0, Math.min(rows - 1, Math.round((point[1] - top) / cell))),
  ];
  const [sx, sy] = at(start);
  const [gx, gy] = at(goal);
  // Where a wire leaves and arrives is never blocked: it is right by its box.
  blocked[sy * cols + sx] = 0;
  blocked[gy * cols + gx] = 0;

  // States are a cell and the way it was entered, so a turn can cost more.
  const steps: [number, number][] = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const turn = 4;
  const key = (x: number, y: number, way: number): number => (y * cols + x) * 4 + way;
  const cost = new Map<number, number>();
  const came = new Map<number, number>();
  const heap: [number, number, number, number, number][] = []; // [f, g, x, y, way]
  const push = (item: [number, number, number, number, number]): void => {
    heap.push(item);
    let i = heap.length - 1;
    while (i > 0) {
      const up = (i - 1) >> 1;
      const parent = heap[up];
      const here = heap[i];
      if (parent === undefined || here === undefined || parent[0] <= here[0]) break;
      heap[up] = here;
      heap[i] = parent;
      i = up;
    }
  };
  const pop = (): [number, number, number, number, number] | undefined => {
    const top0 = heap[0];
    const last = heap.pop();
    if (heap.length > 0 && last !== undefined) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let small = i;
        const hs = heap[small];
        const hl = heap[l];
        const hr = heap[r];
        if (hl !== undefined && hs !== undefined && hl[0] < hs[0]) small = l;
        const hm = heap[small];
        if (hr !== undefined && hm !== undefined && hr[0] < hm[0]) small = r;
        if (small === i) break;
        const a0 = heap[i];
        const b0 = heap[small];
        if (a0 === undefined || b0 === undefined) break;
        heap[i] = b0;
        heap[small] = a0;
        i = small;
      }
    }
    return top0;
  };
  const guess = (x: number, y: number): number => Math.abs(x - gx) + Math.abs(y - gy);
  const firstWay = steps.findIndex(([dx, dy]): boolean => dx === Math.sign(a.dx) && dy === Math.sign(a.dy));
  const begin = key(sx, sy, Math.max(0, firstWay));
  cost.set(begin, 0);
  push([guess(sx, sy), 0, sx, sy, Math.max(0, firstWay)]);
  let found = -1;
  let spent = 0;
  while (heap.length > 0 && spent < 60000) {
    const item = pop();
    if (item === undefined) break;
    spent += 1;
    const [, g, x, y, way] = item;
    const here = key(x, y, way);
    if (g > (cost.get(here) ?? Infinity)) continue;
    if (x === gx && y === gy) {
      found = here;
      break;
    }
    steps.forEach(([dx, dy], nextWay): void => {
      const nx = x + dx;
      const ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= cols || ny >= rows || blocked[ny * cols + nx] === 1) return;
      const ng = g + 1 + (nextWay === way ? 0 : turn);
      const next = key(nx, ny, nextWay);
      if (ng >= (cost.get(next) ?? Infinity)) return;
      cost.set(next, ng);
      came.set(next, here);
      push([ng + guess(nx, ny), ng, nx, ny, nextWay]);
    });
  }
  if (found < 0) return null;

  // Back from the goal, keeping only the corners.
  const cells: [number, number][] = [];
  for (let walk: number | undefined = found; walk !== undefined; walk = came.get(walk)) {
    const index = Math.floor(walk / 4);
    cells.push([left + (index % cols) * cell, top + Math.floor(index / cols) * cell]);
    if (walk === begin) break;
  }
  cells.reverse();
  return [[a.x, a.y], start, ...cells, goal, [b.x, b.y]];
}

/** Points joined by straight runs, each corner rounded a little. Points on
 *  a line with their neighbours are left out first. */
function graphRounded(points: [number, number][]): string {
  const kept: [number, number][] = [];
  for (const point of points) {
    const last = kept[kept.length - 1];
    if (last !== undefined && Math.abs(last[0] - point[0]) < 0.5 && Math.abs(last[1] - point[1]) < 0.5) continue;
    const before = kept[kept.length - 2];
    if (before !== undefined && last !== undefined) {
      const cross = (last[0] - before[0]) * (point[1] - last[1]) - (last[1] - before[1]) * (point[0] - last[0]);
      if (Math.abs(cross) < 0.5) kept.pop();
    }
    kept.push(point);
  }
  const first = kept[0];
  if (first === undefined) return "";
  let d = `M ${first[0]} ${first[1]}`;
  for (let i = 1; i < kept.length; i += 1) {
    const here = kept[i];
    const prev = kept[i - 1];
    const next = kept[i + 1];
    if (here === undefined || prev === undefined) continue;
    if (next === undefined) {
      d += ` L ${here[0]} ${here[1]}`;
      continue;
    }
    // Cut the corner by up to 8px, never more than half either run.
    const r = Math.min(8, Math.hypot(here[0] - prev[0], here[1] - prev[1]) / 2, Math.hypot(next[0] - here[0], next[1] - here[1]) / 2);
    const inX = here[0] - Math.sign(here[0] - prev[0]) * r;
    const inY = here[1] - Math.sign(here[1] - prev[1]) * r;
    const outX = here[0] + Math.sign(next[0] - here[0]) * r;
    const outY = here[1] + Math.sign(next[1] - here[1]) * r;
    d += ` L ${inX} ${inY} Q ${here[0]} ${here[1]} ${outX} ${outY}`;
  }
  return d;
}

/** The boxes each folded group hides, by box: everything it surrounds, and
 *  the pieces slotted under those. */
function graphFoldedAway(state: GraphState): Map<number, number> {
  const hidden = new Map<number, number>();
  for (const group of state.nodes) {
    if (group.kind !== "group" || group.look?.collapsed !== true) continue;
    for (const inside of graphSurrounded(state, group)) hidden.set(inside.id, group.id);
  }
  // A piece goes where its box goes, however it hangs.
  for (let changed = true; changed;) {
    changed = false;
    for (const node of state.nodes) {
      const under = node.piece?.under;
      if (under === null || under === undefined || hidden.has(node.id)) continue;
      const group = hidden.get(under);
      if (group !== undefined) {
        hidden.set(node.id, group);
        changed = true;
      }
    }
  }
  return hidden;
}

/** What a picked wire offers beside its ✕: the ways it can be drawn. */
function graphRouteBar(wire: GraphWireView, x: number, y: number): HTMLElement {
  const bar = graphElement("div", "graph-route-bar");
  bar.style.left = `${x}px`;
  bar.style.top = `${y}px`;
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "How this wire is drawn");
  for (const [name, label] of [["curve", "Curve"], ["straight", "Straight"], ["square", "Square"], ["astar", "Around boxes"]]) {
    const button = graphElement("button", "graph-route", label);
    button.setAttribute("type", "button");
    button.setAttribute("aria-pressed", String(wire.route === name));
    button.dataset["route"] = wire.id;
    button.dataset["routeTo"] = name ?? "curve";
    bar.appendChild(button);
  }
  return bar;
}
