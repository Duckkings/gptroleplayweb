from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.models.schemas import (
    PendingTurnContinueResponse,
    PendingTurnState,
    PublicTurnActionSubmission,
    PublicTurnContinueRequest,
    PublicTurnEntryRequest,
    PublicTurnNarrativeEntry,
    PublicTurnOpposedPlanRequest,
    PublicTurnOpposedPlanResponse,
    PublicTurnOpposedResolveRequest,
    PublicTurnPhase,
    PublicTurnProtocolEnumViolation,
    PublicTurnProtocolRepairNotice,
    PublicTurnProtocolRepairRequest,
    PublicTurnReactionCheckRequest,
    PublicTurnResponse,
    PublicTurnStateResponse,
)
from app.services.ai_protocol_contract_service import AI_PROTOCOL_ENUM_INVALID, AiProtocolContractError, allow_protocol_repair
from app.services.public_turn_narration_formatter import build_settlement_fragment
from app.services import reaction_check_service
from app.services import world_service as world
from app.services.pending_turn_service import clear_pending_turn, load_pending_turn, save_pending_turn
from app.services.public_turn_runtime import (
    PublicTurnRunResult,
    continue_round_in_save,
    iter_round_after_opposed_steps_in_save,
    iter_round_after_reaction_steps_in_save,
    iter_round_continue_steps_in_save,
    iter_round_entry_steps_in_save,
    resume_round_after_opposed_in_save,
    resume_round_after_reaction_in_save,
    start_round_in_save,
)
from app.services.public_turn_narration_service import chunk_narrative_text
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
    phase = result.presentation.phase if result.presentation.round_id else (state.current_round.phase if state.current_round is not None else PublicTurnPhase.IDLE)
    return PublicTurnResponse(
        session_id=session_id,
        phase=phase,
        narration=result.narration,
        scene_events=result.scene_events,
        reaction_check=result.reaction_check,
        public_interaction_prompt=result.public_interaction_prompt,
        public_opposed_prompt=result.public_opposed_prompt,
        round_completed=result.round_completed,
        awaiting_entry=state.awaiting_player_entry,
        public_turn_state=state,
        archived_sub_zone_turn_id=result.archived_sub_zone_turn_id,
        impacts=result.impacts,
        player_action_check_result=result.player_action_check_result,
        presentation=result.presentation,
    )


def _public_turn_presentation_from_save(save) -> dict[str, Any] | None:
    try:
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        if round_state is None:
            return None
        return {
            "round_id": round_state.round_id,
            "round_number": round_state.round_number,
            "phase": round_state.phase,
            "initiative_order": round_state.initiative_order,
            "settlement_entries": round_state.settlement_entries,
            "narrative_entries": round_state.narrative_entries,
            "accumulated_narration": round_state.accumulated_narration,
            "narrative_status": round_state.narrative_status,
            "round_narration": round_state.round_narration,
            "round_narration_status": round_state.round_narration_status,
        }
    except Exception:
        return None


def _protocol_notice_from_error(error: AiProtocolContractError) -> PublicTurnProtocolRepairNotice:
    violations = [
        PublicTurnProtocolEnumViolation(
            field_path=item.field_path,
            invalid_value=item.invalid_value,
            allowed_ids=list(item.allowed_ids),
            reason=item.reason,
        )
        for item in error.violations
    ]
    return PublicTurnProtocolRepairNotice(
        code=error.code,
        message="AI 首次输出协议错误，正在自动修复并续跑...",
        violations=violations,
    )


