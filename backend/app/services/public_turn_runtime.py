from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    ChatConfig,
    DeathSavePrompt,
    EnvironmentRiskLevel,
    InitiativeDeclaration,
    PlayerReactionCheck,
    PublicTurnActionSubmission,
    PublicTurnAttackDefensePrompt,
    PublicTurnAttackPrompt,
    PublicTurnInformationCheckPrompt,
    PublicTurnAttackResponseSubmission,
    PublicTurnEntryType,
    PublicTurnImpact,
    PublicTurnInteractionPrompt,
    PublicTurnInteractionResponseSubmission,
    PublicTurnInitiativeEntry,
    PublicTurnOpposedPrompt,
    PublicTurnPhase,
    PublicTurnPlayerActionCheck,
    PublicTurnPresentation,
    PublicTurnRound,
    PublicTurnRoundNarrationStatus,
    PublicTurnNarrativeEntry,
    PublicTurnSettlementEntry,
    PublicTurnState,
    SaveFile,
    SceneEvent,
)
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import world_service as world
from app.services import zone_metric_service
from app.services.public_turn_candidates import initiative_actor_rows
from app.services.public_turn_gm_push_service import resolve_public_turn_gm_push
from app.services.public_turn_narration_formatter import format_pause_preview_fragment, sync_round_narration_from_settlements
from app.services.public_turn_resolution import (
    build_initiative_declarations,
    build_initiative_order,
    build_settlement_check,
    build_player_initiative_declaration,
    finalize_initiative_totals,
    resolve_ai_round,  # compatibility import for tests that patch this symbol
    resolve_ai_actor_turn,
    resolve_attack_defense_prompt_submission,
    resolve_attack_prompt_submission,
    prepare_npc_attack_prompt,
    resolve_interaction_prompt_submission,
    resolve_opposed_prompt_submission,
    resolve_player_attack_submission,
    resolve_player_submission,
    resolve_public_turn_death_save,
    make_public_turn_death_save_prompt,
)
from app.services.public_turn_segment_service import (
    PublicTurnResolvedBeat,
    plan_public_turn_segment,
    resolve_public_turn_segment,
)
from app.services.public_turn_state_store import (
    get_public_turn_state_in_save,
    save_public_turn_state_in_save,
    sync_pending_public_turn_in_save,
)

_GOD_MODE_MARKERS = ("God Mode", "涓婂笣妯″紡")


@dataclass
class PublicTurnRunResult:
    narration: str
    scene_events: list[SceneEvent]
    impacts: list[PublicTurnImpact]
    initiative_order: list[PublicTurnInitiativeEntry]
    settlement_entries: list[PublicTurnSettlementEntry]
    presentation: PublicTurnPresentation
    round_completed: bool
    archived_sub_zone_turn_id: str | None = None
    reaction_check: PlayerReactionCheck | None = None
    public_interaction_prompt: PublicTurnInteractionPrompt | None = None
    public_attack_prompt: PublicTurnAttackPrompt | None = None
    public_attack_defense_prompt: PublicTurnAttackDefensePrompt | None = None
    public_opposed_prompt: PublicTurnOpposedPrompt | None = None
    public_information_check_prompt: PublicTurnInformationCheckPrompt | None = None
    death_save_prompt: DeathSavePrompt | None = None
    player_action_check_result: ActionCheckResponse | None = None


def is_god_mode(config: ChatConfig | None) -> bool:
    if config is None:
        return False
    prompt = str(config.gm_prompt or "")
    return any(marker in prompt for marker in _GOD_MODE_MARKERS)


def _phase_event(round_state: PublicTurnRound, *, label: str = "") -> SceneEvent:
    return world._new_scene_event(
        "public_turn_phase",
        label or f"Public turn phase -> {round_state.phase.value}",
        actor_name="System",
        metadata={
            "round_id": round_state.round_id,
            "round_number": round_state.round_number,
            "phase": round_state.phase.value,
        },
    )


def _initiative_event(round_state: PublicTurnRound) -> SceneEvent:
    order = " -> ".join(
        f"{item.actor_name}({item.total_initiative})" for item in round_state.initiative_declarations
    ) or "No initiative actors"
    return world._new_scene_event(
        "public_turn_initiative",
        order,
        actor_name="System",
        metadata={
            "round_id": round_state.round_id,
            "round_number": round_state.round_number,
            "phase": round_state.phase.value,
        },
    )


def _round_end_event(round_state: PublicTurnRound, *, narration: str) -> SceneEvent:
    return world._new_scene_event(
        "public_turn_round_end",
        narration,
        actor_name="GM",
        metadata={
            "round_id": round_state.round_id,
            "round_number": round_state.round_number,
            "environment_risk_level": round_state.environment_risk_level.value,
        },
    )


def _presentation_from_round(round_state: PublicTurnRound | None) -> PublicTurnPresentation:
    if round_state is None:
        return PublicTurnPresentation()
    return PublicTurnPresentation(
        round_id=round_state.round_id,
        round_number=round_state.round_number,
        phase=round_state.phase,
        initiative_order=list(round_state.initiative_order),
        settlement_entries=list(round_state.settlement_entries),
        gm_push_result=round_state.gm_push_result,
        narrative_entries=list(round_state.narrative_entries),
        accumulated_narration=round_state.accumulated_narration,
        narrative_status=round_state.narrative_status,
        round_narration=round_state.round_narration,
        round_narration_status=round_state.round_narration_status,
    )


def _sync_initiative_order(round_state: PublicTurnRound) -> None:
    round_state.initiative_order = build_initiative_order(round_state.initiative_declarations)


def _append_settlement(round_state: PublicTurnRound, settlement: PublicTurnSettlementEntry) -> None:
    settlement.order_index = len(round_state.settlement_entries)
    round_state.settlement_entries.append(settlement)


def _coerce_runtime_phase(round_state: PublicTurnRound) -> None:
    if round_state.phase == PublicTurnPhase.SITUATION_ADVANCEMENT:
        round_state.phase = PublicTurnPhase.GM_PUSH


def _sync_compat_narration(round_state: PublicTurnRound) -> None:
    sync_round_narration_from_settlements(round_state)
    if round_state.phase in {
        PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
        PublicTurnPhase.AWAITING_PLAYER_REACTION,
        PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
        PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE,
        PublicTurnPhase.AWAITING_PLAYER_ATTACK_DEFENSE,
        PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK,
        PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE,
    }:
        round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
        round_state.round_narration_status = PublicTurnRoundNarrationStatus.PAUSED


def _reveal_declaration(round_state: PublicTurnRound, actor_id: str) -> None:
    changed = False
    for declaration in round_state.initiative_declarations:
        if declaration.actor_id != actor_id or not declaration.is_hidden:
            continue
        if not declaration.revealed_by_declaration:
            declaration.revealed_by_declaration = True
            changed = True
    if changed:
        _sync_initiative_order(round_state)


def _next_round_number(state: PublicTurnState) -> int:
    if state.current_round is not None:
        return int(state.current_round.round_number) + 1
    if state.round_history:
        return int(state.round_history[-1].round_number) + 1
    return 1


def _new_round(state: PublicTurnState) -> PublicTurnRound:
    return PublicTurnRound(
        round_id=f"ptround_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        round_number=_next_round_number(state),
        phase=PublicTurnPhase.INITIATIVE_DECLARATION,
        environment_risk_level=state.environment_risk_level,
        situation_dc=state.situation_dc,
        current_actor_id=None,
        awaiting_player_action=False,
        awaiting_player_action_phase=None,
        narrative_status=PublicTurnRoundNarrationStatus.EMPTY,
    )


def _normalize_narration(parts: Iterable[str]) -> str:
    return "\n".join(part.strip() for part in parts if str(part or "").strip()).strip()


def _clear_player_pause(round_state: PublicTurnRound) -> None:
    round_state.current_actor_id = None
    round_state.awaiting_player_action = False
    round_state.awaiting_player_action_phase = None
    round_state.pending_interaction_prompt = None
    round_state.pending_attack_prompt = None
    round_state.pending_attack_defense_prompt = None
    round_state.pending_information_check_prompt = None
    round_state.pending_death_save_prompt = None
    round_state.narrative_entries = [item for item in round_state.narrative_entries if item.settlement_entry_id is not None]


