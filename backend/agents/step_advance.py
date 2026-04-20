"""
Step Advance Agent: commits the current step result, increments the index,
and resets per-step state. Routes to the next step or to the final agent.
"""

import logging
from backend.agents.state import AgentState, StepResult
from backend.config import get_settings

logger = logging.getLogger(__name__)


async def step_advance_agent(state: AgentState) -> AgentState:
    settings = get_settings()
    idx = state.get("current_step_index", 0)
    plan_steps = state.get("plan_steps", [])

    current_step = plan_steps[idx] if plan_steps else state["plan"]
    error = state.get("error_message", "")

    if error and state["retry_count"] >= settings.max_retries:
        error = "Max retries exceeded for this step. Skipping."

    step_result: StepResult = {
        "step": current_step,
        "sql": state.get("generated_sql", ""),
        "results": state.get("db_results", []),
        "error": error,
    }

    accumulated = list(state.get("step_results", [])) + [step_result]
    next_index = idx + 1

    logger.info(
        "step_advance",
        extra={
            "completed_step": idx,
            "next_step": next_index,
            "total_steps": len(plan_steps),
            "had_error": bool(error),
        },
    )

    return {
        **state,
        "step_results": accumulated,
        "current_step_index": next_index,
        "generated_sql": "",
        "db_results": [],
        "error_message": "",
        "retry_count": 0,
        # total_retries is NOT reset — it accumulates across all steps
    }


def route_after_step_advance(state: AgentState) -> str:
    """
    more_steps   → sql_generator    (process the next step)
    done_success → insight_generator
    done_failure → failure_explainer (all steps failed)
    """
    plan_steps = state.get("plan_steps", [])
    if state["current_step_index"] < len(plan_steps):
        return "more_steps"

    successful = [sr for sr in state.get("step_results", []) if not sr["error"]]
    return "done_success" if successful else "done_failure"
