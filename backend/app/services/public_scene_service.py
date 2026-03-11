from __future__ import annotations

from datetime import datetime, timezone
import json

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    ChatConfig,
    EncounterTemporaryNpc,
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


def _scene_context_json(scene_context: dict[str, object] | None) -> str:
    return json.dumps(scene_context or {}, ensure_ascii=False, indent=2)


def _team_role_map(save: SaveFile) -> dict[str, NpcRoleCard]:
    member_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
    return {
        role.role_id: role
        for role in save.role_pool
        if role.role_id in member_ids
    }


def _team_member_by_role_id(save: SaveFile, role_id: str):
    return next((item for item in getattr(save.team_state, "members", []) if item.role_id == role_id), None)


def _encounter_temp_npcs(save: SaveFile) -> list[EncounterTemporaryNpc]:
    active_encounter = _active_encounter_for_current_sub_zone(save)
    if active_encounter is None or active_encounter.status != "active":
        return []
    return list(getattr(active_encounter, "temporary_npcs", []) or [])


def _find_actor_name_match(name: str, text: str) -> bool:
    clean_name = (name or "").strip()
    clean_text = (text or "").strip()
    return bool(clean_name and clean_text and clean_name in clean_text)


def _scene_focus_label(save: SaveFile, player_text: str, gm_summary: str) -> str:
    active_encounter = _active_encounter_for_current_sub_zone(save)
    if active_encounter is not None:
        for candidate in [
            active_encounter.scene_summary,
            active_encounter.title,
            active_encounter.description,
            gm_summary,
            player_text,
        ]:
            clean = " ".join(str(candidate or "").split()).strip()
            if clean:
                return clean[:48]
    for candidate in [gm_summary, player_text]:
        clean = " ".join(str(candidate or "").split()).strip()
        if clean:
            return clean[:48]
    return "当前场面"


def _contains_concrete_marker(text: str) -> bool:
    concrete_tokens = [
        "书架",
        "书页",
        "桌面",
        "地板",
        "窗",
        "门",
        "锁",
        "楼梯",
        "墙",
        "符文",
        "影子",
        "管理员",
        "火",
        "灯",
        "绳",
        "木板",
        "脚步",
        "柜",
        "台阶",
        "走廊",
        "巷",
        "血",
        "石",
        "箱",
        "架",
    ]
    return any(token in (text or "") for token in concrete_tokens)