def _entry_seed_text(
    save: SaveFile,
    state: PublicTurnState,
    *,
    entry_type: PublicTurnEntryType,
    player_action: str,
) -> str:
    clean_player_action = str(player_action or "").strip()
    if clean_player_action:
        return clean_player_action
    if entry_type in {PublicTurnEntryType.INITIATIVE, PublicTurnEntryType.GOD_OVERRIDE}:
        return "player prepares to act first"
    if world._active_encounter_for_current_sub_zone(save) is not None:
        return "attack pressure rises in public turn"
    if state.environment_risk_level != EnvironmentRiskLevel.STABLE:
        return "force unstable public turn situation"
    return ""


def _build_round_declarations(
    save: SaveFile,
    state: PublicTurnState,
    *,
    round_state: PublicTurnRound,
    entry_type: PublicTurnEntryType,
    player_action: str,
    config: ChatConfig | None,
) -> list[InitiativeDeclaration]:
    seed_text = _entry_seed_text(save, state, entry_type=entry_type, player_action=player_action)
    declarations = build_initiative_declarations(
        save,
        player_action_text=seed_text,
        mode=("priority_action" if entry_type == PublicTurnEntryType.INITIATIVE else "hostile_only"),
        addressed_role_name="",
        incoming_target_candidates=[],
        config=config,
    )
    if entry_type in {PublicTurnEntryType.INITIATIVE, PublicTurnEntryType.GOD_OVERRIDE}:
        declarations.insert(
            0,
            build_player_initiative_declaration(
                save,
                action_text=(player_action or "Take initiative").strip(),
                speech_text="",
                forced_first=entry_type == PublicTurnEntryType.GOD_OVERRIDE,
            ),
        )
    round_state.initiative_declarations = finalize_initiative_totals(declarations)
    _sync_initiative_order(round_state)
    return round_state.initiative_declarations


def _mark_actor_executed(round_state: PublicTurnRound, actor_id: str) -> None:
    if actor_id and actor_id not in round_state.executed_actor_ids:
        round_state.executed_actor_ids.append(actor_id)


def _response_consumes_actor_turn(*, response_kind: str | None, action_text: str, speech_text: str) -> bool:
    if str(response_kind or "").strip().lower() == "no_action":
        return False
    return bool(str(action_text or "").strip() or str(speech_text or "").strip())


def _resolve_initiative_actor_row(
    save: SaveFile,
    *,
    declaration: InitiativeDeclaration,
    context_text: str,
    config: ChatConfig | None,
) -> dict[str, object] | None:
    rows = initiative_actor_rows(
        save,
        player_text=context_text,
        addressed_role_name="",
        incoming_target_candidates=[],
        config=config,
    )
    for row in rows:
        if str(row.get("actor_id") or "") == declaration.actor_id:
            return row
    if declaration.actor_type == "team":
        member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == declaration.actor_id), None)
        if member is None:
            return None
        role = next((item for item in save.role_pool if item.role_id == declaration.actor_id), None)
        return {
            "actor_id": declaration.actor_id,
            "name": declaration.actor_name,
            "actor_type": "team",
            "priority_reason": "initiative_declaration",
            "role": role,
        }
    if declaration.actor_type == "encounter_temp_npc":
        temp_npc = world._find_active_encounter_temp_npc(save, declaration.actor_id)
        if temp_npc is None:
            return None
        return {
            "actor_id": declaration.actor_id,
            "name": declaration.actor_name,
            "actor_type": "encounter_temp_npc",
            "priority_reason": "initiative_declaration",
            "temp_npc": temp_npc,
        }
    role = next((item for item in save.role_pool if item.role_id == declaration.actor_id), None)
    if role is None:
        return None
    actor_type = "hidden_npc" if declaration.actor_type == "hidden_npc" else "npc"
    return {
        "actor_id": declaration.actor_id,
        "name": declaration.actor_name,
        "actor_type": actor_type,
        "priority_reason": "initiative_declaration",
        "role": role,
        "is_hidden": declaration.is_hidden,
    }


def _make_seed_beat(
    *,
    scene_events: list[SceneEvent],
    settlement: PublicTurnSettlementEntry,
    impact: PublicTurnImpact,
) -> PublicTurnResolvedBeat:
    return PublicTurnResolvedBeat(
        scene_events=list(scene_events),
        settlement=settlement,
        impact=impact,
        narration_input=None,
    )


def _apply_narrated_beats(
    *,
    round_state: PublicTurnRound,
    beats: list[PublicTurnResolvedBeat],
    segment_id: str,
    config: ChatConfig | None,
) -> list:
    del segment_id, config
    preview_entries = [item for item in round_state.narrative_entries if item.settlement_entry_id is None]
    next_order = len([item for item in round_state.narrative_entries if item.settlement_entry_id is not None])
    for beat in beats:
        narration_input = beat.narration_input
        if narration_input is None or narration_input.anchor_kind != "pause_preview":
            continue
        text = format_pause_preview_fragment(narration_input)
        if not text:
            continue
        preview_entries.append(
            PublicTurnNarrativeEntry(
                narrative_entry_id=f"{round_state.round_id}_preview_{len(preview_entries) + 1}",
                round_id=round_state.round_id,
                settlement_entry_id=None,
                phase=round_state.phase,
                order_index=next_order + len(preview_entries),
                actor_id="",
                actor_name=narration_input.actor_name,
                actor_type=narration_input.actor_type,
                text=text,
                status="ready",
            )
        )
    round_state.narrative_entries = [item for item in round_state.narrative_entries if item.settlement_entry_id is not None] + preview_entries
    _sync_compat_narration(round_state)
    return list(round_state.narrative_entries)


def _complete_round(
    save: SaveFile,
    *,
    state: PublicTurnState,
    round_state: PublicTurnRound,
    narration: str,
    scene_events: list[SceneEvent],
    public_phase: PublicTurnPhase,
) -> str:
    round_state.completed_at = world._utc_now()
    world.restore_npc_talkative_from_public_round(save, round_id=round_state.round_id)
    state.environment_risk_level = round_state.environment_risk_level
    state.round_history.append(round_state.model_copy(deep=True))
    state.round_history = state.round_history[-state.max_history :]
    state.current_round = None
    state.awaiting_player_entry = True
    save_public_turn_state_in_save(save, state)
    return world._record_sub_zone_chat_turn(
        save,
        source="main_chat",
        player_mode="active",
        player_action="",
        player_speech="",
        player_action_check={},
        gm_narration=narration,
        events=scene_events,
        public_round_id=round_state.round_id,
        public_round_number=round_state.round_number,
        public_phase=public_phase,
        public_turn_presentation=_presentation_from_round(round_state),
    )


def _build_result(
    *,
    state: PublicTurnState,
    round_state: PublicTurnRound | None,
    narration: str,
    scene_events: list[SceneEvent],
    impacts: list[PublicTurnImpact],
    settlements: list[PublicTurnSettlementEntry],
    round_completed: bool,
    archived_sub_zone_turn_id: str | None = None,
    reaction_check: PlayerReactionCheck | None = None,
    public_interaction_prompt: PublicTurnInteractionPrompt | None = None,
    public_attack_prompt: PublicTurnAttackPrompt | None = None,
    public_attack_defense_prompt: PublicTurnAttackDefensePrompt | None = None,
    public_opposed_prompt: PublicTurnOpposedPrompt | None = None,
    public_information_check_prompt: PublicTurnInformationCheckPrompt | None = None,
    death_save_prompt: DeathSavePrompt | None = None,
    player_action_check_result: ActionCheckResponse | None = None,
) -> PublicTurnRunResult:
    current_round = state.current_round if state.current_round is not None else round_state
    return PublicTurnRunResult(
        narration=narration,
        scene_events=scene_events,
        impacts=impacts,
        initiative_order=(list(current_round.initiative_order) if current_round is not None else []),
        settlement_entries=settlements,
        presentation=_presentation_from_round(current_round),
        round_completed=round_completed,
        archived_sub_zone_turn_id=archived_sub_zone_turn_id,
        reaction_check=reaction_check,
        public_interaction_prompt=public_interaction_prompt,
        public_attack_prompt=public_attack_prompt,
        public_attack_defense_prompt=public_attack_defense_prompt,
        public_opposed_prompt=public_opposed_prompt,
        public_information_check_prompt=public_information_check_prompt,
        death_save_prompt=death_save_prompt,
        player_action_check_result=player_action_check_result,
    )


