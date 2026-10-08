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

/** A Format box's settings: which list, what labels a bar, what it
 *  measures. In the panel, and in the editor — where the fields there are
 *  and the bars it gives are shown beside them. */
function graphFormatFields(form: HTMLElement, node: GraphNodeView, inEditor = false): void {
  const format = node.format;
  if (format === null) return;
  const said = (key: string): string => String(format.settings[key] ?? "");

  if (!inEditor) {
    form.appendChild(
      graphElement(
        "p",
        "hint",
        "Wire a source box into this, and this into a Chart leaflet. Open the editor to see what comes in and the bars it makes.",
      ),
    );
  }
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
}
