from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

from app.models.schemas import (
    EntityRef,
    NpcRoleCard,
    QuestDraft,
    QuestObjective,
    QuestPublishRequest,
    RoleDesire,
    RoleDriveSummary,
    RoleStoryBeat,
    SaveFile,
    SceneEvent,
    TeamMember,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cooldown_ready(value: str | None) -> bool:
    until = _parse_dt(value)
    if until is None:
        return True
    return until <= datetime.now(timezone.utc)


def _same_utc_day(a: str | None, b: str | None) -> bool:
    first = _parse_dt(a)
    second = _parse_dt(b)
    if first is None or second is None:
        return False
    return first.date() == second.date()


def _team_member_map(save: SaveFile) -> dict[str, TeamMember]:
    return {member.role_id: member for member in getattr(save.team_state, "members", [])}


def _relation_score(role: NpcRoleCard, player_id: str) -> int:
    relation = next((item for item in role.relations if item.target_role_id == player_id), None)
    tag = (relation.relation_tag if relation is not None else "neutral").strip().lower()
    return {
        "hostile": 5,
        "wary": 20,
        "neutral": 45,
        "met": 50,
        "friendly": 70,
        "ally": 85,
    }.get(tag, 45)


def _entity_refs(entity_type: str, entity_id: str, label: str) -> list[EntityRef]:
    normalized_id = (entity_id or "").strip()
    if not normalized_id:
        return []
    normalized_label = (label or normalized_id).strip() or normalized_id
    return [EntityRef(entity_type=entity_type, entity_id=normalized_id, label=normalized_label)]


def _seed_desire_templates(role: NpcRoleCard, save: SaveFile) -> list[dict[str, object]]:
    sub_zone_id = role.sub_zone_id or save.area_snapshot.current_sub_zone_id or ""
    zone_id = role.zone_id or save.area_snapshot.current_zone_id or ""
    sub_zone_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), sub_zone_id or "附近")
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), zone_id or "当前区域")
    like_text = role.likes[0] if role.likes else "线索"
    return [
        {
            "kind": "info",
            "title": f"想查清 {sub_zone_name} 的旧传闻",
            "summary": f"{role.name} 一直惦记着 {sub_zone_name} 里没人愿意明说的旧事，希望有人能替他把线索拼起来。",
            "preferred_surface": "public_scene",
            "target_refs": _entity_refs("sub_zone", sub_zone_id, sub_zone_name),
        },
        {
            "kind": "help",
            "title": f"需要有人帮忙处理 {zone_name} 的小麻烦",
            "summary": f"{role.name} 对 {zone_name} 的局面放不下，但又不想把真实压力直接说出口。",
            "preferred_surface": "public_scene",
            "target_refs": _entity_refs("zone", zone_id, zone_name),
        },
        {
            "kind": "item",
            "title": f"想找到与“{like_text}”有关的东西",
            "summary": f"{role.name} 对与“{like_text}”有关的物件格外在意，像是在找一件能证明过去的东西。",
            "preferred_surface": "private_chat",
            "target_refs": [EntityRef(entity_type="item", entity_id=f"{role.role_id}_desire_item", label=like_text)],
        },
        {
            "kind": "place",
            "title": f"想再去一次 {sub_zone_name}",
            "summary": f"{role.name} 对 {sub_zone_name} 有未了的牵挂，路过时总会不自觉放慢脚步。",
            "preferred_surface": "area_arrival",
            "target_refs": _entity_refs("sub_zone", sub_zone_id, sub_zone_name),
        },
        {
            "kind": "secret",
            "title": "有件事不想在太多人面前说",
            "summary": f"{role.name} 明显藏着不愿公开的经历，只有在关系稳下来后才可能松口。",
            "preferred_surface": "private_chat",
            "target_refs": [],
        },
        {
            "kind": "bond",
            "title": "想确认现在的同伴值不值得信任",
            "summary": f"{role.name} 嘴上不说，但一直在观察谁能真的站到最后。",
            "preferred_surface": "team_chat",
            "target_refs": [EntityRef(entity_type="npc", entity_id=role.role_id, label=role.name)],
        },
    ]


def _seed_story_templates(role: NpcRoleCard, save: SaveFile) -> list[dict[str, object]]:
    sub_zone_name = next(
        (item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == role.sub_zone_id),
        role.sub_zone_id or "附近",
    )
    return [
        {
            "title": "第一次提起过去的同伴",
            "summary": f"{role.name} 会在一个相对安静的时刻，第一次认真提起自己曾经失去的同伴。",
            "preferred_surface": "team_chat",
            "affinity_required": 60,
            "min_days_in_team": 2,
        },
        {
            "title": f"解释为什么总盯着 {sub_zone_name}",
            "summary": f"{role.name} 会解释自己为什么每到 {sub_zone_name} 都会短暂沉默，像是在确认某件旧事还在不在。",
            "preferred_surface": "area_arrival",
            "affinity_required": 70,
            "min_days_in_team": 2,
        },
    ]


