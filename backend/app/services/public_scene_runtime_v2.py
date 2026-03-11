from __future__ import annotations

import json

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import ChatConfig, NpcRoleCard, PublicSceneActorCandidate, PublicSceneState, SceneEvent, StoryNpcSummary
from app.services.ai_adapter import build_completion_options, create_sync_client


def _legacy():
    from app.services import public_scene_service as legacy

    return legacy


def _matched_actor_ids(text: str, actors: list[dict[str, object]]) -> list[str]:
    clean_text = str(text or "").strip()
    if not clean_text:
        return []
    matches: list[str] = []
    seen: set[str] = set()
    for actor in actors:
        actor_id = str(actor.get("actor_id") or "")
        actor_name = str(actor.get("name") or "").strip()
        if not actor_id or not actor_name:
            continue
        if actor_name in clean_text and actor_id not in seen:
            seen.add(actor_id)
            matches.append(actor_id)
    return matches


def candidate_rows(
    save,
    *,
    player_text: str,
    addressed_role_name: str = "",
    incoming_target_candidates: list[str] | None = None,
) -> list[dict[str, object]]:
    legacy = _legacy()
    visible_npcs = legacy._visible_public_roles(save)
    team_roles = list(legacy._team_role_map(save).values())
    active_encounter = legacy._active_encounter_for_current_sub_zone(save)
    temp_npcs = legacy._encounter_temp_npcs(save)
    visible_rows: list[dict[str, object]] = [
        {"actor_id": role.role_id, "name": role.name, "actor_type": "npc", "priority_reason": "", "role": role}
        for role in visible_npcs
    ]
    visible_rows.extend(
        {"actor_id": role.role_id, "name": role.name, "actor_type": "team", "priority_reason": "", "role": role}
        for role in team_roles
    )
    visible_rows.extend(
        {
            "actor_id": temp.encounter_npc_id,
            "name": temp.name,
            "actor_type": "encounter_temp_npc",
            "priority_reason": "",
            "temp_npc": temp,
        }
        for temp in temp_npcs
    )
    rows: list[tuple[int, dict[str, object]]] = []

    def add(candidate: dict[str, object], priority: int, reason: str) -> None:
        copy = dict(candidate)
        copy["priority_reason"] = reason
        rows.append((priority, copy))

    if addressed_role_name:
        candidate = next((item for item in visible_rows if legacy._find_actor_name_match(str(item.get("name") or ""), addressed_role_name)), None)
        if candidate is not None:
            add(candidate, 0, "player_targeted_visible_npc")

    incoming_names = [str(name).strip() for name in (incoming_target_candidates or []) if str(name).strip()]
    incoming_text = "\n".join(incoming_names + [player_text]).strip()
    for actor_id in _matched_actor_ids(incoming_text, visible_rows):
        candidate = next((item for item in visible_rows if item.get("actor_id") == actor_id), None)
        if candidate is not None:
            add(candidate, 1, "incoming_player_interaction")

    for temp in temp_npcs:
        candidate = next((item for item in visible_rows if item.get("actor_id") == temp.encounter_npc_id), None)
        if candidate is not None:
            add(candidate, 2, "active_encounter_temp_npc")

    if active_encounter is not None and active_encounter.npc_role_id:
        candidate = next((item for item in visible_rows if item.get("actor_id") == active_encounter.npc_role_id), None)
        if candidate is not None:
            add(candidate, 3, "active_encounter_anchor")

    for candidate in visible_rows:
        if legacy._find_actor_name_match(str(candidate.get("name") or ""), player_text):
            add(candidate, 4, "direct_player_reference")

    if active_encounter is not None and active_encounter.status == "active":
        for role in team_roles:
            candidate = next((item for item in visible_rows if item.get("actor_id") == role.role_id), None)
            if candidate is not None:
                add(candidate, 5, "active_team_presence")

    deduped: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for _, candidate in sorted(rows, key=lambda item: (item[0], str(item[1].get("name") or ""), str(item[1].get("actor_id") or ""))):
        actor_id = str(candidate.get("actor_id") or "")
        if not actor_id or actor_id in seen_ids:
            continue
        seen_ids.add(actor_id)
        deduped.append(candidate)
    if not deduped and visible_rows:
        visible_npc = next((item for item in visible_rows if item.get("actor_type") == "npc"), None)
        if visible_npc is not None:
            deduped.append({**visible_npc, "priority_reason": "scene_fallback_observer"})
    limit = 4 if active_encounter is not None and active_encounter.status == "active" else 2
    return deduped[:limit]


