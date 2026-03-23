from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ChatConfig,
    PlayerReactionCheck,
    PublicTurnInteractionPrompt,
    PublicTurnNarrationFragmentBatch,
    PublicTurnNarrationInputItem,
    PublicTurnOpposedPrompt,
    PublicTurnPhase,
    PublicTurnRound,
    PublicTurnSegmentActorDirective,
    PublicTurnSegmentBoundary,
    PublicTurnSegmentPlan,
    PublicTurnSettlementEntry,
    PublicTurnWorldImpactType,
    PublicTurnImpact,
    SaveFile,
    SceneEvent,
)
from app.services.ai_protocol_contract_service import (
    AI_PROVIDER_CALL_FAILED,
    EnumContractField,
    render_enum_pool_text,
    require_ai_config,
    validate_or_repair_json_payload,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world
from app.services.public_turn_interaction_service import (
    build_ai_interaction_response,
    derive_interaction_kind,
    infer_interaction_kind,
    infer_world_impact_type,
    is_direct_world_counter_response,
    public_turn_actor_type,
    resolve_interaction_target,
    resolve_speech_target,
    resolve_target_ability,
    should_require_interaction_response,
    should_use_speech_target_as_interaction_target,
)
from app.services.public_turn_narration_formatter import build_settlement_fragment
from app.services.public_turn_resolution import (
    _build_reaction_for_actor,
    _finalize_ai_actor_turn,
    normalize_public_turn_ai_payload,
    settlement_actor_type,
)
from app.services.teammate_memory_service import build_private_chat_memory_context


@dataclass
class PublicTurnResolvedBeat:
    scene_events: list[SceneEvent]
    settlement: PublicTurnSettlementEntry | None
    impact: PublicTurnImpact | None
    narration_input: PublicTurnNarrationInputItem | None


@dataclass
class PublicTurnResolvedSegment:
    plan: PublicTurnSegmentPlan
    beats: list[PublicTurnResolvedBeat]
    pending_reaction: PlayerReactionCheck | None = None
    public_interaction_prompt: PublicTurnInteractionPrompt | None = None
    public_opposed_prompt: PublicTurnOpposedPrompt | None = None


def _normalize_action_type(value: str) -> str:
    action_type = str(value or "check").strip().lower()
    if action_type in {"attack", "item_use", "check"}:
        return action_type
    return "check"


def _clean_line(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _player_targeted(text: str, player_name: str) -> bool:
    combined = str(text or "").strip()
    if not combined:
        return False
    markers = [player_name, "玩家", "你", "你们"]
    return any(marker and marker in combined for marker in markers)


def _directive_boundary_from_pause(
    phase: PublicTurnPhase,
    directive: PublicTurnSegmentActorDirective,
) -> PublicTurnSegmentBoundary | None:
    if directive.pause_kind == "player_interaction":
        return PublicTurnSegmentBoundary(
            boundary_kind="player_interaction",
            phase=phase,
            pause_source_actor_id=directive.actor_id,
            pause_source_actor_name=directive.actor_name,
        )
    if directive.pause_kind == "player_reaction":
        return PublicTurnSegmentBoundary(
            boundary_kind="player_reaction",
            phase=phase,
            pause_source_actor_id=directive.actor_id,
            pause_source_actor_name=directive.actor_name,
        )
    if directive.pause_kind == "player_opposed":
        return PublicTurnSegmentBoundary(
            boundary_kind="player_opposed",
            phase=phase,
            pause_source_actor_id=directive.actor_id,
            pause_source_actor_name=directive.actor_name,
        )
    return None


def _directive_payload(
    directive: PublicTurnSegmentActorDirective,
) -> dict[str, object]:
    return {
        "action_narration": directive.action_summary,
        "visible_intent": directive.action_summary,
        "speech_line": directive.speech_text,
        "speech_summary": directive.speech_text,
        "specific_threat": directive.specific_threat,
        "target_label": directive.action_target_name or directive.target_name or "",
        "speech_target_label": directive.speech_target_name or directive.speech_target_label or "",
        "world_impact_type": directive.world_impact_type.value,
        "action_type": directive.action_type,
        "action_prompt": directive.action_prompt,
        "situation_delta_hint": directive.situation_delta_hint,
        "reputation_delta_hint": directive.reputation_delta_hint,
    }


def _base_static_plan(
    save: SaveFile,
    *,
    actor: dict[str, object],
    action_type: str,
    action_prompt: str,
    payload: dict[str, object],
) -> tuple[bool, str, int, str]:
    plan = world._fallback_action_plan(action_type, action_prompt)
    planned_requires_check = bool(
        plan.get("requires_check") or public_scene_runtime.should_force_public_action_check(save, actor, payload)
    )
    planned_ability_used = str(plan.get("ability_used") or "wisdom")
    planned_dc = int(plan.get("dc") or 10)
    planned_check_task = str(plan.get("check_task") or action_prompt)
    return planned_requires_check, planned_ability_used, planned_dc, planned_check_task


def _planned_directive_values(
    save: SaveFile,
    *,
    actor: dict[str, object],
    actor_id: str,
    actor_name: str,
    action_type: str,
    action_summary: str,
    speech_text: str,
    specific_threat: str,
    action_prompt: str,
    target_label: str | None,
    gm_summary: str,
    payload: dict[str, object],
    override: dict[str, object] | None = None,
    config: ChatConfig | None = None,
) -> dict[str, object]:
    planned_requires_check, planned_ability_used, planned_dc, planned_check_task = _base_static_plan(
        save,
        actor=actor,
        action_type=action_type,
        action_prompt=action_prompt,
        payload=payload,
    )
    world_impact_type = PublicTurnWorldImpactType(str(payload.get("world_impact_type") or PublicTurnWorldImpactType.NON_WORLD.value))
    action_target = resolve_interaction_target(
        save,
        actor_role_id=actor_id,
        action_prompt=action_prompt,
        target_label=target_label,
    )
    speech_target = resolve_speech_target(
        save,
        actor_role_id=actor_id,
        action_prompt=action_prompt,
        speech_target_label=str(payload.get("speech_target_label") or ""),
        fallback_target=action_target,
    )
    interaction_target = action_target
    if should_use_speech_target_as_interaction_target(
        action_type=action_type,
        world_impact_type=world_impact_type,
        speech_text=speech_text,
        action_target=action_target,
        speech_target=speech_target,
    ):
        interaction_target = speech_target
    target_actor_id = action_target.actor_id if action_target is not None else None
    target_name = action_target.name if action_target is not None else (str(target_label or "").strip() or None)
    target_actor_kind = action_target.actor_kind if action_target is not None else None
    action_target_actor_id = target_actor_id
    action_target_name = target_name
    action_target_kind = action_target.actor_type if action_target is not None else None
    speech_target_label = str(payload.get("speech_target_label") or "").strip() or None
    speech_target_actor_id = speech_target.actor_id if speech_target is not None else None
    speech_target_name = speech_target.name if speech_target is not None else speech_target_label
    speech_target_kind = speech_target.actor_type if speech_target is not None else None
    target_ability_used = None
    target_ability_modifier = None
    interaction_target_actor_id = interaction_target.actor_id if interaction_target is not None else None
    interaction_target_name = interaction_target.name if interaction_target is not None else None
    interaction_target_kind = interaction_target.actor_type if interaction_target is not None else None
    interaction_kind = ""
    interaction_requires_response = False
    target_response_action_summary = ""
    target_response_speech_text = ""
    target_response_speech_target_name = None
    target_response_world_impact_type = PublicTurnWorldImpactType.NON_WORLD.value
    interaction_exchange_kind = "world_exchange"
    alternation_depth = 0
    consent_state = "not_applicable"
    contest_state = "not_applicable"
    resolution_mode = "none"
    resolution_rule = "static_dc"
    pause_kind = str((override or {}).get("pause_kind") or "").strip().lower()
    if pause_kind not in {"none", "player_interaction", "player_reaction", "player_opposed"}:
        pause_kind = "none"

    if should_require_interaction_response(
        action_type=action_type,
        world_impact_type=world_impact_type,
        action_target=action_target,
        speech_target=speech_target,
    ):
        interaction_requires_response = True
        interaction_kind = derive_interaction_kind(
            action_type=action_type,
            world_impact_type=world_impact_type,
            action_target=action_target,
            speech_target=speech_target,
        )
        rule = ("strength", "max_strength_or_dexterity")
        if interaction_target is not None and interaction_target.actor_kind == "player":
            pause_kind = "player_interaction"
            resolution_mode = "none"
        elif interaction_target is not None:
            response = build_ai_interaction_response(
                save,
                target=interaction_target,
                source_actor_id=actor_id,
                source_actor_name=actor_name,
                source_world_impact_type=world_impact_type,
                source_action_summary=action_summary,
                source_speech_text=speech_text,
                gm_summary=gm_summary,
                config=config,
            )
            target_response_action_summary = response.action_summary
            target_response_speech_text = response.speech_text
            target_response_speech_target_name = response.speech_target_name
            target_response_world_impact_type = response.world_impact_type.value
            consent_state = response.consent_state
            if (
                world_impact_type == PublicTurnWorldImpactType.NON_WORLD
                and response.world_impact_type == PublicTurnWorldImpactType.WORLD
                and response.action_target_actor_id == actor_id
            ):
                interaction_exchange_kind = "alternated_exchange"
                alternation_depth = 1
                resolution_rule = "opposed_actor"
                resolution_mode = "opposed_actor"
                planned_requires_check = True
                planned_ability_used = str(rule[0])
                target_ability_used, target_ability_modifier = resolve_target_ability(save, interaction_target)
                planned_dc = max(5, min(30, 10 + int(target_ability_modifier or 0)))
                planned_check_task = str((override or {}).get("planned_check_task") or action_prompt)
            else:
                interaction_exchange_kind = (
                    "non_world_exchange"
                    if world_impact_type == PublicTurnWorldImpactType.NON_WORLD and response.world_impact_type == PublicTurnWorldImpactType.NON_WORLD
                    else "world_exchange"
                )
                if is_direct_world_counter_response(
                    source_world_impact_type=world_impact_type,
                    response_world_impact_type=response.world_impact_type,
                    source_actor_id=actor_id,
                    source_actor_name=actor_name,
                    response_target_actor_id=response.action_target_actor_id,
                    response_target_name=response.action_target_name,
                ):
                    contest_state = "opposed"
                else:
                    contest_state = response.contest_state
                if contest_state == "opposed":
                    resolution_rule = "opposed_actor"
                    resolution_mode = "opposed_actor"
                    planned_requires_check = True
                    planned_ability_used = str(rule[0])
                    target_ability_used, target_ability_modifier = resolve_target_ability(save, interaction_target)
                    planned_dc = max(5, min(30, 10 + int(target_ability_modifier or 0)))
                    planned_check_task = str((override or {}).get("planned_check_task") or action_prompt)
                else:
                    resolution_rule = "static_dc"
                    consent_state = "ambiguous" if consent_state == "not_applicable" else consent_state
                    contest_state = "non_opposed" if contest_state == "not_applicable" else contest_state
                    resolution_mode = "static_dc" if planned_requires_check else "none"
        else:
            interaction_exchange_kind = (
                "non_world_exchange" if world_impact_type == PublicTurnWorldImpactType.NON_WORLD else "world_exchange"
            )
            resolution_mode = "static_dc" if planned_requires_check else "none"
    else:
        interaction_exchange_kind = (
            "non_world_exchange" if world_impact_type == PublicTurnWorldImpactType.NON_WORLD else "world_exchange"
        )
        resolution_mode = "static_dc" if planned_requires_check else "none"

    if interaction_target is None and pause_kind in {"player_interaction", "player_opposed"}:
        pause_kind = "none"
    if interaction_target is None and pause_kind == "player_reaction":
        pause_kind = "none"
    if interaction_target is not None and interaction_target.actor_kind != "player" and pause_kind in {"player_interaction", "player_opposed"}:
        pause_kind = "none"
    if interaction_target is not None and interaction_target.actor_kind == "player" and interaction_requires_response:
        pause_kind = "player_interaction"
        resolution_mode = "none"
        interaction_exchange_kind = (
            "non_world_exchange" if world_impact_type == PublicTurnWorldImpactType.NON_WORLD else "world_exchange"
        )

    return {
        "target_actor_id": target_actor_id,
        "target_name": target_name,
        "target_actor_kind": target_actor_kind,
        "action_target_actor_id": action_target_actor_id,
        "action_target_name": action_target_name,
        "action_target_kind": action_target_kind,
        "speech_target_actor_id": speech_target_actor_id,
        "speech_target_name": speech_target_name,
        "speech_target_kind": speech_target_kind,
        "interaction_target_actor_id": interaction_target_actor_id,
        "interaction_target_name": interaction_target_name,
        "interaction_target_kind": interaction_target_kind,
        "interaction_kind": interaction_kind,
        "interaction_requires_response": interaction_requires_response,
        "target_response_action_summary": target_response_action_summary,
        "target_response_speech_text": target_response_speech_text,
        "target_response_speech_target_name": target_response_speech_target_name,
        "target_response_world_impact_type": target_response_world_impact_type,
        "interaction_exchange_kind": interaction_exchange_kind,
        "world_impact_type": world_impact_type.value,
        "alternation_depth": alternation_depth,
        "consent_state": consent_state,
        "contest_state": contest_state,
        "resolution_mode": resolution_mode,
        "resolution_rule": resolution_rule,
        "planned_requires_check": planned_requires_check,
        "planned_ability_used": planned_ability_used,
        "planned_dc": planned_dc,
        "planned_check_task": planned_check_task,
        "target_ability_used": target_ability_used,
        "target_ability_modifier": target_ability_modifier,
        "pause_kind": pause_kind,
    }


def _fallback_directive(
    save: SaveFile,
    *,
    actor: dict[str, object],
    phase: PublicTurnPhase,
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None,
    audience_context: dict[str, object],
    config: ChatConfig | None,
) -> PublicTurnSegmentActorDirective:
    actor_id = str(actor.get("actor_id") or "")
    actor_name = str(actor.get("name") or "")
    payload = public_scene_runtime._ai_actor_action(
        save,
        actor,
        player_text=player_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        incoming_interaction=None,
        allow_partial=True,
        config=config,
    )
    normalized = normalize_public_turn_ai_payload(
        payload,
        actor_name=actor_name,
        audience_may_speak=public_scene_runtime.actor_may_speak_in_public_turn(actor, audience_context),
    )
    action_summary = _clean_line(
        str(normalized.get("external_action_narration") or normalized.get("visible_intent") or "")
    )[:200]
    speech_text = _clean_line(str(normalized.get("speech_line") or normalized.get("speech_summary") or ""))[:200]
    specific_threat = _clean_line(str(normalized.get("specific_threat") or ""))[:200]
    action_type = _normalize_action_type(str(normalized.get("action_type") or "check"))
    target_label = _clean_line(str(normalized.get("target_label") or ""))[:80]
    speech_target_label = _clean_line(str(normalized.get("speech_target_label") or ""))[:80]
    action_prompt = _clean_line(
        str(normalized.get("action_prompt") or "") or f"actor={actor_name}; intent={action_summary}; threat={specific_threat}"
    )[:240]
    planned = _planned_directive_values(
        save,
        actor=actor,
        actor_id=actor_id,
        actor_name=actor_name,
        action_type=action_type,
        action_summary=action_summary,
        speech_text=speech_text,
        specific_threat=specific_threat,
        action_prompt=action_prompt,
        target_label=target_label,
        gm_summary=gm_summary,
        payload=normalized,
        config=config,
    )
    return PublicTurnSegmentActorDirective(
        actor_id=actor_id,
        actor_name=actor_name,
        actor_type=settlement_actor_type(str(actor.get("actor_type") or "npc")),
        phase=phase,
        action_type=action_type,  # type: ignore[arg-type]
        action_summary=action_summary,
        speech_text=speech_text,
        action_prompt=action_prompt,
        action_target_actor_id=planned["action_target_actor_id"],
        action_target_name=planned["action_target_name"],
        action_target_kind=planned["action_target_kind"],
        speech_target_actor_id=planned["speech_target_actor_id"],
        speech_target_name=planned["speech_target_name"],
        speech_target_kind=planned["speech_target_kind"],
        speech_target_label=speech_target_label,
        world_impact_type=planned["world_impact_type"],  # type: ignore[arg-type]
        alternation_depth=int(planned["alternation_depth"] or 0),
        target_actor_id=planned["target_actor_id"],
        target_name=planned["target_name"],
        target_actor_kind=planned["target_actor_kind"],  # type: ignore[arg-type]
        interaction_target_actor_id=planned["interaction_target_actor_id"],
        interaction_target_name=planned["interaction_target_name"],
        interaction_target_kind=planned["interaction_target_kind"],
        interaction_kind=str(planned["interaction_kind"] or ""),
        interaction_requires_response=bool(planned["interaction_requires_response"]),
        target_response_action_summary=str(planned["target_response_action_summary"] or ""),
        target_response_speech_text=str(planned["target_response_speech_text"] or ""),
        target_response_speech_target_name=planned["target_response_speech_target_name"],
        target_response_world_impact_type=planned["target_response_world_impact_type"],  # type: ignore[arg-type]
        interaction_exchange_kind=planned["interaction_exchange_kind"],  # type: ignore[arg-type]
        consent_state=planned["consent_state"],  # type: ignore[arg-type]
        resolution_mode=planned["resolution_mode"],  # type: ignore[arg-type]
        resolution_rule=planned["resolution_rule"],  # type: ignore[arg-type]
        planned_requires_check=bool(planned["planned_requires_check"]),
        planned_ability_used=planned["planned_ability_used"],  # type: ignore[arg-type]
        planned_dc=int(planned["planned_dc"]),
        planned_check_task=str(planned["planned_check_task"]),
        target_ability_used=planned["target_ability_used"],  # type: ignore[arg-type]
        target_ability_modifier=planned["target_ability_modifier"],  # type: ignore[arg-type]
        specific_threat=specific_threat,
        stakes_summary=specific_threat or action_summary,
        situation_delta_hint=max(-8, min(8, int(normalized.get("situation_delta_hint") or 0))),
        reputation_delta_hint=max(-3, min(3, int(normalized.get("reputation_delta_hint") or 0))),
        pause_kind=planned["pause_kind"],  # type: ignore[arg-type]
    )


def _planner_prompt_payload(
    actors: list[dict[str, object]],
    fallback_directives: list[PublicTurnSegmentActorDirective],
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for actor, directive in zip(actors, fallback_directives, strict=False):
        payload.append(
            {
                "actor_id": directive.actor_id,
                "actor_name": directive.actor_name,
                "actor_type": directive.actor_type.value,
                "priority_reason": str(actor.get("priority_reason") or ""),
                "roleplay_brief": public_scene_legacy._actor_roleplay_brief(actor),
                "private_chat_memory_context": (
                    build_private_chat_memory_context(actor.get("role"))
                    if directive.actor_type.value == "team" and actor.get("role") is not None
                    else "[]"
                ),
                "fallback_action_summary": directive.action_summary,
                "fallback_speech_text": directive.speech_text,
                "fallback_specific_threat": directive.specific_threat,
                "fallback_action_type": directive.action_type,
                "fallback_situation_delta_hint": directive.situation_delta_hint,
                "fallback_reputation_delta_hint": directive.reputation_delta_hint,
            }
        )
    return payload


def _apply_planner_overrides(
    save: SaveFile,
    *,
    actor: dict[str, object],
    phase: PublicTurnPhase,
    base: PublicTurnSegmentActorDirective,
    override: dict[str, object] | None,
    config: ChatConfig | None,
) -> PublicTurnSegmentActorDirective:
    action_summary = _clean_line(str((override or {}).get("action_summary") or base.action_summary))[:200]
    speech_text = _clean_line(str((override or {}).get("speech_text") or base.speech_text))[:200]
    specific_threat = _clean_line(str((override or {}).get("specific_threat") or base.specific_threat))[:200]
    action_type = _normalize_action_type(str((override or {}).get("action_type") or base.action_type))
    target_label = _clean_line(
        str((override or {}).get("target_label") or base.action_target_name or base.interaction_target_name or base.target_name or "")
    )[:80]
    speech_target_label = _clean_line(str((override or {}).get("speech_target_label") or base.speech_target_name or base.speech_target_label or ""))[:80]
    action_prompt = _clean_line(
        str((override or {}).get("action_prompt") or "")
        or f"actor={base.actor_name}; intent={action_summary}; threat={specific_threat}"
    )[:240]
    payload = {
        **_directive_payload(base),
        "action_narration": action_summary,
        "visible_intent": action_summary,
        "speech_line": speech_text,
        "speech_summary": speech_text,
        "specific_threat": specific_threat,
        "target_label": target_label,
        "speech_target_label": speech_target_label,
        "action_type": action_type,
        "action_prompt": action_prompt,
    }
    planned = _planned_directive_values(
        save,
        actor=actor,
        actor_id=base.actor_id,
        actor_name=base.actor_name,
        action_type=action_type,
        action_summary=action_summary,
        speech_text=speech_text,
        specific_threat=specific_threat,
        action_prompt=action_prompt,
        target_label=target_label,
        gm_summary="",
        payload=payload,
        override=override,
        config=config,
    )
    return PublicTurnSegmentActorDirective(
        actor_id=base.actor_id,
        actor_name=base.actor_name,
        actor_type=base.actor_type,
        phase=phase,
        action_type=action_type,  # type: ignore[arg-type]
        action_summary=action_summary or base.action_summary,
        speech_text=speech_text,
        action_prompt=action_prompt,
        action_target_actor_id=planned["action_target_actor_id"],
        action_target_name=planned["action_target_name"],
        action_target_kind=planned["action_target_kind"],
        speech_target_actor_id=planned["speech_target_actor_id"],
        speech_target_name=planned["speech_target_name"],
        speech_target_kind=planned["speech_target_kind"],
        speech_target_label=speech_target_label,
        world_impact_type=planned["world_impact_type"],  # type: ignore[arg-type]
        alternation_depth=int(planned["alternation_depth"] or 0),
        target_actor_id=planned["target_actor_id"],
        target_name=planned["target_name"],
        target_actor_kind=planned["target_actor_kind"],  # type: ignore[arg-type]
        interaction_target_actor_id=planned["interaction_target_actor_id"],
        interaction_target_name=planned["interaction_target_name"],
        interaction_target_kind=planned["interaction_target_kind"],
        interaction_kind=str(planned["interaction_kind"] or ""),
        interaction_requires_response=bool(planned["interaction_requires_response"]),
        target_response_action_summary=str(planned["target_response_action_summary"] or ""),
        target_response_speech_text=str(planned["target_response_speech_text"] or ""),
        target_response_speech_target_name=planned["target_response_speech_target_name"],
        target_response_world_impact_type=planned["target_response_world_impact_type"],  # type: ignore[arg-type]
        interaction_exchange_kind=planned["interaction_exchange_kind"],  # type: ignore[arg-type]
        consent_state=planned["consent_state"],  # type: ignore[arg-type]
        resolution_mode=planned["resolution_mode"],  # type: ignore[arg-type]
        resolution_rule=planned["resolution_rule"],  # type: ignore[arg-type]
        planned_requires_check=bool(planned["planned_requires_check"]),
        planned_ability_used=planned["planned_ability_used"],  # type: ignore[arg-type]
        planned_dc=int(planned["planned_dc"]),
        planned_check_task=str(planned["planned_check_task"]),
        target_ability_used=planned["target_ability_used"],  # type: ignore[arg-type]
        target_ability_modifier=planned["target_ability_modifier"],  # type: ignore[arg-type]
        specific_threat=specific_threat or base.specific_threat,
        stakes_summary=specific_threat or action_summary or base.stakes_summary,
        situation_delta_hint=max(
            -8,
            min(
                8,
                int((override or {}).get("situation_delta_hint") if (override or {}).get("situation_delta_hint") is not None else base.situation_delta_hint),
            ),
        ),
        reputation_delta_hint=max(
            -3,
            min(
                3,
                int(
                    (override or {}).get("reputation_delta_hint")
                    if (override or {}).get("reputation_delta_hint") is not None
                    else base.reputation_delta_hint
                ),
            ),
        ),
        pause_kind=planned["pause_kind"],  # type: ignore[arg-type]
    )


def _planner_overrides(
    *,
    session_id: str,
    phase: PublicTurnPhase,
    actor_rows: list[dict[str, object]],
    fallback_directives: list[PublicTurnSegmentActorDirective],
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None,
    prior_narration: str,
    config: ChatConfig | None,
) -> dict[str, dict[str, object]]:
    if not actor_rows:
        return {}
    config = require_ai_config(config)
    try:
        prompt = prompt_table.render(
            "public.turn.segment_plan.user",
            (
                "你是公开回合的段级行动规划器。只输出 JSON，结构为 "
                "{\"actors\":[{\"actor_id\":\"...\",\"action_type\":\"check|attack|item_use\","
                "\"action_summary\":\"...\",\"speech_text\":\"...\",\"specific_threat\":\"...\","
                "\"speech_target_label\":\"\",\"situation_delta_hint\":0,\"reputation_delta_hint\":0,"
                "\"pause_kind\":\"none|player_interaction|player_reaction|player_opposed\"}]}。"
                "你必须严格保持输入 actor 顺序，只能规划给定 actors。"
                "target_label 表示动作目标，speech_target_label 表示说话对象，两者可以不同。"
                "如果某个 actor 的动作直接作用到玩家身上，应该优先设置 player_interaction，而不是直接设置 player_reaction。"
                "不要规划玩家回合之后的 actor。"
                "player_text=$player_text; gm_summary=$gm_summary; scene_context_json=$scene_context_json; prior_narration=$prior_narration; phase=$phase; actors_json=$actors_json"
            ),
            player_text=player_text,
            gm_summary=gm_summary,
            scene_context_json=json.dumps(scene_context or {}, ensure_ascii=False),
            prior_narration=prior_narration[-720:],
            phase=phase.value,
            actors_json=json.dumps(_planner_prompt_payload(actor_rows, fallback_directives), ensure_ascii=False),
        )
        prompt = (
            f"{prompt}\nAllowed enum ids:\n"
            f"{render_enum_pool_text((EnumContractField(field_path='actors[].action_type', allowed_ids=('check', 'attack', 'item_use')), EnumContractField(field_path='actors[].pause_kind', allowed_ids=('none', 'player_interaction', 'player_reaction', 'player_opposed'))))}\n"
            "Use only the allowed stable ids for action_type and pause_kind.\n"
            "If actors_json[].private_chat_memory_context is not empty for a team actor, treat it as the primary memory source for that actor's public-turn tone, attitude, and player-facing preference.\n"
            "Those memory summaries may influence wording, body language, and whether the teammate leans toward protecting, supporting, avoiding, or distancing from the player.\n"
            "Do not let private_chat_memory_context override urgent scene threats, legal targets, or the formal check/resource rules.\n"
            "speech_target_label must identify only the listener of the spoken line.\n"
            "Do not use gaze targets, wink targets, gesture targets, or silent coordination partners as speech_target_label.\n"
            "If an actor looks at player A but the spoken line is directed at actor B, speech_target_label must be actor B.\n"
            "If there is no spoken addressee, return an empty speech_target_label.\n"
            "situation_delta_hint must stay within -8..8.\n"
            "reputation_delta_hint must stay within -3..3 and should describe direct public reputation impact in the current zone."
        )
        system_prompt = prompt_table.get_text("public.turn.segment_plan.system", "Return JSON only.")
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": prompt_table.get_text(
                        "public.turn.segment_plan.system",
                        "你只输出 JSON。所有文本使用简体中文。",
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
        raw_json = (resp.choices[0].message.content or "").strip() or "{}"
        parsed = json.loads(raw_json)
        parsed = validate_or_repair_json_payload(
            parsed=parsed if isinstance(parsed, dict) else {},
            raw_json=raw_json,
            fields=(
                EnumContractField(field_path="actors[].action_type", allowed_ids=("check", "attack", "item_use")),
                EnumContractField(
                    field_path="actors[].pause_kind",
                    allowed_ids=("none", "player_interaction", "player_reaction", "player_opposed"),
                ),
            ),
            config=config,
            system_prompt=system_prompt,
            original_prompt=prompt,
        )
        overrides: dict[str, dict[str, object]] = {}
        for item in list(parsed.get("actors") or []):
            if not isinstance(item, dict):
                continue
            actor_id = _clean_line(str(item.get("actor_id") or ""))
            if not actor_id:
                continue
            overrides[actor_id] = item
        return overrides
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc


def plan_public_turn_segment(
    save: SaveFile,
    *,
    round_state: PublicTurnRound,
    actor_rows: list[dict[str, object]],
    phase: PublicTurnPhase,
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None = None,
    audience_context: dict[str, object],
    prior_narration: str,
    default_boundary_kind: str,
    config: ChatConfig | None,
) -> PublicTurnSegmentPlan:
    segment_id = f"{round_state.round_id}_{phase.value}_{len(round_state.settlement_entries) + 1}"
    fallback_directives = [
        _fallback_directive(
            save,
            actor=actor,
            phase=phase,
            player_text=player_text,
            gm_summary=gm_summary,
            scene_context=scene_context,
            audience_context=audience_context,
            config=config,
        )
        for actor in actor_rows
    ]
    overrides = _planner_overrides(
        session_id=save.session_id,
        phase=phase,
        actor_rows=actor_rows,
        fallback_directives=fallback_directives,
        player_text=player_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        prior_narration=prior_narration,
        config=config,
    )
    directives: list[PublicTurnSegmentActorDirective] = []
    boundary = PublicTurnSegmentBoundary(
        boundary_kind=default_boundary_kind,  # type: ignore[arg-type]
        phase=phase,
    )
    for actor, fallback in zip(actor_rows, fallback_directives, strict=False):
        directive = _apply_planner_overrides(
            save,
            actor=actor,
            phase=phase,
            base=fallback,
            override=overrides.get(fallback.actor_id),
            config=config,
        )
        directives.append(directive)
        pause_boundary = _directive_boundary_from_pause(phase, directive)
        if pause_boundary is not None:
            boundary = pause_boundary
            break
    return PublicTurnSegmentPlan(
        segment_id=segment_id,
        round_id=round_state.round_id,
        phase=phase,
        actor_directives=directives,
        boundary=boundary,
    )


def resolve_public_turn_segment(
    save: SaveFile,
    *,
    round_state: PublicTurnRound,
    actor_lookup: dict[str, dict[str, object]],
    plan: PublicTurnSegmentPlan,
    context_text: str,
    reputation_score: int,
    config: ChatConfig | None,
) -> PublicTurnResolvedSegment:
    beats: list[PublicTurnResolvedBeat] = []
    pending_reaction: PlayerReactionCheck | None = None
    public_interaction_prompt: PublicTurnInteractionPrompt | None = None
    public_opposed_prompt: PublicTurnOpposedPrompt | None = None
    for directive in plan.actor_directives:
        actor = actor_lookup.get(directive.actor_id)
        if actor is None:
            continue
        payload = _directive_payload(directive)
        action_content = "\n".join(part for part in (directive.action_summary, directive.speech_text) if part.strip()).strip()
        if not action_content:
            action_content = directive.action_summary or directive.speech_text or directive.actor_name
        events = [
            world._new_scene_event(
                "public_turn_actor_action",
                action_content,
                actor_role_id=directive.actor_id,
                actor_name=directive.actor_name,
                metadata={
                    "actor_type": directive.actor_type.value,
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "target_label": directive.action_target_name or directive.target_name or "",
                    "speech_target_label": directive.speech_target_name or "",
                    "specific_threat": directive.specific_threat,
                },
            )
        ]
        public_scene_legacy._append_actor_memory(
            save,
            actor,
            display_text=context_text,
            action_line=action_content,
            priority_reason=str(actor.get("priority_reason") or ""),
        )
        if directive.pause_kind == "player_interaction":
            if directive.interaction_target_actor_id != save.player_static_data.player_id:
                continue
            public_interaction_prompt = PublicTurnInteractionPrompt(
                prompt_id=f"{round_state.round_id}_{directive.actor_id}_interaction",
                round_id=round_state.round_id,
                phase=round_state.phase,
                source_actor_id=directive.actor_id,
                source_actor_name=directive.actor_name,
                source_action_type=directive.action_type,
                source_action_summary=directive.action_summary,
                source_speech_text=directive.speech_text,
                source_action_target_name=directive.action_target_name,
                source_speech_target_name=directive.speech_target_name,
                source_action_prompt=directive.action_prompt,
                source_world_impact_type=directive.world_impact_type,
                source_situation_delta_hint=directive.situation_delta_hint,
                source_reputation_delta_hint=directive.reputation_delta_hint,
                source_planned_requires_check=directive.planned_requires_check,
                source_planned_ability_used=directive.planned_ability_used,
                source_planned_dc=directive.planned_dc,
                source_planned_check_task=directive.planned_check_task,
                source_interaction_kind=directive.interaction_kind,
                target_actor_id=directive.interaction_target_actor_id or save.player_static_data.player_id,
                target_actor_name=directive.interaction_target_name or save.player_static_data.name,
                target_actor_kind=directive.interaction_target_kind or public_turn_actor_type("player"),
                alternation_depth=directive.alternation_depth,
                interaction_mode=("alternated" if directive.alternation_depth else "initial"),
                suggested_target_label=directive.interaction_target_name or directive.target_name or save.player_static_data.name,
            )
            beats.append(
                PublicTurnResolvedBeat(
                    scene_events=events,
                    settlement=None,
                    impact=None,
                    narration_input=PublicTurnNarrationInputItem(
                        anchor_kind="pause_preview",
                        anchor_id=f"{plan.segment_id}_preview_{len(beats) + 1}",
                        order_index=len(round_state.narrative_entries) + len(beats),
                        actor_name=directive.actor_name,
                        actor_type=directive.actor_type,
                        action_summary=directive.action_summary,
                        speech_text=directive.speech_text,
                        action_target_name=directive.action_target_name,
                        speech_target_name=directive.speech_target_name,
                        gm_resolution_summary="",
                    ),
                )
            )
            break
        if directive.pause_kind == "player_opposed":
            if directive.interaction_target_actor_id != save.player_static_data.player_id:
                continue
            public_opposed_prompt = PublicTurnOpposedPrompt(
                check_id=f"{round_state.round_id}_{directive.actor_id}_opposed",
                round_id=round_state.round_id,
                phase=round_state.phase,
                source_actor_id=directive.actor_id,
                source_actor_name=directive.actor_name,
                source_action_summary=directive.action_summary,
                source_speech_text=directive.speech_text,
                source_interaction_kind=directive.interaction_kind,
                source_action_target_name=directive.action_target_name,
                source_speech_target_name=directive.speech_target_name,
                source_situation_delta_hint=directive.situation_delta_hint,
                source_reputation_delta_hint=directive.reputation_delta_hint,
                target_actor_id=directive.interaction_target_actor_id or save.player_static_data.player_id,
                target_actor_name=directive.interaction_target_name or save.player_static_data.name,
                stakes_summary=directive.stakes_summary,
            )
            beats.append(
                PublicTurnResolvedBeat(
                    scene_events=events,
                    settlement=None,
                    impact=None,
                    narration_input=PublicTurnNarrationInputItem(
                        anchor_kind="pause_preview",
                        anchor_id=f"{plan.segment_id}_preview_{len(beats) + 1}",
                        order_index=len(round_state.narrative_entries) + len(beats),
                        actor_name=directive.actor_name,
                        actor_type=directive.actor_type,
                        action_summary=directive.action_summary,
                        speech_text=directive.speech_text,
                        action_target_name=directive.action_target_name,
                        speech_target_name=directive.speech_target_name,
                        gm_resolution_summary="",
                    ),
                )
            )
            break
        action_result = None
        if directive.planned_requires_check:
            action_result = public_scene_legacy._actor_check(
                save,
                directive.actor_id,
                action_type=directive.action_type,
                action_prompt=directive.action_prompt or action_content,
                resolution_rule=directive.resolution_rule,
                target_role_id=directive.action_target_actor_id or directive.target_actor_id,
                target_name=directive.action_target_name or directive.target_name,
                target_actor_kind=directive.target_actor_kind,
                target_ability_used=directive.target_ability_used,
                target_ability_modifier=directive.target_ability_modifier,
                planned_ability_used=directive.planned_ability_used,
                planned_dc=directive.planned_dc,
                planned_time_spent_min=1,
                planned_requires_check=directive.planned_requires_check,
                planned_check_task=directive.planned_check_task,
                config=config,
            )
        interaction_resolution = "non_interactive"
        if directive.interaction_requires_response:
            if directive.consent_state == "accepted":
                interaction_resolution = "accepted"
            elif directive.resolution_mode == "opposed_actor":
                interaction_resolution = "rejected_opposed"
            else:
                interaction_resolution = "ambiguous_non_opposed"
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
            action_target_actor_id=directive.action_target_actor_id,
            action_target_name=directive.action_target_name,
            action_target_kind=directive.action_target_kind,
            speech_target_actor_id=directive.speech_target_actor_id,
            speech_target_name=directive.speech_target_name,
            speech_target_kind=directive.speech_target_kind,
            source_world_impact_type=directive.world_impact_type,
            target_response_world_impact_type=directive.target_response_world_impact_type,
            interaction_exchange_kind=directive.interaction_exchange_kind,
            alternation_depth=directive.alternation_depth,
            interaction_target_name=directive.interaction_target_name or directive.target_name,
            interaction_resolution=interaction_resolution,
            opposed_target_name=directive.interaction_target_name or directive.target_name,
            opposed_target_action=directive.target_response_action_summary or None,
            opposed_target_speech=directive.target_response_speech_text or None,
            opposed_target_speech_target_name=directive.target_response_speech_target_name,
        )
        beats.append(
            PublicTurnResolvedBeat(
                scene_events=events,
                settlement=settlement,
                impact=impact,
                narration_input=PublicTurnNarrationInputItem(
                    anchor_kind="settlement",
                    anchor_id=settlement.entry_id,
                    order_index=settlement.order_index,
                    actor_name=settlement.actor_name,
                    actor_type=settlement.actor_type,
                    action_summary=settlement.action_summary,
                    speech_text=settlement.speech_text,
                    action_target_name=settlement.action_target_name,
                    speech_target_name=settlement.speech_target_name,
                    gm_resolution_summary=settlement.gm_resolution_summary,
                    opposed_target_name=settlement.opposed_target_name,
                    opposed_target_action=settlement.opposed_target_action,
                    opposed_target_speech=settlement.opposed_target_speech,
                    opposed_target_speech_target_name=settlement.opposed_target_speech_target_name,
                ),
            )
        )
        pending_reaction = _build_reaction_for_actor(
            actor,
            payload=payload,
            situation_delta=situation_delta,
            action_target_name=directive.action_target_name or directive.target_name,
        )
        if pending_reaction is not None:
            break
    return PublicTurnResolvedSegment(
        plan=plan,
        beats=beats,
        pending_reaction=pending_reaction,
        public_interaction_prompt=public_interaction_prompt,
        public_opposed_prompt=public_opposed_prompt,
    )


def narrate_public_turn_segment(
    *,
    session_id: str,
    round_state: PublicTurnRound,
    segment: PublicTurnResolvedSegment,
    config: ChatConfig | None,
) -> PublicTurnNarrationFragmentBatch:
    fragments = []
    for beat in segment.beats:
        if beat.settlement is None:
            continue
        text = build_settlement_fragment(beat.settlement)
        if not text:
            continue
        fragments.append(
            {
                "anchor_kind": "settlement",
                "anchor_id": beat.settlement.entry_id,
                "text": text,
            }
        )
    return PublicTurnNarrationFragmentBatch(segment_id=segment.plan.segment_id, fragments=fragments)
