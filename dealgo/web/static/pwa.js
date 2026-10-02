"use strict";
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
function serviceWorkerUrl() {
    var _a;
    const marker = document.querySelector('meta[name="dealgo-build"]');
    const version = (_a = marker === null || marker === void 0 ? void 0 : marker.content) !== null && _a !== void 0 ? _a : "dev";
    return `/sw.js?v=${encodeURIComponent(version)}`;
}
function registerServiceWorker() {
    if (!("serviceWorker" in navigator))
        return;
    // Registration failing is not worth troubling anyone with: the site works,
    // it simply will not work offline.
    void navigator.serviceWorker.register(serviceWorkerUrl(), { scope: "/" }).catch(() => { });
}
/** Anything that writes: pointless, and misleading, with no network. */
function networkOnlyControls() {
    return Array.from(document.querySelectorAll("[data-needs-network]"));
}
function showOfflineState(offline) {
    document.body.classList.toggle("is-offline", offline);
    const banner = document.getElementById("offline-banner");
    if (banner)
        banner.hidden = !offline;
    networkOnlyControls().forEach((control) => {
        control.disabled = offline;
        if (offline)
            control.title = "Offline — this needs the server";
    });
}
function watchConnection() {
    window.addEventListener("online", () => showOfflineState(false));
    window.addEventListener("offline", () => showOfflineState(true));
    showOfflineState(!navigator.onLine);
}
/** htmx swaps in new controls, which need the same treatment. */
function watchSwaps() {
    document.body.addEventListener("htmx:afterSwap", () => {
        showOfflineState(!navigator.onLine);
    });
}
// -- pieces that could not be loaded ---------------------------------------
/** The element htmx was going to replace, if this event names one.
 *
 *  Read defensively rather than trusted: the detail is whatever htmx put
 *  there, and a missing target is not worth an exception on a page that is
 *  already having a bad time. */
function htmxTarget(event) {
    if (!(event instanceof CustomEvent))
        return null;
    const detail = event.detail;
    if (typeof detail !== "object" || detail === null)
        return null;
    if (!("target" in detail))
        return null;
    const target = detail.target;
    return target instanceof Element ? target : null;
}
/** Mark a panel that could not refresh, and leave what it is showing alone.
 *
 *  The alternative — letting htmx swap in the error — would replace a panel
 *  full of readable content with nothing. What is on screen is still true, it
 *  is just not current, so it stays and says so. */
function markUnrefreshed(event) {
    const target = htmxTarget(event);
    if (!target)
        return;
    event.preventDefault(); // do not swap the failure in
    target.classList.add("is-unrefreshed");
}
function clearUnrefreshed(event) {
    const target = htmxTarget(event);
    if (target)
        target.classList.remove("is-unrefreshed");
}
function watchFragments() {
    // No network at all, and a request that came back an error: the same thing
    // as far as the panel is concerned.
    document.body.addEventListener("htmx:sendError", markUnrefreshed);
    document.body.addEventListener("htmx:responseError", markUnrefreshed);
    document.body.addEventListener("htmx:afterSwap", clearUnrefreshed);
}
/** A page the service worker served from its cache. Readable, and possibly
 *  out of date, which is worth one line rather than a silent guess. */
function showStoredCopyNotice() {
    if (!document.body.dataset["offlineCopy"])
        return;
    const notice = document.getElementById("stored-copy-notice");
    if (notice)
        notice.hidden = false;
}
function initPwa() {
    registerServiceWorker();
    watchConnection();
    watchSwaps();
    watchFragments();
    showStoredCopyNotice();
}
initPwa();
