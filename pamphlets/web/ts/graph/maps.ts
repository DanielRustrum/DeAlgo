// The Map leaflet: wired rows placed as dots on a map, drawn by the Leaflet
// map library (ts/maps.ts) — which only shares a name with these leaflets.
// Its panel, and its settings in the box editor (editor.ts).
//
// Part of the Configuration canvas; see main.ts.

/** A Map leaflet's panel: what it shows, and that the editor places it. */
function graphMapFields(form: HTMLElement, node: GraphNodeView, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "none")));
  form.appendChild(graphElement("p", "hint", leaflet.wired
    ? `Shows ${node.note !== "" ? node.note : "the data wired in"}. Double-click to change it.`
    : "Wire data in — the { } port — from a source, an operation or a Transform box: a dot for each row with a latitude and a longitude. Or double-click to focus it on a place."));
}

/** A Map leaflet's settings in the editor: where each row is, what its dot
 *  says, and what colours and sizes the dots — said back as one sentence. */
function graphMapEditorFields(form: HTMLElement, nodeId: number, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "none — or words, with {{ fields }}")));
  graphMapFocus(form, nodeId, said);
  if (!leaflet.wired) {
    form.appendChild(graphElement("p", "hint", "Wire data into it — its { } port — to place a dot for each row."));
    return;
  }

  const says = graphElement("p", "graph-chart-says");
  says.setAttribute("aria-live", "polite");
  form.appendChild(says);

  const step = (title: string, ...rows: HTMLElement[]): void => {
    const set = graphElement("fieldset", "graph-chart-step");
    set.appendChild(graphElement("legend", "", title));
    for (const row of rows) set.appendChild(row);
    form.appendChild(set);
  };
  const lat = graphLeafletText("leaflet_lat", said("lat"), "drag the latitude here, like lat");
  const lng = graphLeafletText("leaflet_lng", said("lng"), "drag the longitude here, like lng");
  step("Where each row is", graphLabelled("Latitude", lat), graphLabelled("Longitude", lng));

  const popup = document.createElement("textarea");
  popup.name = "leaflet_popup";
  popup.rows = 2;
  popup.value = said("popup");
  popup.placeholder = "words, with {{ fields }} of the row — like {{ title }}";
  step("Pressed, a dot says", graphLabelled("Words", popup));

  const series = graphLeafletText("leaflet_series", said("series"), "optional — leave empty for one colour");
  step("Colour by (optional)", graphLabelled("Field", series),
    graphElement("p", "hint", "Each value of this field gets its own colour, and a place in the key under the map."));
  const size = graphLeafletText("leaflet_size", said("size"), "optional — a number: bigger is bigger");
  step("Size by (optional)", graphLabelled("Field", size));

  const more = document.createElement("details");
  more.className = "graph-chart-more";
  more.appendChild(graphElement("summary", "", "How many, where the rows are"));
  more.appendChild(graphLabelled("At most", graphLeafletNumber("leaflet_limit", said("limit"), 1, 1000)));
  more.appendChild(graphLabelled("Rows are at", graphLeafletText("leaflet_rows", said("rows"), "found by itself — or a path like data.children")));
  form.appendChild(more);

  const focus = form.querySelector<HTMLInputElement>("input[name='leaflet_focus']");
  const retell = (): void => {
    const strong = (text: string): HTMLElement => graphElement("strong", "", text);
    const plain = (text: string): Node => document.createTextNode(text);
    const guess = says.dataset["guessed"] ?? "";
    const parts: Node[] = [plain("A map: a dot for each row, at ")];
    if (graphChartNamed(lat) === "" && graphChartNamed(lng) === "" && guess !== "") {
      parts.push(strong(guess), plain(" (a guess)"));
    } else {
      parts.push(strong(graphChartNamed(lat) || "…"), plain(" and "), strong(graphChartNamed(lng) || "…"));
    }
    if (graphChartNamed(series) !== "") parts.push(plain(", coloured by "), strong(graphChartNamed(series)));
    if (graphChartNamed(size) !== "") parts.push(plain(", as big as "), strong(graphChartNamed(size)));
    const over = (focus?.value ?? "").split(",")[0] ?? "";
    if (over !== "") parts.push(plain(", over "), strong(over));
    parts.push(plain("."));
    says.replaceChildren(...parts);
  };
  form.addEventListener("input", retell);
  form.addEventListener("change", retell);
  form.addEventListener("graph-chart-guess", retell);
  retell();
}

