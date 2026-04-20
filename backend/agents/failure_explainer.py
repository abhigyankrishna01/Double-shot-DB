"""
Failure Explainer Agent: called when ALL steps fail.
Produces a specific, schema-grounded explanation of why the query could not be
answered — naming actual available columns, FK paths, and rephrasing suggestions.
Prompt loaded from backend/prompts/failure_explainer.txt.
"""

import json
import logging
from openai import AsyncAzureOpenAI
from backend.config import get_settings
from backend.agents.state import AgentState
from backend.agents.confidence import compute_confidence
from backend.prompts import load_prompt
from backend.logging_config import safe_log

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("failure_explainer")


def _build_client() -> AsyncAzureOpenAI:
    s = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )


def _format_failures(step_results: list) -> str:
    parts = []
    for i, sr in enumerate(step_results, 1):
        part = f"Attempt {i}: {sr['step']}\n"
        if sr["sql"]:
            part += f"SQL tried:\n{sr['sql']}\n"
        part += f"Error: {sr['error']}"
        parts.append(part)
    return "\n\n".join(parts)


async def failure_explainer_agent(state: AgentState) -> AgentState:
    score, label = compute_confidence(state)  # will be 0.0, "None" or "Low"
    client = _build_client()
    settings = get_settings()

    step_results = state.get("step_results", [])
    logger.warning(
        "failure_explainer_start",
        extra={"question": safe_log(state["question"]), "failed_steps": len(step_results)},
    )

    failures_text = _format_failures(step_results)

    response = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User question: {state['question']}\n\n"
                    f"Database schema:\n{state['schema_context']}\n\n"
                    f"Failed attempts:\n{failures_text}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=300,
    )

    explanation = response.choices[0].message.content.strip()
    logger.warning("failure_explainer_done", extra={"explanation": explanation[:120]})

    return {
        **state,
        "insight": explanation,
        "confidence_score": score,
        "confidence_label": label,
    }