def _stage_protocol_repair_checkpoint(
    *,
    session_id: str,
    original_request: dict[str, Any],
    continue_kind: str,
    staged_save: dict[str, Any],
    error: AiProtocolContractError,
) -> PendingTurnContinueResponse:
    now = world._utc_now()
    pending_turn_id = f"pt_{uuid4().hex}"
    save = world.SaveFile.model_validate(staged_save)
    state = get_public_turn_state_in_save(save)
    notice = _protocol_notice_from_error(error)
    repair_request = PublicTurnProtocolRepairRequest(
        session_id=session_id,
        pending_turn_id=pending_turn_id,
        continue_kind=continue_kind,  # type: ignore[arg-type]
    )
    pending_state = PendingTurnState(
        pending_turn_id=pending_turn_id,
        session_id=session_id,
        flow_kind="public_turn",
        status="awaiting_protocol_repair",
        staged_save=staged_save,
        original_request=original_request,
        accumulated_reply_text="",
        accumulated_scene_events=[],
        accumulated_tool_events=[],
        time_spent_min=0,
        pending_reaction=None,
        public_opposed_prompt=None,
        continuation_index=0,
        npc_role_id=None,
        public_round_id=(state.current_round.round_id if state.current_round is not None else None),
        public_phase_before_pause=(state.current_round.phase if state.current_round is not None else None),
        public_turn_protocol_repair_notice=notice,
        public_turn_protocol_repair_request=repair_request,
        created_at=now,
        updated_at=now,
    )
    save_pending_turn(pending_state)
    return PendingTurnContinueResponse(
        session_id=session_id,
        pending_turn_id=pending_turn_id,
        flow_kind="public_turn",
        status="awaiting_protocol_repair",
        reply_text="",
        scene_events=[],
        tool_events=[],
        pending_reaction=None,
        public_turn_state=state,
        public_turn_presentation=_public_turn_presentation_from_save(save),
        npc_role_id=None,
        public_turn_protocol_repair_notice=notice,
        public_turn_protocol_repair_request=repair_request,
    )


def _stage_opposed_checkpoint(
    *,
    session_id: str,
    original_request: dict[str, Any],
    save,
    result: PublicTurnRunResult,
) -> PendingTurnContinueResponse:
    state = get_public_turn_state_in_save(save)
    round_state = state.current_round
    if round_state is None or result.public_opposed_prompt is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    now = world._utc_now()
    pending_turn_id = f"pt_{uuid4().hex}"
    pending_state = PendingTurnState(
        pending_turn_id=pending_turn_id,
        session_id=session_id,
        flow_kind="public_turn",
        status="awaiting_opposed",
        staged_save=save.model_dump(mode="json"),
        original_request=original_request,
        accumulated_reply_text=result.narration,
        accumulated_scene_events=result.scene_events,
        accumulated_tool_events=[],
        time_spent_min=0,
        pending_reaction=None,
        public_opposed_prompt=result.public_opposed_prompt,
        continuation_index=0,
        npc_role_id=None,
        public_round_id=round_state.round_id,
        public_phase_before_pause=round_state.awaiting_player_action_phase or round_state.phase,
        created_at=now,
        updated_at=now,
    )
    save_pending_turn(pending_state)
    return PendingTurnContinueResponse(
        session_id=session_id,
        pending_turn_id=pending_turn_id,
        flow_kind="public_turn",
        status="awaiting_opposed",
        reply_text=result.narration,
        scene_events=result.scene_events,
        tool_events=[],
        pending_reaction=None,
        public_opposed_prompt=result.public_opposed_prompt,
        player_action_check_result=result.player_action_check_result,
        public_turn_state=state,
        public_turn_presentation=result.presentation,
        npc_role_id=None,
    )


def _stage_reaction_checkpoint(
    *,
    session_id: str,
    original_request: dict[str, Any],
    save,
    result: PublicTurnRunResult,
) -> PendingTurnContinueResponse:
    state = get_public_turn_state_in_save(save)
    round_state = state.current_round
    if round_state is None or result.reaction_check is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    return reaction_check_service.stage_reaction_checkpoint(
        session_id=session_id,
        flow_kind="public_turn",
        staged_save=save.model_dump(mode="json"),
        original_request=original_request,
        accumulated_reply_text=result.narration,
        accumulated_scene_events=result.scene_events,
        accumulated_tool_events=[],
        time_spent_min=0,
        pending_reaction=result.reaction_check,
        continuation_index=0,
        npc_role_id=None,
        public_round_id=round_state.round_id,
        public_phase_before_pause=round_state.awaiting_player_action_phase or round_state.phase,
        player_action_check_result=result.player_action_check_result,
        public_turn_state=state,
        public_turn_presentation=result.presentation,
    )


