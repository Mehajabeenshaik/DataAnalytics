"""In-memory short-term conversation context per session. Redis can replace
this dict-based store later without changing the public interface."""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Any

MAX_TURNS_PER_SESSION = 5
MAX_ACTIVE_SESSIONS = 500


class ConversationMemory:
    def __init__(self, max_turns: int = MAX_TURNS_PER_SESSION, max_sessions: int = MAX_ACTIVE_SESSIONS):
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        # OrderedDict for cheap LRU-style eviction of whole sessions
        self._sessions: "OrderedDict[str, deque]" = OrderedDict()

    def record_turn(
        self,
        session_id: str,
        question: str,
        plan_type: str,
        target: str | None,
        filters: dict | None = None,
        groupby: str | None = None,
    ) -> None:
        if not session_id:
            return

        if session_id not in self._sessions:
            if len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)  # evict oldest session
            self._sessions[session_id] = deque(maxlen=self.max_turns)
        else:
            self._sessions.move_to_end(session_id)

        self._sessions[session_id].append({
            "question": question,
            "plan_type": plan_type,
            "target": target,
            "filters": filters or {},
            "groupby": groupby,
            "timestamp": time.time(),
        })

    def get_context(self, session_id: str) -> str:
        """Returns a short, human-readable summary for prompt injection.
        Newest turn last, so it reads as a natural conversation transcript."""
        if not session_id or session_id not in self._sessions:
            return ""

        turns = list(self._sessions[session_id])
        if not turns:
            return ""

        lines = []
        for t in turns:
            desc = f"Previous question: '{t['question']}'"
            if t.get("target"):
                desc += f" -> used {t['plan_type']} on '{t['target']}'"
            if t.get("groupby"):
                desc += f" grouped by '{t['groupby']}'"
            if t.get("filters"):
                desc += f" with filters {t['filters']}"
            lines.append(desc)
        return "\n".join(lines)


# Module-level singleton, mirrors the in-memory pattern used by tenant_quotas.py
_memory = ConversationMemory()


def get_memory() -> ConversationMemory:
    return _memory