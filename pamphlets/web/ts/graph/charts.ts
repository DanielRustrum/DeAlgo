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

/** How a chart of each kind talks about its parts: what one of them is,
 *  what sets its size, and what a series makes. */
function graphChartWords(kind: string): { each: string; size: string; series: string; says: string; sized: string } {
  if (kind === "bar") return { each: "One bar for each", size: "Bar length is", series: "Split each bar by", says: "Bars", sized: "as long as" };
  if (kind === "line") return { each: "Along the bottom, a point for each", size: "Height of the line is", series: "One line for each", says: "A line", sized: "as high as" };
  if (kind === "area") return { each: "Along the bottom, a point for each", size: "Height of each band is", series: "One band for each", says: "Stacked bands", sized: "as high as" };
  if (kind === "pie") return { each: "One slice for each", size: "Slice size is", series: "", says: "A pie", sized: "as big as" };
  if (kind === "number") return { each: "", size: "The number is", series: "", says: "One number", sized: "" };
  if (kind === "table") return { each: "One row for each", size: "Its value is", series: "One column for each", says: "A table", sized: "showing" };
  return { each: "One column for each", size: "Column height is", series: "Split each column by", says: "Columns", sized: "as tall as" };
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

/** A Chart leaflet's settings in the editor, in the chart's own terms:
 *  what each bar (or slice, or point) is, what sets its size, and what
 *  splits it — said back as one sentence, and worded for the chart chosen. */
function graphChartEditorFields(form: HTMLElement, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows — can include {{ fields }}")));

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

  // What the chart will show, as a sentence, kept up to date as it is set.
  const says = graphElement("p", "graph-chart-says");
  says.setAttribute("aria-live", "polite");
  form.appendChild(says);

  const step = (...rows: HTMLElement[]): { set: HTMLElement; legend: HTMLElement } => {
    const set = graphElement("fieldset", "graph-chart-step");
    const legend = graphElement("legend", "");
    set.appendChild(legend);
    for (const row of rows) set.appendChild(row);
    form.appendChild(set);
    return { set, legend };
  };

  // Each: what one bar, slice or point is.
  const label = graphLeafletText("leaflet_label", said("label"), "drag a field here, or press one below");
  const group = graphLeafletSelect("leaflet_group", leaflet.groups, said("group"));
  const tryThese = graphElement("div", "graph-chart-try");
  tryThese.dataset["chartTry"] = "1";
  const each = step(
    graphLabelled("Field", label),
    tryThese,
    graphLabelled("If it is a date, one for each", group),
  );

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
  const size = step(graphLabelled("Measured by", combine), valueRow);

  // Series: optional, what splits each one.
  const series = graphLeafletText("leaflet_series", said("series"), "optional — leave empty for one colour");
  const split = step(graphLabelled("Field", series),
    graphElement("p", "hint", "Each value of this field gets its own colour and a place in the legend."));

  // The rest, which is right as it is more often than not.
  const more = document.createElement("details");
  more.className = "graph-chart-more";
  more.appendChild(graphElement("summary", "", "Order, how many, where the rows are"));
  more.appendChild(graphLabelled("Order", graphLeafletSelect("leaflet_sort", leaflet.sorts, said("sort"))));
  more.appendChild(graphLabelled("At most", graphLeafletNumber("leaflet_limit", said("limit"), 1, 60)));
  more.appendChild(graphLabelled("Rows are at", graphLeafletText("leaflet_rows", said("rows"), "found by itself — or a path like data.children")));
  form.appendChild(more);

  const retitle = (): void => {
    const words = graphChartWords(kind.value);
    each.legend.textContent = words.each;
    each.set.hidden = words.each === "";
    size.legend.textContent = words.size;
    valueRow.hidden = combine.value === "count";
    split.legend.textContent = words.series !== "" ? `${words.series} (optional)` : "";
    split.set.hidden = words.series === "";

    const named = (field: HTMLInputElement): string => field.value.replace(/\{\{\s*|\s*\}\}/g, "").trim();
    const grouped = group.value !== "none" ? ` (${(group.selectedOptions[0]?.textContent ?? "").toLowerCase()})` : "";
    const measure = graphChartMeasure(combine.value, named(value));
    const parts: (string | HTMLElement)[] = [`${words.says}: `];
    if (words.each !== "") {
      // Nothing chosen yet: the chart shows a guess, and the sentence says which.
      const guess = says.dataset["guessed"] ?? "";
      if (named(label) === "" && guess !== "") parts.push("one for each ", graphElement("strong", "", guess), " (a guess)");
      else parts.push("one for each ", graphElement("strong", "", (named(label) || "…") + grouped));
      parts.push(`, ${words.sized} `, graphElement("strong", "", measure));
      if (words.series !== "" && named(series) !== "") parts.push(", split by ", graphElement("strong", "", named(series)));
    } else {
      parts.push(graphElement("strong", "", measure));
    }
    parts.push(".");
    says.replaceChildren(...parts.map((part): Node => (typeof part === "string" ? document.createTextNode(part) : part)));
  };
  form.addEventListener("input", retitle);
  form.addEventListener("change", retitle);
  form.addEventListener("graph-chart-guess", retitle);
  // A date as it is makes a point of every moment: one dropped in is
  // grouped by day, unless a grouping was already chosen.
  label.addEventListener("input", (): void => {
    const dates = (tryThese.dataset["dates"] ?? "").split("\n");
    const named = label.value.replace(/\{\{\s*|\s*\}\}/g, "").trim();
    if (group.value === "none" && named !== "" && dates.includes(named)) {
      group.value = "day";
      group.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  retitle();
}

/** Fields worth labelling a chart by, from what came in, offered as
 *  buttons under its Field: pressed, one goes in, grouped by day if a date. */
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