def _build_seeded_desire(role: NpcRoleCard, save: SaveFile, index: int) -> RoleDesire:
    templates = _seed_desire_templates(role, save)
    template = templates[index % len(templates)]
    intensity = 45 + (_stable_int(f"{role.role_id}:desire:{index}:intensity") % 41)
    return RoleDesire(
        desire_id=f"{role.role_id}_desire_{index + 1}",
        kind=str(template["kind"]),
        title=str(template["title"]),
        summary=str(template["summary"]),
        intensity=intensity,
        status=("active" if intensity >= 65 else "latent"),
        visibility=("hidden" if intensity < 70 else "hinted"),
        preferred_surface=str(template["preferred_surface"]),
        target_refs=list(template["target_refs"]),
    )


def _build_seeded_story(role: NpcRoleCard, save: SaveFile, index: int) -> RoleStoryBeat:
    templates = _seed_story_templates(role, save)
    template = templates[index % len(templates)]
    return RoleStoryBeat(
        beat_id=f"{role.role_id}_story_{index + 1}",
        title=str(template["title"]),
        summary=str(template["summary"]),
        affinity_required=int(template["affinity_required"]),
        min_days_in_team=int(template["min_days_in_team"]),
        status="locked",
        preferred_surface=str(template["preferred_surface"]),
    )


def ensure_roleplay_state_for_role(save: SaveFile, role: NpcRoleCard, *, is_team_member: bool | None = None) -> bool:
    changed = False
    team_members = _team_member_map(save)
    in_team = bool(is_team_member) if is_team_member is not None else (role.role_id in team_members or role.state == "in_team")
    target_desire_count = 1 + (_stable_int(f"{role.role_id}:desire_count") % 2)
    while len(role.desires) < target_desire_count:
        role.desires.append(_build_seeded_desire(role, save, len(role.desires)))
        changed = True
    if in_team:
        while len(role.story_beats) < 2:
            role.story_beats.append(_build_seeded_story(role, save, len(role.story_beats)))
            changed = True
    return changed


def ensure_roleplay_state_for_save(save: SaveFile) -> bool:
    changed = False
    for role in save.role_pool:
        if ensure_roleplay_state_for_role(save, role):
            changed = True
    return changed


def build_role_drive_summaries(
    save: SaveFile,
    *,
    scope: str = "current_sub_zone",
    role_id: str | None = None,
) -> list[RoleDriveSummary]:
    ensure_roleplay_state_for_save(save)
    team_members = _team_member_map(save)
    items: list[RoleDriveSummary] = []
    for role in save.role_pool:
        if role_id and role.role_id != role_id:
            continue
        if scope == "team" and role.role_id not in team_members:
            continue
        if scope == "current_sub_zone" and role.role_id not in team_members:
            if role.sub_zone_id != save.area_snapshot.current_sub_zone_id:
                continue
        surfaced_desires = [
            item
            for item in role.desires
            if item.status in {"surfaced", "quest_linked", "active"}
        ]
        surfaced_story_beats = [
            item
            for item in role.story_beats
            if item.status in {"ready", "surfaced", "cooldown", "completed"}
        ]
        if role_id or surfaced_desires or surfaced_story_beats:
            items.append(
                RoleDriveSummary(
                    role_id=role.role_id,
                    name=role.name,
                    desires=surfaced_desires,
                    story_beats=surfaced_story_beats,
                )
            )
    return items


def _story_ready(member: TeamMember, beat: RoleStoryBeat, *, active_encounter: bool) -> bool:
    if active_encounter:
        return False
    joined_at = _parse_dt(member.joined_at)
    days_in_team = 0
    if joined_at is not None:
        days_in_team = max(0, (datetime.now(timezone.utc) - joined_at).days)
    if member.affinity < beat.affinity_required:
        return False
    if days_in_team < beat.min_days_in_team:
        return False
    if _same_utc_day(beat.last_surfaced_at, _utc_now()):
        return False
    return True


def _desire_surface_match(desire: RoleDesire, *, scene_mode: str, player_text: str, role_name: str, relation_score: int) -> bool:
    merged = (player_text or "").strip()
    tokens = ["帮", "需要", "线索", "传闻", "秘密", "东西", "找", "一起", "去", "看看"]
    if role_name and role_name in merged:
        return True
    if desire.status == "active" and any(token in merged for token in tokens):
        return True
    if desire.preferred_surface == "public_scene" and scene_mode == "public_scene" and relation_score >= 50 and bool(merged):
        return True
    if desire.preferred_surface == "team_chat" and scene_mode == "team_chat" and relation_score >= 60:
        return True
    if desire.preferred_surface == "area_arrival" and scene_mode == "area_arrival":
        return True
    return False


