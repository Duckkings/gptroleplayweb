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
    PublicTurnNarrationFragmentBatch,
    PublicTurnNarrationInputItem,
    PublicTurnOpposedPrompt,
    PublicTurnPhase,
    PublicTurnRound,
    PublicTurnSegmentActorDirective,
    PublicTurnSegmentBoundary,
    PublicTurnSegmentPlan,
    PublicTurnSettlementEntry,
    PublicTurnImpact,
    SaveFile,
    SceneEvent,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world
from app.services.public_turn_narration_service import build_segment_narration_fragments
from app.services.public_turn_resolution import (
    _build_reaction_for_actor,
    _finalize_ai_actor_turn,
    settlement_actor_type,
)


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
        "target_label": directive.target_name or "",
        "action_type": directive.action_type,
        "action_prompt": directive.action_prompt,
        "situation_delta_hint": directive.situation_delta_hint,
    }


def _fallback_directive(
    save: SaveFile,
    *,
    actor: dict[str, object],
    phase: PublicTurnPhase,
    player_text: str,
    gm_summary: str,
    audience_context: dict[str, object],
) -> PublicTurnSegmentActorDirective:
    actor_id = str(actor.get("actor_id") or "")
    actor_name = str(actor.get("name") or "")
    payload = public_scene_runtime._fallback_actor_action(
        save,
        actor,
        player_text=player_text,
        gm_summary=gm_summary,
        incoming_interaction=None,
    )
    if not public_scene_runtime.actor_may_speak_in_public_turn(actor, audience_context):
        payload["speech_line"] = ""
        payload["speech_summary"] = ""
    action_summary = _clean_line(
        str(payload.get("external_action_narration") or payload.get("visible_intent") or "")
    )[:200]
    speech_text = _clean_line(str(payload.get("speech_line") or payload.get("speech_summary") or ""))[:200]
    specific_threat = _clean_line(str(payload.get("specific_threat") or ""))[:200]
    action_type = _normalize_action_type(str(payload.get("action_type") or "check"))
    action_prompt = _clean_line(
        str(payload.get("action_prompt") or "") or f"actor={actor_name}; intent={action_summary}; threat={specific_threat}"
    )[:240]
    opposed = world._build_public_turn_opposed_plan(
        save,
        actor_role_id=actor_id,
        action_type=action_type,
        action_prompt=action_prompt,
    )
    if opposed is not None:
        resolution_rule = "opposed_actor"
        target_actor_id = str(opposed.get("target_role_id") or "") or None
        target_name = str(opposed.get("target_name") or "") or None
        target_actor_kind = str(opposed.get("target_actor_kind") or "").strip() or None
        target_ability_used = str(opposed.get("target_ability_used") or "").strip() or None
        target_ability_modifier = (
            int(opposed.get("target_ability_modifier"))
            if opposed.get("target_ability_modifier") is not None
            else None
        )
        planned_requires_check = True
        planned_ability_used = str(opposed.get("ability_used") or "strength")
        planned_dc = int(opposed.get("dc") or 10)
        planned_check_task = str(opposed.get("check_task") or action_prompt)
    else:
        plan = world._fallback_action_plan(action_type, action_prompt)
        resolution_rule = "static_dc"
        target_actor_id = None
        target_name = None
        target_actor_kind = None
        target_ability_used = None
        target_ability_modifier = None
        planned_requires_check = bool(
            plan.get("requires_check") or public_scene_runtime.should_force_public_action_check(save, actor, payload)
        )
        planned_ability_used = str(plan.get("ability_used") or "wisdom")
        planned_dc = int(plan.get("dc") or 10)
        planned_check_task = str(plan.get("check_task") or action_prompt)
    pause_kind = "none"
    if target_actor_id == save.player_static_data.player_id and resolution_rule == "opposed_actor" and action_type != "attack":
        pause_kind = "player_opposed"
    elif _player_targeted("\n".join((action_summary, speech_text, specific_threat, action_prompt)), save.player_static_data.name):
        if action_type == "attack":
            pause_kind = "player_reaction"
    return PublicTurnSegmentActorDirective(
        actor_id=actor_id,
        actor_name=actor_name,
        actor_type=settlement_actor_type(str(actor.get("actor_type") or "npc")),
        phase=phase,
        action_type=action_type,  # type: ignore[arg-type]
        action_summary=action_summary,
        speech_text=speech_text,
        action_prompt=action_prompt,
        target_actor_id=target_actor_id,
        target_name=target_name,
        target_actor_kind=target_actor_kind,  # type: ignore[arg-type]
        resolution_rule=resolution_rule,  # type: ignore[arg-type]
        planned_requires_check=planned_requires_check,
        planned_ability_used=planned_ability_used,  # type: ignore[arg-type]
        planned_dc=planned_dc,
        planned_check_task=planned_check_task,
        target_ability_used=target_ability_used,  # type: ignore[arg-type]
        target_ability_modifier=target_ability_modifier,
        specific_threat=specific_threat,
        stakes_summary=specific_threat or action_summary,
        situation_delta_hint=max(-8, min(8, int(payload.get("situation_delta_hint") or 0))),
        pause_kind=pause_kind,  # type: ignore[arg-type]
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
                "fallback_action_summary": directive.action_summary,
                "fallback_speech_text": directive.speech_text,
                "fallback_specific_threat": directive.specific_threat,
                "fallback_action_type": directive.action_type,
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
) -> PublicTurnSegmentActorDirective:
    action_summary = _clean_line(str((override or {}).get("action_summary") or base.action_summary))[:200]
    speech_text = _clean_line(str((override or {}).get("speech_text") or base.speech_text))[:200]
    specific_threat = _clean_line(str((override or {}).get("specific_threat") or base.specific_threat))[:200]
    action_type = _normalize_action_type(str((override or {}).get("action_type") or base.action_type))
    action_prompt = _clean_line(
        str((override or {}).get("action_prompt") or "")
        or f"actor={base.actor_name}; intent={action_summary}; threat={specific_threat}"
    )[:240]
    opposed = world._build_public_turn_opposed_plan(
        save,
        actor_role_id=base.actor_id,
        action_type=action_type,
        action_prompt=action_prompt,
    )
    if opposed is not None:
        resolution_rule = "opposed_actor"
        target_actor_id = str(opposed.get("target_role_id") or "") or None
        target_name = str(opposed.get("target_name") or "") or None
        target_actor_kind = str(opposed.get("target_actor_kind") or "").strip() or None
        target_ability_used = str(opposed.get("target_ability_used") or "").strip() or None
        target_ability_modifier = (
            int(opposed.get("target_ability_modifier"))
            if opposed.get("target_ability_modifier") is not None
            else None
        )
        planned_requires_check = True
        planned_ability_used = str(opposed.get("ability_used") or "strength")
        planned_dc = int(opposed.get("dc") or 10)
        planned_check_task = str(opposed.get("check_task") or action_prompt)
    else:
        plan = world._fallback_action_plan(action_type, action_prompt)
        resolution_rule = "static_dc"
        target_actor_id = None
        target_name = None
        target_actor_kind = None
        target_ability_used = None
        target_ability_modifier = None
        planned_requires_check = bool(
            (override or {}).get("planned_requires_check")
            if (override or {}).get("planned_requires_check") is not None
            else (plan.get("requires_check") or public_scene_runtime.should_force_public_action_check(save, actor, _directive_payload(base)))
        )
        planned_ability_used = str((override or {}).get("planned_ability_used") or plan.get("ability_used") or "wisdom")
        planned_dc = int((override or {}).get("planned_dc") or plan.get("dc") or 10)
        planned_check_task = str((override or {}).get("planned_check_task") or plan.get("check_task") or action_prompt)
    pause_kind = str((override or {}).get("pause_kind") or "").strip().lower()
    if pause_kind not in {"none", "player_reaction", "player_opposed"}:
        pause_kind = "none"
    if target_actor_id == save.player_static_data.player_id and resolution_rule == "opposed_actor" and action_type != "attack":
        pause_kind = "player_opposed"
    elif target_actor_id == save.player_static_data.player_id and action_type == "attack":
        pause_kind = "player_reaction"
    return PublicTurnSegmentActorDirective(
        actor_id=base.actor_id,
        actor_name=base.actor_name,
        actor_type=base.actor_type,
        phase=phase,
        action_type=action_type,  # type: ignore[arg-type]
        action_summary=action_summary or base.action_summary,
        speech_text=speech_text,
        action_prompt=action_prompt,
        target_actor_id=target_actor_id,
        target_name=target_name,
        target_actor_kind=target_actor_kind,  # type: ignore[arg-type]
        resolution_rule=resolution_rule,  # type: ignore[arg-type]
        planned_requires_check=planned_requires_check,
        planned_ability_used=planned_ability_used,  # type: ignore[arg-type]
        planned_dc=planned_dc,
        planned_check_task=planned_check_task,
        target_ability_used=target_ability_used,  # type: ignore[arg-type]
        target_ability_modifier=target_ability_modifier,
        specific_threat=specific_threat or base.specific_threat,
        stakes_summary=specific_threat or action_summary or base.stakes_summary,
        situation_delta_hint=max(
            -8,
            min(
                8,
                int((override or {}).get("situation_delta_hint") if (override or {}).get("situation_delta_hint") is not None else base.situation_delta_hint),
            ),
        ),
        pause_kind=pause_kind,  # type: ignore[arg-type]
    )


