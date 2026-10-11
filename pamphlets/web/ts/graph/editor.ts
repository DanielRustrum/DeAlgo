// The box editor: what came in, the box's settings, what it gives out.
//
// Opened by double-clicking a box, or from its panel. On a data box —
// Transform, Format, Text, a Chart leaflet — it has three panes, the way a
// flow tool lays a node out: input on the left, settings in the middle,
// output on the right, the output worked out again as the settings change,
// before anything is saved. On a source, an operation, a repository or a
// feed it has the two outer panes only: those are set in their own panel.
//
// Each side shows as the fields it has, as a table or as JSON. A field can
// be dragged into a setting, or pressed to go into the setting last used.
//
// Part of the Configuration canvas; see main.ts.

/** One side of a box, as the server says it. */
interface GraphSide {
  how: string;
  note: string;
  rows: unknown[];
  count: number;
  value: unknown;
  foundAt: string;
  fields: { path: string; type: string; sample: unknown }[];
  empty: boolean;
  /** Format boxes and Chart leaflets: the chart, drawn by the server. */
  html: string;
  error: string;
  /** Text boxes: what it last wrote, when, and why it could not. */
  text: string;
  at: string | null;
}

/** Which editor a kind opens: all three panes, the two sides, or none. */
function graphEditorFor(kind: GraphNodeKind): "settings" | "sides" | null {
  if (kind === "transform" || kind === "format" || kind === "text" || kind === "leaflet-chart") return "settings";
  if (
    kind === "source" || kind === "filter" || kind === "sort" || kind === "tag" ||
    kind === "decay" || kind === "expire" || kind === "deposit" || kind === "withdraw" || kind === "feed"
  ) return "sides";
  return null;
}

function asGraphSide(value: unknown): GraphSide | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const text = (key: string): string => (typeof raw[key] === "string" ? raw[key] : "");
  const fields: GraphSide["fields"] = [];
  if (Array.isArray(raw["fields"])) {
    for (const entry of raw["fields"]) {
      const one = asGraphRecord(entry);
      if (one === null || typeof one["path"] !== "string") continue;
      fields.push({ path: one["path"], type: typeof one["type"] === "string" ? one["type"] : "", sample: one["sample"] });
    }
  }
  return {
    how: text("how"),
    note: text("note"),
    rows: Array.isArray(raw["rows"]) ? raw["rows"] : [],
    count: typeof raw["count"] === "number" ? raw["count"] : 0,
    value: raw["value"] ?? null,
    foundAt: text("found_at"),
    fields,
    empty: raw["empty"] === true,
    html: text("html"),
    error: text("error"),
    text: text("text"),
    at: typeof raw["at"] === "string" ? raw["at"] : null,
  };
}

