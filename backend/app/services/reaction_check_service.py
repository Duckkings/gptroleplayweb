from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    MainTurnSummary,
    PendingTurnContinueResponse,
    PendingTurnState,
    PlayerReactionCheck,
    SceneEvent,
    ToolEvent,
    Usage,
    ZoneMetricEntry,
)
from app.services import world_service as world
from app.services.pending_turn_service import save_pending_turn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_player_reaction_check(
    payload: dict[str, Any] | None,
    *,
    resolution_context: str,
) -> PlayerReactionCheck | None:
    if not isinstance(payload, dict):
        return None
    trigger_summary = " ".join(str(payload.get("trigger_summary") or "").split()).strip()
    threatened_consequence = " ".join(str(payload.get("threatened_consequence") or "").split()).strip()
    source_label = " ".join(str(payload.get("source_label") or "").split()).strip()
    check_task = " ".join(str(payload.get("check_task") or "").split()).strip()
    ability_used = str(payload.get("ability_used") or "").strip().lower()
    source_kind = str(payload.get("source_kind") or "").strip().lower()
    dc_raw = payload.get("dc")
    if not trigger_summary or not threatened_consequence or not source_label or not check_task:
        return None
    if ability_used not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
        return None
    if source_kind not in {"npc_action", "environment", "world_push", "encounter_effect", "npc_chat", "map_arrival"}:
        return None
    if not isinstance(dc_raw, int):
        return None
    return PlayerReactionCheck(
        reaction_id=str(payload.get("reaction_id") or f"react_{uuid4().hex}"),
        source_kind=source_kind,  # type: ignore[arg-type]
        source_actor_id=(str(payload.get("source_actor_id") or "").strip() or None),
        source_actor_name=(str(payload.get("source_actor_name") or "").strip() or None),
        source_label=source_label[:80],
        trigger_summary=trigger_summary[:240],
        threatened_consequence=threatened_consequence[:240],
        ability_used=ability_used,  # type: ignore[arg-type]
        dc=max(5, min(30, dc_raw)),
        check_task=check_task[:180],
        resolution_context=resolution_context,  # type: ignore[arg-type]
        success_hint=str(payload.get("success_hint") or "").strip()[:180],
        failure_hint=str(payload.get("failure_hint") or "").strip()[:180],
        critical_success_hint=str(payload.get("critical_success_hint") or "").strip()[:180],
        critical_failure_hint=str(payload.get("critical_failure_hint") or "").strip()[:180],
    )


def build_reaction_trigger_event(check: PlayerReactionCheck) -> SceneEvent:
    return world._new_scene_event(
        "player_reaction_triggered",
        check.trigger_summary,
        actor_role_id=check.source_actor_id or "",
        actor_name=check.source_actor_name or check.source_label,
        metadata={
            "source_kind": check.source_kind,
            "source_label": check.source_label,
            "threatened_consequence": check.threatened_consequence,
            "ability_used": check.ability_used,
            "dc": check.dc,
            "check_task": check.check_task,
            "success_hint": check.success_hint,
            "failure_hint": check.failure_hint,
            "critical_success_hint": check.critical_success_hint,
            "critical_failure_hint": check.critical_failure_hint,
        },
    )


def _reaction_outcome_prefix(result: ActionCheckResponse) -> str:
    if result.critical == "critical_success":
        return "因为你大成功，"
    if result.critical == "critical_failure":
        return "因为你大失败，"
    if result.success:
        return "因为你豁免成功，"
    return "因为你豁免失败，"


def _resolution_tail(narrative: str) -> str:
    parts = [part.strip() for part in str(narrative or "").splitlines() if part.strip()]
    if not parts:
        return ""
    return parts[-1]


def build_reaction_result_text(check: PlayerReactionCheck, result: ActionCheckResponse) -> str:
    tail = _resolution_tail(result.narrative)
    if not tail:
        tail = check.success_hint if result.success else check.failure_hint
    if result.critical == "critical_success" and check.critical_success_hint:
        tail = check.critical_success_hint
    elif result.critical == "critical_failure" and check.critical_failure_hint:
        tail = check.critical_failure_hint
    return f"{_reaction_outcome_prefix(result)}{tail}".strip()


