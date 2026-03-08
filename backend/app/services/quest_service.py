from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ChatConfig,
    GameLogEntry,
    QuestDraft,
    QuestEntry,
    QuestEvaluateAllRequest,
    QuestEvaluateRequest,
    QuestLogEntry,
    QuestMutationResponse,
    QuestObjective,
    QuestPublishRequest,
    QuestReward,
    QuestState,
    QuestStateResponse,
)
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    ensure_world_state,
    extract_entity_refs_from_quest_like,
    validate_entity_refs,
)
from app.services.world_service import get_current_save, save_current


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


def _append_quest_log(quest: QuestEntry, kind: str, message: str) -> None:
    quest.logs.append(QuestLogEntry(id=_new_id("qlog"), kind=kind, message=message))


def _touch_state(state: QuestState) -> None:
    state.updated_at = _utc_now()


def _sort_pending(quests: list[QuestEntry]) -> list[QuestEntry]:
    return sorted(
        [q for q in quests if q.status == "pending_offer"],
        key=lambda item: (0 if item.source == "fate" else 1, item.offered_at),
    )


def _tracked_quest(state: QuestState) -> QuestEntry | None:
    tracked_id = state.tracked_quest_id
    if tracked_id:
        quest = next((q for q in state.quests if q.quest_id == tracked_id), None)
        if quest is not None:
            return quest
    return next((q for q in state.quests if q.is_tracked), None)


def _sync_tracking(state: QuestState) -> None:
    tracked = [q for q in state.quests if q.is_tracked and q.status == "active"]
    if tracked:
        kept = tracked[0]
        state.tracked_quest_id = kept.quest_id
        for quest in state.quests:
            quest.is_tracked = quest.quest_id == kept.quest_id
        return

    active = [q for q in state.quests if q.status == "active"]
    if active:
        active[0].is_tracked = True
        state.tracked_quest_id = active[0].quest_id
    else:
        for quest in state.quests:
            quest.is_tracked = False
        state.tracked_quest_id = None


def _quest_state(save) -> QuestState:
    if save.quest_state is None:
        save.quest_state = QuestState()
    return save.quest_state


def _build_state_response(session_id: str, state: QuestState) -> QuestStateResponse:
    tracked = _tracked_quest(state)
    return QuestStateResponse(
        session_id=session_id,
        quest_state=state,
        pending_offers=_sort_pending(state.quests),
        tracked_quest=tracked,
    )


