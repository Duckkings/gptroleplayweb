from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.models.schemas import (
    PendingTurnContinueResponse,
    PublicTurnActionSubmission,
    PublicTurnContinueRequest,
    PublicTurnEntryRequest,
    PublicTurnPhase,
    PublicTurnReactionCheckRequest,
    PublicTurnResponse,
    PublicTurnStateResponse,
)
from app.services import reaction_check_service
from app.services import world_service as world
from app.services.pending_turn_service import clear_pending_turn, load_pending_turn
from app.services.public_turn_runtime import (
    PublicTurnRunResult,
    continue_round_in_save,
    resume_round_after_reaction_in_save,
    start_round_in_save,
)
from app.services.public_turn_state_store import get_public_turn_state_in_save, sync_pending_public_turn_in_save

EmitCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


def get_public_turn_state(session_id: str) -> PublicTurnStateResponse:
    save = world.get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        world.save_current(save)
    state = sync_pending_public_turn_in_save(save, session_id)
    world.save_current(save)
    return PublicTurnStateResponse(session_id=session_id, public_turn_state=state)


def _to_response(session_id: str, result: PublicTurnRunResult, save) -> PublicTurnResponse:
    state = get_public_turn_state_in_save(save)
    phase = state.current_round.phase if state.current_round is not None else PublicTurnPhase.IDLE
    return PublicTurnResponse(
        session_id=session_id,
        phase=phase,
        narration=result.narration,
        scene_events=result.scene_events,
        reaction_check=result.reaction_check,
        round_completed=result.round_completed,
        awaiting_entry=state.awaiting_player_entry,
        public_turn_state=state,
        archived_sub_zone_turn_id=result.archived_sub_zone_turn_id,
        impacts=result.impacts,
    )


