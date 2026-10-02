// What a Filter is doing: what it let through, and what it held and why.
//
// Part of the Configuration canvas; see main.ts.

interface GraphJudged {
  id: number;
  title: string;
  reason: string | null;
  /** What the boxes on this path would leave on it: a tag, how long you get
   *  with it, when it leaves. Empty for anything held back — nothing happens
   *  to something turned away. */
  marks: string[];
}

function asGraphJudged(value: unknown): GraphJudged[] {
  if (!Array.isArray(value)) return [];
  const read: GraphJudged[] = [];
  for (const entry of value) {
    const raw = asGraphRecord(entry);
    if (raw === null || typeof raw["id"] !== "number") continue;
    const reason = raw["reason"];
    read.push({
      id: raw["id"],
      title: typeof raw["title"] === "string" ? raw["title"] : "",
      reason: typeof reason === "string" ? reason : null,
      marks: Array.isArray(raw["marks"])
        ? raw["marks"].filter((one): one is string => typeof one === "string")
        : [],
    });
  }
  return read;
}

/** Open the list of what this filter lets through and what it holds back. */
async function showGraphFiltered(state: GraphState, nodeId: string): Promise<void> {
  try {
    const answer = await askGraph(`/graph/nodes/${nodeId}/filtered`, null);
    const raw = asGraphRecord(answer);
    if (raw === null) {
      showGraphError(state, asGraphError(answer) ?? "That filter could not be read.");
      return;
    }
    showGraphError(state, null);
    const node = state.nodes.find((entry): boolean => entry.id === Number(nodeId));
    drawGraphFiltered(
      state,
      node?.title ?? "What it catches",
      asGraphJudged(raw["through"]),
      asGraphJudged(raw["held"]),
    );
  } catch {
    showGraphError(state, "No connection, so there is nothing to show.");
  }
}

function drawGraphFiltered(
  state: GraphState,
  name: string,
  through: GraphJudged[],
  held: GraphJudged[],
): void {
  const dialog = graphCatchDialog(state);
  const body = state.parts.canvas
    .closest<HTMLElement>(".graph-panel")
    ?.querySelector<HTMLElement>("[data-graph-catch-body]");
  if (dialog === null || !body) return;

  const title = dialog.querySelector<HTMLElement>("[data-graph-catch-name]");
  if (title !== null) title.textContent = name;

  body.textContent = "";
  body.appendChild(graphJudgedList("Pass", through, "through"));
  body.appendChild(graphJudgedList("Failed", held, "held"));
  openGraphCatch(dialog);
}

function graphCatchDialog(state: GraphState): HTMLDialogElement | null {
  return (
    state.parts.canvas
      .closest<HTMLElement>(".graph-panel")
      ?.querySelector<HTMLDialogElement>("[data-graph-catch]") ?? null
  );
}

/** Open it as a modal where the browser supports one, and plainly where not. */
/** Ask before taking something away, and wait for the answer.
 *
 *  Not `window.confirm`. A browser that has been told to stop this page making
 *  dialogs — the "prevent this page from creating additional dialogs" tick,
 *  which appears after a few in a row — answers confirm() with "no" and says
 *  nothing about it. The Remove button then did nothing at all: no question,
 *  no request, no error, for the rest of the tab's life. Everything else in
 *  the panel kept working, because nothing else asked first.
 *
 *  Falls back to `confirm` only when the dialog is not on the page, which is
 *  the same courtesy the backfill box gets. */
function askGraphSure(state: GraphState, question: string): Promise<boolean> {
  const dialog = graphSureDialog(state);
  if (dialog === null) return Promise.resolve(window.confirm(question));

  const said = dialog.querySelector<HTMLElement>("[data-graph-sure-what]");
  if (said !== null) said.textContent = question;

  return new Promise<boolean>((answer): void => {
    let done = false;
    const finish = (yes: boolean): void => {
      if (done) return;
      done = true;
      dialog.removeEventListener("close", onClose);
      shutGraphSure(dialog);
      answer(yes);
    };
    function onClose(): void {
      finish(false);
    }
    dialog.addEventListener("close", onClose);
    dialog.querySelectorAll<HTMLElement>("[data-graph-sure-yes]").forEach((yes): void => {
      yes.onclick = (): void => finish(true);
    });
    dialog.querySelectorAll<HTMLElement>("[data-graph-sure-no]").forEach((no): void => {
      no.onclick = (): void => finish(false);
    });
    openGraphCatch(dialog);
  });
}

function graphSureDialog(state: GraphState): HTMLDialogElement | null {
  return (
    state.parts.canvas
      .closest(".graph-panel")
      ?.querySelector<HTMLDialogElement>("[data-graph-sure]") ?? null
  );
}

function shutGraphSure(dialog: HTMLDialogElement): void {
  if (dialog.open) {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }
  holdPageForGraph(false);
}

function openGraphCatch(dialog: HTMLDialogElement): void {
  if (dialog.open) return;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  holdPageForGraph(true);
}

/** Stop the page scrolling away behind whatever is open over it.
 *
 *  A modal makes the page inert, which stops it being clicked but not
 *  necessarily scrolled — and the fallback path, where showModal is missing,
 *  makes it neither. The same class the tab drawer uses. */
function holdPageForGraph(held: boolean): void {
  document.body.classList.toggle("page-held", held);
}

/** One side of a report: what got through, or what did not.
 *
 *  Numbered where the order means something — a trial is the batch in the
 *  order it would arrive, and on a sort box that order is the whole answer.
 *  Left unnumbered where it does not, so a number is never implying one. */
function graphJudgedList(
  name: string,
  items: GraphJudged[],
  side: "through" | "held",
  numbered = false,
): HTMLElement {
  const part = graphElement("div", `graph-sheet-part is-${side}`);
  part.appendChild(graphElement("h4", "graph-sheet-name", `${name} (${items.length})`));
  if (items.length === 0) {
    part.appendChild(graphElement("p", "hint", "Nothing."));
    return part;
  }

  const list = graphElement(
    numbered ? "ol" : "ul",
    numbered ? "graph-sheet-list is-numbered" : "graph-sheet-list",
  );
  for (const item of items) {
    const row = graphElement("li", "graph-sheet-row");
    row.appendChild(graphElement("span", "graph-sheet-title", item.title));
    // Only the held-back side has a reason to give; only the side that got
    // through has anything left on it.
    if (side === "held" && item.reason !== null) {
      row.appendChild(graphElement("span", "graph-sheet-reason", item.reason));
    }
    if (item.marks.length > 0) {
      const marks = graphElement("span", "graph-sheet-marks");
      for (const said of item.marks) {
        marks.appendChild(graphElement("span", "graph-sheet-mark", said));
      }
      row.appendChild(marks);
    }
    list.appendChild(row);
  }
  part.appendChild(list);
  return part;
}
