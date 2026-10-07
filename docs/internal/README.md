# Internal Documentation

How Pamphlets works inside: the architecture, how the parts fit, why they are built the way they
are, and the algorithms they run. For contributors and maintainers.

Users want the [wiki](../wiki/README.md). Plugin authors want
[Creating A Plugin](../wiki/Creating%20A%20Plugin/GETTING%20STARTED.md).

Every page and section: [Table of Contents](Table%20of%20Contents.md).

## Read first

1. [Architecture](Architecture.md) — the whole system on one page
2. [Repository Layout](Repository%20Layout.md) — where each thing lives
3. [Data Model](Data%20Model.md) — the tables and what they mean

## Systems

| Page | Covers |
| --- | --- |
| [Multi-Tenancy](Multi-Tenancy.md) | Accounts, owners, and how data is kept apart |
| [The Graph](The%20Graph.md) | Boxes, wires, pieces, and how routes are found |
| [The Sync Engine](The%20Sync%20Engine.md) | One run, phase by phase |
| [Triggers and Scheduling](Triggers%20and%20Scheduling.md) | The heartbeat, triggers, and what is due |
| [Reading Windows](Reading%20Windows.md) | Timer, Reset, Alive: when a feed may be read |
| [Sources and Parsing](Sources%20and%20Parsing.md) | Resolving references, reading feeds, newsletters, rate limits |
| [Plugin Runtime](Plugin%20Runtime.md) | The Lua sandbox and its ceilings |
| [Plugin Registry](Plugin%20Registry.md) | Loading, judging, granting, fetching, installing |
| [Publishing and Quota](Publishing%20and%20Quota.md) | Writing to YouTube and keeping the ledger |
| [Web Layer](Web%20Layer.md) | FastAPI, routing, templates, htmx |
| [Frontend](Frontend.md) | TypeScript, SCSS, the canvas, the service worker |
| [Database and Migrations](Database%20and%20Migrations.md) | Engine, sessions, hand-rolled migrations |
| [Security](Security.md) | Auth, sessions, guards, the threat model |
| [Backups and Migration](Backups%20and%20Migration.md) | Per-account backups and whole-instance moves |

## Working on it

| Page | Covers |
| --- | --- |
| [Testing](Testing.md) | The suite, fixtures, harnesses, the guard tests |
| [Building and Releasing](Building%20and%20Releasing.md) | Assets, image, CI, deploy |
| [Design Decisions](Design%20Decisions.md) | The choices that shape everything, and why |
| [Algorithms](Algorithms.md) | Every non-trivial algorithm, in one place |
| [Known Issues](Known%20Issues.md) | What is wrong or missing today |
| [autodoc](autodoc/README.md) | API reference generated from the code |
