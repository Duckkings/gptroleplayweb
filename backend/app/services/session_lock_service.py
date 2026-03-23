from __future__ import annotations

import asyncio

from app.core.user_context import get_current_user

_SESSION_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def get_session_lock(session_id: str) -> asyncio.Lock:
    key = (get_current_user() or "_anon", session_id)
    lock = _SESSION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[key] = lock
    return lock