/** Open the editor on a box. */
function openGraphEditor(state: GraphState, nodeId: number): void {
  const node = state.nodes.find((one): boolean => one.id === nodeId);
  if (node === undefined) return;
  const shape = graphEditorFor(node.kind);
  if (shape === null) return;
  document.querySelectorAll("[data-graph-editor]").forEach((old): void => old.remove());

  const dialog = document.createElement("dialog");
  dialog.className = `modal graph-editor is-${shape}`;
  dialog.dataset["graphEditor"] = String(node.id);

  const head = graphElement("div", "modal-head graph-editor-head");
  const named = graphElement("div", "graph-editor-name");
  named.appendChild(graphElement("span", "graph-pop-kind", graphTriggerLabel(node)));
  named.appendChild(graphElement("h2", "", node.title));
  head.appendChild(named);
  const actions = graphElement("div", "graph-editor-actions");
  const close = graphElement("button", "modal-close", "✕");
  close.setAttribute("type", "button");
  close.setAttribute("aria-label", "Close");
  head.appendChild(actions);
  head.appendChild(close);
  dialog.appendChild(head);

  const body = graphElement("div", "graph-editor-body");
  const input = graphElement("section", "graph-editor-pane is-input");
  const output = graphElement("section", "graph-editor-pane is-output");
  const form = document.createElement("form");
  form.className = "graph-editor-pane is-settings graph-form";
  form.noValidate = true;
  form.addEventListener("submit", (event): void => event.preventDefault());

  // A source is where things start: it has only what it gives out.
  if (node.kind === "source") dialog.classList.add("is-alone");
  else body.appendChild(input);
  if (shape === "settings") {
    graphEditorSettings(form, node);
    body.appendChild(form);
  }
  body.appendChild(output);
  dialog.appendChild(body);

  // Every setting that can take a field: those naming one, and those that
  // are words a field can be written into. A field goes in as
  // {{ path }}, so what is read from the data stands apart from what is not.
  const takers = graphEditorTakers(form);
  const paths = graphEditorPathFields(form);
  let aim: HTMLInputElement | HTMLTextAreaElement | null =
    paths.find((one): boolean => one.name.endsWith("_label")) ?? paths[0] ?? takers[0] ?? null;
  const usePath = (path: string): void => {
    if (aim === null) return;
    graphPutField(aim, path, paths.includes(aim as HTMLInputElement));
    aim.focus();
  };
  for (const field of takers) {
    graphExpressionField(field);
    field.addEventListener("focus", (): void => {
      aim = field;
    });
    field.addEventListener("dragover", (event: Event): void => {
      if (!(event instanceof DragEvent)) return;
      if (event.dataTransfer?.types.includes("text/plain") === true) {
        event.preventDefault();
        field.classList.add("is-dropping");
      }
    });
    field.addEventListener("dragleave", (): void => field.classList.remove("is-dropping"));
    field.addEventListener("drop", (event: Event): void => {
      if (!(event instanceof DragEvent)) return;
      const path = event.dataTransfer?.getData("text/plain") ?? "";
      field.classList.remove("is-dropping");
      if (path === "") return;
      event.preventDefault();
      aim = field;
      field.focus();
      graphPutField(field, path, paths.includes(field as HTMLInputElement));
    });
  }

  const views: { input: string; output: string } = { input: "fields", output: "" };
  let latest: unknown = null;
  const draw = (): void => {
    const raw = asGraphRecord(latest);
    if (raw === null) return;
    const problem = typeof raw["problem"] === "string" ? raw["problem"] : "";
    const inSide = asGraphSide(raw["input"]);
    const outSide = asGraphSide(raw["output"]);
    graphEditorPane(input, "Input", inSide, views, "input", usePath, problem, draw);
    graphEditorPane(output, node.kind === "feed" ? "Holds" : "Output", outSide, views, "output", usePath, "", draw);
    if (node.kind === "feed") output.replaceChildren(graphElement("p", "hint", "A feed is where items end up: nothing goes on from it."));
    graphShowFilled(takers, asGraphRecord(raw["filled"]));
    if (node.kind === "leaflet-chart") {
      const out = asGraphRecord(raw["output"]);
      graphChartTry(form, out?.["suggested"], typeof out?.["guessed"] === "string" ? out["guessed"] : "");
    }
  };

  let asked = 0;
  let timer = 0;
  const ask = (): void => {
    asked += 1;
    const mine = asked;
    input.classList.add("is-busy");
    output.classList.add("is-busy");
    const fetchSides = async (): Promise<void> => {
      let answer: unknown;
      try {
        answer = await askGraph(`/graph/nodes/${node.id}/inspect`, graphFormValues(form));
      } catch {
        answer = { input: null, output: null, problem: "No connection, so it could not be read." };
      }
      if (mine !== asked) return;
      input.classList.remove("is-busy");
      output.classList.remove("is-busy");
      latest = answer;
      draw();
    };
    void fetchSides();
  };
  form.addEventListener("input", (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(ask, 300);
  });
  form.addEventListener("change", (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(ask, 50);
  });

  const shut = (): void => {
    if (dialog.open && typeof dialog.close === "function") dialog.close();
    dialog.remove();
    holdPageForGraph(false);
  };
  close.addEventListener("click", shut);
  dialog.addEventListener("close", (): void => {
    holdPageForGraph(false);
    dialog.remove();
  });

  if (node.kind === "text") {
    const write = graphElement("button", "btn btn-quiet", "Write now");
    write.setAttribute("type", "button");
    write.addEventListener("click", (): void => {
      write.textContent = "Writing…";
      write.setAttribute("disabled", "");
      const writeThenShow = async (): Promise<void> => {
        // Saved first, so it writes with what the editor says.
        await applyGraph(state, `/graph/nodes/${node.id}`, graphFormValues(form));
        await applyGraph(state, `/graph/nodes/${node.id}/write`, new URLSearchParams());
        write.textContent = "Write now";
        write.removeAttribute("disabled");
        ask();
      };
      void writeThenShow();
    });
    actions.appendChild(write);
  }
  if (shape === "settings") {
    const save = graphElement("button", "btn btn-primary", "Save");
    save.setAttribute("type", "button");
    save.addEventListener("click", (): void => {
      const saveThenShut = async (): Promise<void> => {
        const was = graphNodeFormWas(state, node.id);
        if (was !== "") {
          rememberGraphUndo(state, "the change to that box", async (): Promise<void> => {
            await applyGraph(state, `/graph/nodes/${node.id}`, new URLSearchParams(was));
          });
        }
        if (await applyGraph(state, `/graph/nodes/${node.id}`, graphFormValues(form))) shut();
      };
      void saveThenShut();
    });
    actions.appendChild(save);
  } else {
    actions.appendChild(graphElement("span", "hint", "Set it in its panel; this shows what goes through it."));
  }

  document.body.appendChild(dialog);
  openGraphCatch(dialog);
  for (const field of takers) field.dispatchEvent(new Event("input"));
  ask();
}