async def _emit_public_turn_step(
    *,
    result: PublicTurnRunResult,
    emit: EmitCallback,
) -> None:
    await emit("phase", {"code": result.presentation.phase.value, "label": result.presentation.phase.value, "status": "done", "detail": ""})
    if result.presentation.round_id:
        await emit(
            "initiative_order",
            {
                "entries": [item.model_dump(mode="json") for item in result.presentation.initiative_order],
                "round_id": result.presentation.round_id,
                "round_number": result.presentation.round_number,
            },
        )
    narrative_by_settlement = {
        str(item.settlement_entry_id or ""): item for item in result.presentation.narrative_entries
    }
    emitted_narrative_ids: set[str] = set()
    for settlement in result.settlement_entries:
        await emit("settlement_entry", settlement.model_dump(mode="json"))
        narrative_entry = narrative_by_settlement.get(settlement.entry_id)
        if narrative_entry is None:
            fragment = build_settlement_fragment(settlement)
            if fragment:
                narrative_entry = PublicTurnNarrativeEntry(
                    narrative_entry_id=settlement.narrative_entry_id or f"{settlement.entry_id}_narr",
                    round_id=settlement.round_id,
                    settlement_entry_id=settlement.entry_id,
                    phase=settlement.phase,
                    order_index=settlement.order_index,
                    actor_id=settlement.actor_id,
                    actor_name=settlement.actor_name,
                    actor_type=settlement.actor_type,
                    text=fragment,
                    status="ready",
                )
        if narrative_entry is not None and narrative_entry.narrative_entry_id not in emitted_narrative_ids:
            emitted_narrative_ids.add(narrative_entry.narrative_entry_id)
            await emit("narrative_fragment_started", narrative_entry.model_dump(mode="json"))
            for chunk in chunk_narrative_text(narrative_entry.text):
                await emit(
                    "narrative_fragment_delta",
                    {"narrative_entry_id": narrative_entry.narrative_entry_id, "content": chunk},
                )
                await emit("round_narration_delta", {"content": chunk})
            await emit("narrative_fragment_completed", narrative_entry.model_dump(mode="json"))
    preview_entries = [
        item for item in result.presentation.narrative_entries if item.settlement_entry_id is None and item.narrative_entry_id not in emitted_narrative_ids
    ]
    for narrative_entry in preview_entries:
        emitted_narrative_ids.add(narrative_entry.narrative_entry_id)
        await emit("narrative_fragment_started", narrative_entry.model_dump(mode="json"))
        for chunk in chunk_narrative_text(narrative_entry.text):
            await emit(
                "narrative_fragment_delta",
                {"narrative_entry_id": narrative_entry.narrative_entry_id, "content": chunk},
            )
            await emit("round_narration_delta", {"content": chunk})
        await emit("narrative_fragment_completed", narrative_entry.model_dump(mode="json"))
    for event in result.scene_events:
        await emit("scene_event", event.model_dump(mode="json"))
    for impact in result.impacts:
        await emit("impact", impact.model_dump(mode="json"))
    if result.public_interaction_prompt is not None:
        await emit("interaction_required", result.public_interaction_prompt.model_dump(mode="json"))
    if result.presentation.phase == PublicTurnPhase.GM_PUSH and result.round_completed:
        await emit("gm_push", {"round_id": result.presentation.round_id, "round_number": result.presentation.round_number})