def _extract_json_content(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _current_area_refs(save) -> tuple[str | None, str | None]:
    return save.area_snapshot.current_zone_id, save.area_snapshot.current_sub_zone_id


def _prompt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _allowed_item_ids(save) -> set[str]:
    return {item.item_id for item in save.player_static_data.dnd5e_sheet.backpack.items if item.item_id}


def _sanitize_allowed_id(value: Any, allowed_ids: set[str]) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate not in allowed_ids:
        return ""
    return candidate


def _sanitize_quest_target_ref(
    save,
    kind: str,
    target_ref: dict[str, Any],
    *,
    zone_id: str | None,
    sub_zone_id: str | None,
    allowed_zone_ids: set[str],
    allowed_sub_zone_ids: set[str],
    allowed_npc_ids: set[str],
    allowed_quest_ids: set[str],
    allowed_encounter_ids: set[str],
    allowed_fate_phase_ids: set[str],
) -> dict[str, str | int | float | bool]:
    clean = {str(k): v for k, v in target_ref.items() if isinstance(v, (str, int, float, bool))}
    if kind == "reach_zone":
        zone_value = _sanitize_allowed_id(clean.get("zone_id"), allowed_zone_ids)
        sub_zone_value = _sanitize_allowed_id(clean.get("sub_zone_id"), allowed_sub_zone_ids)
        result: dict[str, str | int | float | bool] = {}
        if zone_value:
            result["zone_id"] = zone_value
        elif zone_id and zone_id in allowed_zone_ids:
            result["zone_id"] = zone_id
        if sub_zone_value:
            result["sub_zone_id"] = sub_zone_value
        elif sub_zone_id and sub_zone_id in allowed_sub_zone_ids:
            result["sub_zone_id"] = sub_zone_id
        return result

    if kind == "talk_to_npc":
        npc_role_id = _sanitize_allowed_id(clean.get("npc_role_id"), allowed_npc_ids)
        return {"npc_role_id": npc_role_id} if npc_role_id else {}

    if kind == "obtain_item":
        result: dict[str, str | int | float | bool] = {}
        item_id = _sanitize_allowed_id(clean.get("item_id"), _allowed_item_ids(save))
        item_name = str(clean.get("item_name") or "").strip()
        if item_id:
            result["item_id"] = item_id
        if item_name:
            result["item_name"] = item_name[:80]
        return result

    if kind == "resolve_encounter":
        result = {}
        encounter_id = _sanitize_allowed_id(clean.get("encounter_id"), allowed_encounter_ids)
        encounter_type = str(clean.get("encounter_type") or "").strip().lower()
        quest_id = _sanitize_allowed_id(clean.get("quest_id"), allowed_quest_ids)
        fate_phase_id = _sanitize_allowed_id(clean.get("fate_phase_id"), allowed_fate_phase_ids)
        if encounter_id:
            result["encounter_id"] = encounter_id
        if encounter_type in {"npc", "event", "anomaly"}:
            result["encounter_type"] = encounter_type
        if quest_id:
            result["quest_id"] = quest_id
        if fate_phase_id:
            result["fate_phase_id"] = fate_phase_id
        return result

    if kind == "complete_quest":
        quest_id = _sanitize_allowed_id(clean.get("quest_id"), allowed_quest_ids)
        return {"quest_id": quest_id} if quest_id else {}

    keyword = str(clean.get("keyword") or "").strip()
    return {"keyword": keyword[:80]} if keyword else {}


def _fallback_objectives(save, source: str, zone_id: str | None, sub_zone_id: str | None) -> list[QuestObjective]:
    first_npc = save.role_pool[0].role_id if save.role_pool else ""
    if source == "fate" and first_npc:
        return [
            QuestObjective(
                objective_id=_new_id("obj"),
                kind="talk_to_npc",
                title="接近命运线索",
                description="与关键人物交谈，确认这段命运的起点。",
                target_ref={"npc_role_id": first_npc},
                progress_target=1,
            )
        ]
    if zone_id:
        return [
            QuestObjective(
                objective_id=_new_id("obj"),
                kind="reach_zone",
                title="前往目标区域",
                description="抵达当前任务指定区域。",
                target_ref={k: v for k, v in {"zone_id": zone_id, "sub_zone_id": sub_zone_id or ""}.items() if v},
                progress_target=1,
            )
        ]
    return [
        QuestObjective(
            objective_id=_new_id("obj"),
            kind="manual_text",
            title="完成委托",
            description="继续推进当前叙事并寻找完成任务的机会。",
            target_ref={"keyword": "完成"},
            progress_target=1,
        )
    ]


def _fallback_rewards(source: str) -> list[QuestReward]:
    if source == "fate":
        return [QuestReward(reward_id=_new_id("rew"), kind="flag", label="命运推进", payload={"value": "phase_advance"})]
    return [QuestReward(reward_id=_new_id("rew"), kind="gold", label="委托酬金", payload={"amount": 50})]


def _fallback_quest_draft(save, source: str) -> QuestDraft:
    zone_id, sub_zone_id = _current_area_refs(save)
    zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == zone_id), "当前地区")
    sub_name = next((z.name for z in save.area_snapshot.sub_zones if z.sub_zone_id == sub_zone_id), "附近")
    if source == "fate":
        return QuestDraft(
            source="fate",
            offer_mode="accept_only",
            title=f"命运的低语：{zone_name}",
            description=f"在【{zone_name}/{sub_name}】确认这段命运的开端。",
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            objectives=_fallback_objectives(save, source, zone_id, sub_zone_id),
            rewards=_fallback_rewards(source),
            metadata={"generated_by": "fallback"},
        )
    return QuestDraft(
        source="normal",
        offer_mode="accept_reject",
        title=f"{zone_name}的委托",
        description=f"前往【{zone_name}/{sub_name}】处理一件需要你亲自确认的小事。",
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        objectives=_fallback_objectives(save, source, zone_id, sub_zone_id),
        rewards=_fallback_rewards(source),
        metadata={"generated_by": "fallback"},
    )