def _next_unexecuted_initiative_index(round_state: PublicTurnRound) -> int | None:
    for index, declaration in enumerate(round_state.initiative_declarations):
        actor_id = declaration.actor_id
        if actor_id and actor_id not in round_state.executed_actor_ids:
            return index
    return None


def _initiative_actor_rows_for_segment(
    save: SaveFile,
    *,
    round_state: PublicTurnRound,
    context_text: str,
    config: ChatConfig | None,
) -> tuple[list[dict[str, object]], bool]:
    start_index = _next_unexecuted_initiative_index(round_state)
    if start_index is None:
        return [], False
    rows: list[dict[str, object]] = []
    player_next = False
    for declaration in round_state.initiative_declarations[start_index:]:
        actor_id = declaration.actor_id
        if not actor_id or actor_id in round_state.executed_actor_ids:
            continue
        if actor_id == save.player_static_data.player_id:
            player_next = True
            break
        actor = _resolve_initiative_actor_row(save, declaration=declaration, context_text=context_text, config=config)
        if actor is None:
            _mark_actor_executed(round_state, actor_id)
            continue
        rows.append(actor)
    return rows, player_next


def _run_segment_step(
    save: SaveFile,
    *,
    state: PublicTurnState,
    context_text: str,
    gm_summary: str,
    config: ChatConfig | None,
    seed_beats: list[PublicTurnResolvedBeat] | None = None,
    seed_scene_events: list[SceneEvent] | None = None,
    seed_impacts: list[PublicTurnImpact] | None = None,
    player_action_check_result: ActionCheckResponse | None = None,
) -> PublicTurnRunResult:
    round_state = state.current_round
    if round_state is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    _coerce_runtime_phase(round_state)
    scene_events: list[SceneEvent] = list(seed_scene_events or [])
    impacts: list[PublicTurnImpact] = list(seed_impacts or [])
    settlements: list[PublicTurnSettlementEntry] = [
        beat.settlement for beat in (seed_beats or []) if beat.settlement is not None
    ]
    pending_beats: list[PublicTurnResolvedBeat] = list(seed_beats or [])

    while True:
        if round_state.phase == PublicTurnPhase.INITIATIVE_DECLARATION:
            _clear_player_pause(round_state)
            round_state.phase = PublicTurnPhase.INITIATIVE_EXECUTION
            scene_events.append(_phase_event(round_state, label="Enter initiative execution phase"))
            scene_events.append(_initiative_event(round_state))
            continue

        if round_state.phase == PublicTurnPhase.INITIATIVE_EXECUTION:
            rows, player_next = _initiative_actor_rows_for_segment(
                save,
                round_state=round_state,
                context_text=context_text,
                config=config,
            )
            next_index = _next_unexecuted_initiative_index(round_state)
            if next_index is not None and round_state.initiative_declarations[next_index].actor_id == save.player_static_data.player_id:
                if pending_beats:
                    _apply_narrated_beats(
                        round_state=round_state,
                        beats=pending_beats,
                        segment_id=f"{round_state.round_id}_{round_state.phase.value}_{len(round_state.narrative_entries) + 1}",
                        config=config,
                    )
                    pending_beats = []
                round_state.current_actor_id = save.player_static_data.player_id
                round_state.awaiting_player_action = True
                round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
                state.awaiting_player_entry = False
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    player_action_check_result=player_action_check_result,
                )
            if not rows:
                round_state.phase = PublicTurnPhase.NORMAL_ADVANCEMENT
                scene_events.append(_phase_event(round_state, label="Enter normal advancement phase"))
                continue
            intent = world._parse_player_intent(context_text)
            audience_context = public_scene_runtime.build_public_audience_context(save, intent)
            scene_context = world._build_scene_context_payload(
                save,
                player_text=context_text,
                gm_narration=gm_summary,
                recent_turn_count=4,
            )
            zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
            reputation_score = getattr(zone_metric, "reputation_score", 50)
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=rows,
                phase=PublicTurnPhase.INITIATIVE_EXECUTION,
                player_text=context_text,
                gm_summary=gm_summary,
                scene_context=scene_context,
                audience_context=audience_context,
                prior_narration=round_state.accumulated_narration,
                default_boundary_kind=("player_turn" if player_next else "round_end"),
                config=config,
            )
            segment = resolve_public_turn_segment(
                save,
                round_state=round_state,
                actor_lookup={str(row.get("actor_id") or ""): row for row in rows},
                plan=plan,
                context_text=context_text,
                reputation_score=reputation_score,
                config=config,
            )
            new_actor_ids: list[str] = []
            for beat in segment.beats:
                scene_events.extend(beat.scene_events)
                pending_beats.append(beat)
                if beat.impact is not None:
                    impacts.append(beat.impact)
                    round_state.impacts.append(beat.impact)
                    new_actor_ids.append(beat.impact.actor_id)
                if beat.settlement is not None:
                    _append_settlement(round_state, beat.settlement)
                    settlements.append(beat.settlement)
                    new_actor_ids.append(beat.settlement.actor_id)
            if pending_beats:
                _apply_narrated_beats(round_state=round_state, beats=pending_beats, segment_id=plan.segment_id, config=config)
                pending_beats = []
            for actor_id in new_actor_ids:
                if actor_id:
                    _reveal_declaration(round_state, actor_id)
                    _mark_actor_executed(round_state, actor_id)
            if segment.public_interaction_prompt is not None:
                attack_prompt = None
                if segment.public_interaction_prompt.source_action_type == "attack":
                    attack_prompt = prepare_npc_attack_prompt(
                        save,
                        source_actor_id=segment.public_interaction_prompt.source_actor_id,
                        source_actor_name=segment.public_interaction_prompt.source_actor_name,
                        source_actor_type="npc",
                        source_action_summary=segment.public_interaction_prompt.source_action_summary,
                        source_speech_text=segment.public_interaction_prompt.source_speech_text,
                        source_action_prompt=segment.public_interaction_prompt.source_action_prompt,
                        source_action_target_name=segment.public_interaction_prompt.source_action_target_name,
                        round_state=round_state,
                        situation_delta_hint=segment.public_interaction_prompt.source_situation_delta_hint,
                        reputation_delta_hint=segment.public_interaction_prompt.source_reputation_delta_hint,
                        config=config,
                    )
                _reveal_declaration(round_state, segment.public_interaction_prompt.source_actor_id)
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                if attack_prompt is not None:
                    round_state.pending_attack_prompt = attack_prompt
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE
                    scene_events.append(_phase_event(round_state, label="Public turn paused for player attack response"))
                else:
                    round_state.pending_interaction_prompt = segment.public_interaction_prompt
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
                    scene_events.append(_phase_event(round_state, label="Public turn paused for player interaction response"))
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    public_interaction_prompt=(None if attack_prompt is not None else segment.public_interaction_prompt),
                    public_attack_prompt=attack_prompt,
                    player_action_check_result=player_action_check_result,
                )
            if segment.public_opposed_prompt is not None:
                _reveal_declaration(round_state, segment.public_opposed_prompt.source_actor_id)
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_OPPOSED
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                scene_events.append(_phase_event(round_state, label="Public turn paused for player opposed response"))
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    public_opposed_prompt=segment.public_opposed_prompt,
                    player_action_check_result=player_action_check_result,
                )
            if segment.pending_reaction is not None:
                round_state.pending_reaction_check_id = segment.pending_reaction.reaction_id
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_REACTION
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                scene_events.append(_phase_event(round_state, label="Public turn paused for player reaction"))
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    reaction_check=segment.pending_reaction,
                    player_action_check_result=player_action_check_result,
                )
            if player_next:
                round_state.current_actor_id = save.player_static_data.player_id
                round_state.awaiting_player_action = True
                round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
                state.awaiting_player_entry = False
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    player_action_check_result=player_action_check_result,
                )
            round_state.phase = PublicTurnPhase.NORMAL_ADVANCEMENT
            round_state.narrative_status = PublicTurnRoundNarrationStatus.STREAMING
            _sync_compat_narration(round_state)
            save_public_turn_state_in_save(save, state)
            return _build_result(
                state=state,
                round_state=round_state,
                narration=round_state.accumulated_narration,
                scene_events=scene_events,
                impacts=impacts,
                settlements=settlements,
                round_completed=False,
                player_action_check_result=player_action_check_result,
            )

        if round_state.phase == PublicTurnPhase.NORMAL_ADVANCEMENT:
            if save.player_static_data.player_id not in round_state.executed_actor_ids:
                if pending_beats:
                    _apply_narrated_beats(
                        round_state=round_state,
                        beats=pending_beats,
                        segment_id=f"{round_state.round_id}_{round_state.phase.value}_{len(round_state.narrative_entries) + 1}",
                        config=config,
                    )
                    pending_beats = []
                round_state.current_actor_id = save.player_static_data.player_id
                round_state.awaiting_player_action = True
                round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
                state.awaiting_player_entry = False
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    player_action_check_result=player_action_check_result,
                )
            intent = world._parse_player_intent(context_text)
            display_text = str(intent.get("display_text") or context_text).strip()
            addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
            audience_context = public_scene_runtime.build_public_audience_context(save, intent)
            from app.services.public_turn_candidates import public_turn_normal_actor_rows

            rows = public_turn_normal_actor_rows(
                save,
                player_text=display_text,
                addressed_role_name=addressed_role_name,
                incoming_target_candidates=[str(item) for item in list(intent.get("incoming_target_candidates") or [])],
                config=config,
            )
            rows = [row for row in rows if str(row.get("actor_id") or "") not in set(round_state.executed_actor_ids)]
            if not rows:
                round_state.phase = PublicTurnPhase.GM_PUSH
                scene_events.append(_phase_event(round_state, label="Enter GM push phase"))
                continue
            scene_context = world._build_scene_context_payload(
                save,
                player_text=display_text or context_text,
                gm_narration=gm_summary,
                recent_turn_count=4,
            )
            zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
            reputation_score = getattr(zone_metric, "reputation_score", 50)
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text=display_text,
                gm_summary=gm_summary,
                scene_context=scene_context,
                audience_context=audience_context,
                prior_narration=round_state.accumulated_narration,
                default_boundary_kind="round_end",
                config=config,
            )
            segment = resolve_public_turn_segment(
                save,
                round_state=round_state,
                actor_lookup={str(row.get("actor_id") or ""): row for row in rows},
                plan=plan,
                context_text=display_text or context_text,
                reputation_score=reputation_score,
                config=config,
            )
            new_actor_ids: list[str] = []
            for beat in segment.beats:
                scene_events.extend(beat.scene_events)
                pending_beats.append(beat)
                if beat.impact is not None:
                    impacts.append(beat.impact)
                    round_state.impacts.append(beat.impact)
                    new_actor_ids.append(beat.impact.actor_id)
                if beat.settlement is not None:
                    _append_settlement(round_state, beat.settlement)
                    settlements.append(beat.settlement)
                    new_actor_ids.append(beat.settlement.actor_id)
            if pending_beats:
                _apply_narrated_beats(round_state=round_state, beats=pending_beats, segment_id=plan.segment_id, config=config)
                pending_beats = []
            for actor_id in new_actor_ids:
                if actor_id:
                    _reveal_declaration(round_state, actor_id)
                    _mark_actor_executed(round_state, actor_id)
            if segment.public_interaction_prompt is not None:
                attack_prompt = None
                if segment.public_interaction_prompt.source_action_type == "attack":
                    attack_prompt = prepare_npc_attack_prompt(
                        save,
                        source_actor_id=segment.public_interaction_prompt.source_actor_id,
                        source_actor_name=segment.public_interaction_prompt.source_actor_name,
                        source_actor_type="npc",
                        source_action_summary=segment.public_interaction_prompt.source_action_summary,
                        source_speech_text=segment.public_interaction_prompt.source_speech_text,
                        source_action_prompt=segment.public_interaction_prompt.source_action_prompt,
                        source_action_target_name=segment.public_interaction_prompt.source_action_target_name,
                        round_state=round_state,
                        situation_delta_hint=segment.public_interaction_prompt.source_situation_delta_hint,
                        reputation_delta_hint=segment.public_interaction_prompt.source_reputation_delta_hint,
                        config=config,
                    )
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                if attack_prompt is not None:
                    round_state.pending_attack_prompt = attack_prompt
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE
                    scene_events.append(_phase_event(round_state, label="Public turn paused for player attack response"))
                else:
                    round_state.pending_interaction_prompt = segment.public_interaction_prompt
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
                    scene_events.append(_phase_event(round_state, label="Public turn paused for player interaction response"))
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    public_interaction_prompt=(None if attack_prompt is not None else segment.public_interaction_prompt),
                    public_attack_prompt=attack_prompt,
                    player_action_check_result=player_action_check_result,
                )
            if segment.public_opposed_prompt is not None:
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_OPPOSED
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                scene_events.append(_phase_event(round_state, label="Public turn paused for player opposed response"))
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    public_opposed_prompt=segment.public_opposed_prompt,
                    player_action_check_result=player_action_check_result,
                )
            if segment.pending_reaction is not None:
                round_state.pending_reaction_check_id = segment.pending_reaction.reaction_id
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_REACTION
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                scene_events.append(_phase_event(round_state, label="Public turn paused for player reaction"))
                return _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=scene_events,
                    impacts=impacts,
                    settlements=settlements,
                    round_completed=False,
                    reaction_check=segment.pending_reaction,
                    player_action_check_result=player_action_check_result,
                )
            round_state.phase = PublicTurnPhase.GM_PUSH
            round_state.narrative_status = PublicTurnRoundNarrationStatus.STREAMING
            _sync_compat_narration(round_state)
            save_public_turn_state_in_save(save, state)
            return _build_result(
                state=state,
                round_state=round_state,
                narration=round_state.accumulated_narration,
                scene_events=scene_events,
                impacts=impacts,
                settlements=settlements,
                round_completed=False,
                player_action_check_result=player_action_check_result,
            )

        if round_state.phase == PublicTurnPhase.GM_PUSH:
            gm_push = resolve_public_turn_gm_push(
                save,
                session_id=save.session_id,
                round_state=round_state,
                impacts=round_state.impacts,
                config=config,
            )
            round_state.environment_risk_level = gm_push.risk
            round_state.gm_push_summary = gm_push.narration
            round_state.gm_push_result = gm_push.result
            scene_events.extend(gm_push.scene_events)
            gm_push_settlement = PublicTurnSettlementEntry(
                entry_id=f"{round_state.round_id}_{len(round_state.settlement_entries) + 1}",
                round_id=round_state.round_id,
                entry_kind="gm_push",
                phase=PublicTurnPhase.GM_PUSH,
                order_index=len(round_state.settlement_entries),
                actor_id="gm_push",
                actor_name="GM推动",
                actor_type="environment",
                action_summary="推动场面进入下一步",
                speech_text="",
                gm_resolution_summary=gm_push.narration,
                gm_push_result=gm_push.result,
                situation_delta=sum(int(item.situation_delta or 0) for item in round_state.impacts),
                zone_reputation_delta=sum(int(item.zone_reputation_delta or 0) for item in round_state.impacts),
                environment_shift=sum(int(item.environment_shift or 0) for item in round_state.impacts),
            )
            _append_settlement(round_state, gm_push_settlement)
            settlements.append(gm_push_settlement)
            if gm_push.spawned_role is not None:
                intent = world._parse_player_intent(context_text or "public turn continues")
                audience_context = public_scene_runtime.build_public_audience_context(save, intent)
                scene_context = world._build_scene_context_payload(
                    save,
                    player_text=context_text or "public turn continues",
                    gm_narration=gm_push.narration,
                    recent_turn_count=4,
                )
                zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
                reputation_score = getattr(zone_metric, "reputation_score", 50)
                spawned_actor = {
                    "actor_id": gm_push.spawned_role.role_id,
                    "name": gm_push.spawned_role.name,
                    "actor_type": "npc",
                    "priority_reason": "gm_push_intervention",
                    "role": gm_push.spawned_role,
                }
                extra_events, extra_impact, extra_settlement, extra_reaction, extra_opposed = resolve_ai_actor_turn(
                    save,
                    actor=spawned_actor,
                    player_text=context_text or "public turn continues",
                    gm_summary=gm_push.narration,
                    round_state=round_state,
                    scene_context=scene_context,
                    audience_context=audience_context,
                    reputation_score=reputation_score,
                    config=config,
                )
                scene_events.extend(extra_events)
                if extra_impact is not None:
                    impacts.append(extra_impact)
                    round_state.impacts.append(extra_impact)
                if extra_settlement is not None:
                    _append_settlement(round_state, extra_settlement)
                    settlements.append(extra_settlement)
                    _mark_actor_executed(round_state, extra_settlement.actor_id)
                _sync_compat_narration(round_state)
                if extra_opposed is not None:
                    round_state.awaiting_player_action = False
                    round_state.awaiting_player_action_phase = PublicTurnPhase.GM_PUSH
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_OPPOSED
                    round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                    state.awaiting_player_entry = False
                    save_public_turn_state_in_save(save, state)
                    return _build_result(
                        state=state,
                        round_state=round_state,
                        narration=round_state.accumulated_narration,
                        scene_events=scene_events,
                        impacts=impacts,
                        settlements=settlements,
                        round_completed=False,
                        public_opposed_prompt=extra_opposed,
                        player_action_check_result=player_action_check_result,
                    )
                if extra_reaction is not None:
                    round_state.pending_reaction_check_id = extra_reaction.reaction_id
                    round_state.awaiting_player_action = False
                    round_state.awaiting_player_action_phase = PublicTurnPhase.GM_PUSH
                    round_state.phase = PublicTurnPhase.AWAITING_PLAYER_REACTION
                    round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                    state.awaiting_player_entry = False
                    save_public_turn_state_in_save(save, state)
                    return _build_result(
                        state=state,
                        round_state=round_state,
                        narration=round_state.accumulated_narration,
                        scene_events=scene_events,
                        impacts=impacts,
                        settlements=settlements,
                        round_completed=False,
                        reaction_check=extra_reaction,
                        player_action_check_result=player_action_check_result,
                    )
            _sync_compat_narration(round_state)
            round_state.narrative_status = PublicTurnRoundNarrationStatus.COMPLETE
            round_state.round_narration_status = PublicTurnRoundNarrationStatus.READY
            final_narration = round_state.accumulated_narration
            gm_push_event = next((item for item in gm_push.scene_events if item.kind == "public_turn_gm_push"), None)
            if gm_push_event is not None:
                round_state.gm_push_scene_event_id = gm_push_event.event_id
            scene_events.append(_round_end_event(round_state, narration=final_narration))
            final_presentation = _presentation_from_round(round_state)
            archived_turn_id = _complete_round(
                save,
                state=state,
                round_state=round_state,
                narration=final_narration,
                scene_events=scene_events,
                public_phase=PublicTurnPhase.GM_PUSH,
            )
            return PublicTurnRunResult(
                narration=final_narration,
                scene_events=scene_events,
                impacts=impacts,
                initiative_order=list(final_presentation.initiative_order),
                settlement_entries=settlements,
                presentation=final_presentation,
                round_completed=True,
                archived_sub_zone_turn_id=archived_turn_id,
                player_action_check_result=player_action_check_result,
            )

        if round_state.phase in {
            PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            PublicTurnPhase.AWAITING_PLAYER_REACTION,
            PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
            PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE,
            PublicTurnPhase.AWAITING_PLAYER_ATTACK_DEFENSE,
            PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK,
            PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE,
        }:
            raise ValueError("PUBLIC_TURN_AWAITING_REACTION")

        raise ValueError(f"PUBLIC_TURN_UNKNOWN_PHASE:{round_state.phase.value}")


