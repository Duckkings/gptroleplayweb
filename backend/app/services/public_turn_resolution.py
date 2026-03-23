from __future__ import annotations

import json
import random
from typing import Any, Literal

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    ChatConfig,
    DeadNpcRecord,
    DeathSavePrompt,
    EnvironmentRiskLevel,
    InitiativeDeclaration,
    NpcRoleCard,
    PlayerReactionCheck,
    PublicTurnActorType,
    PublicTurnAttackDefensePrompt,
    PublicTurnAttackPrompt,
    PublicTurnGmPushResult,
    PublicTurnImpact,
    PublicTurnInteractionPrompt,
    PublicTurnInitiativeEntry,
    PublicTurnInformationCheckPrompt,
    PublicTurnOpposedPrompt,
    PublicTurnOpposedPlanRequest,
    PublicTurnPhase,
    PublicTurnPlayerActionCheck,
    PublicTurnRound,
    PublicTurnSettlementCheck,
    PublicTurnSettlementEntry,
    PublicTurnWorldImpactType,
    SaveFile,
    SceneEvent,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services.ai_protocol_contract_service import (
    EnumContractField,
    allow_protocol_repair,
    render_enum_pool_text,
    validate_or_repair_json_payload,
)
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import reaction_check_service
from app.services import world_service as world
from app.services.actor_resource_service import consume_action_resources_in_profile
from app.services.actor_resource_service import consume_submission_resources_in_save
from app.services.encounter_service import apply_active_encounter_situation_delta_in_save
from app.services.public_turn_interaction_service import build_ai_interaction_response
from app.services.public_turn_interaction_service import classify_player_interaction_response
from app.services.public_turn_interaction_service import infer_world_impact_type
from app.services.public_turn_interaction_service import InteractionResponseClassification
from app.services.public_turn_interaction_service import is_direct_world_counter_response
from app.services.public_turn_interaction_service import public_turn_actor_type
from app.services.public_turn_interaction_service import ResolvedInteractionTarget
from app.services.public_turn_interaction_service import resolve_interaction_target
from app.services.public_turn_interaction_service import resolve_speech_target
from app.services.public_turn_interaction_service import validate_prompt_target_alignment
from app.services import zone_metric_service
from app.services.generation_debug_log_service import current_generation_debug_log
from app.services.public_turn_target_context_service import build_targeted_actor_text
from app.services.public_turn_attack_service import (
    PublicTurnResolvedAttackTarget,
    assess_public_turn_attack,
    attack_ability_modifier,
    classify_attack_response,
    definition_damage_payload,
    generate_attack_outcome_narration,
    resolve_attack_candidates,
    resolve_attack_definition,
    reveal_hidden_public_target,
    roll_damage_dice,
    select_aoe_threatened_targets,
)
from app.services.public_turn_candidates import actor_name_match, dex_modifier_for_actor, initiative_actor_rows, public_turn_normal_actor_rows, visible_actor_rows
from app.services.public_turn_effects import (
    apply_player_npc_reactions,
    apply_player_team_reactions,
    apply_round_reputation,
    build_impact,
    check_bonus,
    next_environment_risk,
    public_turn_zone_reputation_allowed,
    relation_delta_from_result,
    reputation_delta_from_situation,
)

InitiativeMode = Literal["hostile_only", "priority_action"]



_PUBLIC_TURN_DAMAGE_KIND_FIELDS = (
    EnumContractField(field_path="effect_kind", allowed_ids=("none", "damage", "healing", "control", "utility")),
    EnumContractField(
        field_path="area_mode",
        allowed_ids=("single", "multi_target", "sphere", "cone", "line", "cylinder", "emanation"),
    ),
    EnumContractField(
        field_path="rules_basis",
        allowed_ids=("none", "dnd5e_spell", "dnd5e_weapon", "narrative"),
    ),
    EnumContractField(
        field_path="damage_application_mode",
        allowed_ids=("none", "on_success", "on_success_half_on_failure", "always"),
    ),
    EnumContractField(
        field_path="damage_type",
        allowed_ids=(
            "none",
            "acid",
            "bludgeoning",
            "cold",
            "fire",
            "force",
            "lightning",
            "necrotic",
            "piercing",
            "poison",
            "psychic",
            "radiant",
            "slashing",
            "thunder",
        ),
    ),
)


def _empty_public_turn_damage_bundle() -> dict[str, object]:
    return {
        "effect_kind": "none",
        "area_mode": "single",
        "rules_basis": "none",
        "spell_name": "",
        "damage_application_mode": "none",
        "damage_type": "none",
        "base_damage": 0,
        "affected_targets": [],
        "reason": "",
    }


def _public_turn_combat_target_candidates(save: SaveFile) -> list[ResolvedInteractionTarget]:
    candidates: list[ResolvedInteractionTarget] = [
        ResolvedInteractionTarget(
            actor_id=save.player_static_data.player_id,
            name=save.player_static_data.name,
            actor_kind="player",
            actor_type=PublicTurnActorType.PLAYER,
        )
    ]
    team_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
    visible_ids = {role.role_id for role in world._visible_public_roles(save)}
    visible_ids.update(team_ids)
    for role in save.role_pool:
        if role.role_id not in visible_ids:
            continue
        candidates.append(
            ResolvedInteractionTarget(
                actor_id=role.role_id,
                name=role.name,
                actor_kind="npc",
                actor_type=(PublicTurnActorType.TEAM if role.role_id in team_ids else PublicTurnActorType.NPC),
                role=role,
            )
        )
    reserved_name_keys = {public_scene_legacy._normalize_actor_name_key(item.name) for item in candidates}
    temp_npcs = public_scene_legacy._encounter_temp_npcs_for_candidates(save, existing_names=reserved_name_keys)
    for temp_npc in temp_npcs:
        actor_id = str(getattr(temp_npc, "encounter_npc_id", "") or "")
        if not actor_id:
            continue
        candidates.append(
            ResolvedInteractionTarget(
                actor_id=actor_id,
                name=str(getattr(temp_npc, "name", "") or actor_id),
                actor_kind="npc",
                actor_type=PublicTurnActorType.ENCOUNTER_TEMP_NPC,
            )
        )
    unique: dict[str, ResolvedInteractionTarget] = {}
    for candidate in candidates:
        unique.setdefault(candidate.actor_id, candidate)
    return list(unique.values())


def _attack_target_as_interaction_target(target: PublicTurnResolvedAttackTarget) -> ResolvedInteractionTarget:
    return ResolvedInteractionTarget(
        actor_id=target.actor_id,
        name=target.actor_name,
        actor_kind="player" if target.actor_type == PublicTurnActorType.PLAYER else "npc",
        actor_type=target.actor_type,
        role=target.role,
    )


def _resolve_public_turn_damage_targets(
    save: SaveFile,
    *,
    target_labels: list[str],
    fallback_target_name: str | None,
) -> list[ResolvedInteractionTarget]:
    labels = [str(item or "").strip() for item in target_labels if str(item or "").strip()]
    if not labels and str(fallback_target_name or "").strip():
        labels = [str(fallback_target_name or "").strip()]
    if not labels:
        return []
    candidates = _public_turn_combat_target_candidates(save)
    resolved: list[ResolvedInteractionTarget] = []
    seen_ids: set[str] = set()
    for label in labels:
        matched = [
            item
            for item in candidates
            if item.name == label or actor_name_match(item.name, label) or label in item.name
        ]
        if len(matched) != 1:
            continue
        target = matched[0]
        if target.actor_id in seen_ids:
            continue
        seen_ids.add(target.actor_id)
        resolved.append(target)
    return resolved


def _damage_amount_for_action_result(
    *,
    base_damage: int,
    damage_application_mode: str,
    action_result: ActionCheckResponse | None,
) -> int:
    if base_damage <= 0:
        return 0
    mode = str(damage_application_mode or "none").strip().lower()
    if mode == "none":
        return 0
    success = True if action_result is None else bool(action_result.success)
    if mode == "always":
        return base_damage
    if success:
        return base_damage
    if mode == "on_success_half_on_failure":
        return max(1, base_damage // 2)
    return 0


def _is_team_role(save: SaveFile, role_id: str) -> bool:
    return any(item.role_id == role_id for item in getattr(save.team_state, "members", []))


def _current_sub_zone_dead_ids(save: SaveFile) -> set[str]:
    sub_zone = world._current_sub_zone(save)
    if sub_zone is None:
        return set()
    return {
        str(getattr(record, "role_id", "") or "")
        for record in getattr(getattr(sub_zone, "state", None), "dead_npc_records", [])
    }


def _severe_wound_threshold(max_hp: int) -> int:
    return max(1, (max(1, int(max_hp)) + 1) // 2)


def _enter_death_saving_state(sheet, *, timestamp: str) -> None:
    sheet.death_state.life_status = "dying"
    sheet.death_state.death_save_successes = 0
    sheet.death_state.death_save_failures = 0
    sheet.death_state.updated_at = timestamp
    sheet.is_dead = False
    sheet.role_action_status = "death_saving"
    sheet.status_flags = ["dying", "unconscious", "prone"]


def _recover_from_death_save(sheet, *, timestamp: str) -> None:
    sheet.hit_points.current = max(1, int(sheet.hit_points.current))
    sheet.death_state.life_status = "healthy"
    sheet.death_state.death_save_successes = 0
    sheet.death_state.death_save_failures = 0
    sheet.death_state.updated_at = timestamp
    sheet.is_dead = False
    sheet.role_action_status = "free_action"
    sheet.status_flags = [flag for flag in sheet.status_flags if flag not in {"dying", "unconscious", "prone", "dead", "stable"}]


def _mark_sheet_dead(sheet, *, timestamp: str, cause: str) -> None:
    if sheet.death_state.life_status != "dead":
        sheet.death_state.death_count += 1
        sheet.death_state.death_streak_count += 1
    sheet.death_state.life_status = "dead"
    sheet.death_state.last_death_at = timestamp
    sheet.death_state.last_death_cause = cause
    sheet.death_state.updated_at = timestamp
    sheet.death_state.death_save_failures = min(3, max(3, int(sheet.death_state.death_save_failures or 0)))
    sheet.is_dead = True
    sheet.role_action_status = "dead"
    sheet.status_flags = ["dead"]


def _record_dead_npc(
    save: SaveFile,
    *,
    role: NpcRoleCard,
    death_at: str,
    death_cause: str,
    was_team_member: bool,
) -> list[SceneEvent]:
    sub_zone = world._current_sub_zone(save)
    if sub_zone is None:
        return []
    sub_zone.npcs = [item for item in sub_zone.npcs if item.npc_id != role.role_id]
    records = getattr(sub_zone.state, "dead_npc_records", [])
    if any(record.role_id == role.role_id for record in records):
        return []
    sub_zone.state.dead_npc_records.append(
        DeadNpcRecord(
            role_id=role.role_id,
            name=role.name,
            death_at=death_at,
            death_cause=death_cause,
            was_team_member=was_team_member,
        )
    )
    return [
        world._new_scene_event(
            "sub_zone_dead_npc_recorded",
            f"{role.name} is recorded as dead in {sub_zone.name}.",
            actor_role_id=role.role_id,
            actor_name=role.name,
            metadata={
                "role_id": role.role_id,
                "name": role.name,
                "sub_zone_id": sub_zone.sub_zone_id,
                "death_at": death_at,
                "death_cause": death_cause,
                "was_team_member": was_team_member,
            },
        )
    ]


def _resolve_extra_downing_damage(
    *,
    sheet,
    damage: int,
    damage_type_text: str,
    timestamp: str,
) -> str:
    severe = damage >= _severe_wound_threshold(int(sheet.hit_points.maximum))
    if severe:
        _mark_sheet_dead(sheet, timestamp=timestamp, cause=f"severe public_turn_damage ({damage_type_text or 'unknown'})")
        return "dead"
    if sheet.death_state.life_status == "stable":
        sheet.death_state.life_status = "dying"
        sheet.role_action_status = "death_saving"
        sheet.status_flags = ["dying", "unconscious", "prone"]
    sheet.death_state.death_save_failures = min(3, int(sheet.death_state.death_save_failures) + 1)
    sheet.death_state.updated_at = timestamp
    if sheet.death_state.death_save_failures >= 3:
        _mark_sheet_dead(sheet, timestamp=timestamp, cause=f"public_turn_damage ({damage_type_text or 'unknown'})")
        return "dead"
    return "dying"


def make_public_turn_death_save_prompt(
    *,
    round_state: PublicTurnRound,
    actor_id: str,
    actor_name: str,
    sheet,
    speech_text: str,
    phase_before_pause: PublicTurnPhase,
) -> DeathSavePrompt:
    return DeathSavePrompt(
        prompt_id=f"{round_state.round_id}_{actor_id}_death_save",
        round_id=round_state.round_id,
        phase=PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE,
        actor_id=actor_id,
        actor_name=actor_name,
        successes=int(sheet.death_state.death_save_successes),
        failures=int(sheet.death_state.death_save_failures),
        dc=10,
        severe_wound_threshold=_severe_wound_threshold(int(sheet.hit_points.maximum)),
        speech_only=True,
        metadata={
            "speech_text": speech_text,
            "phase_before_pause": phase_before_pause.value,
        },
    )


def _is_speech_only_role_action_status(status: str) -> bool:
    return status in {"death_saving", "unable_to_act", "dead"}


def _resolve_death_save_roll(
    *,
    sheet,
    roll: int,
    timestamp: str,
    death_cause: str,
) -> tuple[str, int, int, int, int]:
    hp_before = int(sheet.hit_points.current)
    if roll == 20:
        _recover_from_death_save(sheet, timestamp=timestamp)
        return "revived", hp_before, int(sheet.hit_points.current), int(sheet.death_state.death_save_successes), int(sheet.death_state.death_save_failures)
    if roll == 1:
        sheet.death_state.death_save_failures = min(3, int(sheet.death_state.death_save_failures) + 2)
    elif roll >= 10:
        sheet.death_state.death_save_successes = min(3, int(sheet.death_state.death_save_successes) + 1)
    else:
        sheet.death_state.death_save_failures = min(3, int(sheet.death_state.death_save_failures) + 1)
    sheet.death_state.updated_at = timestamp
    if int(sheet.death_state.death_save_successes) >= 3:
        _recover_from_death_save(sheet, timestamp=timestamp)
        return "revived", hp_before, int(sheet.hit_points.current), int(sheet.death_state.death_save_successes), int(sheet.death_state.death_save_failures)
    if int(sheet.death_state.death_save_failures) >= 3:
        _mark_sheet_dead(sheet, timestamp=timestamp, cause=death_cause)
        return "dead", hp_before, int(sheet.hit_points.current), int(sheet.death_state.death_save_successes), int(sheet.death_state.death_save_failures)
    return "continue", hp_before, int(sheet.hit_points.current), int(sheet.death_state.death_save_successes), int(sheet.death_state.death_save_failures)


def _death_save_summary(actor_name: str, *, roll: int, outcome: str, successes: int, failures: int) -> str:
    if outcome == "revived":
        if roll == 20:
            return f"{actor_name} rolls a natural 20 and regains 1 HP."
        return f"{actor_name} reaches three death save successes and regains 1 HP."
    if outcome == "dead":
        return f"{actor_name} fails the death save and dies."
    if roll >= 10:
        return f"{actor_name} holds on. Death saves: {successes}/3 successes, {failures}/3 failures."
    return f"{actor_name} slips closer to death. Death saves: {successes}/3 successes, {failures}/3 failures."


def resolve_public_turn_death_save(
    save: SaveFile,
    *,
    prompt: DeathSavePrompt,
    round_state: PublicTurnRound,
    forced_dice_roll: int,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry]:
    timestamp = world._utc_now()
    sheet = save.player_static_data.dnd5e_sheet
    outcome, hp_before, hp_after, successes, failures = _resolve_death_save_roll(
        sheet=sheet,
        roll=forced_dice_roll,
        timestamp=timestamp,
        death_cause="public_turn_death_save",
    )
    summary = _death_save_summary(
        prompt.actor_name,
        roll=forced_dice_roll,
        outcome=outcome,
        successes=successes,
        failures=failures,
    )
    events = [
        world._new_scene_event(
            "player_death_save_result",
            summary,
            actor_role_id=prompt.actor_id,
            actor_name=prompt.actor_name,
            metadata={
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "roll": forced_dice_roll,
                "dc": prompt.dc,
                "successes": successes,
                "failures": failures,
                "outcome": outcome,
            },
        )
    ]
    if outcome == "dead":
        events.append(
            world._new_scene_event(
                "player_died",
                f"{prompt.actor_name} dies.",
                actor_role_id=prompt.actor_id,
                actor_name=prompt.actor_name,
                metadata={
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "roll": forced_dice_roll,
                },
            )
        )
    hp_changes = []
    if hp_before != hp_after:
        hp_changes.append(
            {
                "target_id": prompt.actor_id,
                "target_name": prompt.actor_name,
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_delta": hp_after - hp_before,
            }
        )
    impact = build_impact(
        actor_id=prompt.actor_id,
        actor_name=prompt.actor_name,
        action_summary="death_save",
        action_result=None,
        situation_delta=0,
        zone_reputation_delta=0,
        relation_deltas=[],
        team_affinity_deltas=[],
        hp_changes=hp_changes,
        environment_shift=0,
        scene_events=events,
    )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=prompt.actor_id,
        actor_name=prompt.actor_name,
        actor_type="player",
        action_summary="",
        speech_text=str(prompt.metadata.get("speech_text") or ""),
        action_result=None,
        impact=impact,
        gm_resolution_summary=summary,
        source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        target_response_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        interaction_exchange_kind="speech_only",
        target_response_kind="explicit_response",
    )
    return events, impact, settlement


def resolve_team_npc_death_save_turn(
    save: SaveFile,
    *,
    actor: dict[str, object],
    round_state: PublicTurnRound,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry]:
    timestamp = world._utc_now()
    role = actor.get("role")
    if not isinstance(role, NpcRoleCard):
        raise ValueError("PUBLIC_TURN_TEAM_DEATH_SAVE_ROLE_REQUIRED")
    sheet = role.profile.dnd5e_sheet
    roll = random.randint(1, 20)
    outcome, hp_before, hp_after, successes, failures = _resolve_death_save_roll(
        sheet=sheet,
        roll=roll,
        timestamp=timestamp,
        death_cause="public_turn_team_death_save",
    )
    summary = _death_save_summary(role.name, roll=roll, outcome=outcome, successes=successes, failures=failures)
    events = [
        world._new_scene_event(
            "team_npc_death_save_result",
            summary,
            actor_role_id=role.role_id,
            actor_name=role.name,
            metadata={
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "roll": roll,
                "dc": 10,
                "successes": successes,
                "failures": failures,
                "outcome": outcome,
            },
        )
    ]
    if outcome == "dead":
        role.state = "dead"
        events.append(
            world._new_scene_event(
                "team_npc_died",
                f"{role.name} dies.",
                actor_role_id=role.role_id,
                actor_name=role.name,
                metadata={
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "roll": roll,
                },
            )
        )
        events.extend(
            _record_dead_npc(
                save,
                role=role,
                death_at=timestamp,
                death_cause="public_turn_team_death_save",
                was_team_member=True,
            )
        )
    hp_changes = []
    if hp_before != hp_after:
        hp_changes.append(
            {
                "target_id": role.role_id,
                "target_name": role.name,
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_delta": hp_after - hp_before,
            }
        )
    impact = build_impact(
        actor_id=role.role_id,
        actor_name=role.name,
        action_summary="death_save",
        action_result=None,
        situation_delta=0,
        zone_reputation_delta=0,
        relation_deltas=[],
        team_affinity_deltas=[],
        hp_changes=hp_changes,
        environment_shift=0,
        scene_events=events,
    )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=role.role_id,
        actor_name=role.name,
        actor_type="team",
        action_summary="",
        speech_text="",
        action_result=None,
        impact=impact,
        gm_resolution_summary=summary,
        source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        target_response_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        interaction_exchange_kind="speech_only",
        target_response_kind="no_action",
    )
    return events, impact, settlement


