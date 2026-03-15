from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import re

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    AreaDiscoverInteractionsRequest,
    AreaDiscoverInteractionsResolvedResponse,
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResolvedResponse,
    AreaMoveResolvedResponse,
    AreaMoveSubZoneRequest,
    ChatConfig,
    EncounterCheckRequest,
    EncounterCheckResponse,
    FateEvaluateRequest,
    MapBootstrapResponse,
    MapNarrativePayload,
    MapPostChecksBundle,
    MapStateSyncBundle,
    MoveRequest,
    MoveResolvedResponse,
    Position,
    QuestEntry,
    QuestEvaluateAllRequest,
    RegionGenerateRequest,
    SaveFile,
    SubZoneReputationEntry,
)
from app.services import encounter_service, fate_service, quest_service, world_service as world
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.generation_debug_log_service import current_generation_debug_log, generation_debug_log
from app.services.session_lock_service import get_session_lock
from app.services import zone_metric_service


@dataclass
class MapOperationContext:
    session_id: str
    config: ChatConfig | None = None
    log_limit: int = 200


class MapOperationTransaction:
    def __init__(self, context: MapOperationContext) -> None:
        self.context = context
        self._manager: AbstractContextManager[world.SaveTransaction] | None = None
        self._txn: world.SaveTransaction | None = None

    @property
    def save(self) -> SaveFile:
        if self._txn is None:
            raise RuntimeError("MAP_TRANSACTION_NOT_OPEN")
        return self._txn.save

    def __enter__(self) -> "MapOperationTransaction":
        self._manager = world.save_transaction(self.context.session_id)
        self._txn = self._manager.__enter__()
        return self

    def commit(self) -> SaveFile:
        if self._txn is None:
            raise RuntimeError("MAP_TRANSACTION_NOT_OPEN")
        return self._txn.commit()

    def rollback(self) -> None:
        if self._txn is not None:
            self._txn.rollback()

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()
        if self._manager is not None:
            self._manager.__exit__(exc_type, exc, tb)


