from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    AreaDiscoverInteractionsRequest,
    AreaExecuteInteractionRequest,
    AreaMoveSubZoneRequest,
    ChatRequest,
    EncounterActRequest,
    InventoryEquipRequest,
    InventoryConsumeRequest,
    InventoryGrantRequest,
    InventoryInteractRequest,
    InventoryUnequipRequest,
    Message,
    MoveRequest,
    InventoryItem,
    InventoryOwnerRef,
    PlayerBuffAddRequest,
    PlayerBuffRemoveRequest,
    PlayerEquipRequest,
    PlayerItemAddRequest,
    PlayerItemRemoveRequest,
    PlayerSkillSetRequest,
    PlayerSpellSetRequest,
    PlayerSpellSlotAdjustRequest,
    PlayerStaminaAdjustRequest,
    TeamChatRequest,
    PlayerUnequipRequest,
    RoleBuff,
    RoleRelationSetRequest,
    TemplateLibraryDefinitionsRequest,
    TeamDebugGenerateRequest,
    TeamInviteRequest,
    TeamLeaveRequest,
    ToolEvent,
    Usage,
)
from app.services.actor_capability_service import build_role_capability_response
from app.services.ai_adapter import build_completion_options, create_async_client
from app.services.actor_resource_service import adjust_actor_resource_in_profile
from app.services.actor_resource_service import resolve_actor_profile
from app.services.template_library_query_service import query_template_library_definitions
from app.services.world_service import (
    _active_encounter_for_current_sub_zone,
    _build_scene_context_payload,
    _new_scene_event,
    _parse_player_intent,
    _record_sub_zone_chat_turn,
    _visible_public_roles,
    add_player_buff,
    add_player_item,
    add_player_skill,
    add_player_spell,
    advance_public_scene_in_save,
    apply_speech_time,
    build_main_turn_context_json,
    consume_spell_slots,
    consume_stamina,
    discover_interactions,
    equip_player_item,
    execute_interaction,
    generate_zones_for_chat,
    get_area_current,
    get_current_save,
    get_game_logs,
    get_scene_interactables,
    get_template_library_status_payload,
    recover_spell_slots,
    recover_stamina,
    remove_player_buff,
    remove_player_item,
    remove_player_skill,
    remove_player_spell,
    set_role_relation,
    inventory_equip,
    inventory_consume,
    inventory_grant,
    inventory_interact,
    inventory_unequip,
    spawn_persistent_scene_npc_in_save,
    unequip_player_item,
    move_to_sub_zone,
    move_to_zone,
    save_current,
)
from app.services.encounter_service import act_on_encounter, advance_active_encounter_from_main_chat_in_save, get_encounter_debug_overview
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    build_npc_knowledge_snapshot,
    collect_consistency_issues,
    reconcile_consistency,
)
from app.services.team_service import generate_debug_teammate, get_team_state, invite_npc_to_team, leave_npc_from_team, team_chat
from app.services.death_service import death_service

logger = logging.getLogger("roleplay.tools")


class MissingAPIKeyError(RuntimeError):
    pass


def _build_messages(payload: ChatRequest) -> list[dict[str, Any]]:
    last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
    context_json = "{}"
    if last_user is not None:
        try:
            save = get_current_save(default_session_id=payload.session_id)
            if save.session_id != payload.session_id:
                save.session_id = payload.session_id
                save_current(save)
            context_json = build_main_turn_context_json(save, last_user.content, recent_turn_count=8)
        except Exception:
            context_json = "{}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": payload.config.gm_prompt},
        {
            "role": "system",
            "content": prompt_table.get_text(
                PromptKeys.CHAT_NARRATION_RULE,
                "Narration rule: as GM, only describe environment, objects, situation changes, system results, and encounter state progression. Do not directly speak as visible NPCs or teammates. If a visible NPC should respond, leave that response for the scene event system.",
            ),
        },
        {
            "role": "system",
            "content": prompt_table.get_text(
                "chat.tool_rule",
                "Tool rule: when user asks to generate zones, move to zones, or confirm player state, you must call the proper tool first, then narrate based on tool results.",
            ),
        },
        {
            "role": "system",
            "content": prompt_table.get_text(
                PromptKeys.CHAT_CONTEXT_RULE,
                "Context rule: prefer the current structured game state, scene state, recent dialogue history, and active encounter state. Do not ignore current conversation state. Use tools to fetch fresh facts when needed.",
            ),
        },
        {
            "role": "system",
            "content": prompt_table.get_text(
                "chat.map_awareness_rule",
                "Map awareness rule: if movement target is ambiguous or you need available destinations, call get_map_index first to fetch current zone index.",
            ),
        },
        {
            "role": "system",
            "content": prompt_table.get_text(
                "chat.story_snapshot_rule",
                "Story consistency rule: when you need current world facts about quests, fate, encounters, or legal NPCs, call get_story_snapshot or get_player_state first.",
            ),
        },
        {
            "role": "system",
            "content": prompt_table.render(
                PromptKeys.CHAT_TURN_CONTEXT_USER,
                "当前结构化主回合上下文如下，请把它当作本轮叙事事实基础，不要忽略并行遭遇与地区最近回合。\n$main_turn_context_json",
                main_turn_context_json=context_json,
            ),
        },
    ]
    if last_user is not None:
        messages.append({"role": "user", "content": last_user.content})
    return messages


def _build_usage(resp_usage: object | None) -> Usage:
    if resp_usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(resp_usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(resp_usage, "completion_tokens", 0) or 0,
    )


def _sum_usage(base: Usage, extra: Usage) -> Usage:
    return Usage(
        input_tokens=base.input_tokens + extra.input_tokens,
        output_tokens=base.output_tokens + extra.output_tokens,
    )


def _client(payload: ChatRequest) -> AsyncOpenAI:
    api_key = payload.config.api_key
    if not api_key:
        raise MissingAPIKeyError("api_key is not set")
    return create_async_client(payload.config, client_cls=AsyncOpenAI)


def _contains_any_token(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens if token)


def _find_zone_target(save, text: str):
    clean = (text or "").strip()
    if not clean:
        return None
    for zone in save.map_snapshot.zones:
        if zone.zone_id and zone.zone_id in clean:
            return zone
        if zone.name and zone.name in clean:
            return zone
    return None


def _find_sub_zone_target(save, text: str):
    clean = (text or "").strip()
    if not clean:
        return None
    for sub_zone in save.area_snapshot.sub_zones:
        if sub_zone.sub_zone_id and sub_zone.sub_zone_id in clean:
            return sub_zone
        if sub_zone.name and sub_zone.name in clean:
            return sub_zone
    return None


def _find_named_role(save, text: str, *, team_only: bool = False, visible_only: bool = False):
    clean = (text or "").strip()
    if not clean:
        return None
    allowed_ids: set[str] | None = None
    if team_only:
        allowed_ids = {item.role_id for item in save.team_state.members}
    elif visible_only:
        allowed_ids = {item.role_id for item in _visible_public_roles(save)}
    for role in save.role_pool:
        if allowed_ids is not None and role.role_id not in allowed_ids:
            continue
        if role.role_id and role.role_id in clean:
            return role
        if role.name and role.name in clean:
            return role
    return None


def _find_addressed_scene_actor(save, addressed_role_name: str):
    clean = (addressed_role_name or "").strip()
    if not clean:
        return None
    for role in [*_visible_public_roles(save), *[item for item in save.role_pool if item.role_id in {member.role_id for member in save.team_state.members}]]:
        if role.name and clean in role.name:
            return {"actor_id": role.role_id, "name": role.name, "actor_type": ("team" if role.role_id in {member.role_id for member in save.team_state.members} else "npc")}
    active_encounter = _active_encounter_for_current_sub_zone(save)
    if active_encounter is None:
        return None
    for temp_npc in getattr(active_encounter, "temporary_npcs", []) or []:
        if temp_npc.name and clean in temp_npc.name:
            return {"actor_id": temp_npc.encounter_npc_id, "name": temp_npc.name, "actor_type": "encounter_temp_npc"}
    return None


def _find_inventory_item(items: list[InventoryItem], text: str):
    clean = (text or "").strip()
    if not clean:
        return None
    for item in items:
        if item.item_id and item.item_id in clean:
            return item
        if item.name and item.name in clean:
            return item
    return None


def _encounter_scene_events(encounter, *, reply: str, include_situation: bool = True) -> list[Any]:
    events: list[Any] = []
    if include_situation:
        events.append(
            _new_scene_event(
                "encounter_situation_update",
                f"局势值变为 {encounter.situation_value}/100，趋势为 {encounter.situation_trend}。",
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "situation_value": encounter.situation_value,
                },
            )
        )
    events.append(
        _new_scene_event(
            "encounter_resolution" if encounter.status == "resolved" else "encounter_progress",
            reply,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "status": encounter.status,
            },
        )
    )
    return events


