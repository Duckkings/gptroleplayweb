from __future__ import annotations

from app.core.storage import read_json, storage_state, write_json_atomic
from app.models.schemas import BattleSandboxState


def _battle_state_path():
    return storage_state.save_path.parent / "battle-sandbox-state.json"


def load_current_battle(session_id: str) -> BattleSandboxState | None:
    path = _battle_state_path()
    if not path.exists():
        return None
    try:
        raw = read_json(path)
    except Exception:
        return None
    if raw.get("session_id") != session_id:
        return None
    try:
        return BattleSandboxState.model_validate(raw)
    except Exception:
        return None


def save_current_battle(state: BattleSandboxState) -> None:
    write_json_atomic(_battle_state_path(), state.model_dump(mode="json"))


def clear_current_battle(session_id: str) -> None:
    path = _battle_state_path()
    if not path.exists():
        return
    current = load_current_battle(session_id)
    if current is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
