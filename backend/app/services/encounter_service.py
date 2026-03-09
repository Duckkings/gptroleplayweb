from __future__ import annotations

from datetime import datetime, timezone
import json
from math import ceil
import random
from typing import Any

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckResponse,
    ChatConfig,
    EntityRef,
    EncounterActRequest,
    EncounterActResponse,
    EncounterCheckRequest,
    EncounterCheckResponse,
    EncounterDebugOverviewResponse,
    EncounterEntry,
    EncounterEscapeRequest,
    EncounterEscapeResponse,
    EncounterForceToggleRequest,
    EncounterForceToggleResponse,
    EncounterHistoryResponse,
    EncounterPendingResponse,
    EncounterPresentRequest,
    EncounterPresentResponse,
    EncounterRejoinRequest,
    EncounterRejoinResponse,
    EncounterResolution,
    EncounterState,
    EncounterStepEntry,
    EncounterTerminationCondition,
    GameLogEntry,
)
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    ensure_world_state,
    extract_entity_refs_from_encounter,
    validate_entity_refs,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.world_service import _advance_clock, _default_world_clock, get_current_save, save_current


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def _append_game_log(save, session_id: str, kind: str, message: str, payload: dict[str, str | int | float | bool] | None = None) -> None:
    save.game_logs.append(
        GameLogEntry(
            id=_new_id("glog"),
            session_id=session_id,
            kind=kind,
            message=message,
            payload=payload or {},
        )
    )


def _touch_state(state: EncounterState) -> None:
    state.updated_at = _utc_now()


def _state(save) -> EncounterState:
    if save.encounter_state is None:
        save.encounter_state = EncounterState()
    return save.encounter_state


def _pending_entries(state: EncounterState) -> list[EncounterEntry]:
    entries: list[EncounterEntry] = []
    for encounter_id in state.pending_ids:
        found = next((item for item in state.encounters if item.encounter_id == encounter_id and item.status == "queued"), None)
        if found is not None:
            entries.append(found)
    return entries


def _find_encounter(state: EncounterState, encounter_id: str) -> EncounterEntry:
    encounter = next((item for item in state.encounters if item.encounter_id == encounter_id), None)
    if encounter is None:
        raise KeyError("ENCOUNTER_NOT_FOUND")
    return encounter


def _current_active_encounter(state: EncounterState) -> EncounterEntry | None:
    if not state.active_encounter_id:
        return None
    encounter = next((item for item in state.encounters if item.encounter_id == state.active_encounter_id), None)
    if encounter is None or encounter.status not in {"active", "escaped"}:
        return None
    return encounter


def _append_step(
    encounter: EncounterEntry,
    *,
    kind: str,
    content: str,
    actor_type: str = "system",
    actor_id: str = "",
    actor_name: str = "",
) -> EncounterStepEntry:
    step = EncounterStepEntry(
        step_id=_new_id("estep"),
        kind=kind,  # type: ignore[arg-type]
        actor_type=actor_type,  # type: ignore[arg-type]
        actor_id=actor_id,
        actor_name=actor_name,
        content=content,
    )
    encounter.steps.append(step)
    encounter.steps = encounter.steps[-40:]
    encounter.last_advanced_at = step.created_at
    encounter.latest_outcome_summary = content[:240]
    return step


def _default_termination_conditions(encounter_type: str) -> list[EncounterTerminationCondition]:
    conditions = [
        EncounterTerminationCondition(
            condition_id=_new_id("eterm"),
            kind="player_escapes",
            description="玩家成功脱离当前遭遇并离开现场。",
        ),
        EncounterTerminationCondition(
            condition_id=_new_id("eterm"),
            kind="time_elapsed",
            description="局势在时间推进后自然结束。",
        ),
    ]
    if encounter_type == "npc":
        conditions.insert(
            0,
            EncounterTerminationCondition(
                condition_id=_new_id("eterm"),
                kind="npc_leaves",
                description="关键 NPC 主动离开或中断这次互动。",
            ),
        )
    else:
        conditions.insert(
            0,
            EncounterTerminationCondition(
                condition_id=_new_id("eterm"),
                kind="target_resolved",
                description="遭遇核心目标被处理、确认或排除。",
            ),
        )
    return conditions


