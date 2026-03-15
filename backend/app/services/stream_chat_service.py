from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ActionCheckRequest,
    ChatRequest,
    ChatResponse,
    EncounterCheckRequest,
    EncounterResolution,
    MainTurnSummary,
    Message,
    NpcChatRequest,
    NpcChatResponse,
    PendingTurnContinueResponse,
    PendingTurnState,
    PlayerReactionCheck,
    SceneEvent,
    ToolEvent,
    Usage,
)
from app.services import chat_service as chat_legacy
from app.services import encounter_runtime_v2 as encounter_runtime
from app.services import encounter_service as encounter_legacy
from app.services import map_flow_service
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world
from app.services.ai_adapter import build_completion_options, create_async_client
from app.services.consistency_service import (
    build_npc_knowledge_snapshot,
    npc_guard_reply,
    player_mentions_unknown_npc,
)
from app.services.generation_debug_log_service import current_generation_debug_log, generation_debug_log
from app.services.pending_turn_service import cancel_pending_turn, clear_pending_turn, load_pending_turn, save_pending_turn
from app.services import reaction_check_service
from app.services.session_lock_service import get_session_lock
from app.services import structured_segment_service
from app.services import zone_metric_service

logger = logging.getLogger("roleplay.stream_chat")

EmitCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

_PHASE_LABELS = {
    "prepare": "Prepare",
    "intent_route": "Intent Route",
    "tool_plan": "Tool Plan",
    "tool_run": "Tool Run",
    "model_reply": "Model Reply",
    "bundle_parse": "Bundle Parse",
    "apply": "Apply",
    "commit": "Commit",
    "rollback": "Rollback",
}
_PLANNER_TOOLS: dict[str, str] = {
    "get_story_snapshot": "Return the current story snapshot.",
    "get_quest_state": "Return the current quest state.",
    "get_fate_state": "Return the current fate state.",
    "get_area_reputation": "Return the area reputation state.",
    "get_role_drives": "Return visible drives for one role or current area.",
    "get_public_scene_state": "Return public scene candidates.",
    "get_entity_index": "Return the legal entity ids.",
    "get_consistency_status": "Return consistency status.",
    "get_active_encounters": "Return active encounters.",
    "get_npc_knowledge": "Return one NPC knowledge snapshot. Requires args.npc_role_id.",
    "get_team_state": "Return the team state.",
    "get_role_inventory": "Return one role inventory snapshot. Requires args.role_id.",
    "get_map_index": "Return the map index.",
    "get_game_logs": "Return recent game logs.",
    "get_current_sub_zone": "Return the current sub-zone state.",
    "get_scene_interactables": "Return the current or target sub-zone scene interactables from the formal persistent interactable state.",
    "get_template_library_status": "Return the current account template-library status and definition counts.",
    "spawn_scene_npc": "Create one persistent NPC in the current sub-zone when a new role must immediately join the current scene. Requires args.name.",
    "inventory_grant_item": "Grant one item into player or role inventory when the scene should hand out an item. Requires args.owner_type, args.item_id, and args.name.",
    "inventory_consume_item": "Consume one item from player or role inventory when the scene spends or uses a consumable. Requires args.owner_type and args.item_id.",
    "execute_interaction": "Execute one formal scene interaction against the persistent interactable state. Requires args.interaction_id and usually args.action_kind.",
}


class StreamCancelledError(RuntimeError):
    pass


class StreamProtocolError(RuntimeError):
    pass


@dataclass
class StreamResult:
    reply: str
    usage: Usage
    tool_events: list[ToolEvent]
    scene_events: list[SceneEvent]
    time_spent_min: int
    archived_sub_zone_turn_id: str | None = None
    main_turn_summary: MainTurnSummary | None = None
    current_zone_metric: object | None = None


@dataclass
class BundleApplyResult:
    scene_events: list[SceneEvent]
    pending_reaction: PlayerReactionCheck | None = None


@dataclass
class NpcBundleApplyResult:
    response: NpcChatResponse
    pending_reaction: PlayerReactionCheck | None = None


class StreamingTurnParser:
    def __init__(self, bundle_tag: str) -> None:
        self.bundle_tag = bundle_tag
        self.buffer = ""
        self.bundle_buffer = ""
        self.state = "before_reply"
        self.bundle_complete = False

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self.buffer += chunk
        emitted: list[str] = []
        reply_open = "<reply>"
        reply_close = "</reply>"
        bundle_open = f"<{self.bundle_tag}>"
        bundle_close = f"</{self.bundle_tag}>"
        while True:
            if self.state == "before_reply":
                idx = self.buffer.find(reply_open)
                if idx < 0:
                    self.buffer = self.buffer[-len(reply_open) :]
                    break
                self.buffer = self.buffer[idx + len(reply_open) :]
                self.state = "in_reply"
                continue
            if self.state == "in_reply":
                idx = self.buffer.find(reply_close)
                if idx < 0:
                    safe = max(0, len(self.buffer) - len(reply_close))
                    if safe <= 0:
                        break
                    emitted.append(self.buffer[:safe])
                    self.buffer = self.buffer[safe:]
                    break
                emitted.append(self.buffer[:idx])
                self.buffer = self.buffer[idx + len(reply_close) :]
                self.state = "before_bundle"
                continue
            if self.state == "before_bundle":
                idx = self.buffer.find(bundle_open)
                if idx < 0:
                    self.buffer = self.buffer[-len(bundle_open) :]
                    break
                self.buffer = self.buffer[idx + len(bundle_open) :]
                self.state = "in_bundle"
                continue
            if self.state == "in_bundle":
                idx = self.buffer.find(bundle_close)
                if idx < 0:
                    self.bundle_buffer += self.buffer
                    self.buffer = ""
                    break
                self.bundle_buffer += self.buffer[:idx]
                self.buffer = self.buffer[idx + len(bundle_close) :]
                self.bundle_complete = True
                self.state = "done"
                break
            break
        return [piece for piece in emitted if piece]

    def require_bundle(self) -> dict[str, Any]:
        # First check if we have a complete bundle
        if not self.bundle_complete:
            # Try to find if there's JSON content collected even without closing tag
            text = self.bundle_buffer.strip()
            if text:
                logger.warning(
                    "%s missing closing tag but has %d chars of content. "
                    "Attempting to parse anyway...",
                    self.bundle_tag,
                    len(text),
                )
                # Try to parse what we have
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        logger.warning("%s parsed successfully despite missing closing tag", self.bundle_tag)
                        return parsed
                except json.JSONDecodeError:
                    pass
                # Try raw_decode to extract partial JSON
                try:
                    parsed, end = json.JSONDecoder().raw_decode(text)
                    if isinstance(parsed, dict):
                        logger.warning(
                            "%s extracted partial JSON (pos %d of %d chars) despite missing closing tag",
                            self.bundle_tag,
                            end,
                            len(text),
                        )
                        return parsed
                except json.JSONDecodeError:
                    pass
            raise StreamProtocolError(f"{self.bundle_tag} missing closing tag")
        text = self.bundle_buffer.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            # Log detailed error info for debugging
            logger.error(
                "%s JSON parse failed at pos %d (char %d): %s. Raw content (first 1000 chars): %r",
                self.bundle_tag,
                exc.lineno,
                exc.colno,
                exc.msg,
                text[:1000],
            )
            try:
                parsed, end = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError:
                # Include raw content preview in exception for debugging
                preview = text[:500] if len(text) <= 500 else f"{text[:500]}...<truncated {len(text)-500}>"
                raise StreamProtocolError(
                    f"{self.bundle_tag} json parse failed: {exc}. Raw content preview: {preview!r}"
                ) from exc
            trailing = text[end:].strip()
            if trailing:
                # Log warning for trailing content but accept the first valid JSON
                logger.warning(
                    "%s has trailing content after valid JSON (pos %d of %d chars). "
                    "Accepting first JSON object. Trailing preview: %r",
                    self.bundle_tag,
                    end,
                    len(text),
                    trailing[:200],
                )
        if not isinstance(parsed, dict):
            raise StreamProtocolError(f"{self.bundle_tag} must decode to object")
        return parsed
async def _emit_phase(emit: EmitCallback | None, code: str, status: str, detail: str = "") -> None:
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record("phase", f"{code}:{status}", {"detail": detail})
    if emit is None:
        return
    await emit(
        "phase",
        {
            "code": code,
            "label": _PHASE_LABELS.get(code, code),
            "status": status,
            "detail": detail,
        },
    )


async def _emit_tool(
    emit: EmitCallback | None,
    *,
    tool_name: str,
    status: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> None:
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record("tool", f"{tool_name}:{status}", {"summary": summary, "payload": payload or {}})
    if emit is None:
        return
    await emit(
        "tool",
        {
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
            "payload": payload or {},
        },
    )


async def _emit_rollback(emit: EmitCallback | None, reason: str, message: str) -> None:
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record("rollback", message, {"reason": reason})
    if emit is None:
        return
    await emit("rollback", {"reason": reason, "message": message, "discarded": True})


async def _emit_reaction_required(
    emit: EmitCallback | None,
    payload: PendingTurnContinueResponse,
) -> None:
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record(
            "reaction_check_required",
            "reaction checkpoint staged",
            {
                "pending_turn_id": payload.pending_turn_id,
                "flow_kind": payload.flow_kind,
                "reply_length": len(payload.reply_text),
            },
        )
    if emit is None:
        return
    await emit(
        "reaction_check_required",
        {
            "pending_turn_id": payload.pending_turn_id,
            "flow_kind": payload.flow_kind,
            "reply_so_far": payload.reply_text,
            "scene_events_so_far": [item.model_dump(mode="json") for item in payload.scene_events],
            "pending_reaction": payload.pending_reaction.model_dump(mode="json") if payload.pending_reaction is not None else None,
            "npc_role_id": payload.npc_role_id,
        },
    )


async def _emit_reaction_resumed(
    emit: EmitCallback | None,
    *,
    pending_turn_id: str,
    continuation_index: int,
    reaction_result=None,
) -> None:
    if emit is None:
        return
    await emit(
        "reaction_check_resumed",
        {
            "pending_turn_id": pending_turn_id,
            "continuation_index": continuation_index,
            "reaction_result": (reaction_result.model_dump(mode="json") if reaction_result is not None else None),
        },
    )


async def _emit_reaction_cancelled(emit: EmitCallback | None, *, pending_turn_id: str) -> None:
    if emit is None:
        return
    await emit("reaction_check_cancelled", {"pending_turn_id": pending_turn_id, "discarded": True})


async def _check_cancelled(is_cancelled: Callable[[], Awaitable[bool]] | None) -> None:
    if is_cancelled is None:
        return
    if await is_cancelled():
        raise StreamCancelledError("CLIENT_DISCONNECTED")


def _extract_chunk_text(chunk: Any) -> str:
    pieces: list[str] = []
    for choice in getattr(chunk, "choices", []) or []:
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            pieces.append(content)
            continue
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    pieces.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
    return "".join(pieces)


def _usage_from_chunk(chunk: Any) -> Usage:
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _sum_usage(left: Usage, right: Usage) -> Usage:
    return Usage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
    )


