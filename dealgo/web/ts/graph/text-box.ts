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
function graphTextBoxFields(form: HTMLElement, node: GraphNodeView): void {
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
