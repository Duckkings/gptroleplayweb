from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import ChatConfig, EncounterActRequest, EncounterDebugOverviewResponse, EncounterEntry, EncounterResolution
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.ai_protocol_contract_service import (
    AI_PROTOCOL_REPAIR_FAILED,
    AI_PROVIDER_CALL_FAILED,
    EnumContractField,
    allow_protocol_repair,
    has_ai_config,
    render_enum_pool_text,
    require_ai_config,
    validate_or_repair_json_payload,
)
from app.services.world_service import _new_scene_event, _parse_player_intent, ensure_encounter_location_target_in_save


def _legacy():
    from app.services import encounter_service as legacy

    return legacy


@dataclass(frozen=True)
class SituationAssessment:
    before_value: int
    delta: int
    after_value: int
    direction: str
    trend: str
    allowed_lexicon: tuple[str, ...]
    forbidden_lexicon: tuple[str, ...]


def assess_situation_change(before_value: int, delta: int, after_value: int) -> SituationAssessment:
    before = max(0, min(100, int(before_value)))
    applied = int(delta)
    after = max(0, min(100, int(after_value)))
    if applied > 0:
        return SituationAssessment(
            before_value=before,
            delta=applied,
            after_value=after,
            direction="stabilize",
            trend="improving",
            allowed_lexicon=("稳住", "压住", "争取到空间", "局势更稳", "险情被控制"),
            forbidden_lexicon=("恶化", "更糟", "失控扩大", "逼近失控", "压力扩大", "险情扩散"),
        )
    if applied < 0:
        return SituationAssessment(
            before_value=before,
            delta=applied,
            after_value=after,
            direction="worsen",
            trend="worsening",
            allowed_lexicon=("恶化", "逼近失控", "压力扩大", "险情扩散"),
            forbidden_lexicon=("稳住", "压住", "局势更稳", "险情被控制", "争取到空间"),
        )
    return SituationAssessment(
        before_value=before,
        delta=0,
        after_value=after,
        direction="hold",
        trend="stable",
        allowed_lexicon=("暂时维持", "僵持", "未继续恶化", "未取得突破"),
        forbidden_lexicon=("恶化", "更糟", "失控扩大", "稳住", "压住", "局势更稳"),
    )


def _text_conflicts_with_assessment(text: str, assessment: SituationAssessment) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return True
    return any(token in clean for token in assessment.forbidden_lexicon)


