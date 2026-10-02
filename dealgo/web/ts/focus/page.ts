// Finding the page's parts, and the status line under the player.
//
// Part of Focus mode; see main.ts.

/** An element the template always renders. Missing means the template
 *  changed, which is worth saying by name rather than half-wiring the page. */
function focusElement<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Focus mode: #${id} is missing from the page`);
  return found as T;
}

/** An element that is legitimately absent sometimes. */
function optionalFocusElement<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function collectFocusElements(root: HTMLElement): FocusElements {
  return {
    root,
    stage: focusElement("focus-stage"),
    post: focusElement("focus-post"),
    tiles: focusElement("focus-tiles"),
    words: focusElement("focus-words"),
    postUrl: focusElement<HTMLAnchorElement>("focus-post-url"),
    timer: focusElement("focus-timer"),
    timerCount: focusElement("focus-timer-count"),
    timerWord: focusElement("focus-timer-word"),
    timerFill: focusElement("focus-timer-fill"),
    timerToggle: focusElement<HTMLButtonElement>("focus-timer-toggle"),
    title: focusElement("focus-title"),
    channel: focusElement("focus-channel"),
    remaining: focusElement("focus-remaining"),
    status: focusElement("focus-status"),
    list: focusElement("focus-list"),
    count: focusElement("focus-count"),
    reload: focusElement<HTMLAnchorElement>("focus-reload"),
    next: focusElement<HTMLButtonElement>("focus-next"),
    skip: focusElement<HTMLButtonElement>("focus-skip"),
    frame: optionalFocusElement<HTMLIFrameElement>("focus-player"),
  };
}

/** The queue the server rendered into the page, or null if there is none. */
function readFocusQueue(): FocusItem[] {
  const script = document.getElementById("focus-queue");
  if (!script) return [];
  return JSON.parse(script.textContent ?? "[]") as FocusItem[];
}

function setFocusStatus(sitting: FocusSitting, message: string): void {
  sitting.elements.status.textContent = message ? ` · ${message}` : "";
}
