# Autonomous SQL Data Analyst Agent

A production-grade, autonomous agent that converts natural-language questions into safe, multi-step SQL analyses and returns synthesized insights — built on **LangGraph**, **FastAPI**, **Azure OpenAI**, and **PostgreSQL**.

The agent plans, generates, executes, self-corrects, and explains — all behind a strict read-only security boundary.

---

## Features

- **Multi-step analytical reasoning** — a planner decomposes each question into ordered sub-tasks; a SQL generator, executor, and evaluator run each step with a per-step retry budget.
- **Triple-layer SQL safety** — regex validation + `sqlparse` AST scan + PostgreSQL read-only role.
- **Schema-aware prompting** — table columns *and* foreign-key relationships are injected into every prompt to eliminate hallucinated joins.
- **Multi-turn conversations** — session-scoped history with TTL; follow-up questions retain context.
- **Observability** — structured JSON logs at every node (planner, generator, evaluator, executor, cache, graph).
- **Query caching** — async TTL LRU cache (SHA-256 keyed on normalized SQL).
- **Smart Streamlit UI** — per-step result tabs, auto-detected line/bar/area charts, confidence badges.
- **Rate limited & input-bounded** — `slowapi` (15/min default) + max-question-length guard.
- **Zero-setup deployment** — `docker compose up` brings up db + backend + frontend with seeded e-commerce data.

---

## Architecture

```
User Question
     │
     ▼
[FastAPI /analyze]
     │
     ▼
[LangGraph StateGraph]
  planner_agent            (JSON plan → plan_steps[])
       │
  sql_generator_agent ◄──── retry (per-step, MAX_RETRIES=3)
       │                         ▲
  evaluator_agent ───────────────┘ (on SQL error)
       │ (advance)
  step_advance_agent       (commit result, increment step_index)
       │
  ┌────┴─────────────────────────────────────────┐
  │ more_steps   → sql_generator (next step)     │
  │ done_success → insight_generator             │
  │ done_failure → failure_explainer             │
  └──────────────────────────────────────────────┘
       │
     ▼
Response → Streamlit UI (step tabs, smart charts, confidence)
```

### Stack

| Layer          | Technology                         |
|----------------|------------------------------------|
| Backend API    | FastAPI 0.111 + uvicorn            |
| Agent Engine   | LangGraph 0.1.4                    |
| LLM            | Google Gemini 2.5 Flash (via OpenAI-compatible endpoint)           |
| Database       | PostgreSQL 16 (asyncpg)            |
| ORM            | SQLAlchemy 2.0 async               |
| SQL Validation | regex + sqlparse AST               |
| Cache          | async in-memory TTL (LRU)          |
| Logging        | Python logging + JSONFormatter     |
| Frontend       | Streamlit 1.35                     |
| Deployment     | Docker + docker compose            |

---

## Repository Layout

```
backend/
  config.py                — pydantic-settings (admin + read-only DSNs)
  logging_config.py        — JSON formatter, safe_log()
  main.py                  — FastAPI app, /health /schema /analyze /conversation
  agents/
    state.py               — AgentState + StepResult TypedDicts
    planner.py             — JSON plan with plan_steps[]
    sql_generator.py       — step-aware, retry-aware
    evaluator.py           — executes SQL + routes retry/advance
    step_advance.py        — commits step, resets retry_count
    insight_generator.py   — synthesizes all step_results
    failure_explainer.py   — graceful all-step-failed path
  tools/
    sql_executor.py        — readonly + regex + sqlparse + cache
    schema_inspector.py    — columns + FK relationships
    query_cache.py         — async TTL LRU cache
  workflows/graph.py       — LangGraph StateGraph
  conversation/store.py    — multi-turn session store
  db/connection.py         — SQLAlchemy engine factories

frontend/app.py            — Streamlit UI

sql/sample_db.sql          — e-commerce schema + seed + readonly_user role

tests/                     — 65 unit + integration tests (pytest-asyncio, httpx)
docker-compose.yml         — full stack
.env.example               — template for required secrets
```

---

## Quick Start

### Prerequisites

