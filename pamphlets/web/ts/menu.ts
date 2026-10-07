// The tab drawer, below tablet width.
//
// Opening and closing it is a checkbox and two labels, and works with no
// JavaScript at all — see base.html. Everything here is the part CSS cannot
// do: telling assistive technology whether the drawer is open, closing it on
// Escape, and stopping the page behind it scrolling while it is.
//
// Top-level `function` declarations only, and one entry call at the end: see
// tests/test_scripts.py, which says why and holds every script to it.

/** The checkbox that is the drawer's open/closed state. */
function menuCheckbox(): HTMLInputElement | null {
  return document.getElementById("menu-toggle") as HTMLInputElement | null;
}

/** The button that opens the menu. */
function menuButton(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".menu-button");
}

/** Say what the hamburger does, and what state it is in.
 *
 *  A label for a checkbox announces as a checkbox, which is honest but says
 *  nothing about the drawer. These attributes are only correct while this
 *  script is running, which is why they are set here rather than in the
 *  template. */
function describeMenu(open: boolean): void {
  const button = menuButton();
  if (!button) return;
  button.setAttribute("role", "button");
  button.setAttribute("aria-controls", "site-menu");
  button.setAttribute("aria-expanded", open ? "true" : "false");
  button.setAttribute("aria-label", open ? "Close menu" : "Open menu");
}

/** A drawer over a page that scrolls underneath it reads as broken. */
function holdPageStill(open: boolean): void {
  document.body.classList.toggle("page-held", open);
}

/** Open or close the menu, and hold the page still while it is open. */
function setMenu(open: boolean): void {
  const checkbox = menuCheckbox();
  if (checkbox) checkbox.checked = open;
  describeMenu(open);
  holdPageStill(open);
}

/** Close the menu. */
function closeMenu(): void {
  setMenu(false);
}

/** Follow the menu checkbox when it is toggled. */
function onMenuChange(): void {
  const checkbox = menuCheckbox();
  setMenu(checkbox?.checked ?? false);
}

/** Escape closes the drawer, and puts focus back where it came from. */
function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  const checkbox = menuCheckbox();
  if (!checkbox?.checked) return;
  closeMenu();
  menuButton()?.focus();
}

/** Following a link should leave the drawer shut. A boosted navigation
 *  replaces the bar and closes it anyway; this covers the plain-navigation
 *  case, and the moment between the click and the swap.
 *
 *  The whole panel, not just the tabs: Tour is a link in there too. The sync
 *  buttons are not — they post in place and their result belongs on screen. */
function closeOnNavigation(): void {
  const panel = document.getElementById("site-menu");
  panel?.addEventListener("click", (event: MouseEvent): void => {
    if (event.target instanceof HTMLAnchorElement) closeMenu();
  });
}

/** The menu's entry point: wire up the drawer, Escape, and closing on navigation. */
function initMenu(): void {
  const checkbox = menuCheckbox();
  if (!checkbox) return; // a page without the standard frame

  checkbox.addEventListener("change", onMenuChange);
  document.addEventListener("keydown", onKeyDown);
  closeOnNavigation();

  // A boosted swap brings a fresh, closed drawer; make sure the body class
  // does not outlive the drawer it belonged to.
  document.body.addEventListener("htmx:afterSwap", (): void => {
    setMenu(menuCheckbox()?.checked ?? false);
  });

  setMenu(checkbox.checked);
}

initMenu();
