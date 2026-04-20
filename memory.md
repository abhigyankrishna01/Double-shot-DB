# Autonomous SQL Data Analyst Agent — Memory Log

## Architecture Overview (v2)

```
User Question
     │
     ▼
[FastAPI /analyze]  ←  JSON structured logs (logging_config.py)
     │
     ▼
[LangGraph Graph]
  planner_agent          (JSON plan → plan_steps list)
       │
  sql_generator_agent ◄──── retry (per-step, max 3)
       │                         ▲
  evaluator_agent ───────────────┘ (on SQL error)
       │ (advance)
  step_advance_agent     (commit result, increment step_index, reset retry_count)
       │
  ┌────┴────────────────────────────────────────────┐
  │ more_steps → sql_generator (next step)          │
  │ done       → insight_generator                  │
  └─────────────────────────────────────────────────┘
       │
  insight_generator_agent  (synthesizes ALL step_results)
       │
     ▼
Response → Streamlit UI (tabs per step, smart chart detection)
```

## Stack

| Layer          | Technology                         |
|----------------|------------------------------------|
| Backend API    | FastAPI 0.111                      |
| Agent Engine   | LangGraph 0.1.4                    |
| LLM            | Azure OpenAI GPT-4o-mini           |
| Database       | PostgreSQL 16 (asyncpg)            |
| ORM            | SQLAlchemy 2.0 async               |
| SQL Validation | regex + sqlparse AST               |
| Result Cache   | Async in-memory TTL (QueryCache)   |
| Logging        | Python logging + JSONFormatter     |
| Frontend       | Streamlit 1.35                     |
| Deployment     | Docker + docker-compose            |

## Module Structure

```
backend/
  config.py               — pydantic-settings, admin + readonly DSNs
  logging_config.py       — JSONFormatter, configure_logging()          [NEW]
  main.py                 — FastAPI app, /health /schema /analyze
  agents/
    state.py              — AgentState + StepResult TypedDicts           [UPDATED]
    planner.py            — Planner Agent → JSON plan with steps         [UPDATED]
    sql_generator.py      — SQL Generator (step-aware, retry-aware)      [UPDATED]
    evaluator.py          — Evaluator + route_after_evaluator()          [UPDATED]
    step_advance.py       — Step commit + index advance + routing        [NEW]
    insight_generator.py  — Synthesizes all step_results                 [UPDATED]
  tools/
    sql_executor.py       — Readonly executor + regex + sqlparse + cache [UPDATED]
    schema_inspector.py   — Columns + FK relationships → LLM context     [UPDATED]
    query_cache.py        — Async TTL LRU cache (128 entries, 5 min TTL) [NEW]
  workflows/
    graph.py              — LangGraph StateGraph (multi-step loop)       [UPDATED]
  db/
    connection.py         — SQLAlchemy engine factories (readonly/admin)
frontend/
  app.py                  — Streamlit: tabs, smart chart detection        [UPDATED]
sql/
  sample_db.sql           — E-commerce schema + seed + readonly role
docker-compose.yml        — Full stack: zero manual setup
```

## Security Design

- `readonly_user` PostgreSQL role: GRANT SELECT only, no DDL/DML (true boundary)
- `sql_executor.py` uses ONLY readonly DSN — never admin DSN
- Validation layer 1: regex strips comments, blocks mutation keywords
- Validation layer 2: sqlparse AST scans for DDL tokens + non-SELECT DML
- Both layers raise `DisallowedStatementError` before DB is contacted

## Agent State (TypedDict v2)

```python
StepResult:
  step           str
  sql            str
  results        list[dict]
  error          str

AgentState:
  question             str
  schema_context       str        # table + columns + FK relationships
  plan                 str        # plan summary (display)
  plan_steps           list[str]  # ordered analytical sub-tasks
  current_step_index   int        # 0-based, incremented by step_advance
  generated_sql        str        # current step's SQL
  db_results           list[dict] # current step's results
  step_results         list[StepResult]  # all committed step results
  insight              str
  error_message        str
  retry_count          int        # resets to 0 after each step_advance
```

## Multi-Step Execution Flow

1. `planner_agent` → `response_format: json_object` → parses `plan_steps[]`
2. `sql_generator_agent` reads `plan_steps[current_step_index]` as the task
3. `evaluator_agent` executes, on error increments `retry_count`
4. `route_after_evaluator`:
   - error AND retry_count < MAX_RETRIES → `retry` → sql_generator
   - otherwise → `advance` → step_advance
5. `step_advance_agent` commits result, increments index, resets retry_count
6. `route_after_step_advance`:
   - more steps remain → `more_steps` → sql_generator
   - all done → `done` → insight_generator
7. `insight_generator_agent` synthesizes ALL `step_results` into one insight

## Circuit Breaker (per-step)

- MAX_RETRIES = 3 (env: MAX_RETRIES)
- retry_count is reset to 0 by step_advance_agent on each step transition
- Exhausted retries on a step → graceful skip + move to next step
- Insight generator skips errored steps when building context

## Observability

- All agents, tools, and workflow emit structured JSON logs
- Fields: `ts`, `level`, `logger`, `msg`, + domain-specific extras
- Key log events:
  - `planner_start`, `planner_done`
  - `sql_generator_start`, `sql_generator_done`
  - `evaluator_success`, `evaluator_sql_error`
  - `step_advance`
  - `insight_generator_start`, `insight_generator_done`
  - `query_cache hit`, `executing_query`, `query_success`, `query_failed`
  - `graph_start`, `graph_done`

## Caching