def _planner_overrides(
    *,
    session_id: str,
    phase: PublicTurnPhase,
    actor_rows: list[dict[str, object]],
    fallback_directives: list[PublicTurnSegmentActorDirective],
    player_text: str,
    gm_summary: str,
    prior_narration: str,
    config: ChatConfig | None,
) -> dict[str, dict[str, object]]:
    if not actor_rows or not has_ai_config(config):
        return {}
    assert config is not None
    try:
        prompt = prompt_table.render(
            "public.turn.segment_plan.user",
            (
                "你是公开回合的段级行动规划器。只输出 JSON，结构为 "
                "{\"actors\":[{\"actor_id\":\"...\",\"action_type\":\"check|attack|item_use\","
                "\"action_summary\":\"...\",\"speech_text\":\"...\",\"specific_threat\":\"...\","
                "\"situation_delta_hint\":0,\"pause_kind\":\"none|player_reaction|player_opposed\"}]}。"
                "你必须严格保持输入 actor 顺序，只能规划给定 actors。"
                "如果某个 actor 的动作会直接逼出玩家反应或玩家对抗，可以设置对应 pause_kind。"
                "不要规划玩家回合之后的 actor。"
                "player_text=$player_text; gm_summary=$gm_summary; prior_narration=$prior_narration; phase=$phase; actors_json=$actors_json"
            ),
            player_text=player_text,
            gm_summary=gm_summary,
            prior_narration=prior_narration[-720:],
            phase=phase.value,
            actors_json=json.dumps(_planner_prompt_payload(actor_rows, fallback_directives), ensure_ascii=False),
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
        parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        overrides: dict[str, dict[str, object]] = {}
        for item in list(parsed.get("actors") or []):
            if not isinstance(item, dict):
                continue
            actor_id = _clean_line(str(item.get("actor_id") or ""))
            if not actor_id:
                continue
            overrides[actor_id] = item
        return overrides
    except Exception:
        return {}


def plan_public_turn_segment(
    save: SaveFile,
    *,
    round_state: PublicTurnRound,
    actor_rows: list[dict[str, object]],
    phase: PublicTurnPhase,
    player_text: str,
    gm_summary: str,
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
            audience_context=audience_context,
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
                    "target_label": directive.target_name or "",
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
        if directive.pause_kind == "player_opposed":
            public_opposed_prompt = PublicTurnOpposedPrompt(
                check_id=f"{round_state.round_id}_{directive.actor_id}_opposed",
                round_id=round_state.round_id,
                phase=round_state.phase,
                source_actor_id=directive.actor_id,
                source_actor_name=directive.actor_name,
                source_action_summary=directive.action_summary,
                source_speech_text=directive.speech_text,
                target_actor_id=save.player_static_data.player_id,
                target_actor_name=save.player_static_data.name,
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
                target_role_id=directive.target_actor_id,
                target_name=directive.target_name,
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
        events, impact, settlement, situation_delta = _finalize_ai_actor_turn(
            save,
            actor=actor,
            payload=payload,
            round_state=round_state,
            action_content=action_content,
            action_result=action_result,
            reputation_score=reputation_score,
            base_events=events,
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
                    gm_resolution_summary=settlement.gm_resolution_summary,
                    opposed_target_name=settlement.opposed_target_name,
                    opposed_target_action=settlement.opposed_target_action,
                    opposed_target_speech=settlement.opposed_target_speech,
                ),
            )
        )
        pending_reaction = _build_reaction_for_actor(actor, payload=payload, situation_delta=situation_delta)
        if pending_reaction is not None:
            break
    return PublicTurnResolvedSegment(
        plan=plan,
        beats=beats,
        pending_reaction=pending_reaction,
        public_opposed_prompt=public_opposed_prompt,
    )


def narrate_public_turn_segment(
    *,
    session_id: str,
    round_state: PublicTurnRound,
    segment: PublicTurnResolvedSegment,
    config: ChatConfig | None,
) -> PublicTurnNarrationFragmentBatch:
    items = [beat.narration_input for beat in segment.beats if beat.narration_input is not None]
    return build_segment_narration_fragments(
        session_id=session_id,
        round_number=round_state.round_number,
        phase=round_state.phase.value,
        segment_id=segment.plan.segment_id,
        items=items,  # type: ignore[arg-type]
        prior_text=round_state.accumulated_narration,
        config=config,
    )
