from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai import APIError, RateLimitError
from pydantic import ValidationError

from app.core.dialogs import pick_directory
from app.core.storage import read_json, storage_state, write_json_atomic
from app.core.user_context import get_current_user
from app.models.schemas import (
    AreaCurrentResponse,
    AreaDiscoverInteractionsRequest,
    AreaDiscoverInteractionsResolvedResponse,
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
    AreaExecuteInteractionResolvedResponse,
    ActionCheckRequest,
    ActionCheckPlanRequest,
    ActionCheckPlanResponse,
    ActionCheckResponse,
    AreaMoveResolvedResponse,
    AreaMoveSubZoneRequest,
    BehaviorDescribeRequest,
    BehaviorDescribeResponse,
    BattleActionRequest,
    BattleActionResponse,
    BattleContinueAiRequest,
    BattleContinueAiResponse,
    BattleCurrentResponse,
    BattleEndResponse,
    BattleResolveRollRequest,
    BattleResolveRollResponse,
    BattleStartRequest,
    BattleStartResponse,
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
    InventoryConsumeRequest,
    InventoryGrantRequest,
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
    MoveResolvedResponse,
    ModelDiscoverResponse,
    ModelProfileRequest,
    ModelProfileResponse,
    NpcChatRequest,
    NpcChatResponse,
    NpcGreetRequest,
    NpcGreetResponse,
    PathConfig,
    PathStatusResponse,
    PendingTurnContinueRequest,
    PendingTurnContinueResponse,
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
    PublicSceneStateResponse,
    ReputationStateResponse,
    MapBootstrapResponse,
    RegionGenerateRequest,
    RegionGenerateResponse,
    RoleDrivesResponse,
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
    TemplateLibraryFillRequest,
    TemplateLibraryFillResponse,
    TemplateLibraryStatusResponse,
    TokenUsageResponse,
    ValidateConfigResponse,
    ValidateError,
    WorldClockInitRequest,
    WorldClockInitResponse,
    NpcKnowledgeResponse,
)
from app.services.ai_adapter import discover_models, resolve_model_profile
from app.services.battle_service import (
    end_debug_battle,
    get_current_debug_battle,
    handle_continue_battle_ai,
    handle_player_battle_action,
    handle_resolve_battle_roll,
    start_debug_battle,
)
from app.services.chat_service import MissingAPIKeyError
from app.services.stream_chat_service import (
    StreamCancelledError,
    run_main_turn_once,
    run_main_turn_stream,
    run_pending_turn_once,
    run_pending_turn_stream,
    run_npc_chat_once,
    run_npc_chat_stream,
)
from app.services.map_flow_service import (
    bootstrap_world_map,
    discover_area_interactions,
    execute_area_interaction,
    move_world_map,
    move_world_sub_zone,
    run_action_check_with_state_sync,
)
from app.services.pending_turn_service import cancel_pending_turn, load_pending_turn
from app.services.template_library_debug_service import fill_template_library, get_template_library_status_response
from app.services.world_service import (
    AIBehaviorError,
    AIRegionGenerationError,
    clear_current_save,
    describe_behavior,
    add_game_log,
    action_check,
    plan_action_check,
    discover_interactions,
    execute_interaction,
    equip_player_item,
    generate_regions,
    get_area_current,
    get_game_log_settings,
    get_game_logs,
    get_current_save,
    get_scene_interactables,
    get_player_runtime,
    get_player_static,
    get_template_library_status_payload,
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
    NpcChatConfigError,
    NpcChatGenerationError,
    render_map,
    save_current,
    set_game_log_settings,
    set_player_runtime,
    set_player_static,
    inventory_equip,
    inventory_consume,
    inventory_grant,
    inventory_interact,
    inventory_unequip,
    unequip_player_item,
    init_world_clock,
    npc_greet,
)
from app.services.encounter_service import (
    act_on_encounter,
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
from app.services.public_scene_service import get_public_scene_state
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
from app.services.reputation_service import get_area_reputation
from app.services.roleplay_service import build_role_drive_summaries
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    build_npc_knowledge_snapshot,
    collect_consistency_issues,
    reconcile_consistency,
)
from app.services.team_service import (
    generate_debug_teammate,
    get_team_state,
    invite_npc_to_team,
    leave_npc_from_team,
    team_chat,
)