/** What a box's own panel would send now, for undoing a save made here. */
function graphNodeFormWas(state: GraphState, nodeId: number): string {
  const form = state.parts.layer.querySelector<HTMLFormElement>(`form[data-save="${nodeId}"]`);
  return form?.dataset["was"] ?? "";
}

/** The settings pane: its name, and what its kind is set by. */
function graphEditorSettings(form: HTMLFormElement, node: GraphNodeView): void {
  form.appendChild(graphElement("h3", "graph-editor-title", "Settings"));
  const name = document.createElement("input");
  name.type = "text";
  name.name = "label";
  name.value = node.title;
  form.appendChild(graphLabelled("Name", name));

  if (node.kind === "format") graphFormatFields(form, node, true);
  else if (node.kind === "text") graphTextBoxFields(form, node, true);
  else if (node.kind === "leaflet-chart" && node.leaflet !== null) {
    const leaflet = node.leaflet;
    graphChartEditorFields(form, leaflet, (key: string): string => {
      const value = leaflet.settings[key];
      return value === null || value === undefined ? "" : String(value);
    });
  } else if (node.kind === "transform") {
    form.appendChild(graphElement("p", "hint",
      "What it does is said by the pieces slotted under it on the canvas — Count gives how many came in, as one number. With none, it gives what came in."));
  }
}

