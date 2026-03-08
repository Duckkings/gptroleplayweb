from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError, RateLimitError
from pydantic import ValidationError

from app.core.dialogs import pick_directory
from app.core.storage import read_json, storage_state, write_json_atomic
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    AreaCurrentResponse,
    AreaDiscoverInteractionsRequest,
    AreaDiscoverInteractionsResponse,
    EncounterActRequest,
    EncounterActResponse,
    EncounterCheckRequest,
    EncounterCheckResponse,
    EncounterDebugOverviewResponse,
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
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResponse,
    ActionCheckRequest,
    ActionCheckResponse,
    AreaMoveResult,
    AreaMoveSubZoneRequest,
    BehaviorDescribeRequest,
    BehaviorDescribeResponse,
    ChatConfig,
    FateCurrentResponse,
    FateEvaluateRequest,
    FateEvaluateResponse,
    FateGenerateRequest,
    FateGenerateResponse,
    ConsistencyRunRequest,
    ConsistencyRunResponse,
    ConsistencyStatusResponse,
    EntityIndexResponse,
    InventoryEquipRequest,
    InventoryInteractRequest,
    InventoryInteractResponse,
    InventoryMutationResponse,
    InventoryUnequipRequest,
    GameLogAddRequest,
    GameLogListResponse,
    GameLogSettings,
    GameLogSettingsResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MoveRequest,
    MoveResponse,
    NpcChatRequest,
    NpcChatResponse,
    NpcGreetRequest,
    NpcGreetResponse,
    PathConfig,
    PathStatusResponse,
    PlayerBuffAddRequest,
    PlayerBuffRemoveRequest,
    PlayerEquipRequest,
    PlayerItemAddRequest,
    PlayerItemRemoveRequest,
    PlayerRuntimeData,
    PlayerSkillSetRequest,
    PlayerSpellSetRequest,
    PlayerSpellSlotAdjustRequest,
    PlayerStaticData,
    PlayerStaminaAdjustRequest,
    PlayerUnequipRequest,
    RegionGenerateRequest,
    RegionGenerateResponse,
    QuestEvaluateAllRequest,
    QuestActionRequest,
    QuestEvaluateRequest,
    QuestMutationResponse,
    QuestPublishRequest,
    QuestStateResponse,
    RolePoolListResponse,
    RoleRelationSetRequest,
    RoleRelationUpsertRequest,
    NpcRoleCard,
    RenderMapRequest,
    RenderMapResponse,
    SaveClearRequest,
    SaveFile,
    SaveImportRequest,
    SaveSetRequest,
    StorySnapshotResponse,
    TeamDebugGenerateRequest,
    TeamInviteRequest,
    TeamLeaveRequest,
    TeamChatRequest,
    TeamChatResponse,
    TeamMutationResponse,
    TeamStateResponse,
    TokenUsageResponse,
    ValidateConfigResponse,
    ValidateError,
    WorldClockInitRequest,
    WorldClockInitResponse,
    NpcKnowledgeResponse,
)
from app.services.chat_service import MissingAPIKeyError, chat_once
from app.services.world_service import (
    AIBehaviorError,
    AIRegionGenerationError,
    _new_scene_event,
    advance_public_scene_in_save,
    clear_current_save,
    describe_behavior,
    add_game_log,
    action_check,
    apply_speech_time,
    discover_interactions,
    execute_interaction,
    equip_player_item,
    generate_regions,
    get_area_current,
    get_game_log_settings,
    get_game_logs,
    get_current_save,
    get_player_runtime,
    get_player_static,
    get_role_card,
    get_role_pool,
    add_player_buff,
    add_player_item,
    add_player_skill,
    add_player_spell,
    consume_spell_slots,
    consume_stamina,
    recover_spell_slots,
    recover_stamina,
    remove_player_buff,
    remove_player_item,
    remove_player_skill,
    remove_player_spell,
    set_role_relation,
    upsert_player_relation,
    import_save,
    move_to_zone,
    move_to_sub_zone,
    npc_chat,
    render_map,
    save_current,
    set_game_log_settings,
    set_player_runtime,
    set_player_static,
    inventory_equip,
    inventory_interact,
    inventory_unequip,
    unequip_player_item,
    init_world_clock,
    npc_greet,
)
from app.services.encounter_service import (
    act_on_encounter,
    advance_active_encounter_in_save,
    check_for_encounter,
    escape_encounter,
    get_encounter_debug_overview,
    get_encounter_history,
    get_pending_encounters,
    present_encounter,
    rejoin_encounter,
    set_debug_force_toggle,
)
from app.services.fate_service import evaluate_fate_state, generate_fate, get_fate_state, regenerate_fate
from app.services.quest_service import (
    accept_quest,
    debug_generate_quest,
    evaluate_all_quests,
    evaluate_quest,
    get_quest_state,
    publish_quest,
    reject_quest,
    track_quest,
)
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    build_npc_knowledge_snapshot,
    collect_consistency_issues,
    reconcile_consistency,
)
from app.services.team_service import (
    apply_team_reactions,
    generate_debug_teammate,
    get_team_state,
    invite_npc_to_team,
    leave_npc_from_team,
    team_chat,
)

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, time=datetime.now(timezone.utc).isoformat())


