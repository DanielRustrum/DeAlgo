// Putting something back.
//
// Part of the Configuration canvas; see main.ts.

/** How many steps back it can go. Far enough to fix a mistake, not so far
 *  that it becomes a second history of the setup. */
function graphUndoDepth(): number {
  return 40;
}

function rememberGraphUndo(state: GraphState, says: string, run: () => Promise<void>): void {
  state.undo.push({ says, run });
  if (state.undo.length > graphUndoDepth()) state.undo.shift();
}

/** Put the last change back. */
async function undoGraph(state: GraphState): Promise<void> {
  const step = state.undo.pop();
  if (step === undefined) {
    showGraphVerdict(state, "Nothing left to undo.");
    return;
  }
  await step.run();
  showGraphVerdict(state, `Undone: ${step.says}.`);
}

/** Whether a keystroke is the page's to take.
 *
 *  Ctrl+Z inside a text field is that field's own undo, and taking it would
 *  make typing in a node's name unrecoverable. */
function graphTakesTheKey(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return true;
  return target.closest("input, textarea, select") === null;
}

/** The node that is on the canvas now and was not before. */
function graphNodeAdded(before: GraphNodeView[], after: GraphNodeView[]): number | null {
  const had = new Set(before.map((node): number => node.id));
  const fresh = after.filter((node): boolean => !had.has(node.id));
  return fresh.length === 1 ? (fresh[0]?.id ?? null) : null;
}

/** The wire that is on the canvas now and was not before. */
function graphWireAdded(before: GraphWireView[], after: GraphWireView[]): string | null {
  const had = new Set(before.map((wire): string => wire.id));
  const fresh = after.filter((wire): boolean => !had.has(wire.id));
  return fresh.length === 1 ? (fresh[0]?.id ?? null) : null;
}