def _ai_generate_quest_draft(save, source: str, config: ChatConfig | None) -> QuestDraft | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None

    zone_id, sub_zone_id = _current_area_refs(save)
    zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == zone_id), "当前地区")
    sub_name = next((z.name for z in save.area_snapshot.sub_zones if z.sub_zone_id == sub_zone_id), "附近")
    offer_mode = "accept_only" if source == "fate" else "accept_reject"
    default_prompt = (
        "你是跑团任务设计器，只输出 JSON。"
        "返回结构："
        "{\"title\":\"\",\"description\":\"\",\"objectives\":[{\"kind\":\"reach_zone|talk_to_npc|obtain_item|resolve_encounter|complete_quest|manual_text\",\"title\":\"\",\"description\":\"\",\"target_ref\":{}}],"
        "\"rewards\":[{\"kind\":\"gold|item|relation|flag|none\",\"label\":\"\",\"payload\":{}}]}。"
        "世界默认任务风格：$global_prompt。"
        "任务来源=$source，接受模式=$offer_mode，区域=$zone_name，子区块=$sub_name。"
    )
    prompt = prompt_table.render(
        "quest.generate.user",
        default_prompt,
        global_prompt=prompt_table.get_text("quest.default.global", "剑与魔法世界中的委托、调查、护送、异象追查。"),
        source=source,
        offer_mode=offer_mode,
        zone_name=zone_name,
        sub_name=sub_name,
    )
    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("quest.generate.system", "你只输出 JSON。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip()
        raw_objectives = parsed.get("objectives") if isinstance(parsed.get("objectives"), list) else []
        raw_rewards = parsed.get("rewards") if isinstance(parsed.get("rewards"), list) else []
        objectives: list[QuestObjective] = []
        for item in raw_objectives[:3]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "manual_text").strip().lower()
            if kind not in {"reach_zone", "talk_to_npc", "obtain_item", "resolve_encounter", "complete_quest", "manual_text"}:
                kind = "manual_text"
            obj_title = str(item.get("title") or "").strip() or "任务目标"
            obj_desc = str(item.get("description") or "").strip() or obj_title
            target_ref = item.get("target_ref") if isinstance(item.get("target_ref"), dict) else {}
            clean_target = {str(k): v for k, v in target_ref.items() if isinstance(v, (str, int, float, bool))}
            objectives.append(
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind=kind,  # type: ignore[arg-type]
                    title=obj_title,
                    description=obj_desc,
                    target_ref=clean_target,
                    progress_target=1,
                )
            )
        rewards: list[QuestReward] = []
        for item in raw_rewards[:2]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "none").strip().lower()
            if kind not in {"gold", "item", "relation", "flag", "none"}:
                kind = "none"
            label = str(item.get("label") or "").strip() or "任务奖励"
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            clean_payload = {str(k): v for k, v in payload.items() if isinstance(v, (str, int, float, bool))}
            rewards.append(QuestReward(reward_id=_new_id("rew"), kind=kind, label=label, payload=clean_payload))  # type: ignore[arg-type]
        if not title or not description:
            return None
        return QuestDraft(
            source=("fate" if source == "fate" else "normal"),
            offer_mode=("accept_only" if source == "fate" else "accept_reject"),
            title=title,
            description=description,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            objectives=objectives,
            rewards=rewards,
            metadata={"generated_by": "ai"},
        )
    except Exception:
        return None