def build_public_scene_state(save, *, session_id: str, player_text: str = "") -> PublicSceneState:
    legacy = _legacy()
    intent = legacy._parse_player_intent(player_text)
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    rep = legacy.get_current_sub_zone_reputation(save, create=True)
    team_roles = legacy._team_role_map(save)
    candidates = candidate_rows(
        save,
        player_text=str(intent.get("display_text") or player_text).strip(),
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=[str(item) for item in list(intent.get("incoming_target_candidates") or [])],
    )
    return PublicSceneState(
        session_id=session_id,
        current_zone_id=save.area_snapshot.current_zone_id,
        current_sub_zone_id=save.area_snapshot.current_sub_zone_id,
        current_reputation=rep,
        visible_npcs=[
            StoryNpcSummary(role_id=role.role_id, name=role.name, zone_id=role.zone_id, sub_zone_id=role.sub_zone_id)
            for role in legacy._visible_public_roles(save)
        ],
        team_members=[
            StoryNpcSummary(role_id=role.role_id, name=role.name, zone_id=role.zone_id, sub_zone_id=role.sub_zone_id)
            for role in team_roles.values()
        ],
        candidate_actors=[
            PublicSceneActorCandidate(
                role_id=str(candidate.get("actor_id") or ""),
                name=str(candidate.get("name") or ""),
                actor_type=str(candidate.get("actor_type") or "npc"),  # type: ignore[arg-type]
                priority_reason=str(candidate.get("priority_reason") or ""),
                surfaced_desire_ids=[],
                surfaced_story_beat_ids=[],
            )
            for candidate in candidates
        ],
        surfaced_drives=[],
        active_encounter=legacy._active_encounter_for_current_sub_zone(save),
    )


def _build_incoming_map(save, actors: list[dict[str, object]], *, parsed_intent: dict[str, object], display_text: str) -> dict[str, dict[str, str]]:
    incoming: dict[str, dict[str, str]] = {}
    referenced_names = [str(item).strip() for item in list(parsed_intent.get("incoming_target_candidates") or []) if str(item).strip()]
    incoming_text = "\n".join([display_text, *referenced_names]).strip()
    for actor_id in _matched_actor_ids(incoming_text, actors):
        incoming[actor_id] = {
            "source_actor_id": save.player_static_data.player_id,
            "source_actor_name": save.player_static_data.name,
            "summary": display_text[:180],
        }
    return incoming