async def _emit_pending_response(
    *,
    result: PendingTurnContinueResponse,
    emit: EmitCallback,
) -> None:
    if result.status == "awaiting_protocol_repair":
        event_name = "protocol_repair_required"
    else:
        event_name = "opposed_check_required" if result.status == "awaiting_opposed" else "reaction_check_required"
    await emit(
        event_name,
        {
            "pending_turn_id": result.pending_turn_id,
            "flow_kind": result.flow_kind,
            "reply_so_far": result.reply_text,
            "scene_events_so_far": [item.model_dump(mode="json") for item in result.scene_events],
            "pending_reaction": (result.pending_reaction.model_dump(mode="json") if result.pending_reaction is not None else None),
            "public_opposed_prompt": (
                result.public_opposed_prompt.model_dump(mode="json") if result.public_opposed_prompt is not None else None
            ),
            "npc_role_id": result.npc_role_id,
            "public_turn_state": (result.public_turn_state.model_dump(mode="json") if result.public_turn_state is not None else None),
            "public_turn_presentation": (
                result.public_turn_presentation.model_dump(mode="json") if result.public_turn_presentation is not None else None
            ),
            "public_turn_protocol_repair_notice": (
                result.public_turn_protocol_repair_notice.model_dump(mode="json")
                if result.public_turn_protocol_repair_notice is not None
                else None
            ),
            "public_turn_protocol_repair_request": (
                result.public_turn_protocol_repair_request.model_dump(mode="json")
                if result.public_turn_protocol_repair_request is not None
                else None
            ),
        },
    )


def _merge_step_results(results: list[PublicTurnRunResult]) -> PublicTurnRunResult:
    if not results:
        raise ValueError("PUBLIC_TURN_NO_RESULTS")
    last = results[-1]
    scene_events = []
    impacts = []
    settlements = []
    reaction_check = None
    public_interaction_prompt = None
    public_opposed_prompt = None
    player_action_check_result = None
    archived_sub_zone_turn_id = None
    for item in results:
        scene_events.extend(item.scene_events)
        impacts.extend(item.impacts)
        settlements.extend(item.settlement_entries)
        reaction_check = item.reaction_check or reaction_check
        public_interaction_prompt = item.public_interaction_prompt or public_interaction_prompt
        public_opposed_prompt = item.public_opposed_prompt or public_opposed_prompt
        player_action_check_result = item.player_action_check_result or player_action_check_result
        archived_sub_zone_turn_id = item.archived_sub_zone_turn_id or archived_sub_zone_turn_id
    return PublicTurnRunResult(
        narration=last.narration,
        scene_events=scene_events,
        impacts=impacts,
        initiative_order=last.initiative_order,
        settlement_entries=settlements,
        presentation=last.presentation,
        round_completed=last.round_completed,
        archived_sub_zone_turn_id=archived_sub_zone_turn_id,
        reaction_check=reaction_check,
        public_interaction_prompt=public_interaction_prompt,
        public_opposed_prompt=public_opposed_prompt,
        player_action_check_result=player_action_check_result,
    )


def run_public_turn_opposed_plan_once(payload: PublicTurnOpposedPlanRequest) -> PublicTurnOpposedPlanResponse:
    return world.plan_public_turn_opposed_exchange(payload)


def run_public_turn_entry_once(payload: PublicTurnEntryRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    staged_save = save.model_dump(mode="json")
    try:
        result = start_round_in_save(
            save,
            entry_type=payload.entry_type,
            config=payload.config,
            player_action=payload.player_action,
        )
        if (
            str(payload.player_action or "").strip()
            and result.reaction_check is None
            and result.public_interaction_prompt is None
            and result.public_opposed_prompt is None
            and not result.round_completed
        ):
            state = get_public_turn_state_in_save(save)
            round_state = state.current_round
            if round_state is None or not round_state.awaiting_player_action:
                raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text=str(payload.player_action or "").strip(),
                    speech_text="",
                    source_phase=round_state.awaiting_player_action_phase or round_state.phase,
                    forced_first=payload.entry_type.value == "god_override",
                ),
                interaction_response=None,
                action_check=None,
                config=payload.config,
            )
            if result.reaction_check is not None:
                pending = _stage_reaction_checkpoint(
                    session_id=payload.session_id,
                    original_request=payload.model_dump(mode="json"),
                    save=save,
                    result=result,
                )
                world.save_current(save)
                return pending
            if result.public_opposed_prompt is not None:
                pending = _stage_opposed_checkpoint(
                    session_id=payload.session_id,
                    original_request=payload.model_dump(mode="json"),
                    save=save,
                    result=result,
                )
                world.save_current(save)
                return pending
        if result.public_opposed_prompt is not None:
            pending = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending
        world.save_current(save)
        return _to_response(payload.session_id, result, save)
    except AiProtocolContractError as exc:
        if exc.code == AI_PROTOCOL_ENUM_INVALID:
            return _stage_protocol_repair_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                continue_kind="entry",
                staged_save=staged_save,
                error=exc,
            )
        raise ValueError(exc.code) from exc