def _enforce_assessment_text(text: str, assessment: SituationAssessment, *, fallback_reason: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if clean and not _text_conflicts_with_assessment(clean, assessment):
        return clean[:240]
    basis = fallback_reason.strip() or "现场局势发生了新的变化。"
    if assessment.direction == "stabilize":
        return f"{basis} 这一步替现场争取到了更稳的空间，最危险的部分暂时被压住。"
    if assessment.direction == "worsen":
        return f"{basis} 这一步没能压住最直接的风险，现场压力继续扩大，局面朝更糟的方向滑去。"
    return f"{basis} 现场暂时维持僵持，没有继续恶化，但也还没出现真正的突破口。"


def _actor_label(save, encounter: EncounterEntry, actor_role_id: str = "", actor_name: str = "") -> str:
    if actor_name:
        return actor_name
    if actor_role_id:
        role = next((item for item in save.role_pool if item.role_id == actor_role_id), None)
        if role is not None and role.name:
            return role.name
        temp = next((item for item in (encounter.temporary_npcs or []) if item.encounter_npc_id == actor_role_id), None)
        if temp is not None and temp.name:
            return temp.name
    if encounter.npc_role_id:
        role = next((item for item in save.role_pool if item.role_id == encounter.npc_role_id), None)
        if role is not None and role.name:
            return role.name
    first_temp = next((item for item in (encounter.temporary_npcs or []) if item.name), None)
    if first_temp is not None:
        return first_temp.name
    return "现场"


def _specific_defaults(save, encounter: EncounterEntry, player_prompt: str, actor_role_id: str = "", actor_name: str = "") -> tuple[str, str, str, str]:
    clean_prompt = " ".join((player_prompt or "").split()).strip() or "本轮行动"
    title = encounter.title or "当前遭遇"
    scene_summary = " ".join((encounter.scene_summary or encounter.description or title).split()).strip()
    actor_label = _actor_label(save, encounter, actor_role_id=actor_role_id, actor_name=actor_name)
    specific_change = f"围绕《{title}》的局势继续推进，{actor_label}的注意力被拉向了{scene_summary[:64]}。"
    specific_threat = f"{scene_summary[:96]}，这也是眼前最直接、最需要立刻处理的风险。"
    opened_opportunity = f"你下一轮可以直接围绕{actor_label}刚刚压住或暴露出的那一处继续推进。"
    return scene_summary[:240], specific_change[:180], specific_threat[:180], opened_opportunity[:180]


def concretize_encounter_reply(
    save,
    encounter: EncounterEntry,
    player_prompt: str,
    *,
    reply: str,
    scene_summary: str,
    specific_change: str = "",
    specific_threat: str = "",
    opened_opportunity: str = "",
    actor_role_id: str = "",
    actor_name: str = "",
    assessment: SituationAssessment | None = None,
) -> tuple[str, str]:
    legacy = _legacy()
    fallback_scene, fallback_change, fallback_threat, fallback_opportunity = _specific_defaults(
        save,
        encounter,
        player_prompt,
        actor_role_id=actor_role_id,
        actor_name=actor_name,
    )
    change_text = legacy._force_chinese_text(specific_change, fallback_change, limit=180)
    threat_text = legacy._force_chinese_text(specific_threat, fallback_threat, limit=180)
    opportunity_text = legacy._force_chinese_text(opened_opportunity, fallback_opportunity, limit=180)
    summary_text = " ".join(str(scene_summary or "").split()).strip()[:240]
    if not summary_text:
        summary_text = legacy._force_chinese_text(scene_summary, fallback_scene, limit=240)
    if legacy._text_is_too_vague(summary_text):
        summary_text = f"{change_text} 当前最直接的风险是：{threat_text}。"
    reply_text = " ".join(str(reply or "").split()).strip()[:240]
    if legacy._text_is_too_vague(reply_text):
        reply_text = f"{change_text} 当前最直接的风险是：{threat_text}。这给你留下的明确机会是：{opportunity_text}。"
    if assessment is not None:
        reply_text = _enforce_assessment_text(reply_text, assessment, fallback_reason=change_text)
        summary_text = _enforce_assessment_text(summary_text, assessment, fallback_reason=change_text)
    return reply_text[:240], summary_text[:240]


def resolve_fallback_reply(save, encounter: EncounterEntry, player_prompt: str, *, assessment: SituationAssessment | None = None) -> tuple[str, int]:
    minutes = max(1, min(15, ceil(len((player_prompt or "").strip()) / 30)))
    reply, _ = concretize_encounter_reply(
        save,
        encounter,
        player_prompt,
        reply="",
        scene_summary=encounter.scene_summary or encounter.description or encounter.title,
        assessment=assessment,
    )
    return reply, minutes


def ai_resolve_encounter(encounter: EncounterEntry, req: EncounterActRequest, *, assessment: SituationAssessment | None = None) -> dict[str, object]:
    legacy = _legacy()
    config = require_ai_config(req.config)
    save = legacy.get_current_save(default_session_id=req.session_id)
    fallback_reply, fallback_minutes = resolve_fallback_reply(save, encounter, req.player_prompt, assessment=assessment)
    team_members, visible_npcs = legacy._visible_participant_text(save, encounter)
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_STEP_USER,
        "",
        title=encounter.title,
        description=encounter.description,
        encounter_mode=encounter.encounter_mode,
        player_presence=encounter.player_presence,
        direction=(assessment.direction if assessment is not None else "hold"),
        scene_summary=encounter.scene_summary or encounter.description,
        termination_conditions=legacy._termination_conditions_text(encounter),
        recent_steps=legacy._recent_steps_text(encounter),
        player_prompt=req.player_prompt,
        team_members=team_members,
        visible_npcs=visible_npcs,
        participant_role_ids=", ".join(encounter.participant_role_ids) if encounter.participant_role_ids else "none",
    )
    prompt = (
        f"{prompt}\nAllowed enum ids:\n"
        f"{render_enum_pool_text((EnumContractField(field_path='step_kind', allowed_ids=('gm_update', 'resolution')),))}\n"
        "Use only the allowed stable ids for step_kind."
    )
    try:
        system_prompt = prompt_table.get_text("encounter.resolve.system", "浣犲彧杈撳嚭 JSON銆傛墍鏈夋枃鏈瓧娈典娇鐢ㄧ畝浣撲腑鏂囥€?")
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.resolve.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = (resp.choices[0].message.content or "").strip() or "{}"
        parsed = legacy._extract_json_content(raw_json)
        with allow_protocol_repair():
            parsed = validate_or_repair_json_payload(
                parsed=parsed,
                raw_json=raw_json,
                fields=(EnumContractField(field_path="step_kind", allowed_ids=("gm_update", "resolution")),),
                config=config,
                system_prompt=system_prompt,
                original_prompt=prompt,
            )
        minutes = max(1, min(30, int(parsed.get("time_spent_min") or fallback_minutes or 1)))
        step_kind = str(parsed.get("step_kind") or "").strip().lower()
        reply, next_scene_summary = concretize_encounter_reply(
            save,
            encounter,
            req.player_prompt,
            reply=str(parsed.get("reply") or fallback_reply),
            scene_summary=str(parsed.get("scene_summary") or encounter.scene_summary or encounter.description),
            specific_change=str(parsed.get("specific_change") or ""),
            specific_threat=str(parsed.get("specific_threat") or ""),
            opened_opportunity=str(parsed.get("opened_opportunity") or ""),
            assessment=assessment,
        )
        reply = legacy._force_chinese_text(reply, fallback_reply, limit=240)
        next_scene_summary = legacy._force_chinese_text(
            next_scene_summary,
            encounter.scene_summary or encounter.description or fallback_reply,
            limit=240,
        )
        if not reply:
            raise ValueError(AI_PROTOCOL_REPAIR_FAILED)
        termination_updates = parsed.get("termination_updates")
        if not isinstance(termination_updates, list):
            termination_updates = []
        
        # 处理NPC生成请求
        spawn_requests = parsed.get("spawn_requests")
        if isinstance(spawn_requests, list):
            for spawn_req in spawn_requests:
                if not isinstance(spawn_req, dict):
                    continue
                name = str(spawn_req.get("name") or "").strip()
                if not name:
                    continue
                # 创建临时NPC
                from datetime import datetime, timezone
                from app.models.schemas import EncounterTemporaryNpc
                temp_npc = EncounterTemporaryNpc(
                    encounter_npc_id=f"encnpc_mid_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
                    name=name,
                    title=str(spawn_req.get("title") or "").strip(),
                    description=str(spawn_req.get("description") or f"{name}卷入了当前的遭遇。").strip(),
                    speaking_style=str(spawn_req.get("speaking_style") or "").strip(),
                    agenda=str(spawn_req.get("agenda") or f"{name}正试图处理眼前的情况。").strip(),
                    state="active",
                    zone_id=encounter.zone_id,
                    sub_zone_id=encounter.sub_zone_id,
                    introduced_at=datetime.now(timezone.utc).isoformat(),
                )
                encounter.temporary_npcs.append(temp_npc)
                if temp_npc.encounter_npc_id not in encounter.participant_role_ids:
                    encounter.participant_role_ids.append(temp_npc.encounter_npc_id)
                legacy._refresh_participants(save, encounter)
                legacy._append_step(
                    encounter,
                    kind="npc_entrance",
                    actor_type="temporary_npc",
                    actor_id=temp_npc.encounter_npc_id,
                    actor_name=name,
                    content=f"新角色入场：{name}" + (f"（{temp_npc.title}）" if temp_npc.title else "") + "。",
                    metadata={"npc_name": name, "role_type": str(spawn_req.get("role_type") or "neutral")},
                )
        
        return {
            "reply": reply,
            "time_spent_min": minutes,
            "scene_summary": next_scene_summary,
            "specific_change": legacy._force_chinese_text(parsed.get("specific_change"), "", limit=180),
            "specific_threat": legacy._force_chinese_text(parsed.get("specific_threat"), "", limit=180),
            "opened_opportunity": legacy._force_chinese_text(parsed.get("opened_opportunity"), "", limit=180),
            "situation_delta_hint": legacy._clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
            "step_kind": step_kind,
            "termination_updates": termination_updates,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc


def fallback_step_updates(encounter: EncounterEntry, player_prompt: str) -> tuple[str, list[dict[str, object]], str]:
    clean = (player_prompt or "").strip()
    updates: list[dict[str, object]] = []
    step_kind = "gm_update"
    scene_summary = encounter.scene_summary or encounter.description
    if any(token in clean for token in ["搞清", "确认", "解决", "谈妥", "处理完", "拿到"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "target_resolved":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if encounter.type == "npc" and any(token in clean for token in ["散了", "离开", "不聊", "闭嘴"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "npc_leaves":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if updates:
        step_kind = "resolution"
    return scene_summary, updates, step_kind


def _situation_event_text(assessment: SituationAssessment, summary: str) -> str:
    if assessment.direction == "stabilize":
        prefix = f"局势值变为 {assessment.after_value}/100，现场更稳，最危险的部分被暂时压住。"
    elif assessment.direction == "worsen":
        prefix = f"局势值变为 {assessment.after_value}/100，局面正在恶化，压力继续扩大。"
    else:
        prefix = f"局势值变为 {assessment.after_value}/100，现场暂时维持僵持，没有继续恶化，但也未取得突破。"
    return f"{prefix} {summary}".strip()[:320]


def _update_encounter_state_with_delta(encounter: EncounterEntry, delta: int) -> SituationAssessment:
    legacy = _legacy()
    before = encounter.situation_value
    after = legacy._clamp(before + int(delta), 0, 100)
    assessment = assess_situation_change(before, delta, after)
    encounter.situation_value = after
    encounter.situation_trend = assessment.trend  # type: ignore[assignment]
    return assessment


def apply_active_encounter_situation_delta_in_save(
    save,
    *,
    session_id: str,
    delta: int,
    summary: str,
    actor_role_id: str = "",
    actor_name: str = "",
) -> list:
    legacy = _legacy()
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None or encounter.status not in {"active", "escaped"}:
        return []
    if encounter.presented_at is None:
        legacy._initialize_encounter_state(save, encounter)
    applied = legacy._clamp(delta, -20, 20)
    if applied == 0:
        return []

    if encounter.status == "active":
        team_member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_role_id), None)
        temp_npc = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.encounter_npc_id == actor_role_id), None)
        if team_member is not None:
            step_kind = "team_reaction"
            actor_type = "team"
        elif temp_npc is not None:
            step_kind = "temp_npc_action"
            actor_type = "encounter_temp_npc"
            actor_name = actor_name or temp_npc.name
        elif actor_role_id:
            step_kind = "npc_reaction"
            actor_type = "npc"
        else:
            step_kind = "gm_update"
            actor_type = "system"

        assessment = _update_encounter_state_with_delta(encounter, applied)
        concrete_summary = " ".join(str(summary or "").split()).strip()[:240] or encounter.scene_summary or encounter.description
        encounter.scene_summary = concrete_summary
        encounter.last_advanced_at = legacy._utc_now()
        legacy._append_step(
            encounter,
            kind=step_kind,
            actor_type=actor_type,
            actor_id=actor_role_id,
            actor_name=actor_name,
            content=concrete_summary,
        )
        outcome_package, _ = legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
        legacy._append_game_log(
            save,
            session_id,
            "encounter_situation_update",
            concrete_summary,
            {
                "encounter_id": encounter.encounter_id,
                "situation_value": encounter.situation_value,
                "situation_delta": applied,
            },
        )
        events = [
            _new_scene_event(
                "encounter_situation_update",
                concrete_summary,
                actor_role_id=actor_role_id,
                actor_name=actor_name,
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "situation_value": encounter.situation_value,
                    "situation_delta": applied,
                    "direction": assessment.direction,
                    "trend": assessment.trend,
                    "summary_basis": "ai_summary",
                    "actor_type": actor_type,
                },
            )
        ]
        if outcome_package is not None:
            events.append(
                _new_scene_event(
                    "encounter_resolution",
                    outcome_package.narrative_summary or encounter.scene_summary or encounter.description,
                    metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
                )
            )
        return events

    team_member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_role_id), None)
    temp_npc = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.encounter_npc_id == actor_role_id), None)
    if team_member is not None:
        step_kind = "team_reaction"
        actor_type = "team"
    elif temp_npc is not None:
        step_kind = "temp_npc_action"
        actor_type = "encounter_temp_npc"
        actor_name = actor_name or temp_npc.name
    elif actor_role_id:
        step_kind = "npc_reaction"
        actor_type = "npc"
    else:
        step_kind = "background_tick"
        actor_type = "system"

    assessment = _update_encounter_state_with_delta(encounter, applied)
    concrete_summary, next_scene_summary = concretize_encounter_reply(
        save,
        encounter,
        summary or "局势推进",
        reply=summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description,
        scene_summary=encounter.scene_summary or encounter.description,
        actor_role_id=actor_role_id,
        actor_name=actor_name,
        assessment=assessment,
    )
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = concrete_summary
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(
        encounter,
        kind=step_kind,
        actor_type=actor_type,
        actor_id=actor_role_id,
        actor_name=actor_name,
        content=concrete_summary,
    )
    outcome_package, _ = legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    legacy._append_game_log(
        save,
        session_id,
        "encounter_situation_update",
        concrete_summary,
        {
            "encounter_id": encounter.encounter_id,
            "situation_value": encounter.situation_value,
            "situation_delta": applied,
        },
    )
    events = [
        _new_scene_event(
            "encounter_situation_update",
            _situation_event_text(assessment, concrete_summary),
            actor_role_id=actor_role_id,
            actor_name=actor_name,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": applied,
                "direction": assessment.direction,
                "trend": assessment.trend,
                "summary_basis": "numeric",
                "actor_type": actor_type,
            },
        )
    ]
    if outcome_package is not None:
        events.append(
            _new_scene_event(
                "encounter_resolution",
                outcome_package.narrative_summary or concrete_summary,
                metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
            )
        )
    return events