def build_reaction_result_event(
    check: PlayerReactionCheck,
    result: ActionCheckResponse,
    *,
    content: str,
) -> SceneEvent:
    return world._new_scene_event(
        "player_reaction_result",
        content,
        actor_role_id=check.source_actor_id or "",
        actor_name=check.source_actor_name or check.source_label,
        metadata={
            "source_kind": check.source_kind,
            "source_label": check.source_label,
            "threatened_consequence": check.threatened_consequence,
            "ability_used": result.ability_used,
            "ability_modifier": result.ability_modifier,
            "dc": result.dc,
            "check_task": result.check_task,
            "dice_roll": result.dice_roll,
            "total_score": result.total_score,
            "success": result.success,
            "critical": result.critical,
        },
    )


def stage_reaction_checkpoint(
    *,
    session_id: str,
    flow_kind: str,
    staged_save: dict[str, Any],
    original_request: dict[str, Any],
    accumulated_reply_text: str,
    accumulated_scene_events: list[SceneEvent],
    accumulated_tool_events: list[ToolEvent],
    time_spent_min: int,
    pending_reaction: PlayerReactionCheck,
    continuation_index: int,
    usage: Usage | None = None,
    main_turn_summary: MainTurnSummary | None = None,
    current_zone_metric: ZoneMetricEntry | None = None,
    npc_role_id: str | None = None,
) -> PendingTurnContinueResponse:
    now = _utc_now()
    pending_turn_id = f"pt_{uuid4().hex}"
    state = PendingTurnState(
        pending_turn_id=pending_turn_id,
        session_id=session_id,
        flow_kind=flow_kind,  # type: ignore[arg-type]
        status="awaiting_reaction",
        staged_save=staged_save,
        original_request=original_request,
        accumulated_reply_text=accumulated_reply_text,
        accumulated_scene_events=accumulated_scene_events,
        accumulated_tool_events=accumulated_tool_events,
        time_spent_min=time_spent_min,
        pending_reaction=pending_reaction,
        continuation_index=continuation_index,
        usage=usage or Usage(),
        npc_role_id=npc_role_id,
        created_at=now,
        updated_at=now,
    )
    save_pending_turn(state)
    return PendingTurnContinueResponse(
        session_id=session_id,
        pending_turn_id=pending_turn_id,
        flow_kind=state.flow_kind,
        status="awaiting_reaction",
        reply_text=accumulated_reply_text,
        scene_events=accumulated_scene_events,
        tool_events=accumulated_tool_events,
        main_turn_summary=main_turn_summary,
        current_zone_metric=current_zone_metric,
        pending_reaction=pending_reaction,
        npc_role_id=npc_role_id,
    )


def apply_player_reaction_result_to_staged_save(
    state: PendingTurnState,
    *,
    forced_dice_roll: int,
    config=None,
) -> tuple[PendingTurnState, ActionCheckResponse]:
    with world.save_transaction(state.session_id) as txn:
        txn.save = world.SaveFile.model_validate(state.staged_save)
        pending = state.pending_reaction
        result = world.action_check(
            ActionCheckRequest(
                session_id=state.session_id,
                action_type="check",
                check_mode="reaction_save",
                action_prompt=pending.check_task,
                source_label=pending.source_label,
                threatened_consequence=pending.threatened_consequence,
                pending_turn_id=state.pending_turn_id,
                forced_dice_roll=forced_dice_roll,
                resolution_context="embedded",
                planned_ability_used=pending.ability_used,
                planned_dc=pending.dc,
                planned_time_spent_min=1,
                planned_requires_check=True,
                planned_check_task=pending.check_task,
                config=config,
            )
        )
        state.staged_save = txn.save.model_dump(mode="json")
    state.time_spent_min += result.time_spent_min
    state.updated_at = _utc_now()
    return state, result


def continue_pending_turn_once(
    state: PendingTurnState,
    *,
    forced_dice_roll: int,
    config=None,
) -> tuple[PendingTurnState, ActionCheckResponse]:
    return apply_player_reaction_result_to_staged_save(state, forced_dice_roll=forced_dice_roll, config=config)