def run_public_turn_continue_once(payload: PublicTurnContinueRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    staged_save = save.model_dump(mode="json")
    try:
        result = continue_round_in_save(
            save,
            submission=payload.action_submission,
            interaction_response=payload.player_interaction_response,
            action_check=payload.player_action_check,
            config=payload.config,
        )
        if result.reaction_check is not None:
            pending = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending
        if result.public_opposed_prompt is not None:
            pending = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending
        world.save_current(save)
        return _to_response(payload.session_id, result, save)
    except AiProtocolContractError as exc:
        if exc.code == AI_PROTOCOL_ENUM_INVALID:
            return _stage_protocol_repair_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                continue_kind="continue",
                staged_save=staged_save,
                error=exc,
            )
        raise ValueError(exc.code) from exc


def run_public_turn_reaction_once(payload: PublicTurnReactionCheckRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if pending.pending_reaction is None:
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
    staged_save = pending.staged_save
    try:
        result = resume_round_after_reaction_in_save(
            save,
            phase_before_pause=pending.public_phase_before_pause,
            reaction_text=reaction_text,
            reaction_event=reaction_event,
            config=payload.config,
        )
        clear_pending_turn(payload.session_id)
        if result.reaction_check is not None:
            pending_response = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending_response
        if result.public_opposed_prompt is not None:
            pending_response = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending_response
        world.save_current(save)
        return _to_response(payload.session_id, result, save)
    except AiProtocolContractError as exc:
        if exc.code == AI_PROTOCOL_ENUM_INVALID:
            return _stage_protocol_repair_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                continue_kind="reaction",
                staged_save=staged_save,
                error=exc,
            )
        raise ValueError(exc.code) from exc


def run_public_turn_opposed_once(payload: PublicTurnOpposedResolveRequest) -> PublicTurnResponse | PendingTurnContinueResponse:
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    prompt = pending.public_opposed_prompt
    if pending.status != "awaiting_opposed" or prompt is None:
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if prompt.check_id != payload.check_id:
        raise ValueError("PUBLIC_TURN_OPPOSED_MISMATCH")
    save = world.SaveFile.model_validate(pending.staged_save)
    staged_save = pending.staged_save
    try:
        result = resume_round_after_opposed_in_save(
            save,
            phase_before_pause=pending.public_phase_before_pause,
            prompt=prompt,
            target_action_summary=payload.target_action_summary,
            target_speech_text=payload.target_speech_text,
            forced_dice_roll=payload.forced_dice_roll,
            config=payload.config,
        )
        clear_pending_turn(payload.session_id)
        if result.reaction_check is not None:
            pending_response = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending_response
        if result.public_opposed_prompt is not None:
            pending_response = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=result,
            )
            world.save_current(save)
            return pending_response
        world.save_current(save)
        return _to_response(payload.session_id, result, save)
    except AiProtocolContractError as exc:
        if exc.code == AI_PROTOCOL_ENUM_INVALID:
            return _stage_protocol_repair_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                continue_kind="opposed",
                staged_save=staged_save,
                error=exc,
            )
        raise ValueError(exc.code) from exc