def _normalize_background_world_pushes(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = _legacy()
    raw = parsed.get("world_pushes")
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if len(normalized) >= 2:
            break
        if not isinstance(item, dict):
            continue
        push_kind = str(item.get("push_kind") or "").strip()
        if push_kind not in {"new_clue", "environment_shift", "hazard_escalation", "pressure_release", "faction_move", "npc_arrival"}:
            continue
        location_target = item.get("location_target") if isinstance(item.get("location_target"), dict) else None
        normalized.append(
            {
                "push_kind": push_kind,
                "title": str(item.get("title") or "").strip()[:80],
                "detail": str(item.get("detail") or "").strip()[:240],
                "opened_window": str(item.get("opened_window") or "").strip()[:180],
                "pressure_note": str(item.get("pressure_note") or "").strip()[:180],
                "situation_delta_hint": legacy._clamp(int(item.get("situation_delta_hint") or 0), -8, 8),
                "spawn_npc": legacy._sanitize_new_npc_seed(item.get("spawn_npc")),
                "location_target": location_target,
            }
        )
    return normalized


def _normalize_background_actor_updates(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    raw = parsed.get("actor_updates")
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if len(normalized) >= 4:
            break
        if not isinstance(item, dict):
            continue
        actor_type = str(item.get("actor_type") or "npc").strip()
        if actor_type not in {"npc", "team", "encounter_temp_npc"}:
            actor_type = "npc"
        normalized.append(
            {
                "actor_id": str(item.get("actor_id") or "").strip(),
                "actor_type": actor_type,
                "actor_name": str(item.get("actor_name") or "").strip()[:48],
                "action_summary": str(item.get("action_summary") or "").strip()[:240],
                "impact_summary": str(item.get("impact_summary") or "").strip()[:180],
                "move_to_zone_name": str(item.get("move_to_zone_name") or "").strip()[:48],
                "move_to_sub_zone_name": str(item.get("move_to_sub_zone_name") or "").strip()[:48],
                "move_to_zone_id": str(item.get("move_to_zone_id") or "").strip()[:64],
                "move_to_sub_zone_id": str(item.get("move_to_sub_zone_id") or "").strip()[:64],
            }
        )
    return normalized


def _background_location_directive(save, encounter: EncounterEntry, update: dict[str, Any]) -> dict[str, object] | None:
    zone_name = str(update.get("move_to_zone_name") or "").strip()
    sub_zone_name = str(update.get("move_to_sub_zone_name") or "").strip()
    zone_id = str(update.get("move_to_zone_id") or "").strip()
    sub_zone_id = str(update.get("move_to_sub_zone_id") or "").strip()
    if not any([zone_name, sub_zone_name, zone_id, sub_zone_id]):
        return None
    if not zone_name and zone_id:
        zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), "")
    if not sub_zone_name and sub_zone_id:
        sub_zone_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), "")
    if not sub_zone_name:
        return None
    zone_type_hint = "unknown"
    if zone_id:
        zone = next((item for item in save.map_snapshot.zones if item.zone_id == zone_id), None)
        if zone is not None:
            zone_type_hint = zone.zone_type
    return {
        "zone_name": zone_name,
        "zone_description": "",
        "zone_type_hint": zone_type_hint,
        "sub_zone_name": sub_zone_name,
        "sub_zone_description": "",
        "reason": str(update.get("impact_summary") or update.get("action_summary") or encounter.title),
        "move_encounter_focus": False,
        "move_actor_ids": [],
    }