def _termination_conditions_text(encounter: EncounterEntry) -> str:
    if not encounter.termination_conditions:
        return "none"
    lines = []
    for idx, item in enumerate(encounter.termination_conditions):
        marker = "done" if item.satisfied else "pending"
        lines.append(f"{idx}:{item.kind}:{marker}:{item.description}")
    return "\n".join(lines)


def _recent_steps_text(encounter: EncounterEntry, count: int = 6) -> str:
    if not encounter.steps:
        return "none"
    return "\n".join(f"[{item.kind}] {item.actor_name or item.actor_type}: {item.content}" for item in encounter.steps[-count:])


def _apply_termination_updates(encounter: EncounterEntry, updates: object) -> bool:
    changed = False
    if not isinstance(updates, list):
        return False
    for raw in updates:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("condition_index"))
        except Exception:
            continue
        if index < 0 or index >= len(encounter.termination_conditions):
            continue
        condition = encounter.termination_conditions[index]
        next_value = bool(raw.get("satisfied"))
        if next_value and not condition.satisfied:
            condition.satisfied = True
            condition.satisfied_at = _utc_now()
            changed = True
    return changed


def _encounter_should_resolve(encounter: EncounterEntry) -> bool:
    return any(item.satisfied for item in encounter.termination_conditions)


def _current_area_text(save) -> str:
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), zone_id or "当前区域")
    sub_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), sub_zone_id or "附近")
    return f"{zone_name} / {sub_name}"


def _extract_json_content(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _prompt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _force_chinese_text(value: Any, fallback: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or not _contains_cjk(text):
        text = fallback
    text = " ".join(str(text or fallback).split())
    return text[:limit]


def _sanitize_allowed_id(value: Any, allowed_ids: set[str]) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate not in allowed_ids:
        return ""
    return candidate


def _current_area_data(save) -> tuple[str, str, str | None, str | None]:
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), "当前区域")
    sub_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), "附近")
    return zone_name, sub_name, zone_id, sub_zone_id


def _has_pending_quest(save) -> bool:
    return any(item.status == "pending_offer" for item in save.quest_state.quests)


def _active_quests(save):
    return [item for item in save.quest_state.quests if item.status == "active"]


def _current_fate_phase(save):
    fate = save.fate_state.current_fate
    if fate is None:
        return None
    return next((phase for phase in fate.phases if phase.phase_id == fate.current_phase_id), None)


def _random_should_trigger(trigger_kind: str, force_enabled: bool) -> bool:
    if force_enabled:
        return True
    if trigger_kind in {"quest_rule", "fate_rule", "scripted", "debug_forced"}:
        return True
    chance = 0.35 if trigger_kind == "random_move" else 0.22
    return random.random() < chance


def _has_active_resolve_objective(save) -> bool:
    for quest in _active_quests(save):
        if any(obj.kind == "resolve_encounter" for obj in quest.objectives):
            return True
    return False