def _damage_resolution_scene_event(
    *,
    source_actor_id: str,
    source_actor_name: str,
    source_actor_type: str,
    target_actor_id: str,
    target_actor_name: str,
    target_actor_type: str,
    damage: int,
    damage_type: str,
    hp_before: int,
    hp_after: int,
    temp_hp_absorbed: int,
    life_status_after: str,
    round_id: str,
    phase: PublicTurnPhase,
) -> SceneEvent:
    return world._new_scene_event(
        "damage_resolution",
        f"{target_actor_name}受到{damage}点{damage_type or '伤害'}伤害，HP {hp_before}->{hp_after}。",
        actor_role_id=source_actor_id,
        actor_name=source_actor_name,
        metadata={
            "context_kind": "public_turn",
            "actor_type": source_actor_type,
            "source_actor_id": source_actor_id,
            "source_actor_name": source_actor_name,
            "target_actor_id": target_actor_id,
            "target_actor_name": target_actor_name,
            "target_actor_type": target_actor_type,
            "damage": damage,
            "damage_type": damage_type or "damage",
            "hp_before": hp_before,
            "hp_after": hp_after,
            "hp_delta": hp_after - hp_before,
            "temp_hp_absorbed": temp_hp_absorbed,
            "life_status_after": life_status_after,
            "triggered_death_save": life_status_after == "dying",
            "declared_death": life_status_after == "dead",
            "round_id": round_id,
            "phase": phase.value,
        },
    )


def _apply_public_turn_hp_damage(
    save: SaveFile,
    *,
    source_actor_id: str,
    source_actor_name: str,
    target: ResolvedInteractionTarget,
    damage: int,
    damage_type: str,
    round_id: str,
    phase: PublicTurnPhase,
) -> tuple[dict[str, Any] | None, list[SceneEvent]]:
    if damage <= 0:
        return None, []
    damage_type_text = str(damage_type or "").strip()
    timestamp = world._utc_now()
    if target.actor_id == save.player_static_data.player_id:
        sheet = save.player_static_data.dnd5e_sheet
        hp_before = int(sheet.hit_points.current)
        temp_hp = int(sheet.hit_points.temporary)
        remaining_damage = damage
        absorbed = 0
        if temp_hp > 0:
            absorbed = min(temp_hp, remaining_damage)
            sheet.hit_points.temporary -= absorbed
            remaining_damage -= absorbed
        if remaining_damage > 0 and sheet.death_state.life_status not in {"dying", "stable"}:
            sheet.hit_points.current = max(0, sheet.hit_points.current - remaining_damage)
        hp_after = int(sheet.hit_points.current)
        life_status = sheet.death_state.life_status
        if remaining_damage > 0 and sheet.death_state.life_status in {"dying", "stable"}:
            life_status = _resolve_extra_downing_damage(
                sheet=sheet,
                damage=remaining_damage,
                damage_type_text=damage_type_text,
                timestamp=timestamp,
            )
        elif hp_after <= 0 and hp_before > 0:
            instant_death = remaining_damage >= hp_before + int(sheet.hit_points.maximum)
            if instant_death:
                _mark_sheet_dead(sheet, timestamp=timestamp, cause=f"public_turn_damage ({damage_type_text or 'unknown'})")
                life_status = "dead"
            else:
                _enter_death_saving_state(sheet, timestamp=timestamp)
                life_status = "dying"
        elif hp_after > 0 and life_status == "healthy":
            sheet.role_action_status = "free_action"
        hp_delta = hp_after - hp_before
        event_text = f"{target.name} takes {damage} {damage_type_text or 'damage'} damage, HP {hp_before}->{hp_after}."
        if life_status == "dying":
            event_text += f" {target.name} enters the dying state."
        elif life_status == "dead":
            event_text += f" {target.name} dies on the spot."
        damage_event = _damage_resolution_scene_event(
            source_actor_id=source_actor_id,
            source_actor_name=source_actor_name,
            source_actor_type=("player" if source_actor_id == save.player_static_data.player_id else "npc"),
            target_actor_id=target.actor_id,
            target_actor_name=target.name,
            target_actor_type="player",
            damage=damage,
            damage_type=damage_type_text or "damage",
            hp_before=hp_before,
            hp_after=hp_after,
            temp_hp_absorbed=absorbed,
            life_status_after=life_status,
            round_id=round_id,
            phase=phase,
        )
        event = world._new_scene_event(
            "public_turn_actor_resolution",
            event_text,
            actor_role_id=source_actor_id,
            actor_name=source_actor_name,
            metadata={
                "actor_type": "player" if source_actor_id == save.player_static_data.player_id else "npc",
                "round_id": round_id,
                "phase": phase.value,
                "target_actor_id": target.actor_id,
                "target_actor_name": target.name,
                "damage": damage,
                "damage_type": damage_type_text or "damage",
                "hp_before": hp_before,
                "hp_after": hp_after,
                "life_status": life_status,
            },
        )
        extra_events: list[SceneEvent] = []
        if life_status == "dying":
            extra_events.append(
                world._new_scene_event(
                    "player_entered_death_save",
                    f"{target.name} enters death saving throws.",
                    actor_role_id=target.actor_id,
                    actor_name=target.name,
                    metadata={
                        "round_id": round_id,
                        "phase": phase.value,
                        "successes": int(sheet.death_state.death_save_successes),
                        "failures": int(sheet.death_state.death_save_failures),
                        "severe_wound_threshold": _severe_wound_threshold(int(sheet.hit_points.maximum)),
                    },
                )
            )
        elif life_status == "dead":
            extra_events.append(
                world._new_scene_event(
                    "player_died",
                    f"{target.name} dies.",
                    actor_role_id=target.actor_id,
                    actor_name=target.name,
                    metadata={
                        "round_id": round_id,
                        "phase": phase.value,
                        "damage": damage,
                        "damage_type": damage_type_text or "damage",
                    },
                )
            )
        if hp_before == hp_after:
            return None, [damage_event, event, *extra_events]
        return {
            "target_id": target.actor_id,
            "target_name": target.name,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "hp_delta": hp_delta,
        }, [damage_event, event, *extra_events]

    if target.actor_type == PublicTurnActorType.ENCOUNTER_TEMP_NPC:
        return None, []
    role = next((item for item in save.role_pool if item.role_id == target.actor_id), None)
    if role is None:
        return None, []
    if role.role_id in _current_sub_zone_dead_ids(save):
        return None, []
    sheet = role.profile.dnd5e_sheet
    was_team_member = _is_team_role(save, role.role_id)
    hp_before = int(sheet.hit_points.current)
    temp_hp = int(sheet.hit_points.temporary)
    remaining_damage = damage
    absorbed = 0
    if temp_hp > 0:
        absorbed = min(temp_hp, remaining_damage)
        sheet.hit_points.temporary -= absorbed
        remaining_damage -= absorbed
    if remaining_damage > 0 and sheet.death_state.life_status not in {"dying", "stable"}:
        sheet.hit_points.current = max(0, sheet.hit_points.current - remaining_damage)
    hp_after = int(sheet.hit_points.current)
    record_events: list[SceneEvent] = []
    if remaining_damage > 0 and sheet.death_state.life_status in {"dying", "stable"}:
        life_status = _resolve_extra_downing_damage(
            sheet=sheet,
            damage=remaining_damage,
            damage_type_text=damage_type_text,
            timestamp=timestamp,
        )
        if life_status == "dead":
            role.state = "dead"
            record_events.extend(
                _record_dead_npc(
                    save,
                    role=role,
                    death_at=timestamp,
                    death_cause=f"public_turn_damage ({damage_type_text or 'unknown'})",
                    was_team_member=was_team_member,
                )
            )
    elif hp_after <= 0:
        if was_team_member:
            _enter_death_saving_state(sheet, timestamp=timestamp)
            life_status = "dying"
        else:
            _mark_sheet_dead(sheet, timestamp=timestamp, cause=f"public_turn_damage ({damage_type_text or 'unknown'})")
            role.state = "dead"
            life_status = "dead"
            record_events.extend(
                _record_dead_npc(
                    save,
                    role=role,
                    death_at=timestamp,
                    death_cause=f"public_turn_damage ({damage_type_text or 'unknown'})",
                    was_team_member=False,
                )
            )
    else:
        life_status = "healthy"
        sheet.role_action_status = "free_action"
    hp_delta = hp_after - hp_before
    event_text = f"{target.name} takes {damage} {damage_type_text or 'damage'} damage, HP {hp_before}->{hp_after}."
    if life_status == "dying":
        event_text += f" {target.name} enters the dying state."
    if life_status == "dead":
        event_text += f" {target.name} is dropped."
    damage_event = _damage_resolution_scene_event(
        source_actor_id=source_actor_id,
        source_actor_name=source_actor_name,
        source_actor_type=("player" if source_actor_id == save.player_static_data.player_id else "npc"),
        target_actor_id=target.actor_id,
        target_actor_name=target.name,
        target_actor_type=("team" if was_team_member else "npc"),
        damage=damage,
        damage_type=damage_type_text or "damage",
        hp_before=hp_before,
        hp_after=hp_after,
        temp_hp_absorbed=absorbed,
        life_status_after=life_status,
        round_id=round_id,
        phase=phase,
    )
    event = world._new_scene_event(
        "public_turn_actor_resolution",
        event_text,
        actor_role_id=source_actor_id,
        actor_name=source_actor_name,
        metadata={
            "actor_type": "player" if source_actor_id == save.player_static_data.player_id else "npc",
            "round_id": round_id,
            "phase": phase.value,
            "target_actor_id": target.actor_id,
            "target_actor_name": target.name,
            "damage": damage,
            "damage_type": damage_type_text or "damage",
            "hp_before": hp_before,
            "hp_after": hp_after,
                "life_status": life_status,
            },
        )
    extra_events: list[SceneEvent] = []
    if life_status == "dying" and was_team_member:
        extra_events.append(
            world._new_scene_event(
                "team_npc_entered_death_save",
                f"{target.name} enters death saving throws.",
                actor_role_id=target.actor_id,
                actor_name=target.name,
                metadata={
                    "round_id": round_id,
                    "phase": phase.value,
                    "successes": int(sheet.death_state.death_save_successes),
                    "failures": int(sheet.death_state.death_save_failures),
                    "severe_wound_threshold": _severe_wound_threshold(int(sheet.hit_points.maximum)),
                },
            )
        )
    elif life_status == "dead" and was_team_member:
        extra_events.append(
            world._new_scene_event(
                "team_npc_died",
                f"{target.name} dies.",
                actor_role_id=target.actor_id,
                actor_name=target.name,
                metadata={
                    "round_id": round_id,
                    "phase": phase.value,
                    "damage": damage,
                    "damage_type": damage_type_text or "damage",
                },
            )
        )
    if hp_before == hp_after:
        return None, [damage_event, event, *extra_events, *record_events]
    return {
        "target_id": target.actor_id,
        "target_name": target.name,
        "hp_before": hp_before,
        "hp_after": hp_after,
        "hp_delta": hp_delta,
    }, [damage_event, event, *extra_events, *record_events]


