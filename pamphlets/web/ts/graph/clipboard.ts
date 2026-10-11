// Copy, cut, paste and delete on the canvas, from the keyboard.
//
// Ctrl+C (⌘C) copies what is picked; Ctrl+V pastes it where the pointer is,
// in whatever canvas is open. Ctrl+X cuts: the boxes fade, and pasting moves
// them there — nothing is taken away until then. Delete or Backspace takes
// away what is picked, asking first where something is at stake.
//
// What was copied or cut is kept in this browser rather than this page, so
// it can be pasted into another canvas, or after leaving the tab.
//
// Part of the Configuration canvas; see main.ts.

/** What is waiting to be pasted: a copy, packed by the server, or the boxes
 *  a cut is waiting to move. */
interface GraphClip {
  mode: "copy" | "cut";
  clip?: unknown;
  ids?: number[];
  count: number;
}

/** Where the clipboard is kept. */
function graphClipKey(): string {
  return "pamphlets-canvas-clip";
}

/** What is waiting to be pasted, if anything is. */
function graphClip(): GraphClip | null {
  let kept: unknown = null;
  try {
    kept = JSON.parse(window.localStorage.getItem(graphClipKey()) ?? "null");
  } catch {
    return null;
  }
  const raw = asGraphRecord(kept);
  if (raw === null || (raw["mode"] !== "copy" && raw["mode"] !== "cut")) return null;
  const ids = Array.isArray(raw["ids"]) ? raw["ids"].filter((one): one is number => typeof one === "number") : [];
  return {
    mode: raw["mode"],
    clip: raw["clip"],
    ids,
    count: typeof raw["count"] === "number" ? raw["count"] : ids.length,
  };
}

function keepGraphClip(clip: GraphClip | null): void {
  try {
    if (clip === null) window.localStorage.removeItem(graphClipKey());
    else window.localStorage.setItem(graphClipKey(), JSON.stringify(clip));
  } catch {
    // Storage refused: nothing can wait to be pasted, then.
  }
}

/** Say something briefly over the canvas. */
function sayGraphBriefly(state: GraphState, words: string): void {
  showGraphVerdict(state, words);
  window.setTimeout((): void => {
    if (state.parts.verdict?.textContent === words) showGraphVerdict(state, null);
  }, 2600);
}

/** "3 boxes", "1 box". */
function graphBoxesWord(count: number): string {
  return `${count} box${count === 1 ? "" : "es"}`;
}

/** The boxes picked now, oldest pick first. */
function graphPickedIds(state: GraphState): number[] {
  return state.nodes.filter((node): boolean => state.picked.has(node.id)).map((node): number => node.id);
}

/** Copy what is picked, to be pasted — here, or in another canvas. */
async function copyGraphPicked(state: GraphState): Promise<void> {
  const ids = graphPickedIds(state);
  if (ids.length === 0) return;
  let answer: unknown;
  try {
    answer = await askGraph("/graph/copy", new URLSearchParams({ nodes: ids.join(",") }));
  } catch {
    showGraphError(state, "No connection, so nothing was copied.");
    return;
  }
  const raw = asGraphRecord(answer);
  if (raw === null || raw["clip"] === undefined) {
    showGraphError(state, asGraphError(answer) ?? "That could not be copied.");
    return;
  }
  const count = typeof raw["count"] === "number" ? raw["count"] : ids.length;
  keepGraphClip({ mode: "copy", clip: raw["clip"], count });
  renderGraph(state);
  renderGraphPickedBar(state);
  sayGraphBriefly(state, `Copied ${graphBoxesWord(count)}. Paste with Ctrl+V.`);
}

/** Cut what is picked: it fades, and moves when it is pasted. */
function cutGraphPicked(state: GraphState): void {
  const ids = graphPickedIds(state).filter((id): boolean => {
    const node = state.nodes.find((one): boolean => one.id === id);
    return node !== undefined && node.piece === null;
  });
  if (ids.length === 0) return;
  keepGraphClip({ mode: "cut", ids, count: ids.length });
  renderGraph(state);
  sayGraphBriefly(state, `Cut ${graphBoxesWord(ids.length)}. Paste with Ctrl+V to move them — here, or in another canvas.`);
}