from app.services.retained_npc_service import retained_npc_service

router = APIRouter(prefix="/api/v1", tags=["api"])


def _sse_frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, time=datetime.now(timezone.utc).isoformat())


@router.post("/config/validate", response_model=ValidateConfigResponse)
async def validate_config(payload: dict) -> ValidateConfigResponse:
    try:
        config = ChatConfig.model_validate(payload)
    except ValidationError as exc:
        errors = [
            ValidateError(field=".".join(str(p) for p in err["loc"]), message=err["msg"])
            for err in exc.errors()
        ]
        return ValidateConfigResponse(valid=False, errors=errors, normalized_config=None)

    return ValidateConfigResponse(valid=True, errors=[], normalized_config=config)


@router.post("/config/models/discover", response_model=ModelDiscoverResponse)
async def config_model_discover(payload: ModelProfileRequest) -> ModelDiscoverResponse:
    api_key = (payload.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")
    try:
        return ModelDiscoverResponse(
            models=discover_models(payload.provider, api_key, payload.base_url_override)
        )
    except Exception as exc:
        message = str(exc) or "model discovery failed"
        lowered = message.lower()
        status_code = 401 if "api key" in lowered or "authentication" in lowered else 502
        raise HTTPException(status_code=status_code, detail=message)


@router.post("/config/models/profile", response_model=ModelProfileResponse)
async def config_model_profile(payload: ModelProfileRequest) -> ModelProfileResponse:
    model = (payload.model or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    return ModelProfileResponse(model=resolve_model_profile(payload.provider, model).to_schema())


@router.post("/chat", response_model=ChatResponse | PendingTurnContinueResponse)
async def chat(payload: ChatRequest) -> ChatResponse | PendingTurnContinueResponse:
    try:
        return await run_main_turn_once(payload)
    except MissingAPIKeyError:
        raise HTTPException(status_code=401, detail="api_key is not configured in config")
    except ValueError as exc:
        if str(exc) == "PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER":
            raise HTTPException(status_code=409, detail=str(exc))
        raise
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/chat/stream")
async def chat_sse(request: Request, payload: ChatRequest) -> StreamingResponse:
    if not payload.config.stream:
        raise HTTPException(status_code=400, detail="config.stream must be true")

    async def event_gen():
        queue: asyncio.Queue[tuple[str | None, dict | None]] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def worker() -> None:
            try:
                result = await run_main_turn_stream(
                    payload,
                    emit=emit,
                    is_cancelled=request.is_disconnected,
                )
                if not isinstance(result, PendingTurnContinueResponse):
                    await queue.put(
                        (
                            "end",
                            {
                                "usage": result.usage.model_dump(mode="json"),
                                "tool_events": [item.model_dump(mode="json") for item in result.tool_events],
                                "scene_events": [item.model_dump(mode="json") for item in result.scene_events],
                                "time_spent_min": result.time_spent_min,
                                "archived_sub_zone_turn_id": result.archived_sub_zone_turn_id,
                                "main_turn_summary": (
                                    result.main_turn_summary.model_dump(mode="json") if result.main_turn_summary is not None else None
                                ),
                            },
                        )
                    )
            except StreamCancelledError:
                pass
            except MissingAPIKeyError:
                await queue.put(("error", {"code": 401, "message": "api_key is not configured in config"}))
            except ValueError as exc:
                code = 409 if str(exc) == "PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER" else 400
                await queue.put(("error", {"code": code, "message": str(exc)}))
            except RateLimitError as exc:
                await queue.put(("error", {"code": 429, "message": str(exc)}))
            except APIError as exc:
                await queue.put(("error", {"code": 502, "message": str(exc)}))
            except Exception as exc:
                await queue.put(("error", {"code": 500, "message": str(exc)}))
            finally:
                await queue.put((None, None))

        task = asyncio.create_task(worker())
        yield _sse_frame("start", {"session_id": payload.session_id})
        try:
            while True:
                event, data = await queue.get()
                if event is None:
                    break
                yield _sse_frame(event, data or {})
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/chat/pending/continue", response_model=PendingTurnContinueResponse)
async def chat_pending_continue(payload: PendingTurnContinueRequest) -> PendingTurnContinueResponse:
    try:
        return await run_pending_turn_once(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/chat/pending/continue/stream")
async def chat_pending_continue_stream(request: Request, payload: PendingTurnContinueRequest) -> StreamingResponse:
    async def event_gen():
        queue: asyncio.Queue[tuple[str | None, dict | None]] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def worker() -> None:
            try:
                result = await run_pending_turn_stream(
                    payload,
                    emit=emit,
                    is_cancelled=request.is_disconnected,
                )
                if result.status == "awaiting_reaction":
                    await queue.put(
                        (
                            "reaction_check_required",
                            {
                                "pending_turn_id": result.pending_turn_id,
                                "flow_kind": result.flow_kind,
                                "reply_so_far": result.reply_text,
                                "scene_events_so_far": [item.model_dump(mode="json") for item in result.scene_events],
                                "pending_reaction": (
                                    result.pending_reaction.model_dump(mode="json") if result.pending_reaction is not None else None
                                ),
                                "npc_role_id": result.npc_role_id,
                            },
                        )
                    )
                elif result.flow_kind == "main_chat":
                    await queue.put(
                        (
                            "end",
                            {
                                "tool_events": [item.model_dump(mode="json") for item in result.tool_events],
                                "scene_events": [item.model_dump(mode="json") for item in result.scene_events],
                                "time_spent_min": 0,
                                "archived_sub_zone_turn_id": result.archived_sub_zone_turn_id,
                                "main_turn_summary": (
                                    result.main_turn_summary.model_dump(mode="json") if result.main_turn_summary is not None else None
                                ),
                            },
                        )
                    )
                else:
                    await queue.put(
                        (
                            "end",
                            {
                                "time_spent_min": 0,
                                "dialogue_logs": [],
                                "scene_events": [item.model_dump(mode="json") for item in result.scene_events],
                            },
                        )
                    )
            except StreamCancelledError:
                pass
            except KeyError:
                await queue.put(("error", {"code": 404, "message": "role not found"}))
            except ValueError as exc:
                await queue.put(("error", {"code": 409, "message": str(exc)}))
            except RateLimitError as exc:
                await queue.put(("error", {"code": 429, "message": str(exc)}))
            except APIError as exc:
                await queue.put(("error", {"code": 502, "message": str(exc)}))
            except Exception as exc:
                await queue.put(("error", {"code": 500, "message": str(exc)}))
            finally:
                await queue.put((None, None))

        task = asyncio.create_task(worker())
        yield _sse_frame("start", {"session_id": payload.session_id, "pending_turn_id": payload.pending_turn_id})
        try:
            while True:
                event, data = await queue.get()
                if event is None:
                    break
                yield _sse_frame(event, data or {})
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/pending-turns/{pending_turn_id}/cancel", response_model=PendingTurnContinueResponse)
async def pending_turn_cancel(pending_turn_id: str, session_id: str) -> PendingTurnContinueResponse:
    state = cancel_pending_turn(session_id, pending_turn_id)
    if state is None:
        raise HTTPException(status_code=404, detail="pending turn not found")
    return PendingTurnContinueResponse(
        session_id=session_id,
        pending_turn_id=None,
        flow_kind=state.flow_kind,
        status="cancelled",
        reply_text="",
        scene_events=[],
        tool_events=[],
        pending_reaction=None,
        npc_role_id=state.npc_role_id,
    )


@router.get("/pending-turns/current", response_model=PendingTurnContinueResponse | None)
async def pending_turn_current(session_id: str) -> PendingTurnContinueResponse | None:
    state = load_pending_turn(session_id)
    if state is None:
        return None
    return PendingTurnContinueResponse(
        session_id=state.session_id,
        pending_turn_id=state.pending_turn_id,
        flow_kind=state.flow_kind,
        status="awaiting_reaction",
        reply_text=state.accumulated_reply_text,
        scene_events=state.accumulated_scene_events,
        tool_events=state.accumulated_tool_events,
        main_turn_summary=None,
        current_zone_metric=None,
        pending_reaction=state.pending_reaction,
        npc_role_id=state.npc_role_id,
    )


@router.post("/battle/debug/start", response_model=BattleStartResponse)
async def battle_debug_start(payload: BattleStartRequest) -> BattleStartResponse:
    return start_debug_battle(payload)


@router.get("/battle/debug/current", response_model=BattleCurrentResponse)
async def battle_debug_current(session_id: str) -> BattleCurrentResponse:
    return get_current_debug_battle(session_id)


@router.post("/battle/{battle_id}/player-action", response_model=BattleActionResponse)
async def battle_player_action(battle_id: str, payload: BattleActionRequest) -> BattleActionResponse:
    battle = handle_player_battle_action(
        payload.session_id,
        battle_id,
        action_kind=payload.action_kind,
        target_combatant_id=payload.target_combatant_id,
        destination_band=payload.destination_band,
        item_id=payload.item_id,
    )
    return BattleActionResponse(session_id=payload.session_id, battle=battle)


@router.post("/battle/{battle_id}/continue-ai", response_model=BattleContinueAiResponse)
async def battle_continue_ai(battle_id: str, payload: BattleContinueAiRequest) -> BattleContinueAiResponse:
    battle = handle_continue_battle_ai(payload.session_id, battle_id, ai_pacing=payload.ai_pacing)
    return BattleContinueAiResponse(session_id=payload.session_id, battle=battle)


@router.post("/battle/{battle_id}/resolve-roll", response_model=BattleResolveRollResponse)
async def battle_resolve_roll(battle_id: str, payload: BattleResolveRollRequest) -> BattleResolveRollResponse:
    battle, result = handle_resolve_battle_roll(payload.session_id, battle_id, forced_dice_roll=payload.forced_dice_roll)
    return BattleResolveRollResponse(session_id=payload.session_id, battle=battle, roll_result=result)


@router.post("/battle/{battle_id}/end", response_model=BattleEndResponse)
async def battle_end(battle_id: str, payload: BattleContinueAiRequest) -> BattleEndResponse:
    return end_debug_battle(payload.session_id, battle_id)


def _require_user() -> str:
    user = get_current_user()
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


@router.get("/storage/config/path", response_model=PathStatusResponse)
async def get_config_path() -> PathStatusResponse:
    _require_user()
    return storage_state.path_status(storage_state.config_path)


@router.post("/storage/config/path", response_model=PathStatusResponse)
async def set_config_path(payload: PathConfig) -> PathStatusResponse:
    _require_user()
    raise HTTPException(status_code=403, detail="多用户模式下禁止自定义配置路径")


@router.post("/storage/config/path/pick", response_model=PathStatusResponse)
async def pick_config_path() -> PathStatusResponse:
    _require_user()
    raise HTTPException(status_code=403, detail="多用户模式下禁止选择本地目录")


@router.get("/storage/config")
async def get_config_data() -> dict:
    _require_user()
    path = storage_state.config_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="config file not found")
    data = read_json(path)
    try:
        return ChatConfig.model_validate(data).model_dump(mode="json")
    except ValidationError:
        return data


@router.post("/storage/config")
async def set_config_data(payload: dict) -> dict:
    _require_user()
    try:
        cfg = ChatConfig.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    write_json_atomic(storage_state.config_path, cfg.model_dump(mode="json"))
    return {"ok": True, "path": str(storage_state.config_path)}


@router.get("/saves/path", response_model=PathStatusResponse)
async def get_save_path() -> PathStatusResponse:
    _require_user()
    return storage_state.path_status(storage_state.save_path)


@router.post("/saves/path", response_model=PathStatusResponse)
async def set_save_path(payload: PathConfig) -> PathStatusResponse:
    _require_user()
    raise HTTPException(status_code=403, detail="多用户模式下禁止自定义存档路径")


@router.post("/saves/path/pick", response_model=PathStatusResponse)
async def pick_save_path() -> PathStatusResponse:
    _require_user()
    raise HTTPException(status_code=403, detail="多用户模式下禁止选择本地目录")


@router.get("/saves/current", response_model=SaveFile)
async def get_save_current() -> SaveFile:
    _require_user()
    return get_current_save()


@router.post("/saves/current", response_model=SaveFile)
async def set_save_current(payload: SaveSetRequest) -> SaveFile:
    _require_user()
    save = SaveFile.model_validate(payload.save_data)
    save_current(save)
    return save


@router.post("/saves/import", response_model=SaveFile)
async def import_save_file(payload: SaveImportRequest) -> SaveFile:
    _require_user()
    save = SaveFile.model_validate(payload.save_data)
    return import_save(save)


@router.post("/saves/clear", response_model=SaveFile)
async def clear_save(payload: SaveClearRequest) -> SaveFile:
    _require_user()
    return clear_current_save(payload.session_id)


@router.post("/world-map/regions/generate", response_model=RegionGenerateResponse)
async def world_map_generate(payload: RegionGenerateRequest) -> RegionGenerateResponse:
    try:
        return generate_regions(payload)
    except AIRegionGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"地图区块 AI 生成失败: {exc}")


@router.post("/world-map/bootstrap", response_model=MapBootstrapResponse)
async def world_map_bootstrap(payload: RegionGenerateRequest) -> MapBootstrapResponse:
    try:
        return await bootstrap_world_map(payload)
    except AIRegionGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"地图区块 AI 生成失败: {exc}")


