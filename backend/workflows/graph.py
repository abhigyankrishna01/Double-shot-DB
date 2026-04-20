"""
LangGraph workflow — multi-step analytical pipeline with failure explainability.

State machine:
                        ┌──────────────────────────────────────────┐
                        │            (retry)                        │
  planner → sql_generator → evaluator → step_advance               │
                 ↑                           │                      │
                 │       (more_steps)        │                      │
                 └───────────────────────────┘                      │
                                             │ done_success         │
                                     insight_generator → END        │
                                             │ done_failure         │
                                     failure_explainer → END        │
"""

import logging
from langgraph.graph import StateGraph, END

from backend.agents.state import AgentState
from backend.logging_config import safe_log
from backend.agents.planner import planner_agent
from backend.agents.sql_generator import sql_generator_agent
from backend.agents.evaluator import evaluator_agent, route_after_evaluator
from backend.agents.step_advance import step_advance_agent, route_after_step_advance
from backend.agents.insight_generator import insight_generator_agent
from backend.agents.failure_explainer import failure_explainer_agent

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_agent)
    graph.add_node("sql_generator", sql_generator_agent)
    graph.add_node("evaluator", evaluator_agent)
    graph.add_node("step_advance", step_advance_agent)
    graph.add_node("insight_generator", insight_generator_agent)
    graph.add_node("failure_explainer", failure_explainer_agent)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "sql_generator")
    graph.add_edge("sql_generator", "evaluator")

    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator,
        {"retry": "sql_generator", "advance": "step_advance"},
    )

    graph.add_conditional_edges(
        "step_advance",
        route_after_step_advance,
        {
            "more_steps": "sql_generator",
            "done_success": "insight_generator",
            "done_failure": "failure_explainer",
        },
    )

    graph.add_edge("insight_generator", END)
    graph.add_edge("failure_explainer", END)
    return graph


_compiled_graph = _build_graph().compile()


async def run_analysis(
    question: str,
    schema_context: str,
    conversation_history: str = "",
) -> AgentState:
    logger.info("graph_start", extra={"question": safe_log(question)})

    initial_state: AgentState = {
        "question": question,
        "schema_context": schema_context,
        "conversation_history": conversation_history,
        "plan": "",
        "plan_steps": [],
        "current_step_index": 0,
        "generated_sql": "",
        "db_results": [],
        "step_results": [],
        "insight": "",
        "confidence_score": 0.0,
        "confidence_label": "None",
        "error_message": "",
        "retry_count": 0,
        "total_retries": 0,
    }

    final_state = await _compiled_graph.ainvoke(initial_state)
    logger.info(
        "graph_done",
        extra={
            "steps_run": len(final_state.get("step_results", [])),
            "confidence": final_state.get("confidence_label"),
            "total_retries": final_state.get("total_retries", 0),
        },
    )
    return final_state
