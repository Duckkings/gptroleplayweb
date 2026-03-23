from __future__ import annotations

from app.models.schemas import (
    DeathSavePrompt,
    PendingTurnContinueResponse,
    PendingTurnState,
    PublicTurnPhase,
)
from app.services import world_service as world
from app.services.pending_turn_service import clear_pending_turn, save_pending_turn
from app.services import zone_metric_service


def _severe_wound_threshold(max_hp: int) -> int:
    return max(1, (max(1, int(max_hp)) + 1) // 2)


def _enter_dying_state(sheet, *, timestamp: str) -> None:
    sheet.death_state.life_status = "dying"
    sheet.death_state.death_save_successes = 0
    sheet.death_state.death_save_failures = 0
    sheet.death_state.updated_at = timestamp
    sheet.is_dead = False
    sheet.role_action_status = "death_saving"
    sheet.status_flags = ["dying", "unconscious", "prone"]


def _recover_from_death_save(sheet, *, timestamp: str) -> None:
    sheet.hit_points.current = max(1, int(sheet.hit_points.current or 0))
    sheet.death_state.life_status = "healthy"
    sheet.death_state.death_save_successes = 0
    sheet.death_state.death_save_failures = 0
    sheet.death_state.updated_at = timestamp
    sheet.is_dead = False
    sheet.role_action_status = "free_action"
    sheet.status_flags = [flag for flag in list(sheet.status_flags or []) if flag not in {"dying", "unconscious", "prone", "dead", "stable"}]


def _mark_dead(sheet, *, timestamp: str, cause: str) -> None:
    sheet.death_state.life_status = "dead"
    sheet.death_state.last_death_at = timestamp
    sheet.death_state.last_death_cause = cause
    sheet.death_state.updated_at = timestamp
    sheet.death_state.death_save_failures = 3
    sheet.is_dead = True
    sheet.role_action_status = "dead"
    sheet.status_flags = ["dead"]


def _make_prompt(session_id: str, actor_id: str, actor_name: str, sheet) -> DeathSavePrompt:
    return DeathSavePrompt(
        prompt_id=f"{session_id}_{actor_id}_death_save",
        round_id=f"main_chat_{session_id}",
        phase=PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE,
        actor_id=actor_id,
        actor_name=actor_name,
        successes=int(sheet.death_state.death_save_successes or 0),
        failures=int(sheet.death_state.death_save_failures or 0),
        dc=10,
        severe_wound_threshold=_severe_wound_threshold(int(sheet.hit_points.maximum or 1)),
        speech_only=True,
        metadata={"context_kind": "main_chat"},
    )


def _pending_response_from_state(state: PendingTurnState) -> PendingTurnContinueResponse:
    save = world.SaveFile.model_validate(state.staged_save)
    return PendingTurnContinueResponse(
        session_id=state.session_id,
        pending_turn_id=state.pending_turn_id,
        flow_kind="main_chat",
        status=state.status,
        reply_text=state.accumulated_reply_text,
        scene_events=list(state.accumulated_scene_events),
        tool_events=list(state.accumulated_tool_events),
        death_save_prompt=state.death_save_prompt,
        current_zone_metric=zone_metric_service.get_current_zone_metric(save, create=True),
    )


def zero_player_hp_for_debug(session_id: str) -> PendingTurnContinueResponse:
    clear_pending_turn(session_id)
    save = world.get_current_save(default_session_id=session_id)
    save.session_id = session_id
    timestamp = world._utc_now()
    sheet = save.player_static_data.dnd5e_sheet
    hp_before = int(sheet.hit_points.current or 0)
    sheet.hit_points.temporary = 0
    sheet.hit_points.current = 0
    _enter_dying_state(sheet, timestamp=timestamp)
    damage = max(0, hp_before)
    damage_event = world._new_scene_event(
        "damage_resolution",
        f"{save.player_static_data.name}受到{damage}点伤害，HP {hp_before}->0。",
        actor_role_id=save.player_static_data.player_id,
        actor_name="Debug",
        metadata={
            "context_kind": "debug",
            "actor_type": "system",
            "source_actor_id": "debug_system",
            "source_actor_name": "Debug",
            "target_actor_id": save.player_static_data.player_id,
            "target_actor_name": save.player_static_data.name,
            "target_actor_type": "player",
            "damage": damage,
            "damage_type": "debug",
            "hp_before": hp_before,
            "hp_after": 0,
            "hp_delta": -damage,
            "temp_hp_absorbed": 0,
            "life_status_after": "dying",
            "triggered_death_save": True,
            "declared_death": False,
        },
    )
    death_event = world._new_scene_event(
        "player_entered_death_save",
        f"{save.player_static_data.name}进入死亡豁免。",
        actor_role_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        metadata={"successes": 0, "failures": 0, "context_kind": "debug"},
    )
    prompt = _make_prompt(session_id, save.player_static_data.player_id, save.player_static_data.name, sheet)
    world._recompute_player_derived(save.player_static_data)
    world.save_current(save)
    state = PendingTurnState(
        pending_turn_id=f"pending_death_{session_id}",
        session_id=session_id,
        flow_kind="main_chat",
        status="awaiting_player_death_save",
        staged_save=save.model_dump(mode="json"),
        original_request={"session_id": session_id, "debug_kind": "zero_hp"},
        accumulated_reply_text=f"{save.player_static_data.name}倒下了，必须立刻进行死亡豁免。",
        accumulated_scene_events=[damage_event, death_event],
        accumulated_tool_events=[],
        death_save_prompt=prompt,
    )
    save_pending_turn(state)
    return _pending_response_from_state(state)


def continue_main_chat_death_save(state: PendingTurnState, *, forced_dice_roll: int) -> PendingTurnContinueResponse:
    save = world.SaveFile.model_validate(state.staged_save)
    sheet = save.player_static_data.dnd5e_sheet
    timestamp = world._utc_now()
    roll = max(1, min(int(forced_dice_roll), 20))
    if roll == 20:
        _recover_from_death_save(sheet, timestamp=timestamp)
        outcome = "revived"
    else:
        if roll == 1:
            sheet.death_state.death_save_failures = min(3, int(sheet.death_state.death_save_failures or 0) + 2)
        elif roll >= 10:
            sheet.death_state.death_save_successes = min(3, int(sheet.death_state.death_save_successes or 0) + 1)
        else:
            sheet.death_state.death_save_failures = min(3, int(sheet.death_state.death_save_failures or 0) + 1)
        sheet.death_state.updated_at = timestamp
        if int(sheet.death_state.death_save_successes or 0) >= 3:
            _recover_from_death_save(sheet, timestamp=timestamp)
            outcome = "revived"
        elif int(sheet.death_state.death_save_failures or 0) >= 3:
            _mark_dead(sheet, timestamp=timestamp, cause="main_chat_death_save")
            outcome = "dead"
        else:
            outcome = "continue"
    summary = (
        f"{save.player_static_data.name}掷出{roll}点，奇迹般恢复了意识。"
        if outcome == "revived"
        else (
            f"{save.player_static_data.name}掷出{roll}点，死亡豁免失败，彻底死亡。"
            if outcome == "dead"
            else f"{save.player_static_data.name}掷出{roll}点，死亡豁免继续。"
        )
    )
    result_event = world._new_scene_event(
        "player_death_save_result",
        summary,
        actor_role_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        metadata={
            "roll": roll,
            "successes": int(sheet.death_state.death_save_successes or 0),
            "failures": int(sheet.death_state.death_save_failures or 0),
            "outcome": outcome,
        },
    )
    scene_events = [*list(state.accumulated_scene_events), result_event]
    if outcome == "dead":
        scene_events.append(
            world._new_scene_event(
                "player_died",
                f"{save.player_static_data.name}死亡。",
                actor_role_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                metadata={"context_kind": "main_chat"},
            )
        )
    world._recompute_player_derived(save.player_static_data)
    world.save_current(save)
    state.staged_save = save.model_dump(mode="json")
    state.accumulated_scene_events = scene_events
    state.accumulated_reply_text = "\n".join(part for part in [state.accumulated_reply_text, summary] if part).strip()
    if outcome == "continue":
        state.death_save_prompt = _make_prompt(state.session_id, save.player_static_data.player_id, save.player_static_data.name, sheet)
        state.status = "awaiting_player_death_save"
        save_pending_turn(state)
        return _pending_response_from_state(state)
    clear_pending_turn(state.session_id)
    return PendingTurnContinueResponse(
        session_id=state.session_id,
        pending_turn_id=None,
        flow_kind="main_chat",
        status="completed",
        reply_text=state.accumulated_reply_text,
        scene_events=scene_events,
        tool_events=list(state.accumulated_tool_events),
        current_zone_metric=zone_metric_service.get_current_zone_metric(save, create=True),
    )