/** Where a map looks: an area found by its name — a city, a state, a
 *  country, an address — or, with none, wherever its dots are. The name is
 *  looked up only when Find is pressed; what is chosen is kept as its edges. */
function graphMapFocus(form: HTMLElement, nodeId: number, said: (key: string) => string): void {
  const focus = document.createElement("input");
  focus.type = "hidden";
  focus.name = "leaflet_focus";
  focus.value = said("focus");
  const bounds = document.createElement("input");
  bounds.type = "hidden";
  bounds.name = "leaflet_bounds";
  bounds.value = said("bounds");
  form.appendChild(focus);
  form.appendChild(bounds);

  const set = graphElement("fieldset", "graph-chart-step");
  set.appendChild(graphElement("legend", "", "Focus on"));
  const now = graphElement("p", "graph-map-focus");
  const words = document.createElement("input");
  words.type = "search";
  words.placeholder = "a city, a state, a country, an address";
  words.setAttribute("aria-label", "Place to focus on");
  const find = graphElement("button", "btn btn-quiet", "Find");
  find.setAttribute("type", "button");
  const row = graphElement("div", "graph-map-find");
  row.appendChild(words);
  row.appendChild(find);
  const found = graphElement("div", "graph-map-found");
  set.appendChild(now);
  set.appendChild(row);
  set.appendChild(found);
  form.appendChild(set);

  const choose = (name: string, edges: string): void => {
    focus.value = name;
    bounds.value = edges;
    show();
    found.replaceChildren();
    form.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const show = (): void => {
    if (bounds.value === "") {
      now.replaceChildren(document.createTextNode("Wherever its dots are."));
      return;
    }
    const clear = graphElement("button", "graph-map-clear", "Fit the dots instead");
    clear.setAttribute("type", "button");
    clear.addEventListener("click", (): void => choose("", ""));
    now.replaceChildren(graphElement("strong", "", focus.value || "The chosen area"), document.createTextNode(" "), clear);
  };
  const look = async (): Promise<void> => {
    const asked = words.value.trim();
    if (asked === "") return;
    found.replaceChildren(graphElement("p", "hint", "Looking it up…"));
    let answer: unknown;
    try {
      answer = await askGraph(`/graph/nodes/${nodeId}/map/find`, new URLSearchParams({ q: asked }));
    } catch {
      found.replaceChildren(graphElement("p", "error-note", "No connection, so it could not be looked up."));
      return;
    }
    const raw = asGraphRecord(answer);
    if (raw !== null && typeof raw["error"] === "string") {
      found.replaceChildren(graphElement("p", "error-note", raw["error"]));
      return;
    }
    const places = raw !== null && Array.isArray(raw["places"]) ? raw["places"] : [];
    const picks: HTMLElement[] = [];
    for (const entry of places) {
      const place = asGraphRecord(entry);
      if (place === null || typeof place["name"] !== "string" || typeof place["bounds"] !== "string") continue;
      const name = place["name"];
      const edges = place["bounds"];
      const pick = graphElement("button", "graph-map-place");
      pick.setAttribute("type", "button");
      pick.appendChild(graphElement("span", "", name));
      if (typeof place["kind"] === "string" && place["kind"] !== "") pick.appendChild(graphElement("small", "", place["kind"]));
      pick.addEventListener("click", (): void => choose(name, edges));
      picks.push(pick);
    }
    found.replaceChildren(...(picks.length > 0 ? picks : [graphElement("p", "hint", "Nowhere by that name was found.")]));
  };
  find.addEventListener("click", (): void => {
    void look();
  });
  // Enter in the box finds, rather than saving the box's form.
  words.addEventListener("keydown", (event: KeyboardEvent): void => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    void look();
  });
  show();
}
