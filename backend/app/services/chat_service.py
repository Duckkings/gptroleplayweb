from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

from app.models.schemas import (
    AreaDiscoverInteractionsRequest,
    AreaExecuteInteractionRequest,
    AreaMoveSubZoneRequest,
    ChatRequest,
    Message,
    MoveRequest,
    ToolEvent,
    Usage,
)
from app.services.world_service import (
    discover_interactions,
    execute_interaction,
    generate_zones_for_chat,
    get_area_current,
    get_current_save,
    get_game_logs,
    move_to_sub_zone,
    move_to_zone,
)

logger = logging.getLogger("roleplay.tools")


class MissingAPIKeyError(RuntimeError):
    pass


def _build_messages(payload: ChatRequest) -> list[dict[str, Any]]:
    last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": payload.config.gm_prompt},
        {
            "role": "system",
            "content": (
                "Narration rule: act as a story narrator. "
                "Do not output numbered action choices unless the player explicitly asks for options."
            ),
        },
        {
            "role": "system",
            "content": (
                "Tool rule: when user asks to generate zones, move to zones, or confirm player state, "
                "you must call the proper tool first, then narrate based on tool results."
            ),
        },
        {
            "role": "system",
            "content": "Context rule: ignore prior chat history. Use tools to fetch state when needed.",
        },
        {
            "role": "system",
            "content": (
                "Map awareness rule: if movement target is ambiguous or you need available destinations, "
                "call get_map_index first to fetch current zone index."
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
                "description": "Return player static/runtime/map state as JSON for confirmation.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
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
            "player_static_data": save.player_static_data.model_dump(mode="json"),
            "player_runtime_data": save.player_runtime_data.model_dump(mode="json"),
            "map_snapshot": save.map_snapshot.model_dump(mode="json"),
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
