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
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResponse,
    ActionCheckRequest,
    ActionCheckResponse,
    AreaMoveResult,
    AreaMoveSubZoneRequest,
    BehaviorDescribeRequest,
    BehaviorDescribeResponse,
    ChatConfig,
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
    PlayerRuntimeData,
    PlayerStaticData,
    RegionGenerateRequest,
    RegionGenerateResponse,
    RolePoolListResponse,
    RoleRelationUpsertRequest,
    NpcRoleCard,
    RenderMapRequest,
    RenderMapResponse,
    SaveClearRequest,
    SaveFile,
    SaveImportRequest,
    SaveSetRequest,
    TokenUsageResponse,
    ValidateConfigResponse,
    ValidateError,
    WorldClockInitRequest,
    WorldClockInitResponse,
)
from app.services.chat_service import MissingAPIKeyError, chat_once
from app.services.world_service import (
    AIBehaviorError,
    AIRegionGenerationError,
    clear_current_save,
    describe_behavior,
    add_game_log,
    action_check,
    apply_speech_time,
    discover_interactions,
    execute_interaction,
    generate_regions,
    get_area_current,
    get_game_log_settings,
    get_game_logs,
    get_current_save,
    get_player_runtime,
    get_player_static,
    get_role_card,
    get_role_pool,
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
    init_world_clock,
    npc_greet,
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
    return ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        usage=usage,
        tool_events=tool_events,
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
        try:
            reply, usage, tool_events = await chat_once(payload)
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
        usage_data = json.dumps(
            {
                "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
                "tool_events": [ev.model_dump(mode="json") for ev in tool_events],
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


@router.get("/token-usage", response_model=TokenUsageResponse)
async def token_usage(session_id: str) -> TokenUsageResponse:
    return token_usage_store.get(session_id)


@router.get("/player/static", response_model=PlayerStaticData)
async def player_static_get(session_id: str) -> PlayerStaticData:
    return get_player_static(session_id)


@router.post("/player/static", response_model=PlayerStaticData)
async def player_static_set(session_id: str, payload: PlayerStaticData) -> PlayerStaticData:
    return set_player_static(session_id, payload)


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
