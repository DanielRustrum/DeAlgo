// The canvas's dialogs: the run log, reaching back, and loading a group.
//
// Part of the Configuration canvas; see main.ts.

/** The run log, in a box on the canvas rather than a page away from it.
 *
 *  Fetched when it is opened rather than drawn with the page: most visits to
 *  the canvas are not about what the last run did, and a log nobody asked for
 *  should cost nothing. */
function listenForGraphLog(state: GraphState, panel: HTMLElement): void {
  const dialog = panel.querySelector<HTMLDialogElement>("[data-graph-log]");
  const body = dialog?.querySelector<HTMLElement>("[data-graph-log-body]");
  if (dialog === null || !body) return;

  panel.querySelector<HTMLElement>("[data-graph-log-open]")?.addEventListener(
    "click",
    (): void => {
      openGraphCatch(dialog);
      void fillGraphLog(body);
    },
  );
  dialog.querySelectorAll<HTMLElement>("[data-graph-log-close]").forEach((shut): void => {
    shut.addEventListener("click", (): void => dialog.close());
  });
  dialog.addEventListener("click", (event: MouseEvent): void => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", (): void => holdPageForGraph(false));
}

/** Ask for the log and put it in the box.
 *
 *  Through htmx rather than fetch, because what comes back has htmx
 *  attributes of its own — the filter buttons — and htmx swapping it in is
 *  what makes those live without this file knowing anything about them. */
async function fillGraphLog(body: HTMLElement): Promise<void> {
  body.textContent = "";
  body.appendChild(graphElement("p", "empty", "Reading the log…"));

  const htmx = window.htmx;
  if (htmx === undefined) {
    body.textContent = "";
    body.appendChild(graphElement("p", "empty", "The log needs JavaScript to load."));
    return;
  }
  try {
    await htmx.ajax("GET", "/partials/log", { target: "#graph-log-body", swap: "innerHTML" });
  } catch {
    body.textContent = "";
    body.appendChild(graphElement("p", "empty", "The log could not be read just now."));
  }
}

/** Open the box that asks how far back to reach, remembering which trigger
 *  asked. The trigger is kept on the dialog rather than in a variable up here:
 *  this file is re-run on every htmx swap, so nothing may live at the top
 *  level between runs. */
function askHowFarBack(state: GraphState, nodeId: string): void {
  const dialog = graphReachDialog(state);
  if (dialog === null) {
    // No dialog on the page: reach back as far as the feeds go rather than
    // refusing to do the thing that was asked for.
    void fireGraphPulse(state, nodeId, 0);
    return;
  }
  dialog.dataset["forNode"] = nodeId;
  graphReachTrouble(dialog, null);
  openGraphCatch(dialog);
  dialog.querySelector<HTMLInputElement>("[data-graph-reach-count]")?.select();
}

/** The dialog that asks how far back to reach. */
function graphReachDialog(state: GraphState): HTMLDialogElement | null {
  return (
    state.parts.canvas
      .closest(".graph-panel")
      ?.querySelector<HTMLDialogElement>("[data-graph-reach]") ?? null
  );
}

/** Wire the box up once, the way the group-file one is wired. */
function listenForGraphReach(state: GraphState, panel: HTMLElement): void {
  const dialog = panel.querySelector<HTMLDialogElement>("[data-graph-reach]");
  if (dialog === null) return;

  // Closed by its buttons, or by a click on the backdrop.
  dialog.querySelectorAll<HTMLElement>("[data-graph-reach-close]").forEach((shut): void => {
    shut.addEventListener("click", (): void => dialog.close());
  });
  dialog.addEventListener("click", (event: MouseEvent): void => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", (): void => holdPageForGraph(false));

  // Submitted: check the count, then fire the trigger reaching that far back.
  dialog.querySelector<HTMLFormElement>("[data-graph-reach-form]")?.addEventListener(
    "submit",
    (event: SubmitEvent): void => {
      event.preventDefault();
      const field = dialog.querySelector<HTMLInputElement>("[data-graph-reach-count]");
      const wanted = Number.parseInt(field?.value ?? "", 10);
      if (!Number.isFinite(wanted) || wanted < 1) {
        graphReachTrouble(dialog, "Give it a number of posts, one or more.");
        return;
      }
      const nodeId = dialog.dataset["forNode"];
      if (nodeId === undefined) {
        graphReachTrouble(dialog, "That trigger is no longer there.");
        return;
      }
      dialog.close();
      void fireGraphPulse(state, nodeId, wanted);
    },
  );
}

/** Show why reaching back failed, or clear it with null. */
function graphReachTrouble(dialog: HTMLDialogElement, message: string | null): void {
  const said = dialog.querySelector<HTMLElement>("[data-graph-reach-error]");
  if (said === null) return;
  said.textContent = message ?? "";
  said.hidden = message === null;
}

/** The box that asks for a group file, and what it does with one. */
function listenForGraphLoad(state: GraphState, panel: HTMLElement): void {
  const dialog = panel.querySelector<HTMLDialogElement>("[data-graph-load]");
  if (dialog === null) return;

  panel.querySelector<HTMLElement>("[data-graph-load-open]")?.addEventListener(
    "click",
    (): void => {
      graphLoadTrouble(dialog, null);
      openGraphCatch(dialog);
    },
  );
  dialog.querySelectorAll<HTMLElement>("[data-graph-load-close]").forEach((shut): void => {
    shut.addEventListener("click", (): void => dialog.close());
  });
  // A click on the backdrop lands on the dialog itself, not on its contents.
  dialog.addEventListener("click", (event: MouseEvent): void => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("close", (): void => holdPageForGraph(false));

  dialog.querySelector<HTMLFormElement>("[data-graph-load-form]")?.addEventListener(
    "submit",
    (event: SubmitEvent): void => {
      event.preventDefault();
      const picked = dialog.querySelector<HTMLInputElement>("[data-graph-load-file]");
      const file = picked?.files?.[0];
      if (file === undefined) {
        graphLoadTrouble(dialog, "Choose a group file first.");
        return;
      }
      void loadGraphGroup(state, file, dialog);
    },
  );
}

/** Said inside the box rather than behind it, where it would go unread. */
function graphLoadTrouble(dialog: HTMLDialogElement, message: string | null): void {
  const said = dialog.querySelector<HTMLElement>("[data-graph-load-error]");
  if (said === null) return;
  said.textContent = message ?? "";
  said.hidden = message === null;
}

/** Load a group somebody exported, into the middle of the view. */
async function loadGraphGroup(
  state: GraphState,
  file: File,
  dialog: HTMLDialogElement,
): Promise<void> {
  const centre = graphViewCentre(state);
  const body = new FormData();
  body.append("file", file);
  // Dropped around the middle of what is on screen, not on top of whatever is
  // already at the coordinates it was exported from.
  body.append("x", String(Math.round(centre.x - 260)));
  body.append("y", String(Math.round(centre.y - 150)));

  try {
    const response = await fetch("/graph/groups", { method: "POST", body });
    const answer = (await response.json()) as unknown;
    const view = asGraph(answer);
    if (view === null) {
      graphLoadTrouble(dialog, asGraphError(answer) ?? "That group could not be loaded.");
      return;
    }
    state.nodes = view.nodes;
    state.wires = view.wires;
    forgetMissingGraph(state);
    showGraphError(state, null);
    dialog.close();
    renderGraph(state);
  } catch {
    graphLoadTrouble(dialog, "No connection, so nothing was loaded.");
  }
}

/** Bring a loaded group up to date with a newer copy of its file. */
async function updateGraphGroup(state: GraphState, groupId: number, file: File): Promise<void> {
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch(`/graph/nodes/${groupId}/update`, { method: "POST", body });
    const answer = (await response.json()) as unknown;
    const view = asGraph(answer);
    if (view === null) {
      showGraphError(state, asGraphError(answer) ?? "That group could not be updated.");
      return;
    }
    state.nodes = view.nodes;
    state.wires = view.wires;
    forgetMissingGraph(state);
    showGraphError(state, null);
    renderGraph(state);
    const record = asGraphRecord(answer);
    const said = record !== null && typeof record["said"] === "string" ? record["said"] : null;
    showGraphVerdict(state, said);
  } catch {
    showGraphError(state, "No connection, so nothing was updated.");
  }
}

/** Where the middle of the view is, for a box added without being dragged. */
function graphViewCentre(state: GraphState): { x: number; y: number } {
  const frame = state.parts.canvas.getBoundingClientRect();
  return pointInGraph(state, {
    clientX: frame.left + frame.width / 2,
    clientY: frame.top + frame.height / 2,
  });
}