def _ai_generate_quest_draft_guarded(save, source: str, config: ChatConfig | None) -> QuestDraft | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None

    zone_id, sub_zone_id = _current_area_refs(save)
    zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == zone_id), "current_area")
    sub_name = next((z.name for z in save.area_snapshot.sub_zones if z.sub_zone_id == sub_zone_id), "nearby")
    offer_mode = "accept_only" if source == "fate" else "accept_reject"
    snapshot = build_global_story_snapshot(save)
    entity_index = build_entity_index(save, scope="current_zone")
    allowed_zone_ids = set(entity_index.zone_ids)
    allowed_sub_zone_ids = set(entity_index.sub_zone_ids)
    allowed_npc_ids = set(snapshot.available_npc_ids)
    allowed_quest_ids = set(snapshot.active_quest_ids)
    allowed_encounter_ids = set(entity_index.encounter_ids)
    allowed_fate_phase_ids = set(entity_index.fate_phase_ids)
    default_prompt = (
        "You design a tabletop RPG quest and must return JSON only.\n"
        "Schema: "
        "{\"title\":\"\",\"description\":\"\",\"issuer_role_id\":\"optional\","
        "\"objectives\":[{\"kind\":\"reach_zone|talk_to_npc|obtain_item|resolve_encounter|complete_quest|manual_text\",\"title\":\"\",\"description\":\"\",\"target_ref\":{}}],"
        "\"rewards\":[{\"kind\":\"gold|item|relation|flag|none\",\"label\":\"\",\"payload\":{}}]}.\n"
        "Use only ids from the allowed lists below. Do not invent entity ids.\n"
        "If no valid npc fits, do not create a talk_to_npc objective.\n"
        "Quest tone: $global_prompt.\n"
        "Source=$source. OfferMode=$offer_mode. CurrentZone=$zone_name. CurrentSubZone=$sub_name.\n"
        "CurrentFateId=$current_fate_id. CurrentFatePhaseId=$current_fate_phase_id.\n"
        "AllowedZoneIds=$allowed_zone_ids.\n"
        "AllowedSubZoneIds=$allowed_sub_zone_ids.\n"
        "AllowedNpcIds=$allowed_npc_ids.\n"
        "AllowedQuestIds=$allowed_quest_ids.\n"
        "AllowedEncounterIds=$allowed_encounter_ids.\n"
        "AllowedFatePhaseIds=$allowed_fate_phase_ids.\n"
        "VisibleNpcs=$visible_npcs.\n"
        "ActiveQuests=$active_quests.\n"
        "PendingQuestIds=$pending_quest_ids.\n"
    )
    prompt = prompt_table.render(
        "quest.generate.user",
        default_prompt,
        global_prompt=prompt_table.get_text("quest.default.global", "fantasy quest hooks"),
        source=source,
        offer_mode=offer_mode,
        zone_name=zone_name,
        sub_name=sub_name,
        current_fate_id=snapshot.current_fate_id or "none",
        current_fate_phase_id=snapshot.current_fate_phase_id or "none",
        allowed_zone_ids=_prompt_list(sorted(allowed_zone_ids)),
        allowed_sub_zone_ids=_prompt_list(sorted(allowed_sub_zone_ids)),
        allowed_npc_ids=_prompt_list(sorted(allowed_npc_ids)),
        allowed_quest_ids=_prompt_list(sorted(allowed_quest_ids)),
        allowed_encounter_ids=_prompt_list(sorted(allowed_encounter_ids)),
        allowed_fate_phase_ids=_prompt_list(sorted(allowed_fate_phase_ids)),
        visible_npcs=_prompt_list([f"{npc.role_id}:{npc.name}" for npc in snapshot.available_npcs]),
        active_quests=_prompt_list([f"{quest.quest_id}:{quest.title}" for quest in snapshot.active_quests]),
        pending_quest_ids=_prompt_list(snapshot.pending_quest_ids),
    )
    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("quest.generate.system", "Return JSON only.")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip()
        raw_objectives = parsed.get("objectives") if isinstance(parsed.get("objectives"), list) else []
        raw_rewards = parsed.get("rewards") if isinstance(parsed.get("rewards"), list) else []
        issuer_role_id = _sanitize_allowed_id(parsed.get("issuer_role_id"), allowed_npc_ids) or None
        objectives: list[QuestObjective] = []
        for item in raw_objectives[:3]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "manual_text").strip().lower()
            if kind not in {"reach_zone", "talk_to_npc", "obtain_item", "resolve_encounter", "complete_quest", "manual_text"}:
                kind = "manual_text"
            obj_title = str(item.get("title") or "").strip() or "quest objective"
            obj_desc = str(item.get("description") or "").strip() or obj_title
            target_ref = item.get("target_ref") if isinstance(item.get("target_ref"), dict) else {}
            clean_target = _sanitize_quest_target_ref(
                save,
                kind,
                target_ref,
                zone_id=zone_id,
                sub_zone_id=sub_zone_id,
                allowed_zone_ids=allowed_zone_ids,
                allowed_sub_zone_ids=allowed_sub_zone_ids,
                allowed_npc_ids=allowed_npc_ids,
                allowed_quest_ids=allowed_quest_ids,
                allowed_encounter_ids=allowed_encounter_ids,
                allowed_fate_phase_ids=allowed_fate_phase_ids,
            )
            if kind in {"talk_to_npc", "obtain_item", "complete_quest"} and not clean_target:
                continue
            objectives.append(
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind=kind,  # type: ignore[arg-type]
                    title=obj_title,
                    description=obj_desc,
                    target_ref=clean_target,
                    progress_target=1,
                )
            )
        rewards: list[QuestReward] = []
        for item in raw_rewards[:2]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "none").strip().lower()
            if kind not in {"gold", "item", "relation", "flag", "none"}:
                kind = "none"
            label = str(item.get("label") or "").strip() or "quest reward"
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            clean_payload = {str(k): v for k, v in payload.items() if isinstance(v, (str, int, float, bool))}
            rewards.append(QuestReward(reward_id=_new_id("rew"), kind=kind, label=label, payload=clean_payload))  # type: ignore[arg-type]
        if not title or not description:
            return None
        draft = QuestDraft(
            source=("fate" if source == "fate" else "normal"),
            offer_mode=("accept_only" if source == "fate" else "accept_reject"),
            title=title,
            description=description,
            issuer_role_id=issuer_role_id,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            objectives=objectives,
            rewards=rewards,
            metadata={"generated_by": "ai", "entity_guard": "allowed_ids"},
        )
        draft.entity_refs = extract_entity_refs_from_quest_like(draft)
        return draft
    except Exception:
        return None


