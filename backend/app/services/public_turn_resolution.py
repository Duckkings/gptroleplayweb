from __future__ import annotations

import json
import random
from typing import Any

from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    ChatConfig,
    EnvironmentRiskLevel,
    InitiativeDeclaration,
    NpcRoleCard,
    PlayerReactionCheck,
    PublicTurnActorType,
    PublicTurnImpact,
    PublicTurnInitiativeEntry,
    PublicTurnOpposedPrompt,
    PublicTurnOpposedPlanRequest,
    PublicTurnPlayerActionCheck,
    PublicTurnRound,
    PublicTurnSettlementCheck,
    PublicTurnSettlementEntry,
    SaveFile,
    SceneEvent,
)
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import reaction_check_service
from app.services import world_service as world
from app.services.encounter_service import apply_active_encounter_situation_delta_in_save
from app.services import zone_metric_service
from app.services.public_turn_candidates import (
    actor_name_match,
    dex_modifier_for_actor,
    initiative_actor_rows,
    public_turn_normal_actor_rows,
    visible_actor_rows,
)
from app.services.public_turn_effects import (
    apply_player_npc_reactions,
    apply_player_team_reactions,
    apply_round_reputation,
    build_impact,
    check_bonus,
    next_environment_risk,
    relation_delta_from_result,
    reputation_delta_from_situation,
)

_HOSTILE_TOKENS = ("攻击", "威胁", "阻止", "抢", "强闯", "拔剑", "射击", "法术", "attack", "threat", "force", "kill")
_DESTRUCTIVE_TOKENS = ("爆炸", "火球", "炸", "砸", "推倒", "坍塌", "破坏", "explode", "burn", "collapse")


def _submission_display_text(action_text: str, speech_text: str) -> str:
    parts: list[str] = []
    if action_text.strip():
        parts.append(f"动作:{action_text.strip()}")
    if speech_text.strip():
        parts.append(f"语言:{speech_text.strip()}")
    return "\n".join(parts).strip() or "玩家等待并观察。"


def settlement_actor_type(value: str | None) -> PublicTurnActorType:
    actor_type = str(value or "npc").strip().lower()
    if actor_type == "player":
        return PublicTurnActorType.PLAYER
    if actor_type == "team":
        return PublicTurnActorType.TEAM
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


def _default_gm_resolution_summary(actor_name: str, action_summary: str, situation_delta: int) -> str:
    clean_action = " ".join(str(action_summary or "").split())
    if situation_delta >= 4:
        return f"{actor_name}的动作立刻撬动了现场，让局势明显朝有利方向偏转。"
    if situation_delta <= -4:
        return f"{actor_name}的动作没能稳住场面，反而让现场压力继续堆高。"
    if clean_action:
        return f"{actor_name}的动作落地后，现场对“{clean_action[:24]}”给出了直接回应。"
    return f"{actor_name}的动作落地后，周围人的注意力和站位都发生了变化。"