def _require_async_client(config) -> AsyncOpenAI:
    api_key = (config.api_key or "").strip()
    if not api_key:
        raise chat_legacy.MissingAPIKeyError("api_key is not set")
    return create_async_client(config, client_cls=AsyncOpenAI)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clamp(value: Any, lower: int, upper: int) -> int:
    return max(lower, min(upper, _safe_int(value)))


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _planned_ability(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
        return candidate
    return "wisdom"


def _public_actor_requires_check(save, actor: dict[str, Any], update: dict[str, Any], config) -> bool:
    payload = {
        "needs_check": bool(update.get("needs_check")),
        "outcome_certainty": str(update.get("outcome_certainty") or "").strip().lower(),
        "action_type": str(update.get("action_type") or "check").strip().lower(),
        "specific_threat": str(update.get("specific_threat") or "").strip(),
        "target_label": str(update.get("target_label") or "").strip(),
    }
    return public_scene_runtime.should_force_public_action_check(save, actor, payload, config=config)


def _public_audience_context(save, player_text: str) -> dict[str, Any]:
    return public_scene_runtime.build_public_audience_context(save, world._parse_player_intent(player_text))


def _public_result_label(action_result, situation_delta: int) -> str:
    if action_result is not None:
        if action_result.critical == "critical_success":
            return "大成功"
        if action_result.critical == "critical_failure":
            return "大失败"
        return "成功" if action_result.success else "失败"
    if situation_delta > 0:
        return "推进成功"
    if situation_delta < 0:
        return "推进受阻"
    return "维持僵持"


def _find_team_member(save, role_id: str):
    return next((item for item in getattr(save.team_state, "members", []) if item.role_id == role_id), None)


def _build_checked_action_label(update: dict[str, Any], action_line: str) -> str:
    for candidate in [
        str(update.get("planned_check_task") or "").strip(),
        str(update.get("target_label") or "").strip(),
        str(update.get("specific_threat") or "").strip(),
    ]:
        if candidate:
            return candidate[:120]
    return " ".join(action_line.split()).strip()[:120]


def _build_public_gm_result_summary(
    *,
    actor_name: str,
    checked_action_label: str,
    target_label: str,
    specific_threat: str,
    check_result: dict[str, object],
    situation_delta: int,
) -> str:
    if not bool(check_result.get("requires_check")):
        return ""
    outcome_label = str(check_result.get("outcome_label") or "结果已定")
    focus = target_label.strip() or specific_threat.strip() or "眼前局面"
    action_label = checked_action_label.strip() or "这一手尝试"
    if outcome_label == "大成功":
        return f"因为大成功，{actor_name}在“{action_label}”上超额发挥，{focus}附近的局面被明显拉回到更有利的一侧。"
    if outcome_label == "大失败":
        return f"因为大失败，{actor_name}在“{action_label}”上彻底失手，{focus}附近的压力一下子被放大了。"
    if outcome_label == "成功":
        if situation_delta > 0:
            return f"因为检定成功，{actor_name}做成了“{action_label}”，{focus}附近因此出现了新的处理空间。"
        return f"因为检定成功，{actor_name}稳稳完成了“{action_label}”，现场至少没有继续失控。"
    if situation_delta < 0:
        return f"因为检定失败，{actor_name}没能把“{action_label}”做成，{focus}附近的风险被继续往前推。"
    return f"因为检定失败，{actor_name}这一步没能真正做成“{action_label}”，现场暂时仍维持在僵持里。"


def _append_public_turn_team_reaction(
    save,
    *,
    session_id: str,
    member,
    content: str,
    affinity_delta: int,
    trust_delta: int,
) -> None:
    if not content.strip():
        return
    from app.models.schemas import TeamReaction
    from app.services.team_service import ensure_team_state

    state = ensure_team_state(save)
    stamp = world._utc_now().replace(":", "").replace("-", "").replace(".", "")
    state.reactions.append(
        TeamReaction(
            reaction_id=f"treact_{stamp}",
            member_role_id=member.role_id,
            member_name=member.name,
            trigger_kind="public_turn",
            content=content[:240],
            affinity_delta=affinity_delta,
            trust_delta=trust_delta,
        )
    )
    state.reactions = state.reactions[-100:]
    save.game_logs.append(
        world._new_game_log(
            session_id,
            "team_reaction",
            f"{member.name}: {content[:120]}",
            {
                "role_id": member.role_id,
                "trigger_kind": "public_turn",
                "affinity_delta": affinity_delta,
                "trust_delta": trust_delta,
            },
        )
    )


def _team_relation_summary_text(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        name = str(row.get("name") or row.get("role_id") or "队友")
        affinity_delta = int(row.get("affinity_delta") or 0)
        trust_delta = int(row.get("trust_delta") or 0)
        parts.append(f"{name} 好感{affinity_delta:+d} / 信任{trust_delta:+d}")
    return "；".join(parts)


def _build_public_resolution_detail(
    *,
    actor_name: str,
    affected_object: str,
    specific_threat: str,
    situation_delta: int,
    action_result,
) -> tuple[str, str, str]:
    if action_result is not None and str(getattr(action_result, "narrative", "") or "").strip():
        concrete_effect = str(action_result.narrative).strip()[:220]
    elif situation_delta > 0:
        concrete_effect = f"{actor_name}暂时压住了{affected_object}周围最直接的风险，现场因此出现了可以继续处理的空档。"
    elif situation_delta < 0:
        concrete_effect = f"{actor_name}这一步没能压住{affected_object}附近的险情，压力反而被推得更近。"
    else:
        concrete_effect = f"{actor_name}先把动作落到了{affected_object}上，但现场暂时只是维持住了僵持。"
    if situation_delta >= 0:
        opened_opportunity = f"玩家现在可以顺着{affected_object}继续追查真正的源头。"
    else:
        opened_opportunity = f"玩家仍能直接介入{affected_object}，但必须更快。"
    if situation_delta > 0:
        new_pressure = "现场仍有余压，但不再立刻外溢。"
    elif situation_delta == 0:
        new_pressure = "局面没有继续恶化，但也还没有被真正压住。"
    else:
        new_pressure = specific_threat or f"{affected_object}附近的风险正在继续扩大。"
    return concrete_effect[:220], opened_opportunity[:180], new_pressure[:180]


def _normalize_encounter_world_pushes(encounter_update: dict[str, Any], *, config) -> list[dict[str, Any]]:
    raw = encounter_update.get("world_pushes")
    if not isinstance(raw, list):
        return []
    scene_config = getattr(config, "public_scene", None)
    limit = max(0, min(int(getattr(scene_config, "max_world_pushes", 2) or 2), 4))
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if len(normalized) >= limit:
            break
        if not isinstance(item, dict):
            continue
        push_kind = str(item.get("push_kind") or "").strip()
        if push_kind not in {"new_clue", "environment_shift", "hazard_escalation", "pressure_release", "faction_move", "npc_arrival"}:
            continue
        title = str(item.get("title") or "").strip()[:80]
        detail = str(item.get("detail") or "").strip()[:240]
        opened_window = str(item.get("opened_window") or "").strip()[:180]
        pressure_note = str(item.get("pressure_note") or "").strip()[:180]
        spawn_npc = None
        if push_kind == "npc_arrival":
            spawn_npc = encounter_legacy._sanitize_new_npc_seed(item.get("spawn_npc"))
        location_target = None
        raw_location_target = item.get("location_target")
        if isinstance(raw_location_target, dict):
            sub_zone_name = str(raw_location_target.get("sub_zone_name") or "").strip()[:48]
            if sub_zone_name:
                location_target = {
                    "zone_name": str(raw_location_target.get("zone_name") or "").strip()[:48],
                    "zone_description": str(raw_location_target.get("zone_description") or "").strip()[:160],
                    "zone_type_hint": str(raw_location_target.get("zone_type_hint") or "unknown").strip()[:24] or "unknown",
                    "sub_zone_name": sub_zone_name,
                    "sub_zone_description": str(raw_location_target.get("sub_zone_description") or "").strip()[:180],
                    "reason": str(raw_location_target.get("reason") or "").strip()[:120],
                    "move_encounter_focus": bool(raw_location_target.get("move_encounter_focus")),
                    "move_actor_ids": [
                        str(actor_id).strip()
                        for actor_id in list(raw_location_target.get("move_actor_ids") or [])
                        if str(actor_id).strip()
                    ][:8],
                }
        if not any([title, detail, opened_window, pressure_note, spawn_npc, location_target]):
            continue
        normalized.append(
            {
                "push_kind": push_kind,
                "title": title,
                "detail": detail,
                "opened_window": opened_window,
                "pressure_note": pressure_note,
                "situation_delta_hint": _clamp(item.get("situation_delta_hint"), -8, 8),
                "spawn_npc": spawn_npc,
                "location_target": location_target,
            }
        )
    return normalized


def _world_push_event_text(push: dict[str, Any], *, spawned_name: str = "") -> str:
    parts = [str(push.get("title") or "").strip(), str(push.get("detail") or "").strip()]
    if str(push.get("opened_window") or "").strip():
        parts.append(f"可利用窗口：{str(push.get('opened_window') or '').strip()}")
    if str(push.get("pressure_note") or "").strip():
        parts.append(f"新增压力：{str(push.get('pressure_note') or '').strip()}")
    if spawned_name:
        parts.append(f"新角色入场：{spawned_name}")
    return " ".join(part for part in parts if part).strip()[:320]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _preview_text(value: str, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def _config_log_data(config) -> dict[str, Any]:
    if config is None:
        return {}
    runtime = getattr(config, "runtime", None)
    runtime_payload = runtime.model_dump(mode="json", exclude_none=True) if runtime is not None else {}
    return {
        "provider": str(getattr(config, "provider", "") or ""),
        "model": str(getattr(config, "model", "") or ""),
        "stream": bool(getattr(config, "stream", False)),
        "runtime": runtime_payload,
        "gm_prompt_length": len(str(getattr(config, "gm_prompt", "") or "")),
    }


def _main_request_log_data(payload: ChatRequest) -> dict[str, Any]:
    last_user = next((message for message in reversed(payload.messages) if message.role == "user"), None)
    return {
        **_config_log_data(payload.config),
        "message_count": len(payload.messages),
        "last_user_preview": _preview_text(last_user.content if last_user is not None else ""),
    }


def _npc_request_log_data(payload: NpcChatRequest) -> dict[str, Any]:
    return {
        **_config_log_data(payload.config),
        "npc_role_id": payload.npc_role_id,
        "player_message_preview": _preview_text(payload.player_message),
    }


def _main_result_log_data(result: StreamResult) -> dict[str, Any]:
    return {
        "reply_preview": _preview_text(result.reply),
        "time_spent_min": result.time_spent_min,
        "tool_event_count": len(result.tool_events),
        "scene_event_count": len(result.scene_events),
        "archived_sub_zone_turn_id": result.archived_sub_zone_turn_id,
        "main_turn_summary": (result.main_turn_summary.model_dump(mode="json") if result.main_turn_summary is not None else None),
        "current_zone_metric": (
            result.current_zone_metric.model_dump(mode="json")  # type: ignore[union-attr]
            if result.current_zone_metric is not None and hasattr(result.current_zone_metric, "model_dump")
            else None
        ),
        "usage": result.usage.model_dump(mode="json"),
    }


def _main_turn_summary_from_scene_events(scene_events: list[SceneEvent]) -> MainTurnSummary | None:
    event = next((item for item in scene_events if item.kind == "encounter_situation_update"), None)
    if event is None:
        return None
    metadata = event.metadata or {}
    if "player_situation_delta" not in metadata and "situation_value_before" not in metadata:
        return None
    before_value = metadata.get("situation_value_before")
    after_value = metadata.get("situation_value_after")
    return MainTurnSummary(
        player_situation_delta=_safe_int(metadata.get("player_situation_delta")),
        public_actor_situation_delta_total=_safe_int(metadata.get("public_actor_situation_delta_total")),
        world_push_situation_delta_total=_safe_int(metadata.get("world_push_situation_delta_total")),
        turn_total_delta=_safe_int(metadata.get("turn_total_delta"), _safe_int(metadata.get("situation_delta"))),
        situation_value_before=(int(before_value) if isinstance(before_value, int) else None),
        situation_value_after=(int(after_value) if isinstance(after_value, int) else None),
    )


def _pending_response_from_state(state: PendingTurnState) -> PendingTurnContinueResponse:
    save = world.SaveFile.model_validate(state.staged_save)
    current_zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    return PendingTurnContinueResponse(
        session_id=state.session_id,
        pending_turn_id=state.pending_turn_id,
        flow_kind=state.flow_kind,
        status=state.status if state.status in {"awaiting_reaction", "completed", "cancelled"} else "awaiting_reaction",
        reply_text=state.accumulated_reply_text,
        scene_events=state.accumulated_scene_events,
        tool_events=state.accumulated_tool_events,
        main_turn_summary=_main_turn_summary_from_scene_events(state.accumulated_scene_events),
        current_zone_metric=current_zone_metric,
        pending_reaction=state.pending_reaction if state.status == "awaiting_reaction" else None,
        npc_role_id=state.npc_role_id,
    )


def _npc_result_log_data(result: NpcChatResponse, usage: Usage) -> dict[str, Any]:
    return {
        "npc_role_id": result.npc_role_id,
        "reply_preview": _preview_text(result.reply),
        "time_spent_min": result.time_spent_min,
        "talkative_current": result.talkative_current,
        "scene_event_count": len(result.scene_events),
        "usage": usage.model_dump(mode="json"),
    }


def _planner_prompt(payload: ChatRequest, context_json: str) -> str:
    tool_rows = "\n".join(f"- {name}: {desc}" for name, desc in _PLANNER_TOOLS.items())
    return (
        "You are a tool planner for one roleplay turn.\n"
        "Return JSON only.\n"
        'Schema: {"tools":[{"tool_name":"...","args":{}}]}\n'
        "If the current context is enough, return an empty tools array.\n"
        "You may select at most 3 tools.\n"
        "Only choose from these tools:\n"
        f"{tool_rows}\n"
        "Most tools are read-only. Allowed state mutations are spawn_scene_npc, inventory_grant_item, inventory_consume_item, and execute_interaction. spawn_scene_npc may be used at most once when a new NPC must enter the current scene.\n"
        "Current structured context:\n"
        f"{context_json}\n"
        "Latest player message:\n"
        f"{payload.messages[-1].content}"
    )


def _final_reply_prompt(
    *,
    payload: ChatRequest,
    context_json: str,
    tool_results: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    audience_context: dict[str, Any],
) -> str:
    candidates = [
        {
            "actor_id": str(item.get("actor_id") or ""),
            "name": str(item.get("name") or ""),
            "actor_type": str(item.get("actor_type") or "npc"),
            "affiliation_kind": public_scene_runtime.actor_affiliation(item)[0],
            "affiliation_label": public_scene_runtime.actor_affiliation(item)[1],
            "may_answer_team_directive": str(item.get("actor_type") or "npc") == "team",
            "is_explicitly_addressed": public_scene_runtime.actor_is_explicitly_addressed(item, audience_context),
            "response_scope": str(audience_context.get("scope") or "public_broadcast"),
            "priority_reason": str(item.get("priority_reason") or ""),
            "roleplay_brief": public_scene_legacy._actor_roleplay_brief(item),
        }
        for item in candidate_rows
    ]
    return (
        "You are the GM for one tabletop roleplay turn.\n"
        "Output exactly this tagged format and nothing else:\n"
        "<reply>visible GM narration in Simplified Chinese</reply>"
        "<turn_bundle>{JSON}</turn_bundle>\n"
        "turn_bundle schema:\n"
        '{"public_actor_updates":[{"actor_id":"","actor_type":"npc|team|encounter_temp_npc",'
        '"action_reaction":"","speech_reply":"","response_mode":"respond|ignore|none",'
        '"target_label":"","specific_threat":"","outcome_certainty":"certain|uncertain","action_type":"check|attack|item_use",'
        '"planned_ability_used":"strength|dexterity|constitution|intelligence|wisdom|charisma",'
        '"planned_dc":10,"planned_time_spent_min":1,"planned_check_task":"",'
        '"situation_delta_hint":0,"relation_delta_hint":0,"reputation_delta_hint":0}],'
        '"public_round_resolution":"",'
        '"encounter_update":{"summary":"","situation_delta_hint":0,"step_kind":"gm_update|resolution|world_push","termination_updates":[],"world_pushes":[{"push_kind":"new_clue|environment_shift|hazard_escalation|pressure_release|faction_move|npc_arrival","title":"","detail":"","opened_window":"","pressure_note":"","situation_delta_hint":0,"spawn_npc":{"name":"","title":"","description":"","speaking_style":"","agenda":"","appearance":"","alignment":"","likes":[]}}]},'
        '"player_reaction_check":{"source_kind":"npc_action|environment|world_push|encounter_effect|npc_chat|map_arrival","source_actor_id":"","source_actor_name":"","source_label":"","trigger_summary":"","threatened_consequence":"","ability_used":"dexterity","dc":12,"check_task":"","success_hint":"","failure_hint":"","critical_success_hint":"","critical_failure_hint":""}}'
        "\nRules:\n"
        "1. All visible text must be Simplified Chinese.\n"
        "2. reply is only the GM visible narration.\n"
        "3. public_actor_updates may only reference supplied actor ids.\n"
        "4. If no actor reacts, return an empty array and empty public_round_resolution.\n"
        "5. If there is no active encounter, encounter_update.summary must be empty.\n"
        "6. public_round_resolution must summarize the state change and next opening. Do not repeat each actor's line.\n"
        "7. world_pushes are the world or scene moving on its own after player and NPC actions.\n"
        "8. Only team actors may speak from a teammate perspective. Public NPCs and encounter NPCs must never present themselves as teammates.\n"
        "9. If the player is speaking to the team, non-team actors may only react as bystanders and should avoid direct answer lines.\n"
        "10. If an uncertain hostile or risky effect directly targets the player, emit player_reaction_check and stop before writing the final consequence.\n"
        "11. Each segment may contain at most one player_reaction_check.\n"
        "12. Keep the bundle compact, concrete, and machine-parseable.\n"
        "Structured context:\n"
        f"{context_json}\n"
        "Audience context:\n"
        f"{_json_text(audience_context)}\n"
        "Planner tool results:\n"
        f"{_json_text(tool_results)}\n"
        "Public actor candidates:\n"
        f"{_json_text(candidates)}\n"
        "Latest player input:\n"
        f"{payload.messages[-1].content}"
    )


def _main_turn_segment_prompt(
    *,
    payload: ChatRequest,
    context_json: str,
    tool_results: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    audience_context: dict[str, Any],
) -> str:
    candidates = [
        {
            "actor_id": str(item.get("actor_id") or ""),
            "name": str(item.get("name") or ""),
            "actor_type": str(item.get("actor_type") or "npc"),
            "affiliation_kind": public_scene_runtime.actor_affiliation(item)[0],
            "affiliation_label": public_scene_runtime.actor_affiliation(item)[1],
            "may_answer_team_directive": str(item.get("actor_type") or "npc") == "team",
            "is_explicitly_addressed": public_scene_runtime.actor_is_explicitly_addressed(item, audience_context),
            "response_scope": str(audience_context.get("scope") or "public_broadcast"),
            "priority_reason": str(item.get("priority_reason") or ""),
            "roleplay_brief": public_scene_legacy._actor_roleplay_brief(item),
        }
        for item in candidate_rows
    ]
    return (
        "You are the GM for one tabletop roleplay turn.\n"
        "Return one JSON object that matches the MainTurnSegment schema.\n"
        "Field guide:\n"
        "reply_text: visible GM narration in Simplified Chinese.\n"
        "public_actor_updates: structured public actor reactions for this segment.\n"
        "public_round_resolution: GM summary for this segment.\n"
        "encounter_update: structured encounter progress for this segment.\n"
        "player_reaction_check: null unless the player is directly targeted by an uncertain hostile or risky effect.\n"
        "segment_status: completed or awaiting_reaction.\n"
        "Rules:\n"
        "1. All visible text must be Simplified Chinese.\n"
        "2. reply_text is only the GM visible narration.\n"
        "3. public_actor_updates may only reference supplied actor ids.\n"
        "4. If no actor reacts, return an empty array and empty public_round_resolution.\n"
        "5. If there is no active encounter, encounter_update.summary must be empty.\n"
        "6. public_round_resolution must summarize the state change and next opening. Do not repeat each actor's line.\n"
        "7. world_pushes are the world or scene moving on its own after player and NPC actions.\n"
        "8. Only team actors may speak from a teammate perspective. Public NPCs and encounter NPCs must never present themselves as teammates.\n"
        "9. If the player is speaking to the team, non-team actors may only react as bystanders and should avoid direct answer lines.\n"
        "10. If an uncertain hostile or risky effect directly targets the player, emit player_reaction_check, set segment_status to awaiting_reaction, and stop before writing the final consequence.\n"
        "11. Each segment may contain at most one player_reaction_check.\n"
        "12. Keep the object compact, concrete, and machine-parseable.\n"
        "Structured context:\n"
        f"{context_json}\n"
        "Audience context:\n"
        f"{_json_text(audience_context)}\n"
        "Planner tool results:\n"
        f"{_json_text(tool_results)}\n"
        "Public actor candidates:\n"
        f"{_json_text(candidates)}\n"
        "Latest player input:\n"
        f"{payload.messages[-1].content}"
    )


def _npc_reply_prompt(req: NpcChatRequest, role, save) -> str:
    intent = world._parse_player_intent(req.player_message)
    action_check = intent["action_check"] if isinstance(intent["action_check"], dict) else None
    knowledge = build_npc_knowledge_snapshot(save, role.role_id)
    world_time_text, _ = world._world_time_payload(save.area_snapshot.clock)
    context = world._build_npc_prompt_context(role, save.area_snapshot.clock, save=save)
    conversation_state = world._npc_conversation_state_summary(role)
    return (
        "You are one NPC in a one-on-one roleplay conversation.\n"
        "Output exactly this tagged format and nothing else:\n"
        "<reply>final visible reply in Simplified Chinese</reply>"
        '<npc_bundle>{"action_reaction":"","speech_reply":"","relation_tag":"ally|friendly|met|neutral|wary|hostile","player_reaction_check":{"source_kind":"npc_action|environment|world_push|encounter_effect|npc_chat|map_arrival","source_actor_id":"","source_actor_name":"","source_label":"","trigger_summary":"","threatened_consequence":"","ability_used":"dexterity","dc":12,"check_task":"","success_hint":"","failure_hint":"","critical_success_hint":"","critical_failure_hint":""}}</npc_bundle>\n'
        "Rules:\n"
        "1. reply must stay consistent with npc_bundle.action_reaction and npc_bundle.speech_reply.\n"
        "2. action_reaction must include a visible gesture, posture, or expression.\n"
        "3. If the player asked a direct question, speech_reply should answer it.\n"
        "4. Do not mention entities outside the knowledge boundary.\n"
        "5. If the NPC or environment directly targets the player with an uncertain outcome, emit player_reaction_check and stop before the final consequence.\n"
        "6. All visible text must be Simplified Chinese.\n"
        f"NPC info: name={role.name}, personality={role.personality}, speaking_style={role.speaking_style}, background={role.background}, cognition={role.cognition}\n"
        f"World time: {world_time_text}\n"
        f"Talkative: {role.talkative_current}/{role.talkative_maximum}\n"
        f"Conversation state:\n{conversation_state}\n"
        f"Knowledge rules:\n{_json_text(knowledge.response_rules)}\n"
        f"Recent dialogue:\n{context}\n"
        f"Player action: {intent['action_text'] or 'none'}\n"
        f"Player speech: {intent['speech_text'] or 'none'}\n"
        f"Player action check: {_json_text(action_check or {'status': 'none'})}\n"
        f"Player full input: {intent['display_text'] or req.player_message}"
    )


def _npc_segment_prompt(req: NpcChatRequest, role, save) -> str:
    intent = world._parse_player_intent(req.player_message)
    action_check = intent["action_check"] if isinstance(intent["action_check"], dict) else None
    knowledge = build_npc_knowledge_snapshot(save, role.role_id)
    world_time_text, _ = world._world_time_payload(save.area_snapshot.clock)
    context = world._build_npc_prompt_context(role, save.area_snapshot.clock, save=save)
    conversation_state = world._npc_conversation_state_summary(role)
    return (
        "You are one NPC in a one-on-one roleplay conversation.\n"
        "Return one JSON object that matches the NpcChatSegment schema.\n"
        "Field guide:\n"
        "reply_text: final visible reply in Simplified Chinese.\n"
        "npc_bundle.action_reaction: visible gesture, posture, or expression.\n"
        "npc_bundle.speech_reply: direct spoken reply.\n"
        "npc_bundle.relation_tag: ally|friendly|met|neutral|wary|hostile.\n"
        "player_reaction_check: null unless the NPC or environment directly targets the player with an uncertain outcome.\n"
        "segment_status: completed or awaiting_reaction.\n"
        "Rules:\n"
        "1. reply_text must stay consistent with npc_bundle.action_reaction and npc_bundle.speech_reply.\n"
        "2. action_reaction must include a visible gesture, posture, or expression.\n"
        "3. If the player asked a direct question, speech_reply should answer it.\n"
        "4. Do not mention entities outside the knowledge boundary.\n"
        "5. If the NPC or environment directly targets the player with an uncertain outcome, emit player_reaction_check, set segment_status to awaiting_reaction, and stop before the final consequence.\n"
        "6. All visible text must be Simplified Chinese.\n"
        f"NPC info: name={role.name}, personality={role.personality}, speaking_style={role.speaking_style}, background={role.background}, cognition={role.cognition}\n"
        f"World time: {world_time_text}\n"
        f"Talkative: {role.talkative_current}/{role.talkative_maximum}\n"
        f"Conversation state:\n{conversation_state}\n"
        f"Knowledge rules:\n{_json_text(knowledge.response_rules)}\n"
        f"Recent dialogue:\n{context}\n"
        f"Player action: {intent['action_text'] or 'none'}\n"
        f"Player speech: {intent['speech_text'] or 'none'}\n"
        f"Player action check: {_json_text(action_check or {'status': 'none'})}\n"
        f"Player full input: {intent['display_text'] or req.player_message}"
    )


def _main_turn_continue_prompt(
    *,
    payload: ChatRequest,
    context_json: str,
    accumulated_reply_text: str,
    scene_events: list[SceneEvent],
    reaction_check: PlayerReactionCheck,
    reaction_result_text: str,
    audience_context: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> str:
    candidates = [
        {
            "actor_id": str(item.get("actor_id") or ""),
            "name": str(item.get("name") or ""),
            "actor_type": str(item.get("actor_type") or "npc"),
            "affiliation_kind": public_scene_runtime.actor_affiliation(item)[0],
            "affiliation_label": public_scene_runtime.actor_affiliation(item)[1],
            "response_scope": str(audience_context.get("scope") or "public_broadcast"),
        }
        for item in candidate_rows
    ]
    prior_scene_events = [item.model_dump(mode="json") for item in scene_events[-8:]]
    return (
        "Continue the same tabletop roleplay turn after the player's reaction save has already been resolved.\n"
        "Output exactly this tagged format and nothing else:\n"
        "<reply>new visible GM narration in Simplified Chinese only for the continuation</reply>"
        "<turn_bundle>{JSON}</turn_bundle>\n"
        "turn_bundle schema is identical to the original turn_bundle, including optional player_reaction_check.\n"
        "Rules:\n"
        "1. Do not repeat already visible narration or scene events.\n"
        "2. Treat the reaction result as already visible and continue from after it.\n"
        "3. If another uncertain hostile or risky effect directly targets the player, you may emit exactly one new player_reaction_check.\n"
        "4. If you emit player_reaction_check, stop before writing its final consequence.\n"
        "5. All visible text must be Simplified Chinese.\n"
        "Structured context:\n"
        f"{context_json}\n"
        "Already visible reply:\n"
        f"{accumulated_reply_text}\n"
        "Already visible scene events:\n"
        f"{_json_text(prior_scene_events)}\n"
        "Resolved player reaction:\n"
        f"{_json_text({'reaction': reaction_check.model_dump(mode='json'), 'result_text': reaction_result_text})}\n"
        "Audience context:\n"
        f"{_json_text(audience_context)}\n"
        "Public actor candidates:\n"
        f"{_json_text(candidates)}\n"
        "Latest player input:\n"
        f"{payload.messages[-1].content}"
    )


def _main_turn_continue_segment_prompt(
    *,
    payload: ChatRequest,
    context_json: str,
    accumulated_reply_text: str,
    scene_events: list[SceneEvent],
    reaction_check: PlayerReactionCheck,
    reaction_result_text: str,
    audience_context: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> str:
    candidates = [
        {
            "actor_id": str(item.get("actor_id") or ""),
            "name": str(item.get("name") or ""),
            "actor_type": str(item.get("actor_type") or "npc"),
            "affiliation_kind": public_scene_runtime.actor_affiliation(item)[0],
            "affiliation_label": public_scene_runtime.actor_affiliation(item)[1],
            "response_scope": str(audience_context.get("scope") or "public_broadcast"),
        }
        for item in candidate_rows
    ]
    prior_scene_events = [item.model_dump(mode="json") for item in scene_events[-8:]]
    return (
        "Continue the same tabletop roleplay turn after the player's reaction save has already been resolved.\n"
        "Return one JSON object that matches the MainTurnSegment schema.\n"
        "Rules:\n"
        "1. Do not repeat already visible narration or scene events.\n"
        "2. Treat the reaction result as already visible and continue from after it.\n"
        "3. If another uncertain hostile or risky effect directly targets the player, you may emit exactly one new player_reaction_check and set segment_status to awaiting_reaction.\n"
        "4. If you emit player_reaction_check, stop before writing its final consequence.\n"
        "5. All visible text must be Simplified Chinese.\n"
        "Structured context:\n"
        f"{context_json}\n"
        "Already visible reply:\n"
        f"{accumulated_reply_text}\n"
        "Already visible scene events:\n"
        f"{_json_text(prior_scene_events)}\n"
        "Resolved player reaction:\n"
        f"{_json_text({'reaction': reaction_check.model_dump(mode='json'), 'result_text': reaction_result_text})}\n"
        "Audience context:\n"
        f"{_json_text(audience_context)}\n"
        "Public actor candidates:\n"
        f"{_json_text(candidates)}\n"
        "Latest player input:\n"
        f"{payload.messages[-1].content}"
    )


def _npc_continue_prompt(
    req: NpcChatRequest,
    role,
    save,
    *,
    accumulated_reply_text: str,
    scene_events: list[SceneEvent],
    reaction_check: PlayerReactionCheck,
    reaction_result_text: str,
) -> str:
    intent = world._parse_player_intent(req.player_message)
    context = world._build_npc_prompt_context(role, save.area_snapshot.clock, save=save)
    prior_scene_events = [item.model_dump(mode="json") for item in scene_events[-8:]]
    return (
        "Continue the same one-on-one roleplay conversation after the player's reaction save has already been resolved.\n"
        "Output exactly this tagged format and nothing else:\n"
        "<reply>new visible reply in Simplified Chinese only for the continuation</reply>"
        '<npc_bundle>{"action_reaction":"","speech_reply":"","relation_tag":"ally|friendly|met|neutral|wary|hostile","player_reaction_check":{"source_kind":"npc_action|environment|world_push|encounter_effect|npc_chat|map_arrival","source_actor_id":"","source_actor_name":"","source_label":"","trigger_summary":"","threatened_consequence":"","ability_used":"dexterity","dc":12,"check_task":"","success_hint":"","failure_hint":"","critical_success_hint":"","critical_failure_hint":""}}</npc_bundle>\n'
        "Rules:\n"
        "1. Do not repeat already visible text.\n"
        "2. Treat the supplied reaction result as already visible and continue from after it.\n"
        "3. If another uncertain hostile or risky effect directly targets the player, you may emit exactly one new player_reaction_check.\n"
        "4. If you emit player_reaction_check, stop before the final consequence.\n"
        "5. All visible text must be Simplified Chinese.\n"
        f"Recent dialogue:\n{context}\n"
        f"Already visible reply:\n{accumulated_reply_text}\n"
        f"Already visible scene events:\n{_json_text(prior_scene_events)}\n"
        f"Resolved player reaction:\n{_json_text({'reaction': reaction_check.model_dump(mode='json'), 'result_text': reaction_result_text})}\n"
        f"Player full input: {intent['display_text'] or req.player_message}"
    )


def _npc_continue_segment_prompt(
    req: NpcChatRequest,
    role,
    save,
    *,
    accumulated_reply_text: str,
    scene_events: list[SceneEvent],
    reaction_check: PlayerReactionCheck,
    reaction_result_text: str,
) -> str:
    intent = world._parse_player_intent(req.player_message)
    context = world._build_npc_prompt_context(role, save.area_snapshot.clock, save=save)
    prior_scene_events = [item.model_dump(mode="json") for item in scene_events[-8:]]
    return (
        "Continue the same one-on-one roleplay conversation after the player's reaction save has already been resolved.\n"
        "Return one JSON object that matches the NpcChatSegment schema.\n"
        "Rules:\n"
        "1. Do not repeat already visible text.\n"
        "2. Treat the supplied reaction result as already visible and continue from after it.\n"
        "3. If another uncertain hostile or risky effect directly targets the player, you may emit exactly one new player_reaction_check and set segment_status to awaiting_reaction.\n"
        "4. If you emit player_reaction_check, stop before the final consequence.\n"
        "5. All visible text must be Simplified Chinese.\n"
        f"Recent dialogue:\n{context}\n"
        f"Already visible reply:\n{accumulated_reply_text}\n"
        f"Already visible scene events:\n{_json_text(prior_scene_events)}\n"
        f"Resolved player reaction:\n{_json_text({'reaction': reaction_check.model_dump(mode='json'), 'result_text': reaction_result_text})}\n"
        f"Player full input: {intent['display_text'] or req.player_message}"
    )


async def _plan_tools(payload: ChatRequest, context_json: str) -> list[dict[str, Any]]:
    client = _require_async_client(payload.config)
    debug_log = current_generation_debug_log()
    response = await client.chat.completions.create(
        model=payload.config.model,
        **build_completion_options(payload.config),
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": _planner_prompt(payload, context_json)},
        ],
    )
    content = (response.choices[0].message.content or "").strip()
    if debug_log is not None:
        debug_log.record("tool_planner_raw", "planner response received", {"content": content})
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        parsed = json.loads(content or '{"tools":[]}')
        tools = parsed.get("tools") if isinstance(parsed, dict) else []
        if not isinstance(tools, list):
            raise StreamProtocolError("tool planner must return tools[]")
        normalized: list[dict[str, Any]] = []
        for raw in tools[:3]:
            if not isinstance(raw, dict):
                raise StreamProtocolError("tool planner returned invalid entry")
            tool_name = str(raw.get("tool_name") or "").strip()
            if tool_name not in _PLANNER_TOOLS:
                raise StreamProtocolError(f"tool planner returned unsupported tool: {tool_name}")
            args = raw.get("args")
            if args is None:
                args = {}
            if not isinstance(args, dict):
                raise StreamProtocolError(f"tool planner args must be object: {tool_name}")
            normalized.append({"tool_name": tool_name, "args": args})
    except Exception as exc:
        if debug_log is not None:
            debug_log.record("tool_planner_error", str(exc), {"content": content})
        raise
    if debug_log is not None:
        debug_log.record("tool_planner_parsed", "planner tools parsed", {"tools": normalized})
    return normalized


async def _execute_planned_tools(
    payload: ChatRequest,
    planned_tools: list[dict[str, Any]],
    *,
    emit: EmitCallback | None,
) -> tuple[list[ToolEvent], list[dict[str, Any]]]:
    events: list[ToolEvent] = []
    results: list[dict[str, Any]] = []
    debug_log = current_generation_debug_log()
    spawned_scene_npc = False
    for index, planned in enumerate(planned_tools, start=1):
        tool_name = str(planned["tool_name"])
        args = dict(planned["args"])
        if tool_name == "spawn_scene_npc" and spawned_scene_npc:
            event = ToolEvent(tool_name="spawn_scene_npc", ok=False, summary="spawn_scene_npc may be used at most once per turn")
            events.append(event)
            await _emit_tool(emit, tool_name=event.tool_name, status="failed", summary=event.summary, payload={})
            results.append({"tool_name": event.tool_name, "summary": event.summary, "result": {"ok": False, "error": "spawn_scene_npc_limit"}})
            if debug_log is not None:
                debug_log.record("tool_result", event.summary, {"tool_name": event.tool_name, "result": {"ok": False, "error": "spawn_scene_npc_limit"}})
            continue
        await _emit_tool(emit, tool_name=tool_name, status="running", summary="running", payload={})
        tool_call = SimpleNamespace(
            id=f"planner_{index}",
            function=SimpleNamespace(name=tool_name, arguments=json.dumps(args, ensure_ascii=False)),
        )
        tool_msg, event = await chat_legacy._handle_tool_call(payload, tool_call)
        if tool_name == "spawn_scene_npc" and event.ok:
            spawned_scene_npc = True
        events.append(event)
        status = "done" if event.ok else "failed"
        await _emit_tool(emit, tool_name=event.tool_name, status=status, summary=event.summary, payload=event.payload)
        content = tool_msg.get("content") if isinstance(tool_msg, dict) else "{}"
        try:
            parsed = json.loads(str(content or "{}"))
        except Exception:
            parsed = {"ok": False, "raw": content}
        if not event.ok:
            parsed = {"ok": False, "error": event.summary, "args": args}
        result_entry = {"tool_name": event.tool_name, "summary": event.summary, "result": parsed}
        results.append(result_entry)
        if debug_log is not None:
            debug_log.record("tool_result", event.summary, result_entry)
    return events, results


async def _stream_tagged_completion(
    *,
    client: AsyncOpenAI,
    model: str,
    config,
    messages: list[dict[str, str]],
    bundle_tag: str,
    emit: EmitCallback | None,
    is_cancelled: Callable[[], Awaitable[bool]] | None,
) -> tuple[str, dict[str, Any], Usage]:
    parser = StreamingTurnParser(bundle_tag)
    reply_parts: list[str] = []
    usage = Usage()
    debug_log = current_generation_debug_log()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        **build_completion_options(config),
    }
    if getattr(config, "provider", "") != "gemini":
        kwargs["stream_options"] = {"include_usage": True}
    if debug_log is not None:
        debug_log.record(
            "model_stream_start",
            "streaming tagged completion",
            {"bundle_tag": bundle_tag, "model": model, "message_count": len(messages)},
        )
    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            await _check_cancelled(is_cancelled)
            usage = _sum_usage(usage, _usage_from_chunk(chunk))
            text = _extract_chunk_text(chunk)
            for piece in parser.feed(text):
                reply_parts.append(piece)
                if emit is not None:
                    await emit("delta", {"content": piece})
    except Exception as exc:
        if debug_log is not None:
            debug_log.record(
                "model_stream_error",
                str(exc),
                {"bundle_tag": bundle_tag, "reply_preview": "".join(reply_parts), "usage": usage},
            )
        raise
    try:
        bundle = parser.require_bundle()
    except Exception as exc:
        if debug_log is not None:
            debug_log.record(
                "model_output_error",
                str(exc),
                {
                    "bundle_tag": bundle_tag,
                    "reply_preview": "".join(reply_parts),
                    "bundle_buffer": parser.bundle_buffer,
                },
            )
        raise
    if debug_log is not None:
        debug_log.record(
            "model_output",
            "tagged completion parsed",
            {"bundle_tag": bundle_tag, "reply_preview": "".join(reply_parts), "bundle": bundle, "usage": usage},
        )
    return "".join(reply_parts).strip(), bundle, usage


def _tool_events_from_routed(routed: dict[str, Any]) -> list[ToolEvent]:
    return list(routed.get("tool_events") or [])


def _scene_events_from_routed(routed: dict[str, Any]) -> list[SceneEvent]:
    return list(routed.get("scene_events") or [])


def _compose_actor_event_text(actor_name: str, action_reaction: str, speech_reply: str) -> str:
    parts = []
    if action_reaction.strip():
        parts.append(f"{actor_name}{action_reaction.strip()}")
    if speech_reply.strip():
        parts.append(f"{actor_name}璇达細{speech_reply.strip()}")
    return " ".join(parts).strip()[:320]


def _normalize_public_actor_updates(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    raw = bundle.get("public_actor_updates")
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def _normalize_encounter_update(bundle: dict[str, Any]) -> dict[str, Any]:
    raw = bundle.get("encounter_update")
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_player_reaction_check(bundle: dict[str, Any], *, resolution_context: str) -> PlayerReactionCheck | None:
    raw = bundle.get("player_reaction_check")
    if not isinstance(raw, dict):
        return None
    return reaction_check_service.build_player_reaction_check(raw, resolution_context=resolution_context)


def _structured_output_mode(config) -> str:
    mode = str(getattr(getattr(config, "runtime", None), "structured_output_mode", "auto") or "auto").strip().lower()
    return mode if mode in {"auto", "legacy_tags"} else "auto"


def _use_legacy_tag_protocol(config) -> bool:
    return _structured_output_mode(config) == "legacy_tags"


def _bundle_from_main_turn_segment(segment) -> dict[str, Any]:
    return {
        "public_actor_updates": [dict(item) for item in list(getattr(segment, "public_actor_updates", []) or [])],
        "public_round_resolution": str(getattr(segment, "public_round_resolution", "") or ""),
        "encounter_update": dict(getattr(segment, "encounter_update", {}) or {}),
        "player_reaction_check": (
            getattr(segment, "player_reaction_check", None).model_dump(mode="json")
            if getattr(segment, "player_reaction_check", None) is not None
            else None
        ),
    }


def _bundle_from_npc_segment(segment) -> dict[str, Any]:
    npc_bundle = getattr(segment, "npc_bundle", None)
    bundle = npc_bundle.model_dump(mode="json") if npc_bundle is not None else {}
    bundle["player_reaction_check"] = (
        getattr(segment, "player_reaction_check", None).model_dump(mode="json")
        if getattr(segment, "player_reaction_check", None) is not None
        else None
    )
    return bundle


def _fallback_public_round_resolution(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    total_delta = sum(_safe_int(record.get("situation_delta")) for record in records)
    target = next(
        (
            str(record.get("target_label") or record.get("specific_threat") or "").strip()
            for record in records
            if str(record.get("target_label") or record.get("specific_threat") or "").strip()
        ),
        "眼前局面",
    )
    if total_delta > 0:
        summary = f"这一轮公开行动把{target}附近最直接的风险往下压了一截，现场暂时出现了新的处理窗口。"
    elif total_delta < 0:
        summary = f"这一轮公开行动没能压住{target}周围的险情，局面被进一步推向更危险的方向。"
    else:
        summary = f"这一轮公开行动把手都伸到了{target}附近，但现场暂时仍维持在僵持状态。"
    return summary[:320]


def _append_reply_segment(base: str, segment: str) -> str:
    clean_base = str(base or "").strip()
    clean_segment = str(segment or "").strip()
    if not clean_segment:
        return clean_base
    if not clean_base:
        return clean_segment
    return f"{clean_base}\n{clean_segment}".strip()


def _merge_usage(left: Usage | None, right: Usage | None) -> Usage:
    return Usage(
        input_tokens=int((left.input_tokens if left is not None else 0) + (right.input_tokens if right is not None else 0)),
        output_tokens=int((left.output_tokens if left is not None else 0) + (right.output_tokens if right is not None else 0)),
    )


def _fallback_public_actor_rows(save) -> list[dict[str, Any]]:
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    current_zone_id = save.area_snapshot.current_zone_id
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_row(row: dict[str, Any]) -> None:
        actor_id = str(row.get("actor_id") or "").strip()
        if not actor_id or actor_id in seen_ids:
            return
        seen_ids.add(actor_id)
        rows.append(row)

    for role in public_scene_legacy._visible_public_roles(save):
        add_row({"actor_id": role.role_id, "name": role.name, "actor_type": "npc", "priority_reason": "visible_public_role", "role": role})
    for role in save.role_pool:
        if role.state == "in_team" or role.role_id in seen_ids:
            continue
        if current_sub_zone_id and role.sub_zone_id == current_sub_zone_id:
            add_row({"actor_id": role.role_id, "name": role.name, "actor_type": "npc", "priority_reason": "local_sub_zone_role", "role": role})
            continue
        if not current_sub_zone_id and current_zone_id and role.zone_id == current_zone_id:
            add_row({"actor_id": role.role_id, "name": role.name, "actor_type": "npc", "priority_reason": "local_zone_role", "role": role})
    for role in public_scene_legacy._team_role_map(save).values():
        add_row({"actor_id": role.role_id, "name": role.name, "actor_type": "team", "priority_reason": "team_presence", "role": role})
    for temp in public_scene_legacy._encounter_temp_npcs(save):
        add_row(
            {
                "actor_id": temp.encounter_npc_id,
                "name": temp.name,
                "actor_type": "encounter_temp_npc",
                "priority_reason": "encounter_temp_presence",
                "temp_npc": temp,
            }
        )
    return rows


def _current_active_encounter(save):
    state = encounter_legacy._state(save)
    return state, encounter_legacy._current_active_encounter(state)


async def _run_deterministic_intent_route(payload: ChatRequest, parsed_intent: dict[str, Any]) -> dict[str, Any]:
    save = world.get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
        world.save_current(save)
    action_text = str(parsed_intent.get("action_text") or "").strip()
    speech_text = str(parsed_intent.get("speech_text") or "").strip()
    display_text = str(parsed_intent.get("display_text") or "").strip()
    addressed_role_name = str(parsed_intent.get("addressed_role_name") or "").strip()
    merged = "\n".join(part for part in [action_text, speech_text, display_text] if part).strip()
    active_encounter = world._active_encounter_for_current_sub_zone(save)
    tool_events: list[ToolEvent] = []

    if bool(parsed_intent.get("passive_turn")):
        tool_events.append(ToolEvent(tool_name="route_main_turn_intent", ok=True, summary="passive turn"))
        return {
            "handled": True,
            "reply": Message(role="assistant", content="你暂时按住动作，让当前局势自行推进一轮。"),
            "tool_events": tool_events,
            "scene_events": [],
            "time_spent_min": 1,
            "skip_encounter_main_chat_advance": False,
        }

    if chat_legacy._contains_any_token(merged, ["前往", "去", "移动到", "进入", "赶去", "travel", "move", "go to"]):
        sub_zone = chat_legacy._find_sub_zone_target(save, merged)
        if sub_zone is not None and sub_zone.sub_zone_id != save.area_snapshot.current_sub_zone_id:
            moved = chat_legacy.move_to_sub_zone(
                chat_legacy.AreaMoveSubZoneRequest(
                    session_id=payload.session_id,
                    to_sub_zone_id=sub_zone.sub_zone_id,
                    config=payload.config,
                )
            )
            tool_events.append(
                ToolEvent(tool_name="move_to_sub_zone", ok=True, summary=f"moved to {sub_zone.sub_zone_id}", payload={"duration_min": moved.duration_min})
            )
            return {
                "handled": True,
                "reply": Message(role="assistant", content=moved.movement_feedback),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": moved.duration_min,
                "skip_encounter_main_chat_advance": False,
            }
        zone = chat_legacy._find_zone_target(save, merged)
        if zone is not None:
            from_zone_id = (
                (save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None)
                or (save.map_snapshot.player_position.zone_id if save.map_snapshot.player_position else None)
                or save.area_snapshot.current_zone_id
                or zone.zone_id
            )
            moved = map_flow_service.execute_public_zone_move_turn_in_save(
                save,
                session_id=payload.session_id,
                payload=chat_legacy.MoveRequest(
                    session_id=payload.session_id,
                    from_zone_id=from_zone_id,
                    to_zone_id=zone.zone_id,
                    player_name=save.player_static_data.name,
                    config=payload.config,
                ),
                config=payload.config,
            )
            tool_events.append(
                ToolEvent(tool_name="move_to_zone", ok=True, summary=f"moved to {zone.zone_id}", payload={"duration_min": moved.duration_min})
            )
            return {
                "handled": True,
                "reply": Message(role="assistant", content=moved.narration.text or moved.movement_log.summary),
                "tool_events": tool_events,
                "scene_events": moved.scene_events,
                "time_spent_min": moved.duration_min,
                "skip_encounter_main_chat_advance": True,
                "main_turn_summary": moved.main_turn_summary,
                "current_zone_metric": moved.current_zone_metric,
            }

    if active_encounter is not None:
        if active_encounter.player_presence == "away" and chat_legacy._contains_any_token(merged, ["回去", "返回遭遇", "重新加入", "rejoin"]):
            result = chat_legacy.rejoin_encounter(
                active_encounter.encounter_id,
                chat_legacy.EncounterRejoinRequest(session_id=payload.session_id, config=payload.config),
            )
            tool_events.append(ToolEvent(tool_name="encounter_rejoin", ok=True, summary=f"rejoined {result.encounter_id}"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.reply),
                "tool_events": tool_events,
                "scene_events": chat_legacy._encounter_scene_events(result.encounter, reply=result.reply),
                "time_spent_min": 1,
                "skip_encounter_main_chat_advance": True,
            }
        if active_encounter.player_presence == "engaged" and chat_legacy._contains_any_token(merged, ["离开", "逃离", "脱身", "撤退", "escape"]):
            result = chat_legacy.escape_encounter(
                active_encounter.encounter_id,
                chat_legacy.EncounterEscapeRequest(session_id=payload.session_id, config=payload.config),
            )
            tool_events.append(ToolEvent(tool_name="encounter_escape", ok=True, summary=f"escape {'ok' if result.escape_success else 'failed'}"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.reply),
                "tool_events": tool_events,
                "scene_events": chat_legacy._encounter_scene_events(result.encounter, reply=result.reply),
                "time_spent_min": result.time_spent_min,
                "skip_encounter_main_chat_advance": True,
            }

    if chat_legacy._contains_any_token(merged, ["装备", "穿上", "拿上", "equip", "卸下", "脱下", "unequip"]):
        owner = chat_legacy.InventoryOwnerRef(owner_type="player")
        owner_role = chat_legacy._find_named_role(save, merged, team_only=True)
        owner_items = save.player_static_data.dnd5e_sheet.backpack.items
        if owner_role is not None:
            owner = chat_legacy.InventoryOwnerRef(owner_type="role", role_id=owner_role.role_id)
            owner_items = owner_role.profile.dnd5e_sheet.backpack.items
        item = chat_legacy._find_inventory_item(owner_items, merged)
        if item is not None:
            slot = "armor" if item.slot_type == "armor" or chat_legacy._contains_any_token(merged, ["护甲", "盔甲", "armor"]) else "weapon"
            if chat_legacy._contains_any_token(merged, ["装备", "穿上", "拿上", "equip"]):
                result = chat_legacy.inventory_equip(
                    chat_legacy.InventoryEquipRequest(session_id=payload.session_id, owner=owner, item_id=item.item_id, slot=slot)
                )
                tool_events.append(ToolEvent(tool_name="inventory_mutate", ok=True, summary=result.message[:80] or "equip ok"))
                return {
                    "handled": True,
                    "reply": Message(role="assistant", content=result.message or f"已装备 {item.name}。"),
                    "tool_events": tool_events,
                    "scene_events": [],
                    "time_spent_min": 1,
                    "skip_encounter_main_chat_advance": False,
                }
            result = chat_legacy.inventory_unequip(
                chat_legacy.InventoryUnequipRequest(session_id=payload.session_id, owner=owner, slot=slot)
            )
            tool_events.append(ToolEvent(tool_name="inventory_mutate", ok=True, summary=result.message[:80] or "unequip ok"))
            return {
                "handled": True,
                "reply": Message(role="assistant", content=result.message or f"已卸下 {item.name}。"),
                "tool_events": tool_events,
                "scene_events": [],
                "time_spent_min": 1,
                "skip_encounter_main_chat_advance": False,
            }

    addressed_actor = chat_legacy._find_addressed_scene_actor(save, addressed_role_name)
    if addressed_actor is not None:
        tool_events.append(ToolEvent(tool_name="route_main_turn_target_npc", ok=True, summary=f"public scene target={addressed_actor['actor_id']}"))
    return {
        "handled": False,
        "reply": None,
        "tool_events": tool_events,
        "scene_events": [],
        "time_spent_min": 0,
        "skip_encounter_main_chat_advance": False,
    }


def _apply_encounter_world_pushes(
    save,
    *,
    encounter,
    world_pushes: list[dict[str, Any]],
    config=None,
) -> list[SceneEvent]:
    scene_events: list[SceneEvent] = []
    debug_log = current_generation_debug_log()
    for push in world_pushes:
        location_payload: dict[str, object] | None = None
        raw_location_target = push.get("location_target")
        if isinstance(raw_location_target, dict):
            try:
                location_payload = world.ensure_encounter_location_target_in_save(
                    save,
                    encounter,
                    raw_location_target,
                    session_id=save.session_id or "sess_default",
                    config=config,
                )
            except Exception as exc:
                if debug_log is not None:
                    debug_log.record(
                        "encounter_world_push_location_failed",
                        str(exc),
                        {"push_kind": str(push.get("push_kind") or ""), "location_target": raw_location_target},
                    )
        spawned_role_id = ""
        spawned_name = ""
        spawn_seed = push.get("spawn_npc")
        if isinstance(spawn_seed, dict):
            try:
                spawned_role_id = encounter_legacy._spawn_persistent_encounter_npc(save, encounter, spawn_seed)
                spawned_role = next((item for item in save.role_pool if item.role_id == spawned_role_id), None)
                spawned_name = spawned_role.name if spawned_role is not None else ""
            except Exception as exc:
                if debug_log is not None:
                    debug_log.record(
                        "encounter_world_push_spawn_failed",
                        str(exc),
                        {"push_kind": str(push.get("push_kind") or ""), "spawn_seed": spawn_seed},
                    )
        moved_actor_ids: list[str] = []
        moved_to_label = ""
        if location_payload is not None:
            moved_to_label = str(location_payload.get("target_location_label") or "").strip()
            for actor_id in [str(item).strip() for item in list((raw_location_target or {}).get("move_actor_ids") or []) if str(item).strip()]:
                role = next((item for item in save.role_pool if item.role_id == actor_id), None)
                if role is not None:
                    role.zone_id = str(location_payload.get("zone_id") or role.zone_id)
                    role.sub_zone_id = str(location_payload.get("sub_zone_id") or role.sub_zone_id)
                    moved_actor_ids.append(actor_id)
                    continue
                temp_npc = next((item for item in encounter.temporary_npcs if item.encounter_npc_id == actor_id), None)
                if temp_npc is not None:
                    temp_npc.zone_id = str(location_payload.get("zone_id") or temp_npc.zone_id)
                    temp_npc.sub_zone_id = str(location_payload.get("sub_zone_id") or temp_npc.sub_zone_id)
                    moved_actor_ids.append(actor_id)
        content = _world_push_event_text(push, spawned_name=spawned_name)
        if location_payload is not None and moved_to_label and moved_to_label not in content:
            content = f"{content} 关键地点转向：{moved_to_label}".strip()
        if not content:
            continue
        encounter_legacy._append_step(
            encounter,
            kind="world_push",
            content=content,
            actor_type="system",
            actor_name="世界",
            metadata={
                "impact_summary": str(push.get("pressure_note") or push.get("opened_window") or "").strip(),
                "moved_to_zone_id": (str(location_payload.get("zone_id")) if location_payload is not None else ""),
                "moved_to_sub_zone_id": (str(location_payload.get("sub_zone_id")) if location_payload is not None else ""),
                "moved_to_label": moved_to_label,
                "affects_encounter": True,
                "source_kind": str(push.get("push_kind") or ""),
                "generated_location": bool(location_payload and (location_payload.get("generated_zone") or location_payload.get("generated_sub_zone"))),
            },
        )
        scene_events.append(
            world._new_scene_event(
                "encounter_world_push",
                content,
                actor_name="世界",
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "push_kind": str(push.get("push_kind") or ""),
                    "opened_window": str(push.get("opened_window") or ""),
                    "pressure_note": str(push.get("pressure_note") or ""),
                    "situation_delta_hint": _safe_int(push.get("situation_delta_hint")),
                    "spawned_role_id": spawned_role_id,
                    "spawned_npc_name": spawned_name,
                    "target_zone_id": (str(location_payload.get("zone_id")) if location_payload is not None else ""),
                    "target_sub_zone_id": (str(location_payload.get("sub_zone_id")) if location_payload is not None else ""),
                    "target_location_label": moved_to_label,
                    "generated_zone": bool(location_payload and location_payload.get("generated_zone")),
                    "generated_sub_zone": bool(location_payload and location_payload.get("generated_sub_zone")),
                    "moved_actor_ids": moved_actor_ids,
                },
            )
        )
        if debug_log is not None:
            debug_log.record(
                "encounter_world_push_applied",
                "encounter world push applied",
                {
                    "encounter_id": encounter.encounter_id,
                    "push_kind": str(push.get("push_kind") or ""),
                    "situation_delta_hint": _safe_int(push.get("situation_delta_hint")),
                    "spawned_role_id": spawned_role_id,
                    "target_zone_id": (str(location_payload.get("zone_id")) if location_payload is not None else ""),
                    "target_sub_zone_id": (str(location_payload.get("sub_zone_id")) if location_payload is not None else ""),
                },
            )
    return scene_events


def _apply_structured_encounter_update(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    encounter_update: dict[str, Any],
    public_total_delta: int = 0,
    round_resolution_text: str = "",
    config=None,
) -> list[SceneEvent]:
    state, encounter = _current_active_encounter(save)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return []
    if encounter.presented_at is None:
        encounter_legacy._initialize_encounter_state(save, encounter)
    parsed_intent = world._parse_player_intent(player_text)
    display_text = str(parsed_intent.get("display_text") or player_text).strip()
    world_pushes = _normalize_encounter_world_pushes(encounter_update, config=config)
    base_delta = _clamp(encounter_update.get("situation_delta_hint"), -8, 8)
    base_delta = encounter_legacy._clamp(base_delta + encounter_legacy._check_bonus_from_player_prompt(player_text), -20, 20)
    world_push_delta = sum(_safe_int(item.get("situation_delta_hint")) for item in world_pushes)
    total_delta = max(-60, min(60, base_delta + int(public_total_delta) + int(world_push_delta)))
    before_value = encounter.situation_value
    assessment = encounter_runtime.assess_situation_change(
        before_value,
        total_delta,
        encounter_legacy._clamp(before_value + total_delta, 0, 100),
    )
    reply_seed = str(encounter_update.get("summary") or "").strip() or round_resolution_text or gm_narration
    reply, next_scene_summary = encounter_runtime.concretize_encounter_reply(
        save,
        encounter,
        display_text or gm_narration,
        reply=reply_seed,
        scene_summary=encounter.scene_summary or encounter.description,
        assessment=assessment,
    )
    step_kind = str(encounter_update.get("step_kind") or "gm_update").strip()
    if step_kind not in {"gm_update", "resolution"}:
        step_kind = "gm_update"
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = encounter_legacy._utc_now()
    encounter_legacy._append_step(encounter, kind=step_kind, content=reply)
    encounter_legacy._apply_termination_updates(encounter, encounter_update.get("termination_updates"))
    assessment = encounter_runtime._update_encounter_state_with_delta(encounter, total_delta)
    situation_text = encounter_runtime._situation_event_text(assessment, reply)
    scene_events: list[SceneEvent] = [
        world._new_scene_event(
            "encounter_situation_update",
            situation_text,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value_before": before_value,
                "player_situation_delta": base_delta,
                "public_actor_situation_delta_total": int(public_total_delta),
                "world_push_situation_delta_total": int(world_push_delta),
                "turn_total_delta": total_delta,
                "situation_value_after": encounter.situation_value,
                "situation_value": encounter.situation_value,
                "situation_delta": total_delta,
                "direction": assessment.direction,
                "trend": assessment.trend,
            },
        )
    ]
    scene_events.extend(_apply_encounter_world_pushes(save, encounter=encounter, world_pushes=world_pushes, config=config))
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = encounter_legacy._finalize_encounter_if_needed(
        save,
        state,
        encounter,
        session_id=session_id,
    )
    if outcome_package is not None:
        event_kind = "encounter_resolution"
    else:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id
    state.history.append(
        EncounterResolution(
            encounter_id=encounter.encounter_id,
            player_prompt=display_text or player_text,
            reply=reply,
            time_spent_min=max(1, time_spent_min),
            quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
            situation_delta=total_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    encounter_legacy._append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        reply,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    encounter_legacy._touch_state(state)
    scene_events.append(
        world._new_scene_event(
            event_kind,
            reply,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        )
    )
    return scene_events


def _apply_structured_main_turn_bundle_result(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    bundle: dict[str, Any],
    config,
) -> BundleApplyResult:
    intent = world._parse_player_intent(player_text)
    display_text = str(intent.get("display_text") or player_text).strip()
    pending_reaction = _normalize_player_reaction_check(bundle, resolution_context="main_chat")
    audience_context = public_scene_runtime.build_public_audience_context(save, intent)
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    incoming_target_candidates = [str(item) for item in list(intent.get("incoming_target_candidates") or [])]
    candidates = public_scene_runtime.candidate_rows(
        save,
        player_text=display_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=incoming_target_candidates,
        config=config,
    )
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record(
            "public_candidates_selected",
            "selected public actor candidates",
            {
                "candidate_count": len(candidates),
                "limit": len(candidates),
                "audience_scope": str(audience_context.get("scope") or "public_broadcast"),
                "addressed_role_name": str(audience_context.get("addressed_role_name") or ""),
                "selected_actor_ids": [str(item.get("actor_id") or "") for item in candidates],
            },
        )
    candidate_map = {str(item.get("actor_id") or ""): item for item in candidates}
    fallback_actor_map = {str(item.get("actor_id") or ""): item for item in _fallback_public_actor_rows(save)}
    scene_events: list[SceneEvent] = []
    round_records: list[dict[str, Any]] = []
    reputation_delta_total = 0
    team_relation_rows: list[dict[str, Any]] = []
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = zone_metric.reputation_score if zone_metric is not None else 50
    _, active_encounter = _current_active_encounter(save)

    for update in _normalize_public_actor_updates(bundle):
        actor_id = str(update.get("actor_id") or "").strip()
        actor = candidate_map.get(actor_id)
        if actor is None:
            actor = fallback_actor_map.get(actor_id)
            if actor is not None:
                if debug_log is not None:
                    debug_log.record(
                        "public_actor_fallback",
                        "resolved actor outside candidate rows",
                        {
                            "actor_id": actor_id,
                            "actor_name": str(actor.get("name") or ""),
                            "actor_type": str(actor.get("actor_type") or "npc"),
                            "candidate_ids": list(candidate_map.keys())[:10],
                        },
                    )
            else:
                if debug_log is not None:
                    debug_log.record(
                        "public_actor_skip",
                        "skipping unknown public actor id",
                        {"actor_id": actor_id, "candidate_ids": list(candidate_map.keys())[:10]},
                    )
                continue
        actor_name = str(actor.get("name") or "")
        actor_type = str(actor.get("actor_type") or "npc")
        payload = {
            "action_summary": str(update.get("action_reaction") or "").strip(),
            "speech_summary": str(update.get("speech_reply") or "").strip(),
            "target_label": str(update.get("target_label") or "").strip(),
            "stakes": "",
            "specific_threat": str(update.get("specific_threat") or "").strip(),
        }
        response_mode = str(update.get("response_mode") or "").strip().lower() or "respond"
        if not public_scene_runtime.actor_may_speak_in_public_turn(actor, audience_context):
            if payload["speech_summary"] and debug_log is not None:
                debug_log.record(
                    "public_actor_speech_suppressed",
                    "suppressed non-allowed public actor speech",
                    {
                        "actor_id": actor_id,
                        "actor_name": actor_name,
                        "actor_type": actor_type,
                        "audience_scope": str(audience_context.get("scope") or "public_broadcast"),
                    },
                )
            payload["speech_summary"] = ""
            response_mode = "ignore"
        action_line = public_scene_legacy._compose_actor_action_line(actor, payload)
        if not action_line:
            action_line = _compose_actor_event_text(actor_name, payload["action_summary"], payload["speech_summary"])
        if not action_line:
            continue
        requires_check = _public_actor_requires_check(save, actor, update, config)
        if debug_log is not None and requires_check and not bool(update.get("needs_check")):
            debug_log.record(
                "public_actor_check_forced",
                "forced public actor check",
                {"actor_id": actor_id, "actor_name": actor_name, "reason": "uncertain_or_risky_public_action"},
            )
        public_scene_legacy._append_actor_memory(
            save,
            actor,
            display_text=display_text,
            action_line=action_line,
            priority_reason=str(actor.get("priority_reason") or ""),
        )
        action_result = None
        if requires_check:
            action_result = world.action_check(
                ActionCheckRequest(
                    session_id=session_id,
                    actor_role_id=actor_id,
                    action_type=str(update.get("action_type") or "check"),
                    action_prompt=action_line,
                    allow_backend_roll=True,
                    resolution_context="embedded",
                    planned_ability_used=_planned_ability(update.get("planned_ability_used")),
                    planned_dc=_clamp(update.get("planned_dc"), 5, 30),
                    planned_time_spent_min=_clamp(update.get("planned_time_spent_min"), 1, 180),
                    planned_requires_check=True,
                    planned_check_task=str(update.get("planned_check_task") or action_line),
                    config=config,
                )
            )
        situation_delta = public_scene_legacy._clamp(
            _clamp(update.get("situation_delta_hint"), -8, 8) + public_scene_legacy._check_bonus(action_result),
            -20,
            20,
        )
        relation_delta = _safe_int(
            update.get("relation_delta_hint"),
            public_scene_legacy._resolution_relation_delta(actor_type, action_result, situation_delta),
        )
        reputation_delta = _safe_int(
            update.get("reputation_delta_hint"),
            public_scene_legacy._resolution_reputation_delta(actor_type, situation_delta),
        )
        role = actor.get("role")
        member = _find_team_member(save, actor_id) if actor_type == "team" else None
        affinity_before = int(member.affinity) if member is not None else None
        trust_before = int(member.trust) if member is not None else None
        if role is not None and actor_type != "encounter_temp_npc":
            applied_relation = public_scene_legacy._apply_actor_relation_delta(
                save,
                role,
                actor_type,
                relation_delta,
                reputation_score,
            )
        else:
            applied_relation = 0
        affinity_after = int(member.affinity) if member is not None else None
        trust_after = int(member.trust) if member is not None else None
        affinity_delta = (
            _clamp_score(affinity_after) - _clamp_score(affinity_before)
            if affinity_before is not None and affinity_after is not None
            else None
        )
        trust_delta = (
            _clamp_score(trust_after) - _clamp_score(trust_before)
            if trust_before is not None and trust_after is not None
            else None
        )
        if member is not None and (
            (affinity_delta is not None and affinity_delta != 0) or (trust_delta is not None and trust_delta != 0)
        ):
            _append_public_turn_team_reaction(
                save,
                session_id=session_id,
                member=member,
                content=action_line,
                affinity_delta=int(affinity_delta or 0),
                trust_delta=int(trust_delta or 0),
            )
            team_relation_rows.append(
                {
                    "role_id": member.role_id,
                    "name": member.name,
                    "affinity_before": affinity_before,
                    "affinity_after": affinity_after,
                    "affinity_delta": affinity_delta or 0,
                    "trust_before": trust_before,
                    "trust_after": trust_after,
                    "trust_delta": trust_delta or 0,
                }
            )
        reputation_delta_total += reputation_delta
        affiliation_kind, affiliation_label = public_scene_runtime.actor_affiliation(actor)
        check_result = public_scene_runtime.build_public_check_result(action_result, requires_check=requires_check)
        checked_action_label = _build_checked_action_label(update, action_line)
        gm_result_summary = _build_public_gm_result_summary(
            actor_name=actor_name,
            checked_action_label=checked_action_label,
            target_label=payload["target_label"],
            specific_threat=payload["specific_threat"],
            check_result=check_result,
            situation_delta=situation_delta,
        )
        scene_events.append(
            world._new_scene_event(
                "public_actor_action",
                action_line,
                actor_role_id=actor_id,
                actor_name=actor_name,
                metadata={
                    "actor_type": actor_type,
                    "affiliation_kind": affiliation_kind,
                    "affiliation_label": affiliation_label,
                    "action_type": str(update.get("action_type") or "check"),
                    "response_mode": response_mode,
                    "target_label": payload["target_label"],
                    "specific_threat": payload["specific_threat"],
                    "external_action_narration": payload["action_summary"],
                    "speech_line": payload["speech_summary"],
                    "visible_intent": payload["target_label"] or payload["specific_threat"],
                    "situation_delta": situation_delta,
                    "checked_action_label": checked_action_label,
                    "checked_action_prompt": str(update.get("planned_check_task") or action_line)[:180],
                    "gm_result_summary": gm_result_summary,
                    "team_affinity_before": affinity_before,
                    "team_affinity_after": affinity_after,
                    "team_affinity_delta": affinity_delta,
                    "team_trust_before": trust_before,
                    "team_trust_after": trust_after,
                    "team_trust_delta": trust_delta,
                    "check_result": check_result,
                },
            )
        )
        if debug_log is not None:
            debug_log.record(
                "public_actor_resolved",
                "public actor resolved",
                {
                    "actor_id": actor_id,
                    "success": bool(check_result.get("success", False)),
                    "critical": str(check_result.get("critical") or "none"),
                    "situation_delta": situation_delta,
                },
            )
        round_records.append(
            {
                "actor_id": actor_id,
                "actor_name": actor_name,
                "actor_type": actor_type,
                "result": str(check_result.get("outcome_label") or _public_result_label(action_result, situation_delta)),
                "target_label": payload["target_label"],
                "specific_threat": payload["specific_threat"],
                "situation_delta": situation_delta,
                "relation_delta": applied_relation,
                "reputation_delta": reputation_delta,
            }
        )

    total_situation_delta = sum(int(item["situation_delta"]) for item in round_records)
    if round_records:
        resolution_text = str(bundle.get("public_round_resolution") or "").strip() or _fallback_public_round_resolution(round_records)
        if resolution_text:
            rep_entry, rep_event = zone_metric_service.apply_zone_reputation_delta(
                save,
                session_id=session_id,
                delta=public_scene_legacy._clamp(reputation_delta_total, -6, 6),
                reason="公开场景本轮结算",
                actor_name="公开场景",
                append_scene_event=bool(reputation_delta_total),
                append_log=bool(reputation_delta_total),
            )
            if rep_event is not None:
                scene_events.append(rep_event)
            reputation_score = rep_entry.reputation_score if rep_entry is not None else reputation_score
            scene_events.append(
                world._new_scene_event(
                    "public_round_resolution",
                    resolution_text,
                    actor_name="GM",
                    metadata={
                        "actor_type": "system",
                        "candidate_count": len(round_records),
                        "reputation_score": reputation_score,
                        "team_relation_rows": team_relation_rows,
                    },
                )
            )
            save.game_logs.append(
                world._new_game_log(
                    session_id,
                    "public_scene_director",
                    f"公共场景推进了 {len(round_records)} 个角色反应。",
                    {
                        "candidate_count": len(round_records),
                        "reputation_score": reputation_score,
                        "team_relation_count": len(team_relation_rows),
                        "team_relation_summary": _team_relation_summary_text(team_relation_rows),
                    },
                )
            )
            if active_encounter is None:
                encounter_result = encounter_legacy.check_for_encounter(
                    EncounterCheckRequest(session_id=session_id, trigger_kind="random_dialog", config=None)
                )
                if encounter_result.generated and encounter_result.encounter is not None:
                    scene_events.append(
                        world._new_scene_event(
                            "encounter_started",
                            f"【遭遇触发】{encounter_result.encounter.title}\n{encounter_result.encounter.description}",
                            metadata={"encounter_id": encounter_result.encounter.encounter_id, "encounter_title": encounter_result.encounter.title},
                        )
                    )

    if pending_reaction is not None:
        scene_events.append(reaction_check_service.build_reaction_trigger_event(pending_reaction))

    encounter_update = _normalize_encounter_update(bundle)
    has_world_pushes = bool(_normalize_encounter_world_pushes(encounter_update, config=config))
    has_encounter_payload = bool(
        active_encounter is not None
        and (
            str(encounter_update.get("summary") or "").strip()
            or _safe_int(encounter_update.get("situation_delta_hint")) != 0
            or has_world_pushes
            or list(encounter_update.get("termination_updates") or [])
            or total_situation_delta != 0
        )
    )
    if has_encounter_payload:
        scene_events.extend(
            _apply_structured_encounter_update(
                save,
                session_id=session_id,
                player_text=player_text,
                gm_narration=gm_narration,
                time_spent_min=time_spent_min,
                encounter_update=encounter_update,
                public_total_delta=total_situation_delta,
                round_resolution_text=(str(bundle.get("public_round_resolution") or "").strip() or _fallback_public_round_resolution(round_records)),
                config=config,
            )
        )

    advanced = encounter_runtime.advance_active_encounter_in_save(
        save,
        session_id=session_id,
        minutes_elapsed=time_spent_min,
        config=None,
    )
    if advanced is not None:
        scene_events.append(
            world._new_scene_event(
                "encounter_background",
                advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                metadata={"encounter_id": advanced.encounter_id, "encounter_title": advanced.title},
            )
        )
    return BundleApplyResult(scene_events=scene_events, pending_reaction=pending_reaction)


def apply_structured_main_turn_bundle(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    bundle: dict[str, Any],
    config,
) -> list[SceneEvent]:
    return _apply_structured_main_turn_bundle_result(
        save,
        session_id=session_id,
        player_text=player_text,
        gm_narration=gm_narration,
        time_spent_min=time_spent_min,
        bundle=bundle,
        config=config,
    ).scene_events


def _apply_structured_npc_bundle_result(
    save,
    req: NpcChatRequest,
    bundle: dict[str, Any],
    reply_text: str,
    time_spent_min: int,
    *,
    is_continuation: bool = False,
) -> NpcBundleApplyResult:
    role = next((item for item in save.role_pool if item.role_id == req.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    world._ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = world._default_world_clock()
    world._ensure_npc_role_complete(save, role)
    player = save.player_static_data
    intent = world._parse_player_intent(req.player_message)
    action_text = str(intent["action_text"])
    speech_text = str(intent["speech_text"])
    player_text = str(intent["display_text"]).strip()
    action_check = intent["action_check"] if isinstance(intent["action_check"], dict) else None
    if not is_continuation:
        world._update_npc_conversation_state_from_player(role, action_text, speech_text, player_text, scene_mode="private_chat")
        world._append_npc_dialogue(
            role=role,
            speaker="player",
            speaker_role_id=player.player_id,
            speaker_name=player.name,
            content=player_text,
            clock=save.area_snapshot.clock,
        )
    recovered_talkative = world._restore_npc_talkative(role, save.area_snapshot.clock)
    pending_reaction = _normalize_player_reaction_check(bundle, resolution_context="npc_chat")
    action_reaction, speech_reply = world._normalize_npc_reply_parts(
        role,
        action_text,
        speech_text,
        action_check,
        str(bundle.get("action_reaction") or "").strip(),
        str(bundle.get("speech_reply") or "").strip(),
        allow_action_repair=True,
        allow_speech_repair=True,
    )
    action_reaction = world._normalize_logged_speaker_content("npc", role.name, action_reaction)
    speech_reply = world._normalize_logged_speaker_content("npc", role.name, speech_reply)
    if not action_reaction and not speech_reply:
        raise world.NpcChatGenerationError("npc chat returned empty action and speech")
    talkative_delta = world._npc_talkative_delta(role, action_text, speech_text) if role.talkative_current > 0 else 0
    role.talkative_current = max(0, min(role.talkative_maximum, role.talkative_current + talkative_delta))
    role.last_private_chat_at = world._world_clock_iso(save.area_snapshot.clock)
    world._update_npc_conversation_state_from_reply(role, speech_reply, action_reaction, scene_mode="private_chat")
    reply = (reply_text or "").strip() or world._compose_npc_reply(action_reaction, speech_reply)
    if not reply:
        raise world.NpcChatGenerationError("npc chat returned empty reply")
    world._append_npc_dialogue(
        role=role,
        speaker="npc",
        speaker_role_id=role.role_id,
        speaker_name=role.name,
        content=reply,
        clock=save.area_snapshot.clock,
    )
    relation_tag = str(bundle.get("relation_tag") or "met").strip().lower()
    lower_text = player_text.lower()
    if relation_tag not in {"ally", "friendly", "met", "neutral", "wary", "hostile"}:
        relation_tag = "met"
    if relation_tag == "met" and any(token in lower_text for token in ["谢谢", "thank", "help", "帮忙", "合作"]):
        relation_tag = "friendly"
    elif any(token in lower_text for token in ["威胁", "threat", "滚开", "attack", "打"]):
        relation_tag = "hostile"
    world._upsert_npc_player_relation(role, save.player_static_data.player_id, relation_tag, "对话自动更新关系")
    now = world._utc_now()
    role.attitude_changes.append(f"{now} relation->{relation_tag}")
    role.attitude_changes = role.attitude_changes[-50:]
    role.cognition_changes.append(f"{now} 鍗曡亰璁板繂: {player_text[:48]}")
    role.cognition_changes = role.cognition_changes[-50:]
    save.game_logs.append(
        world._new_game_log(
            req.session_id,
            "npc_chat",
            f"鐜╁涓?{role.name} 瀵硅瘽",
            {"npc_role_id": role.role_id, "time_spent_min": time_spent_min, "talkative_current": role.talkative_current, "talkative_recovered": recovered_talkative},
        )
    )
    try:
        from app.services.team_service import apply_team_reactions_in_save

        apply_team_reactions_in_save(
            save,
            session_id=req.session_id,
            trigger_kind="npc_chat",
            player_text=player_text,
            summary=reply,
            exclude_role_ids={role.role_id},
        )
    except Exception:
        logger.exception("npc team reaction failed")
    scene_events: list[SceneEvent] = []
    if pending_reaction is not None:
        scene_events.append(reaction_check_service.build_reaction_trigger_event(pending_reaction))
    advanced = encounter_runtime.advance_active_encounter_in_save(
        save,
        session_id=req.session_id,
        minutes_elapsed=time_spent_min,
        config=None,
    )
    if advanced is not None:
        scene_events.append(
            world._new_scene_event(
                "encounter_background",
                advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                metadata={"encounter_id": advanced.encounter_id},
            )
        )
    response = NpcChatResponse(
        session_id=req.session_id,
        npc_role_id=role.role_id,
        reply=reply,
        action_reaction=action_reaction,
        speech_reply=speech_reply,
        talkative_current=role.talkative_current,
        talkative_maximum=role.talkative_maximum,
        time_spent_min=time_spent_min,
        dialogue_logs=role.dialogue_logs[-20:],
        scene_events=scene_events,
    )
    return NpcBundleApplyResult(response=response, pending_reaction=pending_reaction)


def apply_structured_npc_bundle(
    save,
    req: NpcChatRequest,
    bundle: dict[str, Any],
    reply_text: str,
    time_spent_min: int,
) -> NpcChatResponse:
    return _apply_structured_npc_bundle_result(save, req, bundle, reply_text, time_spent_min).response


async def run_main_turn_stream(
    payload: ChatRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> StreamResult | PendingTurnContinueResponse:
    with generation_debug_log("main_chat", payload.session_id, request_data=_main_request_log_data(payload)) as debug_log:
        debug_log.record("request", "main chat started", {"session_id": payload.session_id})
        lock = get_session_lock(payload.session_id)
        async with lock:
            with world.save_transaction(payload.session_id) as txn:
                try:
                    await _check_cancelled(is_cancelled)
                    await _emit_phase(emit, "prepare", "running", "loading save")
                    last_user = next((message for message in reversed(payload.messages) if message.role == "user"), None)
                    if last_user is None:
                        raise ValueError("LAST_USER_MESSAGE_REQUIRED")
                    parsed_intent = world._parse_player_intent(last_user.content)
                    debug_log.record(
                        "parsed_intent",
                        "parsed player intent",
                        {
                            "display_text": _preview_text(str(parsed_intent.get("display_text") or "")),
                            "speech_text": _preview_text(str(parsed_intent.get("speech_text") or "")),
                            "action_text": _preview_text(str(parsed_intent.get("action_text") or "")),
                            "passive_turn": bool(parsed_intent.get("passive_turn")),
                        },
                    )
                    save = world.get_current_save(default_session_id=payload.session_id)
                    zone_ids = {zone.zone_id for zone in save.area_snapshot.zones}
                    if payload.config is not None and zone_ids:
                        zone_metric_service.ensure_zone_metrics_for_zones(
                            save,
                            session_id=payload.session_id,
                            zone_ids=zone_ids,
                            config=payload.config,
                            seed_source="migration_backfill",
                        )
                    await _emit_phase(emit, "prepare", "done", "save ready")
                    await _emit_phase(emit, "intent_route", "running", "checking deterministic route")
                    routed = await _run_deterministic_intent_route(payload, parsed_intent)
                    tool_events = _tool_events_from_routed(routed)
                    scene_events = _scene_events_from_routed(routed)
                    debug_log.record(
                        "intent_route_result",
                        "deterministic route checked",
                        {
                            "handled": bool(routed.get("handled")),
                            "time_spent_min": int(routed.get("time_spent_min") or 0),
                            "tool_event_count": len(tool_events),
                            "scene_event_count": len(scene_events),
                        },
                    )
                    for tool_event in tool_events:
                        await _emit_tool(
                            emit,
                            tool_name=tool_event.tool_name,
                            status=("done" if tool_event.ok else "failed"),
                            summary=tool_event.summary,
                            payload=tool_event.payload,
                        )
                    usage = Usage()
                    time_spent_min = int(routed.get("time_spent_min") or 0)
                    archived_sub_zone_turn_id: str | None = None

                    if bool(parsed_intent.get("passive_turn")) and not bool(routed.get("handled")):
                        save = world.get_current_save(default_session_id=payload.session_id)
                        active_encounter = world._active_encounter_for_current_sub_zone(save)
                        if active_encounter is None or active_encounter.status != "active" or active_encounter.player_presence != "engaged":
                            raise ValueError("PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER")

                    if bool(routed.get("handled")):
                        reply_text = (routed.get("reply") or Message(role="assistant", content="")).content
                        await _emit_phase(emit, "intent_route", "done", "handled directly")
                        await _emit_phase(emit, "model_reply", "running", "streaming direct reply")
                        if emit is not None and reply_text:
                            await emit("delta", {"content": reply_text})
                        await _emit_phase(emit, "model_reply", "done", "direct reply complete")
                        debug_log.record("direct_reply", "deterministic reply emitted", {"reply_preview": _preview_text(reply_text)})
                        save = world.get_current_save(default_session_id=payload.session_id)
                        scene_context = world._build_scene_context_payload(
                            save,
                            player_text=last_user.content,
                            gm_narration=reply_text,
                            recent_turn_count=4,
                        )
                        if not bool(routed.get("skip_encounter_main_chat_advance")):
                            scene_events.extend(
                                encounter_runtime.advance_active_encounter_from_main_chat_in_save(
                                    save,
                                    session_id=payload.session_id,
                                    player_text=last_user.content,
                                    gm_narration=reply_text,
                                    time_spent_min=time_spent_min,
                                    config=None,
                                )
                            )
                        scene_events.extend(
                            public_scene_legacy.advance_public_scene_in_save(
                                save,
                                session_id=payload.session_id,
                                player_text=last_user.content,
                                gm_summary=reply_text,
                                scene_context=scene_context,
                                config=payload.config,
                            )
                        )
                        advanced = encounter_runtime.advance_active_encounter_in_save(
                            save,
                            session_id=payload.session_id,
                            minutes_elapsed=time_spent_min,
                            config=None,
                        )
                        if advanced is not None:
                            scene_events.append(
                                world._new_scene_event(
                                    "encounter_background",
                                    advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                                    metadata={"encounter_id": advanced.encounter_id, "encounter_title": advanced.title},
                                )
                            )
                    else:
                        await _emit_phase(emit, "intent_route", "done", "requires model turn")
                        time_spent_min = world.apply_speech_time(payload.session_id, last_user.content, payload.config)
                        save = world.get_current_save(default_session_id=payload.session_id)
                        context_json = world.build_main_turn_context_json(save, last_user.content, recent_turn_count=8)
                        audience_context = _public_audience_context(save, last_user.content)

                        await _emit_phase(emit, "tool_plan", "running", "planning tools")
                        planned_tools = await _plan_tools(payload, context_json)
                        await _emit_phase(emit, "tool_plan", "done", f"{len(planned_tools)} tool(s)")

                        await _emit_phase(emit, "tool_run", "running", "running planned tools")
                        planned_events, tool_results = await _execute_planned_tools(payload, planned_tools, emit=emit)
                        tool_events.extend(planned_events)
                        await _emit_phase(emit, "tool_run", "done", f"{len(planned_tools)} tool(s) done")

                        await _emit_phase(emit, "model_reply", "running", "streaming reply")
                        candidate_rows = public_scene_runtime.candidate_rows(
                            save,
                            player_text=str(parsed_intent.get("display_text") or last_user.content).strip(),
                            addressed_role_name=str(parsed_intent.get("addressed_role_name") or "").strip(),
                            incoming_target_candidates=[str(item) for item in list(parsed_intent.get("incoming_target_candidates") or [])],
                            config=payload.config,
                        )
                        debug_log.record(
                            "model_reply_context",
                            "prepared model reply context",
                            {
                                "candidate_count": len(candidate_rows),
                                "tool_result_count": len(tool_results),
                                "candidates": [
                                    {
                                        "actor_id": str(item.get("actor_id") or ""),
                                        "name": str(item.get("name") or ""),
                                        "actor_type": str(item.get("actor_type") or "npc"),
                                        "priority_reason": str(item.get("priority_reason") or ""),
                                        "affiliation_kind": public_scene_runtime.actor_affiliation(item)[0],
                                        "audience_scope": str(audience_context.get("scope") or "public_broadcast"),
                                    }
                                    for item in candidate_rows
                                ],
                            },
                        )
                        messages = [
                            {"role": "system", "content": payload.config.gm_prompt},
                            {
                                "role": "user",
                                "content": _main_turn_segment_prompt(
                                    payload=payload,
                                    context_json=context_json,
                                    tool_results=tool_results,
                                    candidate_rows=candidate_rows,
                                    audience_context=audience_context,
                                ),
                            },
                        ]

                        async def _emit_reply_piece(piece: str) -> None:
                            if emit is not None and piece:
                                await emit("delta", {"content": piece})

                        async def _check_structured_cancelled() -> None:
                            await _check_cancelled(is_cancelled)

                        if _use_legacy_tag_protocol(payload.config):
                            client = _require_async_client(payload.config)
                            reply_text, bundle, usage = await _stream_tagged_completion(
                                client=client,
                                model=payload.config.model,
                                config=payload.config,
                                messages=[
                                    {"role": "system", "content": payload.config.gm_prompt},
                                    {
                                        "role": "user",
                                        "content": _final_reply_prompt(
                                            payload=payload,
                                            context_json=context_json,
                                            tool_results=tool_results,
                                            candidate_rows=candidate_rows,
                                            audience_context=audience_context,
                                        ),
                                    },
                                ],
                                bundle_tag="turn_bundle",
                                emit=emit,
                                is_cancelled=is_cancelled,
                            )
                        else:
                            try:
                                segment_result = await structured_segment_service.stream_main_turn_segment(
                                    config=payload.config,
                                    messages=messages,
                                    emit_reply_delta=_emit_reply_piece,
                                    check_cancelled=_check_structured_cancelled,
                                )
                                reply_text = segment_result.segment.reply_text.strip()
                                bundle = _bundle_from_main_turn_segment(segment_result.segment)
                                usage = segment_result.usage
                                debug_log.record(
                                    "structured_segment",
                                    "main turn segment received",
                                    {
                                        "provider_path": segment_result.provider_path,
                                        "segment_status": getattr(segment_result.segment, "segment_status", "completed"),
                                        "synthetic_stream": segment_result.synthetic_stream,
                                    },
                                )
                            except structured_segment_service.StructuredSegmentFallbackRequired as exc:
                                debug_log.record(
                                    "structured_fallback",
                                    exc.reason,
                                    {"provider_path": exc.provider_path, "flow_kind": "main_chat"},
                                )
                                client = _require_async_client(payload.config)
                                reply_text, bundle, usage = await _stream_tagged_completion(
                                    client=client,
                                    model=payload.config.model,
                                    config=payload.config,
                                    messages=[
                                        {"role": "system", "content": payload.config.gm_prompt},
                                        {
                                            "role": "user",
                                            "content": _final_reply_prompt(
                                                payload=payload,
                                                context_json=context_json,
                                                tool_results=tool_results,
                                                candidate_rows=candidate_rows,
                                                audience_context=audience_context,
                                            ),
                                        },
                                    ],
                                    bundle_tag="turn_bundle",
                                    emit=emit,
                                    is_cancelled=is_cancelled,
                                )
                        await _emit_phase(emit, "model_reply", "done", "reply stream complete")
                        await _emit_phase(emit, "bundle_parse", "running", "applying structured bundle")
                        applied = _apply_structured_main_turn_bundle_result(
                            save,
                            session_id=payload.session_id,
                            player_text=last_user.content,
                            gm_narration=reply_text,
                            time_spent_min=time_spent_min,
                            bundle=bundle,
                            config=payload.config,
                        )
                        scene_events.extend(applied.scene_events)
                        await _emit_phase(emit, "bundle_parse", "done", "bundle parsed")
                        debug_log.record(
                            "bundle_applied",
                            "structured main turn bundle applied",
                            {"scene_event_count": len(scene_events), "time_spent_min": time_spent_min},
                        )
                        if applied.pending_reaction is not None:
                            pending_response = reaction_check_service.stage_reaction_checkpoint(
                                session_id=payload.session_id,
                                flow_kind="main_chat",
                                staged_save=txn.save.model_dump(mode="json"),
                                original_request=payload.model_dump(mode="json"),
                                accumulated_reply_text=reply_text,
                                accumulated_scene_events=scene_events,
                                accumulated_tool_events=tool_events,
                                time_spent_min=time_spent_min,
                                pending_reaction=applied.pending_reaction,
                                continuation_index=0,
                                usage=usage,
                                main_turn_summary=_main_turn_summary_from_scene_events(scene_events),
                                current_zone_metric=zone_metric_service.get_current_zone_metric(save, create=True),
                            )
                            await _emit_reaction_required(emit, pending_response)
                            debug_log.finish(
                                status="awaiting_reaction",
                                result={
                                    "pending_turn_id": pending_response.pending_turn_id,
                                    "flow_kind": pending_response.flow_kind,
                                    "reply_preview": _preview_text(pending_response.reply_text),
                                },
                            )
                            return pending_response

                    await _check_cancelled(is_cancelled)
                    await _emit_phase(emit, "apply", "running", "recording turn")
                    save = txn.save
                    save.game_logs.append(world._new_game_log(payload.session_id, "player_input", last_user.content))
                    save.game_logs.append(world._new_game_log(payload.session_id, "gm_reply", reply_text))
                    archived_sub_zone_turn_id = world._record_sub_zone_chat_turn(
                        save,
                        source="main_chat",
                        player_mode=("passive" if bool(parsed_intent.get("passive_turn")) else "active"),
                        player_action=str(parsed_intent.get("action_text") or ""),
                        player_speech=str(parsed_intent.get("speech_text") or ""),
                        player_action_check=(parsed_intent.get("action_check") if isinstance(parsed_intent.get("action_check"), dict) else None),
                        gm_narration=reply_text,
                        events=scene_events,
                    )
                    await _emit_phase(emit, "apply", "done", "turn staged")
                    await _emit_phase(emit, "commit", "running", "writing save")
                    txn.commit()
                    token_usage_store.add(payload.session_id, "chat", usage.input_tokens, usage.output_tokens)
                    await _emit_phase(emit, "commit", "done", "save committed")
                    result = StreamResult(
                        reply=reply_text,
                        usage=usage,
                        tool_events=tool_events,
                        scene_events=scene_events,
                        time_spent_min=time_spent_min,
                        archived_sub_zone_turn_id=archived_sub_zone_turn_id,
                        main_turn_summary=(
                            routed.get("main_turn_summary")
                            if isinstance(routed.get("main_turn_summary"), MainTurnSummary)
                            else _main_turn_summary_from_scene_events(scene_events)
                        ),
                        current_zone_metric=routed.get("current_zone_metric") or zone_metric_service.get_current_zone_metric(save, create=True),
                    )
                    debug_log.finish(status="success", result=_main_result_log_data(result))
                    return result
                except StreamCancelledError as exc:
                    txn.rollback()
                    await _emit_phase(emit, "rollback", "done", "cancelled")
                    await _emit_rollback(emit, "cancelled", "本轮生成已作废")
                    debug_log.finish(status="cancelled", error=exc)
                    raise
                except Exception as exc:
                    txn.rollback()
                    await _emit_phase(emit, "rollback", "done", "reverting staged turn")
                    await _emit_rollback(emit, "error", "本轮生成已作废")
                    debug_log.finish(status="error", error=exc)
                    raise


async def run_main_turn_once(payload: ChatRequest) -> ChatResponse | PendingTurnContinueResponse:
    result = await run_main_turn_stream(payload, emit=None, is_cancelled=None)
    if isinstance(result, PendingTurnContinueResponse):
        return result
    return ChatResponse(
        session_id=payload.session_id,
        reply=Message(role="assistant", content=result.reply),
        usage=result.usage,
        tool_events=result.tool_events,
        scene_events=result.scene_events,
        time_spent_min=result.time_spent_min,
        archived_sub_zone_turn_id=result.archived_sub_zone_turn_id,
        main_turn_summary=result.main_turn_summary,
        current_zone_metric=result.current_zone_metric,
    )


async def run_npc_chat_stream(
    payload: NpcChatRequest,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> NpcChatResponse | PendingTurnContinueResponse:
    with generation_debug_log("npc_chat", payload.session_id, request_data=_npc_request_log_data(payload)) as debug_log:
        debug_log.record("request", "npc chat started", {"session_id": payload.session_id, "npc_role_id": payload.npc_role_id})
        lock = get_session_lock(payload.session_id)
        async with lock:
            with world.save_transaction(payload.session_id) as txn:
                try:
                    await _check_cancelled(is_cancelled)
                    await _emit_phase(emit, "prepare", "running", "loading npc chat")
                    save = world.get_current_save(default_session_id=payload.session_id)
                    if save.session_id != payload.session_id:
                        save.session_id = payload.session_id
                    world._ensure_area_snapshot(save)
                    if save.area_snapshot.clock is None:
                        save.area_snapshot.clock = world._default_world_clock()
                    role = next((item for item in save.role_pool if item.role_id == payload.npc_role_id), None)
                    if role is None:
                        raise KeyError("ROLE_NOT_FOUND")
                    world._ensure_npc_role_complete(save, role)
                    await _emit_phase(emit, "prepare", "done", "npc ready")
                    debug_log.record(
                        "npc_prepare",
                        "npc loaded",
                        {"npc_role_id": role.role_id, "npc_name": role.name, "talkative_current": role.talkative_current},
                    )

                    time_spent_min = world.apply_speech_time(payload.session_id, payload.player_message, payload.config)
                    usage = Usage()
                    reply_text = ""
                    bundle: dict[str, Any]

                    await _emit_phase(emit, "model_reply", "running", "streaming npc reply")
                    if role.talkative_current <= 0:
                        bundle = {
                            "action_reaction": f"{role.name}明显不想继续交谈，只是移开了视线。",
                            "speech_reply": "",
                            "relation_tag": "wary",
                        }
                        reply_text = world._compose_npc_reply(bundle["action_reaction"], bundle["speech_reply"])
                        if emit is not None:
                            await emit("delta", {"content": reply_text})
                        debug_log.record("npc_reply_guard", "talkative guard reply used", {"reply_preview": _preview_text(reply_text)})
                    elif player_mentions_unknown_npc(save, role.role_id, payload.player_message):
                        bundle = {
                            "action_reaction": f"{role.name}皱起眉，像是在确认你提到的是谁。",
                            "speech_reply": npc_guard_reply(),
                            "relation_tag": "wary",
                        }
                        reply_text = world._compose_npc_reply(bundle["action_reaction"], bundle["speech_reply"])
                        if emit is not None:
                            await emit("delta", {"content": reply_text})
                        debug_log.record("npc_reply_guard", "knowledge guard reply used", {"reply_preview": _preview_text(reply_text)})
                    else:
                        if payload.config is None:
                            raise world.NpcChatConfigError("npc chat requires config with openai_api_key and model")
                        messages = [
                            {"role": "system", "content": payload.config.gm_prompt},
                            {"role": "user", "content": _npc_segment_prompt(payload, role, save)},
                        ]

                        async def _emit_reply_piece(piece: str) -> None:
                            if emit is not None and piece:
                                await emit("delta", {"content": piece})

                        async def _check_structured_cancelled() -> None:
                            await _check_cancelled(is_cancelled)

                        if _use_legacy_tag_protocol(payload.config):
                            client = _require_async_client(payload.config)
                            reply_text, bundle, usage = await _stream_tagged_completion(
                                client=client,
                                model=payload.config.model,
                                config=payload.config,
                                messages=[
                                    {"role": "system", "content": payload.config.gm_prompt},
                                    {"role": "user", "content": _npc_reply_prompt(payload, role, save)},
                                ],
                                bundle_tag="npc_bundle",
                                emit=emit,
                                is_cancelled=is_cancelled,
                            )
                        else:
                            try:
                                segment_result = await structured_segment_service.stream_npc_chat_segment(
                                    config=payload.config,
                                    messages=messages,
                                    emit_reply_delta=_emit_reply_piece,
                                    check_cancelled=_check_structured_cancelled,
                                )
                                reply_text = segment_result.segment.reply_text.strip()
                                bundle = _bundle_from_npc_segment(segment_result.segment)
                                usage = segment_result.usage
                                debug_log.record(
                                    "structured_segment",
                                    "npc chat segment received",
                                    {
                                        "provider_path": segment_result.provider_path,
                                        "segment_status": getattr(segment_result.segment, "segment_status", "completed"),
                                        "synthetic_stream": segment_result.synthetic_stream,
                                    },
                                )
                            except structured_segment_service.StructuredSegmentFallbackRequired as exc:
                                debug_log.record(
                                    "structured_fallback",
                                    exc.reason,
                                    {"provider_path": exc.provider_path, "flow_kind": "npc_chat"},
                                )
                                client = _require_async_client(payload.config)
                                reply_text, bundle, usage = await _stream_tagged_completion(
                                    client=client,
                                    model=payload.config.model,
                                    config=payload.config,
                                    messages=[
                                        {"role": "system", "content": payload.config.gm_prompt},
                                        {"role": "user", "content": _npc_reply_prompt(payload, role, save)},
                                    ],
                                    bundle_tag="npc_bundle",
                                    emit=emit,
                                    is_cancelled=is_cancelled,
                                )
                    await _emit_phase(emit, "model_reply", "done", "npc reply complete")
                    await _emit_phase(emit, "bundle_parse", "running", "applying npc bundle")
                    applied = _apply_structured_npc_bundle_result(save, payload, bundle, reply_text, time_spent_min)
                    result = applied.response
                    await _emit_phase(emit, "bundle_parse", "done", "npc bundle applied")
                    if applied.pending_reaction is not None:
                        pending_response = reaction_check_service.stage_reaction_checkpoint(
                            session_id=payload.session_id,
                            flow_kind="npc_chat",
                            staged_save=txn.save.model_dump(mode="json"),
                            original_request=payload.model_dump(mode="json"),
                            accumulated_reply_text=result.reply,
                            accumulated_scene_events=result.scene_events,
                            accumulated_tool_events=[],
                            time_spent_min=result.time_spent_min,
                            pending_reaction=applied.pending_reaction,
                            continuation_index=0,
                            usage=usage,
                            npc_role_id=payload.npc_role_id,
                        )
                        await _emit_reaction_required(emit, pending_response)
                        debug_log.finish(
                            status="awaiting_reaction",
                            result={
                                "pending_turn_id": pending_response.pending_turn_id,
                                "flow_kind": pending_response.flow_kind,
                                "reply_preview": _preview_text(pending_response.reply_text),
                            },
                        )
                        return pending_response
                    await _emit_phase(emit, "commit", "running", "writing save")
                    txn.commit()
                    token_usage_store.add(payload.session_id, "chat", usage.input_tokens, usage.output_tokens)
                    await _emit_phase(emit, "commit", "done", "save committed")
                    debug_log.finish(status="success", result=_npc_result_log_data(result, usage))
                    return result
                except StreamCancelledError as exc:
                    txn.rollback()
                    await _emit_phase(emit, "rollback", "done", "cancelled")
                    await _emit_rollback(emit, "cancelled", "本轮生成已作废")
                    debug_log.finish(status="cancelled", error=exc)
                    raise
                except Exception as exc:
                    txn.rollback()
                    await _emit_phase(emit, "rollback", "done", "reverting staged turn")
                    await _emit_rollback(emit, "error", "本轮生成已作废")
                    debug_log.finish(status="error", error=exc)
                    raise


async def run_npc_chat_once(payload: NpcChatRequest) -> NpcChatResponse | PendingTurnContinueResponse:
    return await run_npc_chat_stream(payload, emit=None, is_cancelled=None)


def _update_pending_state_for_next_reaction(
    state: PendingTurnState,
    *,
    staged_save: dict[str, Any],
    pending_reaction: PlayerReactionCheck,
    reply_text: str,
    scene_events: list[SceneEvent],
    tool_events: list[ToolEvent],
    usage: Usage,
    reaction_result=None,
) -> PendingTurnContinueResponse:
    state.status = "awaiting_reaction"
    state.staged_save = staged_save
    state.pending_reaction = pending_reaction
    state.accumulated_reply_text = reply_text
    state.accumulated_scene_events = scene_events
    state.accumulated_tool_events = tool_events
    state.usage = usage
    state.continuation_index += 1
    state.updated_at = world._utc_now()
    save_pending_turn(state)
    response = _pending_response_from_state(state)
    response.reaction_result = reaction_result
    return response


async def _continue_main_turn_state(
    state: PendingTurnState,
    payload: ChatRequest,
    *,
    forced_dice_roll: int,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PendingTurnContinueResponse:
    state, reaction_result = reaction_check_service.continue_pending_turn_once(
        state,
        forced_dice_roll=forced_dice_roll,
        config=payload.config,
    )
    reaction_text = reaction_check_service.build_reaction_result_text(state.pending_reaction, reaction_result)
    reaction_event = reaction_check_service.build_reaction_result_event(
        state.pending_reaction,
        reaction_result,
        content=reaction_text,
    )
    state.accumulated_reply_text = _append_reply_segment(state.accumulated_reply_text, reaction_text)
    state.accumulated_scene_events = [*state.accumulated_scene_events, reaction_event]
    await _emit_reaction_resumed(
        emit,
        pending_turn_id=state.pending_turn_id,
        continuation_index=state.continuation_index + 1,
        reaction_result=reaction_result,
    )
    if emit is not None and reaction_text:
        await emit("delta", {"content": f"\n{reaction_text}" if state.accumulated_reply_text != reaction_text else reaction_text})
    with world.save_transaction(payload.session_id) as txn:
        txn.save = world.SaveFile.model_validate(state.staged_save)
        await _check_cancelled(is_cancelled)
        last_user = next((message for message in reversed(payload.messages) if message.role == "user"), None)
        if last_user is None:
            raise ValueError("LAST_USER_MESSAGE_REQUIRED")
        save = world.get_current_save(default_session_id=payload.session_id)
        context_json = world.build_main_turn_context_json(save, last_user.content, recent_turn_count=8)
        audience_context = _public_audience_context(save, last_user.content)
        candidate_rows = public_scene_runtime.candidate_rows(
            save,
            player_text=str(world._parse_player_intent(last_user.content).get("display_text") or last_user.content).strip(),
            addressed_role_name=str(world._parse_player_intent(last_user.content).get("addressed_role_name") or "").strip(),
            incoming_target_candidates=[str(item) for item in list(world._parse_player_intent(last_user.content).get("incoming_target_candidates") or [])],
            config=payload.config,
        )
        await _emit_phase(emit, "model_reply", "running", "continuing after reaction")
        messages = [
            {"role": "system", "content": payload.config.gm_prompt},
            {
                "role": "user",
                "content": _main_turn_continue_segment_prompt(
                    payload=payload,
                    context_json=context_json,
                    accumulated_reply_text=state.accumulated_reply_text,
                    scene_events=state.accumulated_scene_events,
                    reaction_check=state.pending_reaction,
                    reaction_result_text=reaction_text,
                    audience_context=audience_context,
                    candidate_rows=candidate_rows,
                ),
            },
        ]

        async def _emit_reply_piece(piece: str) -> None:
            if emit is not None and piece:
                await emit("delta", {"content": piece})

        async def _check_structured_cancelled() -> None:
            await _check_cancelled(is_cancelled)

        if _use_legacy_tag_protocol(payload.config):
            client = _require_async_client(payload.config)
            reply_text, bundle, usage = await _stream_tagged_completion(
                client=client,
                model=payload.config.model,
                config=payload.config,
                messages=[
                    {"role": "system", "content": payload.config.gm_prompt},
                    {
                        "role": "user",
                        "content": _main_turn_continue_prompt(
                            payload=payload,
                            context_json=context_json,
                            accumulated_reply_text=state.accumulated_reply_text,
                            scene_events=state.accumulated_scene_events,
                            reaction_check=state.pending_reaction,
                            reaction_result_text=reaction_text,
                            audience_context=audience_context,
                            candidate_rows=candidate_rows,
                        ),
                    },
                ],
                bundle_tag="turn_bundle",
                emit=emit,
                is_cancelled=is_cancelled,
            )
        else:
            try:
                segment_result = await structured_segment_service.stream_main_turn_segment(
                    config=payload.config,
                    messages=messages,
                    emit_reply_delta=_emit_reply_piece,
                    check_cancelled=_check_structured_cancelled,
                )
                reply_text = segment_result.segment.reply_text.strip()
                bundle = _bundle_from_main_turn_segment(segment_result.segment)
                usage = segment_result.usage
            except structured_segment_service.StructuredSegmentFallbackRequired:
                client = _require_async_client(payload.config)
                reply_text, bundle, usage = await _stream_tagged_completion(
                    client=client,
                    model=payload.config.model,
                    config=payload.config,
                    messages=[
                        {"role": "system", "content": payload.config.gm_prompt},
                        {
                            "role": "user",
                            "content": _main_turn_continue_prompt(
                                payload=payload,
                                context_json=context_json,
                                accumulated_reply_text=state.accumulated_reply_text,
                                scene_events=state.accumulated_scene_events,
                                reaction_check=state.pending_reaction,
                                reaction_result_text=reaction_text,
                                audience_context=audience_context,
                                candidate_rows=candidate_rows,
                            ),
                        },
                    ],
                    bundle_tag="turn_bundle",
                    emit=emit,
                    is_cancelled=is_cancelled,
                )
        await _emit_phase(emit, "model_reply", "done", "continuation complete")
        state.usage = _merge_usage(state.usage, usage)
        state.accumulated_reply_text = _append_reply_segment(state.accumulated_reply_text, reply_text)
        applied = _apply_structured_main_turn_bundle_result(
            save,
            session_id=payload.session_id,
            player_text=last_user.content,
            gm_narration=state.accumulated_reply_text,
            time_spent_min=0,
            bundle=bundle,
            config=payload.config,
        )
        state.accumulated_scene_events = [*state.accumulated_scene_events, *applied.scene_events]
        state.staged_save = txn.save.model_dump(mode="json")
        if applied.pending_reaction is not None:
            return _update_pending_state_for_next_reaction(
                state,
                staged_save=state.staged_save,
                pending_reaction=applied.pending_reaction,
                reply_text=state.accumulated_reply_text,
                scene_events=state.accumulated_scene_events,
                tool_events=state.accumulated_tool_events,
                usage=state.usage,
                reaction_result=reaction_result,
            )
        await _emit_phase(emit, "apply", "running", "recording turn")
        save = txn.save
        parsed_intent = world._parse_player_intent(last_user.content)
        save.game_logs.append(world._new_game_log(payload.session_id, "player_input", last_user.content))
        save.game_logs.append(world._new_game_log(payload.session_id, "gm_reply", state.accumulated_reply_text))
        archived_sub_zone_turn_id = world._record_sub_zone_chat_turn(
            save,
            source="main_chat",
            player_mode=("passive" if bool(parsed_intent.get("passive_turn")) else "active"),
            player_action=str(parsed_intent.get("action_text") or ""),
            player_speech=str(parsed_intent.get("speech_text") or ""),
            player_action_check=(parsed_intent.get("action_check") if isinstance(parsed_intent.get("action_check"), dict) else None),
            gm_narration=state.accumulated_reply_text,
            events=state.accumulated_scene_events,
        )
        await _emit_phase(emit, "apply", "done", "turn staged")
        await _emit_phase(emit, "commit", "running", "writing save")
        txn.commit()
        clear_pending_turn(payload.session_id)
        token_usage_store.add(payload.session_id, "chat", state.usage.input_tokens, state.usage.output_tokens)
        await _emit_phase(emit, "commit", "done", "save committed")
        return PendingTurnContinueResponse(
            session_id=payload.session_id,
            pending_turn_id=None,
            flow_kind="main_chat",
            status="completed",
            reply_text=state.accumulated_reply_text,
            scene_events=state.accumulated_scene_events,
            tool_events=state.accumulated_tool_events,
            main_turn_summary=_main_turn_summary_from_scene_events(state.accumulated_scene_events),
            current_zone_metric=zone_metric_service.get_current_zone_metric(save, create=True),
            archived_sub_zone_turn_id=archived_sub_zone_turn_id,
            reaction_result=reaction_result,
        )


async def _continue_npc_chat_state(
    state: PendingTurnState,
    payload: NpcChatRequest,
    *,
    forced_dice_roll: int,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PendingTurnContinueResponse:
    state, reaction_result = reaction_check_service.continue_pending_turn_once(
        state,
        forced_dice_roll=forced_dice_roll,
        config=payload.config,
    )
    reaction_text = reaction_check_service.build_reaction_result_text(state.pending_reaction, reaction_result)
    reaction_event = reaction_check_service.build_reaction_result_event(
        state.pending_reaction,
        reaction_result,
        content=reaction_text,
    )
    state.accumulated_reply_text = _append_reply_segment(state.accumulated_reply_text, reaction_text)
    state.accumulated_scene_events = [*state.accumulated_scene_events, reaction_event]
    await _emit_reaction_resumed(
        emit,
        pending_turn_id=state.pending_turn_id,
        continuation_index=state.continuation_index + 1,
        reaction_result=reaction_result,
    )
    if emit is not None and reaction_text:
        await emit("delta", {"content": f"\n{reaction_text}" if state.accumulated_reply_text != reaction_text else reaction_text})
    with world.save_transaction(payload.session_id) as txn:
        txn.save = world.SaveFile.model_validate(state.staged_save)
        await _check_cancelled(is_cancelled)
        save = world.get_current_save(default_session_id=payload.session_id)
        role = next((item for item in save.role_pool if item.role_id == payload.npc_role_id), None)
        if role is None:
            raise KeyError("ROLE_NOT_FOUND")
        await _emit_phase(emit, "model_reply", "running", "continuing npc reply")
        messages = [
            {"role": "system", "content": payload.config.gm_prompt},
            {
                "role": "user",
                "content": _npc_continue_segment_prompt(
                    payload,
                    role,
                    save,
                    accumulated_reply_text=state.accumulated_reply_text,
                    scene_events=state.accumulated_scene_events,
                    reaction_check=state.pending_reaction,
                    reaction_result_text=reaction_text,
                ),
            },
        ]

        async def _emit_reply_piece(piece: str) -> None:
            if emit is not None and piece:
                await emit("delta", {"content": piece})

        async def _check_structured_cancelled() -> None:
            await _check_cancelled(is_cancelled)

        if _use_legacy_tag_protocol(payload.config):
            client = _require_async_client(payload.config)
            reply_text, bundle, usage = await _stream_tagged_completion(
                client=client,
                model=payload.config.model,
                config=payload.config,
                messages=[
                    {"role": "system", "content": payload.config.gm_prompt},
                    {
                        "role": "user",
                        "content": _npc_continue_prompt(
                            payload,
                            role,
                            save,
                            accumulated_reply_text=state.accumulated_reply_text,
                            scene_events=state.accumulated_scene_events,
                            reaction_check=state.pending_reaction,
                            reaction_result_text=reaction_text,
                        ),
                    },
                ],
                bundle_tag="npc_bundle",
                emit=emit,
                is_cancelled=is_cancelled,
            )
        else:
            try:
                segment_result = await structured_segment_service.stream_npc_chat_segment(
                    config=payload.config,
                    messages=messages,
                    emit_reply_delta=_emit_reply_piece,
                    check_cancelled=_check_structured_cancelled,
                )
                reply_text = segment_result.segment.reply_text.strip()
                bundle = _bundle_from_npc_segment(segment_result.segment)
                usage = segment_result.usage
            except structured_segment_service.StructuredSegmentFallbackRequired:
                client = _require_async_client(payload.config)
                reply_text, bundle, usage = await _stream_tagged_completion(
                    client=client,
                    model=payload.config.model,
                    config=payload.config,
                    messages=[
                        {"role": "system", "content": payload.config.gm_prompt},
                        {
                            "role": "user",
                            "content": _npc_continue_prompt(
                                payload,
                                role,
                                save,
                                accumulated_reply_text=state.accumulated_reply_text,
                                scene_events=state.accumulated_scene_events,
                                reaction_check=state.pending_reaction,
                                reaction_result_text=reaction_text,
                            ),
                        },
                    ],
                    bundle_tag="npc_bundle",
                    emit=emit,
                    is_cancelled=is_cancelled,
                )
        await _emit_phase(emit, "model_reply", "done", "npc continuation complete")
        state.usage = _merge_usage(state.usage, usage)
        state.accumulated_reply_text = _append_reply_segment(state.accumulated_reply_text, reply_text)
        applied = _apply_structured_npc_bundle_result(
            save,
            payload,
            bundle,
            reply_text,
            0,
            is_continuation=True,
        )
        state.accumulated_scene_events = [*state.accumulated_scene_events, *applied.response.scene_events]
        state.staged_save = txn.save.model_dump(mode="json")
        if applied.pending_reaction is not None:
            return _update_pending_state_for_next_reaction(
                state,
                staged_save=state.staged_save,
                pending_reaction=applied.pending_reaction,
                reply_text=state.accumulated_reply_text,
                scene_events=state.accumulated_scene_events,
                tool_events=[],
                usage=state.usage,
                reaction_result=reaction_result,
            )
        await _emit_phase(emit, "commit", "running", "writing save")
        txn.commit()
        clear_pending_turn(payload.session_id)
        token_usage_store.add(payload.session_id, "chat", state.usage.input_tokens, state.usage.output_tokens)
        await _emit_phase(emit, "commit", "done", "save committed")
        return PendingTurnContinueResponse(
            session_id=payload.session_id,
            pending_turn_id=None,
            flow_kind="npc_chat",
            status="completed",
            reply_text=state.accumulated_reply_text,
            scene_events=state.accumulated_scene_events,
            tool_events=[],
            reaction_result=reaction_result,
            npc_role_id=payload.npc_role_id,
        )


async def run_pending_turn_stream(
    req,
    *,
    emit: EmitCallback | None = None,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> PendingTurnContinueResponse:
    state = load_pending_turn(req.session_id)
    if state is None:
        raise ValueError("PENDING_TURN_NOT_FOUND")
    if state.pending_turn_id != req.pending_turn_id:
        raise ValueError("PENDING_TURN_NOT_FOUND")
    lock = get_session_lock(req.session_id)
    async with lock:
        if state.flow_kind == "main_chat":
            payload = ChatRequest.model_validate(state.original_request)
            return await _continue_main_turn_state(
                state,
                payload,
                forced_dice_roll=req.forced_dice_roll,
                emit=emit,
                is_cancelled=is_cancelled,
            )
        if state.flow_kind == "npc_chat":
            payload = NpcChatRequest.model_validate(state.original_request)
            return await _continue_npc_chat_state(
                state,
                payload,
                forced_dice_roll=req.forced_dice_roll,
                emit=emit,
                is_cancelled=is_cancelled,
            )
        raise ValueError("PENDING_TURN_FLOW_NOT_SUPPORTED")


async def run_pending_turn_once(req) -> PendingTurnContinueResponse:
    return await run_pending_turn_stream(req, emit=None, is_cancelled=None)

