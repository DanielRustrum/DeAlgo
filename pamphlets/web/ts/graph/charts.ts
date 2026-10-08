// Chart leaflets: what one draws, and how it organises the data wired in.
//
// The organising is done in the box editor (editor.ts), beside the data it
// organises and the chart it makes; the panel says what is drawn and opens
// the editor.
//
// Part of the Configuration canvas; see main.ts.

/** A Chart leaflet's panel: what it draws, and from what. */
function graphChartFields(form: HTMLElement, node: GraphNodeView, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows")));
  form.appendChild(graphLabelled("Draw as", graphLeafletSelect("leaflet_kind", leaflet.kinds, said("kind"))));

  if (leaflet.wired && leaflet.shapedBy) {
    form.appendChild(graphElement("p", "hint",
      "A Format box is wired in, and says which rows, labels and numbers there are. Draw as says how they look."));
  } else if (leaflet.wired) {
    form.appendChild(graphElement("p", "hint", node.note !== "" ? `Shows ${node.note}.` : "Data is wired in."));
  } else {
    form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
    form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
    form.appendChild(graphElement("p", "hint",
      "Days count for the day-by-day charts only. Or wire data in — the { } port — from a source, an operation or a Transform box, and organise that in the editor."));
  }
}

/** A Chart leaflet's settings in the editor: what it is drawn as, and —
 *  with data wired in — where its rows are, what labels a point, what
 *  number it shows and what splits it into series. */
function graphChartEditorFields(form: HTMLElement, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows")));

  // What it is drawn as, as buttons over one field.
  const kind = document.createElement("input");
  kind.type = "hidden";
  kind.name = "leaflet_kind";
  kind.value = said("kind");
  form.appendChild(kind);
  const kinds = graphElement("div", "graph-chart-kinds");
  kinds.setAttribute("role", "radiogroup");
  kinds.setAttribute("aria-label", "Draw as");
  const press = (): void => {
    kinds.querySelectorAll<HTMLElement>("button").forEach((one): void => {
      one.setAttribute("aria-checked", String(one.dataset["kind"] === kind.value));
    });
  };
  for (const choice of leaflet.kinds) {
    const one = graphElement("button", "graph-chart-kind", choice.label);
    one.setAttribute("type", "button");
    one.setAttribute("role", "radio");
    one.dataset["kind"] = choice.name;
    one.addEventListener("click", (): void => {
      kind.value = choice.name;
      press();
      form.dispatchEvent(new Event("change", { bubbles: true }));
    });
    kinds.appendChild(one);
  }
  press();
  form.appendChild(graphLabelled("Draw as", kinds));

  if (leaflet.wired && leaflet.shapedBy) {
    form.appendChild(graphElement("p", "hint",
      "The Format box wired in says which rows, labels and numbers there are: change them there."));
    return;
  }
  if (!leaflet.wired) {
    form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
    form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
    return;
  }

  const step = (title: string, ...rows: HTMLElement[]): void => {
    const set = graphElement("fieldset", "graph-chart-step");
    set.appendChild(graphElement("legend", "", title));
    for (const row of rows) set.appendChild(row);
    form.appendChild(set);
  };
  const path = (name: string, label: string, placeholder: string): HTMLElement =>
    graphLabelled(label, graphLeafletText(`leaflet_${name}`, said(name), placeholder));
  const pick = (name: string, label: string, choices: GraphChoice[]): HTMLElement =>
    graphLabelled(label, graphLeafletSelect(`leaflet_${name}`, choices, said(name)));

  step("Rows", path("rows", "The list", "found by itself — or a path like data.children"));
  step("Points",
    path("label", "Label each by", "drag a field here, like published"),
    pick("group", "Group labels", leaflet.groups));
  step("Numbers",
    pick("combine", "Combine rows", leaflet.combines),
    path("value", "The number", "drag a field here — not needed to count"));
  step("Series", path("series", "Split by", "optional: a field, like author — a line or bar for each"));
  step("Which",
    pick("sort", "Order", leaflet.sorts),
    graphLabelled("How many points", graphLeafletNumber("leaflet_limit", said("limit"), 1, 60)));
}