def route_main_turn_intent(session_id: str, parsed_intent: dict[str, object], config) -> dict[str, Any]:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    action_text = str(parsed_intent.get("action_text") or "").strip()
    speech_text = str(parsed_intent.get("speech_text") or "").strip()
    display_text = str(parsed_intent.get("display_text") or "").strip()
    addressed_role_name = str(parsed_intent.get("addressed_role_name") or "").strip()
    merged = "\n".join(part for part in [action_text, speech_text, display_text] if part).strip()
    active_encounter = _active_encounter_for_current_sub_zone(save)
    tool_events: list[ToolEvent] = []

    if bool(parsed_intent.get("passive_turn")):
        tool_events.append(ToolEvent(tool_name="route_main_turn_intent", ok=True, summary="passive_turn routed"))
        return {
            "handled": True,
            "reply": Message(role="assistant", content="你暂时按住动作，让当前局势自行推进一轮。"),
            "tool_events": tool_events,
            "scene_events": [],
            "time_spent_min": 1,
            "skip_encounter_main_chat_advance": False,
        }

    zone_tokens = ["前往", "去", "移动到", "进入", "赶去", "travel", "move", "go to"]
    if _contains_any_token(merged, zone_tokens):
        sub_zone = _find_sub_zone_target(save, merged)
        if sub_zone is not None and sub_zone.sub_zone_id != save.area_snapshot.current_sub_zone_id:
            moved = move_to_sub_zone(AreaMoveSubZoneRequest(session_id=session_id, to_sub_zone_id=sub_zone.sub_zone_id, config=config))
            tool_events.append(ToolEvent(tool_name="move_to_sub_zone", ok=True, summary=f"moved to {sub_zone.sub_zone_id}", payload={"duration_min": moved.duration_min}))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=moved.movement_feedback),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": moved.duration_min,
                "skip_encounter_main_chat_advance": False,
            }
        zone = _find_zone_target(save, merged)
        if zone is not None:
            from_zone_id = (
                (save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None)
                or (save.map_snapshot.player_position.zone_id if save.map_snapshot.player_position else None)
                or save.area_snapshot.current_zone_id
                or zone.zone_id
            )
            moved = move_to_zone(
                MoveRequest(
                    session_id=session_id,
                    from_zone_id=from_zone_id,
                    to_zone_id=zone.zone_id,
                    player_name=save.player_static_data.name,
                )
            )
            tool_events.append(ToolEvent(tool_name="move_to_zone", ok=True, summary=f"moved to {zone.zone_id}", payload={"duration_min": moved.duration_min}))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=moved.movement_log.summary),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": moved.duration_min,
                "skip_encounter_main_chat_advance": False,
            }

    if active_encounter is not None:
        if active_encounter.player_presence == "engaged" and merged:
            result = act_on_encounter(
                active_encounter.encounter_id,
                EncounterActRequest(
                    session_id=session_id,
                    player_prompt=display_text or merged,
                    config=config,
                ),
            )
            tool_events.append(ToolEvent(tool_name="encounter_act", ok=True, summary=f"encounter {result.status}", payload={"time_spent_min": result.time_spent_min}))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.reply),
                "tool_events": tool_events,
                "scene_events": _encounter_scene_events(result.encounter, reply=result.reply),
                "time_spent_min": result.time_spent_min,
                "skip_encounter_main_chat_advance": True,
            }

    if _contains_any_token(merged, ["加入队伍", "入队", "跟我走", "同行", "invite", "join team"]):
        role = _find_named_role(save, merged, visible_only=True) or _find_named_role(save, merged)
        if role is not None:
            result = invite_npc_to_team(TeamInviteRequest(session_id=session_id, npc_role_id=role.role_id, player_prompt=merged, config=config))
            tool_events.append(ToolEvent(tool_name="team_invite_npc", ok=result.accepted, summary=result.chat_feedback[:80] or "invite attempted"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.chat_feedback or f"{role.name} 对你的邀请做出了回应。"),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": 1,
                "skip_encounter_main_chat_advance": False,
            }
    if _contains_any_token(merged, ["离队", "退出队伍", "走吧", "leave team", "dismiss"]):
        role = _find_named_role(save, merged, team_only=True)
        if role is not None:
            result = leave_npc_from_team(TeamLeaveRequest(session_id=session_id, npc_role_id=role.role_id, reason=merged, config=config))
            tool_events.append(ToolEvent(tool_name="team_remove_npc", ok=True, summary=result.chat_feedback[:80] or "member removed"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.chat_feedback or f"{role.name} 离开了队伍。"),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": 1,
                "skip_encounter_main_chat_advance": False,
            }

    inventory_tokens = ["装备", "穿上", "拿上", "equip", "卸下", "脱下", "unequip", "查看", "检查", "inspect", "使用", "用掉", "use"]
    if _contains_any_token(merged, inventory_tokens):
        owner = InventoryOwnerRef(owner_type="player")
        owner_role = _find_named_role(save, merged, team_only=True)
        owner_items = save.player_static_data.dnd5e_sheet.backpack.items
        if owner_role is not None:
            owner = InventoryOwnerRef(owner_type="role", role_id=owner_role.role_id)
            owner_items = owner_role.profile.dnd5e_sheet.backpack.items
        item = _find_inventory_item(owner_items, merged)
        if item is not None:
            if _contains_any_token(merged, ["装备", "穿上", "拿上", "equip"]):
                slot = "armor" if item.slot_type == "armor" or _contains_any_token(merged, ["护甲", "盔甲", "armor"]) else "weapon"
                result = inventory_equip(InventoryEquipRequest(session_id=session_id, owner=owner, item_id=item.item_id, slot=slot))  # type: ignore[arg-type]
                tool_events.append(ToolEvent(tool_name="inventory_mutate", ok=True, summary=result.message[:80] or "equip ok"))
                return {
                    "handled": True,
                    "reply": Message(role="assistant", content=result.message or f"已装备 {item.name}。"),
                    "tool_events": tool_events,
                    "scene_events": [],
                    "time_spent_min": 1,
                    "skip_encounter_main_chat_advance": False,
                }
            if _contains_any_token(merged, ["卸下", "脱下", "unequip"]):
                slot = "armor" if item.slot_type == "armor" or _contains_any_token(merged, ["护甲", "盔甲", "armor"]) else "weapon"
                result = inventory_unequip(InventoryUnequipRequest(session_id=session_id, owner=owner, slot=slot))  # type: ignore[arg-type]
                tool_events.append(ToolEvent(tool_name="inventory_mutate", ok=True, summary=result.message[:80] or "unequip ok"))
                return {
                    "handled": True,
                    "reply": Message(role="assistant", content=result.message or f"已卸下 {item.name}。"),
                    "tool_events": tool_events,
                    "scene_events": [],
                    "time_spent_min": 1,
                    "skip_encounter_main_chat_advance": False,
                }
            mode = "use" if _contains_any_token(merged, ["使用", "用掉", "use"]) else "inspect"
            result = inventory_interact(
                InventoryInteractRequest(
                    session_id=session_id,
                    owner=owner,
                    item_id=item.item_id,
                    mode=mode,  # type: ignore[arg-type]
                    prompt=merged,
                    config=config,
                )
            )
            tool_events.append(ToolEvent(tool_name="inventory_interact", ok=True, summary=result.reply[:80] or "item interaction ok"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.reply),
                "tool_events": tool_events,
                "scene_events": list(result.scene_events or []),
                "time_spent_min": result.time_spent_min,
                "skip_encounter_main_chat_advance": False,
            }

    addressed_actor = _find_addressed_scene_actor(save, addressed_role_name)
    if addressed_actor is not None:
        tool_events.append(
            ToolEvent(
                tool_name="route_main_turn_target_npc",
                ok=True,
                summary=f"public scene target={addressed_actor['actor_id']}",
            )
        )
    else:
        visible_role = _find_named_role(save, merged, visible_only=True)
        if visible_role is not None:
            tool_events.append(ToolEvent(tool_name="route_main_turn_target_npc", ok=True, summary=f"public scene target={visible_role.role_id}"))
    return {
        "handled": False,
        "reply": None,
        "tool_events": tool_events,
        "scene_events": [],
        "time_spent_min": 0,
        "skip_encounter_main_chat_advance": False,
    }