def _fallback_encounter(save, trigger_kind: str) -> EncounterEntry:
    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    active_quests = _active_quests(save)
    phase = _current_fate_phase(save)
    global_pref = prompt_table.get_text(
        "encounter.global.preference",
        "默认遭遇：抢劫、可疑NPC、异常痕迹、遗落宝箱。偏好偏向奇幻冒险和轻度悬疑。",
    )

    if active_quests:
        quest = active_quests[0]
        if any(obj.kind == "resolve_encounter" for obj in quest.objectives):
            return EncounterEntry(
                encounter_id=_new_id("enc"),
                type=("anomaly" if quest.source == "fate" else "event"),
                trigger_kind=("fate_rule" if quest.source == "fate" else "quest_rule"),
                encounter_mode="standard",
                title=f"与【{quest.title}】相关的异动",
                description=f"你在【{zone_name}/{sub_name}】察觉到一场与任务【{quest.title}】有关的异动。{global_pref[:36]}",
                zone_id=zone_id,
                sub_zone_id=sub_zone_id,
                related_quest_ids=[quest.quest_id],
                related_fate_phase_ids=([quest.fate_phase_id] if quest.fate_phase_id else []),
                generated_prompt_tags=["quest", "progress", zone_name],
                scene_summary=f"{zone_name}/{sub_name} 中出现了与任务推进有关的突然动静。",
                termination_conditions=_default_termination_conditions("event"),
            )

    if phase is not None and trigger_kind == "fate_rule" and _has_active_resolve_objective(save):
        return EncounterEntry(
            encounter_id=_new_id("enc"),
            type="anomaly",
            trigger_kind="fate_rule",
            encounter_mode="standard",
            title=f"命运相位：{phase.title}",
            description=f"【{zone_name}/{sub_name}】出现与你的命运阶段【{phase.title}】有关的异常迹象。{global_pref[:36]}",
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            related_fate_phase_ids=[phase.phase_id],
            generated_prompt_tags=["fate", "anomaly", zone_name],
            scene_summary=f"{zone_name}/{sub_name} 里忽然出现了不自然的命运征兆。",
            termination_conditions=_default_termination_conditions("anomaly"),
        )

    base_templates = [
        ("event", f"{zone_name}里的可疑痕迹", f"你在【{zone_name}/{sub_name}】发现一串刚留下不久的可疑痕迹。"),
        ("npc", f"{sub_name}的陌生人", f"一名看起来并不属于【{sub_name}】的人正悄悄观察四周。"),
        ("anomaly", f"{sub_name}的异常回响", f"空气里掠过一阵不自然的波动，像有什么在【{sub_name}】被短暂唤醒。"),
    ]
    idx = 0 if trigger_kind == "random_move" else 1
    typ, title, description = base_templates[idx if idx < len(base_templates) else 0]
    return EncounterEntry(
        encounter_id=_new_id("enc"),
        type=typ,  # type: ignore[arg-type]
        trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
        encounter_mode=("npc_initiated_chat" if typ == "npc" and trigger_kind == "random_dialog" else "standard"),
        title=title,
        description=f"{description}{global_pref[:28]}",
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        generated_prompt_tags=[zone_name, sub_name, typ],
        scene_summary=f"{zone_name}/{sub_name} 里突发了一件需要立刻回应的事。",
        termination_conditions=_default_termination_conditions(typ),
    )


