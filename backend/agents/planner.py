"""
Planner Agent: produces a structured JSON analytical plan (plan_steps[])
from the user question and schema context.
Prompts are loaded from backend/prompts/planner.txt for independent versioning.
"""

import json
import logging
from openai import AsyncOpenAI
from backend.config import get_settings
from backend.agents.state import AgentState
from backend.prompts import load_prompt
from backend.logging_config import safe_log

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("planner")


def _build_client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(
        api_key=s.gemini_api_key,
        base_url=s.gemini_base_url,
    )


def _parse_plan(raw: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(raw)
        summary = str(data.get("summary", ""))
        steps = [str(s) for s in data.get("steps", []) if s]
        if not steps:
            raise ValueError("Empty steps list.")
        return summary, steps
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("plan_parse_fallback", extra={"error": str(exc)})
        return raw.strip(), [raw.strip()]


def _build_user_message(state: AgentState) -> str:
    parts: list[str] = []
    if state.get("conversation_history"):
        parts.append(state["conversation_history"])
    parts.append(f"Database schema:\n{state['schema_context']}")
    parts.append(f"User question: {state['question']}")
    return "\n\n".join(parts)


async def planner_agent(state: AgentState) -> AgentState:
    settings = get_settings()
    client = _build_client()

    logger.info("planner_start", extra={"question": safe_log(state["question"])})

    response = await client.chat.completions.create(
        model=settings.gemini_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_message(state),
            },
        ],
        temperature=0.2,
        max_tokens=512,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    summary, steps = _parse_plan(raw)

    # Token guard: cap steps to MAX_STEPS
    if len(steps) > settings.max_steps:
        logger.warning(
            "plan_steps_truncated",
            extra={"original": len(steps), "capped": settings.max_steps},
        )
        steps = steps[: settings.max_steps]

    logger.info("planner_done", extra={"step_count": len(steps), "summary": summary})

    return {
        **state,
        "plan": summary,
        "plan_steps": steps,
        "current_step_index": 0,
        "step_results": [],
        "error_message": "",
        "total_retries": 0,
    }
