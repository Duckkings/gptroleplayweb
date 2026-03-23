from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.storage import read_json, storage_state, write_json_atomic
from app.models.schemas import PendingTurnState


def _pending_turn_path() -> Path:
    return storage_state.save_path.parent / "pending-turn-state.json"


def load_pending_turn(session_id: str) -> PendingTurnState | None:
    path = _pending_turn_path()
    if not path.exists():
        return None
    try:
        raw = read_json(path)
        state = PendingTurnState.model_validate(raw)
    except Exception:
        return None
    if state.session_id != session_id:
        return None
    if state.status not in {
        "awaiting_reaction",
        "awaiting_opposed",
        "awaiting_player_attack_response",
        "awaiting_player_attack_defense",
        "awaiting_player_death_save",
        "awaiting_protocol_repair",
    }:
        return None
    return state


def save_pending_turn(state: PendingTurnState) -> PendingTurnState:
    state.updated_at = datetime.now(timezone.utc).isoformat()
    write_json_atomic(_pending_turn_path(), state.model_dump(mode="json"))
    return state


def clear_pending_turn(session_id: str) -> None:
    state = load_pending_turn(session_id)
    if state is None:
        return
    path = _pending_turn_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def cancel_pending_turn(session_id: str, pending_turn_id: str) -> PendingTurnState | None:
    state = load_pending_turn(session_id)
    if state is None or state.pending_turn_id != pending_turn_id:
        return None
    state.status = "cancelled"
    save_pending_turn(state)
    path = _pending_turn_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return state
