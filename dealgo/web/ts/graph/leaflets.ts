// Pamphlets and their leaflets: laying a page out on the canvas.
//
// A leaflet is a piece, slotted under a Pamphlet box, but it hangs from
// either of two edges: below another, which is the next thing down that
// column, or beside another, which is the next column to its right. So the
// leaflets under a pamphlet are a tree rather than a chain, drawn the way the
// page will be laid out.
//
// Part of the Configuration canvas; see main.ts.

/** One thing a leaflet's panel offers to choose from. */
interface GraphChoice {
  name: string;
  label: string;
}

/** What a leaflet shows, and what its panel offers. */
interface GraphLeaflet {
  /** Its settings, as the server keeps them: strings, numbers, or null. */
  settings: Record<string, string | number | null>;
  feeds: { id: number; title: string }[];
  charts: GraphChoice[];
  goes: GraphChoice[];
}

/** A Pamphlet box: where its page is, and whether the tab opens on it. */
interface GraphPamphlet {
  url: string;
  default: boolean;
}

/** Whether this kind is a leaflet. */
function graphIsLeaflet(kind: GraphNodeKind): boolean {
  return (
    kind === "leaflet-feed" || kind === "leaflet-chart" ||
    kind === "leaflet-text" || kind === "leaflet-link"
  );
}

function asGraphChoices(value: unknown): GraphChoice[] {
  if (!Array.isArray(value)) return [];
  const found: GraphChoice[] = [];
  for (const entry of value) {
    const raw = asGraphRecord(entry);
    if (raw === null || typeof raw["name"] !== "string") continue;
    found.push({
      name: raw["name"],
      label: typeof raw["label"] === "string" ? raw["label"] : raw["name"],
    });
  }
  return found;
}

function asGraphLeaflet(value: unknown): GraphLeaflet | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const settings: Record<string, string | number | null> = {};
  const given = asGraphRecord(raw["settings"]);
  if (given !== null) {
    for (const [key, one] of Object.entries(given)) {
      if (typeof one === "string" || typeof one === "number" || one === null) settings[key] = one;
    }
  }
  const feeds: { id: number; title: string }[] = [];
  if (Array.isArray(raw["feeds"])) {
    for (const entry of raw["feeds"]) {
      const feed = asGraphRecord(entry);
      if (feed === null || typeof feed["id"] !== "number") continue;
      feeds.push({ id: feed["id"], title: typeof feed["title"] === "string" ? feed["title"] : "" });
    }
  }
  return {
    settings,
    feeds,
    charts: asGraphChoices(raw["charts"]),
    goes: asGraphChoices(raw["goes"]),
  };
}

function asGraphPamphlet(value: unknown): GraphPamphlet | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  return {
    url: typeof raw["url"] === "string" ? raw["url"] : "",
    default: raw["default"] === true,
  };
}

/** Every leaflet that hangs from something, by what and which edge: one per edge. */
function graphHanging(state: GraphState): Map<string, GraphNodeView> {
  const hanging = new Map<string, GraphNodeView>();
  const leaflets = state.nodes
    .filter((node): boolean => graphIsLeaflet(node.kind) && node.piece?.under != null)
    .sort((a, b): number => a.id - b.id);
  for (const node of leaflets) {
    const piece = node.piece;
    if (piece === null || piece.under === null) continue;
    const key = `${piece.under}:${piece.side}`;
    if (!hanging.has(key)) hanging.set(key, node);
  }
  return hanging;
}

/** The room around and between leaflets inside a Pamphlet box. */
function graphLeafletSpacing(): { pad: number; gap: number } {
  return { pad: 10, gap: 8 };
}

/** Lay out every pamphlet's leaflets inside it, as a small picture of the
 *  page: the box's own title at the top, then its leaflets as cards — a
 *  column under each leaflet, the next column beside it, far enough along to
 *  clear everything below the one before. The box grows to hold them, so a
 *  pamphlet reads as one thing rather than a box with pieces hung off it.
 *  Measured, as every piece is, once they are in the document. */
