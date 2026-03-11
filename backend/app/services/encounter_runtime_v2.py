from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import ChatConfig, EncounterActRequest, EncounterDebugOverviewResponse, EncounterEntry, EncounterResolution
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.world_service import _new_scene_event, _parse_player_intent


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


def ai_resolve_encounter(encounter: EncounterEntry, req: EncounterActRequest, *, assessment: SituationAssessment | None = None) -> dict[str, object] | None:
    legacy = _legacy()
    config = req.config
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
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
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.resolve.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = legacy._extract_json_content((resp.choices[0].message.content or "").strip())
        minutes = max(1, min(30, int(parsed.get("time_spent_min") or fallback_minutes or 1)))
        step_kind = str(parsed.get("step_kind") or "gm_update").strip().lower()
        if step_kind not in {"gm_update", "resolution"}:
            step_kind = "gm_update"
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
        termination_updates = parsed.get("termination_updates")
        if not isinstance(termination_updates, list):
            termination_updates = []
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
    except Exception:
        return None


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


def advance_active_encounter_in_save(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    legacy = _legacy()
    state = legacy._state(save)
    encounter = legacy._current_active_encounter(state)
    if encounter is None or encounter.player_presence != "away" or encounter.status not in {"active", "escaped"}:
        return None
    if minutes_elapsed <= 0:
        return None
    if encounter.presented_at is None:
        legacy._initialize_encounter_state(save, encounter)

    background_delta = -legacy._clamp(max(1, minutes_elapsed // 10), 1, 6)
    assessment = assess_situation_change(encounter.situation_value, background_delta, legacy._clamp(encounter.situation_value + background_delta, 0, 100))
    team_members, visible_npcs = legacy._visible_participant_text(save, encounter)
    raw_reply = f"你离开现场后，《{encounter.title}》仍在后台推进。"
    raw_scene_summary = encounter.scene_summary or encounter.description
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
    _update_encounter_state_with_delta(encounter, background_delta)
    encounter.scene_summary = next_scene_summary
    encounter.background_tick_count += 1
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = legacy._utc_now()
    legacy._append_step(encounter, kind="background_tick", content=reply)
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

    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    display_text = str(parsed_intent.get("display_text") or player_text).strip()
    if passive_turn:
        display_text = "【玩家旁观】玩家本轮选择观察与等待，不主动行动。"
    if any(token in display_text for token in ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]):
        reply = f"你暂时从《{encounter.title}》里抽身离开，但现场问题仍在继续发展。"
        encounter.status = "escaped"
        encounter.player_presence = "away"
        encounter.latest_outcome_summary = reply
        encounter.last_advanced_at = legacy._utc_now()
        legacy._append_step(encounter, kind="escape_attempt", content=reply)
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                legacy._apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
        state.active_encounter_id = encounter.encounter_id
        legacy._append_game_log(save, session_id, "encounter_escape", reply, {"encounter_id": encounter.encounter_id, "from_main_chat": True})
        legacy._touch_state(state)
        return [_new_scene_event("encounter_progress", reply, metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status})]

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
