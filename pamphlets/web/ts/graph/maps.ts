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
    : "Wire data in — the { } port — from a source, an operation or a Transform box: a dot for each row with a latitude and a longitude."));
}

/** A Map leaflet's settings in the editor: where each row is, what its dot
 *  says, and what colours and sizes the dots — said back as one sentence. */
function graphMapEditorFields(form: HTMLElement, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "none — or words, with {{ fields }}")));
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
    parts.push(plain("."));
    says.replaceChildren(...parts);
  };
  form.addEventListener("input", retell);
  form.addEventListener("change", retell);
  form.addEventListener("graph-chart-guess", retell);
  retell();
}
