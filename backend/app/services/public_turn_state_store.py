from __future__ import annotations

from app.models.schemas import AreaSubZone, PublicTurnPhase, PublicTurnState, SaveFile, SubZoneChatContext
from app.services.pending_turn_service import clear_pending_turn, load_pending_turn
from app.services import world_service as world


def ensure_sub_zone_chat_context(sub_zone: AreaSubZone | None) -> SubZoneChatContext | None:
    if sub_zone is None:
        return None
    context = getattr(sub_zone, "chat_context", None)
    if context is None:
        sub_zone.chat_context = SubZoneChatContext()
    elif getattr(context, "public_turn_state", None) is None:
        context.public_turn_state = PublicTurnState()
        context.version = "0.2.0"
    return sub_zone.chat_context


def current_sub_zone(save: SaveFile) -> AreaSubZone | None:
    return world._current_sub_zone(save)


def get_public_turn_state_in_save(save: SaveFile) -> PublicTurnState:
    world._ensure_area_snapshot(save)
    context = ensure_sub_zone_chat_context(current_sub_zone(save))
    if context is None:
        return PublicTurnState()
    if getattr(context, "public_turn_state", None) is None:
        context.public_turn_state = PublicTurnState()
        context.version = "0.2.0"
    round_state = context.public_turn_state.current_round
    if round_state is not None and round_state.phase == PublicTurnPhase.SITUATION_ADVANCEMENT:
        round_state.phase = PublicTurnPhase.GM_PUSH
    context.updated_at = world._utc_now()
    return context.public_turn_state


def save_public_turn_state_in_save(save: SaveFile, state: PublicTurnState) -> PublicTurnState:
    world._ensure_area_snapshot(save)
    context = ensure_sub_zone_chat_context(current_sub_zone(save))
    if context is None:
        return state
    state.updated_at = world._utc_now()
    context.public_turn_state = state
    context.version = "0.2.0"
    context.updated_at = state.updated_at
    return state


def clear_public_turn_round_in_save(save: SaveFile) -> PublicTurnState:
    state = get_public_turn_state_in_save(save)
    state.current_round = None
    state.awaiting_player_entry = True
    state.updated_at = world._utc_now()
    return save_public_turn_state_in_save(save, state)


def sync_pending_public_turn_in_save(save: SaveFile, session_id: str) -> PublicTurnState:
    state = get_public_turn_state_in_save(save)
    pending = load_pending_turn(session_id)
    if pending is None or pending.flow_kind != "public_turn" or pending.public_round_id is None:
        return state
    if state.current_round is None or state.current_round.round_id != pending.public_round_id:
        return state
    if (
        pending.status in {"awaiting_reaction", "awaiting_opposed"}
        and state.current_round.pending_interaction_prompt is not None
        and state.current_round.pending_interaction_prompt.source_action_type == "attack"
        and pending.public_attack_prompt is None
        and pending.public_attack_defense_prompt is None
    ):
        clear_pending_turn(session_id)
        state.current_round.pending_interaction_prompt = None
        state.current_round.awaiting_player_action = False
        state.current_round.awaiting_player_action_phase = None
        state.current_round.phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        state.updated_at = world._utc_now()
        return save_public_turn_state_in_save(save, state)
    if pending.status == "awaiting_opposed":
        state.current_round.phase = PublicTurnPhase.AWAITING_PLAYER_OPPOSED
    elif pending.status == "awaiting_player_attack_response":
        state.current_round.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_RESPONSE
        state.current_round.pending_attack_prompt = pending.public_attack_prompt
    elif pending.status == "awaiting_player_attack_defense":
        state.current_round.phase = PublicTurnPhase.AWAITING_PLAYER_ATTACK_DEFENSE
        state.current_round.pending_attack_defense_prompt = pending.public_attack_defense_prompt
    elif pending.status == "awaiting_player_death_save":
        state.current_round.phase = PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE
        state.current_round.pending_death_save_prompt = pending.death_save_prompt
    elif pending.pending_reaction is not None:
        state.current_round.pending_reaction_check_id = pending.pending_reaction.reaction_id
        state.current_round.phase = PublicTurnPhase.AWAITING_PLAYER_REACTION
    state.awaiting_player_entry = False
    state.updated_at = world._utc_now()
    return save_public_turn_state_in_save(save, state)
