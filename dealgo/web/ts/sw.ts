// De-Algo's service worker: what makes the app open, and stay readable, with
// no network.
//
// What this can and cannot do is worth being plain about. De-Algo renders its
// pages on the server from a database that lives there, so "offline" means
// *reading what you have already loaded*: the shell, the styles, the pages you
// have visited, and the thumbnails in them. It does not mean writing. Marking
// something watched, syncing, editing a feed — all of those need the server,
// and offline they fail and say so rather than pretending to have worked. The
// page that renders the result of a write is built server-side, so a queued
// write could not produce the right screen anyway.
//
// The version comes from the query string this worker was registered with, so
// a deploy changes the cache name and everything is fetched afresh.

/// <reference lib="webworker" />

/** This worker's own global scope.
 *
 *  TypeScript types a worker's `self` as WorkerGlobalScope, which knows
 *  nothing of `skipWaiting`, `clients`, or the install and fetch events. The
 *  refinement to ServiceWorkerGlobalScope cannot be expressed without a cast,
 *  so there is exactly one, here, rather than at every use.
 */
function worker(): ServiceWorkerGlobalScope {
  return self as unknown as ServiceWorkerGlobalScope;
}

/** Where the page shell and visited pages live. */
function cacheName(): string {
  const version = new URL(worker().location.href).searchParams.get("v") ?? "dev";
  return `dealgo-${version}`;
}

/** Pictures from other hosts: thumbnails, avatars. Kept apart so it can be capped
 *  without touching the shell, and survives a version change. */
function imageCacheName(): string {
  return "dealgo-images";
}

/** How many remote images to keep. A feed of cards is a few dozen; this
 *  leaves room for scrolling back without growing without limit. */
function imageCacheLimit(): number {
  return 300;
}

/** Fetched on install, so the app opens with no network at all.
 *
 *  Only what is reachable without signing in. With accounts switched on, a
 *  page like "/" answers a signed-out request with a redirect to the login
 *  page — and precaching that would store the login page under the feed's
 *  address, to be served back the first time someone opened the app offline.
 *  Pages are cached when they are actually visited instead. */
function shellUrls(): string[] {
  return [
    "/offline",
    "/login",
    "/static/app.css",
    // The typefaces, or an offline first visit falls back to the system font.
    "/static/fonts/dm-sans-latin-wght-normal.woff2",
    "/static/fonts/fraunces-latin-wght-normal.woff2",
    "/static/htmx.min.js",
    "/static/dialog.js",
    "/static/sections.js",
    "/static/menu.js",
    "/static/focus.js",
    "/static/pwa.js",
    "/manifest.webmanifest",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
  ];
}

/** A picture from somewhere else: a thumbnail, an avatar, a post's image.
 *
 *  Whatever its host. Which services an install reads from is its plugins'
 *  business, and a stored feed with every picture missing does not look
 *  like the feed it was. `imageCacheLimit` is what keeps this bounded. */
function isRemoteImage(request: Request, url: URL): boolean {
  return request.destination === "image" && url.origin !== worker().location.origin;
}

/** Whether a URL is one of the app's own static files. */
function isStaticAsset(url: URL): boolean {
  return url.pathname.startsWith("/static/");
}

/** Requests that must never be served from a cache: they report live state,
 *  and a stale answer would be worse than an honest failure. */
function isLiveState(url: URL): boolean {
  return url.pathname === "/healthz" || url.pathname.startsWith("/api/");
}

/** Cache the app shell, file by file, so one missing file does not fail the install. */
async function precache(): Promise<void> {
  const cache = await caches.open(cacheName());
  // One missing file should not fail the whole install, so they go in
  // individually rather than through addAll.
  await Promise.all(
    shellUrls().map(async (url): Promise<void> => {
      try {
        await cache.add(new Request(url, { cache: "reload" }));
      } catch {
        // A page needing an account, say. The rest of the shell still counts.
      }
    }),
  );
}

/** Delete caches from earlier versions of the worker. */
async function dropOldCaches(): Promise<void> {
  const keep = [cacheName(), imageCacheName()];
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((name): boolean => name.startsWith("dealgo-") && !keep.includes(name))
      .map(async (name): Promise<boolean> => caches.delete(name)),
  );
}

/** Keep the image cache from growing forever: oldest out first. */
async function trimImageCache(): Promise<void> {
  const cache = await caches.open(imageCacheName());
  const entries = await cache.keys();
  const excess = entries.length - imageCacheLimit();
  for (let index = 0; index < excess; index += 1) {
    const oldest = entries[index];
    if (oldest) await cache.delete(oldest);
  }
}

/** Whether this answer belongs in the cache under the address that was asked
 *  for.
 *
 *  A redirected response came from somewhere else: with accounts switched on,
 *  a session that has expired answers every page with the login page. Storing
 *  that under the original address would serve the login page for the feed,
 *  offline, long after signing in again. */
function worthStoring(response: Response): boolean {
  return response.ok && !response.redirected;
}

