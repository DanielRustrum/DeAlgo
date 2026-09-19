// Toasts: the things that are not about the page you are on.
//
// Two sorts, and they behave differently because they mean different things.
//
// A *passing* one reports something that just happened — "Watching r/python",
// "That group could not be loaded". It has been read by the time it is read,
// so it goes on its own after a few seconds.
//
// A *standing* one reports a condition — no Google account, an admin password
// somebody could guess. It is still true after you look away, so it stays
// until dismissed, and dismissing it lasts the browsing session rather than
// for ever: a warning you can permanently silence by accident is a warning
// that will be silenced by accident. Settings has the real off switch.
//
// Structure: top-level `function` declarations and one call at the bottom.
// This is a plain script that htmx re-runs on every boosted navigation, and a
// top-level `const` or `class` would throw "already declared" the second time.

/** How long a passing message stays. Long enough to read twice.
 *
 *  A function rather than a const because htmx re-runs this file on every
 *  boosted navigation, and a top-level binding throws "already declared" the
 *  second time. */
function toastSeconds(): number {
  return 7;
}

/** Where a dismissed standing notice is remembered. Per tab and per session:
 *  it comes back tomorrow, which is what a standing condition deserves. */
function toastMemory(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Private windows and blocked site data both throw on access rather than
    // on use. Without it, dismissing works for this page and no longer.
    return null;
  }
}

function toastWasDismissed(name: string): boolean {
  try {
    return toastMemory()?.getItem(`toast:${name}`) === "gone";
  } catch {
    return false;
  }
}

function rememberToastDismissed(name: string): void {
  try {
    toastMemory()?.setItem(`toast:${name}`, "gone");
  } catch {
    // Nothing to do about it, and nothing worth troubling anybody with.
  }
}

/** Take one off the screen, with the animation if the browser wants one. */
function hideToast(toast: HTMLElement): void {
  toast.classList.add("is-going");
  window.setTimeout((): void => toast.remove(), 200);
}

function giveToastACloseButton(toast: HTMLElement): void {
  if (toast.querySelector(".toast-close") !== null) return;

  const shut = document.createElement("button");
  shut.type = "button";
  shut.className = "toast-close";
  shut.setAttribute("aria-label", "Dismiss");
  shut.textContent = "✕";
  shut.addEventListener("click", (): void => {
    const name = toast.dataset["toast"];
    if (name !== undefined) rememberToastDismissed(name);
    hideToast(toast);
  });
  toast.appendChild(shut);
}

/** Prepare whatever is on screen now. Safe to call again: each toast is only
 *  ever set up once, so an htmx swap that leaves the old ones in place does
 *  not restart their timers. */
function dressToasts(): void {
  const toasts = Array.from(document.querySelectorAll<HTMLElement>(".toast"));
  for (const toast of toasts) {
    if (toast.dataset["toastReady"] === "1") continue;
    toast.dataset["toastReady"] = "1";

    const name = toast.dataset["toast"];
    if (name !== undefined && toastWasDismissed(name)) {
      toast.remove();
      continue;
    }

    giveToastACloseButton(toast);

    // A passing one goes by itself. A standing one waits to be dealt with.
    if (toast.hasAttribute("data-toast-passing")) {
      window.setTimeout((): void => hideToast(toast), toastSeconds() * 1000);
    }
  }
}

/** htmx swaps the flash out of band on almost every action, so new toasts
 *  arrive without a page load. */
function watchForNewToasts(): void {
  document.body.addEventListener("htmx:afterSwap", (): void => dressToasts());
  document.body.addEventListener("htmx:oobAfterSwap", (): void => dressToasts());
}

function initToasts(): void {
  dressToasts();
  watchForNewToasts();
}

initToasts();