def _fallback_actor_action(save, actor: dict[str, object], *, player_text: str, gm_summary: str, incoming_interaction: dict[str, str] | None) -> dict[str, object]:
    legacy = _legacy()
    name = str(actor.get("name") or "在场角色")
    actor_type = str(actor.get("actor_type") or "npc")
    active_encounter = legacy._active_encounter_for_current_sub_zone(save)
    focus = legacy._scene_focus_label(save, player_text, gm_summary)
    incoming_summary = str((incoming_interaction or {}).get("summary") or "").strip()
    incoming_from_actor_name = str((incoming_interaction or {}).get("source_actor_name") or "").strip()
    response_mode = "respond" if incoming_interaction else "none"

    if active_encounter is not None:
        target_label = active_encounter.title or focus
        risk_source = "遭遇现场"
        risk_object = target_label
        risk_location = active_encounter.sub_zone_id or save.area_snapshot.current_sub_zone_id or "当前子区域"
        if actor_type == "encounter_temp_npc":
            visible_intent = f"先把{target_label}里最危险的失控点压住。"
            private_goal = f"用自己的经验稳住{target_label}最先要出事的位置。"
            private_reason = str(getattr(actor.get("temp_npc"), "agenda", "") or "不想让现场继续失控。").strip()
            speech_line = f"“先别乱动，最危险的地方在{target_label}里面，我先去压住它。”"
            external_action_narration = f"{name}眉头拧得很紧，先把视线钉在{target_label}边缘最容易失控的那一处，随后快步挤进人群，抬手示意周围人先退开，自己则俯身去压住最危险的点。"
            specific_threat = f"{risk_location}里围绕{risk_object}的失控点还在继续扩散，如果再慢一步，现场压力就会直接压向玩家和队伍。"
            situation_delta_hint = 3
        elif actor_type == "team":
            visible_intent = "替玩家争取一个更稳的处理窗口。"
            private_goal = f"先帮玩家压住{target_label}周围最危险的部分。"
            private_reason = "不想让眼前的险情继续扩大到玩家身上。"
            speech_line = "“我先替你压住这边，你别让它继续往外炸开。”"
            external_action_narration = f"{name}先看了一眼玩家和险情之间的距离，神色明显收紧，随后压低重心贴向{target_label}边缘，伸手去按住最先失控的那一处，想替玩家抢出一点处理空间。"
            specific_threat = f"{risk_location}里围绕{risk_object}的险情已经顶到了队伍正前方，再拖下去就会把整个场面压得更乱。"
            situation_delta_hint = 3
        else:
            visible_intent = f"先确认{target_label}真正失控的源头。"
            private_goal = f"查清{target_label}里哪一处最先出了问题。"
            private_reason = "只有先找准源头，接下来才知道该拦哪里。"
            speech_line = f"“别碰那边，我先去确认{target_label}到底是哪一处先失控了。”"
            external_action_narration = f"{name}顺着玩家刚才的动作看向现场，脸色一下子紧了起来，随后快步靠近{target_label}，一边抬手拦住旁人，一边把视线钉在最可疑的那一处，想先找出真正的失控源头。"
            specific_threat = f"{risk_location}里围绕{risk_object}的异常还没被说破，最危险的部分藏在表面混乱后面，一旦判断错了就会让局势继续扩散。"
            situation_delta_hint = 2
    else:
        target_label = focus
        risk_source = incoming_from_actor_name or "当前公开场景"
        risk_object = name
        risk_location = save.area_snapshot.current_sub_zone_id or "当前子区域"
        visible_intent = "先回应眼前直接落到自己身上的那件事。"
        private_goal = "先弄清玩家到底想让自己怎么表态。"
        private_reason = "如果不先回应，场上的误解会越积越多。"
        speech_line = "“你先把话说清楚，我得知道你到底是冲着哪件事来的。”"
        external_action_narration = f"{name}把视线重新落回到玩家身上，表情明显收紧，随后停下手里的动作，微微侧身正对着玩家，像是要先把刚才那句话听个明白再决定下一步。"
        specific_threat = f"{risk_location}里最直接的压力落在{name}身上，如果不先把玩家刚才的意思说明白，公开场面很容易继续僵住。"
        situation_delta_hint = 0

    incoming_reaction_narration = ""
    incoming_reaction_speech = ""
    if response_mode == "respond" and incoming_summary:
        incoming_reaction_narration = f"{name}先被{incoming_from_actor_name or '他人'}刚才那一下动作和话头牵住了注意力，眼神明显顿了一下，随后才把重心转回到自己要处理的事情上。"
        incoming_reaction_speech = "“我听到了，你先别催，让我先把眼前这一步处理掉。”"

    return {
        "response_mode": response_mode,
        "incoming_from_actor_id": str((incoming_interaction or {}).get("source_actor_id") or ""),
        "incoming_from_actor_name": incoming_from_actor_name,
        "incoming_summary": incoming_summary[:160],
        "incoming_reaction_narration": incoming_reaction_narration[:180],
        "incoming_reaction_speech": incoming_reaction_speech[:140],
        "ignore_reason": "",
        "external_action_narration": external_action_narration[:220],
        "speech_line": speech_line[:140],
        "visible_intent": visible_intent[:160],
        "private_goal": private_goal[:160],
        "private_reason": private_reason[:160],
        "expression_cues": "目光收紧，神情明显紧绷。",
        "body_language": "重心前压，视线始终钉在要处理的对象上。",
        "risk_source": risk_source[:80],
        "risk_object": risk_object[:80],
        "risk_location": risk_location[:80],
        "specific_threat": specific_threat[:180],
        "target_label": target_label[:80],
        "needs_check": bool(active_encounter is not None),
        "action_type": "check",
        "action_prompt": f"actor={name}; target={target_label}; threat={specific_threat}; intent={visible_intent}",
        "situation_delta_hint": legacy._clamp(situation_delta_hint, -8, 8),
    }


