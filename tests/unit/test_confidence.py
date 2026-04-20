"""Unit tests for confidence scoring."""

import pytest
from backend.agents.confidence import compute_confidence


def _state(step_results, total_retries=0):
    return {
        "step_results": step_results,
        "total_retries": total_retries,
        # required fields (unused by compute_confidence)
        "question": "", "schema_context": "", "plan": "", "plan_steps": [],
        "current_step_index": 0, "generated_sql": "", "db_results": [],
        "step_results": step_results, "insight": "",
        "confidence_score": 0.0, "confidence_label": "None",
        "conversation_history": "",
        "error_message": "", "retry_count": 0, "total_retries": total_retries,
    }


def _ok(results=None):
    return {"step": "s", "sql": "SELECT 1", "results": results or [{"id": 1}], "error": ""}


def _failed():
    return {"step": "s", "sql": "", "results": [], "error": "query failed"}


def _empty():
    return {"step": "s", "sql": "SELECT 1", "results": [], "error": ""}


# ── No steps ──────────────────────────────────────────────────────────────────

def test_none_label_when_no_steps():
    score, label = compute_confidence(_state([]))
    assert label == "None"
    assert score == 0.0


# ── High confidence ───────────────────────────────────────────────────────────

def test_high_confidence_all_success_no_retries():
    state = _state([_ok(), _ok(), _ok()], total_retries=0)
    score, label = compute_confidence(state)
    assert label == "High"
    assert score >= 0.85


def test_high_confidence_single_step_no_retries():
    score, label = compute_confidence(_state([_ok()], total_retries=0))
    assert label == "High"


# ── Medium confidence ─────────────────────────────────────────────────────────

def test_medium_confidence_with_retries():
    state = _state([_ok()], total_retries=2)
    score, label = compute_confidence(state)
    assert label in ("Medium", "Low")


def test_medium_confidence_with_empty_results():
    state = _state([_ok(), _empty()], total_retries=0)
    score, label = compute_confidence(state)
    assert label in ("Medium", "High")


# ── Low confidence ────────────────────────────────────────────────────────────

def test_low_confidence_all_failed():
    state = _state([_failed(), _failed()], total_retries=6)
    score, label = compute_confidence(state)
    assert label == "Low"
    assert score == 0.0


def test_low_confidence_partial_failure_heavy_retries():
    state = _state([_ok(), _failed()], total_retries=5)
    score, label = compute_confidence(state)
    assert label in ("Low", "Medium")


# ── Score bounds ──────────────────────────────────────────────────────────────

def test_score_never_exceeds_one():
    score, _ = compute_confidence(_state([_ok()] * 5, total_retries=0))
    assert score <= 1.0


def test_score_never_below_zero():
    score, _ = compute_confidence(_state([_failed()] * 5, total_retries=99))
    assert score >= 0.0