def _ai_public_turn_damage_bundle(
    save: SaveFile,
    *,
    actor_role_id: str,
    actor_name: str,
    action_type: str,
    action_summary: str,
    speech_text: str,
    action_prompt: str,
    specific_threat: str,
    fallback_target_name: str | None,
    action_result: ActionCheckResponse | None,
    config: ChatConfig | None,
) -> dict[str, object]:
    if not has_ai_config(config):
        return _empty_public_turn_damage_bundle()
    assert config is not None
    try:
        _, actor_profile = world._get_actor_profile(save, actor_role_id)
    except Exception:
        actor_profile = save.player_static_data
    visible_targets = _public_turn_combat_target_candidates(save)
    prompt = prompt_table.render(
        "public.turn.damage_plan.user",
        (
            "Analyze one resolved public-turn action and decide whether it should immediately change HP in the current scene. "
            "Return JSON only. "
            "Use DND 5e spell semantics when the action clearly names or describes a recognizable spell. "
            "Recognize classic area spells such as Fireball as multi-target AOE damage instead of single-target attacks. "
            "Choose only from the allowed stable ids for effect_kind, area_mode, rules_basis, damage_application_mode, and damage_type. "
            "affected_targets must be an array of objects with target_label, and each target_label must copy an exact name from visible_target_names_json. "
            "damage_application_mode describes how to apply base_damage against the already-resolved action result: "
            "on_success=full damage only if the action succeeded, on_success_half_on_failure=full on success and half on failure, always=full damage either way, none=no HP change. "
            "If there is no immediate HP damage, return effect_kind=none, damage_application_mode=none, base_damage=0, and affected_targets=[]. "
            "actor_name=$actor_name; action_type=$action_type; action_summary=$action_summary; speech_text=$speech_text; "
            "action_prompt=$action_prompt; specific_threat=$specific_threat; fallback_target_name=$fallback_target_name; "
            "action_outcome=$action_outcome; known_spells_json=$known_spells_json; visible_target_names_json=$visible_target_names_json"
        ),
        actor_name=actor_name,
        action_type=action_type,
        action_summary=action_summary[:200],
        speech_text=speech_text[:160],
        action_prompt=action_prompt[:240],
        specific_threat=specific_threat[:200],
        fallback_target_name=str(fallback_target_name or "")[:120],
        action_outcome=("success" if action_result is None or action_result.success else "failure"),
        known_spells_json=json.dumps(list(actor_profile.dnd5e_sheet.spells or []), ensure_ascii=False),
        visible_target_names_json=json.dumps([item.name for item in visible_targets], ensure_ascii=False),
    )
    prompt = (
        f"{prompt}\nAllowed enum ids:\n{render_enum_pool_text(_PUBLIC_TURN_DAMAGE_KIND_FIELDS)}\n"
        "Use only the allowed stable ids for effect_kind, area_mode, rules_basis, damage_application_mode, and damage_type."
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = (response.choices[0].message.content or "").strip() or "{}"
        parsed = public_scene_legacy._extract_json_content(raw_json)
        with allow_protocol_repair():
            parsed = validate_or_repair_json_payload(
                parsed=parsed,
                raw_json=raw_json,
                fields=_PUBLIC_TURN_DAMAGE_KIND_FIELDS,
                config=config,
                system_prompt=config.gm_prompt,
                original_prompt=prompt,
            )
    except Exception:
        return _empty_public_turn_damage_bundle()
    affected_targets: list[dict[str, str]] = []
    for item in list(parsed.get("affected_targets") or []):
        if not isinstance(item, dict):
            continue
        label = _normalize_public_turn_text(str(item.get("target_label") or ""), limit=120)
        if not label:
            continue
        affected_targets.append({"target_label": label})
    return {
        "effect_kind": str(parsed.get("effect_kind") or "none").strip().lower(),
        "area_mode": str(parsed.get("area_mode") or "single").strip().lower(),
        "rules_basis": str(parsed.get("rules_basis") or "none").strip().lower(),
        "spell_name": _normalize_public_turn_text(str(parsed.get("spell_name") or ""), limit=120),
        "damage_application_mode": str(parsed.get("damage_application_mode") or "none").strip().lower(),
        "damage_type": str(parsed.get("damage_type") or "none").strip().lower(),
        "base_damage": max(0, min(120, int(parsed.get("base_damage") or 0))),
        "affected_targets": affected_targets,
        "reason": _normalize_public_turn_text(str(parsed.get("reason") or ""), limit=200),
    }


def _resolve_public_turn_damage_bundle(
    save: SaveFile,
    *,
    session_id: str,
    actor_role_id: str,
    actor_name: str,
    action_type: str,
    action_summary: str,
    speech_text: str,
    action_prompt: str,
    specific_threat: str,
    fallback_target_name: str | None,
    action_result: ActionCheckResponse | None,
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[list[dict[str, Any]], list[SceneEvent]]:
    del session_id
    damage_bundle = _ai_public_turn_damage_bundle(
        save,
        actor_role_id=actor_role_id,
        actor_name=actor_name,
        action_type=action_type,
        action_summary=action_summary,
        speech_text=speech_text,
        action_prompt=action_prompt,
        specific_threat=specific_threat,
        fallback_target_name=fallback_target_name,
        action_result=action_result,
        config=config,
    )
    if str(damage_bundle.get("effect_kind") or "none") != "damage":
        return [], []
    damage_amount = _damage_amount_for_action_result(
        base_damage=int(damage_bundle.get("base_damage") or 0),
        damage_application_mode=str(damage_bundle.get("damage_application_mode") or "none"),
        action_result=action_result,
    )
    if damage_amount <= 0:
        return [], []
    target_labels = [
        str(item.get("target_label") or "")
        for item in list(damage_bundle.get("affected_targets") or [])
        if isinstance(item, dict)
    ]
    resolved_targets = _resolve_public_turn_damage_targets(
        save,
        target_labels=target_labels,
        fallback_target_name=fallback_target_name,
    )
    hp_changes: list[dict[str, Any]] = []
    events: list[SceneEvent] = []
    for target in resolved_targets:
        hp_change, damage_events = _apply_public_turn_hp_damage(
            save,
            source_actor_id=actor_role_id,
            source_actor_name=actor_name,
            target=target,
            damage=damage_amount,
            damage_type=str(damage_bundle.get("damage_type") or "damage"),
            round_id=round_state.round_id,
            phase=round_state.phase,
        )
        if hp_change is not None:
            hp_changes.append(hp_change)
        events.extend(damage_events)
    return hp_changes, events


def _submission_display_text(action_text: str, speech_text: str) -> str:
    parts: list[str] = []
    if action_text.strip():
        parts.append(f"Action: {action_text.strip()}")
    if speech_text.strip():
        parts.append(f"Speech: {speech_text.strip()}")
    return "\n".join(parts).strip() or "(no visible action)"

def settlement_actor_type(value: str | None) -> PublicTurnActorType:
    actor_type = str(value or "npc").strip().lower()
    if actor_type == "player":
        return PublicTurnActorType.PLAYER
    if actor_type == "team":
        return PublicTurnActorType.TEAM
    if actor_type == "encounter_temp_npc":
        return PublicTurnActorType.ENCOUNTER_TEMP_NPC
    if actor_type == "hidden_npc":
        return PublicTurnActorType.HIDDEN_NPC
    if actor_type == "environment":
        return PublicTurnActorType.ENVIRONMENT
    return PublicTurnActorType.NPC


def build_initiative_order(declarations: list[InitiativeDeclaration]) -> list[PublicTurnInitiativeEntry]:
    rows: list[PublicTurnInitiativeEntry] = []
    for index, declaration in enumerate(declarations):
        revealed = (not declaration.is_hidden) or declaration.revealed_by_declaration
        if not revealed:
            continue
        rows.append(
            PublicTurnInitiativeEntry(
                actor_id=declaration.actor_id,
                actor_name=declaration.actor_name,
                actor_type=settlement_actor_type(declaration.actor_type),
                dex_modifier=int(declaration.dex_modifier),
                roll_d20=int(declaration.roll_d20 or 1),
                total_initiative=int(declaration.total_initiative or (int(declaration.dex_modifier) + int(declaration.roll_d20 or 0))),
                revealed=True,
                order_index=index,
            )
        )
    return rows


def _last_nonempty_line(text: str) -> str:
    parts = [part.strip() for part in str(text or "").splitlines() if part.strip()]
    if not parts:
        return ""
    return parts[-1]


def _recent_conflict_anchor(round_state: PublicTurnRound) -> tuple[str, str, str]:
    for settlement in reversed(round_state.settlement_entries):
        if settlement.entry_kind != "actor":
            continue
        excerpt = "\n".join(
            part
            for part in (
                settlement.action_summary.strip(),
                settlement.speech_text.strip(),
                settlement.gm_resolution_summary.strip(),
            )
            if part
        )[:200]
        primary_target = str(
            settlement.action_target_name
            or settlement.interaction_target_name
            or settlement.opposed_target_name
            or ""
        ).strip()
        return settlement.actor_name, primary_target, excerpt
    return "", "", ""


def _default_gm_resolution_summary(actor_name: str, action_summary: str, situation_delta: int) -> str:
    clean_action = " ".join(str(action_summary or "").split())
    if situation_delta >= 4:
        return f"{actor_name} drives the public scene sharply in their favor and forces the moment to turn."
    if situation_delta <= -4:
        return f"{actor_name} loses control of the moment and the pressure around them visibly worsens."
    if clean_action:
        return f"{actor_name} follows through on {clean_action[:24]} and shifts the immediate scene response."
    return f"{actor_name} commits to the move and changes the immediate public rhythm."


def _clean_json_wrapper_text(text: str) -> str:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```JSON").removeprefix("```").strip()
        if clean.endswith("```"):
            clean = clean[:-3].strip()
    return clean


def _extract_resolution_summary_text(text: str, *, limit: int = 280) -> str:
    clean = _clean_json_wrapper_text(text)
    if not clean:
        return ""
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return _normalize_public_turn_text(clean, limit=limit)
    if isinstance(parsed, dict):
        for key in ("outcome", "outcome_description", "outcome_narration", "summary", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_public_turn_text(value, limit=limit)
    return _normalize_public_turn_text(clean, limit=limit)

def _default_opposed_resolution_summary(
    *,
    actor_name: str,
    target_name: str,
    actor_action_summary: str,
    target_action_summary: str,
    target_speech_text: str,
    action_result: ActionCheckResponse,
) -> str:
    actor_action = _normalize_public_turn_text(actor_action_summary, limit=120)
    target_action = _normalize_public_turn_text(target_action_summary, limit=120)
    target_speech = _normalize_public_turn_text(target_speech_text, limit=120)
    actor_focus = actor_action[:28] if actor_action else "their move"
    target_focus = target_action[:28] if target_action else "the counter"
    if action_result.success:
        if action_result.critical == "critical_success":
            return f"{actor_name} overwhelms {target_name} with {actor_focus}, blows through {target_focus}, and seizes the moment outright."[:280]
        return f"{actor_name} beats {target_name} with {actor_focus} and keeps {target_focus} from holding."[:280]
    if action_result.critical == "critical_failure":
        return f"{actor_name} overcommits to {actor_focus}, while {target_name} turns {target_focus} into a complete reversal."[:280]
    if target_speech:
        return f"{actor_name} cannot force through {target_focus}, and {target_name}'s answer \"{target_speech[:24]}\" hardens the refusal."[:280]
    return f"{actor_name} cannot force through {target_focus}, and {target_name} holds the line against {actor_focus}."[:280]

def _generate_opposed_resolution_summary(
    *,
    session_id: str,
    actor_name: str,
    target_name: str,
    actor_action_summary: str,
    actor_speech_text: str,
    target_action_summary: str,
    target_speech_text: str,
    stakes_summary: str,
    action_result: ActionCheckResponse | None,
    config: ChatConfig | None,
) -> str:
    if action_result is None or action_result.resolution_rule != "opposed_actor":
        return ""
    fallback = _default_opposed_resolution_summary(
        actor_name=actor_name,
        target_name=target_name,
        actor_action_summary=actor_action_summary,
        target_action_summary=target_action_summary,
        target_speech_text=target_speech_text,
        action_result=action_result,
    )
    if not has_ai_config(config):
        return fallback
    assert config is not None
    try:
        prompt = prompt_table.render(
            "public.turn.opposed_resolution.user",
            (
                "Return one JSON object only. Describe the concrete aftermath of the opposed exchange. "
                "Write 1-2 short sentences grounded in the actor action, target response, stakes, and outcome. "
                "actor_name=$actor_name; target_name=$target_name; actor_action=$actor_action; actor_speech=$actor_speech; "
                "target_action=$target_action; target_speech=$target_speech; stakes=$stakes; outcome=$outcome; critical=$critical"
            ),
            actor_name=actor_name,
            target_name=target_name,
            actor_action=actor_action_summary[:200],
            actor_speech=actor_speech_text[:160],
            target_action=target_action_summary[:200],
            target_speech=target_speech_text[:160],
            stakes=stakes_summary[:200],
            outcome=("actor_success" if action_result.success else "actor_failure"),
            critical=action_result.critical,
        )
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": prompt_table.get_text(
                        "public.turn.opposed_resolution.system",
                        "You are a concise tabletop RPG resolution writer. Return one short factual narration of the opposed exchange outcome.",
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            token_usage_store.add(
                session_id,
                "chat",
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        text = _extract_resolution_summary_text(resp.choices[0].message.content or "", limit=280)
        return text or fallback
    except Exception:
        return fallback


def build_settlement_check(action_result: ActionCheckResponse | None) -> PublicTurnSettlementCheck | None:
    if action_result is None:
        return None
    success = bool(action_result.success)
    outcome_text = "Success" if success else "Failure"
    if action_result.critical == "critical_success":
        outcome_text = "Critical Success"
    elif action_result.critical == "critical_failure":
        outcome_text = "Critical Failure"
    if action_result.resolution_rule == "opposed_actor" and action_result.target_name:
        comparison_text = (
            f"{action_result.actor_name} d20({action_result.dice_roll if action_result.dice_roll is not None else "-"}) "
            f"{action_result.ability_modifier:+d} = {action_result.total_score if action_result.total_score is not None else "-"} vs "
            f"{action_result.target_name} d20({action_result.target_dice_roll if action_result.target_dice_roll is not None else "-"}) "
            f"{int(action_result.target_ability_modifier or 0):+d} = {action_result.target_total_score if action_result.target_total_score is not None else "-"}"
        )
    else:
        comparison_text = (
            f"d20({action_result.dice_roll if action_result.dice_roll is not None else "-"}) "
            f"{action_result.ability_modifier:+d} = {action_result.total_score if action_result.total_score is not None else "-"} "
            f"vs DC {action_result.dc}"
        )
    return PublicTurnSettlementCheck(
        resolution_rule=action_result.resolution_rule,
        ability_used=action_result.ability_used,
        ability_modifier=int(action_result.ability_modifier),
        dice_roll=action_result.dice_roll,
        total_score=action_result.total_score,
        dc=action_result.dc,
        target_name=action_result.target_name,
        target_ability_used=action_result.target_ability_used,
        target_ability_modifier=action_result.target_ability_modifier,
        target_dice_roll=action_result.target_dice_roll,
        target_total_score=action_result.target_total_score,
        success=success,
        critical=action_result.critical,
        comparison_text=comparison_text,
        outcome_text=outcome_text,
    )


def _apply_followup_check_to_settlement(
    settlement: PublicTurnSettlementEntry,
    impact: PublicTurnImpact,
    action_result: ActionCheckResponse,
) -> None:
    settlement.followup_check = build_settlement_check(action_result)
    extra_delta = check_bonus(action_result)
    if extra_delta:
        settlement.situation_delta += extra_delta
        impact.situation_delta += extra_delta
        if public_turn_zone_reputation_allowed(settlement.actor_type.value):
            reputation_delta = reputation_delta_from_situation(extra_delta)
            settlement.zone_reputation_delta += reputation_delta
            impact.zone_reputation_delta += reputation_delta
    followup_summary = _last_nonempty_line(action_result.narrative)
    if followup_summary:
        previous = settlement.gm_resolution_summary.strip()
        settlement.gm_resolution_summary = f"{previous}\n{followup_summary}".strip() if previous else followup_summary



def build_settlement_entry(
    *,
    round_state: PublicTurnRound,
    actor_id: str,
    actor_name: str,
    actor_type: str,
    action_summary: str,
    speech_text: str,
    action_result: ActionCheckResponse | None,
    impact: PublicTurnImpact,
    gm_resolution_summary: str = "",
    entry_kind: str = "actor",
    gm_push_result: PublicTurnGmPushResult | None = None,
    action_target_actor_id: str | None = None,
    action_target_name: str | None = None,
    action_target_kind: PublicTurnActorType | None = None,
    speech_target_actor_id: str | None = None,
    speech_target_name: str | None = None,
    speech_target_kind: PublicTurnActorType | None = None,
    source_world_impact_type: PublicTurnWorldImpactType = PublicTurnWorldImpactType.NON_WORLD,
    target_response_world_impact_type: PublicTurnWorldImpactType = PublicTurnWorldImpactType.NON_WORLD,
    interaction_exchange_kind: str = "world_exchange",
    alternation_depth: int = 0,
    target_response_kind: str = "explicit_response",
    interaction_target_name: str | None = None,
    interaction_resolution: str = "non_interactive",
    attack_kind: str | None = None,
    attack_basis: str | None = None,
    attack_definition_id: str | None = None,
    attack_definition_name: str | None = None,
    attack_area_shape: str | None = None,
    threatened_target_names: list[str] | None = None,
    hit_target_names: list[str] | None = None,
    avoided_target_names: list[str] | None = None,
    revealed_target_names: list[str] | None = None,
    opposed_target_name: str | None = None,
    opposed_target_action: str | None = None,
    opposed_target_speech: str | None = None,
    opposed_target_speech_target_name: str | None = None,
) -> PublicTurnSettlementEntry:
    return PublicTurnSettlementEntry(
        entry_id=f"{round_state.round_id}_{len(round_state.settlement_entries) + 1}",
        round_id=round_state.round_id,
        entry_kind=entry_kind,  # type: ignore[arg-type]
        phase=round_state.phase,
        order_index=len(round_state.settlement_entries),
        actor_id=actor_id,
        actor_name=actor_name,
        actor_type=settlement_actor_type(actor_type),
        action_summary=action_summary[:200],
        speech_text=speech_text[:200],
        action_target_actor_id=action_target_actor_id,
        action_target_name=action_target_name,
        action_target_kind=action_target_kind,
        speech_target_actor_id=speech_target_actor_id,
        speech_target_name=speech_target_name,
        speech_target_kind=speech_target_kind,
        source_world_impact_type=source_world_impact_type,
        target_response_world_impact_type=target_response_world_impact_type,
        interaction_exchange_kind=interaction_exchange_kind,  # type: ignore[arg-type]
        alternation_depth=max(0, min(1, int(alternation_depth or 0))),
        target_response_kind=target_response_kind,  # type: ignore[arg-type]
        interaction_target_name=interaction_target_name,
        interaction_resolution=interaction_resolution,  # type: ignore[arg-type]
        attack_kind=attack_kind,  # type: ignore[arg-type]
        attack_basis=attack_basis,  # type: ignore[arg-type]
        attack_definition_id=attack_definition_id,
        attack_definition_name=attack_definition_name,
        attack_area_shape=attack_area_shape,  # type: ignore[arg-type]
        threatened_target_names=list(threatened_target_names or []),
        hit_target_names=list(hit_target_names or []),
        avoided_target_names=list(avoided_target_names or []),
        revealed_target_names=list(revealed_target_names or []),
        opposed_target_name=opposed_target_name or (action_result.target_name if action_result is not None else None),
        opposed_target_action=(opposed_target_action or "")[:200] or None,
        opposed_target_speech=(opposed_target_speech or "")[:200] or None,
        opposed_target_speech_target_name=(opposed_target_speech_target_name or "")[:120] or None,
        check=build_settlement_check(action_result),
        gm_resolution_summary=_extract_resolution_summary_text(gm_resolution_summary or "", limit=280),
        gm_push_result=gm_push_result,
        situation_delta=impact.situation_delta,
        zone_reputation_delta=impact.zone_reputation_delta,
        relation_deltas=list(impact.relation_deltas),
        team_affinity_deltas=list(impact.team_affinity_deltas),
        hp_changes=list(impact.hp_changes),
        environment_shift=impact.environment_shift,
    )


def _action_type_for_text(text: str) -> str:
    _ = text
    return "check"

def _requires_action_check(text: str) -> bool:
    _ = text
    return False


def _situation_hint_from_text(text: str) -> int:
    _ = text
    return 0



def _normalize_public_turn_text(text: str, *, limit: int) -> str:
    return " ".join(str(text or "").split()).strip()[:limit]


def _prompt_action_target_details(
    *,
    prompt_target_actor_id: str | None,
    prompt_target_actor_name: str | None,
    prompt_target_actor_kind: PublicTurnActorType | None,
    source_action_target_name: str | None,
) -> tuple[str | None, str | None, PublicTurnActorType | None]:
    clean_action_target_name = _normalize_public_turn_text(source_action_target_name or "", limit=120) or None
    clean_prompt_target_name = _normalize_public_turn_text(prompt_target_actor_name or "", limit=120) or None
    if clean_action_target_name and clean_prompt_target_name and clean_action_target_name == clean_prompt_target_name:
        return prompt_target_actor_id, clean_action_target_name, prompt_target_actor_kind
    return None, clean_action_target_name, None


def normalize_public_turn_ai_payload(
    payload: dict[str, object] | None,
    *,
    actor_name: str,
    audience_may_speak: bool,
) -> dict[str, object]:
    source = payload or {}
    action_summary = _normalize_public_turn_text(
        str(source.get("external_action_narration") or source.get("visible_intent") or ""), limit=200
    )
    speech_text = _normalize_public_turn_text(
        str(source.get("speech_line") or source.get("speech_summary") or ""), limit=200
    )
    if not audience_may_speak:
        speech_text = ""
    specific_threat = _normalize_public_turn_text(str(source.get("specific_threat") or ""), limit=200)
    action_type = str(source.get("action_type") or "").strip().lower() or "check"
    target_label = _normalize_public_turn_text(str(source.get("target_label") or ""), limit=80)
    speech_target_label = _normalize_public_turn_text(str(source.get("speech_target_label") or ""), limit=80)
    world_impact_type = infer_world_impact_type(
        action_type=action_type,
        action_summary=action_summary,
        speech_text=speech_text,
        explicit_value=str(source.get("world_impact_type") or ""),
    ).value
    action_prompt = _normalize_public_turn_text(
        str(source.get("action_prompt") or "") or f"actor={actor_name}; intent={action_summary}; threat={specific_threat}",
        limit=240,
    )
    return {
        "external_action_narration": action_summary,
        "visible_intent": action_summary,
        "speech_line": speech_text,
        "speech_summary": speech_text,
        "specific_threat": specific_threat,
        "target_label": target_label,
        "speech_target_label": speech_target_label,
        "world_impact_type": world_impact_type,
        "action_type": action_type,
        "action_prompt": action_prompt,
        "situation_delta_hint": max(-8, min(8, int(source.get("situation_delta_hint") or 0))),
        "reputation_delta_hint": (
            max(-3, min(3, int(source.get("reputation_delta_hint") or 0))) if source.get("reputation_delta_hint") is not None else None
        ),
        "incoming_reaction_narration": _normalize_public_turn_text(str(source.get("incoming_reaction_narration") or ""), limit=200),
        "incoming_reaction_speech": _normalize_public_turn_text(str(source.get("incoming_reaction_speech") or ""), limit=200),
    }


def build_player_initiative_declaration(
    save: SaveFile,
    *,
    action_text: str,
    speech_text: str,
    forced_first: bool,
) -> InitiativeDeclaration:
    display_text = _submission_display_text(action_text, speech_text)
    return InitiativeDeclaration(
        actor_id=save.player_static_data.player_id,
        actor_type="player",
        actor_name=save.player_static_data.name,
        declared_action=display_text[:160],
        dex_modifier=int(save.player_static_data.dnd5e_sheet.current_ability_modifiers.dexterity),
        roll_d20=(20 if forced_first else random.randint(1, 20)),
        is_hidden=False,
        revealed_by_declaration=False,
        forced_first=forced_first,
    )


def build_initiative_declarations(
    save: SaveFile,
    *,
    player_action_text: str,
    mode: InitiativeMode = "hostile_only",
    addressed_role_name: str = "",
    incoming_target_candidates: list[str] | None = None,
    config: ChatConfig | None = None,
) -> list[InitiativeDeclaration]:
    declarations: list[InitiativeDeclaration] = []
    if mode == "hostile_only" and not str(player_action_text or "").strip():
        return declarations
    for actor in initiative_actor_rows(
        save,
        player_text=player_action_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=incoming_target_candidates,
        config=config,
    ):
        actor_id = str(actor.get("actor_id") or "")
        if not actor_id:
            continue
        actor_type = str(actor.get("actor_type") or "npc")
        declared_action = "joins the public turn"
        if actor_type == "team":
            declared_action = "team member steps into the public turn"
        elif actor_type == "hidden_npc":
            declared_action = "emerges into the public turn"
        declarations.append(
            InitiativeDeclaration(
                actor_id=actor_id,
                actor_type=("hidden_npc" if actor_type == "hidden_npc" else actor_type),  # type: ignore[arg-type]
                actor_name=str(actor.get("name") or actor_id),
                declared_action=declared_action,
                dex_modifier=dex_modifier_for_actor(actor),
                roll_d20=random.randint(1, 20),
                is_hidden=bool(actor.get("is_hidden")),
                revealed_by_declaration=False,
            )
        )
    return declarations


def finalize_initiative_totals(declarations: list[InitiativeDeclaration]) -> list[InitiativeDeclaration]:
    for item in declarations:
        if item.total_initiative is None:
            item.total_initiative = int(item.dex_modifier) + int(item.roll_d20 or 0)
    declarations.sort(
        key=lambda item: (
            1 if item.forced_first else 0,
            int(item.total_initiative or 0),
            int(item.dex_modifier),
            item.actor_name,
        ),
        reverse=True,
    )
    return declarations



def _player_action_check(
    save: SaveFile,
    *,
    session_id: str,
    actor_id: str,
    text: str,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
) -> ActionCheckResponse | None:
    if action_check is None:
        if not _requires_action_check(text):
            return None
        raise ValueError("PUBLIC_TURN_PLAYER_CHECK_REQUIRED")
    if not action_check.planned_requires_check:
        return None
    return world.action_check(
        ActionCheckRequest(
            session_id=session_id,
            actor_role_id=actor_id,
            action_type=action_check.action_type,
            action_prompt=text,
            source_context=action_check.source_context,
            resolution_rule=action_check.resolution_rule,
            target_role_id=action_check.target_role_id,
            target_name=action_check.target_name,
            target_actor_kind=action_check.target_actor_kind,
            target_ability_used=action_check.target_ability_used,
            target_ability_modifier=action_check.target_ability_modifier,
            forced_dice_roll=action_check.forced_dice_roll,
            resolution_context="embedded",
            planned_ability_used=action_check.planned_ability_used,
            planned_dc=action_check.planned_dc,
            planned_time_spent_min=action_check.planned_time_spent_min,
            planned_requires_check=action_check.planned_requires_check,
            planned_check_task=action_check.planned_check_task,
            config=config,
        )
    )


def resolve_player_submission(
    save: SaveFile,
    *,
    session_id: str,
    action_text: str,
    speech_text: str,
    round_state: PublicTurnRound,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
    include_information_check_prompt: bool = False,
) -> (
    tuple[
        list[SceneEvent],
        PublicTurnImpact,
        PublicTurnSettlementEntry,
        ActionCheckResponse | None,
        PublicTurnInformationCheckPrompt | None,
    ]
    | tuple[
        list[SceneEvent],
        PublicTurnImpact,
        PublicTurnSettlementEntry,
        ActionCheckResponse | None,
    ]
):
    display_text = _submission_display_text(action_text, speech_text)
    action_result = _player_action_check(
        save,
        session_id=session_id,
        actor_id=save.player_static_data.player_id,
        text=display_text,
        action_check=action_check,
        config=config,
    )
    consume_submission_resources_in_save(
        save,
        actor_role_id=save.player_static_data.player_id,
        action_text=action_text,
        speech_text=speech_text,
        entry_point="public_turn_action",
        config=config,
    )
    structured_situation_hint = 4 if action_check is not None and action_check.planned_requires_check else 0
    situation_delta = max(-20, min(20, structured_situation_hint + check_bonus(action_result)))
    relation_delta = relation_delta_from_result(action_result, situation_delta)
    gm_resolution_summary = _extract_resolution_summary_text(action_result.narrative, limit=280) if action_result is not None else ""
    current_primary_aggressor_name, current_primary_target_name, prior_settlement_excerpt = _recent_conflict_anchor(round_state)
    player_action_target_name = (
        str(action_result.target_name or "").strip()
        if action_result is not None
        else str(action_check.target_name or "").strip() if action_check is not None
        else ""
    )
    player_speech_target_name = player_action_target_name if speech_text.strip() else ""
    targeted_context = build_targeted_actor_text(
        actor_name=save.player_static_data.name,
        action_text=action_text,
        speech_text=speech_text,
        action_target_name=player_action_target_name,
        speech_target_name=player_speech_target_name,
    )
    scene_conflict_summary = "\n".join(
        part
        for part in (
            current_primary_aggressor_name and f"primary_aggressor={current_primary_aggressor_name}",
            current_primary_target_name and f"primary_target={current_primary_target_name}",
            player_action_target_name and f"player_action_target={player_action_target_name}",
            targeted_context.combined_text_for_ai,
            gm_resolution_summary or display_text,
        )
        if part
    )
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record(
            "public_turn_targeted_context",
            "built targeted player submission context",
            {
                "display_text": display_text,
                "targeted_context": targeted_context.debug_context_payload,
                "gm_resolution_summary": gm_resolution_summary,
            },
        )
    events: list[SceneEvent] = [
        world._new_scene_event(
            "public_turn_actor_action",
            display_text,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            metadata={
                "actor_type": "player",
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "action_text": action_text,
                "speech_text": speech_text,
            },
        )
    ]
    if gm_resolution_summary:
        events.append(
            world._new_scene_event(
                "public_turn_actor_resolution",
                gm_resolution_summary,
                actor_role_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                metadata={
                    "actor_type": "player",
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "resolution_rule": (action_result.resolution_rule if action_result is not None else (action_check.resolution_rule if action_check is not None else "static_dc")),
                    "check_outcome": ("none" if action_result is None else ("success" if action_result.success else "failure")),
                },
            )
        )
    resolved_action_type = action_check.action_type if action_check is not None else "check"
    hp_changes, damage_events = _resolve_public_turn_damage_bundle(
        save,
        session_id=session_id,
        actor_role_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        action_type=resolved_action_type,
        action_summary=action_text.strip() or display_text,
        speech_text=speech_text.strip(),
        action_prompt=display_text,
        specific_threat=gm_resolution_summary or action_text.strip() or display_text,
        fallback_target_name=player_action_target_name or None,
        action_result=action_result,
        round_state=round_state,
        config=config,
    )
    events.extend(damage_events)
    relation_rows, relation_events = apply_player_npc_reactions(
        save,
        session_id=session_id,
        player_text=targeted_context.combined_text_for_ai,
        summary=gm_resolution_summary or targeted_context.combined_text_for_ai,
        relation_delta=relation_delta,
        target_role_id=(action_result.target_role_id if action_result is not None else (action_check.target_role_id if action_check is not None else None)),
        player_action_target_name=player_action_target_name,
        current_primary_aggressor_name=current_primary_aggressor_name,
        current_primary_target_name=current_primary_target_name,
        prior_settlement_excerpt=prior_settlement_excerpt,
        scene_conflict_summary=scene_conflict_summary,
        config=config,
    )
    team_rows, reaction_events = apply_player_team_reactions(
        save,
        session_id=session_id,
        player_text=targeted_context.combined_text_for_ai,
        summary=gm_resolution_summary or targeted_context.combined_text_for_ai,
        player_action_target_name=player_action_target_name,
        current_primary_aggressor_name=current_primary_aggressor_name,
        current_primary_target_name=current_primary_target_name,
        prior_settlement_excerpt=prior_settlement_excerpt,
        scene_conflict_summary=scene_conflict_summary,
        config=config,
    )
    save.game_logs.append(
        world._new_game_log(
            session_id,
            "public_turn_player_action",
            f"{save.player_static_data.name} 閸︺劌鍙曞鈧崶鐐叉値娑擃叀顢戦崝顭掔窗{display_text[:120]}",
            {
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "situation_delta": situation_delta,
                "relation_delta": relation_delta,
            },
        )
    )
    events.extend(relation_events)
    events.extend(reaction_events)
    impact = build_impact(
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        action_summary=action_text.strip() or display_text,
        action_result=action_result,
        situation_delta=situation_delta,
        zone_reputation_delta=(reputation_delta_from_situation(situation_delta) if public_turn_zone_reputation_allowed("player") else 0),
        relation_deltas=relation_rows,
        team_affinity_deltas=team_rows,
        hp_changes=hp_changes,
        environment_shift=0,
        scene_events=events,
    )
    if not gm_resolution_summary and action_result is not None and action_result.resolution_rule == "opposed_actor":
        gm_resolution_summary = _generate_opposed_resolution_summary(
            session_id=session_id,
            actor_name=save.player_static_data.name,
            target_name=str((action_result.target_name if action_result is not None else player_action_target_name) or "Unknown target"),
            actor_action_summary=action_text.strip() or display_text,
            actor_speech_text=speech_text.strip(),
            target_action_summary="",
            target_speech_text="",
            stakes_summary=display_text,
            action_result=action_result,
            config=config,
        )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        actor_type="player",
        action_summary=action_text.strip() or display_text,
        speech_text=speech_text.strip(),
        action_result=action_result,
        impact=impact,
        gm_resolution_summary=gm_resolution_summary,
        action_target_actor_id=(action_result.target_role_id if action_result is not None else (action_check.target_role_id if action_check is not None else None)),
        action_target_name=player_action_target_name or None,
        action_target_kind=(
            settlement_actor_type("player")
            if player_action_target_name == save.player_static_data.name
            else None
        ),
        source_world_impact_type=(
            PublicTurnWorldImpactType.WORLD
            if resolved_action_type in {"attack", "item_use", "check"} and (action_result is not None or action_check is not None)
            else PublicTurnWorldImpactType.NON_WORLD
        ),
        opposed_target_name=(action_result.target_name if action_result is not None else None),
    )
    information_check_prompt: PublicTurnInformationCheckPrompt | None = None
    if (
        action_check is not None
        and action_check.public_turn_resolution_mode == "opposed_then_information_dc"
        and action_result is not None
        and action_result.success
        and action_check.followup_ability_used is not None
        and action_check.followup_dc is not None
    ):
        ability_used = action_check.followup_ability_used
        ability_modifier = int(getattr(save.player_static_data.dnd5e_sheet.current_ability_modifiers, ability_used))
        information_check_prompt = PublicTurnInformationCheckPrompt(
            prompt_id=f"{round_state.round_id}_{save.player_static_data.player_id}_information_check",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.AWAITING_PLAYER_INFORMATION_CHECK,
            actor_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            source_actor_id=(action_result.target_role_id or action_check.target_role_id or None),
            source_actor_name=(action_result.target_name or action_check.target_name or None),
            source_interaction_kind=(action_check.public_turn_interaction_kind or "information_gathering"),
            notice_state=(action_check.public_turn_notice_state or "noticed"),
            ability_used=ability_used,
            ability_modifier=ability_modifier,
            dc=int(action_check.followup_dc),
            check_task=str(action_check.followup_check_task or action_check.planned_check_task or "获取当前线索"),
            stakes_summary=settlement.gm_resolution_summary or display_text,
            metadata={
                "action_text": action_text,
                "speech_text": speech_text,
                "action_result": action_result.model_dump(mode="json"),
                "settlement_entry_id": settlement.entry_id,
                "source_phase": round_state.phase.value,
            },
        )
    if include_information_check_prompt:
        return events, impact, settlement, action_result, information_check_prompt
    return events, impact, settlement, action_result


def _build_reaction_for_actor(
    actor: dict[str, object],
    *,
    payload: dict[str, object],
    situation_delta: int,
    action_target_name: str | None = None,
) -> PlayerReactionCheck | None:
    if str(action_target_name or "").strip():
        return None
    action_type = str(payload.get("action_type") or "check").strip().lower()
    threat = str(payload.get("specific_threat") or "").strip()
    world_impact_type = str(payload.get("world_impact_type") or "").strip().lower()
    if action_type != "attack" and world_impact_type != PublicTurnWorldImpactType.WORLD.value and not threat:
        return None
    actor_name = str(actor.get("name") or "Unknown actor")
    return reaction_check_service.build_player_reaction_check(
        {
            "source_kind": "public_turn",
            "source_actor_id": str(actor.get("actor_id") or ""),
            "source_actor_name": actor_name,
            "source_label": actor_name,
            "trigger_summary": f"{actor_name} creates immediate public-turn pressure on the player.",
            "threatened_consequence": threat or "If the player does not respond, the pressure lands directly in the scene.",
            "ability_used": "dexterity",
            "dc": max(8, min(18, 10 + max(0, situation_delta // 2))),
            "check_task": f"React in time to {actor_name} before the public-turn pressure lands.",
            "success_hint": "The player reacts in time and reduces the immediate pressure.",
            "failure_hint": "The player reacts too late and the pressure lands anyway.",
            "critical_success_hint": "The player turns the timing completely around and seizes the moment.",
            "critical_failure_hint": "The player mishandles the timing and makes the opening worse.",
        },
        resolution_context="public_turn",
    )





def _auto_attack_response_for_target(
    save: SaveFile,
    *,
    source_actor_id: str,
    source_actor_name: str,
    source_action_summary: str,
    source_speech_text: str,
    target: PublicTurnResolvedAttackTarget,
    config: ChatConfig | None,
) -> tuple[str, str]:
    response = build_ai_interaction_response(
        save,
        target=_attack_target_as_interaction_target(target),
        source_actor_id=source_actor_id,
        source_actor_name=source_actor_name,
        source_world_impact_type=PublicTurnWorldImpactType.WORLD,
        source_action_summary=source_action_summary,
        source_speech_text=source_speech_text,
        gm_summary=source_action_summary or source_actor_name,
        config=config,
    )
    return response.action_summary, response.speech_text


def _run_attack_contest_check(
    save: SaveFile,
    *,
    session_id: str,
    source_actor_id: str,
    source_actor_name: str,
    source_action_summary: str,
    source_speech_text: str,
    target_actor_id: str,
    target_actor_name: str,
    target_action_summary: str,
    target_speech_text: str,
    attack_ability_used: str,
    defense_ability_used: str,
    forced_target_dice_roll: int | None,
    config: ChatConfig | None,
) -> ActionCheckResponse:
    target_modifier = attack_ability_modifier(save, target_actor_id, defense_ability_used)
    return world.action_check(
        ActionCheckRequest(
            session_id=session_id,
            actor_role_id=source_actor_id,
            action_type="attack",
            action_prompt="\n".join(
                part
                for part in (
                    source_action_summary.strip(),
                    source_speech_text.strip(),
                    target_action_summary.strip(),
                    target_speech_text.strip(),
                )
                if part
            ).strip()
            or source_action_summary.strip(),
            source_context="public_turn",
            resolution_rule="opposed_actor",
            target_role_id=target_actor_id,
            target_name=target_actor_name,
            target_actor_kind=("player" if target_actor_id == save.player_static_data.player_id else "npc"),
            target_ability_used=defense_ability_used,  # type: ignore[arg-type]
            target_ability_modifier=target_modifier,
            forced_target_dice_roll=forced_target_dice_roll,
            allow_backend_roll=True,
            resolution_context="embedded",
            planned_ability_used=attack_ability_used,  # type: ignore[arg-type]
            planned_dc=max(5, min(30, 10 + int(target_modifier))),
            planned_time_spent_min=1,
            planned_requires_check=True,
            planned_check_task=f"{source_actor_name} attacks {target_actor_name}",
            config=config,
        )
    )


def _resolve_attack_damage_to_targets(
    save: SaveFile,
    *,
    session_id: str,
    source_actor_id: str,
    source_actor_name: str,
    action_summary: str,
    speech_text: str,
    attack_assessment: dict[str, object],
    hit_targets: list[PublicTurnResolvedAttackTarget],
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[list[dict[str, Any]], list[SceneEvent]]:
    if not hit_targets:
        return [], []
    basis, definition = resolve_attack_definition(
        save,
        actor_role_id=source_actor_id,
        attack_definition_id=str(attack_assessment.get("attack_definition_id") or ""),
        attack_basis_hint=str(attack_assessment.get("attack_basis") or ""),
    )
    damage_dice, damage_bonus, damage_type = definition_damage_payload(definition)
    damage = roll_damage_dice(damage_dice, damage_bonus) if damage_dice or damage_bonus else 0
    if damage <= 0 and has_ai_config(config):
        damage_bundle = _ai_public_turn_damage_bundle(
            save,
            actor_role_id=source_actor_id,
            actor_name=source_actor_name,
            action_type="attack",
            action_summary=action_summary,
            speech_text=speech_text,
            action_prompt=action_summary,
            specific_threat=action_summary,
            fallback_target_name=hit_targets[0].actor_name,
            action_result=None,
            config=config,
        )
        damage = max(0, int(damage_bundle.get("base_damage") or 0))
        damage_type = str(damage_bundle.get("damage_type") or damage_type or "").strip()
    if damage <= 0:
        return [], []
    hp_changes: list[dict[str, Any]] = []
    scene_events: list[SceneEvent] = []
    resolved_damage_type = damage_type or ("force" if basis == "spell" else "damage")
    for target in hit_targets:
        hp_change, damage_events = _apply_public_turn_hp_damage(
            save,
            source_actor_id=source_actor_id,
            source_actor_name=source_actor_name,
            target=_attack_target_as_interaction_target(target),
            damage=damage,
            damage_type=resolved_damage_type,
            round_id=round_state.round_id,
            phase=round_state.phase,
        )
        if hp_change is not None:
            hp_changes.append(hp_change)
        scene_events.extend(damage_events)
    return hp_changes, scene_events


def _build_attack_resolution_bundle(
    *,
    save: SaveFile,
    session_id: str,
    round_state: PublicTurnRound,
    actor_id: str,
    actor_name: str,
    actor_type: str,
    action_summary: str,
    speech_text: str,
    action_result: ActionCheckResponse | None,
    attack_assessment: dict[str, object],
    threatened_targets: list[PublicTurnResolvedAttackTarget],
    hit_targets: list[PublicTurnResolvedAttackTarget],
    avoided_targets: list[PublicTurnResolvedAttackTarget],
    revealed_target_names: list[str],
    defense_action_text: str,
    defense_speech_text: str,
    base_events: list[SceneEvent],
    config: ChatConfig | None,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry]:
    hp_changes, damage_events = _resolve_attack_damage_to_targets(
        save,
        session_id=session_id,
        source_actor_id=actor_id,
        source_actor_name=actor_name,
        action_summary=action_summary,
        speech_text=speech_text,
        attack_assessment=attack_assessment,
        hit_targets=hit_targets,
        round_state=round_state,
        config=config,
    )
    situation_delta = public_scene_legacy._clamp(
        int(attack_assessment.get("situation_delta_hint") or 0) + check_bonus(action_result),
        -20,
        20,
    )
    reputation_delta = 0
    if public_turn_zone_reputation_allowed(actor_type):
        reputation_delta = public_scene_legacy._clamp(
            int(attack_assessment.get("reputation_delta_hint") or reputation_delta_from_situation(situation_delta)),
            -3,
            3,
        )
    hit_target_names = [item.actor_name for item in hit_targets]
    avoided_target_names = [item.actor_name for item in avoided_targets]
    threatened_target_names = [item.actor_name for item in threatened_targets]
    gm_resolution_summary = generate_attack_outcome_narration(
        source_actor_name=actor_name,
        target_actor_name=(threatened_target_names[0] if threatened_target_names else None),
        action_summary=action_summary,
        speech_text=speech_text,
        attack_assessment=attack_assessment,
        defense_action_text=defense_action_text,
        defense_speech_text=defense_speech_text,
        hit_target_names=hit_target_names,
        avoided_target_names=avoided_target_names,
        revealed_target_names=revealed_target_names,
        hp_changes=hp_changes,
        config=config,
    )
    scene_events = [*base_events, *damage_events]
    if gm_resolution_summary:
        scene_events.append(
            world._new_scene_event(
                "public_turn_actor_resolution",
                gm_resolution_summary,
                actor_role_id=actor_id,
                actor_name=actor_name,
                metadata={
                    "actor_type": actor_type,
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "attack_kind": str(attack_assessment.get("attack_kind") or ""),
                    "hit_target_names": hit_target_names,
                    "avoided_target_names": avoided_target_names,
                },
            )
        )
    impact = build_impact(
        actor_id=actor_id,
        actor_name=actor_name,
        action_summary=action_summary,
        action_result=action_result,
        situation_delta=situation_delta,
        zone_reputation_delta=reputation_delta,
        relation_deltas=[],
        team_affinity_deltas=[],
        hp_changes=hp_changes,
        environment_shift=0,
        scene_events=scene_events,
    )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_type=actor_type,
        action_summary=action_summary,
        speech_text=speech_text,
        action_result=action_result,
        impact=impact,
        gm_resolution_summary=gm_resolution_summary,
        action_target_actor_id=(threatened_targets[0].actor_id if len(threatened_targets) == 1 else None),
        action_target_name=(threatened_target_names[0] if len(threatened_target_names) == 1 else None),
        action_target_kind=(threatened_targets[0].actor_type if len(threatened_targets) == 1 else None),
        source_world_impact_type=PublicTurnWorldImpactType.WORLD,
        target_response_world_impact_type=PublicTurnWorldImpactType.WORLD if defense_action_text.strip() else PublicTurnWorldImpactType.NON_WORLD,
        interaction_exchange_kind="world_exchange",
        alternation_depth=0,
        target_response_kind=("explicit_response" if defense_action_text.strip() or defense_speech_text.strip() else "no_action"),
        interaction_target_name=(threatened_target_names[0] if threatened_target_names else None),
        interaction_resolution=("rejected_opposed" if action_result is not None and action_result.resolution_rule == "opposed_actor" else "accepted"),
        attack_kind=str(attack_assessment.get("attack_kind") or ""),
        attack_basis=str(attack_assessment.get("attack_basis") or ""),
        attack_definition_id=(str(attack_assessment.get("attack_definition_id") or "") or None),
        attack_definition_name=(str(attack_assessment.get("attack_definition_name") or "") or None),
        attack_area_shape=(str(attack_assessment.get("attack_area_shape") or "") or None),
        threatened_target_names=threatened_target_names,
        hit_target_names=hit_target_names,
        avoided_target_names=avoided_target_names,
        revealed_target_names=revealed_target_names,
        opposed_target_name=(avoided_target_names[0] if avoided_target_names else None),
        opposed_target_action=(defense_action_text or None),
        opposed_target_speech=(defense_speech_text or None),
    )
    return scene_events, impact, settlement


def _attack_targets_from_metadata(
    save: SaveFile,
    *,
    actor_ids: list[str] | None = None,
    actor_names: list[str] | None = None,
) -> list[PublicTurnResolvedAttackTarget]:
    actor_ids = [str(item or "").strip() for item in (actor_ids or []) if str(item or "").strip()]
    actor_names = [str(item or "").strip() for item in (actor_names or []) if str(item or "").strip()]
    candidates = resolve_attack_candidates(save, include_hidden=True)
    resolved: list[PublicTurnResolvedAttackTarget] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.actor_id in seen:
            continue
        if candidate.actor_id in actor_ids or candidate.actor_name in actor_names:
            resolved.append(candidate)
            seen.add(candidate.actor_id)
    return resolved


def _attack_targets_with_fallback(
    save: SaveFile,
    *,
    actor_ids: list[str] | None = None,
    actor_names: list[str] | None = None,
    fallback_actor_name: str | None = None,
) -> list[PublicTurnResolvedAttackTarget]:
    targets = _attack_targets_from_metadata(save, actor_ids=actor_ids, actor_names=actor_names)
    fallback_name = str(fallback_actor_name or "").strip()
    if not fallback_name:
        return targets
    fallback_targets = _attack_targets_from_metadata(save, actor_names=[fallback_name])
    if not fallback_targets:
        return targets
    seen_ids = {item.actor_id for item in targets}
    for target in fallback_targets:
        if target.actor_id not in seen_ids:
            targets.append(target)
            seen_ids.add(target.actor_id)
    return targets


def _build_attack_prompt(
    *,
    round_state: PublicTurnRound,
    source_actor_id: str,
    source_actor_name: str,
    source_action_summary: str,
    source_speech_text: str,
    current_target: PublicTurnResolvedAttackTarget,
    attack_assessment: dict[str, object],
    threatened_targets: list[PublicTurnResolvedAttackTarget],
    revealed_target_names: list[str],
    metadata: dict[str, Any],
) -> PublicTurnAttackPrompt:
    return PublicTurnAttackPrompt(
        prompt_id=f"{round_state.round_id}_{source_actor_id}_attack_prompt",
        round_id=round_state.round_id,
        phase=round_state.phase,
        source_actor_id=source_actor_id,
        source_actor_name=source_actor_name,
        source_action_summary=source_action_summary,
        source_speech_text=source_speech_text,
        attack_kind=str(attack_assessment.get("attack_kind") or "targeted_attack"),  # type: ignore[arg-type]
        attack_basis=str(attack_assessment.get("attack_basis") or "other"),  # type: ignore[arg-type]
        attack_definition_id=(str(attack_assessment.get("attack_definition_id") or "") or None),
        attack_definition_name=(str(attack_assessment.get("attack_definition_name") or "") or None),
        attack_area_shape=str(attack_assessment.get("attack_area_shape") or "none"),  # type: ignore[arg-type]
        attack_area_radius_m=float(attack_assessment.get("attack_area_radius_m") or 0),
        attack_area_length_m=float(attack_assessment.get("attack_area_length_m") or 0),
        can_include_self=(str(attack_assessment.get("self_target_policy") or "never") != "never"),
        current_target_actor_id=current_target.actor_id,
        current_target_name=current_target.actor_name,
        current_target_kind=current_target.actor_type,
        threatened_target_names=[item.actor_name for item in threatened_targets],
        revealed_target_names=list(revealed_target_names),
        player_in_danger=(current_target.actor_type == PublicTurnActorType.PLAYER),
        attack_ability_used=(str(attack_assessment.get("attack_ability_used") or "") or None),  # type: ignore[arg-type]
        suggested_response_hint="Respond in the world if you want to disrupt or avoid this attack; otherwise the attack may resolve directly.",
        metadata={**metadata, "source_world_impact_type": PublicTurnWorldImpactType.WORLD.value},
    )


def _maybe_build_player_opposed_prompt(
    save: SaveFile,
    *,
    actor: dict[str, object],
    payload: dict[str, object],
    round_state: PublicTurnRound,
    action_content: str,
) -> PublicTurnOpposedPrompt | None:
    actor_id = str(actor.get("actor_id") or "")
    if not actor_id or actor_id == save.player_static_data.player_id:
        return None
    action_type = str(payload.get("action_type") or "check").strip().lower()
    if action_type == "attack":
        return None
    if str(payload.get("world_impact_type") or "").strip().lower() != PublicTurnWorldImpactType.WORLD.value:
        return None
    combined = "\n".join(
        part.strip()
        for part in (
            str(payload.get("action_prompt") or ""),
            str(payload.get("external_action_narration") or ""),
            str(payload.get("visible_intent") or ""),
            str(payload.get("specific_threat") or ""),
            str(payload.get("target_label") or ""),
        )
        if str(part or "").strip()
    )
    target = resolve_interaction_target(
        save,
        actor_role_id=actor_id,
        action_prompt=str(payload.get("action_prompt") or ""),
        target_label=str(payload.get("target_label") or ""),
    )
    if target is None or target.actor_id != save.player_static_data.player_id:
        return None
    player_name = save.player_static_data.name
    if not any(marker and marker in combined for marker in (player_name,)):
        return None
    return PublicTurnOpposedPrompt(
        check_id=f"{round_state.round_id}_{actor_id}_opposed",
        round_id=round_state.round_id,
        phase=round_state.phase,
        source_actor_id=actor_id,
        source_actor_name=str(actor.get("name") or ""),
        source_action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content)[:200],
        source_speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or "")[:200],
        source_situation_delta_hint=int(payload.get("situation_delta_hint") or 0),
        source_reputation_delta_hint=int(payload.get("reputation_delta_hint") or 0),
        target_actor_id=save.player_static_data.player_id,
        target_actor_name=player_name,
        stakes_summary=str(payload.get("specific_threat") or action_content)[:240],
    )


def _finalize_ai_actor_turn(
    save: SaveFile,
    *,
    session_id: str,
    actor: dict[str, object],
    payload: dict[str, object],
    round_state: PublicTurnRound,
    action_content: str,
    action_result: ActionCheckResponse | None,
    reputation_score: int,
    config: ChatConfig | None,
    base_events: list[SceneEvent],
    action_target_actor_id: str | None = None,
    action_target_name: str | None = None,
    action_target_kind: PublicTurnActorType | None = None,
    speech_target_actor_id: str | None = None,
    speech_target_name: str | None = None,
    speech_target_kind: PublicTurnActorType | None = None,
    source_world_impact_type: PublicTurnWorldImpactType = PublicTurnWorldImpactType.NON_WORLD,
    target_response_world_impact_type: PublicTurnWorldImpactType = PublicTurnWorldImpactType.NON_WORLD,
    interaction_exchange_kind: str = "world_exchange",
    alternation_depth: int = 0,
    target_response_kind: str = "explicit_response",
    interaction_target_name: str | None = None,
    interaction_resolution: str = "non_interactive",
    opposed_target_name: str | None = None,
    opposed_target_action: str | None = None,
    opposed_target_speech: str | None = None,
    opposed_target_speech_target_name: str | None = None,
    gm_resolution_summary: str = "",
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry, int]:
    actor_id = str(actor.get("actor_id") or "")
    events = list(base_events)
    del reputation_score
    actor_type = str(actor.get("actor_type") or "npc")
    situation_delta = public_scene_legacy._clamp(int(payload.get("situation_delta_hint") or 0) + check_bonus(action_result), -20, 20)
    reputation_hint = payload.get("reputation_delta_hint")
    reputation_delta = 0
    if public_turn_zone_reputation_allowed(actor_type):
        if reputation_hint is None:
            reputation_delta = reputation_delta_from_situation(situation_delta)
        else:
            reputation_delta = public_scene_legacy._clamp(int(reputation_hint or 0), -3, 3)
    relation_rows: list[dict[str, Any]] = []
    team_rows: list[dict[str, Any]] = []
    hp_changes, damage_events = _resolve_public_turn_damage_bundle(
        save,
        session_id=session_id,
        actor_role_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        action_type=str(payload.get("action_type") or "check"),
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or ""),
        action_prompt=str(payload.get("action_prompt") or action_content),
        specific_threat=str(payload.get("specific_threat") or ""),
        fallback_target_name=action_target_name or (action_result.target_name if action_result is not None else None),
        action_result=action_result,
        round_state=round_state,
        config=config,
    )
    events.extend(damage_events)
    resolution_text = _last_nonempty_line(action_result.narrative if action_result is not None else "")
    if resolution_text:
        events.append(
            world._new_scene_event(
                "public_turn_actor_resolution",
                resolution_text,
                actor_role_id=actor_id,
                actor_name=str(actor.get("name") or ""),
                metadata={
                    "actor_type": actor_type,
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "situation_delta": situation_delta,
                    "reputation_delta": reputation_delta,
                    "check_outcome": ("none" if action_result is None else ("success" if action_result.success else "failure")),
                },
            )
        )
    impact = build_impact(
        actor_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        action_result=action_result,
        situation_delta=situation_delta,
        zone_reputation_delta=reputation_delta,
        relation_deltas=relation_rows,
        team_affinity_deltas=team_rows,
        hp_changes=hp_changes,
        environment_shift=0,
        scene_events=events,
    )
    resolution_summary = gm_resolution_summary
    if (
        not resolution_summary
        and action_result is not None
        and action_result.resolution_rule == "opposed_actor"
        and opposed_target_name
        and opposed_target_action
    ):
        resolution_summary = _generate_opposed_resolution_summary(
            session_id=session_id,
            actor_name=str(actor.get("name") or ""),
            target_name=opposed_target_name,
            actor_action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
            actor_speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or ""),
            target_action_summary=opposed_target_action,
            target_speech_text=opposed_target_speech or "",
            stakes_summary=str(payload.get("specific_threat") or action_content),
            action_result=action_result,
            config=config,
        )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        actor_type=actor_type,
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or ""),
        action_result=action_result,
        impact=impact,
        gm_resolution_summary=resolution_summary,
        action_target_actor_id=action_target_actor_id,
        action_target_name=action_target_name,
        action_target_kind=action_target_kind,
        speech_target_actor_id=speech_target_actor_id,
        speech_target_name=speech_target_name,
        speech_target_kind=speech_target_kind,
        source_world_impact_type=source_world_impact_type,
        target_response_world_impact_type=target_response_world_impact_type,
        interaction_exchange_kind=interaction_exchange_kind,
        alternation_depth=alternation_depth,
        target_response_kind=target_response_kind,
        interaction_target_name=interaction_target_name,
        interaction_resolution=interaction_resolution,
        opposed_target_name=opposed_target_name or (action_result.target_name if action_result is not None else None),
        opposed_target_action=opposed_target_action,
        opposed_target_speech=opposed_target_speech,
        opposed_target_speech_target_name=opposed_target_speech_target_name,
    )
    return events, impact, settlement, situation_delta


