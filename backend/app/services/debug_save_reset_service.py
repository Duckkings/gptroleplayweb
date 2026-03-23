from __future__ import annotations

from pathlib import Path

from app.core.storage import storage_state
from app.models.schemas import DebugSaveResetResponse, EnvironmentRiskLevel, SaveFile
from app.services.pending_turn_service import clear_pending_turn, load_pending_turn
from app.services.public_turn_state_store import current_sub_zone, ensure_sub_zone_chat_context
from app.services.world_service import _new_game_log, _utc_now, get_current_save, save_current


def _pending_turn_path() -> Path:
    return storage_state.save_path.parent / "pending-turn-state.json"


def _collect_public_round_ids(save: SaveFile) -> list[str]:
    sub_zone = current_sub_zone(save)
    context = ensure_sub_zone_chat_context(sub_zone)
    if context is None:
        return []
    ids: list[str] = []
    current_round = context.public_turn_state.current_round
    if current_round is not None and current_round.round_id:
        ids.append(current_round.round_id)
    for round_state in context.public_turn_state.round_history:
        round_id = str(getattr(round_state, "round_id", "") or "")
        if round_id:
            ids.append(round_id)
    unique: list[str] = []
    seen: set[str] = set()
    for round_id in ids:
        if round_id in seen:
            continue
        seen.add(round_id)
        unique.append(round_id)
    return unique


def _clear_public_turn_state(save: SaveFile) -> list[str]:
    sub_zone = current_sub_zone(save)
    context = ensure_sub_zone_chat_context(sub_zone)
    if context is None:
        return []
    cleared_round_ids = _collect_public_round_ids(save)
    state = context.public_turn_state
    state.current_round = None
    state.round_history = []
    state.awaiting_player_entry = True
    state.environment_risk_level = EnvironmentRiskLevel.STABLE
    state.situation_dc = 10
    state.updated_at = _utc_now()
    context.public_turn_state = state
    context.version = "0.2.0"
    context.updated_at = state.updated_at
    return cleared_round_ids


def _invalidate_running_encounters(save: SaveFile) -> tuple[list[str], list[str]]:
    now = _utc_now()
    encounter_state = save.encounter_state
    cleared_active_ids: list[str] = []
    cleared_queued_ids: list[str] = []
    queued_from_pending = {str(item or "") for item in encounter_state.pending_ids if str(item or "")}
    for encounter in encounter_state.encounters:
        if encounter.status == "active":
            cleared_active_ids.append(encounter.encounter_id)
        elif encounter.status == "queued":
            cleared_queued_ids.append(encounter.encounter_id)
        else:
            continue
        encounter.status = "invalidated"
        encounter.invalidated_reason = "debug_test_reset"
        encounter.resolved_at = now
        encounter.player_presence = "away"
    cleared_queued_ids.extend(item for item in queued_from_pending if item not in cleared_queued_ids)
    encounter_state.pending_ids = []
    encounter_state.active_encounter_id = None
    encounter_state.updated_at = now
    return cleared_active_ids, cleared_queued_ids


def _clear_recent_turns(save: SaveFile, *, cleared_encounter_ids: set[str]) -> int:
    sub_zone = current_sub_zone(save)
    context = ensure_sub_zone_chat_context(sub_zone)
    if context is None:
        return 0
    before_count = len(context.recent_turns)
    context.recent_turns = [
        turn
        for turn in context.recent_turns
        if turn.public_round_id is None and str(turn.active_encounter_id or "") not in cleared_encounter_ids
    ]
    removed_count = before_count - len(context.recent_turns)
    if removed_count > 0:
        context.updated_at = _utc_now()
    return removed_count


def _clear_team_memory_logs(save: SaveFile) -> list[str]:
    now = _utc_now()
    cleared_role_ids: list[str] = []
    save.team_state.reactions = []
    save.team_state.updated_at = now
    active_role_ids = {
        str(member.role_id or "")
        for member in save.team_state.members
        if str(getattr(member, "status", "") or "active") == "active" and str(member.role_id or "")
    }
    for member in save.team_state.members:
        if str(getattr(member, "status", "") or "active") != "active":
            continue
        member.last_reaction_at = None
        member.last_reaction_preview = ""
        role_id = str(member.role_id or "")
        if role_id:
            cleared_role_ids.append(role_id)
    for role in save.role_pool:
        if role.role_id not in active_role_ids:
            continue
        role.dialogue_logs = []
        role.private_chat_memories = []
        role.cognition_changes = []
        role.attitude_changes = []
        role.last_private_chat_at = None
        role.last_public_turn_at = None
    return cleared_role_ids


def reset_debug_test_state(session_id: str) -> DebugSaveResetResponse:
    save = get_current_save(default_session_id=session_id)
    pending_before = load_pending_turn(session_id)
    clear_pending_turn(session_id)
    pending_cleared = pending_before is not None and not _pending_turn_path().exists()

    cleared_public_round_ids = _clear_public_turn_state(save)
    cleared_active_encounter_ids, cleared_pending_encounter_ids = _invalidate_running_encounters(save)
    cleared_recent_turn_count = _clear_recent_turns(
        save,
        cleared_encounter_ids=set(cleared_active_encounter_ids) | set(cleared_pending_encounter_ids),
    )
    cleared_team_member_role_ids = _clear_team_memory_logs(save)

    summary = (
        f"测试重置完成：关闭遭遇 {len(cleared_active_encounter_ids) + len(cleared_pending_encounter_ids)} 个，"
        f"清除公开回合 {len(cleared_public_round_ids)} 轮，"
        f"移除最近记录 {cleared_recent_turn_count} 条，"
        f"清空队友记忆 {len(cleared_team_member_role_ids)} 人，"
        f"{'已清理 pending turn。' if pending_cleared else '未发现 pending turn。'}"
    )
    save.game_logs.append(
        _new_game_log(
            session_id,
            "debug_reset",
            summary,
            payload={
                "active_encounters_cleared": len(cleared_active_encounter_ids),
                "queued_encounters_cleared": len(cleared_pending_encounter_ids),
                "public_rounds_cleared": len(cleared_public_round_ids),
                "recent_turns_cleared": cleared_recent_turn_count,
                "team_members_cleared": len(cleared_team_member_role_ids),
                "pending_turn_cleared": pending_cleared,
            },
        )
    )
    save_current(save)
    return DebugSaveResetResponse(
        ok=True,
        session_id=session_id,
        save=save,
        cleared_active_encounter_ids=cleared_active_encounter_ids,
        cleared_pending_encounter_ids=cleared_pending_encounter_ids,
        cleared_public_round_ids=cleared_public_round_ids,
        cleared_recent_turn_count=cleared_recent_turn_count,
        cleared_team_member_role_ids=cleared_team_member_role_ids,
        cleared_pending_turn=pending_cleared,
        summary=summary,
    )
