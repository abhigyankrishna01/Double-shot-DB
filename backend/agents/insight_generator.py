"""
Insight Generator Agent: synthesizes all step_results into one executive insight.
Adds confidence scoring to state. Prompt loaded from prompts/insight_generator.txt.
"""

import json
import logging
from openai import AsyncAzureOpenAI
from backend.config import get_settings
from backend.agents.state import AgentState, StepResult
from backend.agents.confidence import compute_confidence
from backend.prompts import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("insight_generator")
_MAX_ROWS_PER_STEP = 30


def _build_client() -> AsyncAzureOpenAI:
    s = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )


def _format_steps(step_results: list[StepResult]) -> str:
    parts: list[str] = []
    for i, sr in enumerate(step_results, 1):
        part = f"--- Step {i}: {sr['step']} ---\n"
        if sr["error"]:
            part += f"Error: {sr['error']}\n"
        else:
            truncated = sr["results"][: _MAX_ROWS_PER_STEP]
            part += f"SQL: {sr['sql']}\n"
            part += (
                f"Results ({len(sr['results'])} rows, showing {len(truncated)}):\n"
                + json.dumps(truncated, indent=2, default=str)
            )
        parts.append(part)
    return "\n\n".join(parts)


async def insight_generator_agent(state: AgentState) -> AgentState:
    score, label = compute_confidence(state)

    step_results = state.get("step_results", [])
    successful = [sr for sr in step_results if not sr["error"]]

    if not successful:
        # Should not normally reach here — failure_explainer handles this path
        return {
            **state,
            "insight": "No results were returned. Please refine your question.",
            "confidence_score": score,
            "confidence_label": label,
        }

    client = _build_client()
    settings = get_settings()

    logger.info(
        "insight_generator_start",
        extra={
            "total_steps": len(step_results),
            "successful": len(successful),
            "confidence": label,
        },
    )

    response = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Original question: {state['question']}\n\n"
                    + _format_steps(step_results)
                ),
            },
        ],
        temperature=0.4,
        max_tokens=600,
    )

    insight = response.choices[0].message.content.strip()
    logger.info(
        "insight_generator_done",
        extra={"confidence_score": score, "confidence_label": label},
    )

    return {
        **state,
        "insight": insight,
        "confidence_score": score,
        "confidence_label": label,
    }