def _ai_generate_encounter(save, trigger_kind: str, config: ChatConfig | None) -> EncounterEntry | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    quest_titles = " / ".join(item.title for item in _active_quests(save)) or "无活动任务"
    phase = _current_fate_phase(save)
    phase_title = phase.title if phase is not None else "无命运阶段"
    default_prompt = (
        "你是跑团遭遇设计器，只输出 JSON。"
        "结构：{\"type\":\"npc|event|anomaly\",\"title\":\"\",\"description\":\"\",\"tags\":[\"\"]}。"
        "全局遭遇偏好=$global_pref。区域=$zone_name/$sub_name。触发原因=$trigger_kind。活动任务=$quest_titles。当前命运阶段=$phase_title。"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_GENERATE_USER,
        default_prompt,
        global_pref=prompt_table.get_text("encounter.global.preference", "奇幻冒险、随机异象、可疑NPC、宝箱与伏击。"),
        zone_name=zone_name,
        sub_name=sub_name,
        trigger_kind=trigger_kind,
        quest_titles=quest_titles,
        phase_title=phase_title,
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        typ = str(parsed.get("type") or "event").strip().lower()
        if typ not in {"npc", "event", "anomaly"}:
            typ = "event"
        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip()
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        clean_tags = [str(item).strip() for item in tags[:6] if str(item).strip()]
        if not title or not description:
            return None
        active_quests = _active_quests(save)
        return EncounterEntry(
            encounter_id=_new_id("enc"),
            type=typ,  # type: ignore[arg-type]
            trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
            title=title,
            description=description,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            related_quest_ids=[item.quest_id for item in active_quests[:2]],
            related_fate_phase_ids=([phase.phase_id] if phase is not None else []),
            generated_prompt_tags=clean_tags,
        )
    except Exception:
        return None


def _ai_generate_encounter_guarded(save, trigger_kind: str, config: ChatConfig | None) -> EncounterEntry | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None

    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    snapshot = build_global_story_snapshot(save)
    entity_index = build_entity_index(save, scope="current_zone")
    allowed_npc_ids = set(snapshot.available_npc_ids)
    allowed_zone_ids = set(entity_index.zone_ids)
    allowed_sub_zone_ids = set(entity_index.sub_zone_ids)
    allowed_quest_ids = set(snapshot.active_quest_ids)
    allowed_fate_phase_ids = set(entity_index.fate_phase_ids)
    active_quests = _active_quests(save)
    phase = _current_fate_phase(save)
    fallback_encounter = _fallback_encounter(save, trigger_kind)
    default_prompt = (
        "你要设计一个持续型跑团遭遇，且只能返回 JSON。\n"
        "所有可见文本字段都必须使用简体中文，不允许输出英文标题、英文描述或英文叙事。\n"
        "Schema: {\"type\":\"npc|event|anomaly\",\"title\":\"\",\"description\":\"\",\"npc_role_id\":\"optional\",\"scene_summary\":\"\",\"termination_conditions\":[{\"kind\":\"npc_leaves|player_escapes|target_resolved|time_elapsed|manual_custom\",\"description\":\"\"}],\"tags\":[\"\"]}。\n"
        "若 type=npc，则 npc_role_id 必填，且只能从允许列表中选择。\n"
        "禁止编造 npc id、zone id、sub-zone id、quest id 或 fate phase id。\n"
        "遭遇需要有立刻发生的现场感，title、description、scene_summary 和 termination_conditions.description 都必须是简体中文。"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_GENERATE_USER,
        default_prompt,
        global_pref=prompt_table.get_text("encounter.global.preference", "奇幻遭遇"),
        zone_name=zone_name,
        sub_name=sub_name,
        trigger_kind=trigger_kind,
        current_fate_id=snapshot.current_fate_id or "none",
        current_fate_phase_id=snapshot.current_fate_phase_id or "none",
        allowed_npc_ids=_prompt_list(sorted(allowed_npc_ids)),
        allowed_zone_ids=_prompt_list(sorted(allowed_zone_ids)),
        allowed_sub_zone_ids=_prompt_list(sorted(allowed_sub_zone_ids)),
        allowed_quest_ids=_prompt_list(sorted(allowed_quest_ids)),
        allowed_fate_phase_ids=_prompt_list(sorted(allowed_fate_phase_ids)),
        visible_npcs=_prompt_list([f"{npc.role_id}:{npc.name}" for npc in snapshot.available_npcs]),
        active_quests=_prompt_list([f"{quest.quest_id}:{quest.title}" for quest in snapshot.active_quests]),
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        typ = str(parsed.get("type") or "event").strip().lower()
        if typ not in {"npc", "event", "anomaly"}:
            typ = "event"
        title = _force_chinese_text(parsed.get("title"), fallback_encounter.title, limit=80)
        description = _force_chinese_text(parsed.get("description"), fallback_encounter.description, limit=240)
        scene_summary = _force_chinese_text(
            parsed.get("scene_summary"),
            fallback_encounter.scene_summary or fallback_encounter.description,
            limit=240,
        )
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        clean_tags = [str(item).strip()[:40] for item in tags[:6] if str(item).strip()]
        if not title or not description:
            return None

        entity_refs: list[EntityRef] = []
        npc_role_id = _sanitize_allowed_id(parsed.get("npc_role_id"), allowed_npc_ids)
        termination_conditions_raw = parsed.get("termination_conditions") if isinstance(parsed.get("termination_conditions"), list) else []
        termination_conditions: list[EncounterTerminationCondition] = []
        for raw in termination_conditions_raw[:5]:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "").strip()
            description_text = _force_chinese_text(raw.get("description"), "", limit=160)
            if kind not in {"npc_leaves", "player_escapes", "target_resolved", "time_elapsed", "manual_custom"}:
                continue
            if not description_text:
                continue
            termination_conditions.append(
                EncounterTerminationCondition(
                    condition_id=_new_id("eterm"),
                    kind=kind,  # type: ignore[arg-type]
                    description=description_text,
                )
            )
        if typ == "npc":
            if not npc_role_id:
                return None
            npc_name = next((item.name for item in save.role_pool if item.role_id == npc_role_id), npc_role_id)
            if npc_name not in title:
                title = f"{npc_name}: {title}"
            entity_refs.append(EntityRef(entity_type="npc", entity_id=npc_role_id, label=npc_name))

        encounter = EncounterEntry(
            encounter_id=_new_id("enc"),
            type=typ,  # type: ignore[arg-type]
            trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
            encounter_mode=("npc_initiated_chat" if typ == "npc" and trigger_kind == "random_dialog" else "standard"),
            title=title,
            description=description,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            npc_role_id=npc_role_id or None,
            related_quest_ids=[item.quest_id for item in active_quests[:2]],
            related_fate_phase_ids=([phase.phase_id] if phase is not None else []),
            generated_prompt_tags=clean_tags,
            scene_summary=scene_summary,
            termination_conditions=termination_conditions or _default_termination_conditions(typ),
        )
        encounter.entity_refs = extract_entity_refs_from_encounter(encounter) + entity_refs
        return encounter
    except Exception:
        return None


def get_pending_encounters(session_id: str) -> EncounterPendingResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _state(save)
    pending = _pending_entries(state)
    active = _current_active_encounter(state)
    return EncounterPendingResponse(session_id=session_id, encounter_state=state, pending=pending, active_encounter=active)


def get_encounter_history(session_id: str) -> EncounterHistoryResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _state(save)
    return EncounterHistoryResponse(session_id=session_id, items=state.history)


def set_debug_force_toggle(req: EncounterForceToggleRequest) -> EncounterForceToggleResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    enabled = (not state.debug_force_trigger) if req.enabled is None else bool(req.enabled)
    state.debug_force_trigger = enabled
    _touch_state(state)
    save_current(save)
    return EncounterForceToggleResponse(session_id=req.session_id, enabled=enabled, encounter_state=state)


def check_for_encounter(req: EncounterCheckRequest) -> EncounterCheckResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    world_state = ensure_world_state(save)
    if _current_active_encounter(state) is not None:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if req.trigger_kind in {"random_move", "random_dialog"} and _pending_entries(state):
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if len(state.pending_ids) >= 5:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if req.trigger_kind in {"quest_rule", "fate_rule"} and not _has_active_resolve_objective(save):
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    should_trigger = _random_should_trigger(req.trigger_kind, state.debug_force_trigger)
    if not should_trigger:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    encounter = _ai_generate_encounter_guarded(save, req.trigger_kind, req.config) or _fallback_encounter(save, req.trigger_kind)
    encounter.source_world_revision = world_state.world_revision
    encounter.source_map_revision = world_state.map_revision
    base_refs = extract_entity_refs_from_encounter(encounter)
    unique_refs: dict[tuple[str, str], EntityRef] = {}
    for ref in [*base_refs, *(encounter.entity_refs or [])]:
        unique_refs[(ref.entity_type, ref.entity_id)] = ref
    encounter.entity_refs = list(unique_refs.values())
    if validate_entity_refs(save, encounter.entity_refs):
        encounter.status = "invalidated"
        encounter.invalidated_reason = "missing_entity_ref"
        state.encounters.append(encounter)
        _touch_state(state)
        save_current(save)
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))
    state.encounters.append(encounter)
    state.pending_ids.append(encounter.encounter_id)
    _touch_state(state)
    _append_game_log(
        save,
        req.session_id,
        "encounter_generated",
        f"遭遇已生成【{encounter.title}】",
        {
            "encounter_id": encounter.encounter_id,
            "encounter_type": encounter.type,
            "title": encounter.title,
            "description": encounter.description,
        },
    )
    save_current(save)
    return EncounterCheckResponse(
        ok=True,
        generated=True,
        encounter_id=encounter.encounter_id,
        blocked_by_higher_priority_modal=_has_pending_quest(save),
        encounter=encounter,
    )


