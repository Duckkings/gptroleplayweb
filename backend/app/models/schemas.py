from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class UIConfig(BaseModel):
    theme: str = Field(default="dark")


class ChatConfig(BaseModel):
    version: str = Field(default="1.0.0")
    openai_api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    stream: bool
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = Field(default=1200, gt=0)
    gm_prompt: str = Field(..., min_length=1)
    speech_time_per_50_tokens_min: int = Field(default=1, ge=1, le=30)
    ui: UIConfig | None = None


class ValidateError(BaseModel):
    field: str
    message: str


class ValidateConfigResponse(BaseModel):
    valid: bool
    errors: list[ValidateError]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig
    messages: list[Message] = Field(..., min_length=1)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ToolEvent(BaseModel):
    tool_name: str
    ok: bool
    summary: str
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    reply: Message
    usage: Usage
    tool_events: list[ToolEvent] = Field(default_factory=list)
    time_spent_min: int = 0


class HealthResponse(BaseModel):
    ok: bool
    time: str


class PathConfig(BaseModel):
    path: str = Field(..., min_length=1)


class PathStatusResponse(BaseModel):
    path: str
    exists: bool
    writable: bool


class Position(BaseModel):
    x: int
    y: int
    z: int = 0
    zone_id: str = Field(..., min_length=1)


class ZoneSubZoneSeed(BaseModel):
    name: str = Field(..., min_length=1)
    offset_x: int = 0
    offset_y: int = 0
    offset_z: int = 0
    description: str = Field(default="", min_length=0)


class Zone(BaseModel):
    zone_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    x: int
    y: int
    z: int = 0
    zone_type: str = Field(default="unknown", min_length=1)
    size: Literal["small", "medium", "large"] = "medium"
    radius_m: int = Field(default=120, ge=10, le=1000)
    description: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    sub_zones: list[ZoneSubZoneSeed] = Field(default_factory=list)


class Coord3D(BaseModel):
    x: float
    y: float
    z: float = 0


class WorldClock(BaseModel):
    calendar: str = Field(default="fantasy_default", min_length=1)
    year: int = 1024
    month: int = 1
    day: int = 1
    hour: int = 9
    minute: int = 0
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AreaInteraction(BaseModel):
    interaction_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: Literal["item", "npc", "scene"] = "item"
    status: Literal["ready", "disabled", "hidden"] = "ready"
    generated_mode: Literal["pre", "instant"] = "pre"
    placeholder: bool = True


class AreaNpc(BaseModel):
    npc_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    state: str = Field(default="idle", min_length=1)


class ZoneState(BaseModel):
    flags: list[str] = Field(default_factory=lambda: ["normal"])
    last_refresh_clock: str = Field(default="")


class SubZoneState(BaseModel):
    time_segment: str = Field(default="day")
    flags: list[str] = Field(default_factory=lambda: ["normal"])


class AreaSubZone(BaseModel):
    sub_zone_id: str = Field(..., min_length=1)
    zone_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    coord: Coord3D
    radius_m: int = Field(default=20, ge=1)
    description: str = Field(..., min_length=1)
    generated_mode: Literal["pre", "instant"] = "pre"
    key_interactions: list[AreaInteraction] = Field(default_factory=list)
    npcs: list[AreaNpc] = Field(default_factory=list)
    state: SubZoneState = Field(default_factory=SubZoneState)


class AreaZone(BaseModel):
    zone_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    zone_type: str = Field(default="unknown", min_length=1)
    size: Literal["small", "medium", "large"] = "medium"
    center: Coord3D
    radius_m: int = Field(default=120, ge=1)
    description: str = Field(default="", min_length=0)
    sub_zone_ids: list[str] = Field(default_factory=list)
    state: ZoneState = Field(default_factory=ZoneState)


class AreaSnapshot(BaseModel):
    version: str = Field(default="0.1.0")
    zones: list[AreaZone] = Field(default_factory=list)
    sub_zones: list[AreaSubZone] = Field(default_factory=list)
    current_zone_id: str | None = None
    current_sub_zone_id: str | None = None
    clock: WorldClock | None = None


class MapSnapshot(BaseModel):
    player_position: Position | None = None
    zones: list[Zone] = Field(default_factory=list)


class GameLogEntry(BaseModel):
    id: str
    session_id: str
    kind: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GameLogSettings(BaseModel):
    ai_fetch_limit: int = Field(default=10, ge=1, le=100)


class Dnd5eAbilityScores(BaseModel):
    strength: int = Field(default=10, ge=1, le=30)
    dexterity: int = Field(default=10, ge=1, le=30)
    constitution: int = Field(default=10, ge=1, le=30)
    intelligence: int = Field(default=10, ge=1, le=30)
    wisdom: int = Field(default=10, ge=1, le=30)
    charisma: int = Field(default=10, ge=1, le=30)