def _publish_desire_quest_if_needed(save: SaveFile, role: NpcRoleCard, desire: RoleDesire, relation_score: int) -> str | None:
    if desire.kind not in {"item", "help", "info", "place"}:
        return None
    if relation_score < 60 or desire.linked_quest_id:
        return None
    existing = next(
        (
            item
            for item in save.quest_state.quests
            if item.issuer_role_id == role.role_id
            and item.title == f"{role.name}：{desire.title}"
            and item.status in {"pending_offer", "active"}
        ),
        None,
    )
    if existing is not None:
        desire.linked_quest_id = existing.quest_id
        desire.status = "quest_linked"
        return existing.quest_id
    target_ref = desire.target_refs[0] if desire.target_refs else None
    objective_kind = "talk_to_npc"
    objective_target: dict[str, str | int | float | bool] = {"npc_role_id": role.role_id}
    if desire.kind == "place" and target_ref is not None and target_ref.entity_type in {"zone", "sub_zone"}:
        objective_kind = "reach_zone"
        objective_target = {
            "zone_id": (target_ref.entity_id if target_ref.entity_type == "zone" else (role.zone_id or save.area_snapshot.current_zone_id or "")),
            "sub_zone_id": (target_ref.entity_id if target_ref.entity_type == "sub_zone" else ""),
        }
    elif desire.kind == "item" and target_ref is not None and target_ref.entity_type == "item":
        objective_kind = "obtain_item"
        objective_target = {"item_id": target_ref.entity_id, "item_name": target_ref.label or desire.title}
    draft = QuestDraft(
        source="normal",
        title=f"{role.name}：{desire.title}",
        description=desire.summary or f"{role.name} 希望你帮忙处理一件与“{desire.title}”有关的事。",
        issuer_role_id=role.role_id,
        zone_id=role.zone_id or save.area_snapshot.current_zone_id,
        sub_zone_id=role.sub_zone_id or save.area_snapshot.current_sub_zone_id,
        objectives=[
            QuestObjective(
                objective_id=f"{role.role_id}_{desire.desire_id}_obj_1",
                kind=objective_kind,  # type: ignore[arg-type]
                title=desire.title,
                description=desire.summary,
                target_ref=objective_target,
            )
        ],
    )
    from app.services.quest_service import publish_quest

    result = publish_quest(
        QuestPublishRequest(
            session_id=save.session_id,
            quest=draft,
            source="normal",
            open_modal=False,
            config=None,
        )
    )
    if result.quest is None:
        return None
    desire.linked_quest_id = result.quest.quest_id
    desire.status = "quest_linked"
    return result.quest.quest_id


def surface_role_drives_for_scene(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    scene_mode: str,
    active_encounter: bool,
) -> tuple[list[SceneEvent], dict[str, list[str]], dict[str, list[str]]]:
    ensure_roleplay_state_for_save(save)
    events: list[SceneEvent] = []
    desire_hits: dict[str, list[str]] = {}
    story_hits: dict[str, list[str]] = {}
    player_id = save.player_static_data.player_id
    team_members = _team_member_map(save)

    for role in save.role_pool:
        is_team_member = role.role_id in team_members
        in_scope = is_team_member or role.sub_zone_id == save.area_snapshot.current_sub_zone_id
        if not in_scope:
            continue
        relation_score = team_members[role.role_id].affinity if is_team_member else _relation_score(role, player_id)
        for desire in role.desires:
            if desire.status in {"resolved", "expired"} or not _cooldown_ready(desire.cooldown_until):
                continue
            if not _desire_surface_match(
                desire,
                scene_mode=scene_mode,
                player_text=player_text,
                role_name=role.name,
                relation_score=relation_score,
            ):
                continue
            desire.status = "surfaced"
            desire.visibility = "explicit" if relation_score >= 65 else "hinted"
            desire.last_surfaced_at = _utc_now()
            desire.cooldown_until = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
            desire_hits.setdefault(role.role_id, []).append(desire.desire_id)
            linked_quest_id = _publish_desire_quest_if_needed(save, role, desire, relation_score)
            quest_tail = f" 并形成了任务《{linked_quest_id}》的草案。" if linked_quest_id else ""
            events.append(
                SceneEvent(
                    event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{role.role_id}_{desire.desire_id}",
                    kind="role_desire_surface",
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    content=f"{role.name} 的欲望浮出：{desire.title}。{desire.summary}{quest_tail}",
                    metadata={"intensity": desire.intensity, "actor_type": ("team" if is_team_member else "npc")},
                )
            )
            break

        if not is_team_member:
            continue
        member = team_members[role.role_id]
        for beat in role.story_beats:
            if beat.status == "completed":
                continue
            if beat.status == "cooldown" and not _cooldown_ready(beat.last_surfaced_at):
                continue
            if beat.status == "locked" and _story_ready(member, beat, active_encounter=active_encounter):
                beat.status = "ready"
            if beat.status != "ready":
                continue
            beat.status = "surfaced"
            beat.last_surfaced_at = _utc_now()
            story_hits.setdefault(role.role_id, []).append(beat.beat_id)
            events.append(
                SceneEvent(
                    event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{role.role_id}_{beat.beat_id}",
                    kind="companion_story_surface",
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    content=f"{role.name} 的队友故事浮出：{beat.title}。{beat.summary}",
                    metadata={"affinity_required": beat.affinity_required, "actor_type": "team"},
                )
            )
            break
    return events, desire_hits, story_hits