@router.post("/world-map/render", response_model=RenderMapResponse)
async def world_map_render(payload: RenderMapRequest) -> RenderMapResponse:
    return render_map(payload)


@router.post("/world-map/move", response_model=MoveResolvedResponse)
async def world_map_move(payload: MoveRequest) -> MoveResolvedResponse:
    try:
        return await move_world_map(payload)
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


@router.get("/reputation/current", response_model=ReputationStateResponse)
async def reputation_current(session_id: str, sub_zone_id: str | None = None) -> ReputationStateResponse:
    return get_area_reputation(session_id, sub_zone_id=sub_zone_id)


@router.get("/role-drives", response_model=RoleDrivesResponse)
async def role_drives(session_id: str, scope: str = "current_sub_zone", role_id: str | None = None) -> RoleDrivesResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    normalized_scope = scope if scope in {"role", "team", "current_sub_zone"} else "current_sub_zone"
    return RoleDrivesResponse(
        session_id=session_id,
        scope=normalized_scope,  # type: ignore[arg-type]
        items=build_role_drive_summaries(
            save,
            scope=("current_sub_zone" if normalized_scope == "role" and role_id is None else normalized_scope),
            role_id=role_id,
        ),
    )


@router.get("/scene/public-state", response_model=PublicSceneStateResponse)
async def public_scene_state(session_id: str) -> PublicSceneStateResponse:
    return get_public_scene_state(session_id)


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


