# API Reference (autodoc)

Generated from the code's own docstrings and comments. Not committed — build it:

```bash
.venv/bin/pip install -e '.[docs]'   # pdoc
make docs                             # needs Node for the TypeScript half
```

Then open:

| Reference | Open | Built by |
| --- | --- | --- |
| Python — every module under `dealgo/` | `python/index.html` | [pdoc](https://pdoc.dev) 16, Markdown docstrings |
| Browser scripts — `dealgo/web/ts/*.ts` | `browser/index.html` | [TypeDoc](https://typedoc.org) 0.28 |
| The canvas — `dealgo/web/ts/graph/*.ts` | `canvas/index.html` | TypeDoc, `tsconfig.graph.json` |
| Service worker — `dealgo/web/ts/sw.ts` | `service-worker/index.html` | TypeDoc, worker `tsconfig` |

## How it is set up

- **Python:** `pdoc dealgo --docformat markdown --no-show-source`. Importing `dealgo.config`
  creates the data folder, so `make docs` points `DEALGO_DATA_DIR` at a temporary folder and uses an
  in-memory database.
- **TypeScript:** this folder has its own `package.json` pinning `typedoc` and TypeScript 5.9,
  because the app compiles with TypeScript 7, which TypeDoc cannot read yet. Three configs:
  `typedoc.browser.json` (page scripts, root `tsconfig.json`), `typedoc.canvas.json` (the
  canvas's parts, `tsconfig.graph.json`) and `typedoc.worker.json` (`sw.ts`,
  `tsconfig.sw.json`).

## Writing for it

- Python: a module docstring saying what the module is for and why; docstrings on public functions
  and classes. Markdown works. `#:` comments above attributes become their docs.
- TypeScript: `/** … */` above functions and interfaces.
- Explain *why*. The *what* is in the signature.

The narrative internals are one level up, in [Internal Documentation](../README.md).
