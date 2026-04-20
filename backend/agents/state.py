from typing import Any
from typing_extensions import TypedDict


class StepResult(TypedDict):
    step: str
    sql: str
    results: list[dict[str, Any]]
    error: str


class AgentState(TypedDict):
    question: str
    schema_context: str          # table columns + FK relationships
    conversation_history: str    # formatted prior turns for planner context
    plan: str                    # plan summary (for display)
    plan_steps: list[str]        # ordered analytical sub-tasks
    current_step_index: int      # 0-based index into plan_steps
    generated_sql: str           # SQL for the current step
    db_results: list[dict[str, Any]]   # results for the current step
    step_results: list[StepResult]     # accumulated across all steps
    insight: str                 # final synthesized insight or failure explanation
    confidence_score: float      # 0.0–1.0 (computed by insight_generator)
    confidence_label: str        # "High" | "Medium" | "Low" | "None"
    error_message: str
    retry_count: int             # per-step, reset by step_advance
    total_retries: int           # cumulative across all steps (never reset)