@router.post("/config/validate", response_model=ValidateConfigResponse)
async def validate_config(payload: dict) -> ValidateConfigResponse:
    try:
        ChatConfig.model_validate(payload)
    except ValidationError as exc:
        errors = [
            ValidateError(field=".".join(str(p) for p in err["loc"]), message=err["msg"])
            for err in exc.errors()
        ]
        return ValidateConfigResponse(valid=False, errors=errors)

    return ValidateConfigResponse(valid=True, errors=[])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
    time_spent_min = apply_speech_time(payload.session_id, last_user.content, payload.config) if last_user is not None else 0
    try:
        reply, usage, tool_events = await chat_once(payload)
    except MissingAPIKeyError:
        raise HTTPException(status_code=401, detail="openai_api_key is not configured in config")
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    scene_events = []
    if last_user is not None:
        try:
            save = get_current_save(default_session_id=payload.session_id)
            if save.session_id != payload.session_id:
                save.session_id = payload.session_id
            scene_events = advance_public_scene_in_save(
                save,
                session_id=payload.session_id,
                player_text=last_user.content,
                gm_summary=reply.content,
                config=payload.config,
            )
            advanced = advance_active_encounter_in_save(save, session_id=payload.session_id, minutes_elapsed=time_spent_min, config=payload.config)
            if advanced is not None:
                scene_events.append(
                    _new_scene_event(
                        "encounter_background",
                        advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                        metadata={"encounter_id": advanced.encounter_id},
                    )
                )
            save_current(save)
        except Exception:
            pass

    token_usage_store.add(payload.session_id, "chat", usage.input_tokens, usage.output_tokens)
    if last_user is not None:
        add_game_log(
            GameLogAddRequest(
                session_id=payload.session_id,
                kind="player_input",
                message=last_user.content,
            )
        )
    add_game_log(
        GameLogAddRequest(
            session_id=payload.session_id,
            kind="gm_reply",
            message=reply.content,
        )
    )
    if last_user is not None:
        try:
            apply_team_reactions(
                payload.session_id,
                trigger_kind="main_chat",
                player_text=last_user.content,
                summary=reply.content,
            )
        except Exception:
            pass
    return ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        usage=usage,
        tool_events=tool_events,
        scene_events=scene_events,
        time_spent_min=time_spent_min,
    )


