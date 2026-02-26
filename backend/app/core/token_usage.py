from __future__ import annotations

from threading import Lock
from typing import Literal

from app.models.schemas import TokenUsageBucket, TokenUsageResponse, TokenUsageSources

TokenSource = Literal["chat", "map_generation", "movement_narration"]


class TokenUsageStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._by_session: dict[str, TokenUsageResponse] = {}

    def _ensure(self, session_id: str) -> TokenUsageResponse:
        existing = self._by_session.get(session_id)
        if existing is not None:
            return existing
        created = TokenUsageResponse(session_id=session_id, total=TokenUsageBucket(), sources=TokenUsageSources())
        self._by_session[session_id] = created
        return created

    def add(self, session_id: str, source: TokenSource, input_tokens: int, output_tokens: int) -> TokenUsageResponse:
        in_tokens = max(0, int(input_tokens or 0))
        out_tokens = max(0, int(output_tokens or 0))
        total_tokens = in_tokens + out_tokens
        if total_tokens == 0:
            return self.get(session_id)

        with self._lock:
            usage = self._ensure(session_id)
            src_bucket = getattr(usage.sources, source)
            src_bucket.input_tokens += in_tokens
            src_bucket.output_tokens += out_tokens
            src_bucket.total_tokens += total_tokens

            usage.total.input_tokens += in_tokens
            usage.total.output_tokens += out_tokens
            usage.total.total_tokens += total_tokens
            return usage.model_copy(deep=True)

    def get(self, session_id: str) -> TokenUsageResponse:
        with self._lock:
            usage = self._ensure(session_id)
            return usage.model_copy(deep=True)

    def reset(self, session_id: str) -> TokenUsageResponse:
        with self._lock:
            usage = TokenUsageResponse(session_id=session_id, total=TokenUsageBucket(), sources=TokenUsageSources())
            self._by_session[session_id] = usage
            return usage.model_copy(deep=True)


token_usage_store = TokenUsageStore()