def _apply_background_actor_updates(
    save,
    encounter: EncounterEntry,
    actor_updates: list[dict[str, Any]],
    *,
    session_id: str,
    config: ChatConfig | None = None,
) -> None:
    legacy = _legacy()
    for update in actor_updates:
        actor_id = str(update.get("actor_id") or "").strip()
        actor_type = str(update.get("actor_type") or "npc").strip()
        actor_name = str(update.get("actor_name") or "").strip()
        action_summary = str(update.get("action_summary") or "").strip()
        impact_summary = str(update.get("impact_summary") or "").strip()
        location_payload = None
        directive = _background_location_directive(save, encounter, update)
        if directive is not None:
            location_payload = ensure_encounter_location_target_in_save(
                save,
                encounter,
                directive,
                session_id=session_id,
                config=config,
            )
        if actor_type == "encounter_temp_npc":
            temp_npc = next(
                (
                    item
                    for item in encounter.temporary_npcs
                    if (actor_id and item.encounter_npc_id == actor_id) or (actor_name and item.name == actor_name)
                ),
                None,
            )
            if temp_npc is not None and location_payload is not None:
                temp_npc.zone_id = str(location_payload.get("zone_id") or temp_npc.zone_id)
                temp_npc.sub_zone_id = str(location_payload.get("sub_zone_id") or temp_npc.sub_zone_id)
                actor_name = actor_name or temp_npc.name
        else:
            role = next(
                (
                    item
                    for item in save.role_pool
                    if (actor_id and item.role_id == actor_id) or (actor_name and item.name == actor_name)
                ),
                None,
            )
            if role is not None:
                actor_id = actor_id or role.role_id
                actor_name = actor_name or role.name
                if location_payload is not None:
                    role.zone_id = str(location_payload.get("zone_id") or role.zone_id)
                    role.sub_zone_id = str(location_payload.get("sub_zone_id") or role.sub_zone_id)
        if not any([actor_name, action_summary, impact_summary]):
            continue
        step_kind = {
            "npc": "npc_reaction",
            "team": "team_reaction",
            "encounter_temp_npc": "temp_npc_action",
        }.get(actor_type, "npc_reaction")
        content = action_summary or impact_summary
        legacy._append_step(
            encounter,
            kind=step_kind,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            content=content,
            metadata={
                "impact_summary": impact_summary,
                "moved_to_zone_id": (str(location_payload.get("zone_id")) if location_payload is not None else ""),
                "moved_to_sub_zone_id": (str(location_payload.get("sub_zone_id")) if location_payload is not None else ""),
                "moved_to_label": (str(location_payload.get("target_location_label")) if location_payload is not None else ""),
                "affects_encounter": bool(impact_summary),
                "source_kind": "background_actor_update",
            },
        )


