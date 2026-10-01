# Installing as an App

De-Algo can be installed to a phone's home screen or a desktop like an app: **Add to Home Screen** on
iOS, **Install app** on Android and desktop Chrome. It opens in its own window.

**This needs HTTPS** (or `localhost`). Over plain HTTP at a LAN address De-Algo works normally but
installs nothing and caches nothing. Put it behind a reverse proxy with a certificate — see
[Running in Production](Running%20in%20Production.md).

## Offline

**Reading works offline.** Pages you have visited and their thumbnails are kept.

- A page you loaded before comes back, marked as a stored copy.
- A page you never loaded says so by name.
- A thumbnail never cached becomes a *not loaded* tile.
- Panels that cannot refresh keep what they show, tagged **not refreshed — offline**.

**Changes do not.** Marking watched, running, editing — these need the server. A banner appears when
the connection drops, and buttons that cannot work are disabled. Videos stream from YouTube, so they
do not play offline either.

Cached images are capped at a few hundred, and a new version of De-Algo replaces the old cache.

## On a phone

Below tablet width the tabs move into a menu behind the ☰ button. Touch screens get larger targets
and always-visible card actions. It all works with JavaScript off.

**Related:** [The Feed Page](The%20Feed%20Page.md) · [Running in Production](Running%20in%20Production.md)