def present_encounter(encounter_id: str, req: EncounterPresentRequest) -> EncounterPresentResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.invalidated_reason or encounter.status == "invalidated":
        raise ValueError("ENCOUNTER_INVALIDATED")
    if encounter.status not in {"queued", "active", "escaped"}:
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.status == "queued":
        encounter.status = "active"
        encounter.presented_at = _utc_now()
        encounter.player_presence = "engaged"
        encounter.last_advanced_at = encounter.presented_at
        if not encounter.termination_conditions:
            encounter.termination_conditions = _default_termination_conditions(encounter.type)
        encounter.scene_summary = encounter.scene_summary or encounter.description
        encounter.latest_outcome_summary = f"就在这时，{encounter.description}"
        _append_step(encounter, kind="announcement", content=encounter.latest_outcome_summary)
        _append_game_log(
            save,
            req.session_id,
            "encounter_presented",
            f"遭遇开始：《{encounter.title}》",
            {
                "encounter_id": encounter.encounter_id,
                "encounter_type": encounter.type,
                "title": encounter.title,
                "description": encounter.description,
            },
        )
    state.active_encounter_id = encounter.encounter_id
    _touch_state(state)
    save_current(save)
    return EncounterPresentResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        encounter=encounter,
    )


def _resolve_fallback_reply(encounter: EncounterEntry, player_prompt: str) -> tuple[str, int]:
    minutes = max(1, min(15, ceil(len(player_prompt.strip()) / 30)))
    if encounter.type == "npc":
        return (f"对方先打量了你一眼，然后低声回应了你的试探，显然不想在公开场合多说。", minutes)
    if encounter.type == "anomaly":
        return (f"你的动作引发了更明显的异样回响，周围环境短暂变得不自然，但你抓住了一条可继续追查的线索。", minutes)
    return (f"你的举动让这场遭遇有了明确进展，现场留下的细节足够你继续推进调查。", minutes)