def _apply_background_world_pushes(
    save,
    encounter: EncounterEntry,
    world_pushes: list[dict[str, Any]],
    *,
    session_id: str,
    config: ChatConfig | None = None,
) -> None:
    legacy = _legacy()
    for push in world_pushes:
        location_payload = None
        raw_location_target = push.get("location_target")
        if isinstance(raw_location_target, dict):
            location_payload = ensure_encounter_location_target_in_save(
                save,
                encounter,
                raw_location_target,
                session_id=session_id,
                config=config,
            )
        spawned_name = ""
        spawn_seed = push.get("spawn_npc")
        if isinstance(spawn_seed, dict):
            spawned_role_id = legacy._spawn_persistent_encounter_npc(save, encounter, spawn_seed)
            spawned_role = next((item for item in save.role_pool if item.role_id == spawned_role_id), None)
            spawned_name = spawned_role.name if spawned_role is not None else ""
        parts = [str(push.get("title") or "").strip(), str(push.get("detail") or "").strip()]
        if location_payload is not None:
            parts.append(f"关键地点：{str(location_payload.get('target_location_label') or '').strip()}")
        if spawned_name:
            parts.append(f"新角色入场：{spawned_name}")
        content = " ".join(part for part in parts if part).strip()[:320]
        if not content:
            continue
        legacy._append_step(
            encounter,
            kind="world_push",
            actor_type="system",
            actor_name="世界",
            content=content,
            metadata={
                "impact_summary": str(push.get("pressure_note") or push.get("opened_window") or "").strip(),
                "moved_to_zone_id": (str(location_payload.get("zone_id")) if location_payload is not None else ""),
                "moved_to_sub_zone_id": (str(location_payload.get("sub_zone_id")) if location_payload is not None else ""),
                "moved_to_label": (str(location_payload.get("target_location_label")) if location_payload is not None else ""),
                "affects_encounter": True,
                "source_kind": str(push.get("push_kind") or ""),
                "generated_location": bool(location_payload and (location_payload.get("generated_zone") or location_payload.get("generated_sub_zone"))),
            },
        )


