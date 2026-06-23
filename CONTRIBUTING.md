# Contributing to mdgraph

Thanks for your interest in improving **markdown-graph**! This project is a small,
dependency-light engine, so contributions of all sizes are welcome — bug reports,
docs, tests, and features.

## Ground rules

- The **core engine** (`src/mdgraph/`) is **provider-agnostic and offline-deterministic**.
  Keep heavy SDK imports (`fastembed`, `openai`, `anthropic`, …) lazy (inside
  methods), so `import mdgraph` stays cheap and the test suite runs with no network.
- New embedders / LLM extractors go under `src/mdgraph/providers/` behind the
  `EmbeddingProvider` / `LLMProvider` interfaces in `providers/base.py`. Register
  short names in `providers/registry.py` rather than hard-wiring them into callers.
- Tests must pass offline using the Mock providers
  (`DeterministicEmbeddingProvider`, `MockLLMProvider`). No live API calls in CI.

## Dev setup

```bash
git clone https://github.com/Jouryjc/markdown-graph.git
cd markdown-graph
python -m venv .venv && source .venv/bin/activate
pip install -e ".[web,dev]" httpx ruff
```

## Before you open a PR

Run the same gates CI runs:

```bash
ruff check src tests webapp/backend          # lint
pytest tests webapp/backend/tests -q         # engine + web backend tests
```

Frontend changes:

```bash
cd webapp/frontend
npm install
npm run build      # tsc -b && vite build (type gate)
npm test           # vitest run
```

## Pull requests

1. Branch off `main` (`git switch -c feat/<short-name>`).
2. Keep the change focused; add/adjust tests for new behaviour.
3. Write a clear description of **what** and **why**.
4. Make sure `ruff check` and `pytest` are green locally.

## Commit style

Conventional-commit-ish prefixes are used in this repo, e.g.:

```
feat(retrieve): weighted RRF graph/vector fusion
fix(indexer): purge vectors outside the graph transaction
docs: add architecture diagrams to README
```

## Reporting issues

Open a GitHub issue with: what you expected, what happened, and a minimal
reproduction (a tiny markdown corpus + the CLI/API call is ideal).

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