class Dnd5eHitPoints(BaseModel):
    current: int = Field(default=10, ge=0)
    maximum: int = Field(default=10, ge=1)
    temporary: int = Field(default=0, ge=0)


class Dnd5eCharacterSheet(BaseModel):
    level: int = Field(default=1, ge=1, le=20)
    race: str = Field(default="", min_length=0)
    char_class: str = Field(default="", min_length=0)
    background: str = Field(default="", min_length=0)
    alignment: str = Field(default="", min_length=0)
    proficiency_bonus: int = Field(default=2)
    armor_class: int = Field(default=10, ge=0)
    speed_ft: int = Field(default=30, ge=0)
    initiative_bonus: int = Field(default=0)
    hit_dice: str = Field(default="1d8", min_length=1)
    hit_points: Dnd5eHitPoints = Field(default_factory=Dnd5eHitPoints)
    ability_scores: Dnd5eAbilityScores = Field(default_factory=Dnd5eAbilityScores)
    saving_throws_proficient: list[str] = Field(default_factory=list)
    skills_proficient: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    features_traits: list[str] = Field(default_factory=list)
    spells: list[str] = Field(default_factory=list)
    notes: str = Field(default="", min_length=0)


class PlayerStaticData(BaseModel):
    player_id: str = Field(default="player_001", min_length=1)
    name: str = Field(default="玩家", min_length=1)
    move_speed_mph: int = Field(default=4500, gt=0)
    role_type: Literal["player", "npc", "monster"] = "player"
    dnd5e_sheet: Dnd5eCharacterSheet = Field(default_factory=Dnd5eCharacterSheet)


class PlayerRuntimeData(BaseModel):
    session_id: str = Field(default="sess_default", min_length=1)
    current_position: Position | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RoleRelation(BaseModel):
    target_role_id: str = Field(..., min_length=1)
    relation_tag: str = Field(default="neutral", min_length=1)
    note: str = Field(default="", min_length=0)


class NpcDialogueEntry(BaseModel):
    id: str = Field(..., min_length=1)
    speaker: Literal["player", "npc"]
    speaker_role_id: str = Field(..., min_length=1)
    speaker_name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    world_time_text: str = Field(..., min_length=1)
    world_time: dict[str, str | int] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NpcRoleCard(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    state: str = Field(default="idle", min_length=1)
    personality: str = Field(default="", min_length=0)
    speaking_style: str = Field(default="", min_length=0)
    appearance: str = Field(default="", min_length=0)
    background: str = Field(default="", min_length=0)
    cognition: str = Field(default="", min_length=0)
    alignment: str = Field(default="", min_length=0)
    profile: PlayerStaticData = Field(default_factory=lambda: PlayerStaticData(role_type="npc"))
    relations: list[RoleRelation] = Field(default_factory=list)
    dialogue_logs: list[NpcDialogueEntry] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SaveFile(BaseModel):
    version: str = Field(default="1.1.0")
    session_id: str = Field(..., min_length=1)
    map_snapshot: MapSnapshot = Field(default_factory=MapSnapshot)
    area_snapshot: AreaSnapshot = Field(default_factory=AreaSnapshot)
    game_logs: list[GameLogEntry] = Field(default_factory=list)
    game_log_settings: GameLogSettings = Field(default_factory=GameLogSettings)
    player_static_data: PlayerStaticData = Field(default_factory=PlayerStaticData)
    player_runtime_data: PlayerRuntimeData = Field(default_factory=PlayerRuntimeData)
    role_pool: list[NpcRoleCard] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SaveImportRequest(BaseModel):
    save_data: SaveFile


class SaveSetRequest(BaseModel):
    save_data: SaveFile


class SaveClearRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class RegionGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig
    player_position: Position
    desired_count: int = Field(default=6, ge=1, le=10)
    max_count: int = Field(default=10, ge=1, le=10)
    world_prompt: str = Field(default="", min_length=0)
    force_regenerate: bool = False


class RegionGenerateResponse(BaseModel):
    session_id: str
    generated: bool
    zones: list[Zone]


class RenderMapRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    zones: list[Zone] = Field(default_factory=list)
    player_position: Position


class RenderNode(BaseModel):
    zone_id: str
    name: str
    x: int
    y: int


class RenderSubNode(BaseModel):
    sub_zone_id: str
    zone_id: str
    name: str
    x: int
    y: int


class RenderCircle(BaseModel):
    zone_id: str
    center_x: int
    center_y: int
    radius_m: int


class RenderMapResponse(BaseModel):
    session_id: str
    viewport: dict[str, int]
    nodes: list[RenderNode]
    sub_nodes: list[RenderSubNode] = Field(default_factory=list)
    circles: list[RenderCircle] = Field(default_factory=list)
    player_marker: dict[str, int]


class MovementLog(BaseModel):
    id: str
    summary: str
    payload: dict[str, str | int | float]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MoveRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    from_zone_id: str = Field(..., min_length=1)
    to_zone_id: str = Field(..., min_length=1)
    player_name: str | None = None


class MoveResponse(BaseModel):
    session_id: str
    new_position: Position
    duration_min: int
    movement_log: MovementLog


class BehaviorDescribeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig
    log: MovementLog


class BehaviorDescribeResponse(BaseModel):
    session_id: str
    narration: str


class GameLogAddRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)