function placeGraphLeaflets(state: GraphState): void {
  const hanging = graphHanging(state);
  const { pad, gap } = graphLeafletSpacing();
  const at = (id: number, side: string): GraphNodeView | undefined => hanging.get(`${id}:${side}`);
  const width = (node: GraphNodeView): number => state.boxes.get(node.id)?.offsetWidth ?? 0;
  const most = 60; // deeper than any page; a ring built before they were refused

  // Each at its own width first: a leaflet is stretched below to the width
  // of everything under it, and that has to be measured from scratch.
  for (const one of hanging.values()) {
    const box = state.boxes.get(one.id);
    if (box !== undefined) box.style.width = "";
  }

  // A leaflet being dragged follows the pointer, and leaves its place on the
  // page held open until it is let go.
  const held = state.drag?.kind === "move" ? state.drag.nodeId : -1;

  const rowWidth = (first: GraphNodeView | undefined, depth: number): number => {
    let total = 0;
    let walk = first;
    for (let step = 0; walk !== undefined && depth + step < most; step += 1) {
      total += (step > 0 ? gap : 0) + columnWidth(walk, depth + step + 1);
      walk = at(walk.id, "beside");
    }
    return total;
  };
  const columnWidth = (node: GraphNodeView, depth: number): number =>
    depth > most ? 0 : Math.max(width(node), rowWidth(at(node.id, "below"), depth + 1));

  const seen = new Set<number>();
  // Places a row, and answers how far down the page it reached.
  const placeRow = (first: GraphNodeView | undefined, left: number, top: number, depth: number): number => {
    let walk = first;
    let x = left;
    let bottom = top;
    while (walk !== undefined && !seen.has(walk.id) && depth < most) {
      seen.add(walk.id);
      const box = state.boxes.get(walk.id);
      if (box === undefined) break;
      box.dataset["host"] = "pamphlet";
      box.dataset["side"] = walk.piece?.side ?? "below";
      const below = at(walk.id, "below");
      const beside = at(walk.id, "beside");
      // The free edges show a notch, as the bottom of a stack of pieces does.
      box.classList.toggle("has-below", below !== undefined);
      box.classList.toggle("has-beside", beside !== undefined);
      // As wide as its column, as it is on the page: a heading over two
      // columns spans both.
      const across = columnWidth(walk, depth + 1);
      if (walk.id !== held) {
        box.style.width = `${across}px`;
        box.style.left = `${x}px`;
        box.style.top = `${top}px`;
        walk.x = x;
        walk.y = top;
      }
      let reached = top + box.offsetHeight;
      if (below !== undefined) reached = placeRow(below, x, reached + gap, depth + 1);
      bottom = Math.max(bottom, reached);
      x += across + gap;
      walk = beside;
    }
    return bottom;
  };

  for (const node of state.nodes) {
    if (node.kind !== "pamphlet") continue;
    const box = state.boxes.get(node.id);
    if (box === undefined) continue;
    // Its own size first, with nothing in it, to know where the page starts.
    box.style.width = "";
    box.style.height = "";
    const first = at(node.id, "below");
    box.classList.toggle("has-piece", first !== undefined);
    if (first === undefined) continue;
    const inset = box.offsetWidth - box.clientWidth - 1; // the coloured bar down its left
    const top = node.y + box.offsetHeight;
    const bottom = placeRow(first, node.x + inset + pad, top, 0);
    box.style.width = `${Math.max(box.offsetWidth, inset + pad * 2 + rowWidth(first, 0))}px`;
    box.style.height = `${bottom - node.y + pad}px`;
  }
}

/** Every empty edge a leaflet could be dropped on: below a pamphlet with
 *  nothing under it yet, and below or beside any leaflet already on one. */