def _ai_resolve_encounter(encounter: EncounterEntry, req: EncounterActRequest) -> dict[str, object] | None:
    config = req.config
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    fallback_reply, fallback_minutes = _resolve_fallback_reply(encounter, req.player_prompt)
    default_prompt = (
        "\u4f60\u8981\u63a8\u8fdb\u4e00\u4e2a\u8dd1\u56e2\u906d\u9047\u6b65\u9aa4\uff0c\u53ea\u80fd\u8fd4\u56de JSON\u3002\n"
        "reply \u548c scene_summary \u5fc5\u987b\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\uff0c\u4e0d\u5141\u8bb8\u8f93\u51fa\u82f1\u6587\u53d9\u4e8b\u3002\n"
        "JSON schema: "
        "{\"reply\":\"...\",\"time_spent_min\":1,\"scene_summary\":\"...\","
        "\"step_kind\":\"gm_update|npc_reaction|team_reaction|resolution\","
        "\"termination_updates\":[{\"condition_index\":0,\"satisfied\":true}]}"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_STEP_USER,
        default_prompt,
        title=encounter.title,
        description=encounter.description,
        encounter_mode=encounter.encounter_mode,
        player_presence=encounter.player_presence,
        scene_summary=encounter.scene_summary or encounter.description,
        termination_conditions=_termination_conditions_text(encounter),
        recent_steps=_recent_steps_text(encounter),
        player_prompt=req.player_prompt,
        team_members="none",
        visible_npcs="none",
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.resolve.system", "\u4f60\u53ea\u8f93\u51fa JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        reply = _force_chinese_text(parsed.get("reply"), fallback_reply, limit=240)
        minutes = max(1, min(30, int(parsed.get("time_spent_min") or fallback_minutes or 1)))
        if not reply:
            return None
        step_kind = str(parsed.get("step_kind") or "gm_update").strip().lower()
        if step_kind not in {"gm_update", "npc_reaction", "team_reaction", "resolution"}:
            step_kind = "gm_update"
        scene_summary = _force_chinese_text(parsed.get("scene_summary"), encounter.scene_summary or encounter.description, limit=240)
        termination_updates = parsed.get("termination_updates")
        if not isinstance(termination_updates, list):
            termination_updates = []
        return {
            "reply": reply,
            "time_spent_min": minutes,
            "scene_summary": scene_summary,
            "step_kind": step_kind,
            "termination_updates": termination_updates,
        }
    except Exception:
        return None


def _fallback_step_updates(encounter: EncounterEntry, player_prompt: str) -> tuple[str, list[dict[str, object]], str]:
    clean = (player_prompt or "").strip()
    updates: list[dict[str, object]] = []
    step_kind = "gm_update"
    scene_summary = encounter.scene_summary or encounter.description
    if any(token in clean for token in ["搞清", "确认", "解决", "谈妥", "处理完", "拿到"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "target_resolved":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if encounter.type == "npc" and any(token in clean for token in ["散了", "走开", "不聊", "闭嘴"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "npc_leaves":
                updates.append({"condition_index": index, "satisfied": True})
                break
    return scene_summary, updates, step_kind


def act_on_encounter(encounter_id: str, req: EncounterActRequest) -> EncounterActResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.invalidated_reason or encounter.status == "invalidated":
        raise ValueError("ENCOUNTER_INVALIDATED")
    if encounter.status not in {"queued", "active", "escaped"}:
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.status == "queued":
        encounter.status = "active"
        encounter.presented_at = _utc_now()
    if encounter.status == "escaped":
        encounter.status = "active"
        encounter.player_presence = "engaged"
        state.active_encounter_id = encounter.encounter_id

    _append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=req.player_prompt.strip(),
    )
    resolved = _ai_resolve_encounter(encounter, req)
    if resolved is None:
        reply, time_spent_min = _resolve_fallback_reply(encounter, req.player_prompt)
        next_scene_summary, termination_updates, step_kind = _fallback_step_updates(encounter, req.player_prompt)
    else:
        reply = str(resolved.get("reply") or "").strip()
        time_spent_min = max(1, min(30, int(resolved.get("time_spent_min") or 1)))
        next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
        termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
        step_kind = str(resolved.get("step_kind") or "gm_update")
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind=step_kind, content=reply)
    _apply_termination_updates(encounter, termination_updates)
    if _encounter_should_resolve(encounter):
        encounter.status = "resolved"
        encounter.resolved_at = _utc_now()
        if encounter.encounter_id in state.pending_ids:
            state.pending_ids = [item for item in state.pending_ids if item != encounter.encounter_id]
        if state.active_encounter_id == encounter.encounter_id:
            state.active_encounter_id = None
        _append_step(encounter, kind="resolution", content=reply)
    else:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id

    resolution = EncounterResolution(
        encounter_id=encounter.encounter_id,
        player_prompt=req.player_prompt.strip(),
        reply=reply,
        time_spent_min=time_spent_min,
        quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
    )
    state.history.append(resolution)
    state.history = state.history[-80:]
    _touch_state(state)
    _append_game_log(
        save,
        req.session_id,
        ("encounter_resolved" if encounter.status == "resolved" else "encounter_progress"),
        (f"遭遇结束：《{encounter.title}》" if encounter.status == "resolved" else f"遭遇推进：《{encounter.title}》"),
        {
            "encounter_id": encounter.encounter_id,
            "encounter_type": encounter.type,
            "title": encounter.title,
            "description": encounter.description,
            "time_spent_min": time_spent_min,
        },
    )
    _append_game_log(
        save,
        req.session_id,
        "encounter_resolution_text",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "player_prompt": req.player_prompt,
        },
    )
    save_current(save)

    try:
        from app.models.schemas import QuestEvaluateAllRequest
        from app.services.quest_service import evaluate_all_quests

        evaluate_all_quests(QuestEvaluateAllRequest(session_id=req.session_id, config=req.config))
    except Exception:
        pass
    try:
        from app.models.schemas import FateEvaluateRequest
        from app.services.fate_service import evaluate_fate_state

        evaluate_fate_state(FateEvaluateRequest(session_id=req.session_id, config=req.config))
    except Exception:
        pass

    return EncounterActResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        time_spent_min=time_spent_min,
        encounter=encounter,
        resolution=resolution,
        encounter_state=state,
    )


def advance_active_encounter_in_save(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.player_presence != "away" or encounter.status not in {"active", "escaped"}:
        return None
    if minutes_elapsed <= 0:
        return None

    reply = f"\u4f60\u79bb\u5f00\u73b0\u573a\u540e\uff0c\u300a{encounter.title}\u300b\u4ecd\u5728\u540e\u53f0\u63a8\u8fdb\uff0c\u5c40\u52bf\u6084\u6084\u53d1\u751f\u4e86\u53d8\u5316\u3002"
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = create_sync_client(config, client_cls=OpenAI)
                prompt = prompt_table.render(
                    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
                    "\u4f60\u8981\u5728\u540e\u53f0\u63a8\u8fdb\u4e00\u4e2a\u906d\u9047\uff0c\u53ea\u80fd\u8fd4\u56de JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002",
                    title=encounter.title,
                    description=encounter.description,
                    scene_summary=encounter.scene_summary or encounter.description,
                    termination_conditions=_termination_conditions_text(encounter),
                    recent_steps=_recent_steps_text(encounter),
                    minutes_elapsed=minutes_elapsed,
                )
                resp = client.chat.completions.create(
                    model=model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "\u4f60\u53ea\u8f93\u51fa JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002")},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                reply = _force_chinese_text(parsed.get("reply"), reply, limit=240)
                encounter.scene_summary = _force_chinese_text(
                    parsed.get("scene_summary"),
                    encounter.scene_summary or encounter.description,
                    limit=240,
                )
                _apply_termination_updates(encounter, parsed.get("termination_updates"))
            except Exception:
                pass

    encounter.background_tick_count += 1
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="background_tick", content=reply)
    if _encounter_should_resolve(encounter):
        encounter.status = "resolved"
        encounter.resolved_at = _utc_now()
        if state.active_encounter_id == encounter.encounter_id:
            state.active_encounter_id = None
    _append_game_log(
        save,
        session_id,
        "encounter_background_tick",
        reply,
        {"encounter_id": encounter.encounter_id, "minutes_elapsed": minutes_elapsed},
    )
    _touch_state(state)
    return encounter