def _tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "generate_zone",
                "description": "Generate 1-3 new map zones and persist them to current save.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "world_prompt": {
                            "type": "string",
                            "description": "Constraint prompt for world region generation.",
                        },
                        "count": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                    },
                    "required": ["world_prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_to_zone",
                "description": "Move player to target zone. Prefer to_zone_id, can fallback to to_zone_name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to_zone_id": {"type": "string"},
                        "to_zone_name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_player_state",
                "description": "Return player static/runtime/map/world/quest/fate/encounter state as JSON for confirmation.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_story_snapshot",
                "description": "Return the unified structured world snapshot including revisions, current area, available NPCs, active quests, fate phase, and recent encounters.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_quest_state",
                "description": "Return current quest state, pending offers, and tracked quest.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_fate_state",
                "description": "Return the current fate line and phase state.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_area_reputation",
                "description": "Return current or specified sub-zone reputation score and band.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_zone_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_role_drives",
                "description": "Return desire and story beat summaries for one role, the team, or the current sub-zone.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "string"},
                        "scope": {"type": "string", "enum": ["role", "team", "current_sub_zone"]},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_public_scene_state",
                "description": "Return current public scene state including reputation, visible roles, surfaced drives, active encounter, and candidate actors.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_entity_index",
                "description": "Return legal entity ids for zones, sub-zones, NPCs, quests, encounters, and fate phases. Scope can be global/current_zone/current_sub_zone.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["global", "current_zone", "current_sub_zone"]},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_consistency_status",
                "description": "Return current world revision information and detected consistency issues.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_encounters",
                "description": "Return the current active or escaped encounter, queued encounters, and encounter summary.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_consistency_check",
                "description": "Run one consistency reconciliation pass and return whether stale content was invalidated.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_npc_knowledge",
                "description": "Return the knowledge boundary snapshot for one NPC. Use when asking what an NPC should or should not know.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "npc_role_id": {"type": "string"},
                    },
                    "required": ["npc_role_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_team_state",
                "description": "Return the current team state, active members, affinity, trust, and recent team reactions.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_invite_npc",
                "description": "Invite one NPC into the current team. Use only with a legal npc_role_id from get_story_snapshot/get_entity_index/role_pool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "npc_role_id": {"type": "string"},
                        "player_prompt": {"type": "string"},
                    },
                    "required": ["npc_role_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_remove_npc",
                "description": "Remove one NPC from the current team.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "npc_role_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["npc_role_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_role_inventory",
                "description": "Return one NPC role inventory/backpack and equipment information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "string"},
                    },
                    "required": ["role_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inventory_mutate",
                "description": "Equip or unequip one backpack item for player or one teammate role.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner_type": {"type": "string", "enum": ["player", "role"]},
                        "role_id": {"type": "string"},
                        "mode": {"type": "string", "enum": ["equip", "unequip"]},
                        "item_id": {"type": "string"},
                        "slot": {"type": "string", "enum": ["weapon", "armor"]},
                    },
                    "required": ["owner_type", "mode", "slot"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inventory_interact",
                "description": "Inspect or use one backpack item for player or one teammate role.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner_type": {"type": "string", "enum": ["player", "role"]},
                        "role_id": {"type": "string"},
                        "item_id": {"type": "string"},
                        "mode": {"type": "string", "enum": ["inspect", "use"]},
                        "prompt": {"type": "string"},
                    },
                    "required": ["owner_type", "item_id", "mode"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inventory_grant_item",
                "description": "Grant one item into player or one role inventory. Use this when AI should hand an item to the player or an NPC.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner_type": {"type": "string", "enum": ["player", "role"]},
                        "role_id": {"type": "string"},
                        "item_id": {"type": "string"},
                        "name": {"type": "string"},
                        "item_type": {"type": "string"},
                        "description": {"type": "string"},
                        "weight": {"type": "number", "minimum": 0},
                        "rarity": {"type": "string"},
                        "value": {"type": "integer", "minimum": 0},
                        "effect": {"type": "string"},
                        "uses_max": {"type": "integer", "minimum": 0},
                        "uses_left": {"type": "integer", "minimum": 0},
                        "cooldown_min": {"type": "integer", "minimum": 0},
                        "bound": {"type": "boolean"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "slot_type": {"type": "string", "enum": ["weapon", "armor", "misc"]},
                        "attack_bonus": {"type": "integer"},
                        "armor_bonus": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["owner_type", "item_id", "name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inventory_consume_item",
                "description": "Consume one player or role inventory item. Use this when an item is spent, used up, or intentionally consumed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner_type": {"type": "string", "enum": ["player", "role"]},
                        "role_id": {"type": "string"},
                        "item_id": {"type": "string"},
                        "amount": {"type": "integer", "minimum": 1},
                        "consume_mode": {"type": "string", "enum": ["auto", "quantity", "uses"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["owner_type", "item_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_chat",
                "description": "Send one player message into current party chat and return each current teammate response.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "player_message": {"type": "string"},
                    },
                    "required": ["player_message"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "team_generate_debug_member",
                "description": "Generate a debug teammate directly into the current team from a short prompt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "encounter_act",
                "description": "Advance the current encounter by one player action step.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "encounter_id": {"type": "string"},
                        "player_prompt": {"type": "string"},
                    },
                    "required": ["encounter_id", "player_prompt"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "quest_track",
                "description": "Set one active quest as the tracked quest.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "quest_id": {"type": "string"},
                    },
                    "required": ["quest_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "quest_evaluate",
                "description": "Evaluate one quest against current world state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "quest_id": {"type": "string"},
                    },
                    "required": ["quest_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_map_index",
                "description": "Return current map zone index (zone_id, name, x, y, z) and player current zone.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_game_logs",
                "description": "Return recent gameplay logs. If limit omitted, use default ai_fetch_limit from settings.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_sub_zone",
                "description": "Return current area snapshot including current zone/sub-zone and world clock.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_scene_interactables",
                "description": "Return current or target sub-zone scene interactables from the formal persistent interactable state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_zone_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_template_library_status",
                "description": "Return current account template-library counts for item/equipment/interactable definitions.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_template_library_definitions",
                "description": "Return spell or war art definition rows from the current template library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["spell", "war_art", "all"]},
                        "definition_ids": {"type": "array", "items": {"type": "string"}},
                        "recommended_class": {"type": "string"},
                        "min_level": {"type": "integer", "minimum": 1, "maximum": 20},
                        "for_role_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_role_capability_snapshot",
                "description": "Return one role capability snapshot, including known spells, war arts, and current resources.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "string"},
                    },
                    "required": ["role_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "actor_adjust_resource",
                "description": "Consume or recover a spell slot or martial point for the player or one role using a spell or war art definition id from the local template library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "actor_kind": {"type": "string", "enum": ["player", "role"]},
                        "actor_role_id": {"type": "string"},
                        "resource_kind": {"type": "string", "enum": ["spell", "war_art", "spell_slot", "martial_point"]},
                        "resource_definition_id": {"type": "string"},
                        "resource_name": {"type": "string"},
                        "mode": {"type": "string", "enum": ["consume", "recover"], "default": "consume"},
                        "level": {"type": "integer", "minimum": 1, "maximum": 9},
                        "amount": {"type": "integer", "minimum": 1, "default": 1},
                    },
                    "required": ["actor_kind", "resource_kind"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "spawn_scene_npc",
                "description": "Create one persistent NPC in the current sub-zone so the role can immediately join the scene.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "speaking_style": {"type": "string"},
                        "agenda": {"type": "string"},
                        "appearance": {"type": "string"},
                        "alignment": {"type": "string"},
                        "likes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_to_sub_zone",
                "description": "Move player to target sub-zone inside area model and advance world clock.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to_sub_zone_id": {"type": "string"},
                    },
                    "required": ["to_sub_zone_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "discover_interactions",
                "description": "Player actively discovers non-key interactions in current/target sub-zone.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_zone_id": {"type": "string"},
                        "intent": {"type": "string"},
                    },
                    "required": ["sub_zone_id", "intent"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_interaction",
                "description": "Execute one formal scene interaction against the persistent scene interactable state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interaction_id": {"type": "string"},
                        "action_kind": {"type": "string"},
                        "actor_kind": {"type": "string", "enum": ["player", "role"]},
                        "actor_role_id": {"type": "string"},
                        "item_instance_id": {"type": "string"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["interaction_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_add_item",
                "description": "Add an inventory item to player backpack.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "name": {"type": "string"},
                        "item_type": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1, "default": 1},
                        "slot_type": {"type": "string", "enum": ["weapon", "armor", "misc"]},
                        "attack_bonus": {"type": "integer"},
                        "armor_bonus": {"type": "integer"},
                    },
                    "required": ["item_id", "name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_equip_item",
                "description": "Equip or unequip player weapon/armor slot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "slot": {"type": "string", "enum": ["weapon", "armor"]},
                        "mode": {"type": "string", "enum": ["equip", "unequip"], "default": "equip"},
                    },
                    "required": ["slot"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_apply_buff",
                "description": "Add or remove a temporary buff on player.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["add", "remove"], "default": "add"},
                        "buff_id": {"type": "string"},
                        "name": {"type": "string"},
                        "duration_min": {"type": "integer", "minimum": 0, "default": 10},
                        "strength_delta": {"type": "integer"},
                        "dexterity_delta": {"type": "integer"},
                        "constitution_delta": {"type": "integer"},
                        "intelligence_delta": {"type": "integer"},
                        "wisdom_delta": {"type": "integer"},
                        "charisma_delta": {"type": "integer"},
                        "ac_delta": {"type": "integer"},
                        "dc_delta": {"type": "integer"},
                    },
                    "required": ["buff_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_adjust_resource",
                "description": "Consume/recover spell slots, martial points, or stamina.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["spell_slot", "martial_point", "stamina"]},
                        "mode": {"type": "string", "enum": ["consume", "recover"], "default": "consume"},
                        "level": {"type": "integer", "minimum": 1, "maximum": 9},
                        "amount": {"type": "integer", "minimum": 1, "default": 1},
                    },
                    "required": ["kind"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "role_set_relation",
                "description": "Set one role relation to another role.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "string"},
                        "target_role_id": {"type": "string"},
                        "relation_tag": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["role_id", "target_role_id", "relation_tag"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_set_trait",
                "description": "Add/remove player skill or spell.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["skill", "spell"]},
                        "mode": {"type": "string", "enum": ["add", "remove"], "default": "add"},
                        "value": {"type": "string"},
                    },
                    "required": ["kind", "value"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_player_death_state",
                "description": "Get player death/dying state including death save progress, death count, and revival weakness status.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stabilize_player",
                "description": "Attempt to stabilize a dying player using medicine check or healing item. Can be used by teammates.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medic_role_id": {"type": "string", "description": "Role ID of the character attempting to stabilize. If omitted, assumes player is using an item."},
                        "method": {"type": "string", "enum": ["medicine_check", "healing_kit", "spell"], "default": "medicine_check"},
                        "item_instance_id": {"type": "string", "description": "Item to use if method is healing_kit"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "player_revive",
                "description": "Revive a dead player at shrine, by item, or by teammate. Applies death penalties and revival weakness buff.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["shrine", "item", "teammate"], "default": "shrine"},
                        "shrine_zone_id": {"type": "string", "description": "Zone ID of shrine for shrine revival"},
                        "item_instance_id": {"type": "string", "description": "Revival item ID for item revival"},
                        "teammate_role_id": {"type": "string", "description": "Teammate role ID for teammate revival"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "spawn_encounter_npc",
                "description": "Spawn a temporary NPC into an active encounter mid-way. Use when narrative introduces a new character that should be tracked as an encounter participant. This will add the NPC to encounter.temporary_npcs and participant_role_ids.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "encounter_id": {
                            "type": "string",
                            "description": "ID of the active encounter",
                        },
                        "name": {
                            "type": "string",
                            "description": "NPC name",
                        },
                        "title": {
                            "type": "string",
                            "description": "NPC title or role (e.g., 'Mysterious Stranger')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of the NPC",
                        },
                        "speaking_style": {
                            "type": "string",
                            "description": "How the NPC speaks (e.g., 'gruff', 'eloquent')",
                        },
                        "agenda": {
                            "type": "string",
                            "description": "NPC's current goal or motivation in this scene",
                        },
                        "role_type": {
                            "type": "string",
                            "enum": ["neutral", "hostile", "friendly"],
                            "description": "NPC's attitude toward the player",
                        },
                    },
                    "required": ["encounter_id", "name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_encounter_participants",
                "description": "Get current encounter participant list including temporary NPCs. Use to check which NPCs are already instantiated in the encounter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "encounter_id": {
                            "type": "string",
                            "description": "ID of the encounter",
                        },
                    },
                    "required": ["encounter_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]


async def _handle_tool_call(payload: ChatRequest, tool_call: Any) -> tuple[dict[str, Any], ToolEvent]:
    tool_name = getattr(getattr(tool_call, "function", None), "name", "")
    arg_text = getattr(getattr(tool_call, "function", None), "arguments", "") or "{}"
    tool_call_id = getattr(tool_call, "id", "")

    if tool_name == "generate_zone":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="generate_zone", ok=False, summary="invalid json args")
            logger.info("tool_call generate_zone failed: invalid_json_args")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False),
                },
                event,
            )

        world_prompt = str(args.get("world_prompt") or "").strip()
        if not world_prompt:
            event = ToolEvent(tool_name="generate_zone", ok=False, summary="world_prompt is required")
            logger.info("tool_call generate_zone failed: world_prompt_required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "world_prompt_required"}, ensure_ascii=False),
                },
                event,
            )

        count = max(1, min(int(args.get("count") or 1), 3))
        try:
            zones = generate_zones_for_chat(
                session_id=payload.session_id,
                config=payload.config,
                world_prompt=world_prompt,
                count=count,
            )
            result = {
                "ok": True,
                "generated": len(zones),
                "zones": [z.model_dump(mode="json") for z in zones],
            }
            event = ToolEvent(
                tool_name="generate_zone",
                ok=True,
                summary=f"generated {len(zones)} zones",
                payload={"generated": len(zones)},
            )
            logger.info("tool_call generate_zone ok: generated=%s", len(zones))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="generate_zone", ok=False, summary=f"generate failed: {exc}")
            logger.info("tool_call generate_zone failed: %s", exc)

        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "move_to_zone":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="move_to_zone", ok=False, summary="invalid json args")
            logger.info("tool_call move_to_zone failed: invalid_json_args")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False),
                },
                event,
            )

        save = get_current_save(default_session_id=payload.session_id)
        to_zone_id = str(args.get("to_zone_id") or "").strip()
        to_zone_name = str(args.get("to_zone_name") or "").strip()
        if not to_zone_id and to_zone_name:
            match = next((z for z in save.map_snapshot.zones if z.name == to_zone_name), None)
            if match is not None:
                to_zone_id = match.zone_id
        if not to_zone_id:
            event = ToolEvent(tool_name="move_to_zone", ok=False, summary="target zone is required")
            logger.info("tool_call move_to_zone failed: target_required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "target_required"}, ensure_ascii=False),
                },
                event,
            )

        from_zone_id = (
            (save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None)
            or (save.map_snapshot.player_position.zone_id if save.map_snapshot.player_position else None)
            or "zone_0_0_0"
        )
        try:
            moved = move_to_zone(
                MoveRequest(
                    session_id=payload.session_id,
                    from_zone_id=from_zone_id,
                    to_zone_id=to_zone_id,
                    player_name=save.player_static_data.name,
                )
            )
            result = {
                "ok": True,
                "new_position": moved.new_position.model_dump(mode="json"),
                "duration_min": moved.duration_min,
                "movement_log": moved.movement_log.model_dump(mode="json"),
            }
            event = ToolEvent(
                tool_name="move_to_zone",
                ok=True,
                summary=f"moved to {moved.new_position.zone_id}",
                payload={"duration_min": moved.duration_min},
            )
            logger.info("tool_call move_to_zone ok: to=%s duration_min=%s", moved.new_position.zone_id, moved.duration_min)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="move_to_zone", ok=False, summary=f"move failed: {exc}")
            logger.info("tool_call move_to_zone failed: %s", exc)
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_player_state":
        save = get_current_save(default_session_id=payload.session_id)
        result = {
            "ok": True,
            "world_state": save.world_state.model_dump(mode="json"),
            "player_static_data": save.player_static_data.model_dump(mode="json"),
            "player_runtime_data": save.player_runtime_data.model_dump(mode="json"),
            "map_snapshot": save.map_snapshot.model_dump(mode="json"),
            "area_snapshot": save.area_snapshot.model_dump(mode="json"),
            "team_state": save.team_state.model_dump(mode="json"),
            "quest_state": save.quest_state.model_dump(mode="json"),
            "encounter_state": save.encounter_state.model_dump(mode="json"),
            "fate_state": save.fate_state.model_dump(mode="json"),
            "role_pool": [item.model_dump(mode="json") for item in save.role_pool],
        }
        event = ToolEvent(tool_name="get_player_state", ok=True, summary="player state returned")
        logger.info("tool_call get_player_state ok")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_story_snapshot":
        save = get_current_save(default_session_id=payload.session_id)
        snapshot = build_global_story_snapshot(save)
        result = {"ok": True, "snapshot": snapshot.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_story_snapshot",
            ok=True,
            summary="story snapshot returned",
            payload={"world_revision": snapshot.world_revision, "map_revision": snapshot.map_revision},
        )
        logger.info("tool_call get_story_snapshot ok")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_quest_state":
        from app.services.quest_service import get_quest_state

        response = get_quest_state(payload.session_id)
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_quest_state",
            ok=True,
            summary=f"quest state returned: {len(response.quest_state.quests)} quests",
            payload={"quest_count": len(response.quest_state.quests)},
        )
        logger.info("tool_call get_quest_state ok")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_fate_state":
        from app.services.fate_service import get_fate_state

        response = get_fate_state(payload.session_id)
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_fate_state",
            ok=True,
            summary="fate state returned",
            payload={"has_current_fate": bool(response.fate_state.current_fate is not None)},
        )
        logger.info("tool_call get_fate_state ok")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_area_reputation":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        from app.services.reputation_service import get_area_reputation

        response = get_area_reputation(payload.session_id, sub_zone_id=str(args.get("sub_zone_id") or "").strip() or None)
        result = {"ok": True, **response.model_dump(mode="json")}
        current_entry = response.current_entry
        event = ToolEvent(
            tool_name="get_area_reputation",
            ok=True,
            summary=(
                f"reputation {current_entry.score}/100 ({current_entry.band})"
                if current_entry is not None
                else "reputation state returned"
            ),
            payload={"has_current_entry": bool(current_entry is not None)},
        )
        logger.info("tool_call get_area_reputation ok")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_role_drives":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        from app.models.schemas import RoleDrivesResponse
        from app.services.roleplay_service import build_role_drive_summaries

        save = get_current_save(default_session_id=payload.session_id)
        role_id = str(args.get("role_id") or "").strip() or None
        scope = str(args.get("scope") or ("role" if role_id else "current_sub_zone")).strip() or "current_sub_zone"
        if scope not in {"role", "team", "current_sub_zone"}:
            scope = "current_sub_zone"
        response = RoleDrivesResponse(
            session_id=payload.session_id,
            scope=scope,  # type: ignore[arg-type]
            items=build_role_drive_summaries(save, scope=("current_sub_zone" if scope == "role" and role_id is None else scope), role_id=role_id),
        )
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_role_drives",
            ok=True,
            summary=f"role drives returned: {len(response.items)} roles",
            payload={"role_count": len(response.items)},
        )
        logger.info("tool_call get_role_drives ok")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_public_scene_state":
        from app.services.public_scene_service import get_public_scene_state

        response = get_public_scene_state(payload.session_id)
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_public_scene_state",
            ok=True,
            summary=f"public scene candidates: {len(response.public_scene_state.candidate_actors)}",
            payload={"candidate_count": len(response.public_scene_state.candidate_actors)},
        )
        logger.info("tool_call get_public_scene_state ok")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_entity_index":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        scope = str(args.get("scope") or "global").strip() or "global"
        save = get_current_save(default_session_id=payload.session_id)
        index = build_entity_index(save, scope=scope)
        result = {"ok": True, **index.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_entity_index",
            ok=True,
            summary=f"entity index returned: {scope}",
            payload={"npc_count": len(index.npc_ids), "zone_count": len(index.zone_ids)},
        )
        logger.info("tool_call get_entity_index ok: scope=%s", scope)
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_consistency_status":
        save = get_current_save(default_session_id=payload.session_id)
        issues = collect_consistency_issues(save)
        result = {
            "ok": True,
            "world_state": save.world_state.model_dump(mode="json"),
            "issue_count": len(issues),
            "issues": [item.model_dump(mode="json") for item in issues],
        }
        event = ToolEvent(
            tool_name="get_consistency_status",
            ok=True,
            summary=f"consistency issues: {len(issues)}",
            payload={"issue_count": len(issues)},
        )
        logger.info("tool_call get_consistency_status ok: issue_count=%s", len(issues))
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_active_encounters":
        response = get_encounter_debug_overview(payload.session_id)
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_active_encounters",
            ok=True,
            summary=response.summary,
            payload={
                "queued_count": len(response.queued_encounters),
                "has_active": response.active_encounter is not None,
            },
        )
        logger.info("tool_call get_active_encounters ok")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "run_consistency_check":
        save = get_current_save(default_session_id=payload.session_id)
        issues, changed = reconcile_consistency(save, session_id=payload.session_id, reason="tool")
        save_current(save)
        result = {
            "ok": True,
            "changed": changed,
            "world_state": save.world_state.model_dump(mode="json"),
            "issue_count": len(issues),
            "issues": [item.model_dump(mode="json") for item in issues],
        }
        event = ToolEvent(
            tool_name="run_consistency_check",
            ok=True,
            summary=f"consistency check finished: changed={changed}",
            payload={"changed": changed, "issue_count": len(issues)},
        )
        logger.info("tool_call run_consistency_check ok: changed=%s issue_count=%s", changed, len(issues))
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_npc_knowledge":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        npc_role_id = str(args.get("npc_role_id") or "").strip()
        if not npc_role_id:
            event = ToolEvent(tool_name="get_npc_knowledge", ok=False, summary="npc_role_id is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "npc_role_id_required"}, ensure_ascii=False),
                },
                event,
            )
        save = get_current_save(default_session_id=payload.session_id)
        try:
            snapshot = build_npc_knowledge_snapshot(save, npc_role_id)
        except KeyError:
            event = ToolEvent(tool_name="get_npc_knowledge", ok=False, summary="role not found")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "role_not_found"}, ensure_ascii=False),
                },
                event,
            )
        result = {"ok": True, "snapshot": snapshot.model_dump(mode="json")}
        event = ToolEvent(tool_name="get_npc_knowledge", ok=True, summary="npc knowledge returned")
        logger.info("tool_call get_npc_knowledge ok: npc_role_id=%s", npc_role_id)
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_team_state":
        response = get_team_state(payload.session_id)
        result = {"ok": True, **response.model_dump(mode="json")}
        event = ToolEvent(
            tool_name="get_team_state",
            ok=True,
            summary=f"team state returned: {len(response.members)} members",
            payload={"member_count": len(response.members)},
        )
        logger.info("tool_call get_team_state ok: member_count=%s", len(response.members))
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "team_invite_npc":
        try:
            args = json.loads(arg_text)
            npc_role_id = str(args.get("npc_role_id") or "").strip()
            player_prompt = str(args.get("player_prompt") or "").strip()
            response = invite_npc_to_team(
                TeamInviteRequest(session_id=payload.session_id, npc_role_id=npc_role_id, player_prompt=player_prompt)
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="team_invite_npc",
                ok=response.accepted,
                summary=("team invite accepted" if response.accepted else "team invite rejected"),
                payload={"npc_role_id": npc_role_id, "accepted": response.accepted},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="team_invite_npc", ok=False, summary=f"team invite failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "team_remove_npc":
        try:
            args = json.loads(arg_text)
            npc_role_id = str(args.get("npc_role_id") or "").strip()
            reason = str(args.get("reason") or "").strip()
            response = leave_npc_from_team(TeamLeaveRequest(session_id=payload.session_id, npc_role_id=npc_role_id, reason=reason))
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="team_remove_npc",
                ok=True,
                summary="team member removed",
                payload={"npc_role_id": npc_role_id},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="team_remove_npc", ok=False, summary=f"team remove failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_role_inventory":
        try:
            args = json.loads(arg_text)
            role_id = str(args.get("role_id") or "").strip()
        except Exception:
            role_id = ""
        if not role_id:
            event = ToolEvent(tool_name="get_role_inventory", ok=False, summary="role_id is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "role_id_required"}, ensure_ascii=False),
                },
                event,
            )
        save = get_current_save(default_session_id=payload.session_id)
        role = next((item for item in save.role_pool if item.role_id == role_id), None)
        if role is None:
            event = ToolEvent(tool_name="get_role_inventory", ok=False, summary="role not found")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "role_not_found"}, ensure_ascii=False),
                },
                event,
            )
        result = {
            "ok": True,
            "role_id": role.role_id,
            "name": role.name,
            "backpack": role.profile.dnd5e_sheet.backpack.model_dump(mode="json"),
            "equipment_slots": role.profile.dnd5e_sheet.equipment_slots.model_dump(mode="json"),
        }
        event = ToolEvent(tool_name="get_role_inventory", ok=True, summary="role inventory returned")
        logger.info("tool_call get_role_inventory ok: role_id=%s", role_id)
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "inventory_mutate":
        try:
            args = json.loads(arg_text)
            owner_type = str(args.get("owner_type") or "player").strip().lower()
            role_id = str(args.get("role_id") or "").strip() or None
            mode = str(args.get("mode") or "equip").strip().lower()
            slot = str(args.get("slot") or "").strip().lower()
            owner = InventoryOwnerRef(owner_type=owner_type, role_id=role_id)
            if mode == "unequip":
                response = inventory_unequip(payload=InventoryUnequipRequest(session_id=payload.session_id, owner=owner, slot=slot))  # type: ignore[arg-type]
            else:
                response = inventory_equip(
                    payload=InventoryEquipRequest(
                        session_id=payload.session_id,
                        owner=owner,
                        item_id=str(args.get("item_id") or "").strip(),
                        slot=slot,  # type: ignore[arg-type]
                    )
                )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(tool_name="inventory_mutate", ok=True, summary=response.message or f"{mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="inventory_mutate", ok=False, summary=f"inventory mutate failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "inventory_interact":
        try:
            args = json.loads(arg_text)
            owner = InventoryOwnerRef(
                owner_type=str(args.get("owner_type") or "player").strip().lower(),
                role_id=(str(args.get("role_id") or "").strip() or None),
            )
            response = inventory_interact(
                payload=InventoryInteractRequest(
                    session_id=payload.session_id,
                    owner=owner,
                    item_id=str(args.get("item_id") or "").strip(),
                    mode=str(args.get("mode") or "inspect").strip().lower(),  # type: ignore[arg-type]
                    prompt=str(args.get("prompt") or "").strip(),
                )
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(tool_name="inventory_interact", ok=True, summary=f"{response.mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="inventory_interact", ok=False, summary=f"inventory interact failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "inventory_grant_item":
        try:
            args = json.loads(arg_text)
            owner = InventoryOwnerRef(
                owner_type=str(args.get("owner_type") or "player").strip().lower(),
                role_id=(str(args.get("role_id") or "").strip() or None),
            )
            item = InventoryItem(
                item_id=str(args.get("item_id") or "").strip(),
                name=str(args.get("name") or "").strip(),
                item_type=str(args.get("item_type") or "misc").strip() or "misc",
                description=str(args.get("description") or "").strip(),
                weight=max(0.0, float(args.get("weight") or 0.0)),
                rarity=str(args.get("rarity") or "common").strip() or "common",
                value=max(0, int(args.get("value") or 0)),
                effect=str(args.get("effect") or "").strip(),
                uses_max=(int(args["uses_max"]) if args.get("uses_max") is not None else None),
                uses_left=(int(args["uses_left"]) if args.get("uses_left") is not None else None),
                cooldown_min=max(0, int(args.get("cooldown_min") or 0)),
                bound=bool(args.get("bound", False)),
                quantity=max(1, int(args.get("quantity") or 1)),
                slot_type=str(args.get("slot_type") or "misc"),  # type: ignore[arg-type]
                attack_bonus=int(args.get("attack_bonus") or 0),
                armor_bonus=int(args.get("armor_bonus") or 0),
            )
            response = inventory_grant(
                InventoryGrantRequest(
                    session_id=payload.session_id,
                    owner=owner,
                    item=item,
                    reason=str(args.get("reason") or "").strip(),
                )
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(tool_name="inventory_grant_item", ok=True, summary=response.message or "inventory grant ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="inventory_grant_item", ok=False, summary=f"inventory grant failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "inventory_consume_item":
        try:
            args = json.loads(arg_text)
            owner = InventoryOwnerRef(
                owner_type=str(args.get("owner_type") or "player").strip().lower(),
                role_id=(str(args.get("role_id") or "").strip() or None),
            )
            response = inventory_consume(
                InventoryConsumeRequest(
                    session_id=payload.session_id,
                    owner=owner,
                    item_id=str(args.get("item_id") or "").strip(),
                    amount=max(1, int(args.get("amount") or 1)),
                    consume_mode=str(args.get("consume_mode") or "auto").strip().lower(),  # type: ignore[arg-type]
                    reason=str(args.get("reason") or "").strip(),
                )
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(tool_name="inventory_consume_item", ok=True, summary=response.message or "inventory consume ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="inventory_consume_item", ok=False, summary=f"inventory consume failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "team_chat":
        try:
            args = json.loads(arg_text)
            player_message = str(args.get("player_message") or "").strip()
            response = team_chat(TeamChatRequest(session_id=payload.session_id, player_message=player_message))
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="team_chat",
                ok=True,
                summary=f"team chat returned: {len(response.replies)} replies",
                payload={"reply_count": len(response.replies)},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="team_chat", ok=False, summary=f"team chat failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "team_generate_debug_member":
        try:
            args = json.loads(arg_text)
            prompt = str(args.get("prompt") or "").strip()
            response = generate_debug_teammate(TeamDebugGenerateRequest(session_id=payload.session_id, prompt=prompt))
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="team_generate_debug_member",
                ok=True,
                summary="debug teammate generated",
                payload={"role_id": response.member.role_id if response.member is not None else ""},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="team_generate_debug_member", ok=False, summary=f"debug teammate failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "encounter_act":
        try:
            args = json.loads(arg_text)
            encounter_id = str(args.get("encounter_id") or "").strip()
            player_prompt = str(args.get("player_prompt") or "").strip()
            response = act_on_encounter(
                encounter_id,
                EncounterActRequest(
                    session_id=payload.session_id,
                    player_prompt=player_prompt,
                ),
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="encounter_act",
                ok=True,
                summary=f"encounter {response.status}",
                payload={"encounter_id": response.encounter_id, "time_spent_min": response.time_spent_min},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="encounter_act", ok=False, summary=f"encounter act failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "quest_track":
        try:
            args = json.loads(arg_text)
            quest_id = str(args.get("quest_id") or "").strip()
            from app.services.quest_service import track_quest

            response = track_quest(payload.session_id, quest_id)
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="quest_track",
                ok=True,
                summary=response.chat_feedback[:80] or "quest tracked",
                payload={"quest_id": response.quest_id},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="quest_track", ok=False, summary=f"quest track failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "quest_evaluate":
        try:
            args = json.loads(arg_text)
            quest_id = str(args.get("quest_id") or "").strip()
            from app.models.schemas import QuestEvaluateRequest
            from app.services.quest_service import evaluate_quest

            response = evaluate_quest(QuestEvaluateRequest(session_id=payload.session_id, quest_id=quest_id, config=payload.config))
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="quest_evaluate",
                ok=True,
                summary=response.chat_feedback[:80] or "quest evaluated",
                payload={"quest_id": response.quest_id, "status": response.status},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="quest_evaluate", ok=False, summary=f"quest evaluate failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_map_index":
        save = get_current_save(default_session_id=payload.session_id)
        current_zone_id = (
            (save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None)
            or (save.map_snapshot.player_position.zone_id if save.map_snapshot.player_position else None)
            or "zone_0_0_0"
        )
        zones = [
            {
                "zone_id": z.zone_id,
                "name": z.name,
                "x": z.x,
                "y": z.y,
                "z": z.z,
            }
            for z in save.map_snapshot.zones
        ]
        result = {
            "ok": True,
            "current_zone_id": current_zone_id,
            "zone_count": len(zones),
            "zones": zones,
        }
        event = ToolEvent(
            tool_name="get_map_index",
            ok=True,
            summary=f"map index returned: {len(zones)} zones",
            payload={"zone_count": len(zones)},
        )
        logger.info("tool_call get_map_index ok: zone_count=%s", len(zones))
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_game_logs":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        raw_limit = args.get("limit")
        safe_limit = None
        if raw_limit is not None:
            safe_limit = max(1, min(int(raw_limit), 100))
        logs = get_game_logs(payload.session_id, limit=safe_limit)
        result = {
            "ok": True,
            "session_id": logs.session_id,
            "count": len(logs.items),
            "items": [item.model_dump(mode="json") for item in logs.items],
        }
        event = ToolEvent(
            tool_name="get_game_logs",
            ok=True,
            summary=f"game logs returned: {len(logs.items)}",
            payload={"count": len(logs.items)},
        )
        logger.info("tool_call get_game_logs ok: count=%s", len(logs.items))
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_current_sub_zone":
        snap = get_area_current(payload.session_id).area_snapshot
        result = {"ok": True, "area_snapshot": snap.model_dump(mode="json")}
        event = ToolEvent(tool_name="get_current_sub_zone", ok=True, summary="area snapshot returned")
        logger.info("tool_call get_current_sub_zone ok")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_scene_interactables":
        try:
            args = json.loads(arg_text) if arg_text else {}
        except Exception:
            args = {}
        sub_zone_id = str(args.get("sub_zone_id") or "").strip() or None
        items = get_scene_interactables(payload.session_id, sub_zone_id=sub_zone_id)
        result = {
            "ok": True,
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }
        event = ToolEvent(tool_name="get_scene_interactables", ok=True, summary=f"scene interactables returned: {len(items)}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_template_library_status":
        status = get_template_library_status_payload(payload.session_id)
        event = ToolEvent(tool_name="get_template_library_status", ok=True, summary="template library status returned")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"ok": True, **status}, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_template_library_definitions":
        try:
            args = json.loads(arg_text) if arg_text else {}
        except Exception:
            args = {}
        save = get_current_save(default_session_id=payload.session_id)
        req = TemplateLibraryDefinitionsRequest(
            session_id=payload.session_id,
            kind=str(args.get("kind") or "all"),  # type: ignore[arg-type]
            definition_ids=[str(item).strip() for item in list(args.get("definition_ids") or []) if str(item).strip()],
            recommended_class=(str(args.get("recommended_class") or "").strip() or None),
            min_level=(int(args.get("min_level")) if args.get("min_level") is not None else None),
            for_role_id=(str(args.get("for_role_id") or "").strip() or None),
            limit=max(1, min(int(args.get("limit") or 20), 200)),
        )
        response = query_template_library_definitions(req, save=save)
        event = ToolEvent(
            tool_name="get_template_library_definitions",
            ok=True,
            summary="template library definitions returned",
            payload={"spell_count": len(response.spell_definitions), "war_art_count": len(response.war_art_definitions)},
        )
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"ok": True, **response.model_dump(mode="json")}, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "get_role_capability_snapshot":
        try:
            args = json.loads(arg_text) if arg_text else {}
        except Exception:
            args = {}
        role_id = str(args.get("role_id") or "").strip()
        if not role_id:
            event = ToolEvent(tool_name="get_role_capability_snapshot", ok=False, summary="role_id is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "role_id_required"}, ensure_ascii=False),
                },
                event,
            )
        save = get_current_save(default_session_id=payload.session_id)
        try:
            response = build_role_capability_response(save, session_id=payload.session_id, role_id=role_id)
        except KeyError:
            event = ToolEvent(tool_name="get_role_capability_snapshot", ok=False, summary="role not found")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "role_not_found"}, ensure_ascii=False),
                },
                event,
            )
        event = ToolEvent(tool_name="get_role_capability_snapshot", ok=True, summary="role capability returned")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"ok": True, **response.model_dump(mode="json")}, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "actor_adjust_resource":
        try:
            args = json.loads(arg_text) if arg_text else {}
        except Exception:
            args = {}
        actor_kind = str(args.get("actor_kind") or "").strip().lower()
        resource_kind = str(args.get("resource_kind") or "").strip().lower()
        mode = str(args.get("mode") or "consume").strip().lower()
        actor_role_id = str(args.get("actor_role_id") or "").strip()
        resource_definition_id = str(args.get("resource_definition_id") or "").strip()
        resource_name = str(args.get("resource_name") or "").strip()
        if actor_kind not in {"player", "role"}:
            event = ToolEvent(tool_name="actor_adjust_resource", ok=False, summary="invalid actor_kind")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "invalid_actor_kind"}, ensure_ascii=False),
                },
                event,
            )
        if resource_kind not in {"spell", "war_art", "spell_slot", "martial_point"}:
            event = ToolEvent(tool_name="actor_adjust_resource", ok=False, summary="invalid resource_kind")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "invalid_resource_kind"}, ensure_ascii=False),
                },
                event,
            )
        save = get_current_save(default_session_id=payload.session_id)
        try:
            profile, _ = resolve_actor_profile(save, owner_type=actor_kind, role_id=(actor_role_id or None))
        except KeyError:
            event = ToolEvent(tool_name="actor_adjust_resource", ok=False, summary="actor not found")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "actor_not_found"}, ensure_ascii=False),
                },
                event,
            )
        level_value = args.get("level")
        status = adjust_actor_resource_in_profile(
            profile,
            resource_kind=resource_kind,
            mode=mode,
            amount=max(1, int(args.get("amount") or 1)),
            level=(int(level_value) if level_value is not None else None),
            resource_definition_id=resource_definition_id,
            resource_name=resource_name,
        )
        save.session_id = payload.session_id
        save_current(save)
        ok = status.check_status == "passed"
        event = ToolEvent(
            tool_name="actor_adjust_resource",
            ok=ok,
            summary=f"{actor_kind} {resource_kind} {mode} {'ok' if ok else 'failed'}",
            payload={"resource_kind": resource_kind, "resolved_definition_id": status.resolved_definition_id},
        )
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(
                    {
                        "ok": ok,
                        "actor_kind": actor_kind,
                        "actor_role_id": (actor_role_id or save.player_static_data.player_id),
                        "resource_status": status.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
            },
            event,
        )

    if tool_name == "spawn_scene_npc":
        try:
            args = json.loads(arg_text)
        except Exception:
            args = {}
        npc_name = str(args.get("name") or "").strip()
        if not npc_name:
            event = ToolEvent(tool_name="spawn_scene_npc", ok=False, summary="name is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "name_required"}, ensure_ascii=False),
                },
                event,
            )
        try:
            role = spawn_persistent_scene_npc_in_save(
                get_current_save(default_session_id=payload.session_id),
                name=npc_name,
                title=str(args.get("title") or "").strip(),
                description=str(args.get("description") or "").strip(),
                speaking_style=str(args.get("speaking_style") or "").strip(),
                agenda=str(args.get("agenda") or "").strip(),
                appearance=str(args.get("appearance") or "").strip(),
                alignment=str(args.get("alignment") or "").strip(),
                likes=[str(item) for item in list(args.get("likes") or []) if str(item).strip()],
            )
            result = {
                "ok": True,
                "role_id": role.role_id,
                "name": role.name,
                "zone_id": role.zone_id,
                "sub_zone_id": role.sub_zone_id,
            }
            event = ToolEvent(
                tool_name="spawn_scene_npc",
                ok=True,
                summary=f"spawned scene npc {role.name}",
                payload={"role_id": role.role_id},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="spawn_scene_npc", ok=False, summary=f"spawn failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "move_to_sub_zone":
        try:
            args = json.loads(arg_text)
            to_sub_zone_id = str(args.get("to_sub_zone_id") or "").strip()
        except Exception:
            to_sub_zone_id = ""
        if not to_sub_zone_id:
            event = ToolEvent(tool_name="move_to_sub_zone", ok=False, summary="to_sub_zone_id is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "to_sub_zone_id_required"}, ensure_ascii=False),
                },
                event,
            )
        try:
            moved = move_to_sub_zone(AreaMoveSubZoneRequest(session_id=payload.session_id, to_sub_zone_id=to_sub_zone_id))
            result = moved.model_dump(mode="json")
            event = ToolEvent(
                tool_name="move_to_sub_zone",
                ok=True,
                summary=f"moved to sub zone {to_sub_zone_id}",
                payload={"duration_min": moved.duration_min},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="move_to_sub_zone", ok=False, summary=f"move failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "discover_interactions":
        try:
            args = json.loads(arg_text)
            sub_zone_id = str(args.get("sub_zone_id") or "").strip()
            intent = str(args.get("intent") or "").strip()
        except Exception:
            sub_zone_id = ""
            intent = ""
        if not sub_zone_id or not intent:
            event = ToolEvent(tool_name="discover_interactions", ok=False, summary="sub_zone_id and intent required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "invalid_args"}, ensure_ascii=False),
                },
                event,
            )
        try:
            discovered = discover_interactions(
                AreaDiscoverInteractionsRequest(session_id=payload.session_id, sub_zone_id=sub_zone_id, intent=intent)
            )
            result = discovered.model_dump(mode="json")
            event = ToolEvent(
                tool_name="discover_interactions",
                ok=True,
                summary=f"discovered {len(discovered.new_interactions)} interactions",
                payload={"count": len(discovered.new_interactions)},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="discover_interactions", ok=False, summary=f"discover failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "execute_interaction":
        try:
            args = json.loads(arg_text)
            interaction_id = str(args.get("interaction_id") or "").strip()
            action_kind = str(args.get("action_kind") or "inspect").strip() or "inspect"
            actor_kind = str(args.get("actor_kind") or "player").strip() or "player"
            actor_role_id = str(args.get("actor_role_id") or "").strip() or None
            item_instance_id = str(args.get("item_instance_id") or "").strip() or None
            prompt = str(args.get("prompt") or "").strip()
        except Exception:
            interaction_id = ""
            action_kind = "inspect"
            actor_kind = "player"
            actor_role_id = None
            item_instance_id = None
            prompt = ""
        if not interaction_id:
            event = ToolEvent(tool_name="execute_interaction", ok=False, summary="interaction_id is required")
            return (
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"ok": False, "error": "interaction_id_required"}, ensure_ascii=False),
                },
                event,
            )
        try:
            executed = execute_interaction(
                AreaExecuteInteractionRequest(
                    session_id=payload.session_id,
                    interaction_id=interaction_id,
                    action_kind=action_kind,
                    actor_kind=actor_kind,  # type: ignore[arg-type]
                    actor_role_id=actor_role_id,
                    item_instance_id=item_instance_id,
                    prompt=prompt,
                    config=payload.config,
                )
            )
            result = executed.model_dump(mode="json")
            event = ToolEvent(tool_name="execute_interaction", ok=True, summary=executed.reply or executed.message or "scene interaction executed")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="execute_interaction", ok=False, summary=f"execute failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "player_add_item":
        try:
            args = json.loads(arg_text)
            item = InventoryItem(
                item_id=str(args.get("item_id") or "").strip(),
                name=str(args.get("name") or "").strip(),
                item_type=str(args.get("item_type") or "misc").strip() or "misc",
                quantity=max(1, int(args.get("quantity") or 1)),
                slot_type=str(args.get("slot_type") or "misc"),  # type: ignore[arg-type]
                attack_bonus=int(args.get("attack_bonus") or 0),
                armor_bonus=int(args.get("armor_bonus") or 0),
            )
            updated = add_player_item(payload.session_id, PlayerItemAddRequest(item=item))
            result = {"ok": True, "player_static_data": updated.model_dump(mode="json")}
            event = ToolEvent(tool_name="player_add_item", ok=True, summary="item added")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="player_add_item", ok=False, summary=f"item add failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "player_equip_item":
        try:
            args = json.loads(arg_text)
            slot = str(args.get("slot") or "").strip()
            mode = str(args.get("mode") or "equip").strip().lower()
            if mode == "unequip":
                updated = unequip_player_item(payload.session_id, PlayerUnequipRequest(slot=slot))  # type: ignore[arg-type]
            else:
                updated = equip_player_item(
                    payload.session_id,
                    PlayerEquipRequest(item_id=str(args.get("item_id") or "").strip(), slot=slot),  # type: ignore[arg-type]
                )
            result = {"ok": True, "player_static_data": updated.model_dump(mode="json")}
            event = ToolEvent(tool_name="player_equip_item", ok=True, summary=f"{mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="player_equip_item", ok=False, summary=f"equip failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "player_apply_buff":
        try:
            args = json.loads(arg_text)
            mode = str(args.get("mode") or "add").strip().lower()
            buff_id = str(args.get("buff_id") or "").strip()
            if mode == "remove":
                updated = remove_player_buff(payload.session_id, PlayerBuffRemoveRequest(buff_id=buff_id))
            else:
                buff = RoleBuff(
                    buff_id=buff_id,
                    name=str(args.get("name") or buff_id or "临时BUFF").strip(),
                    duration_min=max(0, int(args.get("duration_min") or 10)),
                    remaining_min=max(0, int(args.get("duration_min") or 10)),
                    effect={
                        "strength_delta": int(args.get("strength_delta") or 0),
                        "dexterity_delta": int(args.get("dexterity_delta") or 0),
                        "constitution_delta": int(args.get("constitution_delta") or 0),
                        "intelligence_delta": int(args.get("intelligence_delta") or 0),
                        "wisdom_delta": int(args.get("wisdom_delta") or 0),
                        "charisma_delta": int(args.get("charisma_delta") or 0),
                        "ac_delta": int(args.get("ac_delta") or 0),
                        "dc_delta": int(args.get("dc_delta") or 0),
                    },
                )
                updated = add_player_buff(payload.session_id, PlayerBuffAddRequest(buff=buff))
            result = {"ok": True, "player_static_data": updated.model_dump(mode="json")}
            event = ToolEvent(tool_name="player_apply_buff", ok=True, summary=f"buff {mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="player_apply_buff", ok=False, summary=f"buff failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "player_adjust_resource":
        try:
            args = json.loads(arg_text)
            kind = str(args.get("kind") or "").strip().lower()
            mode = str(args.get("mode") or "consume").strip().lower()
            amount = max(1, int(args.get("amount") or 1))
            if kind == "spell_slot":
                req = PlayerSpellSlotAdjustRequest(level=max(1, int(args.get("level") or 1)), amount=amount)
                updated = recover_spell_slots(payload.session_id, req) if mode == "recover" else consume_spell_slots(payload.session_id, req)
            elif kind == "martial_point":
                from app.models.schemas import PlayerMartialPointAdjustRequest
                from app.services.world_service import consume_martial_points, recover_martial_points

                req = PlayerMartialPointAdjustRequest(amount=amount)
                updated = recover_martial_points(payload.session_id, req) if mode == "recover" else consume_martial_points(payload.session_id, req)
            else:
                req = PlayerStaminaAdjustRequest(amount=amount)
                updated = recover_stamina(payload.session_id, req) if mode == "recover" else consume_stamina(payload.session_id, req)
            result = {"ok": True, "player_static_data": updated.model_dump(mode="json")}
            event = ToolEvent(tool_name="player_adjust_resource", ok=True, summary=f"{kind} {mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="player_adjust_resource", ok=False, summary=f"resource failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "role_set_relation":
        try:
            args = json.loads(arg_text)
            updated_role = set_role_relation(
                payload.session_id,
                str(args.get("role_id") or "").strip(),
                RoleRelationSetRequest(
                    target_role_id=str(args.get("target_role_id") or "").strip(),
                    relation_tag=str(args.get("relation_tag") or "neutral").strip(),
                    note=str(args.get("note") or "").strip(),
                ),
            )
            result = {"ok": True, "role": updated_role.model_dump(mode="json")}
            event = ToolEvent(tool_name="role_set_relation", ok=True, summary="relation updated")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="role_set_relation", ok=False, summary=f"relation failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "player_set_trait":
        try:
            args = json.loads(arg_text)
            kind = str(args.get("kind") or "").strip().lower()
            mode = str(args.get("mode") or "add").strip().lower()
            value = str(args.get("value") or "").strip()
            if kind == "spell":
                updated = remove_player_spell(payload.session_id, PlayerSpellSetRequest(value=value)) if mode == "remove" else add_player_spell(payload.session_id, PlayerSpellSetRequest(value=value))
            else:
                updated = remove_player_skill(payload.session_id, PlayerSkillSetRequest(value=value)) if mode == "remove" else add_player_skill(payload.session_id, PlayerSkillSetRequest(value=value))
            result = {"ok": True, "player_static_data": updated.model_dump(mode="json")}
            event = ToolEvent(tool_name="player_set_trait", ok=True, summary=f"{kind} {mode} ok")
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="player_set_trait", ok=False, summary=f"trait failed: {exc}")
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_player_death_state":
        save = get_current_save(default_session_id=payload.session_id)
        player = save.player_static_data
        death_state = player.dnd5e_sheet.death_state
        
        # 检查虚弱是否过期
        death_service.check_weakness_expired(player.dnd5e_sheet)
        
        result = {
            "ok": True,
            "life_status": death_state.life_status,
            "death_save_progress": {
                "successes": death_state.death_save_successes,
                "failures": death_state.death_save_failures,
            },
            "death_count": death_state.death_count,
            "death_streak_count": death_state.death_streak_count,
            "can_be_stabilized": death_state.life_status == "dying",
            "revival_weakness_active": any(
                b.name == "复活虚弱" for b in player.dnd5e_sheet.buffs
            ),
            "last_death_cause": death_state.last_death_cause,
        }
        event = ToolEvent(
            tool_name="get_player_death_state",
            ok=True,
            summary=f"death state: {death_state.life_status}",
            payload={"life_status": death_state.life_status},
        )
        logger.info("tool_call get_player_death_state ok: status=%s", death_state.life_status)
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "stabilize_player":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="stabilize_player", ok=False, summary="invalid json args")
            logger.info("tool_call stabilize_player failed: invalid_json_args")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False)},
                event,
            )
        
        save = get_current_save(default_session_id=payload.session_id)
        player = save.player_static_data
        
        if player.dnd5e_sheet.death_state.life_status != "dying":
            result = {"ok": False, "error": "player_not_dying"}
            event = ToolEvent(tool_name="stabilize_player", ok=False, summary="player not in dying state")
        else:
            from app.models.schemas import CombatantState
            player_combatant = CombatantState(
                combatant_id="player_001",
                source_kind="player",
                display_name=player.name,
                side="player_side",
                max_hp=player.dnd5e_sheet.hit_points.maximum,
                current_hp=player.dnd5e_sheet.hit_points.current,
                death_state=player.dnd5e_sheet.death_state,
                conditions=["dying", "unconscious", "prone"],
            )
            
            result_stabilize = death_service.stabilize(
                save,
                player_combatant,
                stabilizer=None,
                method="medicine" if args.get("method") == "medicine_check" else "item",
            )
            
            # 同步状态回玩家数据
            player.dnd5e_sheet.death_state = player_combatant.death_state
            if result_stabilize.get("stabilized"):
                player.dnd5e_sheet.status_flags = ["stable", "unconscious"]
            save_current(save)
            
            result = {
                "ok": True,
                "stabilized": result_stabilize.get("stabilized", False),
                "narrative": result_stabilize.get("narrative", ""),
            }
            event = ToolEvent(
                tool_name="stabilize_player",
                ok=True,
                summary="stabilize " + ("ok" if result["stabilized"] else "failed"),
                payload={"stabilized": result["stabilized"]},
            )
            logger.info("tool_call stabilize_player ok: stabilized=%s", result["stabilized"])
        
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "player_revive":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="player_revive", ok=False, summary="invalid json args")
            logger.info("tool_call player_revive failed: invalid_json_args")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False)},
                event,
            )
        
        save = get_current_save(default_session_id=payload.session_id)
        player = save.player_static_data
        
        if player.dnd5e_sheet.death_state.life_status != "dead":
            result = {"ok": False, "error": "player_not_dead"}
            event = ToolEvent(tool_name="player_revive", ok=False, summary="player not dead")
        else:
            method = args.get("method", "shrine")
            
            if method == "shrine":
                revive_result = death_service.revive_at_shrine(save, shrine_zone_id=args.get("shrine_zone_id"))
            elif method == "item":
                # 查找复活道具
                item_id = args.get("item_instance_id")
                item = next((i for i in player.dnd5e_sheet.backpack.items if i.item_id == item_id), None)
                if item:
                    revive_result = death_service.revive_by_item(save, item)
                else:
                    revive_result = {"success": False, "error": "item_not_found"}
            else:
                # 队友复活（简化处理，使用神庙复活的逻辑但减少惩罚）
                revive_result = death_service.revive_at_shrine(save)
                revive_result["method"] = "teammate"
                revive_result["narrative"] = "队友的急救让你重新苏醒。"
            
            if revive_result.get("success"):
                save_current(save)
                result = {
                    "ok": True,
                    "method": revive_result.get("method", method),
                    "narrative": revive_result.get("narrative", ""),
                    "penalties": {
                        "gold_lost": revive_result["penalties_applied"].gold_lost,
                        "exp_lost": revive_result["penalties_applied"].exp_lost,
                        "weakness_duration_min": revive_result["penalties_applied"].weakness_duration_min,
                    },
                }
                event = ToolEvent(
                    tool_name="player_revive",
                    ok=True,
                    summary=f"revived by {method}",
                    payload={"method": method},
                )
                logger.info("tool_call player_revive ok: method=%s", method)
            else:
                result = {"ok": False, "error": revive_result.get("error", "revive_failed")}
                event = ToolEvent(tool_name="player_revive", ok=False, summary=result["error"])
        
        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "deal_damage":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="deal_damage", ok=False, summary="invalid json args")
            logger.info("tool_call deal_damage failed: invalid_json_args")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False)},
                event,
            )

        target_type = str(args.get("target_type") or "").strip().lower()
        damage = max(1, int(args.get("damage") or 1))
        damage_type = str(args.get("damage_type") or "").strip()
        attacker_role_id = str(args.get("attacker_role_id") or "").strip() or None
        reason = str(args.get("reason") or "").strip()
        skip_death_save = bool(args.get("skip_death_save", False))

        if target_type not in {"player", "role"}:
            event = ToolEvent(tool_name="deal_damage", ok=False, summary="target_type must be player or role")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_target_type"}, ensure_ascii=False)},
                event,
            )

        save = get_current_save(default_session_id=payload.session_id)
        result: dict[str, Any] = {"ok": True, "damage_applied": 0, "hp_remaining": 0, "life_status": "healthy"}

        if target_type == "player":
            player_sheet = save.player_static_data.dnd5e_sheet
            hp_before = player_sheet.hit_points.current
            temp_hp = player_sheet.hit_points.temporary

            # 先扣临时HP
            remaining_damage = damage
            if temp_hp > 0:
                absorbed = min(temp_hp, remaining_damage)
                player_sheet.hit_points.temporary -= absorbed
                remaining_damage -= absorbed

            # 扣除当前HP
            if remaining_damage > 0:
                player_sheet.hit_points.current = max(0, player_sheet.hit_points.current - remaining_damage)

            hp_after = player_sheet.hit_points.current
            result["damage_applied"] = damage
            result["hp_remaining"] = hp_after
            result["hp_before"] = hp_before
            result["temp_hp_absorbed"] = min(temp_hp, damage) if temp_hp > 0 else 0

            death_state = player_sheet.death_state

            # 检查死亡流程
            if hp_after <= 0:
                # 检查即死条件：单次伤害从正值降到负的最大生命值
                is_instant_death = skip_death_save
                if hp_before > 0 and damage >= hp_before + player_sheet.hit_points.maximum:
                    is_instant_death = True

                if is_instant_death:
                    # 直接死亡
                    death_state.life_status = "dead"
                    death_state.death_count += 1
                    death_state.death_streak_count += 1
                    death_state.last_death_at = datetime.now(timezone.utc).isoformat()
                    death_state.last_death_cause = reason or f"伤害 ({damage_type or '未知'})"
                    death_state.updated_at = datetime.now(timezone.utc).isoformat()
                    player_sheet.is_dead = True
                    player_sheet.status_flags = ["dead"]
                    result["life_status"] = "dead"
                    result["declared_death"] = True
                    result["is_instant_death"] = True
                    summary = f"deal_damage: player died instantly, damage={damage}"
                else:
                    # 进入濒死状态
                    death_state.life_status = "dying"
                    death_state.death_save_successes = 0
                    death_state.death_save_failures = 0
                    death_state.updated_at = datetime.now(timezone.utc).isoformat()
                    player_sheet.status_flags = ["dying", "unconscious", "prone"]
                    result["life_status"] = "dying"
                    result["entered_dying"] = True
                    result["death_save"] = {"successes": 0, "failures": 0}
                    summary = f"deal_damage: player entering dying state, damage={damage}"
            else:
                result["life_status"] = death_state.life_status
                summary = f"deal_damage: player damaged, hp={hp_after}/{player_sheet.hit_points.maximum}"

            save_current(save)
            event = ToolEvent(tool_name="deal_damage", ok=True, summary=summary, payload={"damage": damage, "hp_remaining": hp_after, "life_status": result["life_status"]})
            logger.info("tool_call deal_damage ok: target=player damage=%s hp_remaining=%s life_status=%s", damage, hp_after, result["life_status"])
        else:
            # target_type == "role"
            target_role_id = str(args.get("target_role_id") or "").strip()
            if not target_role_id:
                event = ToolEvent(tool_name="deal_damage", ok=False, summary="target_role_id is required when target_type is 'role'")
                return (
                    {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "target_role_id_required"}, ensure_ascii=False)},
                    event,
                )

            role = next((r for r in save.role_pool if r.role_id == target_role_id), None)
            if role is None:
                event = ToolEvent(tool_name="deal_damage", ok=False, summary="role not found")
                return (
                    {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "role_not_found"}, ensure_ascii=False)},
                    event,
                )

            role_sheet = role.profile.dnd5e_sheet
            hp_before = role_sheet.hit_points.current
            temp_hp = role_sheet.hit_points.temporary

            # 先扣临时HP
            remaining_damage = damage
            if temp_hp > 0:
                absorbed = min(temp_hp, remaining_damage)
                role_sheet.hit_points.temporary -= absorbed
                remaining_damage -= absorbed

            # 扣除当前HP
            if remaining_damage > 0:
                role_sheet.hit_points.current = max(0, role_sheet.hit_points.current - remaining_damage)

            hp_after = role_sheet.hit_points.current
            result["damage_applied"] = damage
            result["hp_remaining"] = hp_after
            result["hp_before"] = hp_before
            result["temp_hp_absorbed"] = min(temp_hp, damage) if temp_hp > 0 else 0

            if hp_after <= 0:
                role_sheet.is_dead = True
                role_sheet.status_flags = ["dead", "downed"]
                result["life_status"] = "dead"
                summary = f"deal_damage: role died, damage={damage}"
            else:
                result["life_status"] = "healthy"
                summary = f"deal_damage: role damaged, hp={hp_after}/{role_sheet.hit_points.maximum}"

            save_current(save)
            event = ToolEvent(tool_name="deal_damage", ok=True, summary=summary, payload={"damage": damage, "hp_remaining": hp_after, "life_status": result["life_status"]})
            logger.info("tool_call deal_damage ok: target_role=%s damage=%s hp_remaining=%s", target_role_id, damage, hp_after)

        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "spawn_encounter_npc":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="spawn_encounter_npc", ok=False, summary="invalid json args")
            logger.info("tool_call spawn_encounter_npc failed: invalid_json_args")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False)},
                event,
            )

        encounter_id = str(args.get("encounter_id") or "").strip()
        name = str(args.get("name") or "").strip()
        title = str(args.get("title") or "").strip()
        description = str(args.get("description") or "").strip()
        speaking_style = str(args.get("speaking_style") or "").strip()
        agenda = str(args.get("agenda") or "").strip()
        role_type = str(args.get("role_type") or "neutral").strip()

        if not encounter_id or not name:
            event = ToolEvent(tool_name="spawn_encounter_npc", ok=False, summary="encounter_id and name are required")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "missing_required_fields"}, ensure_ascii=False)},
                event,
            )

        save = get_current_save(default_session_id=payload.session_id)
        from app.services.encounter_service import _state, _find_encounter, _refresh_participants, _append_step, _touch_state, _utc_now

        state = _state(save)
        encounter = _find_encounter(state, encounter_id)

        if encounter is None:
            event = ToolEvent(tool_name="spawn_encounter_npc", ok=False, summary="encounter not found")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "encounter_not_found"}, ensure_ascii=False)},
                event,
            )

        # 创建临时NPC
        from datetime import datetime, timezone
        from app.models.schemas import EncounterTemporaryNpc

        temp_npc = EncounterTemporaryNpc(
            encounter_npc_id=f"encnpc_mid_{datetime.now(timezone.utc).timestamp()}",
            name=name,
            title=title,
            description=description or f"{name}卷入了当前的遭遇。",
            speaking_style=speaking_style,
            agenda=agenda or f"{name}正试图处理眼前的情况。",
            state="active",
            zone_id=encounter.zone_id,
            sub_zone_id=encounter.sub_zone_id,
            introduced_at=datetime.now(timezone.utc).isoformat(),
        )

        # 添加到遭遇
        encounter.temporary_npcs.append(temp_npc)
        if temp_npc.encounter_npc_id not in encounter.participant_role_ids:
            encounter.participant_role_ids.append(temp_npc.encounter_npc_id)
        _refresh_participants(save, encounter)

        # 记录日志
        _append_step(
            encounter,
            kind="npc_entrance",
            actor_type="temporary_npc",
            actor_id=temp_npc.encounter_npc_id,
            actor_name=name,
            content=f"新角色入场：{name}" + (f"（{title}）" if title else "") + "。",
            metadata={"npc_name": name, "role_type": role_type},
        )
        _touch_state(state)
        save_current(save)

        result = {
            "ok": True,
            "encounter_npc_id": temp_npc.encounter_npc_id,
            "name": name,
            "title": title,
            "role_type": role_type,
        }
        event = ToolEvent(
            tool_name="spawn_encounter_npc",
            ok=True,
            summary=f"spawned encounter npc: {name}",
            payload={"npc_id": temp_npc.encounter_npc_id, "name": name},
        )
        logger.info("tool_call spawn_encounter_npc ok: encounter=%s npc=%s", encounter_id, name)

        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    if tool_name == "get_encounter_participants":
        try:
            args = json.loads(arg_text)
        except Exception:
            event = ToolEvent(tool_name="get_encounter_participants", ok=False, summary="invalid json args")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "invalid_json_args"}, ensure_ascii=False)},
                event,
            )

        encounter_id = str(args.get("encounter_id") or "").strip()
        if not encounter_id:
            event = ToolEvent(tool_name="get_encounter_participants", ok=False, summary="encounter_id is required")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "encounter_id_required"}, ensure_ascii=False)},
                event,
            )

        save = get_current_save(default_session_id=payload.session_id)
        from app.services.encounter_service import _state, _find_encounter, _visible_participant_text

        state = _state(save)
        encounter = _find_encounter(state, encounter_id)

        if encounter is None:
            event = ToolEvent(tool_name="get_encounter_participants", ok=False, summary="encounter not found")
            return (
                {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"ok": False, "error": "encounter_not_found"}, ensure_ascii=False)},
                event,
            )

        team_members, visible_npcs = _visible_participant_text(save, encounter)

        result = {
            "ok": True,
            "encounter_id": encounter_id,
            "main_npc_role_id": encounter.npc_role_id,
            "participant_role_ids": encounter.participant_role_ids,
            "team_members": team_members,
            "visible_npcs": visible_npcs,
            "temporary_npcs": [
                {
                    "encounter_npc_id": npc.encounter_npc_id,
                    "name": npc.name,
                    "title": npc.title,
                    "state": npc.state,
                }
                for npc in encounter.temporary_npcs
            ],
        }
        event = ToolEvent(
            tool_name="get_encounter_participants",
            ok=True,
            summary=f"participants: {len(encounter.temporary_npcs)} temp npcs",
            payload={"temp_npc_count": len(encounter.temporary_npcs)},
        )
        logger.info("tool_call get_encounter_participants ok: encounter=%s", encounter_id)

        return (
            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)},
            event,
        )

    event = ToolEvent(tool_name=tool_name or "unknown", ok=False, summary="unsupported tool")
    logger.info("tool_call unknown failed: %s", tool_name)
    return (
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps({"ok": False, "error": "unsupported_tool"}, ensure_ascii=False),
        },
        event,
    )