def build_settlement_check(action_result: ActionCheckResponse | None) -> PublicTurnSettlementCheck | None:
    if action_result is None:
        return None
    success = bool(action_result.success)
    outcome_text = "成功" if success else "失败"
    if action_result.critical == "critical_success":
        outcome_text = "大成功"
    elif action_result.critical == "critical_failure":
        outcome_text = "大失败"
    if action_result.resolution_rule == "opposed_actor" and action_result.target_name:
        comparison_text = (
            f"{action_result.actor_name} d20({action_result.dice_roll if action_result.dice_roll is not None else '-'}) "
            f"{action_result.ability_modifier:+d} = {action_result.total_score if action_result.total_score is not None else '-'}；"
            f"{action_result.target_name} d20({action_result.target_dice_roll if action_result.target_dice_roll is not None else '-'}) "
            f"{int(action_result.target_ability_modifier or 0):+d} = {action_result.target_total_score if action_result.target_total_score is not None else '-'}。"
        )
    else:
        comparison_text = (
            f"d20({action_result.dice_roll if action_result.dice_roll is not None else '-'}) "
            f"{action_result.ability_modifier:+d} = {action_result.total_score if action_result.total_score is not None else '-'} "
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
    gm_resolution_summary: str,
    opposed_target_name: str | None = None,
    opposed_target_action: str | None = None,
    opposed_target_speech: str | None = None,
) -> PublicTurnSettlementEntry:
    return PublicTurnSettlementEntry(
        entry_id=f"{round_state.round_id}_{len(round_state.settlement_entries) + 1}",
        round_id=round_state.round_id,
        phase=round_state.phase,
        order_index=len(round_state.settlement_entries),
        actor_id=actor_id,
        actor_name=actor_name,
        actor_type=settlement_actor_type(actor_type),
        action_summary=action_summary[:200],
        speech_text=speech_text[:200],
        opposed_target_name=opposed_target_name or (action_result.target_name if action_result is not None else None),
        opposed_target_action=(opposed_target_action or "")[:200] or None,
        opposed_target_speech=(opposed_target_speech or "")[:200] or None,
        check=build_settlement_check(action_result),
        gm_resolution_summary=(gm_resolution_summary or _default_gm_resolution_summary(actor_name, action_summary, impact.situation_delta))[:240],
        situation_delta=impact.situation_delta,
        zone_reputation_delta=impact.zone_reputation_delta,
        relation_deltas=list(impact.relation_deltas),
        team_affinity_deltas=list(impact.team_affinity_deltas),
        hp_changes=list(impact.hp_changes),
        environment_shift=impact.environment_shift,
    )


def _action_type_for_text(text: str) -> str:
    merged = text.lower()
    if any(token in merged for token in ("attack", "射击", "砍", "刺", "攻击", "拔剑", "施法", "法术")):
        return "attack"
    if any(token in merged for token in ("use", "道具", "药", "item", "使用")):
        return "item_use"
    return "check"


