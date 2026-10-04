"use strict";
// Settings → Theming: the preview follows the form before anything is saved.
//
// The form works without this — it posts, the server checks every value and
// the page comes back in the new look. What this adds is seeing a change as
// it is made: every variable the form sets is copied onto the preview, which
// is a small page of the app's own parts scoped by `.theme-scope`, and the
// contrast of each pairing the app paints is rechecked as you go.
//
// It sets custom properties on one element and nothing else: values come from
// colour pickers, sliders and fixed options, and the server checks them again.
//
// Structure: top-level `function` declarations and one call at the bottom.
// This is a plain script that htmx re-runs on every boosted navigation, and a
// top-level `const` or `class` would throw "already declared" the second time.
/** What the page says it can change: names, defaults, typefaces, pairings. */
function themingData() {
    const node = document.getElementById("theming-data");
    if (!node || !node.textContent)
        return null;
    try {
        return JSON.parse(node.textContent);
    }
    catch (_a) {
        return null;
    }
}
function themingInput(form, name) {
    const found = form.elements.namedItem(name);
    return found instanceof HTMLInputElement ? found : null;
}
function themingSelect(form, name) {
    const found = form.elements.namedItem(name);
    return found instanceof HTMLSelectElement ? found : null;
}
/** What a choice is set to: a list's value, or the ticked radio's. */
function themingChoice(form, name) {
    const select = themingSelect(form, name);
    if (select)
        return select.value;
    const ticked = form.querySelector(`input[name="${name}"]:checked`);
    return ticked ? ticked.value : null;
}
/** Whether a colour that follows another is, in one mode, still following it. */
function themingFollowing(form, mode, name) {
    const box = themingInput(form, `follow.${mode}.${name}`);
    return box !== null && box.checked;
}
/** Every colour in one mode as the form has it now, following where it follows. */
function themingResolve(data, form, mode) {
    const byName = new Map(data.colours.map((colour) => [colour.name, colour]));
    const out = new Map();
    function value(name, depth) {
        const known = out.get(name);
        if (known)
            return known;
        const colour = byName.get(name);
        if (!colour)
            return "#000000";
        let result;
        if (colour.follows && depth < 8 && themingFollowing(form, mode, name)) {
            result = value(colour.follows, depth + 1);
        }
        else {
            const input = themingInput(form, `${mode}.${name}`);
            result = input ? input.value : mode === "dark" ? colour.dark : colour.light;
        }
        out.set(name, result);
        return result;
    }
    for (const colour of data.colours)
        value(colour.name, 0);
    return out;
}
function themingDialValue(form, dial) {
    const input = themingInput(form, dial.name);
    const parsed = input ? parseFloat(input.value) : NaN;
    return Number.isFinite(parsed) ? parsed : dial.default;
}
/** A dial's value the way its slider reads it: 110%, 1.55, 600, 3px. */
function themingShown(value, show) {
    if (show === "%")
        return `${Math.round(value * 100)}%`;
    if (show === "x")
        return value.toFixed(2);
    if (show === "px")
        return `${value}px`;
    return String(value);
}
function themingPreview() {
    return document.getElementById("theme-preview");
}
function themingPreviewMode() {
    var _a;
    return ((_a = themingPreview()) === null || _a === void 0 ? void 0 : _a.dataset["mode"]) === "dark" ? "dark" : "light";
}
/** The modes the chosen setting can show: both, unless it is always one. */
function themingModesShown(form) {
    const chosen = form.querySelector('input[name="mode"]:checked');
    if ((chosen === null || chosen === void 0 ? void 0 : chosen.value) === "light")
        return ["light"];
    if ((chosen === null || chosen === void 0 ? void 0 : chosen.value) === "dark")
        return ["dark"];
    return ["light", "dark"];
}
function themingLuminance(hex) {
    var _a, _b, _c;
    const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
    const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
    return 0.2126 * ((_a = linear[0]) !== null && _a !== void 0 ? _a : 0) + 0.7152 * ((_b = linear[1]) !== null && _b !== void 0 ? _b : 0) + 0.0722 * ((_c = linear[2]) !== null && _c !== void 0 ? _c : 0);
}
function themingRatio(one, other) {
    const a = themingLuminance(one);
    const b = themingLuminance(other);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
/** Rewrite the list of pairings that read below their minimum. */
function themingReport(data, form) {
    var _a, _b;
    const report = document.getElementById("contrast-report");
    if (!report)
        return;
    const lines = [];
    for (const mode of themingModesShown(form)) {
        const colours = themingResolve(data, form, mode);
        const seen = new Set();
        for (const pair of data.pairs) {
            const key = `${pair.ink}/${pair.ground}`;
            if (seen.has(key))
                continue;
            seen.add(key);
            const ratio = themingRatio((_a = colours.get(pair.ink)) !== null && _a !== void 0 ? _a : "#000000", (_b = colours.get(pair.ground)) !== null && _b !== void 0 ? _b : "#ffffff");
            if (Math.round(ratio * 100) / 100 < pair.minimum) {
                lines.push(`${pair.where} (${mode}): ${ratio.toFixed(1)}:1, needs ${pair.minimum}:1`);
            }
        }
    }
    report.replaceChildren();
    const title = document.createElement("p");
    title.className = "contrast-title";
    if (lines.length === 0) {
        title.classList.add("contrast-ok");
        title.textContent = "Everything reads at the recommended contrast.";
        report.append(title);
        return;
    }
    const strong = document.createElement("strong");
    strong.textContent = "Hard to read";
    title.append(strong);
    const list = document.createElement("ul");
    for (const line of lines) {
        const item = document.createElement("li");
        item.textContent = line;
        list.append(item);
    }
    report.append(title, list);
}
/** Copy the form onto the preview, and keep the controls' own state honest. */
function themingApply(data, form) {
    var _a, _b;
    const preview = themingPreview();
    const mode = themingPreviewMode();
    for (const which of ["light", "dark"]) {
        const colours = themingResolve(data, form, which);
        for (const colour of data.colours) {
            const input = themingInput(form, `${which}.${colour.name}`);
            if (!input)
                continue;
            const following = colour.follows !== null && themingFollowing(form, which, colour.name);
            // A colour that follows another shows that one's value, greyed.
            input.disabled = following;
            if (following)
                input.value = (_a = colours.get(colour.name)) !== null && _a !== void 0 ? _a : input.value;
            const reset = form.querySelector(`[data-reset="${colour.name}"][data-mode="${which}"]`);
            if (reset)
                reset.hidden = following || input.value.toLowerCase() === input.dataset["default"];
        }
        if (preview && which === mode) {
            for (const [name, value] of colours)
                preview.style.setProperty(`--${name}`, value);
        }
    }
    for (const dial of data.dials) {
        const value = themingDialValue(form, dial);
        const output = form.querySelector(`output[for="dial-${dial.name}"]`);
        if (output)
            output.textContent = themingShown(value, dial.show);
        if (!preview)
            continue;
        if (dial.name === "depth") {
            const [r, g, b, alpha] = (_b = data.shadow[mode]) !== null && _b !== void 0 ? _b : [0, 0, 0, 0.2];
            preview.style.setProperty("--shadow", `rgba(${r}, ${g}, ${b}, ${Math.min((alpha !== null && alpha !== void 0 ? alpha : 0.2) * value, 0.9)})`);
        }
        else {
            preview.style.setProperty(`--${dial.name}`, `${value}${dial.unit}`);
        }
    }
    for (const name of ["font-body", "font-display"]) {
        const select = themingSelect(form, name);
        const stack = select ? data.fonts[select.value] : undefined;
        if (preview && stack)
            preview.style.setProperty(`--${name}`, stack);
    }
    // The choices the stylesheet acts on, set on the preview as the page sets
    // them on its root: the background, the pattern, which plants and where.
    for (const name of data.choices) {
        const value = themingChoice(form, name);
        if (preview && value !== null)
            preview.setAttribute(`data-${name}`, value);
    }
    if (preview)
        preview.dataset["mode"] = mode;
    themingReport(data, form);
}
function themingSetPreviewMode(data, form, mode) {
    const preview = themingPreview();
    if (preview)
        preview.dataset["mode"] = mode;
    document.querySelectorAll("[data-preview-mode]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset["previewMode"] === mode));
    });
    themingApply(data, form);
}
/** Show one mode's colours, and point the preview at it. */
function themingShowColours(data, form, mode) {
    form.querySelectorAll("[data-colour-mode]").forEach((set) => {
        set.hidden = set.dataset["colourMode"] !== mode;
    });
    form.querySelectorAll("[data-colour-tab]").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab.dataset["colourTab"] === mode));
    });
    themingSetPreviewMode(data, form, mode);
}
function initTheming() {
    var _a;
    const form = document.getElementById("theme-form");
    if (!(form instanceof HTMLFormElement) || form.dataset["themingReady"])
        return;
    const data = themingData();
    if (!data)
        return;
    form.dataset["themingReady"] = "1";
    const unsaved = document.getElementById("theming-unsaved");
    function changed() {
        if (unsaved)
            unsaved.hidden = false;
        themingApply(data, form);
    }
    form.addEventListener("input", changed);
    form.addEventListener("change", changed);
    form.addEventListener("click", (event) => {
        var _a, _b;
        const target = event.target instanceof Element ? event.target : null;
        const reset = target === null || target === void 0 ? void 0 : target.closest("[data-reset]");
        if (reset) {
            const mode = (_a = reset.dataset["mode"]) !== null && _a !== void 0 ? _a : "light";
            const input = themingInput(form, `${mode}.${(_b = reset.dataset["reset"]) !== null && _b !== void 0 ? _b : ""}`);
            if (input && input.dataset["default"])
                input.value = input.dataset["default"];
            changed();
            return;
        }
        const tab = target === null || target === void 0 ? void 0 : target.closest("[data-colour-tab]");
        if (tab)
            themingShowColours(data, form, tab.dataset["colourTab"] === "dark" ? "dark" : "light");
    });
    document.querySelectorAll(".colour-tabs, [data-preview-tabs]").forEach((tabs) => {
        tabs.hidden = false;
    });
    (_a = document.getElementById("colours")) === null || _a === void 0 ? void 0 : _a.classList.add("theming-tabbed");
    document.querySelectorAll("[data-preview-mode]").forEach((button) => {
        button.addEventListener("click", () => {
            themingSetPreviewMode(data, form, button.dataset["previewMode"] === "dark" ? "dark" : "light");
        });
    });
    // Start on whichever the page is showing now.
    const shown = themingModesShown(form);
    const night = shown.length === 1 ? shown[0] === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    themingShowColours(data, form, night ? "dark" : "light");
    if (unsaved)
        unsaved.hidden = true;
}
initTheming();