@router.post("/inventory/grant", response_model=InventoryMutationResponse)
async def inventory_grant_item(payload: InventoryGrantRequest) -> InventoryMutationResponse:
    try:
        return inventory_grant(payload)
    except KeyError as exc:
        code = str(exc)
        if "ROLE_NOT_FOUND" in code:
            raise HTTPException(status_code=404, detail="role not found")
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/inventory/consume", response_model=InventoryMutationResponse)
async def inventory_consume_item(payload: InventoryConsumeRequest) -> InventoryMutationResponse:
    try:
        return inventory_consume(payload)
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


@router.post("/npc/chat", response_model=NpcChatResponse | PendingTurnContinueResponse)
async def npc_chat_run(payload: NpcChatRequest) -> NpcChatResponse | PendingTurnContinueResponse:
    try:
        return await run_npc_chat_once(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    except NpcChatConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except NpcChatGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


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


# Retained NPC endpoints
@router.get("/team/retained")
async def team_retained_list() -> dict:
    """Get all retained NPCs for the current user."""
    _require_user()
    npcs = retained_npc_service.get_all()
    return {
        "npcs": [
            {
                "retained_id": npc.retained_id,
                "name": npc.name,
                "retained_at": npc.retained_at,
                "notes": npc.notes,
            }
            for npc in npcs
        ]
    }


@router.post("/team/retain")
async def team_retain_npc(payload: dict) -> dict:
    """Retain an NPC from the current team."""
    _require_user()
    role_id = payload.get("role_id")
    notes = payload.get("notes", "")
    session_id = payload.get("session_id")
    
    if not role_id or not session_id:
        raise HTTPException(status_code=400, detail="role_id and session_id are required")
    
    # Get the role from the save
    save = get_current_save(default_session_id=session_id)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if not role:
        raise HTTPException(status_code=404, detail="role not found in current save")
    
    retained = retained_npc_service.retain_npc(role, notes)
    return {
        "ok": True,
        "retained_id": retained.retained_id,
        "name": retained.name,
        "message": f"{retained.name} 已被保留到账户中。",
    }


@router.post("/team/retained/{retained_id}/generate")
async def team_generate_from_retained(retained_id: str, payload: dict) -> TeamMutationResponse:
    """Generate a teammate from a retained NPC."""
    _require_user()
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    retained = retained_npc_service.get_by_id(retained_id)
    if not retained:
        raise HTTPException(status_code=404, detail="retained NPC not found")
    
    # Import the function to generate from spec
    from app.services.team_service import generate_team_role_from_prompt, ensure_team_state, sync_team_members_with_player_in_save, save_current
    from app.models.schemas import TeamMember
    
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    state = ensure_team_state(save)
    
    # Create role from retained data
    role_data = retained.role_data.copy()
    role_data["role_id"] = f"debug_team_{int(__import__('time').time() * 1000)}"
    role = NpcRoleCard.model_validate(role_data)
    save.role_pool.append(role)
    
    member = TeamMember(
        role_id=role.role_id,
        name=role.name,
        origin_zone_id=None,
        origin_sub_zone_id=None,
        affinity=85,
        trust=75,
        join_source="debug",
        join_reason=f"从保留的队友生成 (原: {retained.name})",
        is_debug=True,
        debug_prompt=f"retained:{retained.retained_id}",
    )
    state.members.append(member)
    sync_team_members_with_player_in_save(save)
    save_current(save)
    
    return TeamMutationResponse(
        session_id=session_id,
        team_state=state,
        member=member,
        role=role,
        accepted=True,
        chat_feedback=f"{role.name} 已从保留的队友生成并加入队伍。",
    )


@router.delete("/team/retained/{retained_id}")
async def team_delete_retained(retained_id: str) -> dict:
    """Delete a retained NPC."""
    _require_user()
    deleted = retained_npc_service.delete_retained(retained_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="retained NPC not found")
    return {"ok": True, "message": "保留的队友已删除。"}


@router.post("/npc/chat/stream")
async def npc_chat_stream(request: Request, payload: NpcChatRequest) -> StreamingResponse:
    if payload.config is not None and not payload.config.stream:
        raise HTTPException(status_code=400, detail="config.stream must be true")

    async def event_gen():
        queue: asyncio.Queue[tuple[str | None, dict | None]] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def worker() -> None:
            try:
                result = await run_npc_chat_stream(
                    payload,
                    emit=emit,
                    is_cancelled=request.is_disconnected,
                )
                if not isinstance(result, PendingTurnContinueResponse):
                    await queue.put(
                        (
                            "end",
                            {
                                "time_spent_min": result.time_spent_min,
                                "dialogue_logs": [item.model_dump(mode="json") for item in result.dialogue_logs],
                                "scene_events": [item.model_dump(mode="json") for item in result.scene_events],
                            },
                        )
                    )
            except StreamCancelledError:
                pass
            except KeyError:
                await queue.put(("error", {"code": 404, "message": "role not found"}))
            except NpcChatConfigError as exc:
                await queue.put(("error", {"code": 400, "message": str(exc)}))
            except NpcChatGenerationError as exc:
                await queue.put(("error", {"code": 502, "message": str(exc)}))
            except Exception as exc:
                await queue.put(("error", {"code": 500, "message": str(exc)}))
            finally:
                await queue.put((None, None))

        task = asyncio.create_task(worker())
        yield _sse_frame("start", {"session_id": payload.session_id, "npc_role_id": payload.npc_role_id})
        try:
            while True:
                event, data = await queue.get()
                if event is None:
                    break
                yield _sse_frame(event, data or {})
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/world/clock/init", response_model=WorldClockInitResponse)
async def world_clock_init(payload: WorldClockInitRequest) -> WorldClockInitResponse:
    return init_world_clock(payload)


@router.get("/world/area/current", response_model=AreaCurrentResponse)
async def world_area_current(session_id: str) -> AreaCurrentResponse:
    return get_area_current(session_id)


@router.post("/world/area/move-sub-zone", response_model=AreaMoveResolvedResponse)
async def world_area_move_sub_zone(payload: AreaMoveSubZoneRequest) -> AreaMoveResolvedResponse:
    try:
        return await move_world_sub_zone(payload)
    except KeyError as exc:
        if str(exc) == "'AREA_SUB_ZONE_NOT_FOUND'":
            raise HTTPException(status_code=404, detail="sub zone not found")
        raise HTTPException(status_code=404, detail="target not found")
    except ValueError as exc:
        if str(exc) == "AREA_CLOCK_NOT_INIT":
            raise HTTPException(status_code=409, detail="clock not initialized")
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/world/area/interactions/discover", response_model=AreaDiscoverInteractionsResolvedResponse)
async def world_area_discover_interactions(payload: AreaDiscoverInteractionsRequest) -> AreaDiscoverInteractionsResolvedResponse:
    try:
        return await discover_area_interactions(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="sub zone not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/world/area/interactions/execute", response_model=AreaExecuteInteractionResolvedResponse)
async def world_area_execute_interaction(payload: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResolvedResponse:
    try:
        return await execute_area_interaction(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="interaction not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/debug/template-library/status", response_model=TemplateLibraryStatusResponse)
async def debug_template_library_status(session_id: str) -> TemplateLibraryStatusResponse:
    try:
        return get_template_library_status_response(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/debug/template-library/fill", response_model=TemplateLibraryFillResponse)
async def debug_template_library_fill(payload: TemplateLibraryFillRequest) -> TemplateLibraryFillResponse:
    try:
        return fill_template_library(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/actions/check/plan", response_model=ActionCheckPlanResponse)
async def action_check_plan_run(payload: ActionCheckPlanRequest) -> ActionCheckPlanResponse:
    try:
        return plan_action_check(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")


@router.post("/actions/check", response_model=ActionCheckResponse)
async def action_check_run(payload: ActionCheckRequest) -> ActionCheckResponse:
    try:
        if payload.return_state_sync:
            return await run_action_check_with_state_sync(payload)
        return action_check(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="role not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