/** Every setting a field can be put into: text boxes and longer text. */
function graphEditorTakers(form: HTMLFormElement): (HTMLInputElement | HTMLTextAreaElement)[] {
  return Array.from(form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input[type='text'], textarea"))
    .filter((field): boolean => field.name !== "label");
}

/** Put a field into a setting, written {{ path }}. A setting that only ever
 *  names one field is replaced; words have it written in where the cursor is. */
function graphPutField(field: HTMLInputElement | HTMLTextAreaElement, path: string, whole: boolean): void {
  const written = `{{ ${path} }}`;
  if (whole || field.value.trim() === "") {
    field.value = written;
  } else {
    const start = field.selectionStart ?? field.value.length;
    const end = field.selectionEnd ?? start;
    field.value = field.value.slice(0, start) + written + field.value.slice(end);
    const after = start + written.length;
    field.setSelectionRange(after, after);
  }
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

/** A setting that shows its {{ fields }} marked out from the words around
 *  them: a copy of its text laid under it, with each field highlighted, and
 *  a line beneath saying what it comes to. */
function graphExpressionField(field: HTMLInputElement | HTMLTextAreaElement): void {
  const holder = graphElement("span", `graph-expr${field instanceof HTMLTextAreaElement ? " is-long" : ""}`);
  const under = graphElement("span", "graph-expr-under");
  under.setAttribute("aria-hidden", "true");
  field.replaceWith(holder);
  holder.appendChild(under);
  holder.appendChild(field);
  const result = graphElement("span", "graph-expr-result");
  result.setAttribute("aria-live", "polite");
  holder.after(result);
  const sync = (): void => {
    // Laid exactly under the text: the field's own metrics, read once it is
    // on the page — they differ on a phone.
    if (field.isConnected && under.dataset["fitted"] !== "1") {
      const look = getComputedStyle(field);
      if (look.fontSize !== "") {
        under.style.font = look.font;
        under.style.letterSpacing = look.letterSpacing;
        under.style.padding = look.padding;
        under.style.borderWidth = look.borderWidth;
        under.dataset["fitted"] = "1";
      }
    }
    const parts: Node[] = [];
    let last = 0;
    const fields = /\{\{[^{}]*\}\}/g;
    for (let match = fields.exec(field.value); match !== null; match = fields.exec(field.value)) {
      const at = match.index;
      parts.push(document.createTextNode(field.value.slice(last, at)));
      parts.push(graphElement("mark", "graph-expr-field", match[0]));
      last = at + match[0].length;
    }
    // A trailing space keeps a last empty line its height in a textarea.
    parts.push(document.createTextNode(field.value.slice(last) + " "));
    under.replaceChildren(...parts);
    under.scrollTop = field.scrollTop;
    under.scrollLeft = field.scrollLeft;
    holder.classList.toggle("has-fields", field.value.includes("{{"));
    if (!field.value.includes("{{")) result.textContent = "";
  };
  field.addEventListener("input", sync);
  field.addEventListener("scroll", (): void => {
    under.scrollTop = field.scrollTop;
    under.scrollLeft = field.scrollLeft;
  });
  sync();
}

/** Under each setting with a field in it, what it comes to now. */
function graphShowFilled(takers: (HTMLInputElement | HTMLTextAreaElement)[], filled: Record<string, unknown> | null): void {
  for (const field of takers) {
    const result = field.parentElement?.nextElementSibling;
    if (!(result instanceof HTMLElement) || !result.classList.contains("graph-expr-result")) continue;
    const value = filled?.[field.name];
    result.textContent = typeof value === "string" && field.value.includes("{{")
      ? `= ${value === "" ? "(nothing there)" : value}`
      : "";
  }
}

/** The settings that are paths into a row: where a field can go. */
function graphEditorPathFields(form: HTMLFormElement): HTMLInputElement[] {
  return Array.from(form.querySelectorAll<HTMLInputElement>("input[type='text']")).filter(
    (field): boolean => /^(format|leaflet)_(rows|label|value|series)$/.test(field.name),
  );
}

/** Draw one side: its heading, its count, its views, and the view chosen. */
function graphEditorPane(
  pane: HTMLElement, title: string, side: GraphSide | null,
  views: { input: string; output: string }, which: "input" | "output",
  usePath: (path: string) => void, problem: string, redraw: () => void,
): void {
  const parts: HTMLElement[] = [];
  const head = graphElement("div", "graph-editor-pane-head");
  head.appendChild(graphElement("h3", "graph-editor-title", title));
  if (side !== null && !side.empty && side.how !== "text") {
    const many = side.value !== null && side.rows.length === 0 ? "1 value" : `${side.count} ${side.how === "items" ? "item" : "row"}${side.count === 1 ? "" : "s"}`;
    head.appendChild(graphElement("span", "graph-editor-count", many));
  }

  // The views this side has: a chart first where there is one.
  const offered: [string, string][] = [];
  if (side !== null && side.html !== "") offered.push(["chart", "Chart"]);
  if (side !== null && side.how !== "text" && !side.empty) {
    offered.push(["fields", "Fields"], ["table", "Table"], ["json", "JSON"]);
  }
  const chosen = offered.some(([name]): boolean => name === views[which]) ? views[which] : (offered[0]?.[0] ?? "");
  if (offered.length > 1) {
    const tabs = graphElement("div", "graph-editor-views");
    tabs.setAttribute("role", "tablist");
    for (const [name, label] of offered) {
      const tab = graphElement("button", "graph-editor-view", label);
      tab.setAttribute("type", "button");
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(name === chosen));
      tab.addEventListener("click", (): void => {
        views[which] = name;
        redraw();
      });
      tabs.appendChild(tab);
    }
    head.appendChild(tabs);
  }
  parts.push(head);

  if (problem !== "") parts.push(graphElement("p", "error-note", problem));
  if (side === null) {
    parts.push(graphElement("p", "hint", which === "input" ? "A source is where things start: nothing comes into it." : "Nothing goes out of this."));
  } else {
    if (side.note !== "") parts.push(graphElement("p", "hint", side.note));
    if (side.error !== "") parts.push(graphElement("p", "error-note", side.error));
    if (side.foundAt !== "") parts.push(graphElement("p", "hint", `Rows found at “${side.foundAt}”.`));
    const shown = graphElement("div", "graph-editor-shown");
    if (side.how === "text") graphEditorText(shown, side);
    else if (side.empty) shown.appendChild(graphElement("p", "hint", side.note === "" ? "Nothing yet." : ""));
    else if (chosen === "chart") graphEditorChart(shown, side);
    else if (chosen === "table") graphEditorTable(shown, side, usePath);
    else if (chosen === "json") graphEditorJson(shown, side);
    else graphEditorFieldList(shown, side, usePath);
    parts.push(shown);
  }
  pane.replaceChildren(...parts);
}

/** A field that can be dragged into a setting, or pressed to fill the last one. */
function graphEditorDraggable(element: HTMLElement, path: string, usePath: (path: string) => void): void {
  element.draggable = true;
  element.tabIndex = 0;
  element.title = `Drag “${path}” into a setting, or press to use it`;
  element.addEventListener("dragstart", (event): void => {
    event.dataTransfer?.setData("text/plain", path);
    if (event.dataTransfer !== null) event.dataTransfer.effectAllowed = "copy";
  });
  element.addEventListener("click", (): void => usePath(path));
  element.addEventListener("keydown", (event): void => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      usePath(path);
    }
  });
}