def run_public_turn_protocol_repair_once(
    payload: PublicTurnProtocolRepairRequest,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn" or pending.status != "awaiting_protocol_repair":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if pending.pending_turn_id != payload.pending_turn_id:
        raise ValueError("PUBLIC_TURN_PROTOCOL_REPAIR_MISMATCH")
    repair_request = pending.public_turn_protocol_repair_request
    if repair_request is None:
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if payload.continue_kind != repair_request.continue_kind:
        raise ValueError("PUBLIC_TURN_PROTOCOL_REPAIR_MISMATCH")
    request_data = dict(pending.original_request)
    if payload.config is not None:
        request_data["config"] = payload.config.model_dump(mode="json")
    world.save_current(world.SaveFile.model_validate(pending.staged_save))
    clear_pending_turn(payload.session_id)
    with allow_protocol_repair():
        if repair_request.continue_kind == "entry":
            return run_public_turn_entry_once(PublicTurnEntryRequest.model_validate(request_data))
        if repair_request.continue_kind == "continue":
            return run_public_turn_continue_once(PublicTurnContinueRequest.model_validate(request_data))
        if repair_request.continue_kind == "reaction":
            return run_public_turn_reaction_once(PublicTurnReactionCheckRequest.model_validate(request_data))
        if repair_request.continue_kind == "opposed":
            return run_public_turn_opposed_once(PublicTurnOpposedResolveRequest.model_validate(request_data))
    raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")


async def run_public_turn_protocol_repair_stream(
    payload: PublicTurnProtocolRepairRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn" or pending.status != "awaiting_protocol_repair":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if pending.pending_turn_id != payload.pending_turn_id:
        raise ValueError("PUBLIC_TURN_PROTOCOL_REPAIR_MISMATCH")
    repair_request = pending.public_turn_protocol_repair_request
    if repair_request is None:
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if payload.continue_kind != repair_request.continue_kind:
        raise ValueError("PUBLIC_TURN_PROTOCOL_REPAIR_MISMATCH")
    request_data = dict(pending.original_request)
    if payload.config is not None:
        request_data["config"] = payload.config.model_dump(mode="json")
    world.save_current(world.SaveFile.model_validate(pending.staged_save))
    clear_pending_turn(payload.session_id)
    with allow_protocol_repair():
        if repair_request.continue_kind == "entry":
            return await run_public_turn_entry_stream(PublicTurnEntryRequest.model_validate(request_data), emit=emit, is_cancelled=is_cancelled)
        if repair_request.continue_kind == "continue":
            return await run_public_turn_continue_stream(PublicTurnContinueRequest.model_validate(request_data), emit=emit, is_cancelled=is_cancelled)
        if repair_request.continue_kind == "reaction":
            return await run_public_turn_reaction_stream(PublicTurnReactionCheckRequest.model_validate(request_data), emit=emit, is_cancelled=is_cancelled)
        if repair_request.continue_kind == "opposed":
            return await run_public_turn_opposed_stream(PublicTurnOpposedResolveRequest.model_validate(request_data), emit=emit, is_cancelled=is_cancelled)
    raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")


async def run_public_turn_entry_stream(
    payload: PublicTurnEntryRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    if is_cancelled is not None and await is_cancelled():
        raise asyncio.CancelledError()
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    staged_save = save.model_dump(mode="json")
    try:
        step_results: list[PublicTurnRunResult] = []
        for step in iter_round_entry_steps_in_save(
            save,
            entry_type=payload.entry_type,
            config=payload.config,
            player_action=payload.player_action,
        ):
            step_results.append(step)
            if emit is not None:
                await _emit_public_turn_step(result=step, emit=emit)
                await emit("turn_state", get_public_turn_state_in_save(save).model_dump(mode="json"))
                if step.round_completed:
                    await emit(
                        "round_completed",
                        {
                            "archived_sub_zone_turn_id": step.archived_sub_zone_turn_id,
                            "phase": step.presentation.phase.value,
                        },
                    )
            if is_cancelled is not None and await is_cancelled():
                raise asyncio.CancelledError()
        merged = _merge_step_results(step_results)
        if (
            str(payload.player_action or "").strip()
            and merged.reaction_check is None
            and merged.public_interaction_prompt is None
            and merged.public_opposed_prompt is None
            and not merged.round_completed
        ):
            state = get_public_turn_state_in_save(save)
            round_state = state.current_round
            if round_state is not None and round_state.awaiting_player_action:
                submission = PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text=str(payload.player_action or "").strip(),
                    speech_text="",
                    source_phase=round_state.awaiting_player_action_phase or round_state.phase,
                    forced_first=payload.entry_type.value == "god_override",
                )
                for step in iter_round_continue_steps_in_save(
                    save,
                    submission=submission,
                    interaction_response=None,
                    action_check=None,
                    config=payload.config,
                ):
                    step_results.append(step)
                    if emit is not None:
                        await _emit_public_turn_step(result=step, emit=emit)
                        await emit("turn_state", get_public_turn_state_in_save(save).model_dump(mode="json"))
                        if step.round_completed:
                            await emit(
                                "round_completed",
                                {
                                    "archived_sub_zone_turn_id": step.archived_sub_zone_turn_id,
                                    "phase": step.presentation.phase.value,
                                },
                            )
                    if is_cancelled is not None and await is_cancelled():
                        raise asyncio.CancelledError()
                merged = _merge_step_results(step_results)
        if merged.reaction_check is not None:
            pending = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending, emit=emit)
            return pending
        if merged.public_opposed_prompt is not None:
            pending = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending, emit=emit)
            return pending
        world.save_current(save)
        return _to_response(payload.session_id, merged, save)
    except AiProtocolContractError as exc:
        if exc.code != AI_PROTOCOL_ENUM_INVALID:
            raise ValueError(exc.code) from exc
        pending = _stage_protocol_repair_checkpoint(
            session_id=payload.session_id,
            original_request=payload.model_dump(mode="json"),
            continue_kind="entry",
            staged_save=staged_save,
            error=exc,
        )
        if emit is not None:
            await _emit_pending_response(result=pending, emit=emit)
        return pending