def resolve_ai_actor_turn(
    save: SaveFile,
    *,
    actor: dict[str, object],
    player_text: str,
    gm_summary: str,
    round_state: PublicTurnRound,
    scene_context: dict[str, object],
    audience_context: dict[str, object],
    reputation_score: int,
    config: ChatConfig | None,
) -> tuple[
    list[SceneEvent],
    PublicTurnImpact | None,
    PublicTurnSettlementEntry | None,
    PlayerReactionCheck | None,
    PublicTurnOpposedPrompt | None,
]:
    actor_id = str(actor.get("actor_id") or "")
    raw_payload = public_scene_runtime._ai_actor_action(
        save,
        actor,
        player_text=player_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        incoming_interaction=None,
        allow_partial=True,
        config=config,
    )
    payload = normalize_public_turn_ai_payload(
        raw_payload,
        actor_name=str(actor.get("name") or ""),
        audience_may_speak=public_scene_runtime.actor_may_speak_in_public_turn(actor, audience_context),
    )
    action_target = resolve_interaction_target(
        save,
        actor_role_id=actor_id,
        action_prompt=str(payload.get("action_prompt") or ""),
        target_label=str(payload.get("target_label") or ""),
    )
    speech_target = resolve_speech_target(
        save,
        actor_role_id=actor_id,
        action_prompt=str(payload.get("action_prompt") or ""),
        speech_target_label=str(payload.get("speech_target_label") or ""),
        fallback_target=action_target,
    )
    action_content = "\n".join(
        part for part in (str(payload.get("external_action_narration") or ""), str(payload.get("speech_line") or "")) if part.strip()
    ).strip() or "No visible action."
    action_event = world._new_scene_event(
        "public_turn_actor_action",
        action_content,
        actor_role_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        metadata={
            "actor_type": str(actor.get("actor_type") or "npc"),
            "round_id": round_state.round_id,
            "phase": round_state.phase.value,
            "target_label": str(payload.get("target_label") or ""),
            "specific_threat": str(payload.get("specific_threat") or ""),
        },
    )
    events: list[SceneEvent] = [action_event]
    if any(str(payload.get(key) or "").strip() for key in ("external_action_narration", "speech_line", "specific_threat")):
        public_scene_legacy._append_actor_memory(
            save,
            actor,
            display_text=player_text,
            action_line=action_content,
            priority_reason=str(actor.get("priority_reason") or ""),
        )
    source_role = actor.get("role")
    actor_profile = getattr(source_role, "profile", None) if source_role is not None else None
    if actor_profile is not None:
        consume_action_resources_in_profile(
            actor_profile,
            action_text=" ".join(
                part
                for part in (
                    str(payload.get("external_action_narration") or ""),
                    str(payload.get("visible_intent") or ""),
                    str(payload.get("action_prompt") or ""),
                )
                if part.strip()
            ),
            speech_text=str(payload.get("speech_line") or ""),
        )
    opposed_prompt = _maybe_build_player_opposed_prompt(
        save,
        actor=actor,
        payload=payload,
        round_state=round_state,
        action_content=action_content,
    )
    if opposed_prompt is not None:
        return events, None, None, None, opposed_prompt
    requires_check = public_scene_runtime.should_force_public_action_check(save, actor, payload, config=config)
    action_result = None
    if requires_check and str(payload.get("action_prompt") or "").strip():
        action_result = public_scene_legacy._actor_check(
            save,
            actor_id,
            action_type=str(payload.get("action_type") or "check"),
            action_prompt=str(payload.get("action_prompt") or action_content),
            config=config,
        )
    events, impact, settlement, situation_delta = _finalize_ai_actor_turn(
        save,
        session_id=save.session_id,
        actor=actor,
        payload=payload,
        round_state=round_state,
        action_content=action_content,
        action_result=action_result,
        reputation_score=reputation_score,
        config=config,
        base_events=events,
        action_target_actor_id=(action_target.actor_id if action_target is not None else None),
        action_target_name=(action_target.name if action_target is not None else None),
        action_target_kind=(action_target.actor_type if action_target is not None else None),
        speech_target_actor_id=(speech_target.actor_id if speech_target is not None else None),
        speech_target_name=(speech_target.name if speech_target is not None else None),
        speech_target_kind=(speech_target.actor_type if speech_target is not None else None),
    )
    pending_reaction = _build_reaction_for_actor(
        actor,
        payload=payload,
        situation_delta=situation_delta,
        action_target_name=(settlement.action_target_name if settlement is not None else None),
    )
    return events, impact, settlement, pending_reaction, None


