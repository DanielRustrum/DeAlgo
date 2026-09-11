"use strict";
// Promote server-rendered <dialog data-modal> to a real modal.
//
// The markup ships with `open`, so it is visible even if this never runs.
// showModal() adds what the attribute alone cannot: the browser's top layer
// (so no ancestor's overflow or z-index can clip it), a ::backdrop, Esc to
// close, and a focus trap.
//
// Everything here is a top-level `function` on purpose. These files are plain
// scripts, and htmx re-runs a script when it swaps one in, so a top-level
// `const` or `class` would throw "already declared" the second time round.
// Function declarations are the only form that survives being executed twice.
/** Tell the server the box is shut, so a refresh does not reopen it. */
function closeDialogVia(dialog) {
    const url = dialog.dataset["close"];
    if (!url)
        return;
    if (window.htmx) {
        // Drop the ?new flag server-side too, or the panel would bring it back.
        void window.htmx.ajax("GET", url, { target: "#playlist-targets", swap: "outerHTML" });
        return;
    }
    window.location.href = "/channels";
}
/** Give one dialog its modal behaviour, once. */
function promoteDialog(dialog) {
    if (dialog.dataset["promoted"])
        return;
    dialog.dataset["promoted"] = "1";
    if (typeof dialog.showModal === "function") {
        // showModal() throws on a dialog that is open but not modal, which is
        // exactly what the server sends. Clear the attribute rather than calling
        // close(): close() queues a `close` event that would arrive after the
        // listener below is attached and shut the box again a frame after it
        // opened.
        dialog.removeAttribute("open");
        dialog.showModal();
    }
    // Esc, or any other native close, should clear the server flag too.
    dialog.addEventListener("close", () => {
        if (dialog.dataset["closing"])
            return;
        dialog.dataset["closing"] = "1";
        closeDialogVia(dialog);
    });
    // Clicking the backdrop means the click lands on the dialog itself.
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog)
            dialog.close();
    });
}
/** Promote every dialog inside a piece of the page. */
function promoteDialogsIn(root) {
    root.querySelectorAll("dialog[data-modal]").forEach(promoteDialog);
}
/** A swap can land on anything; only an element has children to search. */
function swappedRoot(event) {
    return event.target instanceof Element ? event.target : document;
}
function initDialogs() {
    document.addEventListener("DOMContentLoaded", () => promoteDialogsIn(document));
    document.body.addEventListener("htmx:afterSwap", (event) => {
        promoteDialogsIn(swappedRoot(event));
    });
    promoteDialogsIn(document);
}
initDialogs();
