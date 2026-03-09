from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    ChatConfig,
    NpcRoleCard,
    PublicSceneActorCandidate,
    PublicSceneState,
    PublicSceneStateResponse,
    SaveFile,
    SceneEvent,
    StoryNpcSummary,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.reputation_service import (
    apply_reputation_relation_bias,
    apply_sub_zone_reputation_delta,
    get_current_sub_zone_reputation,
)
from app.services.roleplay_service import build_role_drive_summaries, surface_role_drives_for_scene
from app.services.world_service import (
    _active_encounter_for_current_sub_zone,
    _append_npc_dialogue,
    _build_npc_roleplay_brief,
    _extract_json_content,
    _new_game_log,
    _new_scene_event,
    _parse_player_intent,
    _public_behavior_triggered,
    _upsert_npc_player_relation,
    _visible_public_roles,
    _world_time_payload,
    action_check,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def _team_role_map(save: SaveFile) -> dict[str, NpcRoleCard]:
    member_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
    return {
        role.role_id: role
        for role in save.role_pool
        if role.role_id in member_ids
    }


def _team_member_by_role_id(save: SaveFile, role_id: str):
    return next((item for item in getattr(save.team_state, "members", []) if item.role_id == role_id), None)


def _scene_context_json(scene_context: dict[str, object] | None) -> str:
    return json.dumps(scene_context or {}, ensure_ascii=False, indent=2)


def _relation_tag_after_delta(role: NpcRoleCard, player_id: str, delta: int) -> str:
    ladder = ["hostile", "wary", "neutral", "met", "friendly", "ally"]
    current = next((item.relation_tag for item in role.relations if item.target_role_id == player_id), "neutral")
    try:
        index = ladder.index(current)
    except ValueError:
        index = ladder.index("neutral")
    shift = 0
    if delta > 0:
        shift = 1 if delta < 2 else 2
    elif delta < 0:
        shift = -1 if delta > -2 else -2
    return ladder[_clamp(index + shift, 0, len(ladder) - 1)]


def _fallback_actor_intent(
    role: NpcRoleCard,
    *,
    actor_type: str,
    player_text: str,
    gm_summary: str,
    priority_reason: str,
    has_surfaced_drive: bool,
    in_encounter: bool,
) -> dict[str, object]:
    merged = f"{player_text}\n{gm_summary}".strip()
    mentions_role = bool(role.name and role.name in merged)
    positive = any(token in merged for token in ["谢谢", "帮", "合作", "一起", "线索", "冷静", "别怕"])
    negative = any(token in merged for token in ["威胁", "攻击", "滚开", "抢", "打", "杀", "闭嘴"])
    if actor_type == "team":
        action = f"{role.name} 先靠近半步，保持和你同一条线。"
        speech = "我跟上，你先别乱。" if in_encounter else "我在听，先把眼前局面稳住。"
        if has_surfaced_drive:
            speech = f"{speech} 另外，关于“{role.story_beats[0].title if role.story_beats else role.desires[0].title if role.desires else '那件事'}”，我之后想和你单独说。"
    else:
        if mentions_role:
            action = f"{role.name} 明显把注意力转到了你这边。"
            speech = "你先把话说清楚。" if not positive else "我听见了，继续。"
        else:
            action = f"{role.name} 侧过身观察局势，没有立刻离开。"
            speech = ""
    if negative:
        action = f"{role.name} 下意识绷紧了肩背，动作明显带上戒备。"
        speech = "别把事情闹得更大。"
    situation_delta = 0
    if in_encounter:
        situation_delta = 2 if positive or actor_type == "team" else (-2 if negative else 0)
    reputation_delta = 1 if positive and actor_type == "team" else (-1 if negative else 0)
    relation_delta = 1 if positive or mentions_role else (-1 if negative else 0)
    needs_check = in_encounter and (actor_type == "team" or negative or has_surfaced_drive)
    return {
        "action_summary": action[:160],
        "speech_summary": speech[:120],
        "needs_check": needs_check,
        "action_type": "check",
        "action_prompt": f"{role.name} 在公开场景中{priority_reason or '作出即时反应'}",
        "situation_delta_hint": _clamp(situation_delta, -8, 8),
        "reputation_delta_hint": _clamp(reputation_delta, -2, 2),
        "relation_delta_hint": _clamp(relation_delta, -2, 2),
    }


def _ai_actor_intent(
    role: NpcRoleCard,
    *,
    actor_type: str,
    player_text: str,
    gm_summary: str,
    priority_reason: str,
    scene_context: dict[str, object] | None,
    reputation_score: int,
    config: ChatConfig | None,
    surfaced_desire_titles: list[str],
    surfaced_story_titles: list[str],
) -> dict[str, object] | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    try:
        world_time_text, _ = _world_time_payload(scene_context.get("world_time") if isinstance(scene_context, dict) else None)  # type: ignore[arg-type]
    except Exception:
        world_time_text = ""
    prompt = prompt_table.render(
        PromptKeys.SCENE_ACTOR_INTENT_USER,
        (
            "你要为公开区域里的一个行动体生成结构化行动意图，只输出 JSON。\n"
            "Schema={\"action_summary\":\"\",\"speech_summary\":\"\",\"needs_check\":true,"
            "\"action_type\":\"check|attack|item_use\",\"action_prompt\":\"\","
            "\"situation_delta_hint\":0,\"reputation_delta_hint\":0,\"relation_delta_hint\":0}。\n"
            "数值限制：situation_delta_hint -8..8，reputation_delta_hint -2..2，relation_delta_hint -2..2。"
        ),
        role_name=role.name,
        actor_type=actor_type,
        roleplay_brief=_build_npc_roleplay_brief(role),
        player_text=player_text,
        gm_summary=gm_summary,
        world_time_text=world_time_text,
        priority_reason=priority_reason,
        reputation_score=reputation_score,
        scene_context_json=_scene_context_json(scene_context),
        surfaced_desires=" / ".join(surfaced_desire_titles) or "none",
        surfaced_story_beats=" / ".join(surfaced_story_titles) or "none",
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        action_summary = str(parsed.get("action_summary") or "").strip()[:160]
        speech_summary = str(parsed.get("speech_summary") or "").strip()[:120]
        action_type = str(parsed.get("action_type") or "check").strip().lower()
        if action_type not in {"check", "attack", "item_use"}:
            action_type = "check"
        action_prompt = str(parsed.get("action_prompt") or "").strip()[:160]
        if not action_summary and not speech_summary:
            return None
        return {
            "action_summary": action_summary,
            "speech_summary": speech_summary,
            "needs_check": bool(parsed.get("needs_check")),
            "action_type": action_type,
            "action_prompt": action_prompt or f"{role.name} 在公开场景中采取行动",
            "situation_delta_hint": _clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
            "reputation_delta_hint": _clamp(int(parsed.get("reputation_delta_hint") or 0), -2, 2),
            "relation_delta_hint": _clamp(int(parsed.get("relation_delta_hint") or 0), -2, 2),
        }
    except Exception:
        return None


def _candidate_rows(
    save: SaveFile,
    *,
    player_text: str,
    surfaced_desires: dict[str, list[str]],
    surfaced_stories: dict[str, list[str]],
) -> list[tuple[NpcRoleCard, str, str]]:
    visible_npcs = _visible_public_roles(save)
    team_roles = list(_team_role_map(save).values())
    active_encounter = _active_encounter_for_current_sub_zone(save)
    visible_map = {role.role_id: role for role in [*team_roles, *visible_npcs]}
    targeted_role = next((role for role in visible_npcs if role.name and role.name in player_text), None)
    rows: list[tuple[int, NpcRoleCard, str, str]] = []
    mentioned_ids = {role_id for role_id, role in visible_map.items() if role.name and role.name in player_text}

    def add(role: NpcRoleCard, actor_type: str, priority: int, reason: str) -> None:
        rows.append((priority, role, actor_type, reason))

    if targeted_role is not None:
        add(targeted_role, "npc", 0, "player_targeted_visible_npc")
    if active_encounter is not None and active_encounter.npc_role_id:
        encounter_role = visible_map.get(active_encounter.npc_role_id)
        if encounter_role is not None:
            add(encounter_role, "npc" if encounter_role.role_id not in _team_role_map(save) else "team", 1, "active_encounter_anchor")
    for role in team_roles:
        if role.role_id in surfaced_desires or role.role_id in surfaced_stories:
            add(role, "team", 2, "surfaced_drive")
    for role_id in mentioned_ids:
        role = visible_map.get(role_id)
        if role is not None:
            add(role, "team" if role_id in _team_role_map(save) else "npc", 3, "direct_player_reference")
    for role in visible_npcs:
        add(role, "npc", 5, "bystander")
    for role in team_roles:
        add(role, "team", 4, "team_presence")

    deduped: list[tuple[NpcRoleCard, str, str]] = []
    seen: set[str] = set()
    for _, role, actor_type, reason in sorted(rows, key=lambda item: (item[0], item[1].name, item[1].role_id)):
        if role.role_id in seen:
            continue
        seen.add(role.role_id)
        deduped.append((role, actor_type, reason))
    return deduped


def build_public_scene_state(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str = "",
    surfaced_desires: dict[str, list[str]] | None = None,
    surfaced_stories: dict[str, list[str]] | None = None,
) -> PublicSceneState:
    surfaced_desires = surfaced_desires or {}
    surfaced_stories = surfaced_stories or {}
    rep = get_current_sub_zone_reputation(save, create=True)
    team_roles = _team_role_map(save)
    candidates = _candidate_rows(
        save,
        player_text=player_text,
        surfaced_desires=surfaced_desires,
        surfaced_stories=surfaced_stories,
    )
    return PublicSceneState(
        session_id=session_id,
        current_zone_id=save.area_snapshot.current_zone_id,
        current_sub_zone_id=save.area_snapshot.current_sub_zone_id,
        current_reputation=rep,
        visible_npcs=[
            StoryNpcSummary(
                role_id=role.role_id,
                name=role.name,
                zone_id=role.zone_id,
                sub_zone_id=role.sub_zone_id,
            )
            for role in _visible_public_roles(save)
        ],
        team_members=[
            StoryNpcSummary(
                role_id=role.role_id,
                name=role.name,
                zone_id=role.zone_id,
                sub_zone_id=role.sub_zone_id,
            )
            for role in team_roles.values()
        ],
        candidate_actors=[
            PublicSceneActorCandidate(
                role_id=role.role_id,
                name=role.name,
                actor_type=actor_type,  # type: ignore[arg-type]
                priority_reason=reason,
                surfaced_desire_ids=surfaced_desires.get(role.role_id, []),
                surfaced_story_beat_ids=surfaced_stories.get(role.role_id, []),
            )
            for role, actor_type, reason in candidates[:6]
        ],
        surfaced_drives=build_role_drive_summaries(save, scope="current_sub_zone"),
        active_encounter=_active_encounter_for_current_sub_zone(save),
    )


def get_public_scene_state(session_id: str) -> PublicSceneStateResponse:
    from app.services.world_service import get_current_save, save_current

    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    return PublicSceneStateResponse(
        session_id=session_id,
        public_scene_state=build_public_scene_state(save, session_id=session_id),
    )


def _check_bonus(action_result: ActionCheckResponse | None) -> int:
    if action_result is None:
        return 0
    if action_result.critical == "critical_success":
        return 8
    if action_result.critical == "critical_failure":
        return -8
    return 4 if action_result.success else -4


def _apply_actor_relation_delta(save: SaveFile, role: NpcRoleCard, actor_type: str, relation_delta: int, reputation_score: int) -> int:
    applied = apply_reputation_relation_bias(reputation_score, relation_delta)
    if applied == 0:
        return 0
    if actor_type == "team":
        member = _team_member_by_role_id(save, role.role_id)
        if member is not None:
            member.affinity = _clamp(member.affinity + applied * 3, 0, 100)
            member.trust = _clamp(member.trust + applied * 2, 0, 100)
    else:
        next_tag = _relation_tag_after_delta(role, save.player_static_data.player_id, applied)
        _upsert_npc_player_relation(role, save.player_static_data.player_id, next_tag, "公开场景导演器关系变化")
    return applied


def _actor_check(
    save: SaveFile,
    role: NpcRoleCard,
    *,
    action_type: str,
    action_prompt: str,
    config: ChatConfig | None,
) -> ActionCheckResponse | None:
    try:
        return action_check(
            ActionCheckRequest(
                session_id=save.session_id,
                actor_role_id=role.role_id,
                action_type=action_type,  # type: ignore[arg-type]
                action_prompt=action_prompt,
                allow_backend_roll=True,
                resolution_context="embedded",
                config=config,
            )
        )
    except Exception:
        return None


def _compose_actor_resolution(role: NpcRoleCard, action_summary: str, speech_summary: str, action_result: ActionCheckResponse | None) -> str:
    parts = [item.strip() for item in [action_summary, speech_summary] if item.strip()]
    if action_result is not None:
        outcome = "成功" if action_result.success else "失败"
        if action_result.critical == "critical_success":
            outcome = "大成功"
        elif action_result.critical == "critical_failure":
            outcome = "大失败"
        parts.append(f"检定结果：{outcome}。{action_result.narrative}")
    return "\n".join(parts).strip()[:320]


def advance_public_scene_in_save(
    save: SaveFile,
    session_id: str,
    player_text: str,
    gm_summary: str = "",
    scene_context: dict[str, object] | None = None,
    config: ChatConfig | None = None,
) -> list[SceneEvent]:
    intent = _parse_player_intent(player_text)
    display_text = str(intent.get("display_text") or player_text).strip()
    passive_turn = bool(intent.get("passive_turn"))
    if not passive_turn and not _public_behavior_triggered(str(intent.get("action_text") or ""), str(intent.get("speech_text") or ""), str(intent.get("raw_text") or "")):
        return []
    if scene_context is None:
        from app.services.world_service import _build_scene_context_payload

        scene_context = _build_scene_context_payload(
            save,
            player_text=player_text,
            gm_narration=gm_summary,
            recent_turn_count=4,
        )

    active_encounter = _active_encounter_for_current_sub_zone(save)
    drive_events, surfaced_desires, surfaced_stories = surface_role_drives_for_scene(
        save,
        session_id=session_id,
        player_text=display_text,
        scene_mode=("public_scene" if not passive_turn else "team_chat"),
        active_encounter=active_encounter is not None and active_encounter.status == "active",
    )
    reputation_entry = get_current_sub_zone_reputation(save, create=True)
    reputation_score = reputation_entry.score if reputation_entry is not None else 50
    candidates = _candidate_rows(
        save,
        player_text=display_text,
        surfaced_desires=surfaced_desires,
        surfaced_stories=surfaced_stories,
    )
    if not candidates and not drive_events:
        return []

    scene_events: list[SceneEvent] = [*drive_events]
    reacted_role_ids: list[str] = []
    reputation_delta_total = 0

    for role, actor_type, priority_reason in candidates[:4]:
        reacted_role_ids.append(role.role_id)
        surfaced_desire_titles = [
            item.title
            for item in role.desires
            if item.desire_id in surfaced_desires.get(role.role_id, [])
        ]
        surfaced_story_titles = [
            item.title
            for item in role.story_beats
            if item.beat_id in surfaced_stories.get(role.role_id, [])
        ]
        intent_payload = _ai_actor_intent(
            role,
            actor_type=actor_type,
            player_text=display_text,
            gm_summary=gm_summary,
            priority_reason=priority_reason,
            scene_context=scene_context,
            reputation_score=reputation_score,
            config=config,
            surfaced_desire_titles=surfaced_desire_titles,
            surfaced_story_titles=surfaced_story_titles,
        ) or _fallback_actor_intent(
            role,
            actor_type=actor_type,
            player_text=display_text,
            gm_summary=gm_summary,
            priority_reason=priority_reason,
            has_surfaced_drive=bool(surfaced_desires.get(role.role_id) or surfaced_stories.get(role.role_id)),
            in_encounter=active_encounter is not None and active_encounter.status == "active",
        )

        action_result = None
        if bool(intent_payload.get("needs_check")):
            action_result = _actor_check(
                save,
                role,
                action_type=str(intent_payload.get("action_type") or "check"),
                action_prompt=str(intent_payload.get("action_prompt") or role.name),
                config=config,
            )

        relation_delta = _apply_actor_relation_delta(
            save,
            role,
            actor_type,
            int(intent_payload.get("relation_delta_hint") or 0),
            reputation_score,
        )
        reputation_delta = int(intent_payload.get("reputation_delta_hint") or 0)
        reputation_delta_total += reputation_delta
        situation_delta = _clamp(int(intent_payload.get("situation_delta_hint") or 0) + _check_bonus(action_result), -20, 20)
        line = _compose_actor_resolution(
            role,
            str(intent_payload.get("action_summary") or ""),
            str(intent_payload.get("speech_summary") or ""),
            action_result,
        )
        if not line:
            continue

        role.last_public_turn_at = _utc_now()
        role.cognition_changes.append(f"{role.last_public_turn_at} 公开记忆: {display_text[:64]}")
        role.cognition_changes = role.cognition_changes[-50:]
        role.attitude_changes.append(f"{role.last_public_turn_at} public_director relation={relation_delta:+d} reputation={reputation_delta:+d}")
        role.attitude_changes = role.attitude_changes[-50:]
        if actor_type == "npc":
            context_kind = "public_targeted" if priority_reason == "player_targeted_visible_npc" else ("encounter" if active_encounter is not None else "public_reaction")
            if priority_reason == "player_targeted_visible_npc":
                _append_npc_dialogue(
                    role=role,
                    speaker="player",
                    speaker_role_id=save.player_static_data.player_id,
                    speaker_name=save.player_static_data.name,
                    content=display_text,
                    clock=save.area_snapshot.clock,
                    context_kind="public_targeted",
                )
            _append_npc_dialogue(
                role=role,
                speaker="npc",
                speaker_role_id=role.role_id,
                speaker_name=role.name,
                content=line,
                clock=save.area_snapshot.clock,
                context_kind=context_kind,  # type: ignore[arg-type]
            )
        elif actor_type == "team":
            _append_npc_dialogue(
                role=role,
                speaker="npc",
                speaker_role_id=role.role_id,
                speaker_name=role.name,
                content=line,
                clock=save.area_snapshot.clock,
                context_kind=("encounter" if active_encounter is not None else "team_chat"),
            )
        scene_events.append(
            _new_scene_event(
                "public_actor_resolution",
                line,
                actor_role_id=role.role_id,
                actor_name=role.name,
                metadata={
                    "actor_type": actor_type,
                    "needs_check": bool(action_result is not None),
                    "situation_delta": situation_delta,
                    "reputation_delta": reputation_delta,
                    "relation_delta": relation_delta,
                },
            )
        )
        if priority_reason == "player_targeted_visible_npc" and actor_type == "npc":
            scene_events.append(
                _new_scene_event(
                    "public_targeted_npc_reply",
                    line,
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    metadata={"relation_delta": relation_delta},
                )
            )
        elif actor_type == "npc":
            scene_events.append(
                _new_scene_event(
                    "public_bystander_reaction",
                    line,
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    metadata={"relation_delta": relation_delta},
                )
            )
        elif actor_type == "team":
            scene_events.append(
                _new_scene_event(
                    "team_public_reaction",
                    line,
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                    metadata={"relation_delta": relation_delta},
                )
            )
        if active_encounter is not None and situation_delta != 0:
            try:
                from app.services.encounter_service import apply_active_encounter_situation_delta_in_save

                update_events = apply_active_encounter_situation_delta_in_save(
                    save,
                    session_id=session_id,
                    delta=situation_delta,
                    summary=f"{role.name} 的公开行动改变了局势。",
                    actor_role_id=role.role_id,
                    actor_name=role.name,
                )
                scene_events.extend(update_events)
            except Exception:
                pass

    overflow = [role for role, _, _ in candidates[4:] if role.role_id not in reacted_role_ids]
    if overflow:
        crowd_names = "、".join(item.name for item in overflow[:4])
        scene_events.append(
            _new_scene_event(
                "public_actor_resolution",
                f"其余在场者没有单独插话，只是把注意力集中在局势上：{crowd_names}。",
                actor_name="周围人群",
                metadata={"actor_type": "system", "crowd_summary": True},
            )
        )

    rep_entry, rep_event = apply_sub_zone_reputation_delta(
        save,
        session_id=session_id,
        delta=_clamp(reputation_delta_total, -6, 6),
        reason="公开场景轮次结算",
        actor_name="公开场景",
        append_scene_event=bool(reputation_delta_total),
        append_log=bool(reputation_delta_total),
    )
    if rep_event is not None:
        scene_events.append(rep_event)
        reputation_score = rep_entry.score if rep_entry is not None else reputation_score

    if scene_events:
        save.game_logs.append(
            _new_game_log(
                session_id,
                "public_scene_director",
                f"公开场景导演器推进了 {sum(1 for item in scene_events if item.kind == 'public_actor_resolution')} 个行动体回合",
                {
                    "candidate_count": len(candidates),
                    "resolved_count": sum(1 for item in scene_events if item.kind == "public_actor_resolution"),
                    "reputation_score": reputation_score,
                },
            )
        )
        bystander_count = sum(1 for item in scene_events if item.kind == "public_bystander_reaction")
        if bystander_count > 0:
            save.game_logs.append(
                _new_game_log(
                    session_id,
                    "public_npc_reaction",
                    "公开区域触发周围 NPC 反应",
                    {"count": bystander_count},
                )
            )

    if active_encounter is None and any(item.kind == "public_actor_resolution" for item in scene_events):
        try:
            from app.models.schemas import EncounterCheckRequest
            from app.services.encounter_service import check_for_encounter

            encounter_result = check_for_encounter(
                EncounterCheckRequest(
                    session_id=session_id,
                    trigger_kind="random_dialog",
                    config=config,
                )
            )
            if encounter_result.generated and encounter_result.encounter is not None:
                scene_events.append(
                    _new_scene_event(
                        "encounter_started",
                        f"【遭遇触发】{encounter_result.encounter.title}\n{encounter_result.encounter.description}",
                        metadata={
                            "encounter_id": encounter_result.encounter.encounter_id,
                            "encounter_title": encounter_result.encounter.title,
                        },
                    )
                )
        except Exception:
            pass

    return scene_events[:8]
