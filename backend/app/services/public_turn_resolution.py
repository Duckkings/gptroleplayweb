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
    PublicTurnImpact,
    PublicTurnRound,
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
    visible_actor_rows,
)
from app.services.public_turn_effects import (
    apply_player_team_reactions,
    apply_round_reputation,
    build_impact,
    check_bonus,
    next_environment_risk,
    relation_delta_from_result,
    reputation_delta_from_situation,
    team_reaction_rows,
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
    config: ChatConfig | None,
) -> ActionCheckResponse | None:
    if not _requires_action_check(text):
        return None
    return world.action_check(
        ActionCheckRequest(
            session_id=session_id,
            actor_role_id=actor_id,
            action_type=_action_type_for_text(text),  # type: ignore[arg-type]
            action_prompt=text,
            allow_backend_roll=True,
            resolution_context="embedded",
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
    config: ChatConfig | None,
) -> tuple[str, list[SceneEvent], PublicTurnImpact]:
    display_text = _submission_display_text(action_text, speech_text)
    action_result = _player_action_check(
        save,
        session_id=session_id,
        actor_id=save.player_static_data.player_id,
        text=display_text,
        config=config,
    )
    situation_delta = max(-20, min(20, _situation_hint_from_text(display_text) + check_bonus(action_result)))
    narration = display_text
    if action_result is not None:
        narration = action_result.narrative or display_text
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
    if narration:
        events.append(
            world._new_scene_event(
                "public_turn_actor_resolution",
                narration,
                actor_role_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                metadata={
                    "actor_type": "player",
                    "round_id": round_state.round_id,
                    "phase": round_state.phase.value,
                    "check_outcome": ("none" if action_result is None else ("success" if action_result.success else "failure")),
                },
            )
        )
    reactions, reaction_events = apply_player_team_reactions(
        save,
        session_id=session_id,
        player_text=display_text,
        summary=narration,
    )
    events.extend(reaction_events)
    impact = build_impact(
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        action_summary=display_text,
        action_result=action_result,
        situation_delta=situation_delta,
        zone_reputation_delta=reputation_delta_from_situation(situation_delta),
        team_affinity_deltas=team_reaction_rows(reactions),
        environment_shift=(2 if any(token in display_text.lower() for token in _DESTRUCTIVE_TOKENS) else 0),
        scene_events=events,
    )
    return narration, events, impact


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


def resolve_ai_round(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    gm_summary: str,
    round_state: PublicTurnRound,
    exclude_actor_ids: set[str],
    config: ChatConfig | None,
) -> tuple[str, list[SceneEvent], list[PublicTurnImpact], PlayerReactionCheck | None]:
    intent = world._parse_player_intent(player_text)
    display_text = str(intent.get("display_text") or player_text).strip()
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    audience_context = public_scene_runtime.build_public_audience_context(save, intent)
    scene_context = world._build_scene_context_payload(save, player_text=player_text, gm_narration=gm_summary, recent_turn_count=4)
    candidates = visible_actor_rows(
        save,
        player_text=display_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=[str(item) for item in list(intent.get("incoming_target_candidates") or [])],
        config=config,
    )
    active_encounter = public_scene_legacy._active_encounter_for_current_sub_zone(save)
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = getattr(zone_metric, "reputation_score", 50)
    scene_events: list[SceneEvent] = []
    impacts: list[PublicTurnImpact] = []
    result_rows: list[dict[str, object]] = []
    reputation_delta_total = 0
    total_situation_delta = 0
    pending_reaction: PlayerReactionCheck | None = None
    seen_actor_ids = set(exclude_actor_ids)
    for actor in candidates:
        actor_id = str(actor.get("actor_id") or "")
        if not actor_id or actor_id in seen_actor_ids:
            continue
        seen_actor_ids.add(actor_id)
        payload = public_scene_runtime._ai_actor_action(
            save,
            actor,
            player_text=display_text,
            gm_summary=gm_summary,
            scene_context=scene_context,
            incoming_interaction=None,
            config=config,
        ) or public_scene_runtime._fallback_actor_action(
            save,
            actor,
            player_text=display_text,
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
        scene_events.append(action_event)
        public_scene_legacy._append_actor_memory(
            save,
            actor,
            display_text=display_text,
            action_line=action_content,
            priority_reason=str(actor.get("priority_reason") or ""),
        )
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
        situation_delta = public_scene_legacy._clamp(int(payload.get("situation_delta_hint") or 0) + check_bonus(action_result), -20, 20)
        total_situation_delta += situation_delta
        reputation_delta = reputation_delta_from_situation(situation_delta)
        reputation_delta_total += reputation_delta
        role = actor.get("role")
        relation_rows: list[dict[str, Any]] = []
        team_rows: list[dict[str, Any]] = []
        if isinstance(role, NpcRoleCard):
            relation_delta = relation_delta_from_result(action_result, situation_delta)
            applied = 0
            if relation_delta != 0:
                applied = public_scene_legacy._apply_actor_relation_delta(save, role, str(actor.get("actor_type") or "npc"), relation_delta, reputation_score)
            if applied:
                relation_rows.append({"target_role_id": save.player_static_data.player_id, "delta": applied})
                scene_events.append(
                    world._new_scene_event(
                        "public_turn_relation_update",
                        f"{role.name} 对你的态度发生变化。",
                        actor_role_id=role.role_id,
                        actor_name=role.name,
                        metadata={"delta": applied, "target_role_id": save.player_static_data.player_id},
                    )
                )
        if str(actor.get("actor_type") or "npc") == "team":
            member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_id), None)
            if member is not None:
                before_affinity = int(member.affinity)
                before_trust = int(member.trust)
                # A team member's own success/failure should also shift affinity/trust slightly.
                relation_delta = relation_delta_from_result(action_result, situation_delta)
                if relation_delta:
                    member.affinity = public_scene_legacy._clamp(member.affinity + relation_delta * 3, 0, 100)
                    member.trust = public_scene_legacy._clamp(member.trust + relation_delta * 2, 0, 100)
                affinity_delta = int(member.affinity) - before_affinity
                trust_delta = int(member.trust) - before_trust
                if affinity_delta or trust_delta:
                    team_rows.append(
                        {
                            "member_role_id": actor_id,
                            "member_name": str(actor.get("name") or ""),
                            "affinity_delta": affinity_delta,
                            "trust_delta": trust_delta,
                        }
                    )
                    scene_events.append(
                        world._new_scene_event(
                            "public_turn_team_update",
                            f"{actor.get('name')}: 好感{affinity_delta:+d} / 信任{trust_delta:+d}",
                            actor_role_id=actor_id,
                            actor_name=str(actor.get("name") or ""),
                            metadata={"affinity_delta": affinity_delta, "trust_delta": trust_delta},
                        )
                    )
        resolution_text = (
            (action_result.narrative if action_result is not None else "")
            or f"{actor.get('name')} 把动作落到了眼前局面上。"
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
            },
        )
        scene_events.append(resolution_event)
        impacts.append(
            build_impact(
                actor_id=actor_id,
                actor_name=str(actor.get("name") or ""),
                action_summary=action_content,
                action_result=action_result,
                situation_delta=situation_delta,
                zone_reputation_delta=reputation_delta,
                relation_deltas=relation_rows,
                team_affinity_deltas=team_rows,
                environment_shift=(2 if any(token in str(payload.get("specific_threat") or "") for token in _DESTRUCTIVE_TOKENS) else 0),
                scene_events=[action_event, resolution_event],
            )
        )
        result_rows.append(
            {
                "actor_name": str(actor.get("name") or ""),
                "resolution_line": resolution_text[:220],
                "situation_delta": situation_delta,
            }
        )
        pending_reaction = _build_reaction_for_actor(actor, payload=payload, situation_delta=situation_delta)
        if pending_reaction is not None:
            break
    narration = "\n".join(str(row.get("resolution_line") or "") for row in result_rows if str(row.get("resolution_line") or "").strip()).strip()
    if not narration:
        narration = "公开回合中的其他参与者暂时没有进一步动作。"
    if pending_reaction is None:
        if active_encounter is not None and total_situation_delta:
            scene_events.extend(
                apply_active_encounter_situation_delta_in_save(
                    save,
                    session_id=session_id,
                    delta=total_situation_delta,
                    summary=narration,
                    actor_name="公开回合",
                )
            )
        _, rep_event = apply_round_reputation(
            save,
            session_id=session_id,
            delta=reputation_delta_total,
            reason="公开回合结算",
            actor_name="公开回合",
        )
        if rep_event is not None:
            scene_events.append(rep_event)
    return narration, scene_events, impacts, pending_reaction


def resolve_situation(
    save: SaveFile,
    *,
    session_id: str,
    round_state: PublicTurnRound,
    impacts: list[PublicTurnImpact],
) -> tuple[str, list[SceneEvent], EnvironmentRiskLevel]:
    total_environment_shift = sum(int(item.environment_shift or 0) for item in impacts)
    total_situation_delta = sum(int(item.situation_delta or 0) for item in impacts)
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
    return narration, events, risk