/** Every field the rows have: its path, what kind of thing, an example. */
function graphEditorFieldList(shown: HTMLElement, side: GraphSide, usePath: (path: string) => void): void {
  if (side.fields.length === 0) {
    shown.appendChild(graphElement("p", "graph-editor-value", graphEditorWords(side.value ?? side.rows[0])));
    return;
  }
  const list = graphElement("ul", "graph-editor-fields");
  for (const field of side.fields) {
    const row = graphElement("li", "graph-editor-field");
    row.appendChild(graphElement("span", `graph-editor-type is-${field.type.replace(/[^a-z]/g, "")}`, field.type));
    row.appendChild(graphElement("span", "graph-editor-path", field.path));
    row.appendChild(graphElement("span", "graph-editor-sample", graphEditorWords(field.sample)));
    graphEditorDraggable(row, field.path, usePath);
    list.appendChild(row);
  }
  shown.appendChild(list);
}

/** The rows as a table: a column per field that is not itself a list or object. */
function graphEditorTable(shown: HTMLElement, side: GraphSide, usePath: (path: string) => void): void {
  if (side.rows.length === 0) {
    shown.appendChild(graphElement("p", "graph-editor-value", graphEditorWords(side.value)));
    return;
  }
  const columns = side.fields.filter((one): boolean => one.type !== "object").slice(0, 12).map((one): string => one.path);
  const wrap = graphElement("div", "graph-editor-table");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const top = document.createElement("tr");
  top.appendChild(graphElement("th", "", "#"));
  for (const path of columns) {
    const cell = graphElement("th", "");
    cell.setAttribute("scope", "col");
    const chip = graphElement("span", "graph-editor-path", path);
    graphEditorDraggable(chip, path, usePath);
    cell.appendChild(chip);
    top.appendChild(cell);
  }
  head.appendChild(top);
  table.appendChild(head);
  const rows = document.createElement("tbody");
  side.rows.forEach((row, index): void => {
    const line = document.createElement("tr");
    line.appendChild(graphElement("td", "graph-editor-index", String(index + 1)));
    for (const path of columns) line.appendChild(graphElement("td", "", graphEditorWords(graphWalkPath(row, path))));
    rows.appendChild(line);
  });
  table.appendChild(rows);
  wrap.appendChild(table);
  shown.appendChild(wrap);
  if (side.count > side.rows.length) {
    shown.appendChild(graphElement("p", "hint", `The first ${side.rows.length} of ${side.count}.`));
  }
}