@router.post("/chat/stream")
async def chat_sse(payload: ChatRequest) -> StreamingResponse:
    if not payload.config.stream:
        raise HTTPException(status_code=400, detail="config.stream must be true")

    async def event_gen():
        yield "event: start\ndata: {\"session_id\":\"%s\"}\n\n" % payload.session_id
        last_user = next((m for m in reversed(payload.messages) if m.role == "user"), None)
        time_spent_min = apply_speech_time(payload.session_id, last_user.content, payload.config) if last_user is not None else 0
        scene_events = []
        try:
            reply, usage, tool_events = await chat_once(payload)
            if last_user is not None:
                try:
                    save = get_current_save(default_session_id=payload.session_id)
                    if save.session_id != payload.session_id:
                        save.session_id = payload.session_id
                    scene_events = advance_public_scene_in_save(
                        save,
                        session_id=payload.session_id,
                        player_text=last_user.content,
                        gm_summary=reply.content,
                        config=payload.config,
                    )
                    advanced = advance_active_encounter_in_save(save, session_id=payload.session_id, minutes_elapsed=time_spent_min, config=payload.config)
                    if advanced is not None:
                        scene_events.append(
                            _new_scene_event(
                                "encounter_background",
                                advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                                metadata={"encounter_id": advanced.encounter_id},
                            )
                        )
                    save_current(save)
                except Exception:
                    pass
            data = json.dumps({"content": reply.content}, ensure_ascii=False)
            yield f"event: delta\ndata: {data}\n\n"
        except MissingAPIKeyError:
            data = json.dumps({"code": 401, "message": "openai_api_key is not configured in config"})
            yield f"event: error\ndata: {data}\n\n"
            return
        except RateLimitError as exc:
            data = json.dumps({"code": 429, "message": str(exc)})
            yield f"event: error\ndata: {data}\n\n"
            return
        except APIError as exc:
            data = json.dumps({"code": 502, "message": str(exc)})
            yield f"event: error\ndata: {data}\n\n"
            return

        token_usage_store.add(payload.session_id, "chat", usage.input_tokens, usage.output_tokens)
        if last_user is not None:
            add_game_log(
                GameLogAddRequest(
                    session_id=payload.session_id,
                    kind="player_input",
                    message=last_user.content,
                )
            )
        add_game_log(
            GameLogAddRequest(
                session_id=payload.session_id,
                kind="gm_reply",
                message=reply.content,
            )
        )
        if last_user is not None:
            try:
                apply_team_reactions(
                    payload.session_id,
                    trigger_kind="main_chat",
                    player_text=last_user.content,
                    summary=reply.content,
                )
            except Exception:
                pass
        usage_data = json.dumps(
            {
                "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
                "tool_events": [ev.model_dump(mode="json") for ev in tool_events],
                "scene_events": [ev.model_dump(mode="json") for ev in scene_events],
                "time_spent_min": time_spent_min,
            },
            ensure_ascii=False,
        )
        yield f"event: end\ndata: {usage_data}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/storage/config/path", response_model=PathStatusResponse)
async def get_config_path() -> PathStatusResponse:
    return storage_state.path_status(storage_state.config_path)


@router.post("/storage/config/path", response_model=PathStatusResponse)
async def set_config_path(payload: PathConfig) -> PathStatusResponse:
    path = storage_state.set_config_path(payload.path)
    return storage_state.path_status(path)


@router.post("/storage/config/path/pick", response_model=PathStatusResponse)
async def pick_config_path() -> PathStatusResponse:
    directory = pick_directory("选择配置文件夹")
    if directory is None:
        raise HTTPException(status_code=400, detail="未选择目录或系统不支持目录选择窗口")

    path = storage_state.set_config_path(str(directory / "config.json"))
    return storage_state.path_status(path)


@router.get("/storage/config")
async def get_config_data() -> dict:
    path = storage_state.config_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="config file not found")
    return read_json(path)


@router.post("/storage/config")
async def set_config_data(payload: dict) -> dict:
    try:
        cfg = ChatConfig.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    write_json_atomic(storage_state.config_path, cfg.model_dump(mode="json"))
    return {"ok": True, "path": str(storage_state.config_path)}


@router.get("/saves/path", response_model=PathStatusResponse)
async def get_save_path() -> PathStatusResponse:
    return storage_state.path_status(storage_state.save_path)