def _resolve_publish_draft(save, req: QuestPublishRequest) -> QuestDraft:
    if req.quest is not None:
        draft = req.quest
    else:
        draft = _ai_generate_quest_draft_guarded(save, req.source, req.config) or _fallback_quest_draft(save, req.source)
    if draft.source == "fate":
        draft.offer_mode = "accept_only"
    return draft


def _find_quest(state: QuestState, quest_id: str) -> QuestEntry:
    quest = next((item for item in state.quests if item.quest_id == quest_id), None)
    if quest is None:
        raise KeyError("QUEST_NOT_FOUND")
    return quest


def publish_draft_to_save(save, session_id: str, draft: QuestDraft) -> QuestEntry:
    state = _quest_state(save)
    world_state = ensure_world_state(save)
    quest = QuestEntry(
        quest_id=_new_id("quest"),
        source=draft.source,
        offer_mode=draft.offer_mode,
        title=draft.title,
        description=draft.description,
        issuer_role_id=draft.issuer_role_id,
        zone_id=draft.zone_id,
        sub_zone_id=draft.sub_zone_id,
        fate_id=draft.fate_id,
        fate_phase_id=draft.fate_phase_id,
        source_world_revision=world_state.world_revision,
        source_map_revision=world_state.map_revision,
        entity_refs=(draft.entity_refs or extract_entity_refs_from_quest_like(draft)),
        objectives=draft.objectives or _fallback_objectives(save, draft.source, draft.zone_id, draft.sub_zone_id),
        rewards=draft.rewards or _fallback_rewards(draft.source),
        metadata=draft.metadata,
    )
    if validate_entity_refs(save, quest.entity_refs):
        quest.status = "invalidated"
        quest.invalidated_reason = "missing_entity_ref"
    _append_quest_log(quest, "offer", f"你获得了新任务【{quest.title}】")
    state.quests.append(quest)
    _touch_state(state)
    _append_game_log(
        save,
        session_id,
        "quest_offer",
        f"获得任务【{quest.title}】",
        {"quest_id": quest.quest_id, "source": quest.source, "title": quest.title},
    )
    return quest