/** The rows, or the one value, as JSON. */
function graphEditorJson(shown: HTMLElement, side: GraphSide): void {
  const value = side.rows.length > 0 ? side.rows : side.value;
  let text = JSON.stringify(value, null, 2);
  if (text.length > 120000) text = text.slice(0, 120000) + "\n…";
  shown.appendChild(graphElement("pre", "graph-editor-json", text));
  if (side.count > side.rows.length && side.rows.length > 0) {
    shown.appendChild(graphElement("p", "hint", `The first ${side.rows.length} of ${side.count}.`));
  }
}

/** The chart, as the server drew it with the same partial the pamphlet uses. */
function graphEditorChart(shown: HTMLElement, side: GraphSide): void {
  const picture = graphElement("div", "graph-editor-picture pamphlet-leaflet");
  // Built from the server's own template, whose output is escaped.
  picture.innerHTML = side.html;
  shown.appendChild(picture);
}

/** What a Text box last wrote. */
function graphEditorText(shown: HTMLElement, side: GraphSide): void {
  if (side.error !== "") return;
  if (side.text === "") {
    shown.appendChild(graphElement("p", "hint", "Nothing written yet. Write now has it write from the input on the left."));
    return;
  }
  const when = side.at !== null ? new Date(side.at).toLocaleString() : "";
  if (when !== "") shown.appendChild(graphElement("p", "hint", `Written ${when}:`));
  shown.appendChild(graphElement("blockquote", "graph-written", side.text));
}

/** One step down a dotted path, the way the server walks it. */
function graphWalkPath(row: unknown, path: string): unknown {
  let here: unknown = row;
  for (const step of path.split(".")) {
    if (Array.isArray(here) && /^\d+$/.test(step)) here = here[Number(step)];
    else {
      const record = asGraphRecord(here);
      if (record === null) return undefined;
      here = record[step];
    }
  }
  return here;
}

/** A value as a short line of text for a cell or an example. */
function graphEditorWords(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "string") return value.length > 120 ? value.slice(0, 119) + "…" : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.length}]`;
  const text = JSON.stringify(value);
  return text.length > 120 ? text.slice(0, 119) + "…" : text;
}
