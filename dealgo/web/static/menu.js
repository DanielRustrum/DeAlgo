"use strict";
// The tab drawer, below tablet width.
//
// Opening and closing it is a checkbox and two labels, and works with no
// JavaScript at all — see base.html. Everything here is the part CSS cannot
// do: telling assistive technology whether the drawer is open, closing it on
// Escape, and stopping the page behind it scrolling while it is.
//
// Top-level `function` declarations only: see the note in dialog.ts.
/** The checkbox that is the drawer's open/closed state. */
function menuCheckbox() {
    return document.getElementById("menu-toggle");
}
function menuButton() {
    return document.querySelector(".menu-button");
}
/** Say what the hamburger does, and what state it is in.
 *
 *  A label for a checkbox announces as a checkbox, which is honest but says
 *  nothing about the drawer. These attributes are only correct while this
 *  script is running, which is why they are set here rather than in the
 *  template. */
function describeMenu(open) {
    const button = menuButton();
    if (!button)
        return;
    button.setAttribute("role", "button");
    button.setAttribute("aria-controls", "site-menu");
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.setAttribute("aria-label", open ? "Close menu" : "Open menu");
}
/** A drawer over a page that scrolls underneath it reads as broken. */
function holdPageStill(open) {
    document.body.classList.toggle("page-held", open);
}
function setMenu(open) {
    const checkbox = menuCheckbox();
    if (checkbox)
        checkbox.checked = open;
    describeMenu(open);
    holdPageStill(open);
}
function closeMenu() {
    setMenu(false);
}
function onMenuChange() {
    var _a;
    const checkbox = menuCheckbox();
    setMenu((_a = checkbox === null || checkbox === void 0 ? void 0 : checkbox.checked) !== null && _a !== void 0 ? _a : false);
}
/** Escape closes the drawer, and puts focus back where it came from. */
function onKeyDown(event) {
    var _a;
    if (event.key !== "Escape")
        return;
    const checkbox = menuCheckbox();
    if (!(checkbox === null || checkbox === void 0 ? void 0 : checkbox.checked))
        return;
    closeMenu();
    (_a = menuButton()) === null || _a === void 0 ? void 0 : _a.focus();
}
/** Following a link should leave the drawer shut. A boosted navigation
 *  replaces the bar and closes it anyway; this covers the plain-navigation
 *  case, and the moment between the click and the swap.
 *
 *  The whole panel, not just the tabs: Tour is a link in there too. The sync
 *  buttons are not — they post in place and their result belongs on screen. */
function closeOnNavigation() {
    const panel = document.getElementById("site-menu");
    panel === null || panel === void 0 ? void 0 : panel.addEventListener("click", (event) => {
        if (event.target instanceof HTMLAnchorElement)
            closeMenu();
    });
}
function initMenu() {
    const checkbox = menuCheckbox();
    if (!checkbox)
        return; // a page without the standard frame
    checkbox.addEventListener("change", onMenuChange);
    document.addEventListener("keydown", onKeyDown);
    closeOnNavigation();
    // A boosted swap brings a fresh, closed drawer; make sure the body class
    // does not outlive the drawer it belonged to.
    document.body.addEventListener("htmx:afterSwap", () => {
        var _a;
        var _b;
        setMenu((_b = (_a = menuCheckbox()) === null || _a === void 0 ? void 0 : _a.checked) !== null && _b !== void 0 ? _b : false);
    });
    setMenu(checkbox.checked);
}
initMenu();
