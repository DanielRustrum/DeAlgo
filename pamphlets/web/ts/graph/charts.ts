// Chart leaflets: organising the data wired into one, and choosing how it
// is drawn — columns, bars, a line, a stacked area, a pie, one number or a
// table.
//
// The organising is done in a dialog rather than the panel: it needs room
// for the fields the data has, and for the chart as it would look. Its
// fields belong to the panel's form (by the form attribute) though they sit
// outside it, so the panel's Save sends them like any other.
//
// Part of the Configuration canvas; see main.ts.

/** A Chart leaflet's panel: what it draws, and from what. */
function graphChartFields(form: HTMLElement, node: GraphNodeView, leaflet: GraphLeaflet, said: (key: string) => string): void {
  form.appendChild(graphLabelled("Heading", graphLeafletText("leaflet_title", said("title"), "what it shows")));
  const kind = graphLeafletSelect("leaflet_kind", leaflet.kinds, said("kind"));
  form.appendChild(graphLabelled("Draw as", kind));

  if (leaflet.wired && leaflet.shapedBy) {
    form.appendChild(graphElement("p", "hint",
      "A Format box is wired in, and says which rows, labels and numbers there are. Draw as says how they look."));
    return;
  }
  if (leaflet.wired) {
    form.appendChild(graphElement("p", "hint", node.note !== "" ? `Shows ${node.note}.` : "Data is wired in."));
    const open = graphElement("button", "btn btn-quiet", "Organize the data…");
    open.setAttribute("type", "button");
    open.addEventListener("click", (): void => {
      openGraphChartDialog(form, node, leaflet, said, kind);
    });
    form.appendChild(open);
    return;
  }
  form.appendChild(graphLabelled("Shows", graphLeafletSelect("leaflet_chart", leaflet.charts, said("chart"))));
  form.appendChild(graphLabelled("Days", graphLeafletNumber("leaflet_days", said("days"), 2, 90)));
  form.appendChild(graphElement("p", "hint",
    "Days count for the day-by-day charts only. Or wire data in — the { } port — from a source, an operation or a Transform box, and organise that instead."));
}

/** The dialog that says how a chart reads the data wired into it, with the
 *  chart as it would look, redrawn as the fields change. */
function openGraphChartDialog(
  form: HTMLElement, node: GraphNodeView, leaflet: GraphLeaflet,
  said: (key: string) => string, kind: HTMLSelectElement,
): void {
  document.querySelectorAll("[data-graph-chart]").forEach((old): void => old.remove());
  if (form.id === "") form.id = `graph-form-${node.id}`;
  const owner = form.id;

  const dialog = document.createElement("dialog");
  dialog.className = "modal graph-chart";
  dialog.dataset["graphChart"] = String(node.id);

  const head = graphElement("div", "modal-head");
  head.appendChild(graphElement("h2", "", "Organize the data"));
  const close = graphElement("button", "modal-close", "✕");
  close.setAttribute("type", "button");
  close.setAttribute("aria-label", "Close");
  head.appendChild(close);
  dialog.appendChild(head);

  const body = graphElement("div", "modal-body graph-chart-body");
  const fields = graphElement("div", "graph-chart-fields");
  const seen = graphElement("div", "graph-chart-seen");
  body.appendChild(fields);
  body.appendChild(seen);
  dialog.appendChild(body);

  // What it is drawn as: the panel's own select, pressed from here.
  const kinds = graphElement("div", "graph-chart-kinds");
  kinds.setAttribute("role", "radiogroup");
  kinds.setAttribute("aria-label", "Draw as");
  const pressKinds = (): void => {
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
      pressKinds();
      redraw();
    });
    kinds.appendChild(one);
  }
  pressKinds();
  fields.appendChild(graphLabelled("Draw as", kinds));

  const paths = new Map<string, HTMLInputElement>();
  const text = (name: string, label: string, placeholder: string): HTMLElement => {
    const field = graphLeafletText(`leaflet_${name}`, said(name), placeholder);
    field.setAttribute("form", owner);
    field.addEventListener("focus", (): void => {
      fields.dataset["aim"] = name;
    });
    paths.set(name, field);
    return graphLabelled(label, field);
  };
  const pick = (name: string, label: string, choices: GraphChoice[]): HTMLElement => {
    const select = graphLeafletSelect(`leaflet_${name}`, choices, said(name));
    select.setAttribute("form", owner);
    return graphLabelled(label, select);
  };
  const step = (title: string, ...rows: HTMLElement[]): void => {
    const set = graphElement("fieldset", "graph-chart-step");
    set.appendChild(graphElement("legend", "", title));
    for (const row of rows) set.appendChild(row);
    fields.appendChild(set);
  };
  step("Rows", text("rows", "The list", "found by itself — or a path like data.children"));
  step("Points",
    text("label", "Label each by", "a path in each row, like published"),
    pick("group", "Group labels", leaflet.groups));
  step("Numbers",
    pick("combine", "Combine rows", leaflet.combines),
    text("value", "The number", "a path, like duration — not needed to count"));
  step("Series",
    text("series", "Split by", "optional: a path, like author — a line or bar for each"));
  const limit = graphLeafletNumber("leaflet_limit", said("limit"), 1, 60);
  limit.setAttribute("form", owner);
  step("Which", pick("sort", "Order", leaflet.sorts), graphLabelled("How many points", limit));
  fields.dataset["aim"] = "label";

  const chips = graphElement("div", "graph-chart-chips");
  fields.appendChild(chips);

  const foot = graphElement("div", "modal-foot");
  const cancel = graphElement("button", "btn btn-quiet", "Cancel");
  cancel.setAttribute("type", "button");
  const save = graphElement("button", "btn btn-primary", "Save");
  save.setAttribute("type", "button");
  foot.appendChild(cancel);
  foot.appendChild(save);
  dialog.appendChild(foot);

  const wasKind = kind.value;
  const shut = (): void => {
    if (dialog.open && typeof dialog.close === "function") dialog.close();
    dialog.remove();
    holdPageForGraph(false);
  };
  close.addEventListener("click", (): void => {
    kind.value = wasKind;
    shut();
  });
  cancel.addEventListener("click", (): void => {
    kind.value = wasKind;
    shut();
  });
  // Esc: as Cancel. What was typed goes with the dialog, so a Save from the
  // panel afterwards leaves the organising as it was.
  dialog.addEventListener("cancel", (): void => {
    kind.value = wasKind;
    holdPageForGraph(false);
    window.setTimeout((): void => dialog.remove(), 0);
  });
  save.addEventListener("click", (): void => {
    const sending = form instanceof HTMLFormElement ? form : null;
    // Submitted while the fields are still on the page, then put away.
    if (sending !== null) sending.requestSubmit();
    shut();
  });

  let timer = 0;
  let asked = 0;
  const redraw = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout((): void => {
      asked += 1;
      void previewGraphChart(node.id, dialog, kind, seen, chips, paths, fields, asked, (): number => asked);
    }, 250);
  };
  dialog.addEventListener("input", redraw);
  dialog.addEventListener("change", redraw);

  document.body.appendChild(dialog);
  openGraphCatch(dialog);
  redraw();
}