def _merge_run_results(results: list[PublicTurnRunResult]) -> PublicTurnRunResult:
    if not results:
        raise ValueError("PUBLIC_TURN_NO_RESULTS")
    last = results[-1]
    merged_scene_events: list[SceneEvent] = []
    merged_impacts: list[PublicTurnImpact] = []
    merged_settlements: list[PublicTurnSettlementEntry] = []
    reaction_check: PlayerReactionCheck | None = None
    public_interaction_prompt: PublicTurnInteractionPrompt | None = None
    public_attack_prompt: PublicTurnAttackPrompt | None = None
    public_attack_defense_prompt: PublicTurnAttackDefensePrompt | None = None
    public_opposed_prompt: PublicTurnOpposedPrompt | None = None
    public_information_check_prompt: PublicTurnInformationCheckPrompt | None = None
    death_save_prompt: DeathSavePrompt | None = None
    player_action_check_result: ActionCheckResponse | None = None
    archived_turn_id: str | None = None
    for item in results:
        merged_scene_events.extend(item.scene_events)
        merged_impacts.extend(item.impacts)
        merged_settlements.extend(item.settlement_entries)
        reaction_check = item.reaction_check or reaction_check
        public_interaction_prompt = item.public_interaction_prompt or public_interaction_prompt
        public_attack_prompt = item.public_attack_prompt or public_attack_prompt
        public_attack_defense_prompt = item.public_attack_defense_prompt or public_attack_defense_prompt
        public_opposed_prompt = item.public_opposed_prompt or public_opposed_prompt
        public_information_check_prompt = item.public_information_check_prompt or public_information_check_prompt
        death_save_prompt = item.death_save_prompt or death_save_prompt
        player_action_check_result = item.player_action_check_result or player_action_check_result
        archived_turn_id = item.archived_sub_zone_turn_id or archived_turn_id
    return PublicTurnRunResult(
        narration=last.narration,
        scene_events=merged_scene_events,
        impacts=merged_impacts,
        initiative_order=last.initiative_order,
        settlement_entries=merged_settlements,
        presentation=last.presentation,
        round_completed=last.round_completed,
        archived_sub_zone_turn_id=archived_turn_id,
        reaction_check=reaction_check,
        public_interaction_prompt=public_interaction_prompt,
        public_attack_prompt=public_attack_prompt,
        public_attack_defense_prompt=public_attack_defense_prompt,
        public_opposed_prompt=public_opposed_prompt,
        public_information_check_prompt=public_information_check_prompt,
        death_save_prompt=death_save_prompt,
        player_action_check_result=player_action_check_result,
    )