def advance_active_encounter_in_save(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    legacy = _legacy()
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None:
        return None
    if minutes_elapsed <= 0:
        return None
    # Retired: encounters no longer advance in the background while the player is elsewhere.
    return None

    background_delta = -legacy._clamp(max(1, minutes_elapsed // 10), 1, 6)
    assessment = assess_situation_change(encounter.situation_value, background_delta, legacy._clamp(encounter.situation_value + background_delta, 0, 100))
    team_members, visible_npcs = legacy._visible_participant_text(save, encounter)
    raw_reply = f"你离开现场后，《{encounter.title}》仍在后台推进。"
    raw_scene_summary = encounter.scene_summary or encounter.description
    world_pushes: list[dict[str, Any]] = []
    actor_updates: list[dict[str, Any]] = []
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        prompt = prompt_table.render(
                    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
                    "",
                    title=encounter.title,
                    description=encounter.description,
                    direction=assessment.direction,
                    scene_summary=encounter.scene_summary or encounter.description,
                    termination_conditions=legacy._termination_conditions_text(encounter),
                    recent_steps=legacy._recent_steps_text(encounter),
                    minutes_elapsed=minutes_elapsed,
                    team_members=team_members,
                    visible_npcs=visible_npcs,
                )
        resp = client.chat.completions.create(
            model=config.model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                        {"role": "user", "content": prompt},
                    ],
                )
        parsed = legacy._extract_json_content((resp.choices[0].message.content or "").strip())
        raw_reply = str(parsed.get("reply") or raw_reply)
        raw_scene_summary = str(parsed.get("scene_summary") or raw_scene_summary)
        world_pushes = _normalize_background_world_pushes(parsed)
        actor_updates = _normalize_background_actor_updates(parsed)
        legacy._apply_termination_updates(encounter, parsed.get("termination_updates"))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc

    reply, next_scene_summary = concretize_encounter_reply(
        save,
        encounter,
        f"后台推进 {minutes_elapsed} 分钟",
        reply=raw_reply,
        scene_summary=raw_scene_summary,
        assessment=assessment,
    )
    _apply_background_actor_updates(save, encounter, actor_updates, session_id=session_id, config=config)
    _apply_background_world_pushes(save, encounter, world_pushes, session_id=session_id, config=config)
    _update_encounter_state_with_delta(encounter, background_delta)
    encounter.scene_summary = next_scene_summary
    encounter.background_tick_count += 1
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(
        encounter,
        kind="background_tick",
        content=reply,
        metadata={
            "impact_summary": raw_scene_summary[:180],
            "affects_encounter": True,
            "source_kind": "background_tick",
        },
    )
    legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    legacy._append_game_log(
        save,
        session_id,
        "encounter_background_tick",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "minutes_elapsed": minutes_elapsed,
            "situation_value": encounter.situation_value,
            "situation_delta": background_delta,
        },
    )
    legacy._touch_state(state)
    return encounter


def advance_active_encounter_from_main_chat_in_save(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    config: ChatConfig | None = None,
) -> list:
    legacy = _legacy()
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return []
    if encounter.zone_id and save.area_snapshot.current_zone_id and encounter.zone_id != save.area_snapshot.current_zone_id:
        return []
    if encounter.sub_zone_id and save.area_snapshot.current_sub_zone_id and encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        return []
    if encounter.presented_at is None:
        legacy._initialize_encounter_state(save, encounter)

    def summarize_public_turn_scene() -> str:
        fallback = " ".join((gm_narration or encounter.scene_summary or encounter.description).split()).strip()[:240]
        if not config or not has_ai_config(config):
            return fallback
        try:
            configured = require_ai_config(config)
            team_members, visible_npcs = legacy._visible_participant_text(save, encounter)
            prompt = prompt_table.render(
                PromptKeys.ENCOUNTER_PUBLIC_TURN_SUMMARY_USER,
                "",
                title=encounter.title,
                description=encounter.description,
                goal=encounter.goal or "",
                scene_summary=encounter.scene_summary or encounter.description,
                gm_narration=gm_narration[:800],
                player_text=player_text[:400],
                direction="hold",
                visible_npcs=visible_npcs,
                team_members=team_members,
                termination_conditions=legacy._termination_conditions_text(encounter),
            )
            client = create_sync_client(configured, client_cls=OpenAI)
            resp = client.chat.completions.create(
                model=configured.model,
                **build_completion_options(configured),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_table.get_text("encounter.public_turn.summary.system", "你只输出 JSON。")},
                    {"role": "user", "content": prompt},
                ],
            )
            parsed = legacy._extract_json_content((resp.choices[0].message.content or "").strip())
            summary = " ".join(str(parsed.get("scene_summary") or "").split()).strip()[:240]
            return summary or fallback
        except Exception:
            return fallback

    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = legacy._default_world_clock()
    save.area_snapshot.clock = legacy._advance_clock(save.area_snapshot.clock, max(1, time_spent_min))
    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    display_text = str(parsed_intent.get("display_text") or player_text).strip()
    if passive_turn:
        display_text = "【玩家旁观】玩家本轮选择观察与等待，不主动介入。"
    legacy._append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=display_text or gm_narration or "玩家继续应对当前遭遇。",
    )
    situation_delta = legacy._clamp(legacy._check_bonus_from_player_prompt(player_text), -20, 20)
    assessment = assess_situation_change(encounter.situation_value, situation_delta, legacy._clamp(encounter.situation_value + situation_delta, 0, 100))
    summary_text = summarize_public_turn_scene()
    encounter.scene_summary = summary_text
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(encounter, kind="gm_update", content=summary_text)
    _update_encounter_state_with_delta(encounter, situation_delta)
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    if outcome_package is not None:
        event_kind = "encounter_resolution"
    else:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id
    state.history.append(
        EncounterResolution(
            encounter_id=encounter.encounter_id,
            player_prompt=display_text or player_text,
            reply=summary_text,
            time_spent_min=max(1, time_spent_min),
            quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
            situation_delta=situation_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    legacy._append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        summary_text,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    legacy._touch_state(state)
    return [
        _new_scene_event(
            "encounter_situation_update",
            summary_text,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": situation_delta,
                "direction": assessment.direction,
                "trend": assessment.trend,
                "summary_basis": "ai_summary",
            },
        ),
        _new_scene_event(
            event_kind,
            summary_text,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        ),
    ]

    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    display_text = str(parsed_intent.get("display_text") or player_text).strip()
    escape_tokens = ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]
    if passive_turn:
        display_text = "【玩家旁观】玩家本轮选择观察与等待，不主动行动。"
    if any(token in display_text for token in ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]):
        from app.models.schemas import EncounterEscapeRequest

        result = legacy.escape_encounter(
            encounter.encounter_id,
            EncounterEscapeRequest(session_id=session_id, config=config),
        )
        return [
            _new_scene_event(
                "encounter_progress",
                result.reply,
                metadata={
                    "encounter_id": result.encounter_id,
                    "encounter_title": encounter.title,
                    "status": result.status,
                    "requires_check": True,
                    "escape_success": result.escape_success,
                    "from_main_chat": True,
                },
            )
        ]

    legacy._append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=display_text or gm_narration or "玩家继续应对当前遭遇。",
    )
    resolved = legacy._ai_resolve_encounter(
        encounter,
        EncounterActRequest(
            session_id=session_id,
            encounter_id=encounter.encounter_id,
            player_prompt=f"{display_text}\nGM叙事：{gm_narration}".strip(),
            config=config,
        ),
    )
    reply = str(resolved.get("reply") or "").strip()
    next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
    termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
    step_kind = str(resolved.get("step_kind") or "gm_update")
    situation_delta_hint = legacy._clamp(int(resolved.get("situation_delta_hint") or 0), -8, 8)

    situation_delta = legacy._clamp(situation_delta_hint + legacy._check_bonus_from_player_prompt(player_text), -20, 20)
    assessment = assess_situation_change(encounter.situation_value, situation_delta, legacy._clamp(encounter.situation_value + situation_delta, 0, 100))
    reply, next_scene_summary = concretize_encounter_reply(
        save,
        encounter,
        display_text or gm_narration,
        reply=reply,
        scene_summary=next_scene_summary,
        assessment=assessment,
    )
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(encounter, kind=step_kind, content=reply)
    legacy._apply_termination_updates(encounter, termination_updates)
    _update_encounter_state_with_delta(encounter, situation_delta)
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
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
            situation_delta=situation_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    legacy._append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        reply,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    legacy._touch_state(state)
    return [
        _new_scene_event(
            "encounter_situation_update",
            _situation_event_text(assessment, reply),
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": situation_delta,
                "direction": assessment.direction,
                "trend": assessment.trend,
                "summary_basis": "numeric",
            },
        ),
        _new_scene_event(
            event_kind,
            reply,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        ),
    ]