class GameLogListResponse(BaseModel):
    session_id: str
    items: list[GameLogEntry] = Field(default_factory=list)


class GameLogSettingsResponse(BaseModel):
    session_id: str
    settings: GameLogSettings


class TokenUsageBucket(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TokenUsageSources(BaseModel):
    chat: TokenUsageBucket = Field(default_factory=TokenUsageBucket)
    map_generation: TokenUsageBucket = Field(default_factory=TokenUsageBucket)
    movement_narration: TokenUsageBucket = Field(default_factory=TokenUsageBucket)


class TokenUsageResponse(BaseModel):
    session_id: str
    total: TokenUsageBucket = Field(default_factory=TokenUsageBucket)
    sources: TokenUsageSources = Field(default_factory=TokenUsageSources)


class WorldClockInitRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    calendar: str = Field(default="fantasy_default", min_length=1)


class WorldClockInitResponse(BaseModel):
    ok: bool = True
    clock: WorldClock


class AreaCurrentResponse(BaseModel):
    ok: bool = True
    area_snapshot: AreaSnapshot


class AreaEnterZoneRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    zone_id: str = Field(..., min_length=1)


class AreaMoveSubZoneRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    to_sub_zone_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class AreaMovePoint(BaseModel):
    zone_id: str = Field(..., min_length=1)
    sub_zone_id: str | None = None
    coord: Coord3D


class AreaMoveResult(BaseModel):
    ok: bool = True
    from_point: AreaMovePoint
    to_point: AreaMovePoint
    distance_m: float
    duration_min: int
    clock_delta_min: int
    clock_after: WorldClock
    movement_feedback: str = Field(..., min_length=1)


class AreaDiscoverInteractionsRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    sub_zone_id: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class AreaDiscoverInteractionsResponse(BaseModel):
    ok: bool = True
    generated_mode: Literal["instant"] = "instant"
    new_interactions: list[AreaInteraction] = Field(default_factory=list)


class AreaExecuteInteractionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    interaction_id: str = Field(..., min_length=1)


class AreaExecuteInteractionResponse(BaseModel):
    ok: bool = True
    status: Literal["placeholder"] = "placeholder"
    message: str = Field(default="待开发", min_length=1)


class RolePoolListResponse(BaseModel):
    session_id: str
    total: int
    items: list[NpcRoleCard] = Field(default_factory=list)


class RoleRelationUpsertRequest(BaseModel):
    relation_tag: str = Field(default="met", min_length=1)
    note: str = Field(default="", min_length=0)


class NpcGreetRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    npc_role_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class NpcGreetResponse(BaseModel):
    ok: bool = True
    session_id: str
    npc_role_id: str
    greeting: str = Field(..., min_length=1)


class NpcChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    npc_role_id: str = Field(..., min_length=1)
    player_message: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class NpcChatResponse(BaseModel):
    ok: bool = True
    session_id: str
    npc_role_id: str
    reply: str = Field(..., min_length=1)
    time_spent_min: int = Field(ge=1)
    dialogue_logs: list[NpcDialogueEntry] = Field(default_factory=list)


class ActionCheckRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    action_type: Literal["attack", "check", "item_use"] = "check"
    action_prompt: str = Field(..., min_length=1)
    actor_role_id: str | None = None
    config: ChatConfig | None = None


class ActionCheckResponse(BaseModel):
    ok: bool = True
    session_id: str
    actor_role_id: str
    action_type: Literal["attack", "check", "item_use"]
    requires_check: bool
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    ability_modifier: int
    dc: int
    dice_roll: int | None = None
    total_score: int | None = None
    success: bool
    critical: Literal["none", "critical_success", "critical_failure"] = "none"
    time_spent_min: int = Field(ge=1)
    narrative: str = Field(..., min_length=1)
    applied_effects: list[str] = Field(default_factory=list)
    relation_tag_suggestion: str | None = None