def resolve_ai_round(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    gm_summary: str,
    round_state: PublicTurnRound,
    exclude_actor_ids: set[str],
    config: ChatConfig | None,
) -> tuple[
    list[SceneEvent],
    list[PublicTurnImpact],
    list[PublicTurnSettlementEntry],
    PlayerReactionCheck | None,
    PublicTurnOpposedPrompt | None,
]:
    intent = world._parse_player_intent(player_text)
    display_text = str(intent.get("display_text") or player_text).strip()
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    audience_context = public_scene_runtime.build_public_audience_context(save, intent)
    scene_context = world._build_scene_context_payload(save, player_text=player_text, gm_narration=gm_summary, recent_turn_count=4)
    candidates = public_turn_normal_actor_rows(
        save,
        player_text=display_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=[str(item) for item in list(intent.get("incoming_target_candidates") or [])],
        config=config,
    )
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = getattr(zone_metric, "reputation_score", 50)
    scene_events: list[SceneEvent] = []
    impacts: list[PublicTurnImpact] = []
    settlements: list[PublicTurnSettlementEntry] = []
    pending_reaction: PlayerReactionCheck | None = None
    opposed_prompt: PublicTurnOpposedPrompt | None = None
    seen_actor_ids = set(exclude_actor_ids)
    for actor in candidates:
        actor_id = str(actor.get("actor_id") or "")
        if not actor_id or actor_id in seen_actor_ids:
            continue
        seen_actor_ids.add(actor_id)
        role = actor.get("role")
        if (
            str(actor.get("actor_type") or "") == "team"
            and isinstance(role, NpcRoleCard)
            and role.profile.dnd5e_sheet.role_action_status == "death_saving"
        ):
            actor_events, actor_impact, settlement = resolve_team_npc_death_save_turn(
                save,
                actor=actor,
                round_state=round_state,
            )
            scene_events.extend(actor_events)
            impacts.append(actor_impact)
            settlements.append(settlement)
            continue
        actor_events, actor_impact, settlement, pending_reaction, opposed_prompt = resolve_ai_actor_turn(
            save,
            actor=actor,
            player_text=display_text,
            gm_summary=gm_summary,
            round_state=round_state,
            scene_context=scene_context,
            audience_context=audience_context,
            reputation_score=reputation_score,
            config=config,
        )
        scene_events.extend(actor_events)
        if actor_impact is not None:
            impacts.append(actor_impact)
        if settlement is not None:
            settlements.append(settlement)
        if opposed_prompt is not None:
            break
        if pending_reaction is not None:
            break
    return scene_events, impacts, settlements, pending_reaction, opposed_prompt