def get_quest_state(session_id: str) -> QuestStateResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _quest_state(save)
    _sync_tracking(state)
    _touch_state(state)
    save_current(save)
    return _build_state_response(session_id, state)


def publish_quest(req: QuestPublishRequest) -> QuestMutationResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    draft = _resolve_publish_draft(save, req)
    quest = publish_draft_to_save(save, req.session_id, draft)
    state = _quest_state(save)
    save_current(save)
    return QuestMutationResponse(
        session_id=req.session_id,
        quest_id=quest.quest_id,
        status=quest.status,
        chat_feedback=f"你获得了新任务【{quest.title}】。",
        quest=quest,
        quest_state=state,
    )


def accept_quest(session_id: str, quest_id: str, config: ChatConfig | None = None) -> QuestMutationResponse:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    state = _quest_state(save)
    quest = _find_quest(state, quest_id)
    if quest.status != "pending_offer":
        raise ValueError("QUEST_INVALID_STATUS")
    if quest.invalidated_reason:
        raise ValueError("QUEST_INVALIDATED")
    if quest.source == "fate":
        quest.offer_mode = "accept_only"
    quest.status = "active"
    quest.accepted_at = _utc_now()
    quest.is_tracked = True
    for other in state.quests:
        if other.quest_id != quest.quest_id:
            other.is_tracked = False
    state.tracked_quest_id = quest.quest_id
    _append_quest_log(quest, "accept", f"你接受了任务【{quest.title}】")
    _touch_state(state)
    _append_game_log(
        save,
        session_id,
        "quest_accept",
        f"接受任务【{quest.title}】",
        {"quest_id": quest.quest_id, "source": quest.source, "title": quest.title},
    )
    save_current(save)

    if any(obj.kind == "resolve_encounter" for obj in quest.objectives):
        try:
            from app.models.schemas import EncounterCheckRequest
            from app.services.encounter_service import check_for_encounter

            trigger = "fate_rule" if quest.source == "fate" else "quest_rule"
            check_for_encounter(EncounterCheckRequest(session_id=session_id, trigger_kind=trigger, config=config))
        except Exception:
            pass

    try:
        from app.models.schemas import FateEvaluateRequest
        from app.services.fate_service import evaluate_fate_state

        evaluate_fate_state(FateEvaluateRequest(session_id=session_id, config=config))
    except Exception:
        pass

    return QuestMutationResponse(
        session_id=session_id,
        quest_id=quest.quest_id,
        status=quest.status,
        chat_feedback=(f"你接下了命运任务【{quest.title}】。" if quest.source == "fate" else f"你接受了任务【{quest.title}】。"),
        quest=quest,
        quest_state=state,
    )


