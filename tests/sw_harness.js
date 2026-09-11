// Runs the compiled service worker against a stub Cache API and reports what
// it did, as JSON, for test_pwa.py to assert on.
//
// The worker is the one part of De-Algo that cannot be exercised from Python:
// it runs in a worker, talks to caches, and its whole job is what happens when
// fetch fails. This gives it somewhere to actually run.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WORKER = path.join(__dirname, "..", "dealgo", "web", "static", "sw.js");

function stubResponse(body, init = {}) {
  return {
    body,
    ok: init.ok !== false,
    status: init.status || 200,
    statusText: "",
    headers: init.headers || {},
    type: init.type || "basic",
    clone() { return stubResponse(body, init); },
    async text() { return body; },
  };
}

function makeWorker({ online, cached = {} }) {
  const listeners = {};
  const stores = new Map();
  const caches = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        async match(request) { return store.get(typeof request === "string" ? request : request.url); },
        async put(request, response) { store.set(typeof request === "string" ? request : request.url, response); },
        async add(request) { store.set(request.url, stubResponse("precached")); },
        async keys() { return [...store.keys()].map((url) => ({ url })); },
        async delete(key) { return store.delete(typeof key === "string" ? key : key.url); },
      };
    },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };

  const context = vm.createContext({
    self: {
      location: { href: "https://app.test/sw.js?v=v1", origin: "https://app.test" },
      addEventListener: (kind, fn) => { listeners[kind] = fn; },
      skipWaiting: async () => {},
      clients: { claim: async () => {} },
    },
    caches, URL, URLSearchParams, Promise, console,
    Request: class { constructor(url, options = {}) { this.url = url; this.mode = options.mode || "cors"; this.method = "GET"; } },
    Response: function (body, init) { return stubResponse(body, init); },
    fetch: async () => {
      if (!online) throw new Error("offline");
      return stubResponse("live from the server", { type: "basic" });
    },
  });
  vm.runInContext(fs.readFileSync(WORKER, "utf8"), context);

  const shell = stores.get("dealgo-v1") ?? new Map();
  stores.set("dealgo-v1", shell);
  shell.set("/offline", stubResponse('<html><body hx-boost="true">missing <!--OFFLINE-PATH--> page</body></html>'));
  for (const [url, body] of Object.entries(cached)) shell.set(url, stubResponse(body));

  return { listeners, stores };
}

async function answerFor(worker, request) {
  let promise = null;
  worker.listeners.fetch({ request, respondWith: (value) => { promise = value; } });
  return promise === null ? null : promise;
}

async function main() {
  const report = {};

  // Install fills the shell cache.
  const installed = makeWorker({ online: true });
  let pending;
  await installed.listeners.install({ waitUntil: (value) => { pending = value; } });
  await pending;
  report.cacheNames = [...installed.stores.keys()];
  report.precached = [...installed.stores.get("dealgo-v1").keys()];

  // A write is never touched, however offline we are.
  const writing = makeWorker({ online: false });
  let intercepted = false;
  writing.listeners.fetch({
    request: { method: "POST", url: "https://app.test/sync", mode: "cors" },
    respondWith: () => { intercepted = true; },
  });
  report.postIntercepted = intercepted;

  // A page seen before comes back, flagged as the stored copy it is.
  const revisiting = makeWorker({
    online: false,
    cached: { "https://app.test/feed": '<html><body hx-boost="true">the feed</body></html>' },
  });
  const stored = await answerFor(revisiting, { method: "GET", url: "https://app.test/feed", mode: "navigate" });
  report.storedCopy = await stored.text();

  // A page never seen names itself on the offline page.
  const unseen = makeWorker({ online: false });
  const missing = await answerFor(unseen, { method: "GET", url: "https://app.test/channels/9", mode: "navigate" });
  report.missingPage = await missing.text();

  // A thumbnail never seen gets a drawn placeholder rather than a broken icon.
  const noImage = makeWorker({ online: false });
  const placeholder = await answerFor(noImage, { method: "GET", url: "https://i.ytimg.com/vi/abc/hq.jpg", mode: "no-cors" });
  report.placeholder = {
    status: placeholder.status,
    type: placeholder.headers["Content-Type"],
    marked: placeholder.headers["X-Dealgo-Placeholder"],
    body: placeholder.body,
  };

  // With a network, nothing is substituted for anything.
  const connected = makeWorker({ online: true });
  const live = await answerFor(connected, { method: "GET", url: "https://app.test/feed", mode: "navigate" });
  report.online = await live.text();

  process.stdout.write(JSON.stringify(report));
}

void main();