def resolve_opposed_prompt_submission(
    save: SaveFile,
    *,
    session_id: str,
    prompt: PublicTurnOpposedPrompt,
    target_action_summary: str,
    target_speech_text: str,
    forced_dice_roll: int,
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry, ActionCheckResponse]:
    action_target_actor_id, action_target_name, action_target_kind = _prompt_action_target_details(
        prompt_target_actor_id=prompt.target_actor_id,
        prompt_target_actor_name=prompt.target_actor_name,
        prompt_target_actor_kind=(settlement_actor_type("player") if prompt.target_actor_id == save.player_static_data.player_id else None),
        source_action_target_name=prompt.source_action_target_name,
    )
    plan = world.plan_public_turn_opposed_exchange(
        PublicTurnOpposedPlanRequest(
            session_id=session_id,
            round_id=prompt.round_id,
            check_id=prompt.check_id,
            source_actor_id=prompt.source_actor_id,
            target_actor_id=prompt.target_actor_id,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            target_action_summary=target_action_summary,
            target_speech_text=target_speech_text,
            config=config,
        )
    )
    source_role = next((item for item in save.role_pool if item.role_id == prompt.source_actor_id), None)
    actor_type = "team" if any(item.role_id == prompt.source_actor_id for item in getattr(save.team_state, "members", [])) else "npc"
    actor = {
        "actor_id": prompt.source_actor_id,
        "name": prompt.source_actor_name,
        "actor_type": actor_type,
        "role": source_role,
    }
    action_content = "\n".join(
        part
        for part in (prompt.source_action_summary.strip(), prompt.source_speech_text.strip())
        if part
    ).strip() or prompt.source_action_summary.strip() or prompt.stakes_summary
    action_result = world.action_check(
        ActionCheckRequest(
            session_id=session_id,
            actor_role_id=prompt.source_actor_id,
            action_type="check",
            action_prompt="\n".join(
                part
                for part in (
                    prompt.source_action_summary.strip(),
                    prompt.source_speech_text.strip(),
                    target_action_summary.strip(),
                    target_speech_text.strip(),
                )
                if part
            ).strip() or prompt.source_action_summary.strip() or prompt.stakes_summary,
            source_context="public_turn",
            resolution_rule="opposed_actor",
            target_role_id=prompt.target_actor_id,
            target_name=prompt.target_actor_name,
            target_actor_kind=("player" if prompt.target_actor_id == save.player_static_data.player_id else "npc"),
            target_ability_used=plan.target_ability_used,
            target_ability_modifier=plan.target_ability_modifier,
            forced_target_dice_roll=forced_dice_roll,
            allow_backend_roll=True,
            resolution_context="embedded",
            planned_ability_used=plan.source_ability_used,
            planned_dc=max(5, min(30, 10 + int(plan.target_ability_modifier))),
            planned_time_spent_min=1,
            planned_requires_check=True,
            planned_check_task=plan.check_task,
            config=config,
        )
    )
    gm_resolution_summary = _generate_opposed_resolution_summary(
        session_id=session_id,
        actor_name=prompt.source_actor_name,
        target_name=prompt.target_actor_name,
        actor_action_summary=prompt.source_action_summary,
        actor_speech_text=prompt.source_speech_text,
        target_action_summary=target_action_summary,
        target_speech_text=target_speech_text,
        stakes_summary=prompt.stakes_summary,
        action_result=action_result,
        config=config,
    )
    base_events = [
        world._new_scene_event(
            "public_turn_actor_action",
            action_content,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            metadata={
                "actor_type": actor_type,
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "target_label": prompt.source_action_target_name or "",
                "speech_target_label": prompt.source_speech_target_name or "",
                "specific_threat": prompt.stakes_summary,
            },
        )
    ]
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = getattr(zone_metric, "reputation_score", 50)
    payload = {
        "action_narration": prompt.source_action_summary,
        "visible_intent": prompt.source_action_summary,
        "speech_line": prompt.source_speech_text,
        "speech_summary": prompt.source_speech_text,
        "action_prompt": action_content,
        "specific_threat": prompt.stakes_summary,
        "situation_delta_hint": prompt.source_situation_delta_hint,
        "reputation_delta_hint": prompt.source_reputation_delta_hint,
    }
    events, impact, settlement, _ = _finalize_ai_actor_turn(
        save,
        session_id=session_id,
        actor=actor,
        payload=payload,
        round_state=round_state,
        action_content=action_content,
        action_result=action_result,
        reputation_score=reputation_score,
        config=config,
        base_events=base_events,
        action_target_actor_id=action_target_actor_id,
        action_target_name=action_target_name,
        action_target_kind=action_target_kind,
        speech_target_name=prompt.source_speech_target_name,
        opposed_target_name=prompt.target_actor_name,
        opposed_target_action=target_action_summary,
        opposed_target_speech=target_speech_text,
        gm_resolution_summary=gm_resolution_summary,
    )
    if (
        prompt.source_interaction_kind == "information_gathering"
        and action_result.success
        and prompt.followup_ability_used is not None
        and prompt.followup_dc is not None
        and prompt.source_actor_id != save.player_static_data.player_id
    ):
        followup_result = world.action_check(
            ActionCheckRequest(
                session_id=session_id,
                actor_role_id=prompt.source_actor_id,
                action_type="check",
                action_prompt="\n".join(
                    part
                    for part in (
                        prompt.source_action_summary.strip(),
                        prompt.source_speech_text.strip(),
                        target_action_summary.strip(),
                        target_speech_text.strip(),
                        str(prompt.followup_check_task or "").strip(),
                    )
                    if part
                ).strip()
                or prompt.source_action_summary.strip()
                or prompt.stakes_summary,
                source_context="public_turn",
                resolution_rule="static_dc",
                allow_backend_roll=True,
                resolution_context="embedded",
                planned_ability_used=prompt.followup_ability_used,
                planned_dc=prompt.followup_dc,
                planned_time_spent_min=1,
                planned_requires_check=True,
                planned_check_task=prompt.followup_check_task or prompt.stakes_summary or "获取当前线索",
                config=config,
            )
        )
        _apply_followup_check_to_settlement(settlement, impact, followup_result)
        followup_summary = _extract_resolution_summary_text(followup_result.narrative, limit=280) or settlement.gm_resolution_summary
        events.append(
            world._new_scene_event(
                "public_turn_information_check",
                followup_summary,
                actor_role_id=prompt.source_actor_id,
                actor_name=prompt.source_actor_name,
                metadata={
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "ability_used": prompt.followup_ability_used,
                    "dc": prompt.followup_dc,
                    "success": followup_result.success,
                    "critical": followup_result.critical,
                    "notice_state": prompt.followup_notice_state,
                },
            )
        )
    return events, impact, settlement, action_result


