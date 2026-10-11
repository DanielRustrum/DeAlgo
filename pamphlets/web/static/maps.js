"use strict";
// Maps: the Map leaflet, drawn by Leaflet in the theme's colours.
//
// (A *leaflet* is a block of a pamphlet's page; *Leaflet* is the map library
// that draws this one. They only share a name.)
//
// The server places each row as a dot (services/mapping.py) and sets the map
// on the page as an empty box with its dots beside it, as JSON
// (templates/_map.html). This draws each one: Leaflet, vendored into
// static/vendor, is only fetched the first time a page has a map on it. The
// dots wear the theme's chart colours (--chart-1…6) and are ringed in the
// panel's colour; the map pictures under them are muted towards the theme's
// surfaces by the stylesheet, so the dots are what stands out. A map is
// redrawn when the page goes light or dark, or the theme changes.
//
// Loaded on every page, from base.html; htmx swaps pages in without loading
// it again, so maps in swapped-in content are drawn when it settles. The
// canvas's editor draws its own through `drawMaps`.
/** A map's dots and where its pictures come from, from the JSON beside it. */
function mapSpec(figure) {
    var _a;
    var _b;
    const said = (_b = (_a = figure.querySelector("script[data-map-config]")) === null || _a === void 0 ? void 0 : _a.textContent) !== null && _b !== void 0 ? _b : "";
    let raw;
    try {
        raw = JSON.parse(said);
    }
    catch (_c) {
        return null;
    }
    if (typeof raw !== "object" || raw === null)
        return null;
    const given = raw;
    const dots = [];
    if (Array.isArray(given["dots"])) {
        for (const entry of given["dots"]) {
            if (typeof entry !== "object" || entry === null)
                continue;
            const dot = entry;
            const lat = dot["lat"];
            const lng = dot["lng"];
            if (typeof lat !== "number" || typeof lng !== "number")
                continue;
            dots.push({
                lat,
                lng,
                slot: typeof dot["slot"] === "number" ? dot["slot"] : 1,
                says: typeof dot["says"] === "string" ? dot["says"] : "",
                r: typeof dot["r"] === "number" ? dot["r"] : 6,
            });
        }
    }
    let bounds = null;
    const box = given["bounds"];
    if (Array.isArray(box) && box.length === 2) {
        const corner = (one) => Array.isArray(one) && typeof one[0] === "number" && typeof one[1] === "number" ? [one[0], one[1]] : null;
        const south = corner(box[0]);
        const north = corner(box[1]);
        if (south !== null && north !== null)
            bounds = [south, north];
    }
    return {
        dots,
        tiles: typeof given["tiles"] === "string" ? given["tiles"] : "",
        credit: typeof given["credit"] === "string" ? given["credit"] : "",
        bounds,
        fixed: given["fixed"] === true,
    };
}
/** The theme's colours a map is drawn in, as the page has them now. */
function mapTheme() {
    const look = getComputedStyle(document.documentElement);
    const colours = [];
    for (let slot = 1; slot <= 6; slot += 1)
        colours.push(look.getPropertyValue(`--chart-${slot}`).trim() || "#c04f2c");
    return { colours, panel: look.getPropertyValue("--panel").trim() || "#fffaf3" };
}
/** Draw one map afresh: one drawn there before is put away first. */
function drawMap(figure) {
    var _a, _b;
    const library = window.L;
    const box = figure.querySelector(".map-js-box");
    const spec = mapSpec(figure);
    if (library === undefined || box === null || spec === null)
        return;
    if (spec.dots.length === 0 && spec.bounds === null)
        return;
    const before = box.pamphletsMap;
    before === null || before === void 0 ? void 0 : before.remove();
    const theme = mapTheme();
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Fixed, it is a picture of where it was set: nothing moves it. Free, a
    // page scrolls past it rather than being caught by it: zooming is by its
    // buttons, or by the wheel once the map has been clicked into.
    const free = !spec.fixed;
    const map = library.map(box, {
        zoomControl: free,
        dragging: free,
        touchZoom: free,
        doubleClickZoom: free,
        boxZoom: free,
        keyboard: free,
        scrollWheelZoom: false,
        zoomAnimation: !still,
        fadeAnimation: !still,
        attributionControl: true,
    });
    map.attributionControl.setPrefix(false);
    library.tileLayer(spec.tiles, { attribution: spec.credit, maxZoom: 19 }).addTo(map);
    if (free)
        map.on("click", () => map.scrollWheelZoom.enable());
    const placed = [];
    for (const dot of spec.dots) {
        const colour = (_b = (_a = theme.colours[Math.min(6, Math.max(1, dot.slot)) - 1]) !== null && _a !== void 0 ? _a : theme.colours[0]) !== null && _b !== void 0 ? _b : "#c04f2c";
        const marker = library.circleMarker([dot.lat, dot.lng], {
            radius: dot.r,
            color: theme.panel,
            weight: 2,
            fillColor: colour,
            fillOpacity: 0.85,
        }).addTo(map);
        if (dot.says !== "") {
            // Set as text, never as markup: what a row says is somebody else's.
            const words = document.createElement("span");
            words.textContent = dot.says;
            marker.bindPopup(words);
        }
        placed.push([dot.lat, dot.lng]);
    }
    // Focused on an area, it shows that area, dots or no; else it fits the dots.
    if (spec.bounds !== null)
        map.fitBounds(spec.bounds, { padding: [8, 8] });
    else if (placed.length === 1 && placed[0] !== undefined)
        map.setView(placed[0], 12);
    else
        map.fitBounds(placed, { padding: [24, 24], maxZoom: 15 });
    box.pamphletsMap = map;
    figure.dataset["drawn"] = "1";
}
/** Draw every map in part of the page, fetching Leaflet first if this is
 *  the first map there has been. `again` redraws ones already drawn. */
