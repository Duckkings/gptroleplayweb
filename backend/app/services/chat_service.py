from __future__ import annotations

import json
import logging
import os
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
    EncounterEscapeRequest,
    EncounterRejoinRequest,
    InventoryEquipRequest,
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
    TeamDebugGenerateRequest,
    TeamInviteRequest,
    TeamLeaveRequest,
    ToolEvent,
    Usage,
)
from app.services.world_service import (
    add_player_buff,
    add_player_item,
    add_player_skill,
    add_player_spell,
    consume_spell_slots,
    consume_stamina,
    discover_interactions,
    equip_player_item,
    execute_interaction,
    generate_zones_for_chat,
    get_area_current,
    get_current_save,
    get_game_logs,
    recover_spell_slots,
    recover_stamina,
    remove_player_buff,
    remove_player_item,
    remove_player_skill,
    remove_player_spell,
    set_role_relation,
    inventory_equip,
    inventory_interact,
    inventory_unequip,
    unequip_player_item,
    move_to_sub_zone,
    move_to_zone,
)
from app.services.encounter_service import act_on_encounter, escape_encounter, get_encounter_debug_overview, rejoin_encounter
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    build_npc_knowledge_snapshot,
    collect_consistency_issues,
    reconcile_consistency,
)
from app.services.team_service import generate_debug_teammate, get_team_state, invite_npc_to_team, leave_npc_from_team, team_chat

logger = logging.getLogger("roleplay.tools")


class MissingAPIKeyError(RuntimeError):
    pass


def _build_messages(payload: ChatRequest) -> list[dict[str, Any]]:
    last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": payload.config.gm_prompt},
        {
            "role": "system",
            "content": prompt_table.get_text(
                "chat.narration_rule",
                "Narration rule: act as a story narrator. Do not output numbered action choices unless the player explicitly asks for options.",
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
    api_key = payload.config.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MissingAPIKeyError("openai_api_key is not set")
    return AsyncOpenAI(api_key=api_key)


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
                "name": "encounter_escape",
                "description": "Attempt to escape from the current active encounter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "encounter_id": {"type": "string"},
                    },
                    "required": ["encounter_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "encounter_rejoin",
                "description": "Rejoin an escaped encounter after returning to its original location.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "encounter_id": {"type": "string"},
                    },
                    "required": ["encounter_id"],
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
                "description": "Execute placeholder interaction. Returns fixed placeholder message for now.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interaction_id": {"type": "string"},
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
                "description": "Consume/recover spell slots or stamina.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["spell_slot", "stamina"]},
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

    if tool_name == "encounter_escape":
        try:
            args = json.loads(arg_text)
            encounter_id = str(args.get("encounter_id") or "").strip()
            response = escape_encounter(
                encounter_id,
                EncounterEscapeRequest(
                    session_id=payload.session_id,
                ),
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="encounter_escape",
                ok=True,
                summary=f"escape {'ok' if response.escape_success else 'failed'}",
                payload={"encounter_id": response.encounter_id, "escape_success": response.escape_success},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="encounter_escape", ok=False, summary=f"encounter escape failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
            event,
        )

    if tool_name == "encounter_rejoin":
        try:
            args = json.loads(arg_text)
            encounter_id = str(args.get("encounter_id") or "").strip()
            response = rejoin_encounter(
                encounter_id,
                EncounterRejoinRequest(
                    session_id=payload.session_id,
                ),
            )
            result = {"ok": True, **response.model_dump(mode="json")}
            event = ToolEvent(
                tool_name="encounter_rejoin",
                ok=True,
                summary=f"rejoin {response.status}",
                payload={"encounter_id": response.encounter_id},
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            event = ToolEvent(tool_name="encounter_rejoin", ok=False, summary=f"encounter rejoin failed: {exc}")
        return (
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            },
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
        except Exception:
            interaction_id = ""
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
                AreaExecuteInteractionRequest(session_id=payload.session_id, interaction_id=interaction_id)
            )
            result = executed.model_dump(mode="json")
            event = ToolEvent(tool_name="execute_interaction", ok=True, summary="placeholder interaction executed")
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
            temperature=payload.config.temperature,
            max_tokens=payload.config.max_tokens,
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
