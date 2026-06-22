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
- `MDGRAPH_EMBEDDER` — embedder spec (default
  `mdgraph.providers.fastembed_embedder:FastEmbedProvider`). See
  [Configuring the embedding model](#configuring-the-embedding-model) below.
- `MDGRAPH_LLM` — optional dotted `module:Class` LLM extractor (for re-indexing).

### Configuring the embedding model

`MDGRAPH_EMBEDDER` (and the CLI `--embedder`) accept three forms:

- **`fastembed:<model>`** — local fastembed model, no API key. `<model>` is a
  fastembed model name (default `BAAI/bge-small-zh-v1.5`):

  ```bash
  MDGRAPH_EMBEDDER=fastembed:BAAI/bge-m3
  ```

- **`openai:<model>`** — any OpenAI-compatible embeddings endpoint. By default it
  targets a **local Ollama** (`base_url=http://localhost:11434/v1`,
  `api_key=ollama`, `model=nomic-embed-text`) so it works out of the box. To point
  at **cloud OpenAI**, set all three env vars:

  ```bash
  MDGRAPH_EMBEDDER=openai:text-embedding-3-small
  MDGRAPH_EMBED_BASE_URL=https://api.openai.com/v1
  MDGRAPH_EMBED_API_KEY=sk-...
  # MDGRAPH_EMBED_MODEL also overrides the model if the spec omits it
  ```

  The `<model>` in the spec sets the model; `MDGRAPH_EMBED_BASE_URL` /
  `MDGRAPH_EMBED_API_KEY` / `MDGRAPH_EMBED_MODEL` configure the endpoint
  (the spec never carries the base_url or API key, so secrets stay out of
  command history/logs).

- **dotted path** — `module:Class` or `module.Class`, constructed with no args
  (back-compat; the default value above resolves this way).

A bare model name **must** carry a short-name prefix
(`fastembed:BAAI/bge-m3`, not `BAAI/bge-m3`); an unprefixed name is treated as an
import path and fails.

> ⚠️ **RE-INDEX CAVEAT — changing the embedder requires rebuilding the store.**
> The vector table name is `vectors_<sanitized embedder.name>_<dim>`. Switching
> the embedding model (different name or dim — or even the same name over a
> different vector space/endpoint) targets a **different table**, so old vectors
> are not used and queries return nothing or meaningless results. **The query
> embedder MUST match the build embedder.** After changing `MDGRAPH_EMBEDDER`
> (webapp) or `--embedder` (CLI), rebuild:
>
> - CLI: `python -m mdgraph.cli index <paths> --store ./.mdgraph --full --embedder <new spec>`,
>   then `query` with the **same** spec.
> - webapp: re-upload / rebuild the store after changing `MDGRAPH_EMBEDDER`, and
>   keep build + query on the same embedder configuration.

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
