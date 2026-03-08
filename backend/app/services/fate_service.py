from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    EntityRef,
    FateCurrentResponse,
    FateEvaluateRequest,
    FateEvaluateResponse,
    FateGenerateRequest,
    FateGenerateResponse,
    FateLine,
    FatePhase,
    FateState,
    FateTriggerCondition,
    GameLogEntry,
    QuestDraft,
    QuestObjective,
)
from app.services.consistency_service import ensure_world_state
from app.services.quest_service import publish_draft_to_save
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


def _state(save) -> FateState:
    if save.fate_state is None:
        save.fate_state = FateState()
    return save.fate_state


def _touch_state(state: FateState) -> None:
    state.updated_at = _utc_now()
    if state.current_fate is not None:
        state.current_fate.updated_at = state.updated_at


def _serial_day(clock) -> int:
    if clock is None:
        return 0
    return (clock.year * 12 * 28) + (clock.month * 28) + clock.day


def _default_fate_line(save) -> FateLine:
    world_state = ensure_world_state(save)
    first_npc = save.role_pool[0].role_id if save.role_pool else ""
    first_npc_name = save.role_pool[0].name if save.role_pool else "关键人物"
    phase_1 = FatePhase(
        phase_id=_new_id("phase"),
        index=1,
        source_world_revision=world_state.world_revision,
        source_map_revision=world_state.map_revision,
        title="被指向的起点",
        description="某个并不起眼的相遇，让你意识到自己已经走进了一条不普通的道路。",
        status="ready",
    )
    phase_2 = FatePhase(
        phase_id=_new_id("phase"),
        index=2,
        source_world_revision=world_state.world_revision,
        source_map_revision=world_state.map_revision,
        title="异象的回声",
        description="当第一条线索被确认后，真正的异象会开始显露。",
        status="locked",
        trigger_conditions=[
            FateTriggerCondition(
                condition_id=_new_id("fc"),
                kind="completed_quest",
                description="完成上一阶段任务后，异象才会显现。",
                payload={"phase_index": 1},
            )
        ],
    )
    phase_3 = FatePhase(
        phase_id=_new_id("phase"),
        index=3,
        source_world_revision=world_state.world_revision,
        source_map_revision=world_state.map_revision,
        title="回响之后的选择",
        description="你需要面对异象留下的结果，并决定自己接下来要站在哪一边。",
        status="locked",
        trigger_conditions=[
            FateTriggerCondition(
                condition_id=_new_id("fc"),
                kind="resolved_encounter",
                description="解决上一阶段触发的遭遇后，命运将给出下一步回应。",
                payload={"phase_index": 2},
            )
        ],
    )
    fate = FateLine(
        fate_id=_new_id("fate"),
        source_world_revision=world_state.world_revision,
        source_map_revision=world_state.map_revision,
        title="群星尽头的回响",
        summary=f"一条围绕【{first_npc_name or '关键人物'}】与未知异象展开的长期命运线。",
        status="active",
        current_phase_id=phase_1.phase_id,
        phases=[phase_1, phase_2, phase_3],
    )
    if save.area_snapshot.current_zone_id:
        fate.bound_entity_refs.append(
            EntityRef(entity_type="zone", entity_id=save.area_snapshot.current_zone_id, label=save.area_snapshot.current_zone_id)
        )
    if save.area_snapshot.current_sub_zone_id:
        fate.bound_entity_refs.append(
            EntityRef(entity_type="sub_zone", entity_id=save.area_snapshot.current_sub_zone_id, label=save.area_snapshot.current_sub_zone_id)
        )
    if first_npc:
        fate.bound_entity_refs.append(EntityRef(entity_type="npc", entity_id=first_npc, label=first_npc_name))
        phase_1.bound_entity_refs.append(EntityRef(entity_type="npc", entity_id=first_npc, label=first_npc_name))
        phase_1.description = f"先去与【{first_npc_name}】交谈，确认为什么你的名字会被提起。"
    return fate


def _find_phase(fate: FateLine, phase_id: str) -> FatePhase | None:
    return next((phase for phase in fate.phases if phase.phase_id == phase_id), None)


