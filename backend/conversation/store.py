"""
In-memory conversation store keyed by session_id (UUID).
Each session holds an ordered list of ConversationTurn dicts.
TTL-based expiry prevents unbounded memory growth.
"""

import time
import logging
from typing import Optional
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

_MAX_HISTORY_PROMPT_TURNS = 5   # turns injected into the LLM prompt
_MAX_STORED_TURNS = 20          # hard cap per session


class ConversationTurn(TypedDict):
    question: str
    plan: str
    insight: str
    confidence_label: str
    timestamp: float


class ConversationStore:
    def __init__(self, max_turns: int = _MAX_STORED_TURNS, ttl_seconds: int = 3600) -> None:
        self._store: dict[str, list[ConversationTurn]] = {}
        self._last_access: dict[str, float] = {}
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    def _is_expired(self, session_id: str) -> bool:
        ts = self._last_access.get(session_id)
        return ts is not None and (time.monotonic() - ts) > self._ttl

    def _touch(self, session_id: str) -> None:
        self._last_access[session_id] = time.monotonic()

    def get_turns(self, session_id: str) -> list[ConversationTurn]:
        if self._is_expired(session_id):
            self._store.pop(session_id, None)
            self._last_access.pop(session_id, None)
            return []
        self._touch(session_id)
        return list(self._store.get(session_id, []))

    def append(
        self,
        session_id: str,
        question: str,
        plan: str,
        insight: str,
        confidence_label: str,
    ) -> None:
        if session_id not in self._store:
            self._store[session_id] = []
        turns = self._store[session_id]
        turns.append(
            ConversationTurn(
                question=question,
                plan=plan,
                insight=insight,
                confidence_label=confidence_label,
                timestamp=time.time(),
            )
        )
        # Trim to max_turns
        if len(turns) > self._max_turns:
            self._store[session_id] = turns[-self._max_turns :]
        self._touch(session_id)
        logger.info(
            "conversation_turn_saved",
            extra={"session_id": session_id, "total_turns": len(self._store[session_id])},
        )

    def format_for_prompt(self, session_id: str) -> str:
        """Return the most recent N turns formatted for LLM prompt injection."""
        turns = self.get_turns(session_id)
        if not turns:
            return ""
        recent = turns[-_MAX_HISTORY_PROMPT_TURNS:]
        parts = [
            f"Q: {t['question']}\nA: {t['insight']}"
            for t in recent
        ]
        return "Prior conversation:\n" + "\n\n".join(parts)

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        self._last_access.pop(session_id, None)


# Module-level singleton shared across all requests
conversation_store = ConversationStore()