def escape_encounter(encounter_id: str, req: EncounterEscapeRequest) -> EncounterEscapeResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status != "active" or encounter.player_presence != "engaged":
        raise ValueError("ENCOUNTER_INVALID_STATUS")

    from app.models.schemas import ActionCheckRequest
    from app.services.world_service import action_check

    action_result: ActionCheckResponse = action_check(
        ActionCheckRequest(
            session_id=req.session_id,
            action_type="check",
            action_prompt=f"encounter_escape; encounter_id={encounter.encounter_id}; title={encounter.title}",
            actor_role_id=save.player_static_data.player_id,
            config=req.config,
        )
    )
    escape_success = bool(action_result.success)
    if escape_success:
        encounter.status = "escaped"
        encounter.player_presence = "away"
        state.active_encounter_id = encounter.encounter_id
        reply = f"你暂时从《{encounter.title}》里抽身离开，但事件仍在你身后继续发展。"
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                _apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
    else:
        reply = f"你试图从《{encounter.title}》里脱身，但局势没有给你留下完整的脱离空档。"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="escape_attempt", content=reply)
    _append_game_log(
        save,
        req.session_id,
        "encounter_escape",
        reply,
        {"encounter_id": encounter.encounter_id, "escape_success": escape_success},
    )
    _touch_state(state)
    save_current(save)
    return EncounterEscapeResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        time_spent_min=action_result.time_spent_min,
        escape_success=escape_success,
        encounter=encounter,
        encounter_state=state,
        action_check=action_result,
    )