def _phase_quest_draft(save, fate: FateLine, phase: FatePhase) -> QuestDraft:
    first_npc = save.role_pool[0].role_id if save.role_pool else ""
    first_npc_name = save.role_pool[0].name if save.role_pool else "关键人物"
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    if phase.index == 1:
        if first_npc:
            objectives = [
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind="talk_to_npc",
                    title=f"与{first_npc_name}交谈",
                    description="从对方口中确认这条命运线索的起点。",
                    target_ref={"npc_role_id": first_npc},
                    progress_target=1,
                )
            ]
        else:
            objectives = [
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind="reach_zone",
                    title="抵达命运起点",
                    description="前往当前命运提示所指向的地点。",
                    target_ref={k: v for k, v in {"zone_id": zone_id or "", "sub_zone_id": sub_zone_id or ""}.items() if v},
                    progress_target=1,
                )
            ]
    elif phase.index == 2:
        objectives = [
            QuestObjective(
                objective_id=_new_id("obj"),
                kind="resolve_encounter",
                title="处理正在逼近的异象",
                description="解决与当前命运阶段对应的异常遭遇。",
                target_ref={"fate_phase_id": phase.phase_id, "encounter_type": "anomaly"},
                progress_target=1,
            )
        ]
    else:
        if first_npc:
            objectives = [
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind="talk_to_npc",
                    title=f"再次与{first_npc_name}对话",
                    description="把遭遇的结果告诉关键人物，并确认下一步立场。",
                    target_ref={"npc_role_id": first_npc},
                    progress_target=1,
                )
            ]
        else:
            objectives = [
                QuestObjective(
                    objective_id=_new_id("obj"),
                    kind="manual_text",
                    title="回应命运的余波",
                    description="继续推进叙事，确认你对命运异象的选择。",
                    target_ref={"keyword": "命运"},
                    progress_target=1,
                )
            ]
    entity_refs = list(phase.bound_entity_refs)
    if zone_id:
        entity_refs.append(EntityRef(entity_type="zone", entity_id=zone_id, label=zone_id))
    if sub_zone_id:
        entity_refs.append(EntityRef(entity_type="sub_zone", entity_id=sub_zone_id, label=sub_zone_id))
    if first_npc and phase.index in {1, 3}:
        entity_refs.append(EntityRef(entity_type="npc", entity_id=first_npc, label=first_npc_name))
    if phase.index == 2:
        entity_refs.append(EntityRef(entity_type="fate_phase", entity_id=phase.phase_id, label=phase.title, required=False))
    return QuestDraft(
        source="fate",
        offer_mode="accept_only",
        title=f"命运阶段{phase.index}：{phase.title}",
        description=phase.description,
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        fate_id=fate.fate_id,
        fate_phase_id=phase.phase_id,
        entity_refs=entity_refs,
        objectives=objectives,
        metadata={"generated_by": "fate_fallback", "phase_index": phase.index},
    )


def _condition_satisfied(save, fate: FateLine, condition: FateTriggerCondition) -> bool:
    payload = condition.payload
    if condition.kind == "manual":
        return bool(payload.get("ready"))

    if condition.kind == "days_elapsed":
        days_required = max(1, int(payload.get("days") or 1))
        start_day = int(payload.get("start_day_serial") or _serial_day(save.area_snapshot.clock))
        return (_serial_day(save.area_snapshot.clock) - start_day) >= days_required

    if condition.kind == "met_npc":
        npc_role_id = str(payload.get("npc_role_id") or "").strip()
        role = next((item for item in save.role_pool if item.role_id == npc_role_id), None)
        if role is None:
            return False
        return bool(role.dialogue_logs) or any(rel.target_role_id == save.player_static_data.player_id for rel in role.relations)

    if condition.kind == "obtained_item":
        item_id = str(payload.get("item_id") or "").strip()
        item_name = str(payload.get("item_name") or "").strip().lower()
        for item in save.player_static_data.dnd5e_sheet.backpack.items:
            if item_id and item.item_id == item_id:
                return True
            if item_name and item.name.strip().lower() == item_name:
                return True
        return False

    if condition.kind == "resolved_encounter":
        encounter_id = str(payload.get("encounter_id") or "").strip()
        encounter_type = str(payload.get("encounter_type") or "").strip().lower()
        phase_index = int(payload.get("phase_index") or 0)
        target_phase = next((phase for phase in fate.phases if phase.index == phase_index), None)
        for encounter in save.encounter_state.encounters:
            if encounter.status != "resolved":
                continue
            if encounter_id and encounter.encounter_id == encounter_id:
                return True
            if encounter_type and encounter.type == encounter_type and target_phase is not None and target_phase.phase_id in encounter.related_fate_phase_ids:
                return True
            if encounter_type and encounter.type == encounter_type and not encounter_id and target_phase is None:
                return True
        return False

    if condition.kind == "completed_quest":
        quest_id = str(payload.get("quest_id") or "").strip()
        if quest_id:
            return any(item.quest_id == quest_id and item.status == "completed" for item in save.quest_state.quests)
        phase_index = int(payload.get("phase_index") or 0)
        phase = next((item for item in fate.phases if item.index == phase_index), None)
        if phase is None or not phase.bound_quest_id:
            return False
        return any(item.quest_id == phase.bound_quest_id and item.status == "completed" for item in save.quest_state.quests)

    return False