function graphLeafletSlots(state: GraphState, moving = -1): GraphSlot[] {
  const hanging = graphHanging(state);
  const { gap } = graphLeafletSpacing();
  const found: GraphSlot[] = [];
  // Every edge is somewhere to put one — an edge with a leaflet on it
  // already takes it in between. Moving one already on a page, its own
  // edges and the one it hangs from now are not anywhere new.
  const mover = state.nodes.find((one): boolean => one.id === moving);
  const from = mover?.piece ?? null;
  for (const node of state.nodes) {
    const box = state.boxes.get(node.id);
    if (box === undefined || node.id === moving) continue;
    const onPage = node.kind === "pamphlet" || (graphIsLeaflet(node.kind) && node.piece?.under != null);
    if (!onPage) continue;
    const sides: ("below" | "beside")[] = node.kind === "pamphlet" ? ["below"] : ["below", "beside"];
    for (const side of sides) {
      const taken = hanging.get(`${node.id}:${side}`);
      if (taken?.id === moving) continue;
      if (from !== null && from.under === node.id && from.side === side) continue;
      const between = taken !== undefined;
      if (side === "below" && node.kind === "pamphlet") {
        // A frame grows to hold its page, so its own bottom edge is under
        // everything: the slot is above its first leaflet, under its title.
        const first = taken !== undefined ? state.boxes.get(taken.id) : undefined;
        found.push(
          taken !== undefined && first !== undefined
            ? {
              under: node.id, side, between,
              x: taken.x, y: taken.y - gap / 2, width: first.offsetWidth, height: 0,
            }
            : {
              under: node.id, side, between,
              x: node.x, y: node.y + box.offsetHeight, width: box.offsetWidth, height: 0,
            },
        );
        continue;
      }
      found.push(
        side === "below"
          ? {
            under: node.id, side, between,
            x: node.x,
            y: node.y + box.offsetHeight + gap / 2,
            width: box.offsetWidth, height: 0,
          }
          : {
            under: node.id, side, between,
            x: node.x + box.offsetWidth + gap / 2, y: node.y,
            width: 0, height: box.offsetHeight,
          },
      );
    }
    // The first leaflet of a row has a left edge too: dropped there, a
    // leaflet goes in front of it, and it moves along.
    const first = node.piece?.side === "below" && graphIsLeaflet(node.kind);
    if (first && node.piece?.under != null) {
      found.push({
        under: node.id, side: "before", between: true,
        x: node.x - gap / 2, y: node.y, width: 0, height: box.offsetHeight,
      });
    }
  }
  return found;
}

/** A leaflet's own parts: the port a feed is wired into, for the leaflets
 *  that show one, and the notches on its two free edges. */
function drawGraphLeafletParts(box: HTMLElement, node: GraphNodeView): void {
  if (node.kind === "leaflet-feed" || node.kind === "leaflet-link") {
    box.appendChild(graphPort("in", "page", "Takes a feed: wire a Feed box here to show what it holds."));
  }
  box.appendChild(graphElement("span", "leaflet-notch is-below"));
  box.appendChild(graphElement("span", "leaflet-notch is-beside"));
}

/** A Pamphlet box's panel: where its page is. Its name is the page's title. */
function graphPamphletFields(form: HTMLElement, node: GraphNodeView): void {
  form.appendChild(
    graphElement(
      "p",
      "hint",
      "Slot leaflets under this box to lay out its page: below one another for a column, beside one another for columns side by side.",
    ),
  );
  if (node.pamphlet?.default === true) {
    form.appendChild(graphElement("p", "hint", "The Pamphlets tab opens on this one."));
  }
}

/** A select of choices, with one picked. */
function graphLeafletSelect(
  name: string, choices: GraphChoice[], picked: string, none = "",
): HTMLSelectElement {
  const select = document.createElement("select");
  select.name = name;
  const all = none === "" ? choices : [{ name: "", label: none }, ...choices];
  for (const choice of all) {
    const option = document.createElement("option");
    option.value = choice.name;
    option.textContent = choice.label;
    option.selected = choice.name === picked;
    select.appendChild(option);
  }
  return select;
}

function graphLeafletText(name: string, value: string, placeholder = ""): HTMLInputElement {
  const field = document.createElement("input");
  field.type = "text";
  field.name = name;
  field.value = value;
  field.placeholder = placeholder;
  return field;
}

function graphLeafletNumber(name: string, value: string, least: number, most: number): HTMLInputElement {
  const field = document.createElement("input");
  field.type = "number";
  field.name = name;
  field.value = value;
  field.min = String(least);
  field.max = String(most);
  return field;
}