def run_public_turn_entry_once(payload: PublicTurnEntryRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    result = start_round_in_save(save, entry_type=payload.entry_type, config=payload.config)
    if str(payload.player_action or "").strip():
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        if round_state is None:
            raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
        result = continue_round_in_save(
            save,
            submission=PublicTurnActionSubmission(
                actor_id=save.player_static_data.player_id,
                action_text=str(payload.player_action or "").strip(),
                speech_text="",
                source_phase=round_state.phase,
                forced_first=payload.entry_type.value == "god_override",
            ),
            config=payload.config,
        )
        if result.reaction_check is not None:
            state = get_public_turn_state_in_save(save)
            round_state = state.current_round
            if round_state is None:
                raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
            pending = reaction_check_service.stage_reaction_checkpoint(
                session_id=payload.session_id,
                flow_kind="public_turn",
                staged_save=save.model_dump(mode="json"),
                original_request=payload.model_dump(mode="json"),
                accumulated_reply_text=result.narration,
                accumulated_scene_events=result.scene_events,
                accumulated_tool_events=[],
                time_spent_min=0,
                pending_reaction=result.reaction_check,
                continuation_index=0,
                npc_role_id=None,
                public_round_id=round_state.round_id,
                public_phase_before_pause=round_state.awaiting_player_action_phase or round_state.phase,
            )
            world.save_current(save)
            return pending
    world.save_current(save)
    return _to_response(payload.session_id, result, save)


def run_public_turn_continue_once(payload: PublicTurnContinueRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    if payload.action_submission is None:
        raise ValueError("PUBLIC_TURN_ACTION_REQUIRED")
    result = continue_round_in_save(
        save,
        submission=payload.action_submission,
        config=payload.config,
    )
    if result.reaction_check is not None:
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        if round_state is None:
            raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
        pending = reaction_check_service.stage_reaction_checkpoint(
            session_id=payload.session_id,
            flow_kind="public_turn",
            staged_save=save.model_dump(mode="json"),
            original_request=payload.model_dump(mode="json"),
            accumulated_reply_text=result.narration,
            accumulated_scene_events=result.scene_events,
            accumulated_tool_events=[],
            time_spent_min=0,
            pending_reaction=result.reaction_check,
            continuation_index=0,
            npc_role_id=None,
            public_round_id=round_state.round_id,
            public_phase_before_pause=round_state.awaiting_player_action_phase or round_state.phase,
        )
        world.save_current(save)
        return pending
    world.save_current(save)
    return _to_response(payload.session_id, result, save)


def run_public_turn_reaction_once(payload: PublicTurnReactionCheckRequest) -> PublicTurnResponse:
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if pending.pending_reaction.reaction_id != payload.check_id:
        raise ValueError("PUBLIC_TURN_REACTION_MISMATCH")
    pending, reaction_result = reaction_check_service.continue_pending_turn_once(
        pending,
        forced_dice_roll=payload.forced_dice_roll,
        config=payload.config,
    )
    reaction_text = reaction_check_service.build_reaction_result_text(pending.pending_reaction, reaction_result)
    reaction_event = reaction_check_service.build_reaction_result_event(
        pending.pending_reaction,
        reaction_result,
        content=reaction_text,
    )
    save = world.SaveFile.model_validate(pending.staged_save)
    result = resume_round_after_reaction_in_save(
        save,
        phase_before_pause=pending.public_phase_before_pause,
        reaction_text=reaction_text,
        reaction_event=reaction_event,
    )
    clear_pending_turn(payload.session_id)
    world.save_current(save)
    return _to_response(payload.session_id, result, save)


async def _stream_public_turn(
    *,
    payload,
    runner: Callable[[Any], PublicTurnResponse | PendingTurnContinueResponse],
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    if is_cancelled is not None and await is_cancelled():
        raise asyncio.CancelledError()
    result = runner(payload)
    if emit is not None:
        if isinstance(result, PublicTurnResponse):
            await emit("phase", {"code": result.phase.value, "label": result.phase.value, "status": "done", "detail": ""})
            await emit("turn_state", result.public_turn_state.model_dump(mode="json"))
            if result.narration:
                await emit("narration_delta", {"content": result.narration})
            for event in result.scene_events:
                await emit("scene_event", event.model_dump(mode="json"))
            for impact in result.impacts:
                await emit("impact", impact.model_dump(mode="json"))
            if result.round_completed:
                await emit(
                    "round_completed",
                    {
                        "archived_sub_zone_turn_id": result.archived_sub_zone_turn_id,
                        "phase": result.phase.value,
                    },
                )
        else:
            await emit(
                "reaction_check_required",
                {
                    "pending_turn_id": result.pending_turn_id,
                    "flow_kind": result.flow_kind,
                    "reply_so_far": result.reply_text,
                    "scene_events_so_far": [item.model_dump(mode="json") for item in result.scene_events],
                    "pending_reaction": (result.pending_reaction.model_dump(mode="json") if result.pending_reaction is not None else None),
                    "npc_role_id": result.npc_role_id,
                },
            )
    return result


async def run_public_turn_entry_stream(
    payload: PublicTurnEntryRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    return await _stream_public_turn(payload=payload, runner=run_public_turn_entry_once, emit=emit, is_cancelled=is_cancelled)


async def run_public_turn_continue_stream(
    payload: PublicTurnContinueRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    return await _stream_public_turn(payload=payload, runner=run_public_turn_continue_once, emit=emit, is_cancelled=is_cancelled)


async def run_public_turn_reaction_stream(
    payload: PublicTurnReactionCheckRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse:
    result = run_public_turn_reaction_once(payload)
    if emit is not None:
        await emit("reaction_check_resumed", {"check_id": payload.check_id})
        await emit("phase", {"code": result.phase.value, "label": result.phase.value, "status": "done", "detail": ""})
        await emit("turn_state", result.public_turn_state.model_dump(mode="json"))
        if result.narration:
            await emit("narration_delta", {"content": result.narration})
        for event in result.scene_events:
            await emit("scene_event", event.model_dump(mode="json"))
        for impact in result.impacts:
            await emit("impact", impact.model_dump(mode="json"))
        if result.round_completed:
            await emit(
                "round_completed",
                {
                    "archived_sub_zone_turn_id": result.archived_sub_zone_turn_id,
                    "phase": result.phase.value,
                },
            )
    return result