def _sync_phase_from_quest(save, phase: FatePhase) -> None:
    if not phase.bound_quest_id:
        return
    quest = next((item for item in save.quest_state.quests if item.quest_id == phase.bound_quest_id), None)
    if quest is None:
        return
    if quest.status == "pending_offer":
        phase.status = "quest_offered"
    elif quest.status == "active":
        phase.status = "quest_active"
    elif quest.status == "completed":
        phase.status = "completed"
        phase.completed_at = phase.completed_at or quest.completed_at or _utc_now()
    elif quest.status in {"failed", "superseded"}:
        phase.status = "locked"


def _first_incomplete_phase(fate: FateLine) -> FatePhase | None:
    for phase in sorted(fate.phases, key=lambda item: item.index):
        if phase.status != "completed":
            return phase
    return None


def get_fate_state(session_id: str) -> FateCurrentResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _state(save)
    _touch_state(state)
    save_current(save)
    return FateCurrentResponse(session_id=session_id, fate_state=state)


def _publish_phase_quest(save, fate: FateLine, phase: FatePhase) -> str:
    draft = _phase_quest_draft(save, fate, phase)
    quest = publish_draft_to_save(save, save.session_id, draft)
    phase.bound_quest_id = quest.quest_id
    phase.status = "quest_offered"
    phase.triggered_at = phase.triggered_at or _utc_now()
    return quest.quest_id


def evaluate_fate_state(req: FateEvaluateRequest) -> FateEvaluateResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    fate = state.current_fate
    if fate is None:
        _touch_state(state)
        save_current(save)
        return FateEvaluateResponse(session_id=req.session_id, fate_state=state, advanced=False, generated_quest_id=None)

    advanced = False
    generated_quest_id: str | None = None
    for phase in sorted(fate.phases, key=lambda item: item.index):
        _sync_phase_from_quest(save, phase)
        if phase.status == "completed":
            continue
        if phase.status == "locked":
            conditions = phase.trigger_conditions or []
            all_done = True
            for condition in conditions:
                condition.satisfied = _condition_satisfied(save, fate, condition)
                if condition.satisfied and condition.satisfied_at is None:
                    condition.satisfied_at = _utc_now()
                if not condition.satisfied:
                    all_done = False
            if all_done:
                phase.status = "ready"
                phase.triggered_at = _utc_now()
                advanced = True
                _append_game_log(
                    save,
                    req.session_id,
                    "fate_phase_ready",
                    f"命运阶段已解锁【{phase.title}】",
                    {"fate_id": fate.fate_id, "phase_id": phase.phase_id, "title": phase.title},
                )
        if phase.status == "ready" and phase.bound_quest_id is None:
            generated_quest_id = _publish_phase_quest(save, fate, phase)
            advanced = True
        _sync_phase_from_quest(save, phase)

    current_phase = _first_incomplete_phase(fate)
    fate.current_phase_id = current_phase.phase_id if current_phase is not None else None
    if current_phase is None:
        fate.status = "completed"
    if current_phase is not None and current_phase.status == "completed":
        advanced = True

    for phase in fate.phases:
        already_logged = any(
            log.kind == "fate_phase_completed" and str(log.payload.get("phase_id") or "") == phase.phase_id
            for log in save.game_logs
        )
        if phase.status == "completed" and phase.completed_at is not None and not already_logged:
            _append_game_log(
                save,
                req.session_id,
                "fate_phase_completed",
                f"命运阶段完成【{phase.title}】",
                {"fate_id": fate.fate_id, "phase_id": phase.phase_id, "title": phase.title},
            )

    _touch_state(state)
    save_current(save)
    return FateEvaluateResponse(session_id=req.session_id, fate_state=state, advanced=advanced, generated_quest_id=generated_quest_id)


def generate_fate(req: FateGenerateRequest) -> FateGenerateResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    if state.current_fate is not None:
        raise ValueError("FATE_ALREADY_EXISTS")
    fate = _default_fate_line(save)
    state.current_fate = fate
    _touch_state(state)
    _append_game_log(save, req.session_id, "fate_generated", f"已生成命运线【{fate.title}】", {"fate_id": fate.fate_id})
    save_current(save)
    evaluate_fate_state(FateEvaluateRequest(session_id=req.session_id, config=req.config))
    updated = get_current_save(default_session_id=req.session_id)
    updated_state = _state(updated)
    return FateGenerateResponse(session_id=req.session_id, fate_id=fate.fate_id, generated=True, fate=updated_state.current_fate)


def regenerate_fate(req: FateGenerateRequest) -> FateGenerateResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    if state.current_fate is not None:
        archived = state.current_fate.model_copy(deep=True)
        archived.status = "superseded"
        state.archive.append(archived)
        for quest in save.quest_state.quests:
            if quest.source == "fate" and quest.status not in {"completed", "superseded"}:
                quest.status = "superseded"
                quest.is_tracked = False
        state.current_fate = None
        _append_game_log(save, req.session_id, "fate_regenerated", "命运线已重新生成", {"old_fate_id": archived.fate_id})
    _touch_state(state)
    save_current(save)
    return generate_fate(req)