def _iter_until_pause_or_end(
    save: SaveFile,
    *,
    state: PublicTurnState,
    context_text: str,
    gm_summary: str,
    config: ChatConfig | None,
    seed_beats: list[PublicTurnResolvedBeat] | None = None,
    seed_scene_events: list[SceneEvent] | None = None,
    seed_impacts: list[PublicTurnImpact] | None = None,
    player_action_check_result: ActionCheckResponse | None = None,
) -> Iterable[PublicTurnRunResult]:
    pending_beats = list(seed_beats or [])
    pending_scene_events = list(seed_scene_events or [])
    pending_impacts = list(seed_impacts or [])
    while True:
        step = _run_segment_step(
            save,
            state=state,
            context_text=context_text,
            gm_summary=gm_summary,
            config=config,
            seed_beats=pending_beats,
            seed_scene_events=pending_scene_events,
            seed_impacts=pending_impacts,
            player_action_check_result=player_action_check_result,
        )
        yield step
        pending_beats = []
        pending_scene_events = []
        pending_impacts = []
        current_round = state.current_round
        if (
            step.round_completed
            or step.reaction_check is not None
            or step.public_interaction_prompt is not None
            or step.public_opposed_prompt is not None
            or step.public_information_check_prompt is not None
        ):
            break
        if current_round is None:
            break
        if current_round.awaiting_player_action:
            break
        if current_round.phase in {
            PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            PublicTurnPhase.AWAITING_PLAYER_REACTION,
            PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
            PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK,
        }:
            break
        player_action_check_result = None


def _run_until_pause_or_end(
    save: SaveFile,
    *,
    state: PublicTurnState,
    context_text: str,
    gm_summary: str,
    config: ChatConfig | None,
    seed_beats: list[PublicTurnResolvedBeat] | None = None,
    seed_scene_events: list[SceneEvent] | None = None,
    seed_impacts: list[PublicTurnImpact] | None = None,
    player_action_check_result: ActionCheckResponse | None = None,
) -> list[PublicTurnRunResult]:
    return list(
        _iter_until_pause_or_end(
            save,
            state=state,
            context_text=context_text,
            gm_summary=gm_summary,
            config=config,
            seed_beats=seed_beats,
            seed_scene_events=seed_scene_events,
            seed_impacts=seed_impacts,
            player_action_check_result=player_action_check_result,
        )
    )


def run_round_entry_steps_in_save(
    save: SaveFile,
    *,
    entry_type: PublicTurnEntryType,
    config: ChatConfig | None,
    player_action: str | None = None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_entry_steps_in_save(
            save,
            entry_type=entry_type,
            config=config,
            player_action=player_action,
        )
    )