@router.post("/saves/path", response_model=PathStatusResponse)
async def set_save_path(payload: PathConfig) -> PathStatusResponse:
    path = storage_state.set_save_path(payload.path)
    return storage_state.path_status(path)


@router.post("/saves/path/pick", response_model=PathStatusResponse)
async def pick_save_path() -> PathStatusResponse:
    directory = pick_directory("选择存档文件夹")
    if directory is None:
        raise HTTPException(status_code=400, detail="未选择目录或系统不支持目录选择窗口")

    path = storage_state.set_save_path(str(directory / "current-save.json"))
    return storage_state.path_status(path)


@router.get("/saves/current", response_model=SaveFile)
async def get_save_current() -> SaveFile:
    return get_current_save()


@router.post("/saves/current", response_model=SaveFile)
async def set_save_current(payload: SaveSetRequest) -> SaveFile:
    save = SaveFile.model_validate(payload.save_data)
    save_current(save)
    return save


@router.post("/saves/import", response_model=SaveFile)
async def import_save_file(payload: SaveImportRequest) -> SaveFile:
    save = SaveFile.model_validate(payload.save_data)
    return import_save(save)


@router.post("/saves/clear", response_model=SaveFile)
async def clear_save(payload: SaveClearRequest) -> SaveFile:
    return clear_current_save(payload.session_id)


@router.post("/world-map/regions/generate", response_model=RegionGenerateResponse)
async def world_map_generate(payload: RegionGenerateRequest) -> RegionGenerateResponse:
    try:
        return generate_regions(payload)
    except AIRegionGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"地图区块 AI 生成失败: {exc}")


@router.post("/world-map/render", response_model=RenderMapResponse)
async def world_map_render(payload: RenderMapRequest) -> RenderMapResponse:
    return render_map(payload)


@router.post("/world-map/move", response_model=MoveResponse)
async def world_map_move(payload: MoveRequest) -> MoveResponse:
    try:
        return move_to_zone(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="zone not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/logs/behavior/describe", response_model=BehaviorDescribeResponse)
async def behavior_describe(payload: BehaviorDescribeRequest) -> BehaviorDescribeResponse:
    try:
        return describe_behavior(payload.session_id, payload.log, payload.config)
    except AIBehaviorError as exc:
        raise HTTPException(status_code=502, detail=f"行为叙事 AI 生成失败: {exc}")


@router.post("/logs/game", response_model=GameLogListResponse)
async def game_log_add(payload: GameLogAddRequest) -> GameLogListResponse:
    add_game_log(payload)
    return get_game_logs(payload.session_id, limit=200)


@router.get("/logs/game", response_model=GameLogListResponse)
async def game_log_list(session_id: str, limit: int | None = None) -> GameLogListResponse:
    return get_game_logs(session_id, limit=limit)


@router.get("/logs/game/settings", response_model=GameLogSettingsResponse)
async def game_log_settings_get(session_id: str) -> GameLogSettingsResponse:
    return get_game_log_settings(session_id)


@router.post("/logs/game/settings", response_model=GameLogSettingsResponse)
async def game_log_settings_set(session_id: str, payload: GameLogSettings) -> GameLogSettingsResponse:
    return set_game_log_settings(session_id, payload)


@router.get("/quests", response_model=QuestStateResponse)
async def quest_state_get(session_id: str) -> QuestStateResponse:
    return get_quest_state(session_id)


@router.get("/quests/current", response_model=QuestStateResponse)
async def quest_current_get(session_id: str) -> QuestStateResponse:
    return get_quest_state(session_id)