async def run_public_turn_continue_stream(
    payload: PublicTurnContinueRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    if is_cancelled is not None and await is_cancelled():
        raise asyncio.CancelledError()
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    staged_save = save.model_dump(mode="json")
    try:
        step_results: list[PublicTurnRunResult] = []
        for step in iter_round_continue_steps_in_save(
            save,
            submission=payload.action_submission,
            interaction_response=payload.player_interaction_response,
            action_check=payload.player_action_check,
            config=payload.config,
        ):
            step_results.append(step)
            if emit is not None:
                await _emit_public_turn_step(result=step, emit=emit)
                await emit("turn_state", get_public_turn_state_in_save(save).model_dump(mode="json"))
                if step.round_completed:
                    await emit(
                        "round_completed",
                        {
                            "archived_sub_zone_turn_id": step.archived_sub_zone_turn_id,
                            "phase": step.presentation.phase.value,
                        },
                    )
            if is_cancelled is not None and await is_cancelled():
                raise asyncio.CancelledError()
        merged = _merge_step_results(step_results)
        if merged.reaction_check is not None:
            pending = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending, emit=emit)
            return pending
        if merged.public_opposed_prompt is not None:
            pending = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending, emit=emit)
            return pending
        world.save_current(save)
        return _to_response(payload.session_id, merged, save)
    except AiProtocolContractError as exc:
        if exc.code != AI_PROTOCOL_ENUM_INVALID:
            raise ValueError(exc.code) from exc
        pending = _stage_protocol_repair_checkpoint(
            session_id=payload.session_id,
            original_request=payload.model_dump(mode="json"),
            continue_kind="continue",
            staged_save=staged_save,
            error=exc,
        )
        if emit is not None:
            await _emit_pending_response(result=pending, emit=emit)
        return pending


