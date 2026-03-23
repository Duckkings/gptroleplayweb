from __future__ import annotations

import contextvars
import json
import logging
import traceback
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

from app.core.storage import storage_state, write_json_atomic
from app.core.user_context import get_current_user

_CURRENT_GENERATION_LOG: contextvars.ContextVar["LatestGenerationLog | None"] = contextvars.ContextVar(
    "latest_generation_log",
    default=None,
)
logger = logging.getLogger("roleplay.generation_debug_log")
_MAX_STRING_LENGTH = 8000
_MAX_COLLECTION_ITEMS = 80
_MAX_DEPTH = 6
_FLUSH_RETRY_DELAYS = (0.0, 0.02, 0.05)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_log_path() -> Path:
    base_dir = storage_state.save_path.parent
    path = base_dir / "debug" / "latest-generation-log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _recovery_log_path(path: Path) -> Path:
    return path.with_name("latest-generation-log.recovery.json")


def _truncate_text(value: str) -> str:
    if len(value) <= _MAX_STRING_LENGTH:
        return value
    return f"{value[:_MAX_STRING_LENGTH]}...<truncated {len(value) - _MAX_STRING_LENGTH} chars>"


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return "<max-depth>"
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except Exception:
            value = repr(value)
    elif isinstance(value, SimpleNamespace):
        value = vars(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseException):
        return {"type": value.__class__.__name__, "message": str(value)}
    if isinstance(value, str):
        return _truncate_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        items = list(value.items())[:_MAX_COLLECTION_ITEMS]
        sanitized = {str(key): _sanitize(item, depth=depth + 1) for key, item in items}
        if len(value) > _MAX_COLLECTION_ITEMS:
            sanitized["__truncated_items__"] = len(value) - _MAX_COLLECTION_ITEMS
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:_MAX_COLLECTION_ITEMS]
        sanitized = [_sanitize(item, depth=depth + 1) for item in items]
        if len(value) > _MAX_COLLECTION_ITEMS:
            sanitized.append(f"<truncated {len(value) - _MAX_COLLECTION_ITEMS} items>")
        return sanitized
    return _truncate_text(repr(value))


@dataclass
class LatestGenerationLog:
    flow_kind: str
    session_id: str
    request_data: dict[str, Any] = field(default_factory=dict)
    path: Path = field(default_factory=_latest_log_path)
    payload: dict[str, Any] = field(default_factory=dict)
    _flush_error_count: int = field(default=0, init=False, repr=False)

    def _write_direct_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def __post_init__(self) -> None:
        self.payload = {
            "version": "latest_generation_log.v1",
            "user": get_current_user(),
            "flow_kind": self.flow_kind,
            "session_id": self.session_id,
            "status": "running",
            "started_at": _utc_now(),
            "finished_at": None,
            "request": _sanitize(self.request_data),
            "events": [],
            "result": None,
            "error": None,
        }
        self.flush()

    def record(self, stage: str, message: str = "", data: Any = None) -> None:
        entry = {
            "ts": _utc_now(),
            "stage": stage,
            "message": message,
        }
        if data is not None:
            entry["data"] = _sanitize(data)
        self.payload.setdefault("events", []).append(entry)
        self.flush()

    def finish(self, *, status: str, result: Any = None, error: Any = None) -> None:
        self.payload["status"] = status
        self.payload["finished_at"] = _utc_now()
        if result is not None:
            self.payload["result"] = _sanitize(result)
        if error is not None:
            if isinstance(error, BaseException):
                self.payload["error"] = {
                    "type": error.__class__.__name__,
                    "message": str(error),
                    "traceback": _truncate_text("".join(traceback.format_exception(type(error), error, error.__traceback__))),
                }
            else:
                self.payload["error"] = _sanitize(error)
        self.flush()

    def flush(self) -> None:
        last_error: Exception | None = None
        for delay in _FLUSH_RETRY_DELAYS:
            if delay > 0:
                time.sleep(delay)
            try:
                write_json_atomic(self.path, self.payload)
                recovery_path = _recovery_log_path(self.path)
                if recovery_path.exists():
                    try:
                        recovery_path.unlink()
                    except Exception:
                        logger.debug("generation debug log: failed to remove stale recovery log", exc_info=True)
                return
            except PermissionError as exc:
                last_error = exc
            except OSError as exc:
                last_error = exc
        if last_error is None:
            return

        self._flush_error_count += 1
        warning_payload = dict(self.payload)
        warning_payload["log_write_warning"] = {
            "count": self._flush_error_count,
            "type": last_error.__class__.__name__,
            "message": str(last_error),
            "main_path": str(self.path),
        }
        try:
            self._write_direct_json(self.path, warning_payload)
            return
        except Exception as direct_exc:
            last_error = direct_exc

        recovery_path = _recovery_log_path(self.path)
        try:
            warning_payload["log_write_warning"]["recovery_path"] = str(recovery_path)
            self._write_direct_json(recovery_path, warning_payload)
        except Exception:
            logger.warning(
                "generation debug log flush failed; main_path=%s recovery_path=%s",
                self.path,
                recovery_path,
                exc_info=True,
            )
            return

        logger.warning(
            "generation debug log wrote recovery copy after main path was locked; main_path=%s recovery_path=%s error=%s",
            self.path,
            recovery_path,
            last_error,
        )


def current_generation_debug_log() -> LatestGenerationLog | None:
    return _CURRENT_GENERATION_LOG.get()


@contextmanager
def generation_debug_log(flow_kind: str, session_id: str, request_data: dict[str, Any] | None = None) -> Iterator[LatestGenerationLog]:
    log = LatestGenerationLog(flow_kind=flow_kind, session_id=session_id, request_data=request_data or {})
    token = _CURRENT_GENERATION_LOG.set(log)
    try:
        yield log
    except Exception as exc:
        if log.payload.get("status") == "running":
            log.finish(status="error", error=exc)
        raise
    finally:
        if log.payload.get("status") == "running":
            log.finish(status="incomplete", error={"message": "generation log exited without explicit finish"})
        _CURRENT_GENERATION_LOG.reset(token)