@router.post("/quests/publish", response_model=QuestMutationResponse)
async def quest_publish(payload: QuestPublishRequest) -> QuestMutationResponse:
    try:
        return publish_quest(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/quests/debug/generate", response_model=QuestMutationResponse)
async def quest_debug_generate(payload: FateGenerateRequest) -> QuestMutationResponse:
    return debug_generate_quest(payload.session_id, payload.config)


@router.post("/quests/{quest_id}/accept", response_model=QuestMutationResponse)
async def quest_accept(quest_id: str, payload: QuestActionRequest) -> QuestMutationResponse:
    try:
        return accept_quest(payload.session_id, quest_id, payload.config)
    except KeyError:
        raise HTTPException(status_code=404, detail="quest not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/quests/{quest_id}/reject", response_model=QuestMutationResponse)
async def quest_reject(quest_id: str, payload: QuestActionRequest) -> QuestMutationResponse:
    try:
        return reject_quest(payload.session_id, quest_id, payload.config)
    except KeyError:
        raise HTTPException(status_code=404, detail="quest not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/quests/{quest_id}/track", response_model=QuestMutationResponse)
async def quest_track(quest_id: str, session_id: str) -> QuestMutationResponse:
    try:
        return track_quest(session_id, quest_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="quest not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/quests/{quest_id}/evaluate", response_model=QuestMutationResponse)
async def quest_evaluate(quest_id: str, payload: QuestEvaluateRequest) -> QuestMutationResponse:
    if payload.quest_id != quest_id:
        raise HTTPException(status_code=409, detail="quest id mismatch")
    try:
        return evaluate_quest(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="quest not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/quests/evaluate-all", response_model=QuestStateResponse)
async def quest_evaluate_all(payload: QuestEvaluateAllRequest) -> QuestStateResponse:
    return evaluate_all_quests(payload)


@router.get("/encounters/pending", response_model=EncounterPendingResponse)
async def encounter_pending(session_id: str) -> EncounterPendingResponse:
    return get_pending_encounters(session_id)


@router.get("/encounters/history", response_model=EncounterHistoryResponse)
async def encounter_history(session_id: str) -> EncounterHistoryResponse:
    return get_encounter_history(session_id)


@router.post("/encounters/check", response_model=EncounterCheckResponse)
async def encounter_check(payload: EncounterCheckRequest) -> EncounterCheckResponse:
    try:
        return check_for_encounter(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/encounters/{encounter_id}/present", response_model=EncounterPresentResponse)
async def encounter_present(encounter_id: str, payload: EncounterPresentRequest) -> EncounterPresentResponse:
    try:
        return present_encounter(encounter_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="encounter not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/encounters/{encounter_id}/act", response_model=EncounterActResponse)
async def encounter_act(encounter_id: str, payload: EncounterActRequest) -> EncounterActResponse:
    try:
        return act_on_encounter(encounter_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="encounter not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/encounters/{encounter_id}/escape", response_model=EncounterEscapeResponse)
async def encounter_escape(encounter_id: str, payload: EncounterEscapeRequest) -> EncounterEscapeResponse:
    try:
        return escape_encounter(encounter_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="encounter not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/encounters/{encounter_id}/rejoin", response_model=EncounterRejoinResponse)
async def encounter_rejoin(encounter_id: str, payload: EncounterRejoinRequest) -> EncounterRejoinResponse:
    try:
        return rejoin_encounter(encounter_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="encounter not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/encounters/debug/force-toggle", response_model=EncounterForceToggleResponse)
async def encounter_force_toggle(payload: EncounterForceToggleRequest) -> EncounterForceToggleResponse:
    return set_debug_force_toggle(payload)


@router.get("/encounters/debug/overview", response_model=EncounterDebugOverviewResponse)
async def encounter_debug_overview(session_id: str) -> EncounterDebugOverviewResponse:
    return get_encounter_debug_overview(session_id)


@router.get("/fate/current", response_model=FateCurrentResponse)
async def fate_current(session_id: str) -> FateCurrentResponse:
    return get_fate_state(session_id)


@router.post("/fate/debug/generate", response_model=FateGenerateResponse)
async def fate_debug_generate(payload: FateGenerateRequest) -> FateGenerateResponse:
    try:
        return generate_fate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/fate/debug/regenerate", response_model=FateGenerateResponse)
async def fate_debug_regenerate(payload: FateGenerateRequest) -> FateGenerateResponse:
    return regenerate_fate(payload)


@router.post("/fate/evaluate", response_model=FateEvaluateResponse)
async def fate_evaluate(payload: FateEvaluateRequest) -> FateEvaluateResponse:
    return evaluate_fate_state(payload)


@router.get("/story/snapshot", response_model=StorySnapshotResponse)
async def story_snapshot_get(session_id: str) -> StorySnapshotResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    return StorySnapshotResponse(session_id=session_id, snapshot=build_global_story_snapshot(save))


@router.get("/story/entity-index", response_model=EntityIndexResponse)
async def story_entity_index_get(session_id: str, scope: str | None = None) -> EntityIndexResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    return build_entity_index(save, scope=(scope or "global"))


@router.get("/consistency/status", response_model=ConsistencyStatusResponse)
async def consistency_status_get(session_id: str) -> ConsistencyStatusResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    issues = collect_consistency_issues(save)
    return ConsistencyStatusResponse(session_id=session_id, world_state=save.world_state, issue_count=len(issues), issues=issues)


@router.post("/consistency/run", response_model=ConsistencyRunResponse)
async def consistency_run(payload: ConsistencyRunRequest) -> ConsistencyRunResponse:
    save = get_current_save(default_session_id=payload.session_id)
    save.session_id = payload.session_id
    issues, changed = reconcile_consistency(save, session_id=payload.session_id, reason="manual")
    save_current(save)
    return ConsistencyRunResponse(
        session_id=payload.session_id,
        world_state=save.world_state,
        issue_count=len(issues),
        issues=issues,
        changed=changed,
    )


@router.get("/token-usage", response_model=TokenUsageResponse)
async def token_usage(session_id: str) -> TokenUsageResponse:
    return token_usage_store.get(session_id)


@router.get("/player/static", response_model=PlayerStaticData)
async def player_static_get(session_id: str) -> PlayerStaticData:
    return get_player_static(session_id)


@router.post("/player/static", response_model=PlayerStaticData)
async def player_static_set(session_id: str, payload: PlayerStaticData) -> PlayerStaticData:
    return set_player_static(session_id, payload)


@router.post("/player/equipment/equip", response_model=PlayerStaticData)
async def player_equip_item(session_id: str, payload: PlayerEquipRequest) -> PlayerStaticData:
    try:
        return equip_player_item(session_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/player/equipment/unequip", response_model=PlayerStaticData)
async def player_unequip_item(session_id: str, payload: PlayerUnequipRequest) -> PlayerStaticData:
    return unequip_player_item(session_id, payload)


@router.post("/inventory/equip", response_model=InventoryMutationResponse)
async def inventory_equip_item(payload: InventoryEquipRequest) -> InventoryMutationResponse:
    try:
        return inventory_equip(payload)
    except KeyError as exc:
        code = str(exc)
        if "ROLE_NOT_FOUND" in code:
            raise HTTPException(status_code=404, detail="role not found")
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/inventory/unequip", response_model=InventoryMutationResponse)
async def inventory_unequip_item(payload: InventoryUnequipRequest) -> InventoryMutationResponse:
    try:
        return inventory_unequip(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/inventory/interact", response_model=InventoryInteractResponse)
async def inventory_interact_item(payload: InventoryInteractRequest) -> InventoryInteractResponse:
    try:
        return inventory_interact(payload)
    except KeyError as exc:
        code = str(exc)
        if "ROLE_NOT_FOUND" in code:
            raise HTTPException(status_code=404, detail="role not found")
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/player/buffs/add", response_model=PlayerStaticData)
async def player_buff_add(session_id: str, payload: PlayerBuffAddRequest) -> PlayerStaticData:
    return add_player_buff(session_id, payload)


@router.post("/player/buffs/remove", response_model=PlayerStaticData)
async def player_buff_remove(session_id: str, payload: PlayerBuffRemoveRequest) -> PlayerStaticData:
    return remove_player_buff(session_id, payload)


@router.post("/player/items/add", response_model=PlayerStaticData)
async def player_item_add(session_id: str, payload: PlayerItemAddRequest) -> PlayerStaticData:
    return add_player_item(session_id, payload)


@router.post("/player/items/remove", response_model=PlayerStaticData)
async def player_item_remove(session_id: str, payload: PlayerItemRemoveRequest) -> PlayerStaticData:
    try:
        return remove_player_item(session_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="item not found")


@router.post("/player/spells/add", response_model=PlayerStaticData)
async def player_spell_add(session_id: str, payload: PlayerSpellSetRequest) -> PlayerStaticData:
    return add_player_spell(session_id, payload)


@router.post("/player/spells/remove", response_model=PlayerStaticData)
async def player_spell_remove(session_id: str, payload: PlayerSpellSetRequest) -> PlayerStaticData:
    return remove_player_spell(session_id, payload)


@router.post("/player/skills/add", response_model=PlayerStaticData)
async def player_skill_add(session_id: str, payload: PlayerSkillSetRequest) -> PlayerStaticData:
    return add_player_skill(session_id, payload)


@router.post("/player/skills/remove", response_model=PlayerStaticData)
async def player_skill_remove(session_id: str, payload: PlayerSkillSetRequest) -> PlayerStaticData:
    return remove_player_skill(session_id, payload)


@router.post("/player/resources/spell-slots/consume", response_model=PlayerStaticData)
async def player_spell_slots_consume(session_id: str, payload: PlayerSpellSlotAdjustRequest) -> PlayerStaticData:
    try:
        return consume_spell_slots(session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/player/resources/spell-slots/recover", response_model=PlayerStaticData)
async def player_spell_slots_recover(session_id: str, payload: PlayerSpellSlotAdjustRequest) -> PlayerStaticData:
    return recover_spell_slots(session_id, payload)


@router.post("/player/resources/stamina/consume", response_model=PlayerStaticData)
async def player_stamina_consume(session_id: str, payload: PlayerStaminaAdjustRequest) -> PlayerStaticData:
    try:
        return consume_stamina(session_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/player/resources/stamina/recover", response_model=PlayerStaticData)
async def player_stamina_recover(session_id: str, payload: PlayerStaminaAdjustRequest) -> PlayerStaticData:
    return recover_stamina(session_id, payload)


@router.get("/player/runtime", response_model=PlayerRuntimeData)
async def player_runtime_get(session_id: str) -> PlayerRuntimeData:
    return get_player_runtime(session_id)


@router.post("/player/runtime", response_model=PlayerRuntimeData)
async def player_runtime_set(session_id: str, payload: PlayerRuntimeData) -> PlayerRuntimeData:
    return set_player_runtime(session_id, payload)


@router.get("/role-pool", response_model=RolePoolListResponse)
async def role_pool_list(session_id: str, q: str | None = None, limit: int | None = None) -> RolePoolListResponse:
    return get_role_pool(session_id, query=q, limit=(limit if limit is not None else 200))


@router.get("/role-pool/{role_id}", response_model=NpcRoleCard)
async def role_pool_get(role_id: str, session_id: str) -> NpcRoleCard:
    try:
        return get_role_card(session_id, role_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.post("/role-pool/{role_id}/relate-player", response_model=NpcRoleCard)
async def role_pool_relate_player(role_id: str, session_id: str, payload: RoleRelationUpsertRequest) -> NpcRoleCard:
    try:
        return upsert_player_relation(session_id, role_id, payload.relation_tag, payload.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.post("/role-pool/{role_id}/relations", response_model=NpcRoleCard)
async def role_pool_set_relation(role_id: str, session_id: str, payload: RoleRelationSetRequest) -> NpcRoleCard:
    try:
        return set_role_relation(session_id, role_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.post("/npc/greet", response_model=NpcGreetResponse)
async def npc_greet_run(payload: NpcGreetRequest) -> NpcGreetResponse:
    try:
        return npc_greet(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.post("/npc/chat", response_model=NpcChatResponse)
async def npc_chat_run(payload: NpcChatRequest) -> NpcChatResponse:
    try:
        return npc_chat(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.get("/npc/{npc_role_id}/knowledge", response_model=NpcKnowledgeResponse)
async def npc_knowledge_get(npc_role_id: str, session_id: str) -> NpcKnowledgeResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    try:
        snapshot = build_npc_knowledge_snapshot(save, npc_role_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    return NpcKnowledgeResponse(session_id=session_id, npc_role_id=npc_role_id, snapshot=snapshot)


@router.get("/team", response_model=TeamStateResponse)
async def team_state_get(session_id: str) -> TeamStateResponse:
    try:
        return get_team_state(session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/team/invite", response_model=TeamMutationResponse)
async def team_invite_run(payload: TeamInviteRequest) -> TeamMutationResponse:
    try:
        return invite_npc_to_team(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/team/leave", response_model=TeamMutationResponse)
async def team_leave_run(payload: TeamLeaveRequest) -> TeamMutationResponse:
    try:
        return leave_npc_from_team(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/team/debug/generate", response_model=TeamMutationResponse)
async def team_debug_generate_run(payload: TeamDebugGenerateRequest) -> TeamMutationResponse:
    try:
        return generate_debug_teammate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/team/chat", response_model=TeamChatResponse)
async def team_chat_run(payload: TeamChatRequest) -> TeamChatResponse:
    try:
        return team_chat(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/npc/chat/stream")
async def npc_chat_stream(payload: NpcChatRequest) -> StreamingResponse:
    if payload.config is not None and not payload.config.stream:
        raise HTTPException(status_code=400, detail="config.stream must be true")

    async def event_gen():
        yield "event: start\ndata: {\"session_id\":\"%s\",\"npc_role_id\":\"%s\"}\n\n" % (payload.session_id, payload.npc_role_id)
        try:
            result = npc_chat(payload)
            reply_text = result.reply
            step = 14
            for idx in range(0, len(reply_text), step):
                chunk = reply_text[idx : idx + step]
                yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.015)
        except KeyError:
            data = json.dumps({"code": 404, "message": "role not found"}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"
            return
        except Exception as exc:
            data = json.dumps({"code": 500, "message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"
            return

        data = json.dumps(
            {
                "time_spent_min": result.time_spent_min,
                "dialogue_logs": [item.model_dump(mode="json") for item in result.dialogue_logs],
            },
            ensure_ascii=False,
        )
        yield f"event: end\ndata: {data}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/world/clock/init", response_model=WorldClockInitResponse)
async def world_clock_init(payload: WorldClockInitRequest) -> WorldClockInitResponse:
    return init_world_clock(payload)


@router.get("/world/area/current", response_model=AreaCurrentResponse)
async def world_area_current(session_id: str) -> AreaCurrentResponse:
    return get_area_current(session_id)


@router.post("/world/area/move-sub-zone", response_model=AreaMoveResult)
async def world_area_move_sub_zone(payload: AreaMoveSubZoneRequest) -> AreaMoveResult:
    try:
        return move_to_sub_zone(payload)
    except KeyError as exc:
        if str(exc) == "'AREA_SUB_ZONE_NOT_FOUND'":
            raise HTTPException(status_code=404, detail="sub zone not found")
        raise HTTPException(status_code=404, detail="target not found")
    except ValueError as exc:
        if str(exc) == "AREA_CLOCK_NOT_INIT":
            raise HTTPException(status_code=409, detail="clock not initialized")
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/world/area/interactions/discover", response_model=AreaDiscoverInteractionsResponse)
async def world_area_discover_interactions(payload: AreaDiscoverInteractionsRequest) -> AreaDiscoverInteractionsResponse:
    try:
        return discover_interactions(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="sub zone not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/world/area/interactions/execute", response_model=AreaExecuteInteractionResponse)
async def world_area_execute_interaction(payload: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResponse:
    try:
        return execute_interaction(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="interaction not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/actions/check", response_model=ActionCheckResponse)
async def action_check_run(payload: ActionCheckRequest) -> ActionCheckResponse:
    try:
        return action_check(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
