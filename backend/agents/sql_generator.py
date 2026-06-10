"""
SQL Generator Agent: converts the current analytical step into a single
PostgreSQL SELECT statement. Prompt loaded from backend/prompts/sql_generator.txt.
"""

import logging
import re
from openai import AsyncOpenAI
from backend.config import get_settings
from backend.agents.state import AgentState
from backend.prompts import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("sql_generator")


def _build_client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(
        api_key=s.gemini_api_key,
        base_url=s.gemini_base_url,
    )


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    return re.sub(r"\n?```$", "", text.strip()).strip()


async def sql_generator_agent(state: AgentState) -> AgentState:
    settings = get_settings()
    client = _build_client()

    plan_steps = state.get("plan_steps", [])
    idx = state.get("current_step_index", 0)
    current_step = plan_steps[idx] if plan_steps else state["plan"]

    logger.info(
        "sql_generator_start",
        extra={"step_index": idx, "step": current_step, "retry": state["retry_count"]},
    )

    user_message = (
        f"Database schema:\n{state['schema_context']}\n\n"
        f"Analytical task (step {idx + 1} of {len(plan_steps)}):\n{current_step}\n\n"
        f"Original question for context: {state['question']}"
    )

    if state.get("error_message") and state["retry_count"] > 0:
        user_message += (
            f"\n\nPrevious SQL attempt:\n{state['generated_sql']}\n"
            f"Execution error:\n{state['error_message']}\n"
            "Fix the SQL to resolve this error."
        )

    response = await client.chat.completions.create(
        model=settings.gemini_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
        max_tokens=1024,
    )

    sql = _strip_fences(response.choices[0].message.content.strip())
    logger.info("sql_generator_done", extra={"step_index": idx, "sql_preview": sql[:120]})
    return {**state, "generated_sql": sql, "error_message": ""}
