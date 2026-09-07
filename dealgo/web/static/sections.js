// Keep expanded feed sections open across an htmx refresh.
//
// The sections collapse by default, which is the point — but a sync landing
// while you are part-way through one should not fold it shut underneath you.
// Nothing is stored beyond this page view, so a fresh load starts collapsed.
(function () {
  var open = new Set();

  function remember(root) {
    (root || document).querySelectorAll("details[id]").forEach(function (details) {
      if (details.open) open.add(details.id);
      else open.delete(details.id);
      if (!details.dataset.watched) {
        details.dataset.watched = "1";
        details.addEventListener("toggle", function () {
          if (details.open) open.add(details.id);
          else open.delete(details.id);
        });
      }
    });
  }

  function restore(root) {
    (root || document).querySelectorAll("details[id]").forEach(function (details) {
      if (open.has(details.id)) details.open = true;
    });
    remember(root);
  }

  document.addEventListener("DOMContentLoaded", function () { remember(document); });
  document.body.addEventListener("htmx:beforeSwap", function () { remember(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { restore(event.target); });
  remember(document);
})();
