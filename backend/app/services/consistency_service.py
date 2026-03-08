from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    ConsistencyIssue,
    EntityIndexResponse,
    EntityRef,
    FateLine,
    GameLogEntry,
    GlobalStorySnapshot,
    NpcKnowledgeSnapshot,
    PlayerStorySummary,
    StoryEncounterSummary,
    StoryNpcSummary,
    StoryQuestSummary,
    WorldState,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def ensure_world_state(save) -> WorldState:
    state = getattr(save, "world_state", None)
    if state is None:
        save.world_state = WorldState()
        return save.world_state
    if state.world_revision < 1:
        state.world_revision = 1
    if state.map_revision < 1:
        state.map_revision = 1
    return state


def append_consistency_log(
    save,
    session_id: str,
    kind: str,
    message: str,
    payload: dict[str, str | int | float | bool] | None = None,
) -> None:
    save.game_logs.append(
        GameLogEntry(
            id=_new_id("glog"),
            session_id=session_id,
            kind=kind,
            message=message,
            payload=payload or {},
        )
    )


def bump_world_revision(save, *, world_changed: bool, map_changed: bool, session_id: str | None = None) -> WorldState:
    state = ensure_world_state(save)
    before_world = state.world_revision
    before_map = state.map_revision
    if world_changed:
        state.world_revision += 1
    if map_changed:
        state.map_revision += 1
    state.last_world_rebuild_at = _utc_now()
    if session_id is not None:
        append_consistency_log(
            save,
            session_id,
            "world_revision_bumped",
            "世界结构版本已更新",
            {
                "world_revision_before": before_world,
                "world_revision_after": state.world_revision,
                "map_revision_before": before_map,
                "map_revision_after": state.map_revision,
            },
        )
    return state


def _zone_name(save, zone_id: str | None) -> str:
    if not zone_id:
        return ""
    return next((z.name for z in save.area_snapshot.zones if z.zone_id == zone_id), zone_id)


def _sub_zone_name(save, sub_zone_id: str | None) -> str:
    if not sub_zone_id:
        return ""
    return next((z.name for z in save.area_snapshot.sub_zones if z.sub_zone_id == sub_zone_id), sub_zone_id)


def _player_relation_tag(role, player_id: str) -> str | None:
    rel = next((item for item in role.relations if item.target_role_id == player_id), None)
    return rel.relation_tag if rel is not None else None


def _current_local_roles(save) -> list:
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    current_zone_id = save.area_snapshot.current_zone_id
    if current_sub_zone_id:
        roles = [r for r in save.role_pool if r.sub_zone_id == current_sub_zone_id]
        if roles:
            return roles
    if current_zone_id:
        roles = [r for r in save.role_pool if r.zone_id == current_zone_id]
        if roles:
            return roles
    return save.role_pool[:]


def build_global_story_snapshot(save) -> GlobalStorySnapshot:
    world_state = ensure_world_state(save)
    player = save.player_static_data
    sheet = player.dnd5e_sheet
    local_roles = _current_local_roles(save)
    active_quests = [q for q in save.quest_state.quests if q.status == "active"]
    pending_quest_ids = [q.quest_id for q in save.quest_state.quests if q.status == "pending_offer"]
    recent_encounters = [e for e in save.encounter_state.encounters if e.status in {"queued", "active", "escaped", "resolved"}][-5:]
    available_npcs = [
        StoryNpcSummary(
            role_id=role.role_id,
            name=role.name,
            zone_id=role.zone_id,
            sub_zone_id=role.sub_zone_id,
            relation_tag=_player_relation_tag(role, player.player_id),
        )
        for role in local_roles
    ]
    return GlobalStorySnapshot(
        session_id=save.session_id,
        world_revision=world_state.world_revision,
        map_revision=world_state.map_revision,
        current_zone_id=save.area_snapshot.current_zone_id,
        current_sub_zone_id=save.area_snapshot.current_sub_zone_id,
        current_zone_name=_zone_name(save, save.area_snapshot.current_zone_id),
        current_sub_zone_name=_sub_zone_name(save, save.area_snapshot.current_sub_zone_id),
        clock=save.area_snapshot.clock,
        player_summary=PlayerStorySummary(
            player_id=player.player_id,
            name=player.name,
            level=sheet.level,
            hp_current=sheet.hit_points.current,
            hp_maximum=sheet.hit_points.maximum,
            inventory_item_names=[item.name for item in sheet.backpack.items[:20]],
        ),
        visible_zone_ids=[item.zone_id for item in save.area_snapshot.zones],
        visible_sub_zone_ids=[item.sub_zone_id for item in save.area_snapshot.sub_zones],
        available_npc_ids=[item.role_id for item in local_roles],
        available_npcs=available_npcs,
        team_member_ids=[item.role_id for item in save.team_state.members],
        active_quest_ids=[item.quest_id for item in active_quests],
        active_quests=[
            StoryQuestSummary(quest_id=item.quest_id, title=item.title, status=item.status, source=item.source)
            for item in active_quests
        ],
        pending_quest_ids=pending_quest_ids,
        current_fate_id=(save.fate_state.current_fate.fate_id if save.fate_state.current_fate is not None else None),
        current_fate_phase_id=(save.fate_state.current_fate.current_phase_id if save.fate_state.current_fate is not None else None),
        recent_encounter_ids=[item.encounter_id for item in recent_encounters],
        recent_game_log_refs=[item.id for item in save.game_logs[-10:]],
    )