def resolve_player_attack_submission(
    save: SaveFile,
    *,
    session_id: str,
    action_text: str,
    speech_text: str,
    round_state: PublicTurnRound,
    action_check: PublicTurnPlayerActionCheck | None,
    config: ChatConfig | None,
) -> tuple[
    list[SceneEvent],
    PublicTurnImpact | None,
    PublicTurnSettlementEntry | None,
    ActionCheckResponse | None,
    PublicTurnAttackPrompt | None,
]:
    display_text = _submission_display_text(action_text, speech_text)
    base_events = [
        world._new_scene_event(
            "public_turn_actor_action",
            display_text,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            metadata={
                "actor_type": "player",
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "action_text": action_text,
                "speech_text": speech_text,
            },
        )
    ]
    attack_assessment = assess_public_turn_attack(
        save,
        actor_role_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        action_summary=action_text.strip() or display_text,
        speech_text=speech_text.strip(),
        action_prompt=display_text,
        fallback_target_name=(action_check.target_name if action_check is not None else None),
        config=config,
    )
    attack_assessment["situation_delta_hint"] = 0
    if public_turn_zone_reputation_allowed("player"):
        attack_assessment["reputation_delta_hint"] = reputation_delta_from_situation(0)
    if str(attack_assessment.get("attack_kind") or "ordinary_action") == "ordinary_action":
        events, impact, settlement, action_result = resolve_player_submission(
            save,
            session_id=session_id,
            action_text=action_text,
            speech_text=speech_text,
            round_state=round_state,
            action_check=action_check,
            config=config,
        )
        return events, impact, settlement, action_result, None

    threatened_targets: list[PublicTurnResolvedAttackTarget] = []
    revealed_target_names: list[str] = []
    if str(attack_assessment.get("attack_kind") or "") == "aoe_attack":
        threatened_targets, revealed_target_names = select_aoe_threatened_targets(
            save,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            action_summary=action_text.strip() or display_text,
            attack_assessment=attack_assessment,
            config=config,
        )
    else:
        threatened_targets = _attack_targets_with_fallback(
            save,
            actor_names=list(attack_assessment.get("candidate_target_names") or []),
            fallback_actor_name=(action_check.target_name if action_check is not None else None),
        )
    if not threatened_targets:
        events, impact, settlement, action_result = resolve_player_submission(
            save,
            session_id=session_id,
            action_text=action_text,
            speech_text=speech_text,
            round_state=round_state,
            action_check=action_check,
            config=config,
        )
        return events, impact, settlement, action_result, None
    attack_resource_text = action_text
    if str(attack_assessment.get("attack_basis") or "") in {"spell", "war_art"}:
        attack_resource_text = str(
            attack_assessment.get("attack_definition_name") or attack_assessment.get("attack_definition_id") or action_text
        ).strip() or action_text
    consume_submission_resources_in_save(
        save,
        actor_role_id=save.player_static_data.player_id,
        action_text=attack_resource_text,
        speech_text=speech_text,
        entry_point="public_turn_action",
        config=config,
    )

    hit_targets: list[PublicTurnResolvedAttackTarget] = []
    avoided_targets: list[PublicTurnResolvedAttackTarget] = []
    last_action_result: ActionCheckResponse | None = None
    defense_action_text = ""
    defense_speech_text = ""
    for target in threatened_targets:
        if target.actor_id == save.player_static_data.player_id:
            metadata = {
                "source_actor_type": "player",
                "source_action_summary": action_text.strip() or display_text,
                "source_speech_text": speech_text.strip(),
                "attack_assessment": attack_assessment,
                "threatened_target_actor_ids": [item.actor_id for item in threatened_targets],
                "revealed_target_names": list(revealed_target_names),
                "auto_hit_actor_ids": [item.actor_id for item in hit_targets],
                "auto_avoided_actor_ids": [item.actor_id for item in avoided_targets],
                "auto_hit_target_names": [item.actor_name for item in hit_targets],
                "auto_avoided_target_names": [item.actor_name for item in avoided_targets],
            }
            prompt = _build_attack_prompt(
                round_state=round_state,
                source_actor_id=save.player_static_data.player_id,
                source_actor_name=save.player_static_data.name,
                source_action_summary=action_text.strip() or display_text,
                source_speech_text=speech_text.strip(),
                current_target=target,
                attack_assessment=attack_assessment,
                threatened_targets=threatened_targets,
                revealed_target_names=revealed_target_names,
                metadata=metadata,
            )
            return base_events, None, None, last_action_result, prompt
        response_action, response_speech = _auto_attack_response_for_target(
            save,
            source_actor_id=save.player_static_data.player_id,
            source_actor_name=save.player_static_data.name,
            source_action_summary=action_text.strip() or display_text,
            source_speech_text=speech_text.strip(),
            target=target,
            config=config,
        )
        response_classification = classify_attack_response(
            source_actor_name=save.player_static_data.name,
            source_action_summary=action_text.strip() or display_text,
            source_speech_text=speech_text.strip(),
            target_actor_name=target.actor_name,
            response_action_text=response_action,
            response_speech_text=response_speech,
            response_kind=("explicit_response" if response_action.strip() or response_speech.strip() else "no_action"),
            config=config,
        )
        defense_action_text = response_action or defense_action_text
        defense_speech_text = response_speech or defense_speech_text
        if str(response_classification.get("world_impact_type") or "non_world") == "world" and bool(
            response_classification.get("effective_against_attack")
        ):
            action_result = _run_attack_contest_check(
                save,
                session_id=session_id,
                source_actor_id=save.player_static_data.player_id,
                source_actor_name=save.player_static_data.name,
                source_action_summary=action_text.strip() or display_text,
                source_speech_text=speech_text.strip(),
                target_actor_id=target.actor_id,
                target_actor_name=target.actor_name,
                target_action_summary=response_action,
                target_speech_text=response_speech,
                attack_ability_used=str(attack_assessment.get("attack_ability_used") or "strength"),
                defense_ability_used=str(response_classification.get("defense_ability_used") or "dexterity"),
                forced_target_dice_roll=None,
                config=config,
            )
            last_action_result = action_result
            if action_result.success:
                hit_targets.append(target)
            else:
                avoided_targets.append(target)
        else:
            hit_targets.append(target)
    events, impact, settlement = _build_attack_resolution_bundle(
        save=save,
        session_id=session_id,
        round_state=round_state,
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        actor_type="player",
        action_summary=action_text.strip() or display_text,
        speech_text=speech_text.strip(),
        action_result=last_action_result,
        attack_assessment=attack_assessment,
        threatened_targets=threatened_targets,
        hit_targets=hit_targets,
        avoided_targets=avoided_targets,
        revealed_target_names=revealed_target_names,
        defense_action_text=defense_action_text,
        defense_speech_text=defense_speech_text,
        base_events=base_events,
        config=config,
    )
    return events, impact, settlement, last_action_result, None


def prepare_npc_attack_prompt(
    save: SaveFile,
    *,
    source_actor_id: str,
    source_actor_name: str,
    source_actor_type: str,
    source_action_summary: str,
    source_speech_text: str,
    source_action_prompt: str,
    source_action_target_name: str | None,
    round_state: PublicTurnRound,
    situation_delta_hint: int,
    reputation_delta_hint: int,
    config: ChatConfig | None,
) -> PublicTurnAttackPrompt | None:
    attack_assessment = assess_public_turn_attack(
        save,
        actor_role_id=source_actor_id,
        actor_name=source_actor_name,
        action_summary=source_action_summary,
        speech_text=source_speech_text,
        action_prompt=source_action_prompt,
        fallback_target_name=source_action_target_name,
        config=config,
    )
    attack_assessment["situation_delta_hint"] = int(situation_delta_hint or 0)
    attack_assessment["reputation_delta_hint"] = int(reputation_delta_hint or 0)
    if str(attack_assessment.get("attack_kind") or "ordinary_action") == "ordinary_action":
        return None
    threatened_targets: list[PublicTurnResolvedAttackTarget] = []
    revealed_target_names: list[str] = []
    if str(attack_assessment.get("attack_kind") or "") == "aoe_attack":
        threatened_targets, revealed_target_names = select_aoe_threatened_targets(
            save,
            actor_role_id=source_actor_id,
            actor_name=source_actor_name,
            action_summary=source_action_summary,
            attack_assessment=attack_assessment,
            config=config,
        )
    else:
        threatened_targets = _attack_targets_with_fallback(
            save,
            actor_names=list(attack_assessment.get("candidate_target_names") or []),
            fallback_actor_name=source_action_target_name,
        )
    player_target = next((item for item in threatened_targets if item.actor_id == save.player_static_data.player_id), None)
    if player_target is None:
        return None
    hit_targets: list[PublicTurnResolvedAttackTarget] = []
    avoided_targets: list[PublicTurnResolvedAttackTarget] = []
    for target in threatened_targets:
        if target.actor_id == save.player_static_data.player_id:
            continue
        response_action, response_speech = _auto_attack_response_for_target(
            save,
            source_actor_id=source_actor_id,
            source_actor_name=source_actor_name,
            source_action_summary=source_action_summary,
            source_speech_text=source_speech_text,
            target=target,
            config=config,
        )
        response_classification = classify_attack_response(
            source_actor_name=source_actor_name,
            source_action_summary=source_action_summary,
            source_speech_text=source_speech_text,
            target_actor_name=target.actor_name,
            response_action_text=response_action,
            response_speech_text=response_speech,
            response_kind=("explicit_response" if response_action.strip() or response_speech.strip() else "no_action"),
            config=config,
        )
        if str(response_classification.get("world_impact_type") or "non_world") == "world" and bool(
            response_classification.get("effective_against_attack")
        ):
            action_result = _run_attack_contest_check(
                save,
                session_id=save.session_id,
                source_actor_id=source_actor_id,
                source_actor_name=source_actor_name,
                source_action_summary=source_action_summary,
                source_speech_text=source_speech_text,
                target_actor_id=target.actor_id,
                target_actor_name=target.actor_name,
                target_action_summary=response_action,
                target_speech_text=response_speech,
                attack_ability_used=str(attack_assessment.get("attack_ability_used") or "strength"),
                defense_ability_used=str(response_classification.get("defense_ability_used") or "dexterity"),
                forced_target_dice_roll=None,
                config=config,
            )
            if action_result.success:
                hit_targets.append(target)
            else:
                avoided_targets.append(target)
        else:
            hit_targets.append(target)
    metadata = {
        "source_actor_type": source_actor_type,
        "source_action_summary": source_action_summary,
        "source_speech_text": source_speech_text,
        "attack_assessment": attack_assessment,
        "threatened_target_actor_ids": [item.actor_id for item in threatened_targets],
        "revealed_target_names": list(revealed_target_names),
        "auto_hit_actor_ids": [item.actor_id for item in hit_targets],
        "auto_avoided_actor_ids": [item.actor_id for item in avoided_targets],
        "auto_hit_target_names": [item.actor_name for item in hit_targets],
        "auto_avoided_target_names": [item.actor_name for item in avoided_targets],
    }
    return _build_attack_prompt(
        round_state=round_state,
        source_actor_id=source_actor_id,
        source_actor_name=source_actor_name,
        source_action_summary=source_action_summary,
        source_speech_text=source_speech_text,
        current_target=player_target,
        attack_assessment=attack_assessment,
        threatened_targets=threatened_targets,
        revealed_target_names=revealed_target_names,
        metadata=metadata,
    )