- `query_cache.py` — async-safe dict with asyncio.Lock
- Key: SHA-256 of normalized SQL
- TTL: 300s, max 128 entries
- LRU eviction when full
- Hit logged as `query_cache hit`

## Schema-Aware Prompting

- `schema_inspector.py` queries `information_schema` for columns AND FK constraints
- Output format injected into every agent prompt:
  ```
  Table: orders
  Columns:
    - order_id (integer, NOT NULL)
    - customer_id (integer, NULL)
    ...
  Relationships:
    - orders.customer_id → customers.customer_id
  ```

## Completed Components

- [x] logging_config.py (JSON structured logging)
- [x] query_cache.py (async TTL cache)
- [x] StepResult TypedDict + updated AgentState
- [x] schema_inspector.py (columns + FK relationships)
- [x] sql_executor.py (regex + sqlparse dual validation + cache integration)
- [x] planner.py (JSON output, plan_steps list)
- [x] sql_generator.py (step-aware, logging)
- [x] evaluator.py (logging, route_after_evaluator)
- [x] step_advance.py (NEW: multi-step state machine node)
- [x] insight_generator.py (synthesizes all step_results)
- [x] workflows/graph.py (multi-step loop wired)
- [x] main.py (logging init, updated response model)
- [x] frontend/app.py (tabs per step, smart charts)
- [x] requirements.txt (sqlparse added)

## Test Suite

```
tests/conftest.py              — fake env vars + settings lru_cache reset
tests/unit/test_sql_executor.py  — 25 cases: stacking, regex, sqlparse, enforce_limit
tests/unit/test_query_cache.py   — 11 cases: miss/hit/TTL/normalisation/concurrency
tests/unit/test_evaluator.py     — 8 cases: success/error/routing
tests/unit/test_confidence.py    — 10 cases: all label paths, score bounds
tests/integration/test_api.py    — 11 cases: response shape, sessions, error sanitisation
pytest.ini                       — asyncio_mode=auto
tests/requirements.txt           — pytest==8.2.1, pytest-asyncio==0.23.7, httpx==0.27.0
```

Run: `pip install -r tests/requirements.txt && pytest`

## Multi-Turn Conversation History

```
backend/conversation/store.py   — ConversationStore: TTL=1h, max 20 turns, 5 injected
```

Flow:
1. `POST /analyze` accepts optional `session_id` (UUID string)
2. Empty → uuid4 generated; provided → existing history loaded
3. `format_for_prompt()` injects last 5 Q&A turns into planner user message
4. After analysis → turn appended to store
5. `session_id` always returned so frontend carries it forward

New API endpoints:
- `GET /conversation/{session_id}` → full turn history
- `DELETE /conversation/{session_id}` → clear and start over

Frontend: `st.session_state` carries `session_id` and local history; collapsible
history panel above input shows each turn with confidence badge.

## Pending Tasks

- [ ] Redis-backed ConversationStore for multi-worker deployments
- [ ] Redis query cache option for multi-worker deployments

## Architecture Decisions

| Decision | Rationale |
|---|---|
| `response_format: json_object` in planner | Prevents markdown-wrapped JSON, ensures parseable output |
| Per-step retry_count reset | Each step gets its own MAX_RETRIES budget; one bad step doesn't consume all retries |
| step_advance as separate node | Clean separation: evaluation (did it work?) vs. progression (what's next?) |
| Graceful step skip vs. full abort | Multi-step questions can partially succeed; partial insight > total failure |
| sqlparse as 2nd validation layer | Catches DDL tokens in nested/obfuscated statements that regex misses |
| FK relationships in schema context | #1 failure mode in LLM SQL: wrong joins. Explicit FKs prevent hallucination |
| QueryCache SHA-256 keyed on normalized SQL | Identical queries from retry loop get cache hits |

## Security Controls

| Control | Implementation | File |
|---|---|---|
| Secrets never in code | pydantic-settings reads from `.env` | `config.py` |
| `.env` never committed | `.gitignore` blocks `.env` and variants | `.gitignore` |
| Docker has no hardcoded secrets | Uses `env_file: .env` only | `docker-compose.yml` |
| SQL validation layer 1 | Stacking check (`;` stripped), regex mutation keywords | `sql_executor.py` |
| SQL validation layer 2 | sqlparse AST: DDL/non-SELECT DML tokens | `sql_executor.py` |
| SQL validation layer 3 | PostgreSQL read-only role (SELECT only) | `sql/sample_db.sql` |
| Raw DB errors never reach frontend | `_sanitize_error()` at API boundary | `main.py` |
| Stack traces never reach client | `@app.exception_handler(Exception)` returns generic 500 | `main.py` |
| User input truncated in logs | `safe_log()` caps at 120 chars | `logging_config.py` |
| Prompt content not logged | Only metadata (step_count, confidence, etc.) | all agents |
| CORS configured | `CORSMiddleware` on GET/POST only | `main.py` |
| Rate limiting | `slowapi` 15/min per IP (configurable) | `main.py`, `config.py` |
| Question length guard | `MAX_QUESTION_LENGTH=500`, rejected before graph | `main.py`, `config.py` |
| Plan steps cap | `MAX_STEPS=4`, truncated in planner | `planner.py`, `config.py` |

## Change Log

| Date       | Change |
|------------|--------|
| 2026-04-20 | Initial full build: all agents, tools, workflow, API, frontend, Docker |
| 2026-04-20 | v2 upgrade: observability, schema-aware prompting, sqlparse, multi-step execution, caching, smart charts |
| 2026-04-20 | v3 security hardening: .gitignore, CORS, semicolon stacking block, safe_log(), error sanitization, generic exception handler, question length guard |
