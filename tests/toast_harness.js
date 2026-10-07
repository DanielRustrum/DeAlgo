// Runs the compiled toast script against a stub DOM and reports what it did,
// as JSON, for test_toast.py to assert on.
//
// The drawing needs a browser; the decisions do not. Which toasts go by
// themselves, which wait to be dealt with, and what a dismissal is remembered
// as — those are the parts worth pinning down, and this gives them somewhere
// to run.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SCRIPT = path.join(__dirname, "..", "pamphlets", "web", "static", "toast.js");

/** One toast, as the script will find it in the document. */
function stubToast(attrs) {
  const element = {
    dataset: { ...(attrs.dataset ?? {}) },
    children: [],
    removed: false,
    classes: new Set(),
    classList: {
      add(name) { element.classes.add(name); },
      remove(name) { element.classes.delete(name); },
    },
    hasAttribute(name) { return attrs.passing === true && name === "data-toast-passing"; },
    querySelector(selector) {
      return element.children.find((child) => `.${child.className}` === selector) ?? null;
    },
    appendChild(child) { element.children.push(child); return child; },
    remove() { element.removed = true; },
  };
  return element;
}

function run({ toasts, stored = {}, storageThrows = false }) {
  const made = toasts.map(stubToast);
  const timers = [];
  const memory = { ...stored };
  const listeners = [];

  const document = {
    querySelectorAll() { return made; },
    body: {
      addEventListener(name) { listeners.push(name); },
    },
    createElement(tag) {
      const made = {
        tag,
        type: "",
        className: "",
        textContent: "",
        handlers: {},
        setAttribute() {},
        addEventListener(name, run) { made.handlers[name] = run; },
      };
      return made;
    },
  };

  const window = {
    document,
    setTimeout(run, after) { timers.push({ run, after }); return timers.length; },
    get sessionStorage() {
      if (storageThrows) throw new Error("blocked");
      return {
        getItem(key) { return key in memory ? memory[key] : null; },
        setItem(key, value) { memory[key] = value; },
      };
    },
  };

  const context = vm.createContext({ window, document, console });
  vm.runInContext(fs.readFileSync(SCRIPT, "utf8"), context);

  return { made, timers, memory, listeners, context };
}

const report = {};

// A passing message — something that just happened. It has been read by the
// time it is read, so it goes on its own.
{
  const { made, timers } = run({ toasts: [{ passing: true }] });
  report.passing = {
    hasCloseButton: made[0].children.length === 1,
    timerCount: timers.length,
    secondsUntilGone: timers.length ? timers[0].after / 1000 : null,
  };
}

// A standing condition — still true after you look away. It waits.
{
  const { made, timers } = run({ toasts: [{ dataset: { toast: "no-sign-in" } }] });
  report.standing = {
    hasCloseButton: made[0].children.length === 1,
    timerCount: timers.length,
  };
}

// One already dismissed this session never appears at all.
{
  const { made } = run({
    toasts: [{ dataset: { toast: "no-sign-in" } }],
    stored: { "toast:no-sign-in": "gone" },
  });
  report.alreadyDismissed = { removed: made[0].removed };
}

// Dismissing a standing one remembers it; dismissing a passing one does not,
// because a passing one has no identity to remember.
{
  const { made, memory } = run({ toasts: [{ dataset: { toast: "weak-password" } }] });
  made[0].children[0].handlers.click();
  report.dismissRemembers = { memory: { ...memory }, going: made[0].classes.has("is-going") };
}
{
  const { made, memory } = run({ toasts: [{ passing: true }] });
  made[0].children[0].handlers.click();
  report.dismissPassing = { memory: { ...memory } };
}

// Storage that throws on access — a private window, or blocked site data.
// The toast still works; the dismissal simply does not outlive the page.
{
  const { made, memory } = run({ toasts: [{ dataset: { toast: "no-sign-in" } }], storageThrows: true });
  made[0].children[0].handlers.click();
  report.storageBlocked = {
    shown: made[0].removed === false,
    going: made[0].classes.has("is-going"),
    memory: { ...memory },
  };
}

// Run twice over the same toasts: nothing is set up again, so a swap that
// leaves the old ones in place does not restart their timers or grow a
// second close button.
{
  const { made, timers, context } = run({ toasts: [{ passing: true }] });
  context.initToasts();
  report.runTwice = { children: made[0].children.length, timerCount: timers.length };
}

// It listens for htmx swaps, because the flash arrives out of band.
{
  const { listeners } = run({ toasts: [] });
  report.listensFor = listeners;
}

process.stdout.write(JSON.stringify(report, null, 2));
