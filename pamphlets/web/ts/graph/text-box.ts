// Text boxes: having a language model write from what comes in, for a Text
// leaflet on a pamphlet.
//
// Part of the Configuration canvas; see main.ts.

/** What a Text box is told, and what it last wrote. */
interface GraphWriting {
  settings: Record<string, string | number>;
  refreshes: GraphChoice[];
  /** The start of what it last wrote, for the panel. */
  written: string;
  /** When it last wrote, as ISO; null if never. */
  at: string | null;
  /** Why the last try failed; "" if it did not. */
  error: string;
  /** The model it writes with, named; "" if none is chosen. */
  model: string;
}

function asGraphWriting(value: unknown): GraphWriting | null {
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
    refreshes: asGraphChoices(raw["refreshes"]),
    written: typeof raw["written"] === "string" ? raw["written"] : "",
    at: typeof raw["at"] === "string" ? raw["at"] : null,
    error: typeof raw["error"] === "string" ? raw["error"] : "",
    model: typeof raw["model"] === "string" ? raw["model"] : "",
  };
}

/** A Text box's panel: what to write, how often, and what it last wrote. */
function graphTextBoxFields(form: HTMLElement, node: GraphNodeView, inEditor = false): void {
  const writing = node.writing;
  if (writing === null) return;
  const said = (key: string): string => String(writing.settings[key] ?? "");

  form.appendChild(
    graphElement(
      "p",
      "hint",
      writing.model !== ""
        ? `Writes with ${writing.model}. Wire items (▶) or data ({ }) in, and its sheet port to a Text leaflet.`
        : "No model is chosen yet: choose one under Settings → AI model.",
    ),
  );
  const told = document.createElement("textarea");
  told.name = "writing_instructions";
  told.rows = 5;
  told.value = said("instructions");
  form.appendChild(graphLabelled("What to write", told));
  form.appendChild(graphLabelled("Items it reads", graphLeafletNumber("writing_items", said("items"), 1, 100)));
  form.appendChild(
    graphLabelled("Writes again", graphLeafletSelect("writing_refresh", writing.refreshes, said("refresh"))),
  );
  form.appendChild(
    graphElement("p", "hint", "It reads the first items that come in, up to that many, each cut to its first 600 characters."),
  );

  // In the editor, writing and what was written are on its output side.
  if (inEditor) return;
  const write = graphElement("button", "btn btn-quiet", "Write now");
  write.setAttribute("type", "button");
  write.dataset["write"] = String(node.id);
  form.appendChild(write);

  if (writing.error !== "") form.appendChild(graphElement("p", "error-note", writing.error));
  if (writing.written !== "") {
    const when = writing.at !== null ? new Date(writing.at).toLocaleString() : "";
    form.appendChild(graphElement("p", "hint", `Last written ${when}:`));
    form.appendChild(graphElement("blockquote", "graph-written", writing.written));
  }
}

/** Have a Text box write now. A model takes its time, so it says so. */
async function writeGraphText(state: GraphState, button: HTMLElement, nodeId: string): Promise<void> {
  button.textContent = "Writing…";
  button.setAttribute("disabled", "");
  await applyGraph(state, `/graph/nodes/${nodeId}/write`, new URLSearchParams());
  // The panel is drawn afresh from the answer, with what it wrote or why not.
}

/** An Aggregation piece: which signal, its range, and where the
 *  algorithm is — learned, still learning, or switched off. */
interface GraphAggregation {
  settings: Record<string, string | number>;
  signals: GraphChoice[];
  /** What saturation is measured by: its source, or a tag. */
  of: GraphChoice[];
  state: string;
}

function asGraphAggregation(value: unknown): GraphAggregation | null {
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
    signals: asGraphChoices(raw["signals"]),
    of: asGraphChoices(raw["of"]),
    state: typeof raw["state"] === "string" ? raw["state"] : "",
  };
}

/** An Aggregation piece's panel: what it predicts, and how much is enough. */
function graphAggregationFields(form: HTMLElement, node: GraphNodeView): void {
  const said = node.aggregation;
  if (said === null) return;
  const value = (key: string): string => String(said.settings[key] ?? "");
  const signal = graphLeafletSelect("aggregation_signal", said.signals, value("signal"));
  form.appendChild(graphLabelled("Predicts", signal));
  // Saturation is of a source, or of a tag named here.
  const crowd = graphElement("div", "graph-format");
  const of = graphLeafletSelect("aggregation_of", said.of, value("of"));
  crowd.appendChild(graphLabelled("Saturation of", of));
  const tag = graphLeafletText("aggregation_tag", value("tag"), "news");
  const tagRow = graphLabelled("The tag", tag);
  crowd.appendChild(tagRow);
  crowd.appendChild(graphElement("p", "hint", "How much room this feed has for more like it: what share of what you open is like it, against what share of what waits in the feed is. 100% is plenty."));
  form.appendChild(crowd);
  const show = (): void => {
    crowd.hidden = signal.value !== "saturation";
    tagRow.hidden = of.value !== "tag";
  };
  signal.addEventListener("change", show);
  of.addEventListener("change", show);
  show();
  const range = graphElement("div", "graph-pair");
  range.appendChild(graphLabelled("Minimum, %", graphLeafletNumber("aggregation_least", value("least"), 0, 100)));
  range.appendChild(graphLabelled("Maximum, %", graphLeafletNumber("aggregation_most", value("most"), 0, 100)));
  form.appendChild(range);
  form.appendChild(graphElement("p", "hint", "Within the range counts. A maximum below 100% keeps out what it is too sure of — so your feed is not only ever more of the same."));
  const under = node.piece?.under == null ? "" : node.note;
  form.appendChild(
    graphElement(
      "p",
      "hint",
      node.piece?.under == null
        ? "Loose on the canvas. Drop it on a Filter, a Sort or an Expire box. Under a Filter it holds back what it predicts outside the range; under a Sort it puts the most predicted first, what is in the range ahead of the rest; under an Expire box, what it predicts outside the range leaves sooner."
        : `Under this box: ${under}.`,
    ),
  );
  if (said.state !== "") form.appendChild(graphElement("p", "hint", said.state));
}
