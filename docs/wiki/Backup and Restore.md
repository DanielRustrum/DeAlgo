# Backup and Restore

## The complete backup: copy the database

Everything De-Algo knows is in one SQLite file — your canvas, sources, feeds, history, settings and
Google grant. Copy it while De-Algo is stopped:

```bash
make down
docker run --rm -v dealgo_dealgo-data:/data -v "$PWD":/out alpine cp /data/dealgo.sqlite3 /out/
make up
```

Compose names the volume `<project>_dealgo-data` — `dealgo_dealgo-data` by default. Check with
`docker volume ls`.

Outside Docker, copy `./data/dealgo.sqlite3`. To restore, put the file back and start De-Algo.

**This is the only backup that keeps everything.** Use it.

## The setup file: Settings → Back up your setup

Downloads your account's feeds and sources as JSON, along with your [theme](Theming.md). **Load backup** on the same page reads one back.

Restoring **merges**: what the file names is created or updated, matched by each source's and
feed's own identifier, and nothing is deleted. Restoring twice changes nothing the second time.
Sources come back as never checked, so their backfill applies again on the first run.

No credentials are included — no Google grant, no client id or secret.

### What the setup file does not keep yet

It predates the canvas. It does **not** include:

- the canvas itself: [triggers](Nodes/Triggers.md), [filters](Nodes/Filter.md) and their conditions, [sorts](Nodes/Sort.md),
  [tags](Nodes/Tag.md), [Decay](Nodes/Decay.md), [Expire](Nodes/Expire.md), [repositories](Nodes/Repositories.md),
  [augmentations](Nodes/Augmentations.md), [groups](Nodes/Groups.md) and box positions;
- each source's kind and feed address, so **only YouTube channels restore correctly**;
- your item history.

After restoring, sources are wired straight to the feeds they filled, with no triggers — so nothing
runs until you add them again.

## From the command line

```bash
make backup    # writes ./de-algo-backup.json — the same setup file
```

**Related:** [Moving an Instance](Moving%20an%20Instance.md) · [Groups](Nodes/Groups.md)