def advance_active_encounter_in_save_v3(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    legacy = _legacy()
    config = require_ai_config(config)
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None or encounter.player_presence != "away" or encounter.status not in {"active", "escaped"}:
        return None
    if minutes_elapsed <= 0:
        return None
    if encounter.presented_at is None:
        legacy._initialize_encounter_state(save, encounter)

    background_delta = -legacy._clamp(max(1, minutes_elapsed // 10), 1, 6)
    projected_after = legacy._clamp(encounter.situation_value + background_delta, 0, 100)
    assessment = assess_situation_change(encounter.situation_value, background_delta, projected_after)
    team_members, visible_npcs = legacy._visible_participant_text(save, encounter)
    raw_reply = f"你离开现场后，《{encounter.title}》仍在后台继续推进。"
    raw_scene_summary = encounter.scene_summary or encounter.description
    world_pushes: list[dict[str, Any]] = []
    actor_updates: list[dict[str, Any]] = []
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = create_sync_client(config, client_cls=OpenAI)
                prompt = prompt_table.render(
                    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
                    "",
                    title=encounter.title,
                    description=encounter.description,
                    direction=assessment.direction,
                    scene_summary=encounter.scene_summary or encounter.description,
                    termination_conditions=legacy._termination_conditions_text(encounter),
                    recent_steps=legacy._recent_steps_text(encounter),
                    minutes_elapsed=minutes_elapsed,
                    team_members=team_members,
                    visible_npcs=visible_npcs,
                )
                resp = client.chat.completions.create(
                    model=model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = legacy._extract_json_content((resp.choices[0].message.content or "").strip())
                raw_reply = str(parsed.get("reply") or raw_reply)
                raw_scene_summary = str(parsed.get("scene_summary") or raw_scene_summary)
                world_pushes = _normalize_background_world_pushes(parsed)
                actor_updates = _normalize_background_actor_updates(parsed)
                legacy._apply_termination_updates(encounter, parsed.get("termination_updates"))
            except Exception:
                pass

    reply, next_scene_summary = concretize_encounter_reply(
        save,
        encounter,
        f"后台推进 {minutes_elapsed} 分钟",
        reply=raw_reply,
        scene_summary=raw_scene_summary,
        assessment=assessment,
    )
    _apply_background_actor_updates(save, encounter, actor_updates, session_id=session_id, config=config)
    _apply_background_world_pushes(save, encounter, world_pushes, session_id=session_id, config=config)
    _update_encounter_state_with_delta(encounter, background_delta)
    encounter.scene_summary = next_scene_summary
    encounter.background_tick_count += 1
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(
        encounter,
        kind="background_tick",
        content=reply,
        metadata={
            "impact_summary": raw_scene_summary[:180],
            "affects_encounter": True,
            "source_kind": "background_tick",
        },
    )
    legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    legacy._append_game_log(
        save,
        session_id,
        "encounter_background_tick",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "minutes_elapsed": minutes_elapsed,
            "situation_value": encounter.situation_value,
            "situation_delta": background_delta,
            "actor_update_count": len(actor_updates),
            "world_push_count": len(world_pushes),
        },
    )
    legacy._touch_state(state)
    return encounter


def advance_active_encounter_from_main_chat_in_save_v3(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    config: ChatConfig | None = None,
) -> list:
    legacy = _legacy()
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return []
    if encounter.zone_id and save.area_snapshot.current_zone_id and encounter.zone_id != save.area_snapshot.current_zone_id:
        return []
    if encounter.sub_zone_id and save.area_snapshot.current_sub_zone_id and encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        return []
    if encounter.presented_at is None:
        legacy._initialize_encounter_state(save, encounter)

    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    display_text = str(parsed_intent.get("display_text") or player_text).strip()
    if passive_turn:
        display_text = "【玩家旁观】玩家本轮选择观察与等待，不主动行动。"
    escape_tokens = ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]
    if any(token in display_text for token in escape_tokens):
        escape_result = legacy._escape_encounter_in_save(save, encounter, session_id=session_id, config=config)
        legacy._touch_state(state)
        return [
            _new_scene_event(
                "encounter_progress",
                escape_result.reply,
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "status": encounter.status,
                    "requires_check": True,
                    "escape_success": escape_result.escape_success,
                    "from_main_chat": True,
                },
            )
        ]

    legacy._append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=display_text or gm_narration or "玩家继续应对当前遭遇。",
    )
    resolved = legacy._ai_resolve_encounter(
        encounter,
        EncounterActRequest(
            session_id=session_id,
            encounter_id=encounter.encounter_id,
            player_prompt=f"{display_text}\nGM叙事：{gm_narration}".strip(),
            config=config,
        ),
    )
    if resolved is None:
        reply, _ = legacy._resolve_fallback_reply(encounter, display_text or gm_narration)
        next_scene_summary, termination_updates, step_kind = legacy._fallback_step_updates(encounter, display_text or gm_narration)
        situation_delta_hint = legacy._fallback_situation_delta(encounter, display_text or gm_narration)
    else:
        reply = str(resolved.get("reply") or "").strip()
        next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
        termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
        step_kind = str(resolved.get("step_kind") or "gm_update")
        situation_delta_hint = legacy._clamp(int(resolved.get("situation_delta_hint") or 0), -8, 8)

    situation_delta = legacy._clamp(situation_delta_hint + legacy._check_bonus_from_player_prompt(player_text), -20, 20)
    assessment = assess_situation_change(encounter.situation_value, situation_delta, legacy._clamp(encounter.situation_value + situation_delta, 0, 100))
    reply, next_scene_summary = concretize_encounter_reply(
        save,
        encounter,
        display_text or gm_narration,
        reply=reply,
        scene_summary=next_scene_summary,
        assessment=assessment,
    )
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(encounter, kind=step_kind, content=reply)
    legacy._apply_termination_updates(encounter, termination_updates)
    _update_encounter_state_with_delta(encounter, situation_delta)
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = legacy._finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
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
            situation_delta=situation_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    legacy._append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        reply,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    legacy._touch_state(state)
    return [
        _new_scene_event(
            "encounter_situation_update",
            _situation_event_text(assessment, reply),
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": situation_delta,
                "direction": assessment.direction,
                "trend": assessment.trend,
                "summary_basis": "numeric",
            },
        ),
        _new_scene_event(
            event_kind,
            reply,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        ),
    ]


def get_encounter_debug_overview(session_id: str) -> EncounterDebugOverviewResponse:
    legacy = _legacy()
    save = legacy.get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    state = legacy._state(save)
    active = legacy._current_active_encounter(state)
    queued = legacy._pending_entries(state)
    if active is not None:
        summary = f"当前活跃遭遇: {active.title} / {active.status} / 局势 {active.situation_value}/100"
    elif queued:
        summary = f"待处理遭遇数: {len(queued)}"
    else:
        summary = "当前没有活跃或待处理遭遇。"
    return EncounterDebugOverviewResponse(
        session_id=session_id,
        active_encounter=(legacy.serialize_public_encounter(active) if active is not None else None),
        queued_encounters=[legacy.serialize_public_encounter(item) for item in queued],
        summary=summary,
    )
    if active is not None:
        summary = f"当前活跃遭遇: {active.title} / {active.status} / {active.player_presence} / 局势 {active.situation_value}/100"
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