async def chat_once(payload: ChatRequest) -> tuple[Message, Usage, list[ToolEvent]]:
    client = _client(payload)
    messages = _build_messages(payload)
    usage_sum = Usage()
    tool_events: list[ToolEvent] = []

    for _ in range(4):
        response = await client.chat.completions.create(
            model=payload.config.model,
            **build_completion_options(payload.config),
            messages=messages,
            tools=_tools_schema(),
            tool_choice="auto",
        )
        usage_sum = _sum_usage(usage_sum, _build_usage(response.usage))
        choice = response.choices[0].message
        assistant_entry: dict[str, Any] = {
            "role": "assistant",
            "content": choice.content or "",
        }
        if getattr(choice, "tool_calls", None):
            assistant_entry["tool_calls"] = choice.tool_calls
        messages.append(assistant_entry)

        if not getattr(choice, "tool_calls", None):
            content = choice.content or ""
            return Message(role="assistant", content=content), usage_sum, tool_events

        for call in choice.tool_calls:
            tool_msg, event = await _handle_tool_call(payload, call)
            tool_events.append(event)
            messages.append(tool_msg)

    return Message(role="assistant", content="Tool call limit reached. Please simplify your request."), usage_sum, tool_events


async def resolve_main_chat_turn(payload: ChatRequest) -> tuple[Message, Usage, list[ToolEvent], list[Any], int, str | None]:
    last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
    parsed_intent: dict[str, object] = _parse_player_intent(last_user.content) if last_user is not None else {}
    routed = route_main_turn_intent(payload.session_id, parsed_intent, payload.config) if last_user is not None else {
        "handled": False,
        "reply": None,
        "tool_events": [],
        "scene_events": [],
        "time_spent_min": 0,
        "skip_encounter_main_chat_advance": False,
    }
    if last_user is not None and bool(parsed_intent.get("passive_turn")) and not bool(routed.get("handled")):
        save = get_current_save(default_session_id=payload.session_id)
        if save.session_id != payload.session_id:
            save.session_id = payload.session_id
            save_current(save)
        active_encounter = _active_encounter_for_current_sub_zone(save)
        if active_encounter is None or active_encounter.status != "active" or active_encounter.player_presence != "engaged":
            raise ValueError("PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER")
    if bool(routed.get("handled")):
        time_spent_min = int(routed.get("time_spent_min") or 0)
        reply = routed.get("reply") or Message(role="assistant", content="")
        usage = Usage()
        tool_events = list(routed.get("tool_events") or [])
        scene_events: list[Any] = list(routed.get("scene_events") or [])
    else:
        time_spent_min = apply_speech_time(payload.session_id, last_user.content, payload.config) if last_user is not None else 0
        reply, usage, tool_events = await chat_once(payload)
        tool_events = [*list(routed.get("tool_events") or []), *tool_events]
        scene_events = []
    archived_sub_zone_turn_id: str | None = None
    if last_user is not None:
        save = get_current_save(default_session_id=payload.session_id)
        if save.session_id != payload.session_id:
            save.session_id = payload.session_id
        if not bool(routed.get("skip_encounter_main_chat_advance")):
            encounter_events = advance_active_encounter_from_main_chat_in_save(
                save,
                session_id=payload.session_id,
                player_text=last_user.content,
                gm_narration=reply.content,
                time_spent_min=time_spent_min,
                config=payload.config,
            )
            scene_events.extend(encounter_events)
        scene_context = _build_scene_context_payload(
            save,
            player_text=last_user.content,
            gm_narration=reply.content,
            recent_turn_count=4,
        )
        public_events = advance_public_scene_in_save(
            save,
            session_id=payload.session_id,
            player_text=last_user.content,
            gm_summary=reply.content,
            scene_context=scene_context,
            config=payload.config,
        )
        scene_events.extend(public_events)
        archived_sub_zone_turn_id = _record_sub_zone_chat_turn(
            save,
            source="main_chat",
            player_mode=("passive" if bool(parsed_intent.get("passive_turn")) else "active"),
            player_action=str(parsed_intent["action_text"]),
            player_speech=str(parsed_intent["speech_text"]),
            player_action_check=(parsed_intent["action_check"] if isinstance(parsed_intent["action_check"], dict) else None),
            gm_narration=reply.content,
            events=scene_events,
        )
        save_current(save)
    return reply, usage, tool_events, scene_events, time_spent_min, archived_sub_zone_turn_id