def resolve_attack_prompt_submission(
    save: SaveFile,
    *,
    session_id: str,
    prompt: PublicTurnAttackPrompt,
    target_action_summary: str,
    target_speech_text: str,
    target_response_kind: str,
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[
    list[SceneEvent],
    PublicTurnImpact | None,
    PublicTurnSettlementEntry | None,
    ActionCheckResponse | None,
    PublicTurnAttackDefensePrompt | None,
]:
    metadata = dict(prompt.metadata or {})
    attack_assessment = dict(metadata.get("attack_assessment") or {})
    threatened_targets = _attack_targets_from_metadata(
        save,
        actor_ids=list(metadata.get("threatened_target_actor_ids") or []),
        actor_names=list(prompt.threatened_target_names or []),
    )
    hit_targets = _attack_targets_from_metadata(save, actor_ids=list(metadata.get("auto_hit_actor_ids") or []))
    avoided_targets = _attack_targets_from_metadata(save, actor_ids=list(metadata.get("auto_avoided_actor_ids") or []))
    player_action_status = save.player_static_data.dnd5e_sheet.role_action_status
    speech_only_response = (
        prompt.current_target_actor_id == save.player_static_data.player_id
        and _is_speech_only_role_action_status(player_action_status)
    )
    if speech_only_response and str(target_action_summary or "").strip():
        raise ValueError("PUBLIC_TURN_SPEECH_ONLY")
    response_action_summary = "" if speech_only_response else target_action_summary
    response_classification = (
        {
            "world_impact_type": "non_world",
            "effective_against_attack": False,
            "defense_ability_used": "dexterity",
        }
        if speech_only_response
        else classify_attack_response(
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            target_actor_name=prompt.current_target_name,
            response_action_text=target_action_summary,
            response_speech_text=target_speech_text,
            response_kind=target_response_kind,
            config=config,
        )
    )
    consume_submission_resources_in_save(
        save,
        actor_role_id=prompt.current_target_actor_id,
        action_text=target_action_summary,
        speech_text=target_speech_text,
        entry_point="public_turn_attack_response",
        config=config,
    )
    base_events = [
        world._new_scene_event(
            "public_turn_actor_action",
            "\n".join(part for part in (prompt.source_action_summary, prompt.source_speech_text) if part.strip()).strip()
            or prompt.source_action_summary,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            metadata={
                "actor_type": str(metadata.get("source_actor_type") or "npc"),
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
            },
        )
    ]
    current_target = next(
        (item for item in threatened_targets if item.actor_id == prompt.current_target_actor_id),
        PublicTurnResolvedAttackTarget(
            actor_id=prompt.current_target_actor_id,
            actor_name=prompt.current_target_name,
            actor_type=prompt.current_target_kind,
        ),
    )
    if str(response_classification.get("world_impact_type") or "non_world") == "world" and bool(
        response_classification.get("effective_against_attack")
    ):
        defense_prompt = PublicTurnAttackDefensePrompt(
            check_id=f"{round_state.round_id}_{prompt.source_actor_id}_attack_defense",
            round_id=round_state.round_id,
            phase=round_state.phase,
            attack_kind=prompt.attack_kind,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            source_attack_ability_used=(prompt.attack_ability_used or "strength"),
            source_attack_ability_modifier=attack_ability_modifier(
                save,
                prompt.source_actor_id,
                str(prompt.attack_ability_used or "strength"),
            ),
            target_actor_id=current_target.actor_id,
            target_actor_name=current_target.actor_name,
            target_action_summary=response_action_summary,
            target_speech_text=target_speech_text,
            target_defense_ability_used=str(response_classification.get("defense_ability_used") or "dexterity"),  # type: ignore[arg-type]
            target_defense_ability_modifier=attack_ability_modifier(
                save,
                current_target.actor_id,
                str(response_classification.get("defense_ability_used") or "dexterity"),
            ),
            threatened_target_names=[item.actor_name for item in threatened_targets],
            hit_target_names=[item.actor_name for item in hit_targets],
            aoe_remaining_target_count=max(0, len(threatened_targets) - len(hit_targets) - len(avoided_targets) - 1),
            stakes_summary=prompt.source_action_summary or prompt.source_speech_text,
            metadata={
                **metadata,
                "player_response_action": response_action_summary,
                "player_response_speech": target_speech_text,
            },
        )
        return base_events, None, None, None, defense_prompt
    hit_targets.append(current_target)
    events, impact, settlement = _build_attack_resolution_bundle(
        save=save,
        session_id=session_id,
        round_state=round_state,
        actor_id=prompt.source_actor_id,
        actor_name=prompt.source_actor_name,
        actor_type=str(metadata.get("source_actor_type") or "npc"),
        action_summary=prompt.source_action_summary,
        speech_text=prompt.source_speech_text,
        action_result=None,
        attack_assessment=attack_assessment,
        threatened_targets=threatened_targets,
        hit_targets=hit_targets,
        avoided_targets=avoided_targets,
        revealed_target_names=list(metadata.get("revealed_target_names") or prompt.revealed_target_names or []),
        defense_action_text=response_action_summary,
        defense_speech_text=target_speech_text,
        base_events=base_events,
        config=config,
    )
    return events, impact, settlement, None, None


def resolve_attack_defense_prompt_submission(
    save: SaveFile,
    *,
    session_id: str,
    prompt: PublicTurnAttackDefensePrompt,
    forced_dice_roll: int,
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry, ActionCheckResponse]:
    metadata = dict(prompt.metadata or {})
    consume_submission_resources_in_save(
        save,
        actor_role_id=prompt.target_actor_id,
        action_text=prompt.target_action_summary,
        speech_text=prompt.target_speech_text,
        entry_point="public_turn_attack_response",
        config=config,
    )
    attack_assessment = dict(metadata.get("attack_assessment") or {})
    threatened_targets = _attack_targets_from_metadata(
        save,
        actor_ids=list(metadata.get("threatened_target_actor_ids") or []),
        actor_names=list(prompt.threatened_target_names or []),
    )
    hit_targets = _attack_targets_from_metadata(save, actor_ids=list(metadata.get("auto_hit_actor_ids") or []))
    avoided_targets = _attack_targets_from_metadata(save, actor_ids=list(metadata.get("auto_avoided_actor_ids") or []))
    current_target = next(
        (item for item in threatened_targets if item.actor_id == prompt.target_actor_id),
        PublicTurnResolvedAttackTarget(
            actor_id=prompt.target_actor_id,
            actor_name=prompt.target_actor_name,
            actor_type=PublicTurnActorType.PLAYER if prompt.target_actor_id == save.player_static_data.player_id else PublicTurnActorType.NPC,
        ),
    )
    action_result = _run_attack_contest_check(
        save,
        session_id=session_id,
        source_actor_id=prompt.source_actor_id,
        source_actor_name=prompt.source_actor_name,
        source_action_summary=prompt.source_action_summary,
        source_speech_text=prompt.source_speech_text,
        target_actor_id=prompt.target_actor_id,
        target_actor_name=prompt.target_actor_name,
        target_action_summary=prompt.target_action_summary,
        target_speech_text=prompt.target_speech_text,
        attack_ability_used=prompt.source_attack_ability_used,
        defense_ability_used=prompt.target_defense_ability_used,
        forced_target_dice_roll=forced_dice_roll,
        config=config,
    )
    if action_result.success:
        hit_targets.append(current_target)
    else:
        avoided_targets.append(current_target)
    base_events = [
        world._new_scene_event(
            "public_turn_actor_action",
            "\n".join(part for part in (prompt.source_action_summary, prompt.source_speech_text) if part.strip()).strip()
            or prompt.source_action_summary,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            metadata={
                "actor_type": str(metadata.get("source_actor_type") or "npc"),
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
            },
        )
    ]
    events, impact, settlement = _build_attack_resolution_bundle(
        save=save,
        session_id=session_id,
        round_state=round_state,
        actor_id=prompt.source_actor_id,
        actor_name=prompt.source_actor_name,
        actor_type=str(metadata.get("source_actor_type") or "npc"),
        action_summary=prompt.source_action_summary,
        speech_text=prompt.source_speech_text,
        action_result=action_result,
        attack_assessment=attack_assessment,
        threatened_targets=threatened_targets,
        hit_targets=hit_targets,
        avoided_targets=avoided_targets,
        revealed_target_names=list(metadata.get("revealed_target_names") or []),
        defense_action_text=prompt.target_action_summary,
        defense_speech_text=prompt.target_speech_text,
        base_events=base_events,
        config=config,
    )
    return events, impact, settlement, action_result


def resolve_interaction_prompt_submission(
    save: SaveFile,
    *,
    session_id: str,
    prompt: PublicTurnInteractionPrompt,
    target_action_summary: str,
    target_speech_text: str,
    target_response_kind: str,
    round_state: PublicTurnRound,
    config: ChatConfig | None,
) -> tuple[
    list[SceneEvent],
    PublicTurnImpact | None,
    PublicTurnSettlementEntry | None,
    ActionCheckResponse | None,
    PublicTurnOpposedPrompt | None,
]:
    if not validate_prompt_target_alignment(
        prompt_target_actor_id=prompt.target_actor_id,
        prompt_target_actor_name=prompt.target_actor_name,
        source_action_target_name=prompt.source_action_target_name,
        source_speech_target_name=prompt.source_speech_target_name,
        expected_player_id=save.player_static_data.player_id,
    ):
        raise ValueError("PUBLIC_TURN_INTERACTION_TARGET_MISMATCH")
    action_target_actor_id, action_target_name, action_target_kind = _prompt_action_target_details(
        prompt_target_actor_id=prompt.target_actor_id,
        prompt_target_actor_name=prompt.target_actor_name,
        prompt_target_actor_kind=prompt.target_actor_kind,
        source_action_target_name=prompt.source_action_target_name,
    )
    actor_type = "npc"
    if any(item.role_id == prompt.source_actor_id for item in getattr(save.team_state, "members", [])):
        actor_type = "team"
    elif world._find_active_encounter_temp_npc(save, prompt.source_actor_id) is not None:
        actor_type = "encounter_temp_npc"
    source_role = next((item for item in save.role_pool if item.role_id == prompt.source_actor_id), None)
    actor = {
        "actor_id": prompt.source_actor_id,
        "name": prompt.source_actor_name,
        "actor_type": actor_type,
        "role": source_role,
    }
    speech_only_response = (
        prompt.target_actor_id == save.player_static_data.player_id
        and _is_speech_only_role_action_status(save.player_static_data.dnd5e_sheet.role_action_status)
    )
    if speech_only_response and str(target_action_summary or "").strip():
        raise ValueError("PUBLIC_TURN_SPEECH_ONLY")
    response = (
        InteractionResponseClassification(
            action_text="",
            speech_text=target_speech_text,
            speech_target_label=None,
            target_label=None,
            world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
            consent_state="accepted",
            contest_state="non_opposed",
        )
        if speech_only_response
        else classify_player_interaction_response(
            save,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_world_impact_type=prompt.source_world_impact_type,
            action_text=target_action_summary,
            speech_text=target_speech_text,
            response_kind=target_response_kind,
            config=config,
        )
    )
    target_action_summary = response.action_text
    target_speech_text = response.speech_text
    response_target = resolve_interaction_target(
        save,
        actor_role_id=prompt.target_actor_id,
        action_prompt=f"actor={prompt.target_actor_name}; intent={target_action_summary}; speech={target_speech_text}",
        target_label=response.target_label,
    )
    if (
        response.world_impact_type == PublicTurnWorldImpactType.WORLD
        and response_target is not None
        and response_target.actor_id != prompt.source_actor_id
    ):
        raise ValueError("PUBLIC_TURN_ALTERNATION_TARGET_MISMATCH")
    consume_submission_resources_in_save(
        save,
        actor_role_id=prompt.target_actor_id,
        action_text=target_action_summary,
        speech_text=target_speech_text,
        entry_point="public_turn_interaction_response",
        config=config,
    )
    action_content = "\n".join(
        part for part in (prompt.source_action_summary.strip(), prompt.source_speech_text.strip()) if part
    ).strip() or prompt.source_action_summary.strip() or prompt.source_action_prompt.strip() or prompt.source_actor_name
    base_events = [
        world._new_scene_event(
            "public_turn_actor_action",
            action_content,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            metadata={
                "actor_type": actor_type,
                "round_id": round_state.round_id,
                "phase": round_state.phase.value,
                "target_label": prompt.source_action_target_name or "",
                "speech_target_label": prompt.source_speech_target_name or "",
                "specific_threat": prompt.source_action_summary,
            },
        )
    ]
    if (
        prompt.source_world_impact_type == PublicTurnWorldImpactType.NON_WORLD
        and response.world_impact_type == PublicTurnWorldImpactType.WORLD
        and response_target is not None
        and response_target.actor_id == prompt.source_actor_id
    ):
        source_target = ResolvedInteractionTarget(
            actor_id=prompt.source_actor_id,
            name=prompt.source_actor_name,
            actor_kind="npc",
            actor_type=public_turn_actor_type(actor_type),
            role=source_role,
        )
        source_response = build_ai_interaction_response(
            save,
            target=source_target,
            source_actor_id=prompt.target_actor_id,
            source_actor_name=prompt.target_actor_name,
            source_world_impact_type=response.world_impact_type,
            source_action_summary=target_action_summary,
            source_speech_text=target_speech_text,
            gm_summary=prompt.source_action_summary or prompt.source_actor_name,
            config=config,
        )
        contest_state = source_response.contest_state
        if is_direct_world_counter_response(
            source_world_impact_type=response.world_impact_type,
            response_world_impact_type=source_response.world_impact_type,
            source_actor_id=prompt.target_actor_id,
            source_actor_name=prompt.target_actor_name,
            response_target_actor_id=source_response.action_target_actor_id,
            response_target_name=source_response.action_target_name,
        ):
            contest_state = "opposed"
        if contest_state == "opposed":
            opposed_prompt = PublicTurnOpposedPrompt(
                check_id=f"{round_state.round_id}_{prompt.source_actor_id}_opposed",
                round_id=round_state.round_id,
                phase=round_state.phase,
                source_actor_id=prompt.source_actor_id,
                source_actor_name=prompt.source_actor_name,
                source_action_summary=source_response.action_summary or prompt.source_action_summary,
                source_speech_text=source_response.speech_text,
                source_interaction_kind=prompt.source_interaction_kind,
                source_action_target_name=source_response.action_target_name or prompt.target_actor_name,
                source_speech_target_name=source_response.speech_target_name,
                source_situation_delta_hint=prompt.source_situation_delta_hint,
                source_reputation_delta_hint=prompt.source_reputation_delta_hint,
                target_actor_id=prompt.target_actor_id,
                target_actor_name=prompt.target_actor_name,
                stakes_summary=prompt.source_action_summary or prompt.source_action_prompt,
                followup_notice_state=("noticed" if prompt.source_interaction_kind == "information_gathering" else None),
                followup_ability_used=prompt.source_planned_ability_used,
                followup_dc=prompt.source_planned_dc,
                followup_check_task=prompt.source_planned_check_task,
            )
            return base_events, None, None, None, opposed_prompt

        reverse_check = PublicTurnPlayerActionCheck(
            action_type="check",
            source_context="public_turn",
            resolution_rule="static_dc",
            planned_requires_check=True,
            planned_ability_used="strength",
            planned_dc=max(10, int(prompt.source_planned_dc or 10)),
            planned_time_spent_min=1,
            planned_check_task=target_action_summary or "Push back against the current public-turn pressure.",
            target_role_id=prompt.source_actor_id,
            target_name=prompt.source_actor_name,
            target_actor_kind="npc",
        )
        events, impact, settlement, action_result = resolve_player_submission(
            save,
            session_id=session_id,
            action_text=target_action_summary,
            speech_text=target_speech_text,
            round_state=round_state,
            action_check=reverse_check,
            config=config,
        )
        settlement.action_target_actor_id = prompt.source_actor_id
        settlement.action_target_name = prompt.source_actor_name
        settlement.action_target_kind = public_turn_actor_type(actor_type)
        settlement.source_world_impact_type = PublicTurnWorldImpactType.WORLD
        settlement.target_response_world_impact_type = source_response.world_impact_type
        settlement.interaction_exchange_kind = "alternated_exchange"
        settlement.alternation_depth = 1
        settlement.target_response_kind = target_response_kind  # type: ignore[assignment]
        settlement.interaction_target_name = prompt.source_actor_name
        settlement.interaction_resolution = (
            "accepted"
            if source_response.consent_state == "accepted"
            else "ambiguous_non_opposed"
        )
        settlement.opposed_target_name = prompt.source_actor_name
        settlement.opposed_target_action = source_response.action_summary or None
        settlement.opposed_target_speech = source_response.speech_text or None
        settlement.opposed_target_speech_target_name = source_response.speech_target_name
        return events, impact, settlement, action_result, None

    contest_state = response.contest_state
    if is_direct_world_counter_response(
        source_world_impact_type=prompt.source_world_impact_type,
        response_world_impact_type=response.world_impact_type,
        source_actor_id=prompt.source_actor_id,
        source_actor_name=prompt.source_actor_name,
        response_target_actor_id=(response_target.actor_id if response_target is not None else None),
        response_target_name=(response_target.name if response_target is not None else response.target_label),
    ):
        contest_state = "opposed"
    if contest_state == "opposed":
        opposed_prompt = PublicTurnOpposedPrompt(
            check_id=f"{round_state.round_id}_{prompt.source_actor_id}_opposed",
            round_id=round_state.round_id,
            phase=round_state.phase,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            source_interaction_kind=prompt.source_interaction_kind,
            source_action_target_name=prompt.source_action_target_name,
            source_speech_target_name=prompt.source_speech_target_name,
            source_situation_delta_hint=prompt.source_situation_delta_hint,
            source_reputation_delta_hint=prompt.source_reputation_delta_hint,
            target_actor_id=prompt.target_actor_id,
            target_actor_name=prompt.target_actor_name,
            stakes_summary=prompt.source_action_summary or prompt.source_action_prompt,
            followup_notice_state=("noticed" if prompt.source_interaction_kind == "information_gathering" else None),
            followup_ability_used=prompt.source_planned_ability_used,
            followup_dc=prompt.source_planned_dc,
            followup_check_task=prompt.source_planned_check_task,
        )
        return base_events, None, None, None, opposed_prompt

    action_result = None
    # `no_action` is a passive response, but the source actor still needs to
    # resolve its own check so we can emit the DC/result narration and
    # downstream consequences. Keep explicit responses on the existing path.
    should_run_source_check = prompt.source_planned_requires_check or target_response_kind == "no_action"
    if should_run_source_check:
        combined_prompt = "\n".join(
            part
            for part in (
                prompt.source_action_prompt.strip(),
                prompt.source_action_summary.strip(),
                prompt.source_speech_text.strip(),
                target_action_summary.strip(),
                target_speech_text.strip(),
            )
            if part
            ).strip() or prompt.source_action_prompt.strip() or prompt.source_action_summary.strip()
        action_result = world.action_check(
            ActionCheckRequest(
                session_id=session_id,
                actor_role_id=prompt.source_actor_id,
                action_type=prompt.source_action_type,
                action_prompt=combined_prompt,
                source_context="public_turn",
                resolution_rule="static_dc",
                target_role_id=None,
                target_name=action_target_name,
                target_actor_kind=("player" if action_target_actor_id == save.player_static_data.player_id else None),
                forced_target_dice_roll=None,
                allow_backend_roll=True,
                resolution_context="embedded",
                planned_ability_used=prompt.source_planned_ability_used or "wisdom",
                planned_dc=prompt.source_planned_dc or 10,
                planned_time_spent_min=1,
                planned_requires_check=True,
                planned_check_task=prompt.source_planned_check_task or prompt.source_action_prompt or prompt.source_action_summary,
                config=config,
            )
        )
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = getattr(zone_metric, "reputation_score", 50)
    payload = {
        "action_narration": prompt.source_action_summary,
        "visible_intent": prompt.source_action_summary,
        "speech_line": prompt.source_speech_text,
        "speech_summary": prompt.source_speech_text,
        "action_type": prompt.source_action_type,
        "action_prompt": prompt.source_action_prompt,
        "specific_threat": prompt.source_action_summary,
        "world_impact_type": prompt.source_world_impact_type.value,
        "situation_delta_hint": prompt.source_situation_delta_hint,
        "reputation_delta_hint": prompt.source_reputation_delta_hint,
    }
    interaction_resolution = "accepted" if response.consent_state == "accepted" else "ambiguous_non_opposed"
    events, impact, settlement, _ = _finalize_ai_actor_turn(
        save,
        session_id=session_id,
        actor=actor,
        payload=payload,
        round_state=round_state,
        action_content=action_content,
        action_result=action_result,
        reputation_score=reputation_score,
        config=config,
        base_events=base_events,
        action_target_actor_id=action_target_actor_id,
        action_target_name=action_target_name,
        action_target_kind=action_target_kind,
        speech_target_name=prompt.source_speech_target_name,
        source_world_impact_type=prompt.source_world_impact_type,
        target_response_world_impact_type=response.world_impact_type,
        interaction_exchange_kind=(
            "non_world_exchange"
            if prompt.source_world_impact_type == PublicTurnWorldImpactType.NON_WORLD
            and response.world_impact_type == PublicTurnWorldImpactType.NON_WORLD
            else "world_exchange"
        ),
        alternation_depth=prompt.alternation_depth,
        target_response_kind=target_response_kind,
        interaction_target_name=prompt.target_actor_name,
        interaction_resolution=interaction_resolution,
        opposed_target_name=prompt.target_actor_name,
        opposed_target_action=target_action_summary,
        opposed_target_speech=target_speech_text,
    )
    return events, impact, settlement, action_result, None


def resolve_situation(
    save: SaveFile,
    *,
    session_id: str,
    round_state: PublicTurnRound,
    impacts: list[PublicTurnImpact],
) -> tuple[str, list[SceneEvent], EnvironmentRiskLevel]:
    total_environment_shift = sum(int(item.environment_shift or 0) for item in impacts)
    total_situation_delta = sum(int(item.situation_delta or 0) for item in impacts)
    total_reputation_delta = sum(int(item.zone_reputation_delta or 0) for item in impacts)
    destructive_failure = total_environment_shift > 0 and total_situation_delta < 0
    risk = next_environment_risk(
        round_state.environment_risk_level,
        total_environment_shift=total_environment_shift,
        destructive_failure=destructive_failure,
    )
    narration = (
        f"Public turn situation total {total_situation_delta:+d}; environment risk now {risk.value}."
        if impacts
        else "Public turn situation remains unchanged."
    )
    events = [
        world._new_scene_event(
            "public_turn_situation",
            narration,
            actor_name="GM",
            metadata={
                "round_id": round_state.round_id,
                "situation_delta_total": total_situation_delta,
                "environment_risk_level": risk.value,
            },
        )
    ]
    active_encounter = public_scene_legacy._active_encounter_for_current_sub_zone(save)
    if active_encounter is not None and total_situation_delta:
        events.extend(
            apply_active_encounter_situation_delta_in_save(
                save,
                session_id=session_id,
                delta=total_situation_delta,
                summary=narration,
                actor_name="System",
            )
        )
    _, reputation_event = apply_round_reputation(
        save,
        session_id=session_id,
        delta=total_reputation_delta,
        reason="public turn round resolution",
        actor_name="System",
    )
    if reputation_event is not None:
        events.append(reputation_event)
    if risk != round_state.environment_risk_level or total_environment_shift:
        events.append(
            world._new_scene_event(
                "public_turn_environment_update",
                f"Environment risk {round_state.environment_risk_level.value} -> {risk.value}",
                actor_name="GM",
                metadata={
                    "round_id": round_state.round_id,
                    "environment_shift": total_environment_shift,
                    "environment_risk_level_before": round_state.environment_risk_level.value,
                    "environment_risk_level_after": risk.value,
                },
            )
        )
    return narration, events, risk