async def run_public_turn_reaction_stream(
    payload: PublicTurnReactionCheckRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    if is_cancelled is not None and await is_cancelled():
        raise asyncio.CancelledError()
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn" or pending.pending_reaction is None:
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
    staged_save = pending.staged_save
    clear_pending_turn(payload.session_id)
    try:
        step_results: list[PublicTurnRunResult] = []
        if emit is not None:
            await emit("reaction_check_resumed", {"check_id": payload.check_id})
        for step in iter_round_after_reaction_steps_in_save(
            save,
            phase_before_pause=pending.public_phase_before_pause,
            reaction_text=reaction_text,
            reaction_event=reaction_event,
            config=payload.config,
        ):
            step_results.append(step)
            if emit is not None:
                await _emit_public_turn_step(result=step, emit=emit)
                await emit("turn_state", get_public_turn_state_in_save(save).model_dump(mode="json"))
                if step.round_completed:
                    await emit(
                        "round_completed",
                        {
                            "archived_sub_zone_turn_id": step.archived_sub_zone_turn_id,
                            "phase": step.presentation.phase.value,
                        },
                    )
            if is_cancelled is not None and await is_cancelled():
                raise asyncio.CancelledError()
        merged = _merge_step_results(step_results)
        if merged.reaction_check is not None:
            pending_response = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending_response, emit=emit)
            return pending_response
        if merged.public_opposed_prompt is not None:
            pending_response = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending_response, emit=emit)
            return pending_response
        world.save_current(save)
        return _to_response(payload.session_id, merged, save)
    except AiProtocolContractError as exc:
        if exc.code != AI_PROTOCOL_ENUM_INVALID:
            raise ValueError(exc.code) from exc
        pending_response = _stage_protocol_repair_checkpoint(
            session_id=payload.session_id,
            original_request=payload.model_dump(mode="json"),
            continue_kind="reaction",
            staged_save=staged_save,
            error=exc,
        )
        if emit is not None:
            await _emit_pending_response(result=pending_response, emit=emit)
        return pending_response


async def run_public_turn_opposed_stream(
    payload: PublicTurnOpposedResolveRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PublicTurnResponse | PendingTurnContinueResponse:
    if is_cancelled is not None and await is_cancelled():
        raise asyncio.CancelledError()
    pending = load_pending_turn(payload.session_id)
    if pending is None or pending.flow_kind != "public_turn":
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    prompt = pending.public_opposed_prompt
    if pending.status != "awaiting_opposed" or prompt is None:
        raise ValueError("PUBLIC_TURN_PENDING_NOT_FOUND")
    if prompt.check_id != payload.check_id:
        raise ValueError("PUBLIC_TURN_OPPOSED_MISMATCH")
    save = world.SaveFile.model_validate(pending.staged_save)
    staged_save = pending.staged_save
    clear_pending_turn(payload.session_id)
    try:
        step_results: list[PublicTurnRunResult] = []
        if emit is not None:
            await emit("opposed_check_resolved", {"check_id": payload.check_id})
        for step in iter_round_after_opposed_steps_in_save(
            save,
            phase_before_pause=pending.public_phase_before_pause,
            prompt=prompt,
            target_action_summary=payload.target_action_summary,
            target_speech_text=payload.target_speech_text,
            forced_dice_roll=payload.forced_dice_roll,
            config=payload.config,
        ):
            step_results.append(step)
            if emit is not None:
                await _emit_public_turn_step(result=step, emit=emit)
                await emit("turn_state", get_public_turn_state_in_save(save).model_dump(mode="json"))
                if step.round_completed:
                    await emit(
                        "round_completed",
                        {
                            "archived_sub_zone_turn_id": step.archived_sub_zone_turn_id,
                            "phase": step.presentation.phase.value,
                        },
                    )
            if is_cancelled is not None and await is_cancelled():
                raise asyncio.CancelledError()
        merged = _merge_step_results(step_results)
        if merged.reaction_check is not None:
            pending_response = _stage_reaction_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending_response, emit=emit)
            return pending_response
        if merged.public_opposed_prompt is not None:
            pending_response = _stage_opposed_checkpoint(
                session_id=payload.session_id,
                original_request=payload.model_dump(mode="json"),
                save=save,
                result=merged,
            )
            world.save_current(save)
            if emit is not None:
                await _emit_pending_response(result=pending_response, emit=emit)
            return pending_response
        world.save_current(save)
        return _to_response(payload.session_id, merged, save)
    except AiProtocolContractError as exc:
        if exc.code != AI_PROTOCOL_ENUM_INVALID:
            raise ValueError(exc.code) from exc
        pending_response = _stage_protocol_repair_checkpoint(
            session_id=payload.session_id,
            original_request=payload.model_dump(mode="json"),
            continue_kind="opposed",
            staged_save=staged_save,
            error=exc,
        )
        if emit is not None:
            await _emit_pending_response(result=pending_response, emit=emit)
        return pending_response