def iter_round_entry_steps_in_save(
    save: SaveFile,
    *,
    entry_type: PublicTurnEntryType,
    config: ChatConfig | None,
    player_action: str | None = None,
) -> Iterable[PublicTurnRunResult]:
    sync_pending_public_turn_in_save(save, save.session_id)
    state = get_public_turn_state_in_save(save)
    if state.current_round is not None and not state.awaiting_player_entry:
        raise ValueError("PUBLIC_TURN_ALREADY_RUNNING")
    if entry_type == PublicTurnEntryType.GOD_OVERRIDE and not is_god_mode(config):
        raise ValueError("PUBLIC_TURN_GOD_MODE_REQUIRED")
    round_state = _new_round(state)
    state.current_round = round_state
    state.awaiting_player_entry = False
    start_event = _phase_event(round_state, label="Public turn starts")
    _build_round_declarations(
        save,
        state,
        round_state=round_state,
        entry_type=entry_type,
        player_action=str(player_action or "").strip(),
        config=config,
    )
    save_public_turn_state_in_save(save, state)
    entry_context = _entry_seed_text(save, state, entry_type=entry_type, player_action=str(player_action or "").strip())
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text=entry_context,
        gm_summary="Public turn starts",
        config=config,
        seed_scene_events=[start_event],
    )


def start_round_in_save(
    save: SaveFile,
    *,
    entry_type: PublicTurnEntryType,
    config: ChatConfig | None,
    player_action: str | None = None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_entry_steps_in_save(
            save,
            entry_type=entry_type,
            config=config,
            player_action=player_action,
        )
    )


def run_round_continue_steps_in_save(
    save: SaveFile,
    *,
    submission: PublicTurnActionSubmission | None,
    interaction_response: PublicTurnInteractionResponseSubmission | None = None,
    attack_response: PublicTurnAttackResponseSubmission | None = None,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_continue_steps_in_save(
            save,
            submission=submission,
            interaction_response=interaction_response,
            attack_response=attack_response,
            action_check=action_check,
            config=config,
        )
    )