- Docker Desktop (Docker Engine 24+ and Compose v2)
- A Google Gemini API key (free tier at https://aistudio.google.com/apikey)

### 1. Clone and configure

```bash
git clone <your-fork-url>.git
cd "Autonomous SQL Data Analyst Agent"
cp .env.example .env
```

Edit `.env` and set your Gemini API key:

```env
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

Get a free key at https://aistudio.google.com/apikey.

For local Docker dev, leave `READONLY_DATABASE_URL` commented out — `docker-compose.yml` constructs it automatically from the bundled `db` service. For cloud deploys (Neon, Render, Supabase), set `READONLY_DATABASE_URL` to your provider's connection string — `?sslmode=require` is fine, the app handles it.

### 2. Start the stack

```bash
docker compose up -d --build
```

This boots three containers:

| Service  | URL                    | Purpose                      |
|----------|------------------------|------------------------------|
| db       | localhost:5432         | PostgreSQL 16 (auto-seeded)  |
| backend  | http://localhost:8000  | FastAPI (`/docs` for Swagger)|
| frontend | http://localhost:8501  | Streamlit UI                 |

### 3. Use it

Open **http://localhost:8501** and ask questions like:

- *"What are the top 5 products by revenue?"*
- *"Which countries have the most customers?"*
- *"How does that compare with last year?"* (multi-turn follow-up)

### 4. Tail logs / tear down

```bash
docker compose logs -f backend
docker compose logs -f frontend

docker compose down            # stop containers
docker compose down -v         # stop + wipe DB volume
```

---

## API Reference

### `GET /health`
Returns service status.

### `GET /schema`
Returns the schema context (tables, columns, FK relationships) injected into every prompt.

### `POST /analyze`

```json
{
  "question": "What are the top 5 products by revenue?",
  "session_id": ""
}
```

Response:

```json
{
  "session_id": "…",
  "question": "…",
  "plan": "…",
  "plan_steps": ["…"],
  "step_results": [{ "step": "…", "sql": "…", "results": [...], "error": "" }],
  "insight": "…",
  "confidence_score": 0.87,
  "confidence_label": "High",
  "error_message": "",
  "retry_count": 0,
  "total_retries": 1
}
```

### `GET /conversation/{session_id}`
Full turn history for a session.

### `DELETE /conversation/{session_id}`
Clears session history.

---

## Configuration

All runtime knobs live in `.env`:

| Variable               | Default       | Meaning                                    |
|------------------------|---------------|--------------------------------------------|
| `MAX_RETRIES`          | 3             | Per-step SQL generation retry budget       |
| `MAX_STEPS`            | 4             | Cap on plan_steps per question             |
| `MAX_QUERY_ROWS`       | 500           | Auto-injected LIMIT when SQL omits one     |
| `MAX_QUESTION_LENGTH`  | 500           | Rejected before entering the graph         |
| `RATE_LIMIT`           | `15/minute`   | Per-IP via slowapi                         |

---

## Security

- `readonly_user` PostgreSQL role: `GRANT SELECT` only — **the true enforcement boundary**.
- `sql_executor.py` connects via the read-only DSN exclusively.
- **Layer 1** — regex strips comments, blocks mutation keywords, rejects statement stacking.
- **Layer 2** — `sqlparse` AST scan catches DDL/non-SELECT DML that regex may miss.
- **Layer 3** — PostgreSQL role permissions.
- Raw DB errors never reach the client (`_sanitize_error` at API boundary).
- Generic 500 handler for uncaught exceptions — no stack traces leaked.
- User input truncated in logs (`safe_log()` caps at 120 chars); prompt content is never logged.
- CORS restricted to `GET/POST/DELETE` — tighten `allow_origins` before public deployment.
- `.gitignore` blocks `.env` and variants.

---

## Development

### Run tests

```bash
pip install -r tests/requirements.txt
pytest
```

65 tests across unit and integration layers — no real LLM or DB required (everything is mocked).

### Run backend locally (without Docker)

```bash
pip install -r backend/requirements.txt
# Start Postgres however you prefer; update POSTGRES_HOST in .env
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Run frontend locally

```bash
pip install -r frontend/requirements.txt
BACKEND_URL=http://localhost:8000 streamlit run frontend/app.py
```

---

## Roadmap

- [ ] Redis-backed `ConversationStore` for multi-worker deployments
- [ ] Redis query cache for multi-worker deployments
- [ ] Pluggable LLM provider (OpenAI, Anthropic, local)
- [ ] Pluggable DB dialect (MySQL, SQL Server, BigQuery)

---

## Deploy to Render

This repo ships with [render.yaml](render.yaml) — a Render Blueprint that provisions:
- The **FastAPI backend** as a Docker web service (`agent-backend`)
- The **Streamlit frontend** as a Docker web service (`agent-frontend`)

The database is **external (Neon)** — Render's free tier does not allow custom role creation via shell, so the read-only role required by this app cannot be provisioned there. Neon's free tier supports it out of the box.

### Steps

**Prerequisite — Neon database (free):**

1. Create a project at https://neon.tech.
2. Open the Neon **SQL Editor** and run the contents of [sql/sample_db.sql](sql/sample_db.sql) — this creates the schema, seeds data, and provisions the `readonly_user` role.
3. From Neon dashboard → **Connection Details** → select the `readonly_user` role → copy the connection string (`postgresql://readonly_user:...@ep-xxx.neon.tech/analyst_db?sslmode=require`).

**Deploy:**

1. Push to GitHub.
2. Render → **New + → Blueprint** → select this repo. It provisions the two web services from `render.yaml`.
3. On `agent-backend`, set these env vars in **Environment**:
   - `GEMINI_API_KEY` — your Gemini key
   - `READONLY_DATABASE_URL` — the Neon URL you copied above
4. On `agent-frontend`, set `BACKEND_URL` to the backend's public URL (e.g. `https://agent-backend.onrender.com`).
5. *(Recommended)* On `agent-backend`, set `ALLOWED_ORIGINS` to the frontend's URL — replaces the wildcard CORS default.
6. Visit the frontend URL → ask a question.

### Notes for free-tier Render

- Free web services sleep after 15 min idle — first request after sleep can take ~30s.
- Neon's free tier puts an inactive DB into "scale-to-zero" — first request after idle wakes it in <1s.
- For multi-worker deployments, replace the in-memory `ConversationStore` and `QueryCache` with the Redis-backed variants (roadmap).

---

## License

MIT