/** Rebuild an HTML response around changed markup, keeping its headers. */
async function rewrittenHtml(response: Response, edit: (html: string) => string): Promise<Response> {
  const html = await response.text();
  return new Response(edit(html), {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

/** Flag a page that came out of the cache, so it can say so for itself.
 *  The page is perfectly readable; it is simply not necessarily current. */
async function asStoredCopy(response: Response): Promise<Response> {
  return rewrittenHtml(response, (html): string =>
    html.replace("<body ", '<body data-offline-copy="1" '),
  );
}

/** The offline page, told which page it is standing in for. The template
 *  leaves a comment for exactly this. */
async function offlinePageFor(request: Request, cache: Cache): Promise<Response | null> {
  const offline = await cache.match("/offline");
  if (!offline) return null;
  const path = new URL(request.url).pathname;
  return rewrittenHtml(offline, (html): string =>
    html.replace("<!--OFFLINE-PATH-->", escapeHtml(path)),
  );
}

/** Text made safe to put inside HTML. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** The page as it is now, falling back to the copy we have, falling back to
 *  saying which page could not be reached. Fresh wins whenever there is a
 *  network. */
async function pageOrCachedPage(request: Request): Promise<Response> {
  const cache = await caches.open(cacheName());
  try {
    const fresh = await fetch(request);
    if (worthStoring(fresh)) await cache.put(request, fresh.clone());
    return fresh;
  } catch {
    const cached = await cache.match(request);
    if (cached) return asStoredCopy(cached);
    const offline = await offlinePageFor(request, cache);
    if (offline) return offline;
    return new Response("Offline, and this page has not been loaded before.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

/** Assets carry a ?v= hash, so a hit is always the right file. */
async function cachedAssetOrFetch(request: Request): Promise<Response> {
  const cache = await caches.open(cacheName());
  const cached = await cache.match(request);
  if (cached) return cached;

  const fresh = await fetch(request);
  if (fresh.ok) await cache.put(request, fresh.clone());
  return fresh;
}

/** Thumbnails, so a cached feed still looks like a feed. */
async function cachedImageOrFetch(request: Request): Promise<Response> {
  const cache = await caches.open(imageCacheName());
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const fresh = await fetch(request);
    // Cross-origin images come back opaque, which is fine to store and show.
    if (fresh.ok || fresh.type === "opaque") {
      await cache.put(request, fresh.clone());
      void trimImageCache();
    }
    return fresh;
  } catch {
    // Never seen, and no network to see it now. A broken-image icon says
    // nothing useful, so the card gets a tile that explains itself and keeps
    // the layout the shape it was.
    return placeholderImage();
  }
}

/** Stands in for a thumbnail that is not in the cache. Drawn rather than
 *  fetched, for obvious reasons, and in the app's own colours. */
function placeholderImage(): Response {
  const svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" width="320" height="180"',
    ' role="img" aria-label="Image not available offline">',
    '<rect width="320" height="180" fill="#1d212a"/>',
    '<path d="M136 78 L184 78 M160 54 L160 102" stroke="#8b93a5" stroke-width="6"',
    ' stroke-linecap="round" transform="rotate(45 160 78)"/>',
    '<text x="160" y="132" text-anchor="middle" fill="#8b93a5"',
    ' font-family="system-ui, sans-serif" font-size="13">not loaded</text>',
    "</svg>",
  ].join("");
  return new Response(svg, {
    status: 200,
    headers: {
      "Content-Type": "image/svg+xml",
      "Cache-Control": "no-store",
      // So the page can tell a placeholder from a real thumbnail.
      "X-Dealgo-Placeholder": "1",
    },
  });
}

/** Fragments and other reads: fresh if possible, the last copy if not. */
async function freshOrCached(request: Request): Promise<Response> {
  const cache = await caches.open(cacheName());
  try {
    const fresh = await fetch(request);
    if (worthStoring(fresh)) await cache.put(request, fresh.clone());
    return fresh;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw new Error("offline");
  }
}

/** How to answer a GET: from the network, the cache, or not at all (null). */
function routeRequest(request: Request): Promise<Response> | null {
  const url = new URL(request.url);

  if (isRemoteImage(request, url)) return cachedImageOrFetch(request);
  if (url.origin !== worker().location.origin) return null; // not ours to handle
  if (isLiveState(url)) return null;
  if (request.mode === "navigate") return pageOrCachedPage(request);
  if (isStaticAsset(url)) return cachedAssetOrFetch(request);
  return freshOrCached(request);
}

/** Install: cache the shell and take over at once. */
function onInstall(event: ExtendableEvent): void {
  // The new worker takes over at once; caches are versioned, so there is no
  // half-updated state to be careful about.
  event.waitUntil(precache().then((): Promise<void> => worker().skipWaiting()));
}

/** Activate: drop old caches and take control of open pages. */
function onActivate(event: ExtendableEvent): void {
  event.waitUntil(dropOldCaches().then((): Promise<void> => worker().clients.claim()));
}

/** Answer GETs this worker handles; let everything else through untouched. */
function onFetch(event: FetchEvent): void {
  // Writes are the server's business. Letting them through untouched is what
  // makes them fail honestly when there is no network.
  if (event.request.method !== "GET") return;

  const handled = routeRequest(event.request);
  if (handled) event.respondWith(handled);
}

/** The worker's entry point: listen for install, activate and fetch. */
function listenForWorkerEvents(): void {
  worker().addEventListener("install", onInstall);
  worker().addEventListener("activate", onActivate);
  worker().addEventListener("fetch", onFetch);
}

listenForWorkerEvents();