def _preview_text(value: str, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def _config_log_data(config: ChatConfig | None) -> dict[str, object]:
    if config is None:
        return {}
    runtime = config.runtime.model_dump(mode="json", exclude_none=True)
    return {
        "provider": config.provider,
        "model": config.model,
        "stream": config.stream,
        "runtime": runtime,
        "gm_prompt_length": len(config.gm_prompt or ""),
    }


def _record_map_debug(stage: str, message: str, data: object | None = None) -> None:
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record(stage, message, data)


def _state_sync_summary(bundle: MapStateSyncBundle) -> dict[str, object]:
    return {
        "zone_count": len(bundle.map_snapshot.zones),
        "current_zone_id": bundle.area_snapshot.current_zone_id,
        "current_sub_zone_id": bundle.area_snapshot.current_sub_zone_id,
        "role_pool_count": len(bundle.role_pool),
        "game_log_count": len(bundle.game_logs),
        "pending_offer_count": len(bundle.pending_offers),
        "pending_encounter_count": len(bundle.pending_encounters),
    }


def execute_public_zone_move_turn_in_save(
    save: SaveFile,
    *,
    session_id: str,
    payload: MoveRequest,
    config: ChatConfig | None,
    log_limit: int = 200,
) -> MoveResolvedResponse:
    moved = world.move_to_zone_in_save(payload)
    _record_map_debug(
        "map_move",
        "zone move applied",
        {"from_zone_id": payload.from_zone_id, "to_zone_id": moved.new_position.zone_id, "duration_min": moved.duration_min},
    )
    narration = MapNarrativePayload(text=moved.movement_log.summary, source="deterministic")
    post_checks = run_post_map_transition_checks_in_save(
        save,
        session_id=session_id,
        trigger_kind="random_move",
        config=config,
    )
    state_sync = build_map_state_sync_bundle(
        save,
        session_id=session_id,
        config=config,
        log_limit=log_limit,
    )
    scene_events = []
    if post_checks.encounter_generated and state_sync.active_encounter is not None:
        scene_events.append(
            world._new_scene_event(
                "encounter_started",
                f"【遭遇触发】{state_sync.active_encounter.title}\n{state_sync.active_encounter.description}",
                metadata={
                    "encounter_id": state_sync.active_encounter.encounter_id,
                    "encounter_title": state_sync.active_encounter.title,
                },
            )
        )
    return MoveResolvedResponse(
        session_id=moved.session_id,
        new_position=moved.new_position,
        duration_min=moved.duration_min,
        movement_log=moved.movement_log,
        narration=narration,
        post_checks=post_checks,
        state_sync=state_sync,
        scene_events=scene_events,
        current_zone_metric=state_sync.current_zone_metric,
    )


def _player_position(save: SaveFile) -> Position:
    return save.map_snapshot.player_position or save.player_runtime_data.current_position or Position(x=0, y=0, z=0, zone_id="zone_0_0_0")


def _current_reputation(save: SaveFile) -> SubZoneReputationEntry | None:
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    if not sub_zone_id:
        return None
    for entry in save.reputation_state.entries:
        if entry.sub_zone_id == sub_zone_id:
            return entry
    return None


def _pending_offers(save: SaveFile) -> list[QuestEntry]:
    return [quest for quest in save.quest_state.quests if quest.status == "pending_offer"]


def _tracked_quest(save: SaveFile) -> QuestEntry | None:
    tracked_id = save.quest_state.tracked_quest_id
    if tracked_id:
        for quest in save.quest_state.quests:
            if quest.quest_id == tracked_id:
                return quest
    for quest in save.quest_state.quests:
        if quest.status == "active" and quest.is_tracked:
            return quest
    return None


def _pending_encounters(save: SaveFile):
    pending_ids = set(save.encounter_state.pending_ids or [])
    return [encounter for encounter in save.encounter_state.encounters if encounter.encounter_id in pending_ids]


def _active_encounter(save: SaveFile):
    active_id = save.encounter_state.active_encounter_id
    if not active_id:
        return None
    return next((encounter for encounter in save.encounter_state.encounters if encounter.encounter_id == active_id), None)


def build_map_state_sync_bundle(
    save: SaveFile,
    *,
    session_id: str | None = None,
    config: ChatConfig | None = None,
    log_limit: int = 200,
) -> MapStateSyncBundle:
    player_position = _player_position(save)
    zone_metric_map = {}
    zone_ids = {zone.zone_id for zone in save.map_snapshot.zones}
    if zone_ids:
        if session_id is not None:
            zone_metric_service.ensure_zone_metrics_for_zones(
                save,
                session_id=session_id,
                zone_ids=zone_ids,
                config=config,
            )
        zone_metric_state = zone_metric_service.ensure_zone_metric_state(save)
        zone_metric_map = {entry.zone_id: entry for entry in zone_metric_state.entries}
    else:
        zone_metric_state = zone_metric_service.ensure_zone_metric_state(save)
    render = world.render_map_payload(
        zones=save.map_snapshot.zones,
        player_position=player_position,
        zone_metrics=zone_metric_map,
    )
    logs = list(save.game_logs[-max(1, log_limit) :])
    current_zone_metric = zone_metric_service.get_current_zone_metric(save, create=bool(session_id))
    bundle = MapStateSyncBundle(
        map_snapshot=save.map_snapshot.model_copy(deep=True),
        area_snapshot=save.area_snapshot.model_copy(deep=True),
        render=render,
        world_state=save.world_state.model_copy(deep=True),
        player_static_data=save.player_static_data.model_copy(deep=True),
        player_runtime_data=save.player_runtime_data.model_copy(deep=True),
        role_pool=[role.model_copy(deep=True) for role in save.role_pool],
        current_reputation=(_current_reputation(save).model_copy(deep=True) if _current_reputation(save) is not None else None),
        current_zone_metric=(current_zone_metric.model_copy(deep=True) if current_zone_metric is not None else None),
        zone_metric_state=zone_metric_state.model_copy(deep=True),
        quest_state=save.quest_state.model_copy(deep=True),
        pending_offers=[quest.model_copy(deep=True) for quest in _pending_offers(save)],
        tracked_quest=(_tracked_quest(save).model_copy(deep=True) if _tracked_quest(save) is not None else None),
        encounter_state=save.encounter_state.model_copy(deep=True),
        pending_encounters=[encounter.model_copy(deep=True) for encounter in _pending_encounters(save)],
        active_encounter=(_active_encounter(save).model_copy(deep=True) if _active_encounter(save) is not None else None),
        fate_state=save.fate_state.model_copy(deep=True),
        team_state=save.team_state.model_copy(deep=True),
        team_members=[member.model_copy(deep=True) for member in save.team_state.members],
        game_logs=[item.model_copy(deep=True) for item in logs],
    )
    _record_map_debug("state_sync", "built map state sync bundle", _state_sync_summary(bundle))
    return bundle


def run_post_map_transition_checks_in_save(
    save: SaveFile,
    *,
    session_id: str,
    trigger_kind: str | None,
    config: ChatConfig | None,
) -> MapPostChecksBundle:
    try:
        quest_service.evaluate_all_quests(QuestEvaluateAllRequest(session_id=session_id, config=config))
        fate_service.evaluate_fate_state(FateEvaluateRequest(session_id=session_id, config=config))
        encounter_response = EncounterCheckResponse()
        encounter_checked = False
        if trigger_kind is not None:
            encounter_checked = True
            encounter_response = encounter_service.check_for_encounter(
                EncounterCheckRequest(session_id=session_id, trigger_kind=trigger_kind, config=config)
            )
        bundle = MapPostChecksBundle(
            trigger_kind=trigger_kind,  # type: ignore[arg-type]
            quests_evaluated=True,
            fate_evaluated=True,
            encounter_checked=encounter_checked,
            encounter_generated=bool(encounter_response.generated),
            generated_encounter_id=encounter_response.encounter_id,
            blocked_by_higher_priority_modal=bool(encounter_response.blocked_by_higher_priority_modal),
        )
        _record_map_debug("post_checks", "map post checks completed", bundle)
        return bundle
    except Exception as exc:
        _record_map_debug("post_checks_error", str(exc), {"trigger_kind": trigger_kind})
        raise


def _generate_sub_zone_move_reply(
    *,
    session_id: str,
    config: ChatConfig,
    fallback_text: str,
    from_name: str,
    to_name: str,
    from_id: str,
    to_id: str,
    distance_m: float,
    duration_min: int,
) -> MapNarrativePayload:
    _record_map_debug(
        "map_narration_start",
        "generating sub-zone movement narration",
        {
            "kind": "sub_zone_move",
            "from_name": from_name,
            "to_name": to_name,
            "from_id": from_id,
            "to_id": to_id,
            "distance_m": distance_m,
            "duration_min": duration_min,
        },
    )
    client = create_sync_client(config, client_cls=OpenAI)
    default_prompt = (
        "你是跑团GM。基于以下子区块移动结果写一段50-120字叙事。"
        "不要编号，不要选项。"
        "from_name=$from_name, from_id=$from_id, to_name=$to_name, to_id=$to_id, "
        "distance_m=$distance_m, duration_min=$duration_min"
    )
    prompt = prompt_table.render(
        "move.subzone.user",
        default_prompt,
        from_name=from_name or "上一处地点",
        from_id=from_id or from_name or "current_sub_zone",
        to_name=to_name,
        to_id=to_id or to_name or "target_sub_zone",
        distance_m=round(distance_m, 2),
        duration_min=duration_min,
    )
    resp = client.chat.completions.create(
        model=config.model,
        **build_completion_options(config),
        messages=[
            {"role": "system", "content": config.gm_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    if content and not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", content):
        _record_map_debug("map_narration", "sub-zone narration generated", {"source": "ai", "text_preview": _preview_text(content)})
        return MapNarrativePayload(text=content, source="ai")
    if content:
        _record_map_debug(
            "map_narration_fallback",
            "sub-zone narration leaked template tokens; using fallback",
            {"source": "deterministic", "model_output_preview": _preview_text(content)},
        )
    return MapNarrativePayload(text=fallback_text, source=("deterministic" if fallback_text else "none"))


def generate_map_reply_once(
    *,
    session_id: str,
    config: ChatConfig | None,
    kind: str,
    fallback_text: str,
    movement_log=None,
    from_name: str = "",
    to_name: str = "",
    from_id: str = "",
    to_id: str = "",
    distance_m: float = 0.0,
    duration_min: int = 0,
) -> MapNarrativePayload:
    text = fallback_text.strip()
    if config is None:
        _record_map_debug("map_narration_fallback", "no config; using deterministic narration", {"kind": kind, "text_preview": _preview_text(text)})
        return MapNarrativePayload(text=text, source=("deterministic" if text else "none"))

    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        _record_map_debug(
            "map_narration_fallback",
            "missing api key or model; using deterministic narration",
            {"kind": kind, "text_preview": _preview_text(text)},
        )
        return MapNarrativePayload(text=text, source=("deterministic" if text else "none"))

    try:
        if kind == "zone_move" and movement_log is not None:
            response = world.describe_behavior(session_id, movement_log, config)
            if response.narration.strip():
                _record_map_debug(
                    "map_narration",
                    "zone movement narration generated",
                    {"source": "ai", "text_preview": _preview_text(response.narration.strip())},
                )
                return MapNarrativePayload(text=response.narration.strip(), source="ai")
            _record_map_debug(
                "map_narration_fallback",
                "zone movement narration empty; using deterministic fallback",
                {"kind": kind, "text_preview": _preview_text(text)},
            )
        elif kind == "sub_zone_move":
            return _generate_sub_zone_move_reply(
                session_id=session_id,
                config=config,
                fallback_text=text,
                from_name=from_name,
                to_name=to_name,
                from_id=from_id,
                to_id=to_id,
                distance_m=distance_m,
                duration_min=duration_min,
            )
            client = create_sync_client(config, client_cls=OpenAI)
            default_prompt = (
                "你是跑团GM。基于以下子区块移动结果写一段50-120字叙事。"
                "不要编号，不要选项。"
                "from_name=$from_name, to_name=$to_name, distance_m=$distance_m, duration_min=$duration_min"
            )
            prompt = prompt_table.render(
                "move.subzone.user",
                default_prompt,
                from_name=from_name or "上一处地点",
                to_name=to_name,
                distance_m=round(distance_m, 2),
                duration_min=duration_min,
            )
            resp = client.chat.completions.create(
                model=model,
                **build_completion_options(config),
                messages=[
                    {"role": "system", "content": config.gm_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            if content:
                return MapNarrativePayload(text=content, source="ai")
    except Exception as exc:
        _record_map_debug(
            "map_narration_error",
            str(exc),
            {"kind": kind, "text_preview": _preview_text(text), "from_name": from_name, "to_name": to_name},
        )
    return MapNarrativePayload(text=text, source=("deterministic" if text else "none"))


async def bootstrap_world_map(payload: RegionGenerateRequest) -> MapBootstrapResponse:
    with generation_debug_log(
        "map_bootstrap",
        payload.session_id,
        request_data={
            **_config_log_data(payload.config),
            "force_regenerate": payload.force_regenerate,
            "desired_count": payload.desired_count,
            "max_count": payload.max_count,
            "player_position": payload.player_position,
        },
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id, config=payload.config)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                save = world.get_current_save(default_session_id=payload.session_id)
                generated = False
                if payload.force_regenerate or not save.map_snapshot.zones:
                    _record_map_debug("map_bootstrap", "generating regions", {"existing_zone_count": len(save.map_snapshot.zones)})
                    response = world.generate_regions_in_save(payload)
                    generated = response.generated
                else:
                    save.session_id = payload.session_id
                    if save.map_snapshot.player_position is None:
                        save.map_snapshot.player_position = payload.player_position
                        save.player_runtime_data.current_position = payload.player_position
                        world.save_current(save)
                current = world.get_current_save(default_session_id=payload.session_id)
                state_sync = build_map_state_sync_bundle(
                    current,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                narration_text = f"地图区块已准备完成，共 {len(state_sync.map_snapshot.zones)} 个区块。" if generated else "地图已就绪。"
                result = MapBootstrapResponse(
                    generated=generated,
                    narration=MapNarrativePayload(text=narration_text, source="deterministic"),
                    state_sync=state_sync,
                )
                debug_log.finish(
                    status="success",
                    result={"generated": generated, "narration": result.narration, "state_sync": _state_sync_summary(state_sync)},
                )
                return result
            narration_text = f"地图区块已准备完成，共 {len(state_sync.map_snapshot.zones)} 个区块。" if generated else "地图已就绪。"
            return MapBootstrapResponse(
                generated=generated,
                narration=MapNarrativePayload(text=narration_text, source="deterministic"),
                state_sync=state_sync,
            )


async def move_world_map(payload: MoveRequest) -> MoveResolvedResponse:
    with generation_debug_log(
        "map_move_zone",
        payload.session_id,
        request_data={
            **_config_log_data(payload.config),
            "from_zone_id": payload.from_zone_id,
            "to_zone_id": payload.to_zone_id,
            "player_name": payload.player_name,
        },
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id, config=payload.config)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                result = execute_public_zone_move_turn_in_save(
                    txn.save,
                    session_id=payload.session_id,
                    payload=payload,
                    config=payload.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                debug_log.finish(
                    status="success",
                    result={
                        "new_zone_id": result.new_position.zone_id,
                        "duration_min": result.duration_min,
                        "narration": result.narration,
                        "post_checks": result.post_checks,
                        "state_sync": _state_sync_summary(result.state_sync),
                    },
                )
                return result
                state_sync = build_map_state_sync_bundle(
                    txn.save,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                scene_events = []
                if post_checks.encounter_generated and state_sync.active_encounter is not None:
                    scene_events.append(
                        world._new_scene_event(
                            "encounter_started",
                            f"【遭遇触发】{state_sync.active_encounter.title}\n{state_sync.active_encounter.description}",
                            metadata={
                                "encounter_id": state_sync.active_encounter.encounter_id,
                                "encounter_title": state_sync.active_encounter.title,
                            },
                        )
                    )
                txn.commit()
                result = MoveResolvedResponse(
                    session_id=moved.session_id,
                    new_position=moved.new_position,
                    duration_min=moved.duration_min,
                    movement_log=moved.movement_log,
                    narration=narration,
                    post_checks=post_checks,
                    state_sync=state_sync,
                    scene_events=scene_events,
                    current_zone_metric=state_sync.current_zone_metric,
                )
                debug_log.finish(
                    status="success",
                    result={
                        "new_zone_id": result.new_position.zone_id,
                        "duration_min": result.duration_min,
                        "narration": result.narration,
                        "post_checks": result.post_checks,
                        "state_sync": _state_sync_summary(state_sync),
                    },
                )
                return result


async def move_world_sub_zone(payload: AreaMoveSubZoneRequest) -> AreaMoveResolvedResponse:
    with generation_debug_log(
        "map_move_sub_zone",
        payload.session_id,
        request_data={**_config_log_data(payload.config), "to_sub_zone_id": payload.to_sub_zone_id},
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id, config=payload.config)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                moved = world.move_to_sub_zone_in_save(payload)
                from_name = next(
                    (item.name for item in txn.save.area_snapshot.sub_zones if item.sub_zone_id == moved.from_point.sub_zone_id),
                    moved.from_point.sub_zone_id or moved.from_point.zone_id,
                )
                to_name = next(
                    (item.name for item in txn.save.area_snapshot.sub_zones if item.sub_zone_id == moved.to_point.sub_zone_id),
                    moved.to_point.sub_zone_id or moved.to_point.zone_id,
                )
                _record_map_debug(
                    "map_move",
                    "sub-zone move applied",
                    {
                        "from_sub_zone_id": moved.from_point.sub_zone_id,
                        "to_sub_zone_id": moved.to_point.sub_zone_id,
                        "distance_m": moved.distance_m,
                        "duration_min": moved.duration_min,
                    },
                )
                narration = generate_map_reply_once(
                    session_id=payload.session_id,
                    config=payload.config,
                    kind="sub_zone_move",
                    fallback_text=moved.movement_feedback,
                    from_name=from_name,
                    to_name=to_name,
                    from_id=moved.from_point.sub_zone_id or moved.from_point.zone_id,
                    to_id=moved.to_point.sub_zone_id or moved.to_point.zone_id,
                    distance_m=moved.distance_m,
                    duration_min=moved.duration_min,
                )
                post_checks = run_post_map_transition_checks_in_save(
                    txn.save,
                    session_id=payload.session_id,
                    trigger_kind="random_move",
                    config=payload.config,
                )
                state_sync = build_map_state_sync_bundle(
                    txn.save,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                result = AreaMoveResolvedResponse(
                    ok=moved.ok,
                    from_point=moved.from_point,
                    to_point=moved.to_point,
                    distance_m=moved.distance_m,
                    duration_min=moved.duration_min,
                    clock_delta_min=moved.clock_delta_min,
                    clock_after=moved.clock_after,
                    movement_feedback=narration.text or moved.movement_feedback,
                    narration=narration,
                    post_checks=post_checks,
                    state_sync=state_sync,
                )
                debug_log.finish(
                    status="success",
                    result={
                        "to_sub_zone_id": result.to_point.sub_zone_id,
                        "distance_m": result.distance_m,
                        "duration_min": result.duration_min,
                        "narration": result.narration,
                        "post_checks": result.post_checks,
                        "state_sync": _state_sync_summary(state_sync),
                    },
                )
                return result


async def discover_area_interactions(payload: AreaDiscoverInteractionsRequest) -> AreaDiscoverInteractionsResolvedResponse:
    with generation_debug_log(
        "map_discover_interactions",
        payload.session_id,
        request_data={**_config_log_data(payload.config), "sub_zone_id": payload.sub_zone_id, "intent_preview": _preview_text(payload.intent)},
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id, config=payload.config)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                discovered = world.discover_interactions_in_save(payload)
                _record_map_debug(
                    "map_interactions",
                    "discovered area interactions",
                    {"generated_mode": discovered.generated_mode, "new_interaction_count": len(discovered.new_interactions)},
                )
                state_sync = build_map_state_sync_bundle(
                    txn.save,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                result = AreaDiscoverInteractionsResolvedResponse(
                    ok=discovered.ok,
                    generated_mode=discovered.generated_mode,
                    new_interactions=discovered.new_interactions,
                    narration=MapNarrativePayload(
                        text=(f"发现 {len(discovered.new_interactions)} 个新交互。" if discovered.new_interactions else ""),
                        source=("deterministic" if discovered.new_interactions else "none"),
                    ),
                    state_sync=state_sync,
                )
                debug_log.finish(
                    status="success",
                    result={
                        "generated_mode": result.generated_mode,
                        "new_interaction_count": len(result.new_interactions),
                        "narration": result.narration,
                        "state_sync": _state_sync_summary(state_sync),
                    },
                )
                return result
            return AreaDiscoverInteractionsResolvedResponse(
                ok=discovered.ok,
                generated_mode=discovered.generated_mode,
                new_interactions=discovered.new_interactions,
                narration=MapNarrativePayload(
                    text=(f"发现 {len(discovered.new_interactions)} 个新交互。" if discovered.new_interactions else ""),
                    source=("deterministic" if discovered.new_interactions else "none"),
                ),
                state_sync=state_sync,
            )


async def execute_area_interaction(payload: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResolvedResponse:
    with generation_debug_log(
        "map_execute_interaction",
        payload.session_id,
        request_data={"interaction_id": payload.interaction_id},
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                executed = world.execute_interaction_in_save(payload)
                _record_map_debug(
                    "map_interactions",
                    "executed area interaction",
                    {"interaction_id": payload.interaction_id, "status": executed.status},
                )
                state_sync = build_map_state_sync_bundle(
                    txn.save,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                result = AreaExecuteInteractionResolvedResponse(
                    ok=executed.ok,
                    status=executed.status,
                    message=executed.message,
                    reply=executed.reply,
                    scene_events=executed.scene_events,
                    inventory_changes=executed.inventory_changes,
                    interactable_updates=executed.interactable_updates,
                    state_sync=state_sync,
                )
                debug_log.finish(
                    status="success",
                    result={"status": result.status, "message": _preview_text(result.message), "state_sync": _state_sync_summary(state_sync)},
                )
                return result


async def run_action_check_with_state_sync(payload: ActionCheckRequest) -> ActionCheckResponse:
    with generation_debug_log(
        "map_action_check",
        payload.session_id,
        request_data={
            **_config_log_data(payload.config),
            "action_type": payload.action_type,
            "action_prompt_preview": _preview_text(payload.action_prompt),
            "return_state_sync": payload.return_state_sync,
            "post_trigger_kind": payload.post_trigger_kind,
        },
    ) as debug_log:
        context = MapOperationContext(session_id=payload.session_id, config=payload.config)
        lock = get_session_lock(payload.session_id)
        async with lock:
            with MapOperationTransaction(context) as txn:
                result = world.action_check_in_save(payload)
                _record_map_debug(
                    "action_check",
                    "action check completed",
                    {"success": result.success, "critical": result.critical, "time_spent_min": result.time_spent_min},
                )
                post_checks = MapPostChecksBundle()
                if payload.post_trigger_kind is not None:
                    post_checks = run_post_map_transition_checks_in_save(
                        txn.save,
                        session_id=payload.session_id,
                        trigger_kind=payload.post_trigger_kind,
                        config=payload.config,
                    )
                state_sync = build_map_state_sync_bundle(
                    txn.save,
                    session_id=context.session_id,
                    config=context.config,
                    log_limit=context.log_limit,
                )
                txn.commit()
                resolved = result.model_copy(update={"state_sync": state_sync, "post_checks": post_checks})
                debug_log.finish(
                    status="success",
                    result={
                        "success": resolved.success,
                        "critical": resolved.critical,
                        "time_spent_min": resolved.time_spent_min,
                        "post_checks": resolved.post_checks,
                        "state_sync": _state_sync_summary(state_sync),
                    },
                )
                return resolved
