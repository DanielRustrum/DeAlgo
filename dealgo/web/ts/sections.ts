// Keep expanded feed sections open across an htmx refresh.
//
// The sections collapse by default, which is the point — but a sync landing
// while you are part-way through one should not fold it shut underneath you.
// Nothing is stored beyond this page view, so a fresh load starts collapsed.
//
// Top-level `function` declarations only, and one entry call at the end: see
// tests/test_scripts.py, which says why and holds every script to it.

/** Which sections are open, by element id. Lives for one page view. */
type OpenSections = Set<string>;

/** Note what is open now, and watch each section for later changes. */
function rememberSections(open: OpenSections, root: ParentNode): void {
  root.querySelectorAll<HTMLDetailsElement>("details[id]").forEach((details): void => {
    noteSection(open, details);
    if (details.dataset["watched"]) return;
    details.dataset["watched"] = "1";
    details.addEventListener("toggle", (): void => noteSection(open, details));
  });
}

function noteSection(open: OpenSections, details: HTMLDetailsElement): void {
  if (details.open) open.add(details.id);
  else open.delete(details.id);
}

/** Reopen what was open before the swap replaced it. */
function restoreSections(open: OpenSections, root: ParentNode): void {
  root.querySelectorAll<HTMLDetailsElement>("details[id]").forEach((details): void => {
    if (open.has(details.id)) details.open = true;
  });
  rememberSections(open, root);
}

/** A swap can land on anything; only an element has children to search. */
function swappedSectionRoot(event: Event): ParentNode {
  return event.target instanceof Element ? event.target : document;
}

function initSections(): void {
  // Scoped to this call rather than to the file: nothing else needs it, and a
  // top-level binding could not survive the script being run twice.
  const open: OpenSections = new Set<string>();

  document.addEventListener("DOMContentLoaded", (): void => rememberSections(open, document));
  document.body.addEventListener("htmx:beforeSwap", (): void => rememberSections(open, document));
  document.body.addEventListener("htmx:afterSwap", (event: Event): void => {
    restoreSections(open, swappedSectionRoot(event));
  });
  rememberSections(open, document);
}

initSections();