def iter_round_continue_steps_in_save(
    save: SaveFile,
    *,
    submission: PublicTurnActionSubmission | None,
    interaction_response: PublicTurnInteractionResponseSubmission | None = None,
    attack_response: PublicTurnAttackResponseSubmission | None = None,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    context_text = ""
    gm_summary = ""
    seed_scene_events: list[SceneEvent] = []
    seed_impacts: list[PublicTurnImpact] = []
    seed_beats: list[PublicTurnResolvedBeat] = []
    player_action_check_result: ActionCheckResponse | None = None

    if round_state.phase == PublicTurnPhase.AWAITING_PLAYER_INTERACTION:
        prompt = round_state.pending_interaction_prompt
        if prompt is None:
            raise ValueError("PUBLIC_TURN_INTERACTION_NOT_FOUND")
        if submission is not None:
            raise ValueError("PUBLIC_TURN_INTERACTION_REQUIRED")
        if interaction_response is None:
            raise ValueError("PUBLIC_TURN_INTERACTION_REQUIRED")
        if interaction_response.prompt_id != prompt.prompt_id:
            raise ValueError("PUBLIC_TURN_INTERACTION_MISMATCH")
        phase_before_pause = round_state.awaiting_player_action_phase or PublicTurnPhase.NORMAL_ADVANCEMENT
        original_phase = round_state.phase
        try:
            round_state.phase = phase_before_pause
            events, impact, settlement, player_action_check_result, opposed_prompt = resolve_interaction_prompt_submission(
                save,
                session_id=save.session_id,
                prompt=prompt,
                target_action_summary=interaction_response.action_text,
                target_speech_text=interaction_response.speech_text,
                target_response_kind=interaction_response.response_kind,
                round_state=round_state,
                config=config,
            )
        except Exception:
            round_state.phase = original_phase
            raise
        round_state.pending_interaction_prompt = None
        _clear_player_pause(round_state)
        seed_scene_events.extend(events)
        context_text = _normalize_narration(
            [prompt.source_action_summary, interaction_response.action_text, interaction_response.speech_text]
        )
        gm_summary = prompt.source_action_summary
        if opposed_prompt is not None:
            round_state.awaiting_player_action = False
            round_state.awaiting_player_action_phase = phase_before_pause
            round_state.phase = PublicTurnPhase.AWAITING_PLAYER_OPPOSED
            round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
            state.awaiting_player_entry = False
            _sync_compat_narration(round_state)
            save_public_turn_state_in_save(save, state)
            return [
                _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=seed_scene_events,
                    impacts=[],
                    settlements=[],
                    round_completed=False,
                    public_opposed_prompt=opposed_prompt,
                    player_action_check_result=player_action_check_result,
                )
            ]
        if impact is not None and settlement is not None:
            round_state.impacts.append(impact)
            _append_settlement(round_state, settlement)
            _mark_actor_executed(round_state, prompt.source_actor_id)
            if _response_consumes_actor_turn(
                response_kind=interaction_response.response_kind,
                action_text=interaction_response.action_text,
                speech_text=interaction_response.speech_text,
            ):
                _mark_actor_executed(round_state, prompt.target_actor_id)
            seed_impacts.append(impact)
            seed_beats.append(_make_seed_beat(scene_events=events, settlement=settlement, impact=impact))
        save_public_turn_state_in_save(save, state)
        return _iter_until_pause_or_end(
            save,
            state=state,
            context_text=context_text,
            gm_summary=gm_summary,
            config=config,
            seed_beats=seed_beats,
            seed_scene_events=seed_scene_events,
            seed_impacts=seed_impacts,
            player_action_check_result=player_action_check_result,
        )

    if round_state.phase == PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE:
        prompt = round_state.pending_attack_prompt
        if prompt is None:
            raise ValueError("PUBLIC_TURN_ATTACK_PROMPT_NOT_FOUND")
        if submission is not None:
            raise ValueError("PUBLIC_TURN_ATTACK_RESPONSE_REQUIRED")
        if attack_response is None:
            raise ValueError("PUBLIC_TURN_ATTACK_RESPONSE_REQUIRED")
        if attack_response.prompt_id != prompt.prompt_id:
            raise ValueError("PUBLIC_TURN_ATTACK_PROMPT_MISMATCH")
        phase_before_pause = round_state.awaiting_player_action_phase or PublicTurnPhase.NORMAL_ADVANCEMENT
        original_phase = round_state.phase
        try:
            round_state.phase = phase_before_pause
            events, impact, settlement, player_action_check_result, defense_prompt = resolve_attack_prompt_submission(
                save,
                session_id=save.session_id,
                prompt=prompt,
                target_action_summary=attack_response.action_text,
                target_speech_text=attack_response.speech_text,
                target_response_kind=attack_response.response_kind,
                round_state=round_state,
                config=config,
            )
        except Exception:
            round_state.phase = original_phase
            raise
        round_state.pending_attack_prompt = None
        _clear_player_pause(round_state)
        seed_scene_events.extend(events)
        context_text = _normalize_narration([prompt.source_action_summary, attack_response.action_text, attack_response.speech_text])
        gm_summary = prompt.source_action_summary
        if defense_prompt is not None:
            round_state.awaiting_player_action = False
            round_state.awaiting_player_action_phase = phase_before_pause
            round_state.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_DEFENSE
            round_state.pending_attack_defense_prompt = defense_prompt
            round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
            state.awaiting_player_entry = False
            _sync_compat_narration(round_state)
            save_public_turn_state_in_save(save, state)
            return [
                _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=seed_scene_events,
                    impacts=[],
                    settlements=[],
                    round_completed=False,
                    public_attack_defense_prompt=defense_prompt,
                    player_action_check_result=player_action_check_result,
                )
            ]
        if impact is not None and settlement is not None:
            round_state.impacts.append(impact)
            _append_settlement(round_state, settlement)
            _mark_actor_executed(round_state, prompt.source_actor_id)
            _mark_actor_executed(round_state, prompt.current_target_actor_id)
            seed_impacts.append(impact)
            seed_beats.append(_make_seed_beat(scene_events=events, settlement=settlement, impact=impact))
        save_public_turn_state_in_save(save, state)
        return _iter_until_pause_or_end(
            save,
            state=state,
            context_text=context_text,
            gm_summary=gm_summary,
            config=config,
            seed_beats=seed_beats,
            seed_scene_events=seed_scene_events,
            seed_impacts=seed_impacts,
            player_action_check_result=player_action_check_result,
        )

    if round_state.phase == PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE:
        prompt = round_state.pending_death_save_prompt
        if prompt is None:
            raise ValueError("PUBLIC_TURN_DEATH_SAVE_NOT_FOUND")
        if submission is not None:
            raise ValueError("PUBLIC_TURN_DEATH_SAVE_REQUIRED")
        if interaction_response is not None or attack_response is not None:
            raise ValueError("PUBLIC_TURN_DEATH_SAVE_REQUIRED")
        raise ValueError("PUBLIC_TURN_DEATH_SAVE_REQUIRED")

    if round_state.phase == PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK:
        prompt = round_state.pending_information_check_prompt
        if prompt is None:
            raise ValueError("PUBLIC_TURN_INFORMATION_CHECK_NOT_FOUND")
        if submission is not None:
            raise ValueError("PUBLIC_TURN_INFORMATION_CHECK_REQUIRED")
        if interaction_response is not None or attack_response is not None:
            raise ValueError("PUBLIC_TURN_INFORMATION_CHECK_REQUIRED")
        raise ValueError("PUBLIC_TURN_INFORMATION_CHECK_REQUIRED")

    if round_state.awaiting_player_action:
        if submission is None:
            raise ValueError("PUBLIC_TURN_ACTION_REQUIRED")
        if submission.actor_id != save.player_static_data.player_id:
            raise ValueError("PUBLIC_TURN_PLAYER_ONLY")
        phase_before_pause = round_state.awaiting_player_action_phase or round_state.phase
        player_action_status = save.player_static_data.dnd5e_sheet.role_action_status
        if player_action_status == "dead":
            raise ValueError("PUBLIC_TURN_PLAYER_DEAD")
        if player_action_status == "death_saving":
            if submission.action_text.strip():
                raise ValueError("PUBLIC_TURN_SPEECH_ONLY")
            _clear_player_pause(round_state)
            death_save_prompt = make_public_turn_death_save_prompt(
                round_state=round_state,
                actor_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                sheet=save.player_static_data.dnd5e_sheet,
                speech_text=submission.speech_text,
                phase_before_pause=phase_before_pause,
            )
            round_state.phase = PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE
            round_state.pending_death_save_prompt = death_save_prompt
            round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
            state.awaiting_player_entry = False
            _sync_compat_narration(round_state)
            save_public_turn_state_in_save(save, state)
            return [
                _build_result(
                    state=state,
                    round_state=round_state,
                    narration=round_state.accumulated_narration,
                    scene_events=[],
                    impacts=[],
                    settlements=[],
                    round_completed=False,
                    death_save_prompt=death_save_prompt,
                )
            ]
        if player_action_status == "unable_to_act":
            if submission.action_text.strip():
                raise ValueError("PUBLIC_TURN_SPEECH_ONLY")
            submission = PublicTurnActionSubmission(
                actor_id=submission.actor_id,
                action_text="",
                speech_text=submission.speech_text,
                source_phase=submission.source_phase,
                forced_first=submission.forced_first,
            )
            action_check = None
        _clear_player_pause(round_state)
        if action_check is not None and action_check.action_type == "attack":
            player_events, player_impact, player_settlement, player_action_check_result, attack_prompt = resolve_player_attack_submission(
                save,
                session_id=save.session_id,
                action_text=submission.action_text,
                speech_text=submission.speech_text,
                round_state=round_state,
                action_check=action_check,
                config=config,
            )
            seed_scene_events.extend(player_events)
            context_text = _normalize_narration([submission.action_text, submission.speech_text])
            gm_summary = submission.action_text
            if attack_prompt is not None:
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = round_state.phase
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE
                round_state.pending_attack_prompt = attack_prompt
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return [
                    _build_result(
                        state=state,
                        round_state=round_state,
                        narration=round_state.accumulated_narration,
                        scene_events=seed_scene_events,
                        impacts=[],
                        settlements=[],
                        round_completed=False,
                        public_attack_prompt=attack_prompt,
                        player_action_check_result=player_action_check_result,
                    )
                ]
            if player_impact is not None and player_settlement is not None:
                round_state.impacts.append(player_impact)
                _append_settlement(round_state, player_settlement)
                _mark_actor_executed(round_state, save.player_static_data.player_id)
                seed_impacts.append(player_impact)
                seed_beats.append(_make_seed_beat(scene_events=player_events, settlement=player_settlement, impact=player_impact))
                gm_summary = player_settlement.gm_resolution_summary
        else:
            player_events, player_impact, player_settlement, player_action_check_result, information_check_prompt = resolve_player_submission(
                save,
                session_id=save.session_id,
                action_text=submission.action_text,
                speech_text=submission.speech_text,
                round_state=round_state,
                action_check=action_check,
                config=config,
                include_information_check_prompt=True,
            )
            round_state.impacts.append(player_impact)
            _append_settlement(round_state, player_settlement)
            _mark_actor_executed(round_state, save.player_static_data.player_id)
            seed_scene_events.extend(player_events)
            seed_impacts.append(player_impact)
            seed_beats.append(_make_seed_beat(scene_events=player_events, settlement=player_settlement, impact=player_impact))
            context_text = _normalize_narration([submission.action_text, submission.speech_text])
            gm_summary = player_settlement.gm_resolution_summary
            if information_check_prompt is not None:
                information_check_prompt.metadata["settlement_entry_id"] = player_settlement.entry_id
                information_check_prompt.metadata["impact_index"] = len(round_state.impacts) - 1
                round_state.awaiting_player_action = False
                round_state.awaiting_player_action_phase = phase_before_pause
                round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK
                round_state.pending_information_check_prompt = information_check_prompt
                round_state.narrative_status = PublicTurnRoundNarrationStatus.PAUSED
                state.awaiting_player_entry = False
                _sync_compat_narration(round_state)
                save_public_turn_state_in_save(save, state)
                return [
                    _build_result(
                        state=state,
                        round_state=round_state,
                        narration=round_state.accumulated_narration,
                        scene_events=seed_scene_events,
                        impacts=seed_impacts,
                        settlements=[player_settlement],
                        round_completed=False,
                        public_information_check_prompt=information_check_prompt,
                        player_action_check_result=player_action_check_result,
                    )
                ]
    else:
        if submission is not None:
            raise ValueError("PUBLIC_TURN_NOT_AWAITING_PLAYER_ACTION")
        if interaction_response is not None:
            raise ValueError("PUBLIC_TURN_NOT_AWAITING_PLAYER_INTERACTION")
        if attack_response is not None:
            raise ValueError("PUBLIC_TURN_NOT_AWAITING_PLAYER_ATTACK")
        if round_state.phase in {
            PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            PublicTurnPhase.AWAITING_PLAYER_REACTION,
            PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
            PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE,
            PublicTurnPhase.AWAITING_PLAYER_ATTACK_DEFENSE,
            PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK,
            PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE,
        }:
            raise ValueError("PUBLIC_TURN_AWAITING_REACTION")
        context_text = "public turn continues"
        gm_summary = "round continues"
    save_public_turn_state_in_save(save, state)
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text=context_text,
        gm_summary=gm_summary,
        config=config,
        seed_beats=seed_beats,
        seed_scene_events=seed_scene_events,
        seed_impacts=seed_impacts,
        player_action_check_result=player_action_check_result,
    )


def continue_round_in_save(
    save: SaveFile,
    *,
    submission: PublicTurnActionSubmission | None,
    interaction_response: PublicTurnInteractionResponseSubmission | None = None,
    attack_response: PublicTurnAttackResponseSubmission | None = None,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_continue_steps_in_save(
            save,
            submission=submission,
            interaction_response=interaction_response,
            attack_response=attack_response,
            action_check=action_check,
            config=config,
        )
    )


def run_round_after_reaction_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    reaction_text: str,
    reaction_event: SceneEvent,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_after_reaction_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            reaction_text=reaction_text,
            reaction_event=reaction_event,
            config=config,
        )
    )


def iter_round_after_reaction_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    reaction_text: str,
    reaction_event: SceneEvent,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    _coerce_runtime_phase(round_state)
    round_state.phase = phase_before_pause or PublicTurnPhase.NORMAL_ADVANCEMENT
    round_state.pending_reaction_check_id = None
    _clear_player_pause(round_state)
    save_public_turn_state_in_save(save, state)
    resume_event = _phase_event(round_state, label="Reaction resolved, public turn resumes")
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text=reaction_text,
        gm_summary=reaction_text,
        config=config,
        seed_scene_events=[reaction_event, resume_event],
    )


