// Chart leaflets: one for each kind of chart — bar, line, pie, radar, polar
// area, scatter, bubble — and the two that show data undrawn, one number and
// a table. What each draws, and how it organises the data wired into it.
//
// The organising is done in the box editor (editor.ts), beside the data it
// organises and the chart it makes; the panel says what is drawn and opens
// the editor. The chart itself is drawn by Chart.js (ts/charts.ts).
//
// Part of the Configuration canvas; see main.ts.

/** How a chart of each kind talks about its parts: what one of them is,
 *  what sets its size, what a series makes, and how it says what it shows. */
function graphChartWords(kind: GraphNodeKind): { each: string; size: string; series: string; says: string; sized: string } {
  if (kind === "leaflet-line") return { each: "Along the bottom, a point for each", size: "Height of the line is", series: "One line for each", says: "A line", sized: "as high as" };
  if (kind === "leaflet-pie") return { each: "One slice for each", size: "Slice size is", series: "", says: "A pie", sized: "as big as" };
  if (kind === "leaflet-polar") return { each: "One wedge for each", size: "How far a wedge reaches is", series: "", says: "Wedges", sized: "reaching as far as" };
  if (kind === "leaflet-radar") return { each: "Round the edge, a spoke for each", size: "How far out is", series: "One shape for each", says: "A radar", sized: "out as far as" };
  if (kind === "leaflet-number") return { each: "", size: "The number is", series: "", says: "One number", sized: "" };
  if (kind === "leaflet-table") return { each: "One row for each", size: "Its value is", series: "One column for each", says: "A table", sized: "showing" };
  return { each: "One bar for each", size: "Bar length is", series: "Split each bar by", says: "Bars", sized: "as long as" };
}

/** What sets a point's size, said the way a person would. */
function graphChartMeasure(combine: string, value: string): string {
  const of = value !== "" ? value : "…";
  if (combine === "count") return "how many rows there are";
  if (combine === "sum") return `the total of ${of}`;
  if (combine === "average") return `the average ${of}`;
  if (combine === "min") return `the smallest ${of}`;
  if (combine === "max") return `the largest ${of}`;
  if (combine === "latest") return `the last ${of} seen`;
  return of;
}

/** The field a setting names: what is between its braces. */
function graphChartNamed(field: HTMLInputElement): string {
  return field.value.replace(/\{\{\s*|\s*\}\}/g, "").trim();
}

/** A chart leaflet's panel: what it shows, and that the editor organises it. */
function graphChartFields(form: HTMLElement, node: GraphNodeView, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows")));
  if (leaflet.wired && leaflet.shapedBy) {
    form.appendChild(graphElement("p", "hint",
      "A Format box is wired in, and says which rows, labels and numbers there are. Double-click for how it is drawn."));
  } else if (leaflet.wired) {
    form.appendChild(graphElement("p", "hint", node.note !== "" ? `Shows ${node.note}. Double-click to change it.` : "Data is wired in."));
  } else if (node.kind === "leaflet-scatter" || node.kind === "leaflet-bubble") {
    form.appendChild(graphElement("p", "hint",
      "Wire data in — the { } port — from a source, an operation or a Transform box: a point for each row."));
  } else {
    form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
    form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
    form.appendChild(graphElement("p", "hint",
      "Days count for the day-by-day charts only. Or wire data in — the { } port — from a source, an operation or a Transform box, and organise that in the editor."));
  }
}

/** A choice of how a chart is drawn, as a row of buttons over one field. */
function graphChartStyle(form: HTMLElement, name: string, choices: GraphChoice[], picked: string): HTMLElement {
  const field = document.createElement("input");
  field.type = "hidden";
  field.name = `leaflet_${name}`;
  field.value = picked !== "" ? picked : (choices[0]?.name ?? "");
  form.appendChild(field);
  const row = graphElement("div", "graph-chart-kinds");
  row.setAttribute("role", "radiogroup");
  const press = (): void => {
    row.querySelectorAll<HTMLElement>("button").forEach((one): void => {
      one.setAttribute("aria-checked", String(one.dataset["choice"] === field.value));
    });
  };
  for (const choice of choices) {
    const one = graphElement("button", "graph-chart-kind", choice.label);
    one.setAttribute("type", "button");
    one.setAttribute("role", "radio");
    one.dataset["choice"] = choice.name;
    one.addEventListener("click", (): void => {
      field.value = choice.name;
      press();
      form.dispatchEvent(new Event("change", { bubbles: true }));
    });
    row.appendChild(one);
  }
  press();
  return row;
}