/** Paste where the pointer is: a copy made again, or a cut moved. */
async function pasteGraph(state: GraphState): Promise<void> {
  const clip = graphClip();
  if (clip === null) return;
  const at = state.pointer ?? graphMiddle(state);
  const body = new URLSearchParams({ x: String(Math.round(at.x)), y: String(Math.round(at.y)) });
  if (clip.mode === "cut") body.set("cut", (clip.ids ?? []).join(","));
  else body.set("clip", JSON.stringify(clip.clip));

  const before = new Set(state.nodes.map((node): number => node.id));
  let answer: unknown;
  try {
    answer = await askGraph("/graph/paste", body);
  } catch {
    showGraphError(state, "No connection, so nothing was pasted.");
    return;
  }
  const view = asGraph(answer);
  if (view === null) {
    showGraphError(state, asGraphError(answer) ?? "That could not be pasted here.");
    return;
  }
  const raw = asGraphRecord(answer);
  const pasted = raw !== null && Array.isArray(raw["pasted"])
    ? raw["pasted"].filter((one): one is number => typeof one === "number")
    : [];
  state.nodes = view.nodes;
  state.wires = view.wires;
  state.trail = view.trail;
  // What landed is what is picked now, ready to be dragged into place.
  state.selectedNode = pasted.length === 1 ? (pasted[0] ?? null) : null;
  state.picked = new Set<number>(pasted);
  state.selectedWire = null;
  if (clip.mode === "cut") {
    // A cut goes once: what it moved is where it was pasted.
    keepGraphClip(null);
  } else {
    const made = pasted.filter((id): boolean => !before.has(id));
    rememberGraphUndo(state, "the paste", async (): Promise<void> => {
      for (const id of made) await applyGraph(state, `/graph/nodes/${id}/delete`, new URLSearchParams());
    });
  }
  showGraphError(state, null);
  renderGraph(state);
}

/** The middle of what is on screen, in the drawing's own coordinates. */
function graphMiddle(state: GraphState): { x: number; y: number } {
  const frame = state.parts.canvas.getBoundingClientRect();
  return pointInGraph(state, { clientX: frame.left + frame.width / 2, clientY: frame.top + frame.height / 2 });
}

/** Fade the boxes a cut is waiting to move. */
function markGraphCut(state: GraphState): void {
  const clip = graphClip();
  const cut = new Set<number>(clip !== null && clip.mode === "cut" ? (clip.ids ?? []) : []);
  for (const [id, box] of state.boxes) box.classList.toggle("is-cut", cut.has(id));
}

/** The keys: copy, cut, paste and delete, whenever the canvas is open and
 *  nothing else — a field being typed in, a dialog, chosen text — has them. */
function onGraphClipboardKey(state: GraphState, event: KeyboardEvent): void {
  if (!state.parts.canvas.isConnected || !graphTakesTheKey(event.target)) return;
  if (document.querySelector("dialog[open]") !== null) return;
  const chosen = window.getSelection?.()?.toString() ?? "";
  const key = event.key.toLowerCase();
  const held = event.ctrlKey || event.metaKey;
  if (held && key === "c" && chosen === "" && state.picked.size > 0) {
    event.preventDefault();
    void copyGraphPicked(state);
  } else if (held && key === "x" && chosen === "" && state.picked.size > 0) {
    event.preventDefault();
    cutGraphPicked(state);
  } else if (held && key === "v" && graphClip() !== null) {
    event.preventDefault();
    void pasteGraph(state);
  } else if (!held && (event.key === "Delete" || event.key === "Backspace") && state.picked.size > 0) {
    event.preventDefault();
    void removeGraphPicked(state, true);
  }
}
