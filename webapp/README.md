# mdgraph webapp

A FastAPI backend + React/Vite frontend over the `mdgraph` dual-engine
(vector + knowledge graph) retrieval library.

Layout:

- `backend/` — FastAPI app (`webapp.backend.app:app`), routers under `/api`.
- `frontend/` — React 18 + TypeScript + Vite 5 + Tailwind v3 SPA.

## 0. Build a store first

The webapp reads an existing mdgraph store. Create one from the repo root with
the bundled CLI (real embedder requires the `local` extra: `pip install -e .[local]`):

```bash
# from repo root
python -m mdgraph.cli index examples/ai_kb \
  --store ./.mdgraph \
  --embedder mdgraph.providers.fastembed_embedder:FastEmbedProvider
```

Or run the demo script which builds its own store:

```bash
python examples/run_demo.py
```

`MDGRAPH_STORE` must point the backend at whichever store dir you built
(default `./.mdgraph` relative to the repo root).

## 1. Backend

From the **repo root** (so `src/` is on the path via `pyproject.toml`
`pythonpath=["src"]`):

```bash
pip install -e .            # installs mdgraph + engine deps
pip install fastapi "uvicorn[standard]" httpx    # or: pip install -e .[web]

MDGRAPH_STORE=./.mdgraph \
MDGRAPH_EMBEDDER=mdgraph.providers.fastembed_embedder:FastEmbedProvider \
uvicorn webapp.backend.app:app --reload --port 8000
```

Environment variables:

- `MDGRAPH_STORE` — store dir (default `./.mdgraph`, resolved against repo root).
- `MDGRAPH_EMBEDDER` — dotted `module:Class` embedder
  (default `mdgraph.providers.fastembed_embedder:FastEmbedProvider`).
- `MDGRAPH_LLM` — optional dotted `module:Class` LLM extractor (for re-indexing).

Graceful degradation: if the embedder import/deps fail or the store has no
vectors, `stats` / `graph` / `documents` / `node` still work; `query` / `index`
return HTTP 503 with a clear `detail` message instead of crashing.

### Tests

```bash
# from repo root
python -m pytest webapp/backend/tests
```

Tests build a tiny store in a tmp dir with offline Mock providers
(`DeterministicEmbeddingProvider`, `MockLLMProvider`). No network, no real models.

## 2. Frontend

```bash
cd webapp/frontend
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000
```

Build / typecheck gate:

```bash
npm run build      # tsc -b && vite build
npm test           # vitest run
```

When `webapp/frontend/dist` exists, the backend serves the built SPA at `/`.

## Routes

- `/` Search · `/graph` Graph Explorer · `/stats` Stats · `/doc/:id` Document
