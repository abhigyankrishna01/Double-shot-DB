"""
Evaluator Agent: executes the generated SQL via SQLQueryTool and implements
the per-step circuit breaker. Tracks total_retries across all steps.
"""

import logging
from backend.agents.state import AgentState
from backend.tools.sql_tool import SQLQueryTool, SQLQueryInput
from backend.config import get_settings

logger = logging.getLogger(__name__)

_sql_tool = SQLQueryTool()


async def evaluator_agent(state: AgentState) -> AgentState:
    settings = get_settings()
    sql = state.get("generated_sql", "").strip()
    idx = state.get("current_step_index", 0)

    if not sql:
        logger.warning("evaluator_empty_sql", extra={"step_index": idx})
        return {
            **state,
            "db_results": [],
            "error_message": "No SQL was generated.",
            "retry_count": state["retry_count"] + 1,
            "total_retries": state.get("total_retries", 0) + 1,
        }

    result = await _sql_tool.run(
        SQLQueryInput(sql=sql)
    )

    if result.success:
        logger.info(
            "evaluator_success",
            extra={"step_index": idx, "row_count": len(result.data)},
        )
        return {**state, "db_results": result.data, "error_message": ""}

    new_retry = state["retry_count"] + 1
    new_total = state.get("total_retries", 0) + 1
    logger.error(
        "evaluator_sql_error",
        extra={"step_index": idx, "retry": new_retry, "error": result.error},
    )
    return {
        **state,
        "db_results": [],
        "error_message": result.error,
        "retry_count": new_retry,
        "total_retries": new_total,
    }


def route_after_evaluator(state: AgentState) -> str:
    """
    retry   → sql_generator  (same step, error injected)
    advance → step_advance   (commit result and move on)
    """
    settings = get_settings()
    if state["error_message"] and state["retry_count"] < settings.max_retries:
        return "retry"
    return "advance"
