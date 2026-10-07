// Format boxes: reshaping a source's JSON into bars for a Chart leaflet.
//
// Part of the Configuration canvas; see main.ts.

/** What a Format box is set to, and what its panel offers. */
interface GraphFormat {
  settings: Record<string, string | number>;
  groups: GraphChoice[];
  combines: GraphChoice[];
  sorts: GraphChoice[];
  draws: GraphChoice[];
}

function asGraphFormat(value: unknown): GraphFormat | null {
  const raw = asGraphRecord(value);
  if (raw === null) return null;
  const settings: Record<string, string | number> = {};
  const given = asGraphRecord(raw["settings"]);
  if (given !== null) {
    for (const [key, one] of Object.entries(given)) {
      if (typeof one === "string" || typeof one === "number") settings[key] = one;
    }
  }
  return {
    settings,
    groups: asGraphChoices(raw["groups"]),
    combines: asGraphChoices(raw["combines"]),
    sorts: asGraphChoices(raw["sorts"]),
    draws: asGraphChoices(raw["draws"]),
  };
}

/** A Format box's panel: which list, what labels a bar, what it measures,
 *  and a Try that shows the fields there are and the bars it would give. */
function graphFormatFields(form: HTMLElement, node: GraphNodeView): void {
  const format = node.format;
  if (format === null) return;
  const said = (key: string): string => String(format.settings[key] ?? "");

  form.appendChild(
    graphElement(
      "p",
      "hint",
      "Wire a source box into this, and this into a Chart leaflet. A REST API source gives its last whole answer; any other source gives its items as JSON.",
    ),
  );
  const group = graphElement("div", "graph-format");
  const inputs = new Map<string, HTMLInputElement>();
  const text = (name: string, label: string, placeholder: string): void => {
    const field = graphLeafletText(`format_${name}`, said(name), placeholder);
    inputs.set(name, field);
    group.appendChild(graphLabelled(label, field));
  };
  text("rows", "Rows", "found by itself — or a path like data.children");
  text("label", "Label each bar by", "a path in each row, like published or data.author");
  group.appendChild(graphLabelled("Group it", graphLeafletSelect("format_group", format.groups, said("group"))));
  group.appendChild(graphLabelled("Combine rows", graphLeafletSelect("format_combine", format.combines, said("combine"))));
  text("value", "The number", "a path, like duration — not needed to count");
  group.appendChild(graphLabelled("Order", graphLeafletSelect("format_sort", format.sorts, said("sort"))));
  group.appendChild(graphLabelled("How many bars", graphLeafletNumber("format_limit", said("limit"), 1, 60)));
  group.appendChild(graphLabelled("Draw as", graphLeafletSelect("format_draw", format.draws, said("draw"))));
  form.appendChild(group);
  // Which path field a chip from Try goes into: the one last in focus.
  for (const name of ["label", "value"]) {
    inputs.get(name)?.addEventListener("focus", (): void => {
      group.dataset["aim"] = name;
    });
  }

  const tried = graphElement("div", "graph-format-tried");
  const button = graphElement("button", "btn btn-quiet", "Try");
  button.setAttribute("type", "button");
  button.addEventListener("click", (): void => {
    void tryGraphFormat(node.id, group, inputs, tried);
  });
  form.appendChild(button);
  form.appendChild(tried);
}

/** Ask what the box would make of what is wired into it, unsaved. */
async function tryGraphFormat(
  nodeId: number,
  group: HTMLElement,
  inputs: Map<string, HTMLInputElement>,
  said: HTMLElement,
): Promise<void> {
  const body = new URLSearchParams();
  group.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[name^='format_']").forEach((field): void => {
    body.append(field.name, field.value);
  });
  said.replaceChildren(graphElement("p", "hint", "Reading…"));
  let answer: unknown;
  try {
    answer = await askGraph(`/graph/nodes/${nodeId}/format/try`, body);
  } catch {
    said.replaceChildren(graphElement("p", "error-note", "No connection, so it could not be tried."));
    return;
  }
  const raw = asGraphRecord(answer);
  if (raw === null) {
    said.replaceChildren(graphElement("p", "error-note", "That did not work."));
    return;
  }
  const shown: HTMLElement[] = [];
  const rows = typeof raw["rows"] === "number" ? raw["rows"] : 0;
  const where = typeof raw["rows_path"] === "string" && raw["rows_path"] !== "" ? raw["rows_path"] : "the top";
  if (rows > 0) {
    shown.push(graphElement("p", "hint", `${rows} rows, at “${where}”.`));
    const rowsField = inputs.get("rows");
    if (rowsField !== undefined && rowsField.value === "" && where !== "the top") rowsField.placeholder = where;
  }
  if (Array.isArray(raw["fields"]) && raw["fields"].length > 0) {
    // The fields there are, as chips: pressed, one goes into whichever of
    // the two path fields was last in focus — the label by default.
    const chips = graphElement("div", "graph-tag-choices");
    for (const one of raw["fields"]) {
      if (typeof one !== "string") continue;
      const chip = graphElement("button", "graph-tag-choice", one);
      chip.setAttribute("type", "button");
      chip.addEventListener("click", (): void => {
        const aim = group.dataset["aim"] === "value" ? inputs.get("value") : inputs.get("label");
        if (aim !== undefined) aim.value = one;
      });
      chips.appendChild(chip);
    }
    shown.push(graphElement("p", "hint", "Fields in its rows — press one to use it:"));
    shown.push(chips);
  }
  if (typeof raw["error"] === "string" && raw["error"] !== "") {
    shown.push(graphElement("p", "error-note", raw["error"]));
  }
  if (Array.isArray(raw["bars"]) && raw["bars"].length > 0) {
    const list = graphElement("ol", "graph-rest-items");
    for (const one of raw["bars"]) {
      const bar = asGraphRecord(one);
      if (bar === null) continue;
      const row = graphElement("li", "");
      row.appendChild(graphElement("strong", "", String(bar["label"] ?? "")));
      row.appendChild(graphElement("span", "graph-rest-meta", String(bar["value"] ?? "")));
      list.appendChild(row);
    }
    shown.push(list);
    const more = typeof raw["more"] === "number" ? raw["more"] : 0;
    if (more > 0) shown.push(graphElement("p", "hint", `and ${more} more.`));
  }
  said.replaceChildren(...shown);
}