def build_npc_knowledge_snapshot(save, npc_role_id: str) -> NpcKnowledgeSnapshot:
    world_state = ensure_world_state(save)
    role = next((item for item in save.role_pool if item.role_id == npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    local_roles = [item for item in save.role_pool if item.zone_id == role.zone_id]
    local_role_ids = [item.role_id for item in local_roles if item.role_id != role.role_id]
    local_zone_ids = sorted({item.zone_id for item in local_roles if item.zone_id})
    forbidden_role_ids = [item.role_id for item in save.role_pool if item.role_id not in local_role_ids and item.role_id != role.role_id]
    known_quest_refs: list[EntityRef] = []
    for quest in save.quest_state.quests:
        if quest.status not in {"active", "pending_offer"}:
            continue
        if quest.zone_id and quest.zone_id == role.zone_id:
            known_quest_refs.append(EntityRef(entity_type="quest", entity_id=quest.quest_id, label=quest.title))
            continue
        if quest.issuer_role_id and quest.issuer_role_id == role.role_id:
            known_quest_refs.append(EntityRef(entity_type="quest", entity_id=quest.quest_id, label=quest.title))
    relation_tag = _player_relation_tag(role, save.player_static_data.player_id) or "neutral"
    profile_summary = f"{role.name}，位于{_zone_name(save, role.zone_id)}/{_sub_zone_name(save, role.sub_zone_id)}。{role.background}".strip()
    return NpcKnowledgeSnapshot(
        npc_role_id=role.role_id,
        npc_name=role.name,
        world_revision=world_state.world_revision,
        map_revision=world_state.map_revision,
        current_zone_id=role.zone_id,
        current_sub_zone_id=role.sub_zone_id,
        self_profile_summary=profile_summary,
        known_player_relation=relation_tag,
        known_local_npc_ids=local_role_ids,
        known_local_zone_ids=local_zone_ids,
        known_active_quest_refs=known_quest_refs[:8],
        recent_dialogue_summary=[
            f"[{item.world_time_text}] {item.speaker_name}: {item.content}"
            for item in role.dialogue_logs[-8:]
        ],
        forbidden_entity_ids=forbidden_role_ids[:50],
        response_rules=[
            "只能基于当前合法可知事实回答。",
            "若玩家提到不存在或不在你知识范围内的人物/区域，明确表示不知道或不确认。",
            "不要把传闻当作确定事实，不要编造当前地图不存在的NPC。",
        ],
    )


def build_entity_index(save, scope: str = "global") -> EntityIndexResponse:
    world_state = ensure_world_state(save)
    if scope == "current_sub_zone" and save.area_snapshot.current_sub_zone_id:
        npc_ids = [item.role_id for item in save.role_pool if item.sub_zone_id == save.area_snapshot.current_sub_zone_id]
        sub_zone_ids = [save.area_snapshot.current_sub_zone_id]
        zone_ids = [save.area_snapshot.current_zone_id] if save.area_snapshot.current_zone_id else []
    elif scope == "current_zone" and save.area_snapshot.current_zone_id:
        npc_ids = [item.role_id for item in save.role_pool if item.zone_id == save.area_snapshot.current_zone_id]
        zone_ids = [save.area_snapshot.current_zone_id]
        sub_zone_ids = [item.sub_zone_id for item in save.area_snapshot.sub_zones if item.zone_id == save.area_snapshot.current_zone_id]
    else:
        npc_ids = [item.role_id for item in save.role_pool]
        zone_ids = [item.zone_id for item in save.area_snapshot.zones]
        sub_zone_ids = [item.sub_zone_id for item in save.area_snapshot.sub_zones]
    return EntityIndexResponse(
        session_id=save.session_id,
        world_revision=world_state.world_revision,
        map_revision=world_state.map_revision,
        zone_ids=[item for item in zone_ids if item],
        sub_zone_ids=[item for item in sub_zone_ids if item],
        npc_ids=npc_ids,
        quest_ids=[item.quest_id for item in save.quest_state.quests],
        encounter_ids=[item.encounter_id for item in save.encounter_state.encounters],
        fate_phase_ids=(
            [item.phase_id for item in save.fate_state.current_fate.phases]
            if save.fate_state.current_fate is not None
            else []
        ),
    )


def _entity_exists(save, ref: EntityRef) -> bool:
    if ref.entity_type == "zone":
        return any(item.zone_id == ref.entity_id for item in save.area_snapshot.zones)
    if ref.entity_type == "sub_zone":
        return any(item.sub_zone_id == ref.entity_id for item in save.area_snapshot.sub_zones)
    if ref.entity_type == "npc":
        return any(item.role_id == ref.entity_id for item in save.role_pool)
    if ref.entity_type == "item":
        return any(item.item_id == ref.entity_id for item in save.player_static_data.dnd5e_sheet.backpack.items)
    if ref.entity_type == "quest":
        return any(item.quest_id == ref.entity_id for item in save.quest_state.quests)
    if ref.entity_type == "encounter":
        return any(item.encounter_id == ref.entity_id for item in save.encounter_state.encounters)
    if ref.entity_type == "fate":
        if save.fate_state.current_fate is not None and save.fate_state.current_fate.fate_id == ref.entity_id:
            return True
        return any(item.fate_id == ref.entity_id for item in save.fate_state.archive)
    if ref.entity_type == "fate_phase":
        if save.fate_state.current_fate is None:
            return False
        return any(item.phase_id == ref.entity_id for item in save.fate_state.current_fate.phases)
    return False


def validate_entity_refs(save, refs: list[EntityRef]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for ref in refs:
        if _entity_exists(save, ref):
            continue
        if not ref.required:
            continue
        issues.append(
            ConsistencyIssue(
                issue_id=_new_id("ci"),
                severity="error",
                issue_type="missing_entity_ref",
                entity_type=ref.entity_type,
                entity_id=ref.entity_id,
                message=f"引用实体不存在: {ref.entity_type}/{ref.entity_id}",
            )
        )
    return issues


def _issues_for_quest(save, quest) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    world_state = ensure_world_state(save)
    if quest.status in {"completed", "failed", "rejected", "superseded", "invalidated"}:
        return issues
    if quest.source_world_revision != world_state.world_revision or quest.source_map_revision != world_state.map_revision:
        issues.append(
            ConsistencyIssue(
                issue_id=_new_id("ci"),
                severity="warning",
                issue_type="quest_revision_mismatch",
                entity_type="quest",
                entity_id=quest.quest_id,
                message="任务引用的世界版本已过期",
            )
        )
    issues.extend(validate_entity_refs(save, quest.entity_refs))
    return issues


def _issues_for_encounter(save, encounter) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    world_state = ensure_world_state(save)
    if encounter.status in {"resolved", "expired", "invalidated"}:
        return issues
    if encounter.source_world_revision != world_state.world_revision or encounter.source_map_revision != world_state.map_revision:
        issues.append(
            ConsistencyIssue(
                issue_id=_new_id("ci"),
                severity="warning",
                issue_type="encounter_revision_mismatch",
                entity_type="encounter",
                entity_id=encounter.encounter_id,
                message="遭遇引用的世界版本已过期",
            )
        )
    issues.extend(validate_entity_refs(save, encounter.entity_refs))
    return issues


def _issues_for_fate(save, fate: FateLine | None) -> list[ConsistencyIssue]:
    if fate is None:
        return []
    issues: list[ConsistencyIssue] = []
    world_state = ensure_world_state(save)
    if fate.status in {"completed", "superseded", "invalidated"}:
        return issues
    if fate.source_world_revision != world_state.world_revision or fate.source_map_revision != world_state.map_revision:
        issues.append(
            ConsistencyIssue(
                issue_id=_new_id("ci"),
                severity="warning",
                issue_type="fate_revision_mismatch",
                entity_type="fate",
                entity_id=fate.fate_id,
                message="命运线引用的世界版本已过期",
            )
        )
    issues.extend(validate_entity_refs(save, fate.bound_entity_refs))
    for phase in fate.phases:
        issues.extend(validate_entity_refs(save, phase.bound_entity_refs))
    return issues


def collect_consistency_issues(save) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    ensure_world_state(save)
    issues.extend(_issues_for_fate(save, save.fate_state.current_fate))
    for quest in save.quest_state.quests:
        issues.extend(_issues_for_quest(save, quest))
    for encounter in save.encounter_state.encounters:
        issues.extend(_issues_for_encounter(save, encounter))
    role_ids = {item.role_id for item in save.role_pool}
    for role in save.role_pool:
        for relation in role.relations:
            if relation.target_role_id == save.player_static_data.player_id:
                continue
            if relation.target_role_id in role_ids:
                continue
            issues.append(
                ConsistencyIssue(
                    issue_id=_new_id("ci"),
                    severity="warning",
                    issue_type="missing_relation_target",
                    entity_type="npc",
                    entity_id=role.role_id,
                    message=f"NPC {role.role_id} 存在指向无效目标的关系",
                )
            )
    return issues


def reconcile_consistency(save, *, session_id: str, reason: str = "manual") -> tuple[list[ConsistencyIssue], bool]:
    changed = False
    world_state = ensure_world_state(save)

    valid_role_ids = {item.role_id for item in save.role_pool}
    for role in save.role_pool:
        before = len(role.relations)
        role.relations = [
            item
            for item in role.relations
            if item.target_role_id == save.player_static_data.player_id or item.target_role_id in valid_role_ids
        ]
        if len(role.relations) != before:
            changed = True

    current_fate = save.fate_state.current_fate
    fate_issues = _issues_for_fate(save, current_fate)
    if current_fate is not None and fate_issues:
        archived = current_fate.model_copy(deep=True)
        archived.status = "superseded"
        archived.invalidated_reason = reason
        save.fate_state.archive.append(archived)
        save.fate_state.current_fate = None
        for quest in save.quest_state.quests:
            if quest.source == "fate" and quest.status not in {"completed", "superseded", "invalidated"}:
                quest.status = "superseded"
                quest.invalidated_reason = reason
                quest.is_tracked = False
        append_consistency_log(
            save,
            session_id,
            "fate_invalidated",
            "当前命运线因世界状态变化失效",
            {"reason": reason, "world_revision": world_state.world_revision},
        )
        changed = True

    for quest in save.quest_state.quests:
        issues = _issues_for_quest(save, quest)
        if not issues:
            continue
        if quest.status in {"completed", "failed", "rejected", "superseded", "invalidated"}:
            continue
        quest.status = "superseded" if quest.source == "fate" else "invalidated"
        quest.invalidated_reason = reason
        quest.is_tracked = False
        append_consistency_log(
            save,
            session_id,
            "quest_invalidated",
            f"任务已失效: {quest.title}",
            {"quest_id": quest.quest_id, "reason": reason},
        )
        changed = True

    if any(item.status == "invalidated" and item.quest_id == save.quest_state.tracked_quest_id for item in save.quest_state.quests):
        save.quest_state.tracked_quest_id = None
        changed = True

    pending_ids: list[str] = []
    for encounter in save.encounter_state.encounters:
        issues = _issues_for_encounter(save, encounter)
        if issues and encounter.status not in {"resolved", "expired", "invalidated"}:
            encounter.status = "invalidated"
            encounter.invalidated_reason = reason
            append_consistency_log(
                save,
                session_id,
                "encounter_invalidated",
                f"遭遇已失效: {encounter.title}",
                {"encounter_id": encounter.encounter_id, "reason": reason},
            )
            if save.encounter_state.active_encounter_id == encounter.encounter_id:
                save.encounter_state.active_encounter_id = None
            changed = True
            continue
        if encounter.status in {"queued"}:
            pending_ids.append(encounter.encounter_id)
    if pending_ids != save.encounter_state.pending_ids:
        save.encounter_state.pending_ids = pending_ids
        changed = True

    issues = collect_consistency_issues(save)
    world_state.last_consistency_check_at = _utc_now()
    if changed:
        append_consistency_log(
            save,
            session_id,
            "consistency_reconciled",
            "一致性协调已执行",
            {"issue_count": len(issues), "reason": reason},
        )
    return issues, changed


def extract_entity_refs_from_quest_like(quest_like) -> list[EntityRef]:
    refs: list[EntityRef] = []
    zone_id = getattr(quest_like, "zone_id", None)
    sub_zone_id = getattr(quest_like, "sub_zone_id", None)
    issuer_role_id = getattr(quest_like, "issuer_role_id", None)
    fate_id = getattr(quest_like, "fate_id", None)
    fate_phase_id = getattr(quest_like, "fate_phase_id", None)
    title = getattr(quest_like, "title", "")
    if zone_id:
        refs.append(EntityRef(entity_type="zone", entity_id=zone_id, label=title or zone_id))
    if sub_zone_id:
        refs.append(EntityRef(entity_type="sub_zone", entity_id=sub_zone_id, label=title or sub_zone_id))
    if issuer_role_id:
        refs.append(EntityRef(entity_type="npc", entity_id=issuer_role_id, label=issuer_role_id))
    if fate_id:
        refs.append(EntityRef(entity_type="fate", entity_id=fate_id, label=fate_id, required=False))
    if fate_phase_id:
        refs.append(EntityRef(entity_type="fate_phase", entity_id=fate_phase_id, label=fate_phase_id, required=False))
    for objective in getattr(quest_like, "objectives", []) or []:
        target = getattr(objective, "target_ref", {}) or {}
        npc_role_id = str(target.get("npc_role_id") or "").strip()
        target_zone_id = str(target.get("zone_id") or "").strip()
        target_sub_zone_id = str(target.get("sub_zone_id") or "").strip()
        encounter_id = str(target.get("encounter_id") or "").strip()
        quest_id = str(target.get("quest_id") or "").strip()
        phase_id = str(target.get("fate_phase_id") or "").strip()
        item_id = str(target.get("item_id") or "").strip()
        if npc_role_id:
            refs.append(EntityRef(entity_type="npc", entity_id=npc_role_id, label=objective.title))
        if target_zone_id:
            refs.append(EntityRef(entity_type="zone", entity_id=target_zone_id, label=objective.title))
        if target_sub_zone_id:
            refs.append(EntityRef(entity_type="sub_zone", entity_id=target_sub_zone_id, label=objective.title))
        if encounter_id:
            refs.append(EntityRef(entity_type="encounter", entity_id=encounter_id, label=objective.title, required=False))
        if quest_id:
            refs.append(EntityRef(entity_type="quest", entity_id=quest_id, label=objective.title, required=False))
        if phase_id:
            refs.append(EntityRef(entity_type="fate_phase", entity_id=phase_id, label=objective.title, required=False))
        if item_id:
            refs.append(EntityRef(entity_type="item", entity_id=item_id, label=objective.title, required=False))
    unique: dict[tuple[str, str], EntityRef] = {}
    for ref in refs:
        unique[(ref.entity_type, ref.entity_id)] = ref
    return list(unique.values())


def extract_entity_refs_from_encounter(encounter) -> list[EntityRef]:
    refs: list[EntityRef] = []
    if encounter.zone_id:
        refs.append(EntityRef(entity_type="zone", entity_id=encounter.zone_id, label=encounter.title))
    if encounter.sub_zone_id:
        refs.append(EntityRef(entity_type="sub_zone", entity_id=encounter.sub_zone_id, label=encounter.title))
    if getattr(encounter, "npc_role_id", None):
        refs.append(EntityRef(entity_type="npc", entity_id=encounter.npc_role_id, label=encounter.title, required=False))
    for quest_id in encounter.related_quest_ids:
        refs.append(EntityRef(entity_type="quest", entity_id=quest_id, label=encounter.title, required=False))
    for phase_id in encounter.related_fate_phase_ids:
        refs.append(EntityRef(entity_type="fate_phase", entity_id=phase_id, label=encounter.title, required=False))
    return refs


def extract_entity_refs_from_fate(fate: FateLine) -> list[EntityRef]:
    refs = list(fate.bound_entity_refs)
    for phase in fate.phases:
        refs.extend(phase.bound_entity_refs)
    unique: dict[tuple[str, str], EntityRef] = {}
    for ref in refs:
        unique[(ref.entity_type, ref.entity_id)] = ref
    return list(unique.values())


def player_mentions_unknown_npc(save, npc_role_id: str, player_message: str) -> bool:
    snapshot = build_npc_knowledge_snapshot(save, npc_role_id)
    mentioned_non_local = False
    for role in save.role_pool:
        if role.role_id == npc_role_id:
            continue
        if role.name and role.name in player_message and role.role_id not in snapshot.known_local_npc_ids:
            mentioned_non_local = True
            break
    if mentioned_non_local:
        return True
    for quest in save.quest_state.quests:
        if quest.status not in {"invalidated", "superseded"}:
            continue
        for ref in quest.entity_refs:
            if ref.entity_type == "npc" and ref.label and ref.label in player_message:
                return True
    if save.fate_state.current_fate is None:
        return False
    if save.fate_state.current_fate.invalidated_reason:
        for ref in save.fate_state.current_fate.bound_entity_refs:
            if ref.entity_type == "npc" and ref.label and ref.label in player_message:
                return True
    return False


def npc_guard_reply() -> str:
    return "这名字我没听说过，或者至少不敢把传闻当成真事。"