/** Draw the chart as the dialog says now, unsaved, and offer the fields
 *  the wired data's rows have. Only the latest answer is shown. */
async function previewGraphChart(
  nodeId: number, dialog: HTMLElement, kind: HTMLSelectElement, seen: HTMLElement,
  chips: HTMLElement, paths: Map<string, HTMLInputElement>, fields: HTMLElement,
  mine: number, latest: () => number,
): Promise<void> {
  const body = new URLSearchParams();
  body.append("leaflet_kind", kind.value);
  dialog.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[name^='leaflet_']").forEach((field): void => {
    body.append(field.name, field.value);
  });
  seen.classList.add("is-busy");
  let answer: unknown;
  try {
    answer = await askGraph(`/graph/nodes/${nodeId}/chart/preview`, body);
  } catch {
    if (mine !== latest()) return;
    seen.classList.remove("is-busy");
    seen.replaceChildren(graphElement("p", "error-note", "No connection, so it could not be drawn."));
    return;
  }
  if (mine !== latest()) return;
  seen.classList.remove("is-busy");
  const raw = asGraphRecord(answer);
  if (raw === null) {
    seen.replaceChildren(graphElement("p", "error-note", "That did not work."));
    return;
  }

  const shown: HTMLElement[] = [];
  const label = typeof raw["label"] === "string" ? raw["label"] : "";
  if (label !== "") shown.push(graphElement("h3", "paper-section", label));
  const picture = graphElement("div", "graph-chart-picture pamphlet-leaflet");
  // The server's own partial, the same the pamphlet sets: what is seen here
  // is what the page will show. Built from escaped template output only.
  picture.innerHTML = typeof raw["html"] === "string" ? raw["html"] : "";
  shown.push(picture);
  const rows = typeof raw["rows"] === "number" ? raw["rows"] : 0;
  const where = typeof raw["rows_path"] === "string" && raw["rows_path"] !== "" ? raw["rows_path"] : "the top";
  if (rows > 0) {
    shown.push(graphElement("p", "hint", `${rows} rows, at “${where}”.`));
    const rowsField = paths.get("rows");
    if (rowsField !== undefined && rowsField.value === "" && where !== "the top") rowsField.placeholder = where;
  }
  seen.replaceChildren(...shown);

  // The fields there are, as chips: pressed, one goes into whichever path
  // field was last in focus — the label to begin with.
  const offered: HTMLElement[] = [];
  if (Array.isArray(raw["fields"]) && raw["fields"].length > 0) {
    offered.push(graphElement("p", "hint", "Fields in its rows — press one to put it in the field you were last in:"));
    const list = graphElement("div", "graph-tag-choices");
    for (const one of raw["fields"]) {
      if (typeof one !== "string") continue;
      const chip = graphElement("button", "graph-tag-choice", one);
      chip.setAttribute("type", "button");
      chip.addEventListener("click", (): void => {
        const aim = paths.get(fields.dataset["aim"] ?? "label") ?? paths.get("label");
        if (aim === undefined) return;
        aim.value = one;
        aim.dispatchEvent(new Event("input", { bubbles: true }));
        aim.focus();
      });
      list.appendChild(chip);
    }
    offered.push(list);
  }
  chips.replaceChildren(...offered);
}