def _requires_action_check(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    if any(token in clean.lower() for token in _HOSTILE_TOKENS):
        return True
    return len(clean) >= 12


def _situation_hint_from_text(text: str) -> int:
    hint = 0
    lowered = text.lower()
    if any(token in lowered for token in ("帮助", "安抚", "稳定", "观察", "保护", "assist", "stabilize", "observe", "protect")):
        hint += 2
    if any(token in lowered for token in ("攻击", "威胁", "强闯", "冒险", "attack", "threat", "force")):
        hint += 1
    if any(token in lowered for token in ("失误", "慌", "乱", "误伤", "panic", "mistake")):
        hint -= 2
    return max(-6, min(6, hint))


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
    addressed_role_name: str = "",
    incoming_target_candidates: list[str] | None = None,
    config: ChatConfig | None = None,
) -> list[InitiativeDeclaration]:
    hostile = any(token in player_action_text.lower() for token in _HOSTILE_TOKENS)
    declarations: list[InitiativeDeclaration] = []
    if not hostile:
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
        declared_action = "立刻介入并回应玩家的危险动作。"
        if actor_type == "team":
            declared_action = "抢先保护玩家并压住眼前风险。"
        elif actor_type == "hidden_npc":
            declared_action = "从暗处介入，试图打断当前局面。"
        declarations.append(
            InitiativeDeclaration(
                actor_id=actor_id,
                actor_type=("hidden_npc" if actor_type == "hidden_npc" else actor_type),  # type: ignore[arg-type]
                actor_name=str(actor.get("name") or "在场角色"),
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
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry, ActionCheckResponse | None]:
    display_text = _submission_display_text(action_text, speech_text)
    action_result = _player_action_check(
        save,
        session_id=session_id,
        actor_id=save.player_static_data.player_id,
        text=display_text,
        action_check=action_check,
        config=config,
    )
    situation_delta = max(-20, min(20, _situation_hint_from_text(display_text) + check_bonus(action_result)))
    relation_delta = relation_delta_from_result(action_result, situation_delta)
    gm_resolution_summary = _last_nonempty_line(action_result.narrative) if action_result is not None else ""
    if not gm_resolution_summary:
        gm_resolution_summary = _default_gm_resolution_summary(
            save.player_static_data.name,
            action_text.strip() or display_text,
            situation_delta,
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
    relation_rows, relation_events = apply_player_npc_reactions(
        save,
        session_id=session_id,
        player_text=display_text,
        summary=gm_resolution_summary or display_text,
        relation_delta=relation_delta,
        target_role_id=(action_result.target_role_id if action_result is not None else (action_check.target_role_id if action_check is not None else None)),
    )
    team_rows, reaction_events = apply_player_team_reactions(
        save,
        session_id=session_id,
        player_text=display_text,
        summary=gm_resolution_summary or display_text,
    )
    save.game_logs.append(
        world._new_game_log(
            session_id,
            "public_turn_player_action",
            f"{save.player_static_data.name} 在公开回合中行动：{display_text[:120]}",
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
        zone_reputation_delta=reputation_delta_from_situation(situation_delta),
        relation_deltas=relation_rows,
        team_affinity_deltas=team_rows,
        environment_shift=(2 if any(token in display_text.lower() for token in _DESTRUCTIVE_TOKENS) else 0),
        scene_events=events,
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
        opposed_target_name=(action_result.target_name if action_result is not None else None),
    )
    return events, impact, settlement, action_result


def _build_reaction_for_actor(
    actor: dict[str, object],
    *,
    payload: dict[str, object],
    situation_delta: int,
) -> PlayerReactionCheck | None:
    action_type = str(payload.get("action_type") or "check").strip().lower()
    threat = str(payload.get("specific_threat") or "").strip()
    if action_type != "attack" and not any(token in threat for token in ("攻击", "打", "砍", "刺", "威胁")):
        return None
    actor_name = str(actor.get("name") or "在场角色")
    return reaction_check_service.build_player_reaction_check(
        {
            "source_kind": "public_turn",
            "source_actor_id": str(actor.get("actor_id") or ""),
            "source_actor_name": actor_name,
            "source_label": actor_name,
            "trigger_summary": f"{actor_name}突然把动作压向你，逼你立刻做出反应。",
            "threatened_consequence": threat or "你若应对失误，局面会立刻恶化。",
            "ability_used": "dexterity",
            "dc": max(8, min(18, 10 + max(0, situation_delta // 2))),
            "check_task": f"立刻应对{actor_name}压上来的动作",
            "success_hint": "你及时避开或挡开了这次危险。",
            "failure_hint": "你慢了半拍，被这股压力正面撞上。",
            "critical_success_hint": "你不仅避开了危险，还抢回了局面主动。",
            "critical_failure_hint": "你失去重心，局面彻底被对方抢走。",
        },
        resolution_context="public_turn",
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
    if world._opposed_rule_for_prompt(combined) is None:
        return None
    player_name = save.player_static_data.name
    if not any(marker and marker in combined for marker in (player_name, "玩家", "你", "你们")):
        return None
    return PublicTurnOpposedPrompt(
        check_id=f"{round_state.round_id}_{actor_id}_opposed",
        round_id=round_state.round_id,
        phase=round_state.phase,
        source_actor_id=actor_id,
        source_actor_name=str(actor.get("name") or ""),
        source_action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content)[:200],
        source_speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or "")[:200],
        target_actor_id=save.player_static_data.player_id,
        target_actor_name=player_name,
        stakes_summary=str(payload.get("specific_threat") or action_content)[:240],
    )


def _finalize_ai_actor_turn(
    save: SaveFile,
    *,
    actor: dict[str, object],
    payload: dict[str, object],
    round_state: PublicTurnRound,
    action_content: str,
    action_result: ActionCheckResponse | None,
    reputation_score: int,
    base_events: list[SceneEvent],
    opposed_target_name: str | None = None,
    opposed_target_action: str | None = None,
    opposed_target_speech: str | None = None,
) -> tuple[list[SceneEvent], PublicTurnImpact, PublicTurnSettlementEntry, int]:
    actor_id = str(actor.get("actor_id") or "")
    events = list(base_events)
    situation_delta = public_scene_legacy._clamp(int(payload.get("situation_delta_hint") or 0) + check_bonus(action_result), -20, 20)
    reputation_delta = reputation_delta_from_situation(situation_delta)
    relation_rows: list[dict[str, Any]] = []
    team_rows: list[dict[str, Any]] = []
    role = actor.get("role")
    if isinstance(role, NpcRoleCard):
        before_tag = next((item.relation_tag for item in role.relations if item.target_role_id == save.player_static_data.player_id), "neutral")
        relation_delta = relation_delta_from_result(action_result, situation_delta)
        applied = 0
        if relation_delta != 0:
            applied = public_scene_legacy._apply_actor_relation_delta(
                save,
                role,
                str(actor.get("actor_type") or "npc"),
                relation_delta,
                reputation_score,
            )
        after_tag = next((item.relation_tag for item in role.relations if item.target_role_id == save.player_static_data.player_id), before_tag)
        if applied or before_tag != after_tag:
            relation_rows.append(
                {
                    "role_id": role.role_id,
                    "name": role.name,
                    "before_tag": before_tag,
                    "after_tag": after_tag,
                    "relation_delta": applied,
                    "reaction_text": "",
                }
            )
            events.append(
                world._new_scene_event(
                    "public_turn_relation_update",
                    f"{role.name} 对你的态度发生变化。",
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    metadata={
                        "role_id": role.role_id,
                        "name": role.name,
                        "before_tag": before_tag,
                        "after_tag": after_tag,
                        "relation_delta": applied,
                        "reaction_text": "",
                    },
                )
            )
    if str(actor.get("actor_type") or "npc") == "team":
        member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_id), None)
        if member is not None:
            before_affinity = int(member.affinity)
            before_trust = int(member.trust)
            relation_delta = relation_delta_from_result(action_result, situation_delta)
            if relation_delta:
                member.affinity = public_scene_legacy._clamp(member.affinity + relation_delta * 3, 0, 100)
                member.trust = public_scene_legacy._clamp(member.trust + relation_delta * 2, 0, 100)
            affinity_after = int(member.affinity)
            trust_after = int(member.trust)
            affinity_delta = affinity_after - before_affinity
            trust_delta = trust_after - before_trust
            if affinity_delta or trust_delta:
                team_rows.append(
                    {
                        "member_role_id": actor_id,
                        "name": str(actor.get("name") or ""),
                        "affinity_before": before_affinity,
                        "affinity_after": affinity_after,
                        "affinity_delta": affinity_delta,
                        "trust_before": before_trust,
                        "trust_after": trust_after,
                        "trust_delta": trust_delta,
                        "reaction_text": "",
                    }
                )
                events.append(
                    world._new_scene_event(
                        "public_turn_team_update",
                        f"{actor.get('name')}: 好感{affinity_delta:+d} / 信任{trust_delta:+d}",
                        actor_role_id=actor_id,
                        actor_name=str(actor.get("name") or ""),
                        metadata={
                            "member_role_id": actor_id,
                            "name": str(actor.get("name") or ""),
                            "affinity_before": before_affinity,
                            "affinity_after": affinity_after,
                            "affinity_delta": affinity_delta,
                            "trust_before": before_trust,
                            "trust_after": trust_after,
                            "trust_delta": trust_delta,
                            "reaction_text": "",
                        },
                    )
                )
    resolution_text = (action_result.narrative if action_result is not None else "") or f"{actor.get('name')} 把动作落到了眼前局面上。"
    resolution_text = _last_nonempty_line(resolution_text)
    if not resolution_text:
        resolution_text = _default_gm_resolution_summary(
            str(actor.get("name") or "在场角色"),
            str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
            situation_delta,
        )
    events.append(
        world._new_scene_event(
            "public_turn_actor_resolution",
            resolution_text,
            actor_role_id=actor_id,
            actor_name=str(actor.get("name") or ""),
            metadata={
                "actor_type": str(actor.get("actor_type") or "npc"),
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
        environment_shift=(2 if any(token in str(payload.get("specific_threat") or "") for token in _DESTRUCTIVE_TOKENS) else 0),
        scene_events=events,
    )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        actor_type=str(actor.get("actor_type") or "npc"),
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or ""),
        action_result=action_result,
        impact=impact,
        gm_resolution_summary=resolution_text,
        opposed_target_name=opposed_target_name or (action_result.target_name if action_result is not None else None),
        opposed_target_action=opposed_target_action,
        opposed_target_speech=opposed_target_speech,
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
    payload = public_scene_runtime._ai_actor_action(
        save,
        actor,
        player_text=player_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        incoming_interaction=None,
        config=config,
    ) or public_scene_runtime._fallback_actor_action(
        save,
        actor,
        player_text=player_text,
        gm_summary=gm_summary,
        incoming_interaction=None,
    )
    if not public_scene_runtime.actor_may_speak_in_public_turn(actor, audience_context):
        payload["speech_line"] = ""
        payload["speech_summary"] = ""
    action_content = public_scene_runtime._compose_actor_content(payload)
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
    public_scene_legacy._append_actor_memory(
        save,
        actor,
        display_text=player_text,
        action_line=action_content,
        priority_reason=str(actor.get("priority_reason") or ""),
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
    if requires_check:
        action_result = public_scene_legacy._actor_check(
            save,
            actor_id,
            action_type=str(payload.get("action_type") or "check"),
            action_prompt=str(payload.get("action_prompt") or action_content),
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
    pending_reaction = _build_reaction_for_actor(actor, payload=payload, situation_delta=situation_delta)
    return events, impact, settlement, pending_reaction, None
    situation_delta = public_scene_legacy._clamp(int(payload.get("situation_delta_hint") or 0) + check_bonus(action_result), -20, 20)
    reputation_delta = reputation_delta_from_situation(situation_delta)
    relation_rows: list[dict[str, Any]] = []
    team_rows: list[dict[str, Any]] = []
    role = actor.get("role")
    if isinstance(role, NpcRoleCard):
        before_tag = next((item.relation_tag for item in role.relations if item.target_role_id == save.player_static_data.player_id), "neutral")
        relation_delta = relation_delta_from_result(action_result, situation_delta)
        applied = 0
        if relation_delta != 0:
            applied = public_scene_legacy._apply_actor_relation_delta(
                save,
                role,
                str(actor.get("actor_type") or "npc"),
                relation_delta,
                reputation_score,
            )
        after_tag = next((item.relation_tag for item in role.relations if item.target_role_id == save.player_static_data.player_id), before_tag)
        if applied or before_tag != after_tag:
            relation_rows.append(
                {
                    "role_id": role.role_id,
                    "name": role.name,
                    "before_tag": before_tag,
                    "after_tag": after_tag,
                    "relation_delta": applied,
                    "reaction_text": "",
                }
            )
            events.append(
                world._new_scene_event(
                    "public_turn_relation_update",
                    f"{role.name} 对你的态度发生变化。",
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    metadata={
                        "role_id": role.role_id,
                        "name": role.name,
                        "before_tag": before_tag,
                        "after_tag": after_tag,
                        "relation_delta": applied,
                        "reaction_text": "",
                    },
                )
            )
    if str(actor.get("actor_type") or "npc") == "team":
        member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_id), None)
        if member is not None:
            before_affinity = int(member.affinity)
            before_trust = int(member.trust)
            relation_delta = relation_delta_from_result(action_result, situation_delta)
            if relation_delta:
                member.affinity = public_scene_legacy._clamp(member.affinity + relation_delta * 3, 0, 100)
                member.trust = public_scene_legacy._clamp(member.trust + relation_delta * 2, 0, 100)
            affinity_after = int(member.affinity)
            trust_after = int(member.trust)
            affinity_delta = affinity_after - before_affinity
            trust_delta = trust_after - before_trust
            if affinity_delta or trust_delta:
                team_rows.append(
                    {
                        "member_role_id": actor_id,
                        "name": str(actor.get("name") or ""),
                        "affinity_before": before_affinity,
                        "affinity_after": affinity_after,
                        "affinity_delta": affinity_delta,
                        "trust_before": before_trust,
                        "trust_after": trust_after,
                        "trust_delta": trust_delta,
                        "reaction_text": "",
                    }
                )
                events.append(
                    world._new_scene_event(
                        "public_turn_team_update",
                        f"{actor.get('name')}: 好感{affinity_delta:+d} / 信任{trust_delta:+d}",
                        actor_role_id=actor_id,
                        actor_name=str(actor.get("name") or ""),
                        metadata={
                            "member_role_id": actor_id,
                            "name": str(actor.get("name") or ""),
                            "affinity_before": before_affinity,
                            "affinity_after": affinity_after,
                            "affinity_delta": affinity_delta,
                            "trust_before": before_trust,
                            "trust_after": trust_after,
                            "trust_delta": trust_delta,
                            "reaction_text": "",
                        },
                    )
                )
    resolution_text = (action_result.narrative if action_result is not None else "") or f"{actor.get('name')} 把动作落到了眼前局面上。"
    resolution_text = _last_nonempty_line(resolution_text)
    if not resolution_text:
        resolution_text = _default_gm_resolution_summary(
            str(actor.get("name") or "在场角色"),
            str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
            situation_delta,
        )
    resolution_event = world._new_scene_event(
        "public_turn_actor_resolution",
        resolution_text,
        actor_role_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        metadata={
            "actor_type": str(actor.get("actor_type") or "npc"),
            "round_id": round_state.round_id,
            "phase": round_state.phase.value,
            "situation_delta": situation_delta,
            "reputation_delta": reputation_delta,
            "check_outcome": ("none" if action_result is None else ("success" if action_result.success else "failure")),
        },
    )
    events.append(resolution_event)
    impact = build_impact(
        actor_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        action_result=action_result,
        situation_delta=situation_delta,
        zone_reputation_delta=reputation_delta,
        relation_deltas=relation_rows,
        team_affinity_deltas=team_rows,
        environment_shift=(2 if any(token in str(payload.get("specific_threat") or "") for token in _DESTRUCTIVE_TOKENS) else 0),
        scene_events=events,
    )
    settlement = build_settlement_entry(
        round_state=round_state,
        actor_id=actor_id,
        actor_name=str(actor.get("name") or ""),
        actor_type=str(actor.get("actor_type") or "npc"),
        action_summary=str(payload.get("action_narration") or payload.get("visible_intent") or action_content),
        speech_text=str(payload.get("speech_line") or payload.get("speech_summary") or ""),
        action_result=action_result,
        impact=impact,
        gm_resolution_summary=resolution_text,
        opposed_target_name=(action_result.target_name if action_result is not None else None),
    )
    pending_reaction = _build_reaction_for_actor(actor, payload=payload, situation_delta=situation_delta)
    return events, impact, settlement, pending_reaction


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
                "target_label": prompt.target_actor_name,
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
        "specific_threat": prompt.stakes_summary,
        "situation_delta_hint": _situation_hint_from_text(
            "\n".join(part for part in (prompt.source_action_summary, target_action_summary) if part.strip())
        ),
    }
    events, impact, settlement, _ = _finalize_ai_actor_turn(
        save,
        actor=actor,
        payload=payload,
        round_state=round_state,
        action_content=action_content,
        action_result=action_result,
        reputation_score=reputation_score,
        base_events=base_events,
        opposed_target_name=prompt.target_actor_name,
        opposed_target_action=target_action_summary,
        opposed_target_speech=target_speech_text,
    )
    return events, impact, settlement, action_result


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
        f"本轮结束后，现场局势变化 {total_situation_delta:+d}，环境风险为 {risk.value}。"
        if impacts
        else "本轮结束后，场面暂时没有新的连锁变化。"
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
                actor_name="公开回合",
            )
        )
    _, reputation_event = apply_round_reputation(
        save,
        session_id=session_id,
        delta=total_reputation_delta,
        reason="公开回合结算",
        actor_name="公开回合",
    )
    if reputation_event is not None:
        events.append(reputation_event)
    if risk != round_state.environment_risk_level or total_environment_shift:
        events.append(
            world._new_scene_event(
                "public_turn_environment_update",
                f"环境风险由 {round_state.environment_risk_level.value} 变为 {risk.value}。",
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