def _ai_actor_action(
    save,
    actor: dict[str, object],
    *,
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None,
    incoming_interaction: dict[str, str] | None,
    config: ChatConfig | None,
) -> dict[str, object] | None:
    legacy = _legacy()
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    try:
        world_time_text, _ = legacy._world_time_payload(scene_context.get("world_time") if isinstance(scene_context, dict) else None)  # type: ignore[arg-type]
    except Exception:
        world_time_text = ""
    prompt = prompt_table.render(
        PromptKeys.SCENE_ACTOR_ACTION_USER,
        "",
        role_name=str(actor.get("name") or ""),
        actor_type=str(actor.get("actor_type") or "npc"),
        roleplay_brief=legacy._actor_roleplay_brief(actor),
        player_text=player_text,
        gm_summary=gm_summary,
        world_time_text=world_time_text,
        priority_reason=str(actor.get("priority_reason") or ""),
        incoming_interaction_json=json.dumps(incoming_interaction or {}, ensure_ascii=False),
        scene_context_json=legacy._scene_context_json(scene_context),
    )
    try:
        client = legacy.create_sync_client(config, client_cls=legacy.OpenAI)
        response = client.chat.completions.create(
            model=model,
            **legacy.build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = legacy._extract_json_content((response.choices[0].message.content or "").strip())
    except Exception:
        return None
    payload = {
        "response_mode": str(parsed.get("response_mode") or ("respond" if incoming_interaction else "none")).strip().lower(),
        "incoming_from_actor_id": str((incoming_interaction or {}).get("source_actor_id") or ""),
        "incoming_from_actor_name": str((incoming_interaction or {}).get("source_actor_name") or ""),
        "incoming_summary": str((incoming_interaction or {}).get("summary") or "")[:160],
        "incoming_reaction_narration": str(parsed.get("incoming_reaction_narration") or "")[:180],
        "incoming_reaction_speech": str(parsed.get("incoming_reaction_speech") or "")[:140],
        "ignore_reason": str(parsed.get("ignore_reason") or "")[:120],
        "external_action_narration": str(parsed.get("external_action_narration") or "")[:220],
        "speech_line": str(parsed.get("speech_line") or "")[:140],
        "visible_intent": str(parsed.get("visible_intent") or "")[:160],
        "private_goal": str(parsed.get("private_goal") or "")[:160],
        "private_reason": str(parsed.get("private_reason") or "")[:160],
        "expression_cues": str(parsed.get("expression_cues") or "")[:120],
        "body_language": str(parsed.get("body_language") or "")[:120],
        "risk_source": str(parsed.get("risk_source") or "")[:80],
        "risk_object": str(parsed.get("risk_object") or "")[:80],
        "risk_location": str(parsed.get("risk_location") or "")[:80],
        "specific_threat": str(parsed.get("specific_threat") or "")[:180],
        "target_label": str(parsed.get("target_label") or "")[:80],
        "needs_check": bool(parsed.get("needs_check")),
        "action_type": str(parsed.get("action_type") or "check").strip().lower(),
        "action_prompt": str(parsed.get("action_prompt") or "")[:200],
        "situation_delta_hint": legacy._clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
    }
    if payload["response_mode"] not in {"respond", "ignore", "none"}:
        return None
    if str(payload["action_type"]) not in {"check", "attack", "item_use"}:
        payload["action_type"] = "check"
    required_text = ["external_action_narration", "speech_line", "visible_intent", "risk_source", "risk_object", "risk_location", "specific_threat"]
    if any(not str(payload.get(key) or "").strip() for key in required_text):
        return None
    if legacy._looks_too_vague(str(payload["external_action_narration"])) or legacy._looks_too_vague(str(payload["specific_threat"])):
        return None
    if not str(payload["action_prompt"]):
        payload["action_prompt"] = f"actor={actor.get('name')}; target={payload['target_label']}; threat={payload['specific_threat']}; intent={payload['visible_intent']}"
    return payload


def _ai_round_resolution(
    result_rows: list[dict[str, object]],
    *,
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None,
    predicted_situation_value: int,
    direction: str,
    config: ChatConfig | None,
) -> str | None:
    legacy = _legacy()
    if config is None or not result_rows:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    prompt = prompt_table.render(
        PromptKeys.SCENE_ROUND_RESOLVE_USER,
        "",
        player_text=player_text,
        gm_summary=gm_summary,
        direction=direction,
        predicted_situation_value=predicted_situation_value,
        scene_context_json=legacy._scene_context_json(scene_context),
        result_rows_json=json.dumps(result_rows, ensure_ascii=False),
    )
    try:
        client = legacy.create_sync_client(config, client_cls=legacy.OpenAI)
        response = client.chat.completions.create(
            model=model,
            **legacy.build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = legacy._extract_json_content((response.choices[0].message.content or "").strip())
        text = str(parsed.get("resolution_text") or "").strip()[:720]
        if not text or legacy._looks_too_vague(text):
            return None
        return text
    except Exception:
        return None


def _compose_actor_content(payload: dict[str, object]) -> str:
    lines = [
        "【外在行为】",
        str(payload.get("external_action_narration") or "").strip(),
        "【角色语言】",
        str(payload.get("speech_line") or "").strip(),
        "【表面意图】",
        str(payload.get("visible_intent") or "").strip(),
        "【眼前风险】",
        str(payload.get("specific_threat") or "").strip(),
        "【调试·内在目标】",
        str(payload.get("private_goal") or "").strip(),
        "【调试·内在原因】",
        str(payload.get("private_reason") or "").strip(),
    ]
    return "\n".join(part for part in lines if part).strip()[:720]


def advance_public_scene_in_save(
    save,
    session_id: str,
    player_text: str,
    gm_summary: str = "",
    scene_context: dict[str, object] | None = None,
    config: ChatConfig | None = None,
) -> list[SceneEvent]:
    legacy = _legacy()
    intent = legacy._parse_player_intent(player_text)
    display_text = str(intent.get("display_text") or player_text).strip()
    if not bool(intent.get("passive_turn")) and not legacy._public_behavior_triggered(str(intent.get("action_text") or ""), str(intent.get("speech_text") or ""), str(intent.get("raw_text") or "")):
        return []
    if scene_context is None:
        from app.services.world_service import _build_scene_context_payload

        scene_context = _build_scene_context_payload(save, player_text=player_text, gm_narration=gm_summary, recent_turn_count=4)
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    active_encounter = legacy._active_encounter_for_current_sub_zone(save)
    reputation_entry = legacy.get_current_sub_zone_reputation(save, create=True)
    reputation_score = reputation_entry.score if reputation_entry is not None else 50
    candidates = candidate_rows(
        save,
        player_text=display_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=[str(item) for item in list(intent.get("incoming_target_candidates") or [])],
    )
    if not candidates:
        return []
    incoming_map = _build_incoming_map(save, candidates, parsed_intent=intent, display_text=display_text)
    scene_events: list[SceneEvent] = []
    result_rows: list[dict[str, object]] = []
    total_situation_delta = 0
    reputation_delta_total = 0
    seen_risks: set[tuple[str, str, str]] = set()

    for actor in candidates:
        actor_id = str(actor.get("actor_id") or "")
        incoming = incoming_map.get(actor_id)
        payload = _ai_actor_action(
            save,
            actor,
            player_text=display_text,
            gm_summary=gm_summary,
            scene_context=scene_context,
            incoming_interaction=incoming,
            config=config,
        ) or _fallback_actor_action(
            save,
            actor,
            player_text=display_text,
            gm_summary=gm_summary,
            incoming_interaction=incoming,
        )
        risk_key = (str(payload.get("risk_source") or ""), str(payload.get("risk_object") or ""), str(payload.get("risk_location") or ""))
        if risk_key in seen_risks:
            payload["risk_object"] = f"{actor.get('name') or '该角色'}眼前那一处最容易出事的地方"
            payload["specific_threat"] = f"{payload['risk_location']}里围绕{payload['risk_object']}的压力正在继续堆高，如果这一步处理慢了，现场就会更难收住。"
        seen_risks.add((str(payload.get("risk_source") or ""), str(payload.get("risk_object") or ""), str(payload.get("risk_location") or "")))

        action_content = _compose_actor_content(payload)
        scene_events.append(
            legacy._new_scene_event(
                "public_actor_action",
                action_content,
                actor_role_id=actor_id,
                actor_name=str(actor.get("name") or ""),
                metadata={
                    **payload,
                    "actor_type": str(actor.get("actor_type") or "npc"),
                },
            )
        )
        legacy._append_actor_memory(save, actor, display_text=display_text, action_line=action_content, priority_reason=str(actor.get("priority_reason") or ""))
        action_result = None
        if bool(payload.get("needs_check")):
            action_result = legacy._actor_check(
                save,
                actor_id,
                action_type=str(payload.get("action_type") or "check"),
                action_prompt=str(payload.get("action_prompt") or action_content),
                config=config,
            )
        situation_delta = legacy._clamp(int(payload.get("situation_delta_hint") or 0) + legacy._check_bonus(action_result), -20, 20)
        total_situation_delta += situation_delta
        reputation_delta = legacy._resolution_reputation_delta(str(actor.get("actor_type") or "npc"), situation_delta)
        relation_delta = legacy._resolution_relation_delta(str(actor.get("actor_type") or "npc"), action_result, situation_delta)
        reputation_delta_total += reputation_delta
        role = actor.get("role")
        applied_relation_delta = 0
        if isinstance(role, NpcRoleCard) and relation_delta != 0:
            applied_relation_delta = legacy._apply_actor_relation_delta(save, role, str(actor.get("actor_type") or "npc"), relation_delta, reputation_score)
        affected_object = str(payload.get("target_label") or payload.get("risk_object") or "眼前局面")
        if action_result is not None and action_result.narrative:
          concrete_effect = str(action_result.narrative).strip()[:220]
        elif situation_delta > 0:
          concrete_effect = f"{actor.get('name')}暂时压住了{affected_object}周围最直接的风险，现场因此出现了可以继续处理的空档。"
        elif situation_delta < 0:
          concrete_effect = f"{actor.get('name')}这一步没能压住{affected_object}附近的险情，压力反而被推得更近。"
        else:
          concrete_effect = f"{actor.get('name')}先把动作落到了{affected_object}上，但现场暂时只是维持住了僵持。"
        result_rows.append(
            {
                "actor_id": actor_id,
                "actor_name": str(actor.get("name") or ""),
                "result": ("成功" if action_result is not None and action_result.success else ("失败" if action_result is not None else ("推进成功" if situation_delta > 0 else ("推进受阻" if situation_delta < 0 else "维持僵持")))),
                "affected_object": affected_object,
                "concrete_effect": concrete_effect,
                "opened_opportunity": (f"玩家现在可以顺着{affected_object}继续追查真正的源头。" if situation_delta >= 0 else f"玩家仍能直接介入{affected_object}，但必须更快。"),
                "new_pressure": ("现场仍有余压，但不再立刻外溢。" if situation_delta > 0 else ("局面没有继续恶化，但也还没有被真正压住。" if situation_delta == 0 else f"{affected_object}附近的风险正在继续扩大。")),
                "resolution_line": f"{actor.get('name')}：{concrete_effect}",
                "situation_delta": situation_delta,
                "reputation_delta": reputation_delta,
                "relation_delta": applied_relation_delta,
            }
        )

    predicted_situation_value = legacy._predict_situation_value(save, total_situation_delta)
    direction = "hold"
    trend = "stable"
    situation_before = active_encounter.situation_value if active_encounter is not None else 0
    if active_encounter is not None:
        from app.services.encounter_runtime_v2 import assess_situation_change

        assessment = assess_situation_change(situation_before, total_situation_delta, predicted_situation_value)
        direction = assessment.direction
        trend = assessment.trend
    resolution_lines = [str(item.get("resolution_line") or "") for item in result_rows if str(item.get("resolution_line") or "").strip()]
    if direction == "stabilize":
        resolution_lines.append(f"这一轮之后，局势值来到 {predicted_situation_value}/100，现场被暂时压住，玩家下一步可以趁着这点空间继续处理最关键的失控点。")
    elif direction == "worsen":
        resolution_lines.append(f"这一轮之后，局势值掉到 {predicted_situation_value}/100，现场压力继续扩大，玩家下一步必须立刻处理最先要出事的位置。")
    else:
        resolution_lines.append(f"这一轮之后，局势值停在 {predicted_situation_value}/100，现场暂时维持僵持，没有继续恶化，但还没有真正突破。")
    fallback_resolution_text = "\n".join(line for line in resolution_lines if line).strip()[:720]
    resolution_text = _ai_round_resolution(
        result_rows,
        player_text=display_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        predicted_situation_value=predicted_situation_value,
        direction=direction,
        config=config,
    ) or fallback_resolution_text
    if active_encounter is not None:
        from app.services.encounter_service import apply_active_encounter_situation_delta_in_save

        scene_events.extend(
            apply_active_encounter_situation_delta_in_save(save, session_id=session_id, delta=total_situation_delta, summary=resolution_text, actor_name="公开轮次")
        )
    rep_entry, rep_event = legacy.apply_sub_zone_reputation_delta(
        save,
        session_id=session_id,
        delta=legacy._clamp(reputation_delta_total, -6, 6),
        reason="公开场景轮次结算",
        actor_name="公开场景",
        append_scene_event=bool(reputation_delta_total),
        append_log=bool(reputation_delta_total),
    )
    if rep_event is not None:
        scene_events.append(rep_event)
        reputation_score = rep_entry.score if rep_entry is not None else reputation_score
    scene_events.append(
        legacy._new_scene_event(
            "public_round_resolution",
            resolution_text,
            actor_name="GM",
            metadata={
                "actor_type": "system",
                "candidate_count": len(result_rows),
                "reputation_score": reputation_score,
                "predicted_situation_value": predicted_situation_value,
                "situation_value_before": situation_before,
                "situation_value_after": predicted_situation_value,
                "direction": direction,
                "trend": trend,
                "result_rows": result_rows,
            },
        )
    )
    save.game_logs.append(
        legacy._new_game_log(
            session_id,
            "public_scene_director",
            f"鍏紑鍦烘櫙鎺ㄨ繘浜?{len(result_rows)} 涓鍔ㄥ０鏄庯紝骞剁粺涓€瀹屾垚杞缁撶畻",
            {
                "candidate_count": len(result_rows),
                "predicted_situation_value": predicted_situation_value,
                "direction": direction,
                "trend": trend,
                "reputation_score": reputation_score,
            },
        )
    )
    if active_encounter is None and any(item.kind == "public_actor_action" for item in scene_events):
        try:
            from app.models.schemas import EncounterCheckRequest
            from app.services.encounter_service import check_for_encounter

            encounter_result = check_for_encounter(
                EncounterCheckRequest(session_id=session_id, trigger_kind="random_dialog", config=config)
            )
            if encounter_result.generated and encounter_result.encounter is not None:
                scene_events.append(
                    legacy._new_scene_event(
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
    return scene_events[:10]