def reject_quest(session_id: str, quest_id: str, config: ChatConfig | None = None) -> QuestMutationResponse:
    del config
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    state = _quest_state(save)
    quest = _find_quest(state, quest_id)
    if quest.source == "fate" or quest.offer_mode == "accept_only":
        raise ValueError("QUEST_REJECT_FORBIDDEN")
    if quest.status != "pending_offer":
        raise ValueError("QUEST_INVALID_STATUS")
    quest.status = "rejected"
    quest.rejected_at = _utc_now()
    quest.is_tracked = False
    if state.tracked_quest_id == quest.quest_id:
        state.tracked_quest_id = None
    _append_quest_log(quest, "reject", f"你拒绝了任务【{quest.title}】")
    _touch_state(state)
    _append_game_log(
        save,
        session_id,
        "quest_reject",
        f"拒绝任务【{quest.title}】",
        {"quest_id": quest.quest_id, "source": quest.source, "title": quest.title},
    )
    _sync_tracking(state)
    save_current(save)
    return QuestMutationResponse(
        session_id=session_id,
        quest_id=quest.quest_id,
        status=quest.status,
        chat_feedback=f"你拒绝了任务【{quest.title}】。",
        quest=quest,
        quest_state=state,
    )


def track_quest(session_id: str, quest_id: str) -> QuestMutationResponse:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    state = _quest_state(save)
    quest = _find_quest(state, quest_id)
    if quest.status != "active":
        raise ValueError("QUEST_TRACK_NOT_ALLOWED")
    if quest.invalidated_reason:
        raise ValueError("QUEST_INVALIDATED")
    for item in state.quests:
        item.is_tracked = item.quest_id == quest.quest_id
    state.tracked_quest_id = quest.quest_id
    _append_quest_log(quest, "system", "任务已设为当前追踪任务")
    _touch_state(state)
    _append_game_log(
        save,
        session_id,
        "quest_track",
        f"当前追踪任务切换为【{quest.title}】",
        {"quest_id": quest.quest_id, "title": quest.title},
    )
    save_current(save)
    return QuestMutationResponse(
        session_id=session_id,
        quest_id=quest.quest_id,
        status=quest.status,
        chat_feedback=f"当前追踪任务已切换为【{quest.title}】。",
        quest=quest,
        quest_state=state,
    )


def _objective_completed(save, quest: QuestEntry, obj: QuestObjective) -> bool:
    target = obj.target_ref
    if obj.kind == "reach_zone":
        zone_id = str(target.get("zone_id") or quest.zone_id or "").strip()
        sub_zone_id = str(target.get("sub_zone_id") or quest.sub_zone_id or "").strip()
        zone_ok = not zone_id or save.area_snapshot.current_zone_id == zone_id
        sub_ok = not sub_zone_id or save.area_snapshot.current_sub_zone_id == sub_zone_id
        return zone_ok and sub_ok

    if obj.kind == "talk_to_npc":
        npc_id = str(target.get("npc_role_id") or "").strip()
        role = next((item for item in save.role_pool if item.role_id == npc_id), None)
        if role is None:
            return False
        return bool(role.dialogue_logs) or any(rel.target_role_id == save.player_static_data.player_id for rel in role.relations)

    if obj.kind == "obtain_item":
        item_id = str(target.get("item_id") or "").strip()
        item_name = str(target.get("item_name") or "").strip().lower()
        for item in save.player_static_data.dnd5e_sheet.backpack.items:
            if item_id and item.item_id == item_id:
                return True
            if item_name and item.name.strip().lower() == item_name:
                return True
        return False

    if obj.kind == "resolve_encounter":
        encounter_id = str(target.get("encounter_id") or "").strip()
        encounter_type = str(target.get("encounter_type") or "").strip().lower()
        related_fate_phase_id = str(target.get("fate_phase_id") or quest.fate_phase_id or "").strip()
        for entry in save.encounter_state.encounters:
            if entry.status != "resolved":
                continue
            if encounter_id and entry.encounter_id == encounter_id:
                return True
            if encounter_type and entry.type == encounter_type:
                return True
            if related_fate_phase_id and related_fate_phase_id in entry.related_fate_phase_ids:
                return True
            if quest.quest_id in entry.related_quest_ids:
                return True
        return False

    if obj.kind == "complete_quest":
        target_quest_id = str(target.get("quest_id") or "").strip()
        return any(item.quest_id == target_quest_id and item.status == "completed" for item in save.quest_state.quests)

    keyword = str(target.get("keyword") or "").strip()
    if not keyword:
        return False
    return any(keyword in log.message for log in save.game_logs[-20:])