function drawMaps(root, again = false) {
    const figures = Array.from(root.querySelectorAll("[data-map]"))
        .filter((one) => again || one.dataset["drawn"] !== "1");
    if (figures.length === 0)
        return;
    if (window.L === undefined) {
        fetchLeaflet(() => drawMaps(root, again));
        return;
    }
    for (const figure of figures)
        drawMap(figure);
}
/** Fetch Leaflet's script and stylesheet once, then carry on. Their
 *  addresses — with the version that keeps a cached copy current — are on
 *  this script's own tag. */
function fetchLeaflet(then) {
    const asked = document.querySelector("script[data-leaflet-loading]");
    if (asked !== null) {
        asked.addEventListener("load", then, { once: true });
        return;
    }
    const tag = document.querySelector("script[data-leaflet-js]");
    const script = tag === null || tag === void 0 ? void 0 : tag.dataset["leafletJs"];
    const sheet = tag === null || tag === void 0 ? void 0 : tag.dataset["leafletCss"];
    if (script === undefined || script === "" || sheet === undefined)
        return;
    // The library's stylesheet first, in the head, before the app's: the app's
    // rules for maps are written to win over it.
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = sheet;
    document.head.prepend(link);
    const loading = document.createElement("script");
    loading.src = script;
    loading.dataset["leafletLoading"] = "1";
    loading.addEventListener("load", then, { once: true });
    document.head.appendChild(loading);
}
/** Draw the page's maps, and again whenever the page or its theme changes:
 *  content swapped in by htmx, a move between light and dark, a new theme. */
function initMaps() {
    // `drawMaps`, a function at the top of a plain script, is already
    // window.drawMaps: the canvas's editor calls it from there.
    drawMaps(document);
    const root = document.documentElement;
    if (root.dataset["mapsListen"] === "1")
        return;
    root.dataset["mapsListen"] = "1";
    document.body.addEventListener("htmx:afterSettle", (event) => {
        drawMaps(event.target instanceof Element ? event.target : document);
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        drawMaps(document, true);
    });
    new MutationObserver(() => drawMaps(document, true)).observe(root, {
        attributes: true, attributeFilter: ["data-mode", "style"],
    });
}
initMaps();