def rejoin_encounter(encounter_id: str, req: EncounterRejoinRequest) -> EncounterRejoinResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status not in {"active", "escaped"} or encounter.player_presence != "away":
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.zone_id != save.area_snapshot.current_zone_id or encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        raise ValueError("ENCOUNTER_REJOIN_AREA_MISMATCH")

    reply = f"你重新回到了《{encounter.title}》发生的地点，局势再次把你卷了进去。"
    encounter.status = "active"
    encounter.player_presence = "engaged"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    state.active_encounter_id = encounter.encounter_id
    _append_step(encounter, kind="gm_update", content=reply)
    _touch_state(state)
    save_current(save)
    return EncounterRejoinResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        encounter=encounter,
        encounter_state=state,
    )


def get_encounter_debug_overview(session_id: str) -> EncounterDebugOverviewResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    state = _state(save)
    active = _current_active_encounter(state)
    queued = _pending_entries(state)
    if active is not None:
        summary = f"当前活跃遭遇: {active.title} / {active.status} / {active.player_presence}"
    elif queued:
        summary = f"待处理遭遇数: {len(queued)}"
    else:
        summary = "当前没有活跃或待处理遭遇。"
    return EncounterDebugOverviewResponse(
        session_id=session_id,
        active_encounter=active,
        queued_encounters=queued,
        summary=summary,
    )