def _update_objective(save, quest: QuestEntry, obj: QuestObjective) -> bool:
    done = _objective_completed(save, quest, obj)
    if done:
        obj.progress_current = obj.progress_target
        obj.status = "completed"
        if obj.completed_at is None:
            obj.completed_at = _utc_now()
        return True
    obj.progress_current = 0
    obj.status = "in_progress"
    return False


def evaluate_quest(req: QuestEvaluateRequest) -> QuestMutationResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _quest_state(save)
    quest = _find_quest(state, req.quest_id)
    if quest.status not in {"active", "completed"}:
        raise ValueError("QUEST_INVALID_STATUS")
    if quest.invalidated_reason:
        raise ValueError("QUEST_INVALIDATED")

    was_completed = quest.status == "completed"
    all_completed = True
    for obj in quest.objectives:
        if not _update_objective(save, quest, obj):
            all_completed = False

    chat_feedback = f"任务【{quest.title}】尚未完成。"
    if all_completed and quest.status != "completed":
        quest.status = "completed"
        quest.completed_at = _utc_now()
        quest.is_tracked = False
        if state.tracked_quest_id == quest.quest_id:
            state.tracked_quest_id = None
        _append_quest_log(quest, "complete", f"任务【{quest.title}】已完成")
        _append_game_log(
            save,
            req.session_id,
            "quest_complete",
            f"完成任务【{quest.title}】",
            {"quest_id": quest.quest_id, "source": quest.source, "title": quest.title},
        )
        _sync_tracking(state)
        chat_feedback = f"任务【{quest.title}】已完成。"
    _touch_state(state)
    save_current(save)

    if all_completed and not was_completed:
        try:
            from app.models.schemas import FateEvaluateRequest
            from app.services.fate_service import evaluate_fate_state

            evaluate_fate_state(FateEvaluateRequest(session_id=req.session_id, config=req.config))
        except Exception:
            pass
        try:
            from app.models.schemas import EncounterCheckRequest
            from app.services.encounter_service import check_for_encounter

            check_for_encounter(EncounterCheckRequest(session_id=req.session_id, trigger_kind="quest_rule", config=req.config))
        except Exception:
            pass

    return QuestMutationResponse(
        session_id=req.session_id,
        quest_id=quest.quest_id,
        status=quest.status,
        chat_feedback=chat_feedback,
        quest=quest,
        quest_state=state,
    )


def evaluate_all_quests(req: QuestEvaluateAllRequest) -> QuestStateResponse:
    save = get_current_save(default_session_id=req.session_id)
    active_ids = [quest.quest_id for quest in save.quest_state.quests if quest.status == "active"]
    for quest_id in active_ids:
        try:
            evaluate_quest(QuestEvaluateRequest(session_id=req.session_id, quest_id=quest_id, config=req.config))
        except Exception:
            continue
    return get_quest_state(req.session_id)


def debug_generate_quest(session_id: str, config: ChatConfig | None = None) -> QuestMutationResponse:
    return publish_quest(QuestPublishRequest(session_id=session_id, source="normal", config=config))
