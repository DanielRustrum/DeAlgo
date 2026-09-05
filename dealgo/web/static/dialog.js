// Promote server-rendered <dialog data-modal> to a real modal.
//
// The markup ships with `open`, so it is visible even if this never runs.
// showModal() adds what the attribute alone cannot: the browser's top layer
// (so no ancestor's overflow or z-index can clip it), a ::backdrop, Esc to
// close, and a focus trap.
(function () {
  function closeVia(dialog) {
    var url = dialog.dataset.close;
    if (url && window.htmx) {
      // Drop the ?new flag server-side too, or the panel would bring it back.
      window.htmx.ajax("GET", url, { target: "#playlist-targets", swap: "outerHTML" });
    } else if (url) {
      window.location.href = "/channels";
    }
  }

  function promote(root) {
    (root || document).querySelectorAll("dialog[data-modal]").forEach(function (dialog) {
      if (dialog.dataset.promoted) return;
      dialog.dataset.promoted = "1";

      if (typeof dialog.showModal === "function") {
        // showModal() throws on a dialog that is open but not modal, which is
        // exactly what the server sends. Clear the attribute rather than
        // calling close(): close() queues a `close` event that would arrive
        // after the listener below is attached and shut the box again a frame
        // after it opened.
        dialog.removeAttribute("open");
        dialog.showModal();
      }

      // Esc, or any other native close, should clear the server flag too.
      dialog.addEventListener("close", function () {
        if (dialog.dataset.closing) return;
        dialog.dataset.closing = "1";
        closeVia(dialog);
      });

      // Clicking the backdrop means the click lands on the dialog itself.
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) dialog.close();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () { promote(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { promote(event.target); });
  promote(document);
})();
