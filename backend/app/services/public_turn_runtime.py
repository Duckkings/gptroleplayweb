from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.models.schemas import (
    ChatConfig,
    EnvironmentRiskLevel,
    PlayerReactionCheck,
    PublicTurnActionSubmission,
    PublicTurnEntryType,
    PublicTurnImpact,
    PublicTurnPhase,
    PublicTurnRound,
    PublicTurnState,
    SaveFile,
    SceneEvent,
)
from app.services import world_service as world
from app.services.public_turn_resolution import (
    build_initiative_declarations,
    build_player_initiative_declaration,
    finalize_initiative_totals,
    resolve_ai_round,
    resolve_player_submission,
    resolve_situation,
)
from app.services.public_turn_state_store import get_public_turn_state_in_save, save_public_turn_state_in_save, sync_pending_public_turn_in_save

_GOD_MODE_MARKER = "上帝模式"


@dataclass
class PublicTurnRunResult:
    narration: str
    scene_events: list[SceneEvent]
    impacts: list[PublicTurnImpact]
    round_completed: bool
    archived_sub_zone_turn_id: str | None = None
    reaction_check: PlayerReactionCheck | None = None


def is_god_mode(config: ChatConfig | None) -> bool:
    return bool(config is not None and _GOD_MODE_MARKER in str(config.gm_prompt or ""))


def _phase_event(round_state: PublicTurnRound, *, label: str = "") -> SceneEvent:
    return world._new_scene_event(
        "public_turn_phase",
        label or f"公开回合阶段切换：{round_state.phase.value}",
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
    ) or "无人参与抢先。"
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


def _next_round_number(state: PublicTurnState) -> int:
    if state.current_round is not None:
        return int(state.current_round.round_number) + 1
    if state.round_history:
        return int(state.round_history[-1].round_number) + 1
    return 1


def _new_round(state: PublicTurnState, *, entry_type: PublicTurnEntryType) -> PublicTurnRound:
    phase = (
        PublicTurnPhase.INITIATIVE_DECLARATION
        if entry_type in {PublicTurnEntryType.INITIATIVE, PublicTurnEntryType.GOD_OVERRIDE}
        else PublicTurnPhase.NORMAL_ADVANCEMENT
    )
    return PublicTurnRound(
        round_id=f"ptround_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        round_number=_next_round_number(state),
        phase=phase,
        environment_risk_level=state.environment_risk_level,
        situation_dc=state.situation_dc,
        current_actor_id=None,
        awaiting_player_action=True,
        awaiting_player_action_phase=phase,
    )


def _normalize_narration(parts: Iterable[str]) -> str:
    return "\n".join(part.strip() for part in parts if str(part or "").strip()).strip()