/** A chart leaflet's settings in the editor, in the chart's own terms:
 *  what each bar (or slice, or point) is, what sets its size, and what
 *  splits it — said back as one sentence, and worded for the chart. */
function graphChartEditorFields(form: HTMLElement, kind: GraphNodeKind, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows — can include {{ fields }}")));

  // How it is drawn: this chart's own choices.
  const names: Record<string, string> = {
    direction: "Bars run", stacking: "Series are", fill: "Drawn as", curve: "Lines are", shape: "Shape",
  };
  for (const style of leaflet.styles) {
    form.appendChild(graphLabelled(names[style.name] ?? style.name, graphChartStyle(form, style.name, style.choices, said(style.name))));
  }

  if (leaflet.wired && leaflet.shapedBy) {
    form.appendChild(graphElement("p", "hint",
      "The Format box wired in says which rows, labels and numbers there are: change them there."));
    return;
  }
  const placed = kind === "leaflet-scatter" || kind === "leaflet-bubble";
  if (!leaflet.wired) {
    if (placed) {
      form.appendChild(graphElement("p", "hint", "Wire data into it — its { } port — to place a point for each row."));
      return;
    }
    form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
    form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
    return;
  }

  // What the chart will show, as a sentence, kept up to date as it is set.
  const says = graphElement("p", "graph-chart-says");
  says.setAttribute("aria-live", "polite");
  form.appendChild(says);

  const step = (title: string, ...rows: HTMLElement[]): void => {
    const set = graphElement("fieldset", "graph-chart-step");
    set.appendChild(graphElement("legend", "", title));
    for (const row of rows) set.appendChild(row);
    form.appendChild(set);
  };
  const more = (title: string, ...rows: HTMLElement[]): void => {
    const folded = document.createElement("details");
    folded.className = "graph-chart-more";
    folded.appendChild(graphElement("summary", "", title));
    for (const row of rows) folded.appendChild(row);
    form.appendChild(folded);
  };
  const strong = (text: string): HTMLElement => graphElement("strong", "", text);
  const plain = (text: string): Node => document.createTextNode(text);
  const series = graphLeafletText("leaflet_series", said("series"), "optional — leave empty for one colour");
  const seriesHint = graphElement("p", "hint", "Each value of this field gets its own colour and a place in the legend.");
  const rows = graphLabelled("Rows are at", graphLeafletText("leaflet_rows", said("rows"), "found by itself — or a path like data.children"));
  const retellOn = (retell: () => void): void => {
    form.addEventListener("input", retell);
    form.addEventListener("change", retell);
    form.addEventListener("graph-chart-guess", retell);
    retell();
  };

  if (placed) {
    // A point for each row, placed by two of its numbers — sized by a third.
    const x = graphLeafletText("leaflet_x", said("x"), "drag a number or a date here");
    const y = graphLeafletText("leaflet_y", said("y"), "drag a number here");
    const size = graphLeafletText("leaflet_size", said("size"), "drag a number here — bigger is bigger");
    step("Along the bottom", graphLabelled("Field", x));
    step("Up the side", graphLabelled("Field", y));
    if (kind === "leaflet-bubble") step("Bubble size", graphLabelled("Field", size));
    step("Colour by (optional)", graphLabelled("Field", series), seriesHint);
    more("How many, where the rows are",
      graphLabelled("At most", graphLeafletNumber("leaflet_limit", said("limit"), 1, 500)), rows);
    retellOn((): void => {
      const guess = says.dataset["guessed"] ?? "";
      const parts: Node[] = [plain(kind === "leaflet-bubble" ? "Bubbles: " : "Dots: ")];
      if (graphChartNamed(x) === "" && graphChartNamed(y) === "" && guess !== "") {
        parts.push(strong(guess), plain(" (a guess)"));
      } else {
        parts.push(plain("one for each row, "), strong(graphChartNamed(x) || "…"), plain(" along and "),
          strong(graphChartNamed(y) || "…"), plain(" up"));
        if (kind === "leaflet-bubble" && graphChartNamed(size) !== "") parts.push(plain(", as big as "), strong(graphChartNamed(size)));
        if (graphChartNamed(series) !== "") parts.push(plain(", coloured by "), strong(graphChartNamed(series)));
      }
      parts.push(plain("."));
      says.replaceChildren(...parts);
    });
    return;
  }

  // Each: what one bar, slice or point is.
  const words = graphChartWords(kind);
  const label = graphLeafletText("leaflet_label", said("label"), "drag a field here, or press one below");
  const group = graphLeafletSelect("leaflet_group", leaflet.groups, said("group"));
  const tryThese = graphElement("div", "graph-chart-try");
  tryThese.dataset["chartTry"] = "1";
  if (words.each !== "") step(words.each, graphLabelled("Field", label), tryThese, graphLabelled("If it is a date, one for each", group));

  // Size: what sets how big each one is.
  const measured: Record<string, string> = {
    count: "How many rows there are", sum: "The total of a field", average: "The average of a field",
    min: "The smallest value of a field", max: "The largest value of a field", latest: "The last value of a field seen",
  };
  const combine = graphLeafletSelect("leaflet_combine", leaflet.combines.map((one): GraphChoice => ({
    name: one.name, label: measured[one.name] ?? one.label,
  })), said("combine"));
  const value = graphLeafletText("leaflet_value", said("value"), "drag a number field here, like views");
  const valueRow = graphLabelled("Of the field", value);
  step(words.size, graphLabelled("Measured by", combine), valueRow);

  // Series: optional, what splits each one.
  if (words.series !== "") step(`${words.series} (optional)`, graphLabelled("Field", series), seriesHint);

  if (words.each !== "") {
    more("Order, how many, where the rows are",
      graphLabelled("Order", graphLeafletSelect("leaflet_sort", leaflet.sorts, said("sort"))),
      graphLabelled("At most", graphLeafletNumber("leaflet_limit", said("limit"), 1, 60)),
      rows);
  } else {
    more("Where the rows are", rows);
  }

  // A date as it is makes a point of every moment: one dropped in is
  // grouped by day, unless a grouping was already chosen.
  label.addEventListener("input", (): void => {
    const dates = (tryThese.dataset["dates"] ?? "").split("\n");
    const named = graphChartNamed(label);
    if (group.value === "none" && named !== "" && dates.includes(named)) {
      group.value = "day";
      group.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  retellOn((): void => {
    valueRow.hidden = combine.value === "count";
    const grouped = group.value !== "none" ? ` (${(group.selectedOptions[0]?.textContent ?? "").toLowerCase()})` : "";
    const measure = graphChartMeasure(combine.value, graphChartNamed(value));
    const parts: Node[] = [plain(`${words.says}: `)];
    if (words.each !== "") {
      const guess = says.dataset["guessed"] ?? "";
      if (graphChartNamed(label) === "" && guess !== "") parts.push(plain("one for each "), strong(guess), plain(" (a guess)"));
      else parts.push(plain("one for each "), strong((graphChartNamed(label) || "…") + grouped));
      parts.push(plain(`, ${words.sized} `), strong(measure));
      if (words.series !== "" && graphChartNamed(series) !== "") parts.push(plain(", split by "), strong(graphChartNamed(series)));
    } else {
      parts.push(strong(measure));
    }
    parts.push(plain("."));
    says.replaceChildren(...parts);
  });
}

/** Fields worth labelling a chart by, from what came in, offered as
 *  buttons under its Field: pressed, one goes in, grouped by day if a date.
 *  And, when nothing is chosen yet, which one the chart has guessed. */
function graphChartTry(form: HTMLElement, suggested: unknown, guessed: string): void {
  const says = form.querySelector<HTMLElement>(".graph-chart-says");
  if (says !== null && says.dataset["guessed"] !== guessed) {
    says.dataset["guessed"] = guessed;
    form.dispatchEvent(new Event("graph-chart-guess"));
  }
  const holder = form.querySelector<HTMLElement>("[data-chart-try]");
  const label = form.querySelector<HTMLInputElement>("input[name='leaflet_label']");
  const group = form.querySelector<HTMLSelectElement>("select[name='leaflet_group']");
  if (holder === null || label === null || group === null || !Array.isArray(suggested)) return;
  const picks: HTMLElement[] = [];
  for (const entry of suggested) {
    const one = asGraphRecord(entry);
    if (one === null || typeof one["path"] !== "string") continue;
    const path = one["path"];
    const by = typeof one["group"] === "string" ? one["group"] : "none";
    const chip = graphElement("button", "graph-tag-choice", typeof one["label"] === "string" ? one["label"] : path);
    chip.setAttribute("type", "button");
    chip.addEventListener("click", (): void => {
      group.value = by;
      graphPutField(label, path, true);
      group.dispatchEvent(new Event("change", { bubbles: true }));
    });
    picks.push(chip);
  }
  holder.dataset["dates"] = suggested
    .map((entry): Record<string, unknown> | null => asGraphRecord(entry))
    .filter((one): boolean => one !== null && one["group"] === "day")
    .map((one): string => String(one?.["path"] ?? ""))
    .join("\n");
  holder.replaceChildren(...(picks.length > 0 ? [graphElement("span", "graph-chart-try-name", "Try:"), ...picks] : []));
}