def resume_round_after_reaction_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    reaction_text: str,
    reaction_event: SceneEvent,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_after_reaction_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            reaction_text=reaction_text,
            reaction_event=reaction_event,
            config=config,
        )
    )


def run_round_after_opposed_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnOpposedPrompt,
    target_action_summary: str,
    target_speech_text: str,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_after_opposed_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            target_action_summary=target_action_summary,
            target_speech_text=target_speech_text,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def iter_round_after_opposed_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnOpposedPrompt,
    target_action_summary: str,
    target_speech_text: str,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    _coerce_runtime_phase(round_state)
    round_state.phase = phase_before_pause or PublicTurnPhase.NORMAL_ADVANCEMENT
    round_state.pending_reaction_check_id = None
    _clear_player_pause(round_state)
    events, impact, settlement, action_result = resolve_opposed_prompt_submission(
        save,
        session_id=save.session_id,
        prompt=prompt,
        target_action_summary=target_action_summary,
        target_speech_text=target_speech_text,
        forced_dice_roll=forced_dice_roll,
        round_state=round_state,
        config=config,
    )
    round_state.impacts.append(impact)
    _append_settlement(round_state, settlement)
    _mark_actor_executed(round_state, prompt.source_actor_id)
    _mark_actor_executed(round_state, prompt.target_actor_id)
    save_public_turn_state_in_save(save, state)
    resume_event = _phase_event(round_state, label="Opposed exchange resolved, public turn resumes")
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text="\n".join(part for part in (prompt.source_action_summary, target_action_summary, target_speech_text) if part.strip()),
        gm_summary=settlement.gm_resolution_summary,
        config=config,
        seed_beats=[_make_seed_beat(scene_events=events, settlement=settlement, impact=impact)],
        seed_scene_events=[*events, resume_event],
        seed_impacts=[impact],
        player_action_check_result=action_result,
    )


def resume_round_after_opposed_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnOpposedPrompt,
    target_action_summary: str,
    target_speech_text: str,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_after_opposed_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            target_action_summary=target_action_summary,
            target_speech_text=target_speech_text,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def run_round_after_information_check_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnInformationCheckPrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_after_information_check_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def iter_round_after_information_check_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnInformationCheckPrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    _coerce_runtime_phase(round_state)
    round_state.phase = phase_before_pause or PublicTurnPhase.NORMAL_ADVANCEMENT
    round_state.pending_information_check_prompt = None
    round_state.awaiting_player_action = False
    round_state.awaiting_player_action_phase = None
    action_result = world.action_check(
        ActionCheckRequest(
            session_id=save.session_id,
            actor_role_id=prompt.actor_id,
            action_type="check",
            action_prompt="\n".join(
                part
                for part in (
                    str(prompt.metadata.get("action_text") or "").strip(),
                    str(prompt.metadata.get("speech_text") or "").strip(),
                    prompt.check_task.strip(),
                    prompt.stakes_summary.strip(),
                )
                if part
            ).strip()
            or prompt.check_task.strip()
            or prompt.stakes_summary.strip()
            or prompt.actor_name,
            source_context="public_turn",
            resolution_rule="static_dc",
            forced_dice_roll=forced_dice_roll,
            resolution_context="embedded",
            planned_ability_used=prompt.ability_used,
            planned_dc=prompt.dc,
            planned_time_spent_min=1,
            planned_requires_check=True,
            planned_check_task=prompt.check_task,
            config=config,
        )
    )
    settlement_id = str(prompt.metadata.get("settlement_entry_id") or "").strip()
    if settlement_id:
        settlement = next((item for item in round_state.settlement_entries if item.entry_id == settlement_id), None)
        if settlement is not None:
            settlement.followup_check = build_settlement_check(action_result)
            summary = str(action_result.narrative or "").strip()
            if summary:
                previous = settlement.gm_resolution_summary.strip()
                settlement.gm_resolution_summary = f"{previous}\n{summary}".strip() if previous else summary
    info_summary = str(action_result.narrative or "").strip() or prompt.check_task or prompt.stakes_summary
    save_public_turn_state_in_save(save, state)
    resume_event = _phase_event(round_state, label="Information check resolved, public turn resumes")
    info_event = world._new_scene_event(
        "public_turn_information_check",
        info_summary,
        actor_role_id=prompt.actor_id,
        actor_name=prompt.actor_name,
        metadata={
            "round_id": round_state.round_id,
            "phase": round_state.phase.value,
            "ability_used": prompt.ability_used,
            "dc": prompt.dc,
            "success": action_result.success,
            "critical": action_result.critical,
            "notice_state": prompt.notice_state,
            "check_task": prompt.check_task,
        },
    )
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text="\n".join(
            part
            for part in (
                str(prompt.metadata.get("action_text") or "").strip(),
                str(prompt.metadata.get("speech_text") or "").strip(),
                prompt.check_task.strip(),
            )
            if part
        ),
        gm_summary=info_summary,
        config=config,
        seed_scene_events=[info_event, resume_event],
    )


def resume_round_after_information_check_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnInformationCheckPrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_after_information_check_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def run_round_after_attack_defense_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnAttackDefensePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_after_attack_defense_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def iter_round_after_attack_defense_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnAttackDefensePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    _coerce_runtime_phase(round_state)
    round_state.phase = phase_before_pause or PublicTurnPhase.NORMAL_ADVANCEMENT
    _clear_player_pause(round_state)
    events, impact, settlement, action_result = resolve_attack_defense_prompt_submission(
        save,
        session_id=save.session_id,
        prompt=prompt,
        forced_dice_roll=forced_dice_roll,
        round_state=round_state,
        config=config,
    )
    round_state.impacts.append(impact)
    _append_settlement(round_state, settlement)
    _mark_actor_executed(round_state, prompt.source_actor_id)
    _mark_actor_executed(round_state, prompt.target_actor_id)
    save_public_turn_state_in_save(save, state)
    resume_event = _phase_event(round_state, label="Attack defense resolved, public turn resumes")
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text="\n".join(
            part for part in (prompt.source_action_summary, prompt.target_action_summary, prompt.target_speech_text) if part.strip()
        ),
        gm_summary=settlement.gm_resolution_summary,
        config=config,
        seed_beats=[_make_seed_beat(scene_events=events, settlement=settlement, impact=impact)],
        seed_scene_events=[*events, resume_event],
        seed_impacts=[impact],
        player_action_check_result=action_result,
    )


def resume_round_after_attack_defense_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: PublicTurnAttackDefensePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_after_attack_defense_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def run_round_after_death_save_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: DeathSavePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> list[PublicTurnRunResult]:
    return list(
        iter_round_after_death_save_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )


def iter_round_after_death_save_steps_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: DeathSavePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> Iterable[PublicTurnRunResult]:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    _coerce_runtime_phase(round_state)
    round_state.phase = phase_before_pause or PublicTurnPhase.NORMAL_ADVANCEMENT
    _clear_player_pause(round_state)
    events, impact, settlement = resolve_public_turn_death_save(
        save,
        prompt=prompt,
        round_state=round_state,
        forced_dice_roll=forced_dice_roll,
    )
    round_state.impacts.append(impact)
    _append_settlement(round_state, settlement)
    _mark_actor_executed(round_state, prompt.actor_id)
    save_public_turn_state_in_save(save, state)
    resume_event = _phase_event(round_state, label="Death save resolved, public turn resumes")
    return _iter_until_pause_or_end(
        save,
        state=state,
        context_text=str(prompt.metadata.get("speech_text") or ""),
        gm_summary=settlement.gm_resolution_summary,
        config=config,
        seed_beats=[_make_seed_beat(scene_events=events, settlement=settlement, impact=impact)],
        seed_scene_events=[*events, resume_event],
        seed_impacts=[impact],
    )


def resume_round_after_death_save_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    prompt: DeathSavePrompt,
    forced_dice_roll: int,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    return _merge_run_results(
        run_round_after_death_save_steps_in_save(
            save,
            phase_before_pause=phase_before_pause,
            prompt=prompt,
            forced_dice_roll=forced_dice_roll,
            config=config,
        )
    )