/** A leaflet's panel: what this block of the page shows. */
function graphLeafletFields(form: HTMLElement, node: GraphNodeView): void {
  const leaflet = node.leaflet;
  if (leaflet === null) return;
  if (node.piece?.under == null) {
    form.appendChild(
      graphElement("p", "hint", "Loose on the canvas. Drop it under a Pamphlet box, or below or beside another leaflet."),
    );
  }
  const said = (key: string): string => {
    const value = leaflet.settings[key];
    return value === null || value === undefined ? "" : String(value);
  };
  const feeds: GraphChoice[] = leaflet.feeds.map(
    (feed): GraphChoice => ({ name: String(feed.id), label: feed.title }),
  );

  // Which feed is said by the wire into it, not picked here.
  const wiredFeed = feeds.find((one): boolean => one.name === said("feed"))?.label ?? "";
  const fromWire = (): void => {
    form.appendChild(
      graphElement(
        "p",
        "hint",
        wiredFeed !== ""
          ? `Shows “${wiredFeed}”, wired in from its Feed box. Wire another feed in to change it.`
          : "Wire a Feed box's page port (the sheet on its right) into this leaflet to say which feed.",
      ),
    );
  };

  if (node.kind === "leaflet-feed") {
    fromWire();
    form.appendChild(graphLabelled("How many", graphLeafletNumber("leaflet_count", said("count"), 1, 60)));
    form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "the feed's name")));
  } else if (node.kind === "leaflet-chart") {
    form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
    form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
    form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows")));
    form.appendChild(graphElement("p", "hint", "Days count for the day-by-day charts only."));
  } else if (node.kind === "leaflet-text") {
    form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_heading", said("heading"))));
    const body = document.createElement("textarea");
    body.name = "leaflet_body";
    body.rows = 5;
    body.value = said("body");
    form.appendChild(graphLabelled("Words", body));
    form.appendChild(graphElement("p", "hint", "A blank line starts a new paragraph."));
  } else if (node.kind === "leaflet-link") {
    form.appendChild(graphLabelled("Goes to", graphLeafletSelect("leaflet_goes", leaflet.goes, said("goes"))));
    fromWire();
    form.appendChild(graphLabelled("Address", graphLeafletText("leaflet_url", said("url"), "https://")));
    form.appendChild(graphLabelled("Says", graphLeafletText("leaflet_label", said("label"), "worked out from where it goes")));
    form.appendChild(graphElement("p", "hint", "Focus with no feed wired in goes through everything."));
  }
}

/** Where the part of a page wire inside its pamphlet is drawn: among the
 *  boxes, over the pamphlet's frame and under its leaflets. Made once. */
function graphPageWireLayer(state: GraphState): SVGSVGElement {
  const found = state.parts.layer.querySelector<SVGSVGElement>(":scope > .graph-page-wires");
  if (found !== null) return found;
  const made = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  made.setAttribute("class", "graph-page-wires");
  made.setAttribute("aria-hidden", "true");
  state.parts.layer.appendChild(made);
  return made;
}

/** A wire into a leaflet runs under every box, as every wire does — so the
 *  last of it, across its own pamphlet's frame, is drawn again over the
 *  frame, clipped to it, so the frame does not hide where it goes in. */
function drawGraphWireIntoPage(
  state: GraphState, over: SVGSVGElement, wire: GraphWireView, d: string, classes: string,
): void {
  let walk = state.nodes.find((one): boolean => one.id === wire.to);
  for (let depth = 0; walk !== undefined && walk.kind !== "pamphlet" && depth < 60; depth += 1) {
    const above: number | null | undefined = walk.piece?.under;
    walk = above == null ? undefined : state.nodes.find((one): boolean => one.id === above);
  }
  if (walk === undefined) return;
  const frame = state.boxes.get(walk.id);
  if (frame === undefined) return;

  const svg = "http://www.w3.org/2000/svg";
  const clip = document.createElementNS(svg, "clipPath");
  const named = `graph-page-clip-${wire.id.replace(/[^a-z0-9-]/gi, "-")}`;
  clip.setAttribute("id", named);
  const rect = document.createElementNS(svg, "rect");
  rect.setAttribute("x", String(walk.x));
  rect.setAttribute("y", String(walk.y));
  rect.setAttribute("width", String(frame.offsetWidth));
  rect.setAttribute("height", String(frame.offsetHeight));
  clip.appendChild(rect);
  over.appendChild(clip);

  const line = graphSvgPath(classes, d);
  line.setAttribute("clip-path", `url(#${named})`);
  over.appendChild(line);
}
