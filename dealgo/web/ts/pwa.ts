// Install the service worker, and keep the page honest about being offline.
//
// The worker makes what has already been loaded readable with no network. It
// cannot make writing work: marking watched, syncing and editing all need the
// server. So the other half of the job is here — say plainly when the network
// is gone, and stop offering the buttons that cannot work without it.
//
// Top-level `function` declarations only, and one entry call at the end: see
// tests/test_scripts.py, which says why and holds every script to it.

/** Registered with the asset version, so a deploy installs a new worker and
 *  retires the old caches. */
function serviceWorkerUrl(): string {
  const marker = document.querySelector<HTMLMetaElement>('meta[name="dealgo-build"]');
  const version = marker?.content ?? "dev";
  return `/sw.js?v=${encodeURIComponent(version)}`;
}

function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  // Registration failing is not worth troubling anyone with: the site works,
  // it simply will not work offline.
  void navigator.serviceWorker.register(serviceWorkerUrl(), { scope: "/" }).catch((): void => {});
}

/** Anything that writes: pointless, and misleading, with no network. */
function networkOnlyControls(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("[data-needs-network]"));
}

function showOfflineState(offline: boolean): void {
  document.body.classList.toggle("is-offline", offline);
  const banner = document.getElementById("offline-banner");
  if (banner) banner.hidden = !offline;
  networkOnlyControls().forEach((control): void => {
    control.disabled = offline;
    if (offline) control.title = "Offline — this needs the server";
  });
}

function watchConnection(): void {
  window.addEventListener("online", (): void => showOfflineState(false));
  window.addEventListener("offline", (): void => showOfflineState(true));
  showOfflineState(!navigator.onLine);
}

/** htmx swaps in new controls, which need the same treatment. */
function watchSwaps(): void {
  document.body.addEventListener("htmx:afterSwap", (): void => {
    showOfflineState(!navigator.onLine);
  });
}

// -- pieces that could not be loaded ---------------------------------------

/** The element htmx was going to replace, if this event names one.
 *
 *  Read defensively rather than trusted: the detail is whatever htmx put
 *  there, and a missing target is not worth an exception on a page that is
 *  already having a bad time. */
function htmxTarget(event: Event): Element | null {
  if (!(event instanceof CustomEvent)) return null;
  const detail: unknown = event.detail;
  if (typeof detail !== "object" || detail === null) return null;
  if (!("target" in detail)) return null;
  const target: unknown = detail.target;
  return target instanceof Element ? target : null;
}

/** Mark a panel that could not refresh, and leave what it is showing alone.
 *
 *  The alternative — letting htmx swap in the error — would replace a panel
 *  full of readable content with nothing. What is on screen is still true, it
 *  is just not current, so it stays and says so. */
function markUnrefreshed(event: Event): void {
  const target = htmxTarget(event);
  if (!target) return;
  event.preventDefault(); // do not swap the failure in
  target.classList.add("is-unrefreshed");
}

function clearUnrefreshed(event: Event): void {
  const target = htmxTarget(event);
  if (target) target.classList.remove("is-unrefreshed");
}

function watchFragments(): void {
  // No network at all, and a request that came back an error: the same thing
  // as far as the panel is concerned.
  document.body.addEventListener("htmx:sendError", markUnrefreshed);
  document.body.addEventListener("htmx:responseError", markUnrefreshed);
  document.body.addEventListener("htmx:afterSwap", clearUnrefreshed);
}

/** A page the service worker served from its cache. Readable, and possibly
 *  out of date, which is worth one line rather than a silent guess. */
function showStoredCopyNotice(): void {
  if (!document.body.dataset["offlineCopy"]) return;
  const notice = document.getElementById("stored-copy-notice");
  if (notice) notice.hidden = false;
}

function initPwa(): void {
  registerServiceWorker();
  watchConnection();
  watchSwaps();
  watchFragments();
  showStoredCopyNotice();
}

initPwa();