def start_round_in_save(
    save: SaveFile,
    *,
    entry_type: PublicTurnEntryType,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    sync_pending_public_turn_in_save(save, save.session_id)
    state = get_public_turn_state_in_save(save)
    if state.current_round is not None and not state.awaiting_player_entry:
        raise ValueError("PUBLIC_TURN_ALREADY_RUNNING")
    if entry_type == PublicTurnEntryType.GOD_OVERRIDE and not is_god_mode(config):
        raise ValueError("PUBLIC_TURN_GOD_MODE_REQUIRED")
    round_state = _new_round(state, entry_type=entry_type)
    round_state.current_actor_id = save.player_static_data.player_id
    state.current_round = round_state
    state.awaiting_player_entry = False
    save_public_turn_state_in_save(save, state)
    label = (
        "公开回合开始：等待玩家抢先声明。"
        if round_state.phase == PublicTurnPhase.INITIATIVE_DECLARATION
        else "公开回合开始：等待玩家进行本轮行动。"
    )
    return PublicTurnRunResult(
        narration=label,
        scene_events=[_phase_event(round_state, label=label)],
        impacts=[],
        round_completed=False,
    )


def continue_round_in_save(
    save: SaveFile,
    *,
    submission: PublicTurnActionSubmission,
    config: ChatConfig | None,
) -> PublicTurnRunResult:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    if not round_state.awaiting_player_action:
        raise ValueError("PUBLIC_TURN_NOT_AWAITING_PLAYER_ACTION")
    if submission.actor_id != save.player_static_data.player_id:
        raise ValueError("PUBLIC_TURN_PLAYER_ONLY")
    narration_parts: list[str] = []
    scene_events: list[SceneEvent] = []
    impacts: list[PublicTurnImpact] = []
    phase_before_pause: PublicTurnPhase = round_state.phase

    if round_state.phase == PublicTurnPhase.INITIATIVE_DECLARATION:
        intent_text = f"{submission.action_text}\n{submission.speech_text}".strip()
        declarations = [
            build_player_initiative_declaration(
                save,
                action_text=submission.action_text,
                speech_text=submission.speech_text,
                forced_first=bool(submission.forced_first),
            ),
            *build_initiative_declarations(
                save,
                player_action_text=intent_text,
                addressed_role_name="",
                incoming_target_candidates=[],
                config=config,
            ),
        ]
        round_state.initiative_declarations = finalize_initiative_totals(declarations)
        round_state.phase = PublicTurnPhase.INITIATIVE_EXECUTION
        round_state.awaiting_player_action = False
        round_state.awaiting_player_action_phase = None
        scene_events.append(_phase_event(round_state, label="进入抢先执行阶段。"))
        scene_events.append(_initiative_event(round_state))

    player_narration, player_events, player_impact = resolve_player_submission(
        save,
        session_id=save.session_id,
        action_text=submission.action_text,
        speech_text=submission.speech_text,
        round_state=round_state,
        config=config,
    )
    narration_parts.append(player_narration)
    scene_events.extend(player_events)
    impacts.append(player_impact)
    round_state.executed_actor_ids.append(save.player_static_data.player_id)
    round_state.impacts.append(player_impact)

    if round_state.phase == PublicTurnPhase.INITIATIVE_EXECUTION:
        round_state.phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        scene_events.append(_phase_event(round_state, label="进入常规推进阶段。"))

    ai_narration, ai_events, ai_impacts, pending_reaction = resolve_ai_round(
        save,
        session_id=save.session_id,
        player_text=_normalize_narration([submission.action_text, submission.speech_text]),
        gm_summary=player_narration,
        round_state=round_state,
        exclude_actor_ids=set(round_state.executed_actor_ids),
        config=config,
    )
    narration_parts.append(ai_narration)
    scene_events.extend(ai_events)
    impacts.extend(ai_impacts)
    round_state.impacts.extend(ai_impacts)
    round_state.executed_actor_ids.extend(
        impact.actor_id for impact in ai_impacts if impact.actor_id not in round_state.executed_actor_ids
    )

    if pending_reaction is not None:
        round_state.pending_reaction_check_id = pending_reaction.reaction_id
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_REACTION
        round_state.awaiting_player_action = False
        round_state.awaiting_player_action_phase = phase_before_pause
        state.awaiting_player_entry = False
        state.current_round = round_state
        save_public_turn_state_in_save(save, state)
        scene_events.append(_phase_event(round_state, label="公开回合被玩家反应检定打断。"))
        return PublicTurnRunResult(
            narration=_normalize_narration(narration_parts),
            scene_events=scene_events,
            impacts=impacts,
            round_completed=False,
            reaction_check=pending_reaction,
        )

    round_state.phase = PublicTurnPhase.SITUATION_ADVANCEMENT
    scene_events.append(_phase_event(round_state, label="进入事态推进阶段。"))
    situation_narration, situation_events, risk = resolve_situation(
        save,
        session_id=save.session_id,
        round_state=round_state,
        impacts=round_state.impacts,
    )
    round_state.environment_risk_level = risk
    narration_parts.append(situation_narration)
    scene_events.extend(situation_events)
    final_narration = _normalize_narration(narration_parts)
    scene_events.append(_round_end_event(round_state, narration=final_narration))
    round_state.completed_at = world._utc_now()
    state.environment_risk_level = risk
    state.round_history.append(round_state.model_copy(deep=True))
    state.round_history = state.round_history[-state.max_history :]
    state.current_round = None
    state.awaiting_player_entry = True
    save_public_turn_state_in_save(save, state)
    archived_turn_id = world._record_sub_zone_chat_turn(
        save,
        source="main_chat",
        player_mode="active",
        player_action=submission.action_text,
        player_speech=submission.speech_text,
        player_action_check={},
        gm_narration=final_narration,
        events=scene_events,
        public_round_id=round_state.round_id,
        public_round_number=round_state.round_number,
        public_phase=PublicTurnPhase.SITUATION_ADVANCEMENT,
    )
    return PublicTurnRunResult(
        narration=final_narration,
        scene_events=scene_events,
        impacts=impacts,
        round_completed=True,
        archived_sub_zone_turn_id=archived_turn_id,
    )


def resume_round_after_reaction_in_save(
    save: SaveFile,
    *,
    phase_before_pause: PublicTurnPhase | None,
    reaction_text: str,
    reaction_event: SceneEvent,
) -> PublicTurnRunResult:
    state = get_public_turn_state_in_save(save)
    if state.current_round is None:
        raise ValueError("PUBLIC_TURN_NOT_ACTIVE")
    round_state = state.current_round
    round_state.phase = phase_before_pause or PublicTurnPhase.SITUATION_ADVANCEMENT
    round_state.pending_reaction_check_id = None
    scene_events = [reaction_event, _phase_event(round_state, label="玩家反应检定完成，回合继续。")]
    narration_parts = [reaction_text]
    round_state.phase = PublicTurnPhase.SITUATION_ADVANCEMENT
    situation_narration, situation_events, risk = resolve_situation(
        save,
        session_id=save.session_id,
        round_state=round_state,
        impacts=round_state.impacts,
    )
    round_state.environment_risk_level = risk
    narration_parts.append(situation_narration)
    scene_events.extend(situation_events)
    final_narration = _normalize_narration(narration_parts)
    scene_events.append(_round_end_event(round_state, narration=final_narration))
    round_state.completed_at = world._utc_now()
    state.environment_risk_level = risk
    state.round_history.append(round_state.model_copy(deep=True))
    state.round_history = state.round_history[-state.max_history :]
    state.current_round = None
    state.awaiting_player_entry = True
    save_public_turn_state_in_save(save, state)
    archived_turn_id = world._record_sub_zone_chat_turn(
        save,
        source="main_chat",
        player_mode="active",
        player_action="",
        player_speech="",
        player_action_check={},
        gm_narration=final_narration,
        events=scene_events,
        public_round_id=round_state.round_id,
        public_round_number=round_state.round_number,
        public_phase=PublicTurnPhase.SITUATION_ADVANCEMENT,
    )
    return PublicTurnRunResult(
        narration=final_narration,
        scene_events=scene_events,
        impacts=list(round_state.impacts),
        round_completed=True,
        archived_sub_zone_turn_id=archived_turn_id,
    )