def _looks_too_vague(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return True
    vague_tokens = [
        "危险",
        "异常",
        "变化",
        "局势",
        "紧张",
        "不安",
        "某种",
        "似乎",
        "仿佛",
        "威胁",
        "压力",
        "进展",
    ]
    if any(token in clean for token in vague_tokens) and not _contains_concrete_marker(clean):
        return True
    return False


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


def _actor_check(
    save: SaveFile,
    actor_id: str,
    *,
    action_type: str,
    action_prompt: str,
    config: ChatConfig | None,
) -> ActionCheckResponse | None:
    try:
        return action_check(
            ActionCheckRequest(
                session_id=save.session_id,
                actor_role_id=actor_id,
                action_type=action_type,  # type: ignore[arg-type]
                action_prompt=action_prompt,
                allow_backend_roll=True,
                resolution_context="embedded",
                config=config,
            )
        )
    except Exception:
        return None


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
        return applied
    next_tag = _relation_tag_after_delta(role, save.player_static_data.player_id, applied)
    _upsert_npc_player_relation(role, save.player_static_data.player_id, next_tag, "公开场景轮次结算")
    return applied


def _actor_roleplay_brief(actor: dict[str, object]) -> str:
    role = actor.get("role")
    if isinstance(role, NpcRoleCard):
        return _build_npc_roleplay_brief(role)
    temp_npc = actor.get("temp_npc")
    if isinstance(temp_npc, EncounterTemporaryNpc):
        parts = [
            f"姓名={temp_npc.name}",
            f"头衔={temp_npc.title}",
            f"描述={temp_npc.description}",
            f"说话风格={temp_npc.speaking_style}",
            f"当前意图={temp_npc.agenda}",
        ]
        return "；".join(part for part in parts if part and not part.endswith("="))
    return str(actor.get("name") or "在场角色")


def _fallback_actor_action(
    save: SaveFile,
    actor: dict[str, object],
    *,
    player_text: str,
    gm_summary: str,
    priority_reason: str,
) -> dict[str, object]:
    name = str(actor.get("name") or "在场角色")
    actor_type = str(actor.get("actor_type") or "npc")
    active_encounter = _active_encounter_for_current_sub_zone(save)
    focus = _scene_focus_label(save, player_text, gm_summary)
    if active_encounter is not None:
        target_label = active_encounter.title or focus
        specific_threat = active_encounter.scene_summary or active_encounter.description or focus
        stakes = f"不让{target_label}继续恶化"
        if actor_type == "team":
            action_summary = f"立刻贴近{target_label}的核心位置，先去稳住最容易失控的那一处。"
            speech_summary = f"提醒大家先盯住{target_label}里最危险的部分。"
            situation_delta_hint = 3
        elif actor_type == "encounter_temp_npc":
            agenda = str(getattr(actor.get("temp_npc"), "agenda", "") or "").strip()
            action_summary = f"直接把注意力转向{target_label}，试图按自己熟悉的方式处理现场。"
            speech_summary = agenda[:80]
            situation_delta_hint = 2
        else:
            action_summary = f"快步靠向{target_label}，试着先确认造成混乱的具体源头。"
            speech_summary = "示意周围人别碰最危险的位置。"
            situation_delta_hint = 2
        needs_check = True
    else:
        target_label = focus
        specific_threat = f"{focus}里最容易被忽略的异常点"
        stakes = f"把{focus}说明白"
        if priority_reason.startswith("player_targeted"):
            action_summary = "把注意力转向你，准备先回应你点出的那件事。"
            speech_summary = "让你直接说清楚最关键的那部分。"
        else:
            action_summary = f"停下手里的事，转头确认{focus}到底出了什么问题。"
            speech_summary = ""
        situation_delta_hint = 0
        needs_check = False
    return {
        "action_summary": action_summary[:160],
        "speech_summary": speech_summary[:120],
        "needs_check": needs_check,
        "action_type": "check",
        "action_prompt": f"actor={name}; target={target_label}; stakes={stakes}; threat={specific_threat}",
        "target_label": target_label[:80],
        "stakes": stakes[:120],
        "specific_threat": specific_threat[:120],
        "situation_delta_hint": _clamp(situation_delta_hint, -8, 8),
    }


def _ai_actor_action(
    actor: dict[str, object],
    *,
    player_text: str,
    gm_summary: str,
    priority_reason: str,
    scene_context: dict[str, object] | None,
    config: ChatConfig | None,
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
        PromptKeys.SCENE_ACTOR_ACTION_USER,
        (
            "你要为公开场景中的一个非玩家行动体生成本轮动作声明，只输出 JSON。"
            "Schema={\"action_summary\":\"\",\"speech_summary\":\"\",\"needs_check\":true,"
            "\"action_type\":\"check|attack|item_use\",\"action_prompt\":\"\",\"target_label\":\"\","
            "\"stakes\":\"\",\"specific_threat\":\"\",\"situation_delta_hint\":0}。"
            "动作声明必须具体到对象、目标和风险，不允许只说发现危险、局势变化或情况恶化。"
        ),
        role_name=str(actor.get("name") or ""),
        actor_type=str(actor.get("actor_type") or "npc"),
        roleplay_brief=_actor_roleplay_brief(actor),
        player_text=player_text,
        gm_summary=gm_summary,
        world_time_text=world_time_text,
        priority_reason=priority_reason,
        scene_context_json=_scene_context_json(scene_context),
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((response.choices[0].message.content or "").strip())
    except Exception:
        return None
    action_summary = str(parsed.get("action_summary") or "").strip()[:160]
    speech_summary = str(parsed.get("speech_summary") or "").strip()[:120]
    action_type = str(parsed.get("action_type") or "check").strip().lower()
    if action_type not in {"check", "attack", "item_use"}:
        action_type = "check"
    action_prompt = str(parsed.get("action_prompt") or "").strip()[:160]
    target_label = str(parsed.get("target_label") or "").strip()[:80]
    stakes = str(parsed.get("stakes") or "").strip()[:120]
    specific_threat = str(parsed.get("specific_threat") or "").strip()[:120]
    if not action_summary or not target_label or not stakes or not specific_threat:
        return None
    if _looks_too_vague(action_summary) or _looks_too_vague(specific_threat):
        return None
    return {
        "action_summary": action_summary,
        "speech_summary": speech_summary,
        "needs_check": bool(parsed.get("needs_check")),
        "action_type": action_type,
        "action_prompt": action_prompt or f"actor={actor.get('name')}; target={target_label}; stakes={stakes}; threat={specific_threat}",
        "target_label": target_label,
        "stakes": stakes,
        "specific_threat": specific_threat,
        "situation_delta_hint": _clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
    }


def _compose_actor_action_line(actor: dict[str, object], payload: dict[str, object]) -> str:
    name = str(actor.get("name") or "在场角色")
    action_summary = str(payload.get("action_summary") or "").strip()
    speech_summary = str(payload.get("speech_summary") or "").strip()
    target_label = str(payload.get("target_label") or "").strip()
    stakes = str(payload.get("stakes") or "").strip()
    specific_threat = str(payload.get("specific_threat") or "").strip()
    parts = [f"{name}{action_summary}"]
    if target_label:
        parts.append(f"目标是：{target_label}")
    if stakes:
        parts.append(f"意图是：{stakes}")
    if specific_threat:
        parts.append(f"眼前风险是：{specific_threat}")
    if speech_summary:
        parts.append(f"{name}同时出声提醒：{speech_summary}")
    line = " ".join(part for part in parts if part.strip()).strip()
    return line[:320]


def _candidate_rows(
    save: SaveFile,
    *,
    player_text: str,
    addressed_role_name: str = "",
) -> list[dict[str, object]]:
    visible_npcs = _visible_public_roles(save)
    team_roles = list(_team_role_map(save).values())
    active_encounter = _active_encounter_for_current_sub_zone(save)
    temp_npcs = _encounter_temp_npcs(save)
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
    seen_ids: set[str] = set()

    def add(candidate: dict[str, object], priority: int, reason: str) -> None:
        actor_id = str(candidate.get("actor_id") or "")
        if not actor_id:
            return
        copy = dict(candidate)
        copy["priority_reason"] = reason
        rows.append((priority, copy))

    targeted = next(
        (
            candidate
            for candidate in visible_rows
            if addressed_role_name and _find_actor_name_match(str(candidate.get("name") or ""), addressed_role_name)
        ),
        None,
    )
    if targeted is None:
        targeted = next(
            (
                candidate
                for candidate in visible_rows
                if _find_actor_name_match(str(candidate.get("name") or ""), player_text)
            ),
            None,
        )
    if targeted is not None:
        add(targeted, 0, "player_targeted_visible_npc")

    for temp in temp_npcs:
        candidate = next((item for item in visible_rows if item.get("actor_id") == temp.encounter_npc_id), None)
        if candidate is not None:
            add(candidate, 1, "active_encounter_temp_npc")

    if active_encounter is not None and active_encounter.npc_role_id:
        candidate = next((item for item in visible_rows if item.get("actor_id") == active_encounter.npc_role_id), None)
        if candidate is not None:
            add(candidate, 2, "active_encounter_anchor")

    for candidate in visible_rows:
        if candidate is targeted:
            continue
        if _find_actor_name_match(str(candidate.get("name") or ""), player_text):
            add(candidate, 3, "direct_player_reference")

    if active_encounter is not None and active_encounter.status == "active":
        for role in team_roles:
            candidate = next((item for item in visible_rows if item.get("actor_id") == role.role_id), None)
            if candidate is not None:
                add(candidate, 4, "active_team_presence")
    elif not rows and visible_npcs:
        add(
            {"actor_id": visible_npcs[0].role_id, "name": visible_npcs[0].name, "actor_type": "npc", "role": visible_npcs[0]},
            6,
            "scene_fallback_observer",
        )

    deduped: list[dict[str, object]] = []
    for _, candidate in sorted(rows, key=lambda item: (item[0], str(item[1].get("name") or ""), str(item[1].get("actor_id") or ""))):
        actor_id = str(candidate.get("actor_id") or "")
        if actor_id in seen_ids:
            continue
        seen_ids.add(actor_id)
        deduped.append(candidate)
    limit = 4 if active_encounter is not None and active_encounter.status == "active" else 2
    return deduped[:limit]


def build_public_scene_state(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str = "",
) -> PublicSceneState:
    intent = _parse_player_intent(player_text)
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
    rep = get_current_sub_zone_reputation(save, create=True)
    team_roles = _team_role_map(save)
    candidates = _candidate_rows(
        save,
        player_text=str(intent.get("display_text") or player_text).strip(),
        addressed_role_name=addressed_role_name,
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


def _resolution_relation_delta(actor_type: str, action_result: ActionCheckResponse | None, situation_delta: int) -> int:
    if actor_type == "encounter_temp_npc":
        return 0
    if action_result is not None:
        if action_result.critical == "critical_success":
            return 2
        if action_result.critical == "critical_failure":
            return -2
        if action_result.success:
            return 1
        return -1
    if situation_delta > 2:
        return 1
    if situation_delta < -2:
        return -1
    return 0


def _resolution_reputation_delta(actor_type: str, situation_delta: int) -> int:
    if actor_type not in {"npc", "team", "encounter_temp_npc"}:
        return 0
    if situation_delta >= 4:
        return 1
    if situation_delta <= -4:
        return -1
    return 0


def _predict_situation_value(save: SaveFile, situation_delta_total: int) -> int:
    active_encounter = _active_encounter_for_current_sub_zone(save)
    if active_encounter is None:
        return 0
    return _clamp(active_encounter.situation_value + situation_delta_total, 0, 100)


def _fallback_round_resolution(records: list[dict[str, object]], *, predicted_situation_value: int) -> str:
    if not records:
        return ""
    lines: list[str] = []
    for record in records:
        name = str(record.get("name") or "在场角色")
        target_label = str(record.get("target_label") or "眼前局面")
        stakes = str(record.get("stakes") or "先把事情稳住")
        threat = str(record.get("specific_threat") or "最危险的部分")
        action_result = record.get("action_result")
        if isinstance(action_result, ActionCheckResponse):
            if action_result.critical == "critical_success":
                outcome = "大成功"
            elif action_result.critical == "critical_failure":
                outcome = "大失败"
            else:
                outcome = "成功" if action_result.success else "失败"
            detail = (action_result.narrative or "").strip()
            if not detail:
                if action_result.success:
                    detail = f"{name}把{target_label}里最关键的风险压住了，{stakes}。"
                else:
                    detail = f"{name}没能处理好{target_label}，{threat}反而压得更近。"
            lines.append(f"{name}处理{target_label}时检定{outcome}，{detail}")
        else:
            lines.append(f"{name}已经把动作落到了{target_label}上，意图是{stakes}，现场最危险的是{threat}。")
    if predicted_situation_value:
        lines.append(f"GM随后把这一轮的结果汇总起来，局势值来到 {predicted_situation_value}/100，下一轮的压力和机会都已经摆在明处。")
    return "\n".join(lines)[:640]


def _ai_round_resolution(
    records: list[dict[str, object]],
    *,
    player_text: str,
    gm_summary: str,
    scene_context: dict[str, object] | None,
    predicted_situation_value: int,
    config: ChatConfig | None,
) -> str | None:
    if config is None or not records:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    prompt = prompt_table.render(
        PromptKeys.SCENE_ROUND_RESOLVE_USER,
        (
            "你要把一轮公开场景的行动统一结算成一段 GM 反馈，只输出 JSON。"
            "Schema={\"resolution_text\":\"...\"}。"
            "必须逐条说清谁成功或失败、影响了什么对象、什么风险被推进或暴露、给下一轮留下什么机会或压力。"
            "不允许只说局势恶化、发现危险、出现异常。"
        ),
        player_text=player_text,
        gm_summary=gm_summary,
        predicted_situation_value=predicted_situation_value,
        scene_context_json=_scene_context_json(scene_context),
        action_rows_json=json.dumps(records, ensure_ascii=False),
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((response.choices[0].message.content or "").strip())
        text = str(parsed.get("resolution_text") or "").strip()[:640]
        if not text or _looks_too_vague(text):
            return None
        return text
    except Exception:
        return None


def _append_actor_memory(
    save: SaveFile,
    actor: dict[str, object],
    *,
    display_text: str,
    action_line: str,
    priority_reason: str,
) -> None:
    role = actor.get("role")
    if not isinstance(role, NpcRoleCard):
        return
    role.last_public_turn_at = _utc_now()
    role.cognition_changes.append(f"{role.last_public_turn_at} 公开记忆: {display_text[:64]}")
    role.cognition_changes = role.cognition_changes[-50:]
    context_kind = "public_targeted" if priority_reason == "player_targeted_visible_npc" else ("encounter" if _active_encounter_for_current_sub_zone(save) is not None else "public_reaction")
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
        content=action_line,
        clock=save.area_snapshot.clock,
        context_kind=context_kind,  # type: ignore[arg-type]
    )


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
    addressed_role_name = str(intent.get("addressed_role_name") or "").strip()
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
    reputation_entry = get_current_sub_zone_reputation(save, create=True)
    reputation_score = reputation_entry.score if reputation_entry is not None else 50
    candidates = _candidate_rows(
        save,
        player_text=display_text,
        addressed_role_name=addressed_role_name,
    )
    if not candidates:
        return []

    scene_events: list[SceneEvent] = []
    round_records: list[dict[str, object]] = []
    reputation_delta_total = 0

    for actor in candidates:
        priority_reason = str(actor.get("priority_reason") or "")
        payload = _ai_actor_action(
            actor,
            player_text=display_text,
            gm_summary=gm_summary,
            priority_reason=priority_reason,
            scene_context=scene_context,
            config=config,
        ) or _fallback_actor_action(
            save,
            actor,
            player_text=display_text,
            gm_summary=gm_summary,
            priority_reason=priority_reason,
        )
        action_line = _compose_actor_action_line(actor, payload)
        if not action_line:
            continue
        scene_events.append(
            _new_scene_event(
                "public_actor_action",
                action_line,
                actor_role_id=str(actor.get("actor_id") or ""),
                actor_name=str(actor.get("name") or ""),
                metadata={
                    "actor_type": str(actor.get("actor_type") or "npc"),
                    "needs_check": bool(payload.get("needs_check")),
                },
            )
        )
        _append_actor_memory(
            save,
            actor,
            display_text=display_text,
            action_line=action_line,
            priority_reason=priority_reason,
        )
        action_result = None
        if bool(payload.get("needs_check")):
            action_result = _actor_check(
                save,
                str(actor.get("actor_id") or ""),
                action_type=str(payload.get("action_type") or "check"),
                action_prompt=str(payload.get("action_prompt") or action_line),
                config=config,
            )
        situation_delta = _clamp(int(payload.get("situation_delta_hint") or 0) + _check_bonus(action_result), -20, 20)
        relation_delta = _resolution_relation_delta(str(actor.get("actor_type") or "npc"), action_result, situation_delta)
        reputation_delta = _resolution_reputation_delta(str(actor.get("actor_type") or "npc"), situation_delta)
        role = actor.get("role")
        if isinstance(role, NpcRoleCard) and relation_delta != 0:
            applied = _apply_actor_relation_delta(
                save,
                role,
                str(actor.get("actor_type") or "npc"),
                relation_delta,
                reputation_score,
            )
        else:
            applied = 0
        reputation_delta_total += reputation_delta
        round_records.append(
            {
                "actor_id": str(actor.get("actor_id") or ""),
                "name": str(actor.get("name") or ""),
                "actor_type": str(actor.get("actor_type") or "npc"),
                "target_label": str(payload.get("target_label") or ""),
                "stakes": str(payload.get("stakes") or ""),
                "specific_threat": str(payload.get("specific_threat") or ""),
                "action_line": action_line,
                "action_result": (action_result.model_dump() if action_result is not None else None),
                "situation_delta": situation_delta,
                "reputation_delta": reputation_delta,
                "relation_delta": applied,
            }
        )

    if not round_records:
        return []

    total_situation_delta = sum(int(item.get("situation_delta") or 0) for item in round_records)
    predicted_situation_value = _predict_situation_value(save, total_situation_delta)
    resolution_text = _ai_round_resolution(
        round_records,
        player_text=display_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        predicted_situation_value=predicted_situation_value,
        config=config,
    ) or _fallback_round_resolution(
        round_records,
        predicted_situation_value=predicted_situation_value,
    )

    if active_encounter is not None:
        try:
            from app.services.encounter_service import apply_active_encounter_situation_delta_in_save

            scene_events.extend(
                apply_active_encounter_situation_delta_in_save(
                    save,
                    session_id=session_id,
                    delta=total_situation_delta,
                    summary=resolution_text,
                    actor_name="公开轮次",
                )
            )
        except Exception:
            pass

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

    scene_events.append(
        _new_scene_event(
            "public_round_resolution",
            resolution_text,
            actor_name="GM",
            metadata={
                "actor_type": "system",
                "candidate_count": len(round_records),
                "reputation_score": reputation_score,
                "predicted_situation_value": predicted_situation_value,
            },
        )
    )
    save.game_logs.append(
        _new_game_log(
            session_id,
            "public_scene_director",
            f"公开场景推进了 {len(round_records)} 个行动声明，并统一完成轮次结算",
            {
                "candidate_count": len(round_records),
                "reputation_score": reputation_score,
            },
        )
    )

    if active_encounter is None and any(item.kind == "public_actor_action" for item in scene_events):
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

    return scene_events[:10]


def build_public_scene_state(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str = "",
) -> PublicSceneState:
    from app.services.public_scene_runtime_v2 import build_public_scene_state as runtime_v2

    return runtime_v2(save, session_id=session_id, player_text=player_text)


def advance_public_scene_in_save(
    save: SaveFile,
    session_id: str,
    player_text: str,
    gm_summary: str = "",
    scene_context: dict[str, object] | None = None,
    config: ChatConfig | None = None,
) -> list[SceneEvent]:
    from app.services.public_scene_runtime_v2 import advance_public_scene_in_save as runtime_v2

    return runtime_v2(
        save,
        session_id=session_id,
        player_text=player_text,
        gm_summary=gm_summary,
        scene_context=scene_context,
        config=config,
    )
