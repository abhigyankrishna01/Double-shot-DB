"""Unit tests for evaluator_agent and route_after_evaluator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.agents.evaluator import evaluator_agent, route_after_evaluator
from backend.agents.state import AgentState


def _state(**kwargs) -> AgentState:
    base: AgentState = {
        "question": "test question",
        "schema_context": "",
        "plan": "",
        "plan_steps": ["find top products"],
        "current_step_index": 0,
        "generated_sql": "SELECT id FROM orders",
        "db_results": [],
        "step_results": [],
        "insight": "",
        "confidence_score": 0.0,
        "confidence_label": "None",
        "conversation_history": "",
        "error_message": "",
        "retry_count": 0,
        "total_retries": 0,
    }
    base.update(kwargs)
    return base


def _tool_result(success: bool, data=None, error=""):
    m = MagicMock()
    m.success = success
    m.data = data or []
    m.error = error
    return m


# ── Success path ──────────────────────────────────────────────────────────────

async def test_evaluator_success_clears_error():
    rows = [{"id": 1, "total": 500.0}]
    with patch("backend.agents.evaluator._sql_tool") as mock_tool:
        mock_tool.run = AsyncMock(return_value=_tool_result(True, data=rows))
        result = await evaluator_agent(_state())

    assert result["db_results"] == rows
    assert result["error_message"] == ""
    assert result["retry_count"] == 0


async def test_evaluator_success_does_not_increment_retries():
    with patch("backend.agents.evaluator._sql_tool") as mock_tool:
        mock_tool.run = AsyncMock(return_value=_tool_result(True, data=[{"x": 1}]))
        result = await evaluator_agent(_state(total_retries=2))

    assert result["total_retries"] == 2  # unchanged on success


# ── Failure path ──────────────────────────────────────────────────────────────

async def test_evaluator_tool_error_increments_retry():
    with patch("backend.agents.evaluator._sql_tool") as mock_tool:
        mock_tool.run = AsyncMock(
            return_value=_tool_result(False, error="column does not exist")
        )
        result = await evaluator_agent(_state(retry_count=1, total_retries=1))

    assert result["error_message"] == "column does not exist"
    assert result["retry_count"] == 2
    assert result["total_retries"] == 2
    assert result["db_results"] == []


async def test_evaluator_empty_sql_sets_error():
    result = await evaluator_agent(_state(generated_sql="  "))
    assert result["error_message"] == "No SQL was generated."
    assert result["retry_count"] == 1
    assert result["total_retries"] == 1


# ── Routing ───────────────────────────────────────────────────────────────────

def test_route_retry_when_error_and_under_limit():
    state = _state(error_message="bad column", retry_count=1)
    assert route_after_evaluator(state) == "retry"


def test_route_advance_on_success():
    state = _state(error_message="", retry_count=0)
    assert route_after_evaluator(state) == "advance"


def test_route_advance_when_retries_exhausted():
    state = _state(error_message="still failing", retry_count=3)
    assert route_after_evaluator(state) == "advance"


def test_route_advance_at_exact_limit():
    # retry_count == max_retries (3) → advance (not retry)
    state = _state(error_message="error", retry_count=3)
    assert route_after_evaluator(state) == "advance"
