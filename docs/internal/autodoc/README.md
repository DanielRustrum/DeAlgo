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
| Browser scripts — `dealgo/web/ts/`, folders of parts included | `browser/index.html` | [TypeDoc](https://typedoc.org) 0.28 |
| Service worker — `dealgo/web/ts/sw.ts` | `service-worker/index.html` | TypeDoc, worker `tsconfig` |

## How it is set up

- **Python:** `pdoc dealgo --docformat markdown --no-show-source`. Importing `dealgo.config`
  creates the data folder, so `make docs` points `DEALGO_DATA_DIR` at a temporary folder and uses an
  in-memory database.
- **TypeScript:** this folder has its own `package.json` pinning `typedoc` and TypeScript 5.9,
  because the app compiles with TypeScript 7, which TypeDoc cannot read yet. Two configs:
  `typedoc.browser.json` (every page script, through this folder's `tsconfig.json`, which
  holds the single files and the folders of parts in one program) and `typedoc.worker.json`
  (`sw.ts`, `tsconfig.sw.json`).

## Writing for it

- Python: a module docstring saying what the module is for and why; docstrings on public functions
  and classes. Markdown works. `#:` comments above attributes become their docs.
- TypeScript: `/** … */` above functions and interfaces.
- Every class and function has one. Names starting with `_` are private: the reference leaves them
  out, but their docstrings are there for whoever reads the source.
- Inline `#` / `//` comments go above a step whose purpose is not obvious from the code — not on
  every line.
- Explain *why*. The *what* is in the signature.

The narrative internals are one level up, in [Internal Documentation](../README.md).
