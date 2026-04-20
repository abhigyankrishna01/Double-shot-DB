"""
Integration tests — full FastAPI app wiring, mocking only the LLM + DB calls.
Tests: request validation, response schema, error sanitization, session handling.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from backend.main import app

MOCK_SCHEMA = (
    "Table: orders\nColumns:\n  - order_id (integer, NOT NULL)\n"
    "  - customer_id (integer, NULL)\n\n"
    "Table: customers\nColumns:\n  - customer_id (integer, NOT NULL)\n"
    "  - name (varchar, NOT NULL)\n"
    "Relationships:\n  - orders.customer_id → customers.customer_id"
)

_BASE_STATE = {
    "question": "Top 5 products by revenue?",
    "plan": "Find top 5 products by total revenue",
    "plan_steps": ["Find top 5 products by total revenue using order_items"],
    "step_results": [
        {
            "step": "Find top 5 products by total revenue using order_items",
            "sql": "SELECT p.name, SUM(oi.unit_price * oi.quantity) AS revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.name ORDER BY revenue DESC LIMIT 5",
            "results": [
                {"name": "Smartwatch", "revenue": 399.98},
                {"name": "Standing Desk", "revenue": 349.99},
            ],
            "error": "",
        }
    ],
    "insight": "The top product is Smartwatch with $399.98 in revenue.",
    "confidence_score": 1.0,
    "confidence_label": "High",
    "error_message": "",
    "retry_count": 0,
    "total_retries": 0,
    "conversation_history": "",
}


@pytest_asyncio.fixture
async def client():
    with patch(
        "backend.main.get_schema_context",
        new_callable=AsyncMock,
        return_value=MOCK_SCHEMA,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac


# ── Health & schema ───────────────────────────────────────────────────────────

async def test_health_returns_ok(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_schema_endpoint_returns_string(client: AsyncClient):
    resp = await client.get("/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "schema" in body
    assert isinstance(body["schema"], str)
    assert len(body["schema"]) > 0


# ── Successful analysis ───────────────────────────────────────────────────────

async def test_analyze_success_response_shape(client: AsyncClient):
    with patch("backend.main.run_analysis", new_callable=AsyncMock, return_value=_BASE_STATE):
        resp = await client.post("/analyze", json={"question": "Top 5 products by revenue?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["insight"] == _BASE_STATE["insight"]
    assert data["confidence_label"] == "High"
    assert data["confidence_score"] == 1.0
    assert len(data["step_results"]) == 1
    assert data["plan_steps"] == _BASE_STATE["plan_steps"]
    assert "session_id" in data


async def test_analyze_returns_session_id(client: AsyncClient):
    with patch("backend.main.run_analysis", new_callable=AsyncMock, return_value=_BASE_STATE):
        resp = await client.post("/analyze", json={"question": "Top 5 products?"})

    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    assert isinstance(session_id, str)
    assert len(session_id) == 36  # UUID4 format


async def test_second_request_same_session_builds_history(client: AsyncClient):
    state_turn2 = {
        **_BASE_STATE,
        "question": "How does that compare with last year?",
        "insight": "Compared to last year, revenue increased by 15%.",
    }

    with patch("backend.main.run_analysis", new_callable=AsyncMock, return_value=_BASE_STATE) as mock_run:
        r1 = await client.post("/analyze", json={"question": "Top 5 products?"})
        session_id = r1.json()["session_id"]

        mock_run.return_value = state_turn2
        r2 = await client.post(
            "/analyze",
            json={"question": "How does that compare with last year?", "session_id": session_id},
        )

    assert r2.status_code == 200
    # run_analysis must have been called with non-empty conversation_history on the second turn
    _, second_call_kwargs = mock_run.call_args_list[1]
    history = second_call_kwargs.get("conversation_history", "")
    assert "Top 5 products?" in history or len(history) > 0


# ── Request validation ────────────────────────────────────────────────────────

async def test_empty_question_returns_400(client: AsyncClient):
    resp = await client.post("/analyze", json={"question": "   "})
    assert resp.status_code == 400


async def test_question_too_long_returns_400(client: AsyncClient):
    resp = await client.post("/analyze", json={"question": "x" * 501})
    assert resp.status_code == 400


async def test_missing_question_field_returns_422(client: AsyncClient):
    resp = await client.post("/analyze", json={})
    assert resp.status_code == 422


# ── Error sanitization ────────────────────────────────────────────────────────

async def test_raw_db_error_is_not_exposed(client: AsyncClient):
    state_with_db_error = {
        **_BASE_STATE,
        "step_results": [
            {
                **_BASE_STATE["step_results"][0],
                "error": 'relation "nonexistent_table" does not exist\nLINE 1: SELECT * FROM nonexistent_table',
            }
        ],
        "error_message": 'relation "nonexistent_table" does not exist',
    }
    with patch("backend.main.run_analysis", new_callable=AsyncMock, return_value=state_with_db_error):
        resp = await client.post("/analyze", json={"question": "Show data?"})

    assert resp.status_code == 200
    body_str = resp.text
    assert "nonexistent_table" not in body_str
    assert "LINE 1" not in body_str


async def test_unhandled_exception_returns_500_without_stacktrace(client: AsyncClient):
    with patch("backend.main.run_analysis", new_callable=AsyncMock, side_effect=RuntimeError("internal boom")):
        resp = await client.post("/analyze", json={"question": "trigger error"})

    assert resp.status_code == 500
    body = resp.json()
    assert "detail" in body
    assert "boom" not in body["detail"]   # internal error detail must not leak
    assert "Traceback" not in resp.text


# ── Conversation endpoint ─────────────────────────────────────────────────────

async def test_get_conversation_history_empty_for_new_session(client: AsyncClient):
    resp = await client.get("/conversation/unknown-session-id")
    assert resp.status_code == 200
    assert resp.json()["history"] == []


async def test_get_conversation_history_after_analysis(client: AsyncClient):
    with patch("backend.main.run_analysis", new_callable=AsyncMock, return_value=_BASE_STATE):
        r = await client.post("/analyze", json={"question": "Top products?"})
    session_id = r.json()["session_id"]

    resp = await client.get(f"/conversation/{session_id}")
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert len(history) == 1
    assert history[0]["question"] == "Top products?"
    assert "insight" in history[0]
