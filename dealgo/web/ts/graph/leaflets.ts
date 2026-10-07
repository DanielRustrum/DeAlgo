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

/** Lay out every pamphlet's leaflets: a column under each leaflet, the next
 *  column beside it — far enough along to clear everything below the one
 *  before, so a column that splits into columns of its own never overlaps
 *  the next. Measured, as every piece is, once they are in the document. */
function placeGraphLeaflets(state: GraphState): void {
  const hanging = graphHanging(state);
  if (hanging.size === 0) return;
  const at = (id: number, side: string): GraphNodeView | undefined => hanging.get(`${id}:${side}`);
  const width = (node: GraphNodeView): number => state.boxes.get(node.id)?.offsetWidth ?? 0;
  const most = 60; // deeper than any page; a ring built before they were refused

  const rowWidth = (first: GraphNodeView | undefined, depth: number): number => {
    let total = 0;
    let walk = first;
    for (let step = 0; walk !== undefined && depth + step < most; step += 1) {
      total += columnWidth(walk, depth + step + 1);
      walk = at(walk.id, "beside");
    }
    return total;
  };
  const columnWidth = (node: GraphNodeView, depth: number): number =>
    depth > most ? 0 : Math.max(width(node), rowWidth(at(node.id, "below"), depth + 1));

  const seen = new Set<number>();
  const placeRow = (first: GraphNodeView | undefined, left: number, top: number, depth: number): void => {
    let walk = first;
    let x = left;
    while (walk !== undefined && !seen.has(walk.id) && depth < most) {
      seen.add(walk.id);
      const box = state.boxes.get(walk.id);
      if (box === undefined) return;
      box.dataset["host"] = "pamphlet";
      box.style.left = `${x}px`;
      box.style.top = `${top}px`;
      walk.x = x;
      walk.y = top;
      const below = at(walk.id, "below");
      const beside = at(walk.id, "beside");
      box.classList.toggle("has-piece", below !== undefined);
      box.classList.toggle("has-beside", beside !== undefined);
      placeRow(below, x, top + box.offsetHeight, depth + 1);
      x += columnWidth(walk, depth + 1);
      walk = beside;
    }
  };

  for (const node of state.nodes) {
    if (node.kind !== "pamphlet") continue;
    const box = state.boxes.get(node.id);
    const first = at(node.id, "below");
    if (box === undefined || first === undefined) continue;
    box.classList.add("has-piece");
    placeRow(first, node.x, node.y + box.offsetHeight, 0);
  }
}

/** Every empty edge a leaflet could be dropped on: below a pamphlet with
 *  nothing under it yet, and below or beside any leaflet already on one. */
function graphLeafletSlots(state: GraphState): GraphSlot[] {
  const hanging = graphHanging(state);
  const found: GraphSlot[] = [];
  for (const node of state.nodes) {
    const box = state.boxes.get(node.id);
    if (box === undefined) continue;
    const onPage = node.kind === "pamphlet" || (graphIsLeaflet(node.kind) && node.piece?.under != null);
    if (!onPage) continue;
    if (!hanging.has(`${node.id}:below`)) {
      found.push({
        under: node.id, side: "below",
        x: node.x, y: node.y + box.offsetHeight, width: box.offsetWidth, height: 0,
      });
    }
    if (node.kind !== "pamphlet" && !hanging.has(`${node.id}:beside`)) {
      found.push({
        under: node.id, side: "beside",
        x: node.x + box.offsetWidth, y: node.y, width: 0, height: box.offsetHeight,
      });
    }
  }
  return found;
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

  if (node.kind === "leaflet-feed") {
    form.appendChild(graphLabelled("Feed", graphLeafletSelect("leaflet_feed", feeds, said("feed"), "Pick a feed")));
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
    form.appendChild(graphLabelled("Feed", graphLeafletSelect("leaflet_feed", feeds, said("feed"), "Everything")));
    form.appendChild(graphLabelled("Address", graphLeafletText("leaflet_url", said("url"), "https://")));
    form.appendChild(graphLabelled("Says", graphLeafletText("leaflet_label", said("label"), "worked out from where it goes")));
    form.appendChild(graphElement("p", "hint", "Focus with no feed picked goes through everything."));
  }
}
