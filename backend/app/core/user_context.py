from __future__ import annotations

import contextvars

_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("grw_current_user", default=None)


def set_current_user(username: str | None) -> None:
    _current_user.set(username)


def get_current_user() -> str | None:
    return _current_user.get()
