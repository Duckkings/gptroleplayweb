from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class UIConfig(BaseModel):
    theme: str = Field(default="dark")


class SubZoneDebugConfig(BaseModel):
    small_min_count: int = Field(default=3, ge=1, le=20)
    small_max_count: int = Field(default=5, ge=1, le=20)
    medium_min_count: int = Field(default=5, ge=1, le=30)
    medium_max_count: int = Field(default=10, ge=1, le=30)
    large_min_count: int = Field(default=8, ge=1, le=40)
    large_max_count: int = Field(default=15, ge=1, le=40)
    discover_interaction_limit: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "SubZoneDebugConfig":
        pairs = (
            ("small", self.small_min_count, self.small_max_count),
            ("medium", self.medium_min_count, self.medium_max_count),
            ("large", self.large_min_count, self.large_max_count),
        )
        for label, minimum, maximum in pairs:
            if minimum > maximum:
                raise ValueError(f"{label}_min_count must be <= {label}_max_count")
        return self


class PublicSceneConfig(BaseModel):
    active_actor_limit: int = Field(default=8, ge=1, le=16)
    idle_actor_limit: int = Field(default=2, ge=1, le=8)
    max_world_pushes: int = Field(default=2, ge=0, le=4)
    uncertain_actions_require_check: bool = True


class ChatRuntimeConfig(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    structured_output_mode: Literal["auto", "legacy_tags"] = "auto"


AIProvider = Literal["openai", "deepseek", "gemini"]
AI_PROVIDERS: tuple[str, ...] = ("openai", "deepseek", "gemini")


def _normalize_runtime_payload(raw: Any) -> dict[str, Any]:
    runtime = dict(raw) if isinstance(raw, dict) else {}
    if "temperature" in runtime and runtime["temperature"] in ("", None):
        runtime.pop("temperature", None)
    if "max_tokens" in runtime and runtime["max_tokens"] in ("", None):
        runtime.pop("max_tokens", None)
    if "max_completion_tokens" in runtime and runtime["max_completion_tokens"] in ("", None):
        runtime.pop("max_completion_tokens", None)
    mode = str(runtime.get("structured_output_mode") or "").strip().lower()
    if mode in {"auto", "legacy_tags"}:
        runtime["structured_output_mode"] = mode
    elif "structured_output_mode" in runtime:
        runtime.pop("structured_output_mode", None)
    return runtime


def _normalize_provider_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    data = dict(raw)
    runtime = _normalize_runtime_payload(data.get("runtime"))
    if "temperature" in data and "temperature" not in runtime:
        runtime["temperature"] = data.pop("temperature")
    if "max_tokens" in data and "max_tokens" not in runtime:
        runtime["max_tokens"] = data.pop("max_tokens")
    if "max_completion_tokens" in data and "max_completion_tokens" not in runtime:
        runtime["max_completion_tokens"] = data.pop("max_completion_tokens")
    if "openai_api_key" in data and "api_key" not in data:
        data["api_key"] = data.pop("openai_api_key")

    normalized: dict[str, Any] = {"runtime": runtime}
    if "api_key" in data:
        normalized["api_key"] = data.get("api_key")
    if "base_url_override" in data:
        normalized["base_url_override"] = data.get("base_url_override")
    if "model" in data:
        normalized["model"] = data.get("model")
    return normalized


def _empty_provider_config() -> dict[str, Any]:
    return {
        "api_key": "",
        "base_url_override": None,
        "model": "",
        "runtime": {},
    }


class ProviderChatConfig(BaseModel):
    api_key: str = Field(default="", min_length=0)
    base_url_override: str | None = None
    model: str = Field(default="", min_length=0)
    runtime: ChatRuntimeConfig = Field(default_factory=ChatRuntimeConfig)


class ProviderConfigMap(BaseModel):
    openai: ProviderChatConfig = Field(default_factory=ProviderChatConfig)
    deepseek: ProviderChatConfig = Field(default_factory=ProviderChatConfig)
    gemini: ProviderChatConfig = Field(default_factory=ProviderChatConfig)

    def for_provider(self, provider: AIProvider) -> ProviderChatConfig:
        return getattr(self, provider)


class ChatConfig(BaseModel):
    version: str = Field(default="2.0.0")
    provider: AIProvider = "openai"
    api_key: str = Field(..., min_length=1)
    base_url_override: str | None = None
    model: str = Field(..., min_length=1)
    stream: bool
    runtime: ChatRuntimeConfig = Field(default_factory=ChatRuntimeConfig)
    provider_configs: ProviderConfigMap = Field(default_factory=ProviderConfigMap)
    gm_prompt: str = Field(..., min_length=1)
    speech_time_per_50_tokens_min: int = Field(default=1, ge=1, le=30)
    sub_zone_debug: SubZoneDebugConfig = Field(default_factory=SubZoneDebugConfig)
    public_scene: PublicSceneConfig = Field(default_factory=PublicSceneConfig)
    ui: UIConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        runtime = _normalize_runtime_payload(data.get("runtime"))

        if "provider" not in data or data.get("provider") not in AI_PROVIDERS:
            data["provider"] = "openai"
        provider = data["provider"]
        if "openai_api_key" in data and "api_key" not in data:
            data["api_key"] = data.pop("openai_api_key")
        if "temperature" in data and "temperature" not in runtime:
            runtime["temperature"] = data.pop("temperature")
        if "max_tokens" in data and "max_tokens" not in runtime:
            runtime["max_tokens"] = data.pop("max_tokens")
        if "max_completion_tokens" in data and "max_completion_tokens" not in runtime:
            runtime["max_completion_tokens"] = data.pop("max_completion_tokens")

        provider_configs = {
            name: _empty_provider_config()
            for name in AI_PROVIDERS
        }
        raw_provider_configs = data.get("provider_configs")
        if isinstance(raw_provider_configs, dict):
            for name in AI_PROVIDERS:
                if name not in raw_provider_configs:
                    continue
                provider_configs[name].update(_normalize_provider_payload(raw_provider_configs[name]))

        current_config = dict(provider_configs[provider])
        current_config.update(_normalize_provider_payload(data))
        current_config["runtime"] = runtime if runtime else current_config.get("runtime", {})
        provider_configs[provider] = current_config

        selected = provider_configs[provider]
        data["provider_configs"] = provider_configs
        data["api_key"] = selected.get("api_key", "")
        data["base_url_override"] = selected.get("base_url_override")
        data["model"] = selected.get("model", "")
        data["runtime"] = selected.get("runtime", {})
        return data

    @property
    def openai_api_key(self) -> str:
        return self.api_key

    @property
    def temperature(self) -> float:
        return self.runtime.temperature if self.runtime.temperature is not None else 0.8

    @property
    def max_tokens(self) -> int:
        if self.runtime.max_tokens is not None:
            return self.runtime.max_tokens
        if self.runtime.max_completion_tokens is not None:
            return self.runtime.max_completion_tokens
        return 1200

    @property
    def max_completion_tokens(self) -> int | None:
        return self.runtime.max_completion_tokens


class ValidateError(BaseModel):
    field: str
    message: str


class ValidateConfigResponse(BaseModel):
    valid: bool
    errors: list[ValidateError]
    normalized_config: ChatConfig | None = None


class ModelProfileRequest(BaseModel):
    provider: AIProvider
    api_key: str = Field(default="", min_length=0)
    model: str = Field(default="", min_length=0)
    base_url_override: str | None = None


class ModelCapabilityInfo(BaseModel):
    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    capability_profile: Literal[
        "openai_gpt5",
        "openai_standard",
        "deepseek_chat",
        "deepseek_reasoner",
        "gemini_openai_compatible",
        "generic_compatible",
    ]
    supported_params: list[Literal["temperature", "max_tokens", "max_completion_tokens"]] = Field(default_factory=list)
    defaults: dict[str, int | float | bool | str] = Field(default_factory=dict)
    warning: str | None = None


class ModelDiscoverResponse(BaseModel):
    models: list[ModelCapabilityInfo] = Field(default_factory=list)


class ModelProfileResponse(BaseModel):
    model: ModelCapabilityInfo


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


class SceneEvent(BaseModel):
    event_id: str = Field(..., min_length=1)
    kind: Literal[
        "public_targeted_npc_reply",
        "public_bystander_reaction",
        "team_public_reaction",
        "public_actor_action",
        "public_actor_resolution",
        "public_round_resolution",
        "role_desire_surface",
        "companion_story_surface",
        "reputation_update",
        "encounter_started",
        "encounter_progress",
        "encounter_resolution",
        "encounter_background",
        "encounter_situation_update",
        "encounter_world_push",
        "player_reaction_triggered",
        "player_reaction_result",
        "player_dying",
        "player_death_save",
        "player_stabilized",
        "player_died",
        "player_revived",
    ]
    actor_role_id: str = Field(default="", min_length=0)
    actor_name: str = Field(default="", min_length=0)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ChatResponse(BaseModel):
    session_id: str
    reply: Message
    usage: Usage
    tool_events: list[ToolEvent] = Field(default_factory=list)
    scene_events: list[SceneEvent] = Field(default_factory=list)
    time_spent_min: int = 0
    archived_sub_zone_turn_id: str | None = None
    main_turn_summary: "MainTurnSummary | None" = None
    current_zone_metric: "ZoneMetricEntry | None" = None


class HealthResponse(BaseModel):
    ok: bool
    time: str


class PathConfig(BaseModel):
    path: str = Field(..., min_length=1)


class MainTurnSummary(BaseModel):
    player_situation_delta: int = 0
    public_actor_situation_delta_total: int = 0
    world_push_situation_delta_total: int = 0
    turn_total_delta: int = 0
    situation_value_before: int | None = None
    situation_value_after: int | None = None


class PlayerReactionCheck(BaseModel):
    reaction_id: str = Field(..., min_length=1)
    source_kind: Literal["npc_action", "environment", "world_push", "encounter_effect", "npc_chat", "map_arrival"]
    source_actor_id: str | None = None
    source_actor_name: str | None = None
    source_label: str = Field(..., min_length=1)
    trigger_summary: str = Field(..., min_length=1)
    threatened_consequence: str = Field(..., min_length=1)
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    dc: int = Field(..., ge=5, le=30)
    check_task: str = Field(..., min_length=1)
    resolution_context: Literal["main_chat", "encounter", "npc_chat", "map_move"]
    success_hint: str = Field(default="", min_length=0)
    failure_hint: str = Field(default="", min_length=0)
    critical_success_hint: str = Field(default="", min_length=0)
    critical_failure_hint: str = Field(default="", min_length=0)


class PlayerReactionCheckSeed(BaseModel):
    source_kind: Literal["npc_action", "environment", "world_push", "encounter_effect", "npc_chat", "map_arrival"]
    source_actor_id: str | None = None
    source_actor_name: str | None = None
    source_label: str = Field(..., min_length=1)
    trigger_summary: str = Field(..., min_length=1)
    threatened_consequence: str = Field(..., min_length=1)
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    dc: int = Field(..., ge=5, le=30)
    check_task: str = Field(..., min_length=1)
    success_hint: str = Field(default="", min_length=0)
    failure_hint: str = Field(default="", min_length=0)
    critical_success_hint: str = Field(default="", min_length=0)
    critical_failure_hint: str = Field(default="", min_length=0)


class MainTurnSegment(BaseModel):
    reply_text: str = Field(default="", min_length=0)
    public_actor_updates: list[dict[str, Any]] = Field(default_factory=list)
    public_round_resolution: str = Field(default="", min_length=0)
    encounter_update: dict[str, Any] = Field(default_factory=dict)
    player_reaction_check: PlayerReactionCheckSeed | None = None
    segment_status: Literal["completed", "awaiting_reaction"] = "completed"

    @model_validator(mode="after")
    def _validate_reaction_checkpoint(self) -> "MainTurnSegment":
        if self.segment_status == "awaiting_reaction" and self.player_reaction_check is None:
            raise ValueError("awaiting_reaction requires player_reaction_check")
        if self.segment_status == "completed" and self.player_reaction_check is not None:
            raise ValueError("completed segment must not include player_reaction_check")
        return self


class NpcChatBundleSegment(BaseModel):
    action_reaction: str = Field(default="", min_length=0)
    speech_reply: str = Field(default="", min_length=0)
    relation_tag: Literal["ally", "friendly", "met", "neutral", "wary", "hostile"] = "neutral"


class NpcChatSegment(BaseModel):
    reply_text: str = Field(default="", min_length=0)
    npc_bundle: NpcChatBundleSegment = Field(default_factory=NpcChatBundleSegment)
    player_reaction_check: PlayerReactionCheckSeed | None = None
    segment_status: Literal["completed", "awaiting_reaction"] = "completed"

    @model_validator(mode="after")
    def _validate_reaction_checkpoint(self) -> "NpcChatSegment":
        if self.segment_status == "awaiting_reaction" and self.player_reaction_check is None:
            raise ValueError("awaiting_reaction requires player_reaction_check")
        if self.segment_status == "completed" and self.player_reaction_check is not None:
            raise ValueError("completed segment must not include player_reaction_check")
        return self


class PendingTurnState(BaseModel):
    pending_turn_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    flow_kind: Literal["main_chat", "encounter", "npc_chat", "map_move"]
    status: Literal["awaiting_reaction", "cancelled", "completed"] = "awaiting_reaction"
    staged_save: dict[str, Any] = Field(default_factory=dict)
    original_request: dict[str, Any] = Field(default_factory=dict)
    accumulated_reply_text: str = Field(default="", min_length=0)
    accumulated_scene_events: list[SceneEvent] = Field(default_factory=list)
    accumulated_tool_events: list[ToolEvent] = Field(default_factory=list)
    time_spent_min: int = 0
    pending_reaction: PlayerReactionCheck
    continuation_index: int = 0
    usage: Usage = Field(default_factory=Usage)
    npc_role_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PendingTurnContinueRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    pending_turn_id: str = Field(..., min_length=1)
    forced_dice_roll: int = Field(..., ge=1, le=20)
    config: ChatConfig | None = None


class PendingTurnContinueResponse(BaseModel):
    session_id: str
    pending_turn_id: str | None = None
    flow_kind: Literal["main_chat", "encounter", "npc_chat", "map_move"]
    status: Literal["awaiting_reaction", "completed", "cancelled"]
    reply_text: str = Field(default="", min_length=0)
    scene_events: list[SceneEvent] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    main_turn_summary: "MainTurnSummary | None" = None
    current_zone_metric: "ZoneMetricEntry | None" = None
    pending_reaction: PlayerReactionCheck | None = None
    reaction_result: "ActionCheckResponse | None" = None
    archived_sub_zone_turn_id: str | None = None
    npc_role_id: str | None = None


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


class ItemDefinition(BaseModel):
    definition_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    item_kind: str = Field(default="misc", min_length=1)
    sub_kind: str = Field(default="", min_length=0)
    description: str = Field(default="", min_length=0)
    rarity: str = Field(default="common", min_length=1)
    weight: float = Field(default=0, ge=0)
    value: int = Field(default=0, ge=0)
    stackable: bool = True
    max_stack: int = Field(default=1, ge=1)
    use_tags: list[str] = Field(default_factory=list)
    interaction_tags: list[str] = Field(default_factory=list)
    combat_tags: list[str] = Field(default_factory=list)
    effect_prompt_hint: str = Field(default="", min_length=0)


class EquipmentDefinition(BaseModel):
    definition_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    equipment_kind: Literal["weapon", "armor", "shield"] = "weapon"
    slot_type: Literal["weapon", "armor", "shield"] = "weapon"
    damage_dice: str = Field(default="", min_length=0)
    damage_type: str = Field(default="bludgeoning", min_length=1)
    attack_bonus: int = 0
    armor_bonus: int = 0
    range_normal: int = Field(default=0, ge=0)
    range_long: int = Field(default=0, ge=0)
    two_handed: bool = False
    light: bool = False
    heavy: bool = False
    thrown: bool = False
    finesse: bool = False
    ammunition: bool = False
    description: str = Field(default="", min_length=0)
    rarity: str = Field(default="common", min_length=1)
    weight: float = Field(default=0, ge=0)
    value: int = Field(default=0, ge=0)


class InteractableTemplate(BaseModel):
    template_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    interactable_kind: Literal["item_proxy", "container", "clue", "door", "path", "mechanism", "hazard", "scene"] = "scene"
    description: str = Field(default="", min_length=0)
    allowed_actions: list[str] = Field(default_factory=list)
    initial_state_tags: list[str] = Field(default_factory=list)
    loot_mode: Literal["none", "fixed", "ai_first_open"] = "none"
    allowed_item_tags: list[str] = Field(default_factory=list)
    allowed_definition_ids: list[str] = Field(default_factory=list)
    can_pick_up: bool = False
    can_drop_into: bool = False
    can_lock: bool = False
    can_break: bool = False
    can_trigger: bool = False


class ItemInstance(BaseModel):
    item_instance_id: str = Field(..., min_length=1)
    definition_id: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=0)
    uses_left: int | None = Field(default=None, ge=0)
    uses_max: int | None = Field(default=None, ge=0)
    durability: int | None = Field(default=None, ge=0)
    owner_kind: Literal["player", "role", "scene", "container"] = "player"
    owner_id: str = Field(..., min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    display_name: str = Field(default="", min_length=0)
    description_override: str = Field(default="", min_length=0)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ItemInstanceState(BaseModel):
    version: str = Field(default="0.1.0")
    items: list[ItemInstance] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SceneInteractable(BaseModel):
    interactable_id: str = Field(..., min_length=1)
    template_id: str = Field(..., min_length=1)
    zone_id: str = Field(..., min_length=1)
    sub_zone_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    interactable_kind: Literal["item_proxy", "container", "clue", "door", "path", "mechanism", "hazard", "scene"] = "scene"
    description: str = Field(default="", min_length=0)
    allowed_actions: list[str] = Field(default_factory=list)
    state_tags: list[str] = Field(default_factory=list)
    status: Literal["ready", "disabled", "hidden"] = "ready"
    generated_mode: Literal["pre", "instant", "migrated"] = "pre"
    placeholder: bool = False
    item_instance_id: str | None = None
    contained_item_instance_ids: list[str] = Field(default_factory=list)
    loot_generation_status: Literal["ungenerated", "generated"] = "ungenerated"
    first_generated_at: str | None = None
    clue_payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SceneInteractableState(BaseModel):
    version: str = Field(default="0.1.0")
    items: list[SceneInteractable] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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


class SubZoneChatTurnEvent(BaseModel):
    event_kind: Literal[
        "encounter_progress",
        "encounter_resolution",
        "npc_reply",
        "team_reply",
        "system_notice",
        "public_actor_action",
        "public_actor_resolution",
        "public_round_resolution",
        "role_desire_surface",
        "companion_story_surface",
        "reputation_update",
        "encounter_situation_update",
        "encounter_world_push",
    ] = "system_notice"
    actor_type: Literal["npc", "team", "encounter_temp_npc", "system"] = "system"
    actor_id: str = Field(default="", min_length=0)
    actor_name: str = Field(default="", min_length=0)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubZoneChatTurn(BaseModel):
    turn_id: str = Field(..., min_length=1)
    source: Literal["main_chat", "encounter", "system"] = "main_chat"
    player_mode: Literal["active", "passive"] = "active"
    world_time_text: str = Field(default="", min_length=0)
    world_time: dict[str, str | int] = Field(default_factory=dict)
    player_action: str = Field(default="", min_length=0)
    player_speech: str = Field(default="", min_length=0)
    player_action_check: dict[str, str | int | float | bool] = Field(default_factory=dict)
    gm_narration: str = Field(default="", min_length=0)
    active_encounter_id: str | None = None
    active_encounter_title: str = Field(default="", min_length=0)
    active_encounter_status: str = Field(default="", min_length=0)
    events: list[SubZoneChatTurnEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SubZoneChatContext(BaseModel):
    version: str = Field(default="0.1.0")
    recent_turns: list[SubZoneChatTurn] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    chat_context: SubZoneChatContext = Field(default_factory=SubZoneChatContext)


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


class Dnd5eAbilityModifiers(BaseModel):
    strength: int = Field(default=0, ge=-10, le=20)
    dexterity: int = Field(default=0, ge=-10, le=20)
    constitution: int = Field(default=0, ge=-10, le=20)
    intelligence: int = Field(default=0, ge=-10, le=20)
    wisdom: int = Field(default=0, ge=-10, le=20)
    charisma: int = Field(default=0, ge=-10, le=20)


class Dnd5eHitPoints(BaseModel):
    current: int = Field(default=10, ge=0)
    maximum: int = Field(default=10, ge=1)
    temporary: int = Field(default=0, ge=0)


class Dnd5eSpellSlots(BaseModel):
    level_1: int = Field(default=2, ge=0, le=9)
    level_2: int = Field(default=0, ge=0, le=9)
    level_3: int = Field(default=0, ge=0, le=9)
    level_4: int = Field(default=0, ge=0, le=9)
    level_5: int = Field(default=0, ge=0, le=9)
    level_6: int = Field(default=0, ge=0, le=9)
    level_7: int = Field(default=0, ge=0, le=9)
    level_8: int = Field(default=0, ge=0, le=9)
    level_9: int = Field(default=0, ge=0, le=9)


class RoleBuffEffect(BaseModel):
    strength_delta: int = 0
    dexterity_delta: int = 0
    constitution_delta: int = 0
    intelligence_delta: int = 0
    wisdom_delta: int = 0
    charisma_delta: int = 0
    ac_delta: int = 0
    dc_delta: int = 0
    speed_ft_delta: int = 0
    move_speed_mph_delta: int = 0
    hp_max_delta: int = 0
    stamina_max_delta: int = 0


class RoleBuff(BaseModel):
    buff_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = Field(default="", min_length=0)
    source: str = Field(default="", min_length=0)
    duration_min: int = Field(default=10, ge=0)
    remaining_min: int = Field(default=10, ge=0)
    stackable: bool = False
    effect: RoleBuffEffect = Field(default_factory=RoleBuffEffect)


class InventoryItem(BaseModel):
    item_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    item_type: str = Field(default="misc", min_length=1)
    description: str = Field(default="", min_length=0)
    weight: float = Field(default=0, ge=0)
    rarity: str = Field(default="common", min_length=1)
    value: int = Field(default=0, ge=0)
    effect: str = Field(default="", min_length=0)
    uses_max: int | None = Field(default=None, ge=0)
    uses_left: int | None = Field(default=None, ge=0)
    cooldown_min: int = Field(default=0, ge=0)
    bound: bool = False
    quantity: int = Field(default=1, ge=1)
    slot_type: Literal["weapon", "armor", "misc"] = "misc"
    attack_bonus: int = 0
    armor_bonus: int = 0


class InventoryData(BaseModel):
    gold: int = Field(default=0, ge=0)
    item_instance_ids: list[str] = Field(default_factory=list)
    items: list[InventoryItem] = Field(default_factory=list)


class EquipmentSlots(BaseModel):
    weapon_item_id: str | None = None
    armor_item_id: str | None = None
    shield_item_id: str | None = None
    weapon_item_instance_id: str | None = None
    armor_item_instance_id: str | None = None
    shield_item_instance_id: str | None = None


class PlayerDeathState(BaseModel):
    """轻量级死亡状态追踪，嵌入 Dnd5eCharacterSheet"""
    version: str = Field(default="0.1.0")
    
    # 生命状态
    life_status: Literal["healthy", "dying", "stable", "dead"] = "healthy"
    
    # 濒死追踪 (0-3)
    death_save_successes: int = Field(default=0, ge=0, le=3)
    death_save_failures: int = Field(default=0, ge=0, le=3)
    
    # 死亡统计
    death_count: int = Field(default=0, ge=0)
    death_streak_count: int = Field(default=0, ge=0)  # 24小时内
    death_streak_reset_at: str | None = None
    
    # 上次死亡信息
    last_death_at: str | None = None
    last_death_zone_id: str | None = None
    last_death_sub_zone_id: str | None = None
    last_death_cause: str = Field(default="")
    
    # 复活追踪
    revived_at: str | None = None
    revival_method: Literal["shrine", "teammate", "item"] | None = None
    revival_weakness_until: str | None = None
    
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DeathPenalties(BaseModel):
    """死亡惩罚计算结果"""
    gold_lost: int = 0
    exp_lost: int = 0
    items_lost: list[str] = Field(default_factory=list)  # item_instance_ids
    weakness_duration_min: int = 60


class Dnd5eCharacterSheet(BaseModel):
    level: int = Field(default=1, ge=1, le=20)
    experience_current: int = Field(default=0, ge=0)
    experience_to_next_level: int = Field(default=300, ge=0)
    race: str = Field(default="", min_length=0)
    char_class: str = Field(default="", min_length=0)
    background: str = Field(default="", min_length=0)
    alignment: str = Field(default="", min_length=0)
    proficiency_bonus: int = Field(default=2)
    armor_class: int = Field(default=10, ge=0)
    difficulty_class: int = Field(default=10, ge=0)
    speed_ft: int = Field(default=30, ge=0)
    initiative_bonus: int = Field(default=0)
    stamina_current: int = Field(default=10, ge=0)
    stamina_maximum: int = Field(default=10, ge=1)
    is_dead: bool = False
    status_flags: list[str] = Field(default_factory=list)
    hit_dice: str = Field(default="1d8", min_length=1)
    hit_points: Dnd5eHitPoints = Field(default_factory=Dnd5eHitPoints)
    ability_scores: Dnd5eAbilityScores = Field(default_factory=Dnd5eAbilityScores)
    current_ability_scores: Dnd5eAbilityScores = Field(default_factory=Dnd5eAbilityScores)
    ability_modifiers: Dnd5eAbilityModifiers = Field(default_factory=Dnd5eAbilityModifiers)
    current_ability_modifiers: Dnd5eAbilityModifiers = Field(default_factory=Dnd5eAbilityModifiers)
    saving_throws_proficient: list[str] = Field(default_factory=list)
    skills_proficient: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    equipment_slots: EquipmentSlots = Field(default_factory=EquipmentSlots)
    backpack: InventoryData = Field(default_factory=InventoryData)
    buffs: list[RoleBuff] = Field(default_factory=list)
    features_traits: list[str] = Field(default_factory=list)
    spells: list[str] = Field(default_factory=list)
    spell_slots_max: Dnd5eSpellSlots = Field(default_factory=Dnd5eSpellSlots)
    spell_slots_current: Dnd5eSpellSlots = Field(default_factory=Dnd5eSpellSlots)
    notes: str = Field(default="", min_length=0)
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)


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
    context_kind: Literal["private_chat", "public_targeted", "public_reaction", "team_chat", "encounter"] = "private_chat"
    content: str = Field(..., min_length=1)
    world_time_text: str = Field(..., min_length=1)
    world_time: dict[str, str | int] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NpcConversationState(BaseModel):
    current_topic: str = Field(default="", min_length=0)
    last_open_question: str = Field(default="", min_length=0)
    last_npc_claim: str = Field(default="", min_length=0)
    last_player_intent: str = Field(default="", min_length=0)
    last_referenced_entity: str = Field(default="", min_length=0)
    last_scene_mode: Literal["private_chat", "public_chat", "team_chat", "encounter", "unknown"] = "unknown"
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RoleDesire(BaseModel):
    desire_id: str = Field(..., min_length=1)
    kind: Literal["item", "place", "info", "bond", "secret", "help"] = "info"
    title: str = Field(..., min_length=1)
    summary: str = Field(default="", min_length=0)
    intensity: int = Field(default=50, ge=0, le=100)
    status: Literal["latent", "active", "surfaced", "quest_linked", "resolved", "expired"] = "latent"
    visibility: Literal["hidden", "hinted", "explicit"] = "hidden"
    preferred_surface: Literal["public_scene", "team_chat", "area_arrival", "encounter_aftermath", "private_chat"] = "public_scene"
    target_refs: list["EntityRef"] = Field(default_factory=list)
    linked_quest_id: str | None = None
    cooldown_until: str | None = None
    last_surfaced_at: str | None = None


class RoleStoryBeat(BaseModel):
    beat_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(default="", min_length=0)
    affinity_required: int = Field(default=60, ge=0, le=100)
    min_days_in_team: int = Field(default=2, ge=0, le=3650)
    status: Literal["locked", "ready", "surfaced", "completed", "cooldown"] = "locked"
    preferred_surface: Literal["team_chat", "area_arrival", "passive_turn", "encounter_aftermath"] = "team_chat"
    last_surfaced_at: str | None = None
    completed_at: str | None = None


class NpcRoleCard(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    source_world_revision: int = Field(default=1, ge=1)
    source_map_revision: int = Field(default=1, ge=1)
    knowledge_scope: str = Field(default="local", min_length=1)
    state: str = Field(default="idle", min_length=1)
    personality: str = Field(default="", min_length=0)
    speaking_style: str = Field(default="", min_length=0)
    appearance: str = Field(default="", min_length=0)
    background: str = Field(default="", min_length=0)
    cognition: str = Field(default="", min_length=0)
    alignment: str = Field(default="", min_length=0)
    secret: str = Field(default="", min_length=0)
    likes: list[str] = Field(default_factory=list)
    desires: list[RoleDesire] = Field(default_factory=list)
    story_beats: list[RoleStoryBeat] = Field(default_factory=list)
    talkative_current: int = Field(default=100, ge=0, le=100)
    talkative_maximum: int = Field(default=100, ge=1, le=100)
    last_private_chat_at: str | None = None
    last_public_turn_at: str | None = None
    profile: PlayerStaticData = Field(default_factory=lambda: PlayerStaticData(role_type="npc"))
    relations: list[RoleRelation] = Field(default_factory=list)
    cognition_changes: list[str] = Field(default_factory=list)
    attitude_changes: list[str] = Field(default_factory=list)
    conversation_state: NpcConversationState = Field(default_factory=NpcConversationState)
    dialogue_logs: list[NpcDialogueEntry] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorldState(BaseModel):
    version: str = Field(default="0.1.0")
    world_revision: int = Field(default=1, ge=1)
    map_revision: int = Field(default=1, ge=1)
    last_consistency_check_at: str | None = None
    last_world_rebuild_at: str | None = None


class EntityRef(BaseModel):
    entity_type: Literal["zone", "sub_zone", "npc", "item", "quest", "encounter", "fate", "fate_phase"] = "zone"
    entity_id: str = Field(..., min_length=1)
    label: str = Field(default="", min_length=0)
    required: bool = True
    source: Literal["system", "ai", "fallback"] = "system"


class ConsistencyIssue(BaseModel):
    issue_id: str = Field(..., min_length=1)
    severity: Literal["info", "warning", "error"] = "warning"
    issue_type: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    entity_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class StoryNpcSummary(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    relation_tag: str | None = None


class RoleDriveSummary(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    desires: list[RoleDesire] = Field(default_factory=list)
    story_beats: list[RoleStoryBeat] = Field(default_factory=list)


class PublicSceneActorCandidate(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    actor_type: Literal["npc", "team", "encounter_temp_npc"] = "npc"
    priority_reason: str = Field(default="", min_length=0)
    surfaced_desire_ids: list[str] = Field(default_factory=list)
    surfaced_story_beat_ids: list[str] = Field(default_factory=list)


class SubZoneReputationEntry(BaseModel):
    sub_zone_id: str = Field(..., min_length=1)
    zone_id: str | None = None
    score: int = Field(default=50, ge=0, le=100)
    band: Literal["hostile", "cold", "neutral", "trusted", "favored"] = "neutral"
    recent_reasons: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReputationState(BaseModel):
    version: str = Field(default="0.1.0")
    entries: list[SubZoneReputationEntry] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ZoneMetricEntry(BaseModel):
    zone_id: str = Field(..., min_length=1)
    zone_name: str = Field(..., min_length=1)
    reputation_score: int = Field(default=50, ge=0, le=100)
    reputation_band: Literal["hostile", "cold", "neutral", "trusted", "favored"] = "neutral"
    danger_score: int = Field(default=50, ge=0, le=100)
    danger_band: Literal["low", "medium", "high"] = "medium"
    reputation_reasons: list[str] = Field(default_factory=list)
    danger_reasons: list[str] = Field(default_factory=list)
    seed_source: Literal["ai_generated", "migration_backfill", "system_default"] = "system_default"
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ZoneMetricState(BaseModel):
    version: str = Field(default="0.1.0")
    entries: list[ZoneMetricEntry] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StoryQuestSummary(BaseModel):
    quest_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)


class StoryEncounterSummary(BaseModel):
    encounter_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)


class PlayerStorySummary(BaseModel):
    player_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    level: int = Field(default=1, ge=1)
    hp_current: int = Field(default=0, ge=0)
    hp_maximum: int = Field(default=0, ge=0)
    inventory_item_names: list[str] = Field(default_factory=list)


class GlobalStorySnapshot(BaseModel):
    session_id: str = Field(..., min_length=1)
    world_revision: int = Field(default=1, ge=1)
    map_revision: int = Field(default=1, ge=1)
    current_zone_id: str | None = None
    current_sub_zone_id: str | None = None
    current_zone_name: str = Field(default="", min_length=0)
    current_sub_zone_name: str = Field(default="", min_length=0)
    clock: WorldClock | None = None
    player_summary: PlayerStorySummary
    visible_zone_ids: list[str] = Field(default_factory=list)
    visible_sub_zone_ids: list[str] = Field(default_factory=list)
    available_npc_ids: list[str] = Field(default_factory=list)
    available_npcs: list[StoryNpcSummary] = Field(default_factory=list)
    team_member_ids: list[str] = Field(default_factory=list)
    active_quest_ids: list[str] = Field(default_factory=list)
    active_quests: list[StoryQuestSummary] = Field(default_factory=list)
    pending_quest_ids: list[str] = Field(default_factory=list)
    current_fate_id: str | None = None
    current_fate_phase_id: str | None = None
    recent_encounter_ids: list[str] = Field(default_factory=list)
    recent_game_log_refs: list[str] = Field(default_factory=list)


class EncounterOutcomeChange(BaseModel):
    target_id: str = Field(..., min_length=1)
    delta: int = 0
    summary: str = Field(default="", min_length=0)


class EncounterOutcomePackage(BaseModel):
    result: Literal["success", "failure"] = "success"
    reputation_delta: int = 0
    zone_reputation_delta: int = 0
    zone_danger_delta: int = 0
    npc_relation_deltas: list[EncounterOutcomeChange] = Field(default_factory=list)
    team_deltas: list[EncounterOutcomeChange] = Field(default_factory=list)
    item_rewards: list[InventoryItem] = Field(default_factory=list)
    buff_rewards: list[RoleBuff] = Field(default_factory=list)
    resource_deltas: list[str] = Field(default_factory=list)
    narrative_summary: str = Field(default="", min_length=0)


class PublicSceneState(BaseModel):
    session_id: str = Field(..., min_length=1)
    current_zone_id: str | None = None
    current_sub_zone_id: str | None = None
    current_reputation: SubZoneReputationEntry | None = None
    current_zone_metric: ZoneMetricEntry | None = None
    visible_npcs: list[StoryNpcSummary] = Field(default_factory=list)
    team_members: list[StoryNpcSummary] = Field(default_factory=list)
    candidate_actors: list[PublicSceneActorCandidate] = Field(default_factory=list)
    surfaced_drives: list[RoleDriveSummary] = Field(default_factory=list)
    active_encounter: "EncounterEntry | None" = None


class NpcKnowledgeSnapshot(BaseModel):
    npc_role_id: str = Field(..., min_length=1)
    npc_name: str = Field(..., min_length=1)
    world_revision: int = Field(default=1, ge=1)
    map_revision: int = Field(default=1, ge=1)
    current_zone_id: str | None = None
    current_sub_zone_id: str | None = None
    self_profile_summary: str = Field(default="", min_length=0)
    known_player_relation: str = Field(default="neutral", min_length=1)
    known_local_npc_ids: list[str] = Field(default_factory=list)
    known_local_zone_ids: list[str] = Field(default_factory=list)
    known_active_quest_refs: list[EntityRef] = Field(default_factory=list)
    recent_dialogue_summary: list[str] = Field(default_factory=list)
    forbidden_entity_ids: list[str] = Field(default_factory=list)
    response_rules: list[str] = Field(default_factory=list)


class TeamMember(BaseModel):
    role_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    origin_zone_id: str | None = None
    origin_sub_zone_id: str | None = None
    joined_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    affinity: int = Field(default=50, ge=0, le=100)
    trust: int = Field(default=40, ge=0, le=100)
    join_source: Literal["story", "debug"] = "story"
    join_reason: str = Field(default="", min_length=0)
    is_debug: bool = False
    debug_prompt: str = Field(default="", min_length=0)
    status: Literal["active", "left"] = "active"
    last_reaction_at: str | None = None
    last_reaction_preview: str = Field(default="", min_length=0)


class TeamReaction(BaseModel):
    reaction_id: str = Field(..., min_length=1)
    member_role_id: str = Field(..., min_length=1)
    member_name: str = Field(..., min_length=1)
    trigger_kind: Literal["main_chat", "npc_chat", "zone_move", "sub_zone_move", "action_check", "team_chat", "public_chat", "public_turn", "encounter", "system"] = "system"
    content: str = Field(..., min_length=1)
    affinity_delta: int = 0
    trust_delta: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TeamState(BaseModel):
    version: str = Field(default="0.1.0")
    members: list[TeamMember] = Field(default_factory=list)
    reactions: list[TeamReaction] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TravelCompanionEntry(BaseModel):
    role_id: str = Field(..., min_length=1)
    role_name: str = Field(..., min_length=1)
    source_kind: Literal["npc", "team"] = "npc"
    destination_zone_id: str = Field(..., min_length=1)
    destination_sub_zone_id: str | None = None
    follow_until_arrival: bool = True
    declared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TravelCompanionState(BaseModel):
    version: str = Field(default="0.1.0")
    companions: list[TravelCompanionEntry] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BattleDamageProfile(BaseModel):
    dice: str = Field(default="1d4", min_length=1)
    damage_type: str = Field(default="bludgeoning", min_length=1)
    flat_bonus: int = 0


class BattleFieldState(BaseModel):
    zone_id: str | None = None
    zone_name: str = Field(default="", min_length=0)
    sub_zone_id: str | None = None
    sub_zone_name: str = Field(default="", min_length=0)
    description: str = Field(default="", min_length=0)
    feature_tags: list[str] = Field(default_factory=list)
    danger_score: int | None = Field(default=None, ge=0, le=100)
    reputation_score: int | None = Field(default=None, ge=0, le=100)


class BattleStepEntry(BaseModel):
    step_id: str = Field(..., min_length=1)
    round: int = Field(default=1, ge=1)
    kind: Literal[
        "setup",
        "initiative",
        "turn_start",
        "attack",
        "damage",
        "move",
        "defend",
        "disengage",
        "escape",
        "observe",
        "item_use",
        "reaction_prompt",
        "reaction_result",
        "defeat",
        "end",
        "system",
    ] = "system"
    actor_combatant_id: str | None = None
    actor_name: str = Field(default="", min_length=0)
    content: str = Field(..., min_length=1)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CombatantState(BaseModel):
    combatant_id: str = Field(..., min_length=1)
    source_kind: Literal["player", "team", "npc", "test_monster"] = "player"
    role_id: str | None = None
    display_name: str = Field(..., min_length=1)
    side: Literal["player_side", "enemy_side"] = "player_side"
    template_id: str | None = None
    role_kind: Literal["brute", "skirmisher", "ranged", "support", "beast", "adventurer"] = "adventurer"
    ai_style: str = Field(default="hold_line", min_length=1)
    level_hint: int = Field(default=1, ge=1)
    max_hp: int = Field(default=10, ge=1)
    current_hp: int = Field(default=10, ge=0)
    temp_hp: int = Field(default=0, ge=0)
    base_armor_class: int = Field(default=10, ge=0)
    armor_class: int = Field(default=10, ge=0)
    speed: int = Field(default=6, ge=0)
    initiative: int = 0
    initiative_bonus: int = 0
    attack_bonus: int = 0
    damage_profile: BattleDamageProfile = Field(default_factory=BattleDamageProfile)
    ability_modifiers: Dnd5eAbilityModifiers = Field(default_factory=Dnd5eAbilityModifiers)
    saving_throw_bonuses: Dnd5eAbilityModifiers = Field(default_factory=Dnd5eAbilityModifiers)
    position_band: Literal["engaged", "near", "far", "remote"] = "near"
    position_feature_tags: list[str] = Field(default_factory=list)
    action_available: bool = True
    bonus_action_available: bool = True
    reaction_available: bool = True
    movement_remaining: int = Field(default=6, ge=0)
    conditions: list[str] = Field(default_factory=list)
    alive: bool = True
    downed: bool = False
    escaped: bool = False
    temporary_ac_bonus: int = 0
    next_attack_bonus_against: str | None = None
    next_attack_bonus_amount: int = 0
    inventory_item_instance_ids: list[str] = Field(default_factory=list)
    equipped_weapon_instance_id: str | None = None
    equipped_armor_instance_id: str | None = None
    equipped_shield_instance_id: str | None = None
    inventory_items: list[InventoryItem] = Field(default_factory=list)
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)


class CombatState(BaseModel):
    round: int = Field(default=1, ge=1)
    phase: Literal["initiative", "turn", "resolution", "ended"] = "initiative"
    active_combatant_id: str | None = None
    initiative_order: list[str] = Field(default_factory=list)
    momentum_value: int = 0
    combatants: list[CombatantState] = Field(default_factory=list)
    recent_steps: list[BattleStepEntry] = Field(default_factory=list)
    winner_side: Literal["player_side", "enemy_side", "escaped", "cancelled"] | None = None


class BattleRollPrompt(BaseModel):
    prompt_id: str = Field(..., min_length=1)
    roll_kind: Literal["initiative", "attack", "observe", "escape", "reaction", "item_use", "death_save", "stabilize"] = "attack"
    actor_combatant_id: str = Field(..., min_length=1)
    actor_name: str = Field(..., min_length=1)
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"] = "strength"
    ability_modifier: int = 0
    dc: int = Field(default=10, ge=1, le=30)
    check_task: str = Field(..., min_length=1)
    source_label: str | None = None
    threatened_consequence: str | None = None
    success_hint: str | None = None
    failure_hint: str | None = None
    target_combatant_id: str | None = None
    action_name: str = Field(default="", min_length=0)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class BattleRollResolution(BaseModel):
    prompt_id: str = Field(..., min_length=1)
    actor_combatant_id: str = Field(..., min_length=1)
    actor_name: str = Field(..., min_length=1)
    roll_kind: Literal["initiative", "attack", "observe", "escape", "reaction", "item_use"] = "attack"
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"] = "strength"
    ability_modifier: int = 0
    dc: int = Field(default=10, ge=1, le=30)
    dice_roll: int = Field(..., ge=1, le=20)
    total_score: int
    success: bool
    critical: Literal["none", "critical_success", "critical_failure"] = "none"
    summary: str = Field(..., min_length=1)


class BattleUiFlags(BaseModel):
    ai_pacing: Literal["step", "auto"] = "step"
    can_continue_ai: bool = False


class BattleSandboxState(BaseModel):
    battle_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    status: Literal["setup", "active", "awaiting_player_action", "awaiting_player_roll", "awaiting_ai_continue", "ended", "cancelled"] = "setup"
    source_kind: Literal["debug_template", "debug_ai_generated"] = "debug_template"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    battlefield: BattleFieldState = Field(default_factory=BattleFieldState)
    player_snapshot: CombatantState
    ally_snapshots: list[CombatantState] = Field(default_factory=list)
    enemy_snapshots: list[CombatantState] = Field(default_factory=list)
    combat_state: CombatState = Field(default_factory=CombatState)
    pending_roll: BattleRollPrompt | None = None
    last_roll_result: BattleRollResolution | None = None
    battle_logs: list[BattleStepEntry] = Field(default_factory=list)
    ui_flags: BattleUiFlags = Field(default_factory=BattleUiFlags)


class BattleStartRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    mode: Literal["template", "ai_generated"] = "template"
    template_group: str | None = None
    ai_scale: Literal["single", "squad"] = "single"
    ai_strength: Literal["weak", "standard", "strong"] = "standard"
    ai_pacing: Literal["step", "auto"] = "step"
    config: ChatConfig | None = None


class BattleStartResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle: BattleSandboxState


class BattleActionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    action_kind: Literal["attack", "defend", "move", "disengage", "escape", "use_item", "observe", "end_turn"]
    target_combatant_id: str | None = None
    destination_band: Literal["engaged", "near", "far", "remote"] | None = None
    item_id: str | None = None


class BattleActionResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle: BattleSandboxState


class BattleContinueAiRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    ai_pacing: Literal["step", "auto"] | None = None


class BattleContinueAiResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle: BattleSandboxState


class BattleResolveRollRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    forced_dice_roll: int = Field(..., ge=1, le=20)


class BattleResolveRollResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle: BattleSandboxState
    roll_result: BattleRollResolution | None = None


class BattleCurrentResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle: BattleSandboxState | None = None


class BattleEndResponse(BaseModel):
    ok: bool = True
    session_id: str
    battle_id: str | None = None
    ended: bool = True


class SaveFile(BaseModel):
    version: str = Field(default="1.4.0")
    session_id: str = Field(..., min_length=1)
    world_state: WorldState = Field(default_factory=WorldState)
    map_snapshot: MapSnapshot = Field(default_factory=MapSnapshot)
    area_snapshot: AreaSnapshot = Field(default_factory=AreaSnapshot)
    game_logs: list[GameLogEntry] = Field(default_factory=list)
    game_log_settings: GameLogSettings = Field(default_factory=GameLogSettings)
    player_static_data: PlayerStaticData = Field(default_factory=PlayerStaticData)
    player_runtime_data: PlayerRuntimeData = Field(default_factory=PlayerRuntimeData)
    role_pool: list[NpcRoleCard] = Field(default_factory=list)
    team_state: TeamState = Field(default_factory=TeamState)
    reputation_state: ReputationState = Field(default_factory=ReputationState)
    zone_metric_state: ZoneMetricState = Field(default_factory=ZoneMetricState)
    travel_companion_state: TravelCompanionState = Field(default_factory=TravelCompanionState)
    item_instance_state: ItemInstanceState = Field(default_factory=ItemInstanceState)
    scene_interactable_state: SceneInteractableState = Field(default_factory=SceneInteractableState)
    quest_state: QuestState = Field(default_factory=lambda: QuestState())
    encounter_state: EncounterState = Field(default_factory=lambda: EncounterState())
    fate_state: FateState = Field(default_factory=lambda: FateState())
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


class MapRenderPayload(BaseModel):
    viewport: dict[str, int]
    nodes: list["RenderNode"]
    sub_nodes: list["RenderSubNode"] = Field(default_factory=list)
    circles: list["RenderCircle"] = Field(default_factory=list)
    player_marker: dict[str, int]


class RenderMapRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    zones: list[Zone] = Field(default_factory=list)
    player_position: Position
    zone_metric_state: ZoneMetricState | None = None


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
    danger_score: int | None = None
    danger_band: Literal["low", "medium", "high"] | None = None
    fill_color: str | None = None


class RenderMapResponse(BaseModel):
    session_id: str
    viewport: dict[str, int]
    nodes: list[RenderNode]
    sub_nodes: list[RenderSubNode] = Field(default_factory=list)
    circles: list[RenderCircle] = Field(default_factory=list)
    player_marker: dict[str, int]


class MapNarrativePayload(BaseModel):
    text: str = Field(default="", min_length=0)
    source: Literal["ai", "deterministic", "none"] = "none"


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
    config: ChatConfig | None = None
    config: ChatConfig | None = None


class MoveResponse(BaseModel):
    session_id: str
    new_position: Position
    duration_min: int
    movement_log: MovementLog


class MapPostChecksBundle(BaseModel):
    trigger_kind: Literal["random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"] | None = None
    quests_evaluated: bool = False
    fate_evaluated: bool = False
    encounter_checked: bool = False
    encounter_generated: bool = False
    generated_encounter_id: str | None = None
    blocked_by_higher_priority_modal: bool = False


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


class QuestObjective(BaseModel):
    objective_id: str = Field(..., min_length=1)
    kind: Literal["reach_zone", "talk_to_npc", "obtain_item", "resolve_encounter", "complete_quest", "manual_text"] = "manual_text"
    title: str = Field(..., min_length=1)
    description: str = Field(default="", min_length=0)
    target_ref: dict[str, str | int | float | bool] = Field(default_factory=dict)
    progress_current: int = Field(default=0, ge=0)
    progress_target: int = Field(default=1, ge=1)
    status: Literal["pending", "in_progress", "completed"] = "pending"
    completed_at: str | None = None


class QuestReward(BaseModel):
    reward_id: str = Field(..., min_length=1)
    kind: Literal["gold", "item", "relation", "flag", "none"] = "none"
    label: str = Field(..., min_length=1)
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)


class QuestLogEntry(BaseModel):
    id: str = Field(..., min_length=1)
    kind: Literal["offer", "accept", "reject", "progress", "complete", "fail", "system"] = "system"
    message: str = Field(..., min_length=1)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class QuestEntry(BaseModel):
    quest_id: str = Field(..., min_length=1)
    source: Literal["normal", "fate"] = "normal"
    offer_mode: Literal["accept_reject", "accept_only"] = "accept_reject"
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    issuer_role_id: str | None = None
    zone_id: str | None = None
    sub_zone_id: str | None = None
    fate_id: str | None = None
    fate_phase_id: str | None = None
    source_world_revision: int = Field(default=1, ge=1)
    source_map_revision: int = Field(default=1, ge=1)
    entity_refs: list[EntityRef] = Field(default_factory=list)
    invalidated_reason: str | None = None
    status: Literal["pending_offer", "active", "rejected", "completed", "failed", "superseded", "invalidated"] = "pending_offer"
    is_tracked: bool = False
    objectives: list[QuestObjective] = Field(default_factory=list)
    rewards: list[QuestReward] = Field(default_factory=list)
    logs: list[QuestLogEntry] = Field(default_factory=list)
    offered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accepted_at: str | None = None
    rejected_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class QuestState(BaseModel):
    version: str = Field(default="0.1.0")
    tracked_quest_id: str | None = None
    quests: list[QuestEntry] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EncounterEntry(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_status(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        status = str(data.get("status") or "").strip().lower()
        if status == "presented":
            data["status"] = "active"
        elif status == "skipped":
            data["status"] = "expired"
        return data

    encounter_id: str = Field(..., min_length=1)
    type: Literal["npc", "event", "anomaly"] = "event"
    source_world_revision: int = Field(default=1, ge=1)
    source_map_revision: int = Field(default=1, ge=1)
    entity_refs: list[EntityRef] = Field(default_factory=list)
    invalidated_reason: str | None = None
    status: Literal["queued", "active", "resolved", "escaped", "expired", "invalidated"] = "queued"
    trigger_kind: Literal["random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"] = "random_move"
    encounter_mode: Literal["standard", "npc_initiated_chat"] = "standard"
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    npc_role_id: str | None = None
    player_presence: Literal["engaged", "away"] = "engaged"
    related_quest_ids: list[str] = Field(default_factory=list)
    related_fate_phase_ids: list[str] = Field(default_factory=list)
    participant_role_ids: list[str] = Field(default_factory=list)
    temporary_npcs: list["EncounterTemporaryNpc"] = Field(default_factory=list)
    generated_prompt_tags: list[str] = Field(default_factory=list)
    allow_player_prompt: bool = True
    termination_conditions: list["EncounterTerminationCondition"] = Field(default_factory=list)
    steps: list["EncounterStepEntry"] = Field(default_factory=list)
    scene_summary: str = Field(default="", min_length=0)
    latest_outcome_summary: str = Field(default="", min_length=0)
    situation_start_value: int = Field(default=50, ge=0, le=100)
    situation_value: int = Field(default=50, ge=0, le=100)
    situation_trend: Literal["improving", "stable", "worsening"] = "stable"
    last_outcome_package: "EncounterOutcomePackage | None" = None
    background_tick_count: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    presented_at: str | None = None
    resolved_at: str | None = None
    last_advanced_at: str | None = None


class EncounterTemporaryNpc(BaseModel):
    encounter_npc_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    title: str = Field(default="", min_length=0)
    description: str = Field(default="", min_length=0)
    speaking_style: str = Field(default="", min_length=0)
    agenda: str = Field(default="", min_length=0)
    state: str = Field(default="active", min_length=1)
    zone_id: str | None = None
    sub_zone_id: str | None = None
    introduced_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EncounterTerminationCondition(BaseModel):
    condition_id: str = Field(..., min_length=1)
    kind: Literal["npc_leaves", "player_escapes", "target_resolved", "time_elapsed", "manual_custom"] = "manual_custom"
    description: str = Field(..., min_length=1)
    satisfied: bool = False
    satisfied_at: str | None = None


class EncounterStepEntry(BaseModel):
    step_id: str = Field(..., min_length=1)
    kind: Literal["announcement", "player_action", "gm_update", "npc_reaction", "team_reaction", "temp_npc_action", "escape_attempt", "background_tick", "world_push", "resolution"] = "gm_update"
    actor_type: Literal["player", "npc", "team", "encounter_temp_npc", "system"] = "system"
    actor_id: str = Field(default="", min_length=0)
    actor_name: str = Field(default="", min_length=0)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EncounterResolution(BaseModel):
    encounter_id: str = Field(..., min_length=1)
    player_prompt: str = Field(..., min_length=1)
    reply: str = Field(..., min_length=1)
    time_spent_min: int = Field(default=1, ge=1)
    quest_updates: list[str] = Field(default_factory=list)
    situation_delta: int = 0
    situation_value_after: int = Field(default=50, ge=0, le=100)
    reputation_delta: int = 0
    applied_outcome_summaries: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EncounterState(BaseModel):
    version: str = Field(default="0.1.0")
    pending_ids: list[str] = Field(default_factory=list)
    active_encounter_id: str | None = None
    encounters: list[EncounterEntry] = Field(default_factory=list)
    history: list[EncounterResolution] = Field(default_factory=list)
    debug_force_trigger: bool = False
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FateTriggerCondition(BaseModel):
    condition_id: str = Field(..., min_length=1)
    kind: Literal["manual", "days_elapsed", "met_npc", "obtained_item", "resolved_encounter", "completed_quest"] = "manual"
    description: str = Field(..., min_length=1)
    payload: dict[str, str | int | float | bool] = Field(default_factory=dict)
    satisfied: bool = False
    satisfied_at: str | None = None


class FatePhase(BaseModel):
    phase_id: str = Field(..., min_length=1)
    index: int = Field(default=1, ge=1)
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    source_world_revision: int = Field(default=1, ge=1)
    source_map_revision: int = Field(default=1, ge=1)
    bound_entity_refs: list[EntityRef] = Field(default_factory=list)
    invalidated_reason: str | None = None
    status: Literal["locked", "ready", "quest_offered", "quest_active", "completed"] = "locked"
    trigger_conditions: list[FateTriggerCondition] = Field(default_factory=list)
    triggered_at: str | None = None
    bound_quest_id: str | None = None
    completed_at: str | None = None


class FateLine(BaseModel):
    fate_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    source_world_revision: int = Field(default=1, ge=1)
    source_map_revision: int = Field(default=1, ge=1)
    bound_entity_refs: list[EntityRef] = Field(default_factory=list)
    invalidated_reason: str | None = None
    status: Literal["not_generated", "active", "completed", "superseded", "invalidated"] = "active"
    current_phase_id: str | None = None
    phases: list[FatePhase] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FateState(BaseModel):
    version: str = Field(default="0.1.0")
    current_fate: FateLine | None = None
    archive: list[FateLine] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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


class MapStateSyncBundle(BaseModel):
    map_snapshot: MapSnapshot
    area_snapshot: AreaSnapshot
    render: MapRenderPayload
    world_state: WorldState
    player_static_data: PlayerStaticData
    player_runtime_data: PlayerRuntimeData
    role_pool: list[NpcRoleCard] = Field(default_factory=list)
    current_reputation: SubZoneReputationEntry | None = None
    current_zone_metric: ZoneMetricEntry | None = None
    zone_metric_state: ZoneMetricState = Field(default_factory=ZoneMetricState)
    quest_state: QuestState
    pending_offers: list[QuestEntry] = Field(default_factory=list)
    tracked_quest: QuestEntry | None = None
    encounter_state: EncounterState
    pending_encounters: list[EncounterEntry] = Field(default_factory=list)
    active_encounter: EncounterEntry | None = None
    fate_state: FateState
    team_state: TeamState
    team_members: list[TeamMember] = Field(default_factory=list)
    game_logs: list[GameLogEntry] = Field(default_factory=list)


class MapBootstrapResponse(BaseModel):
    ok: bool = True
    operation: Literal["bootstrap"] = "bootstrap"
    generated: bool = False
    narration: MapNarrativePayload = Field(default_factory=MapNarrativePayload)
    state_sync: MapStateSyncBundle


class MoveResolvedResponse(MoveResponse):
    narration: MapNarrativePayload = Field(default_factory=MapNarrativePayload)
    post_checks: MapPostChecksBundle = Field(default_factory=MapPostChecksBundle)
    state_sync: MapStateSyncBundle
    scene_events: list[SceneEvent] = Field(default_factory=list)
    main_turn_summary: MainTurnSummary | None = None
    current_zone_metric: ZoneMetricEntry | None = None


class AreaMoveResolvedResponse(AreaMoveResult):
    narration: MapNarrativePayload = Field(default_factory=MapNarrativePayload)
    post_checks: MapPostChecksBundle = Field(default_factory=MapPostChecksBundle)
    state_sync: MapStateSyncBundle


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
    action_kind: str = Field(default="inspect", min_length=1)
    actor_kind: Literal["player", "role"] = "player"
    actor_role_id: str | None = None
    item_instance_id: str | None = None
    prompt: str = Field(default="", min_length=0)
    action_check: "ActionCheckResponse | None" = None
    config: ChatConfig | None = None


class AreaExecuteInteractionResponse(BaseModel):
    ok: bool = True
    status: Literal["placeholder", "ok", "fallback"] = "placeholder"
    message: str = Field(default="待开发", min_length=1)
    reply: str = Field(default="", min_length=0)
    scene_events: list[SceneEvent] = Field(default_factory=list)
    inventory_changes: list[dict[str, Any]] = Field(default_factory=list)
    interactable_updates: list[dict[str, Any]] = Field(default_factory=list)


class AreaDiscoverInteractionsResolvedResponse(AreaDiscoverInteractionsResponse):
    narration: MapNarrativePayload = Field(default_factory=MapNarrativePayload)
    state_sync: MapStateSyncBundle


class AreaExecuteInteractionResolvedResponse(AreaExecuteInteractionResponse):
    state_sync: MapStateSyncBundle


class TemplateLibraryStatusResponse(BaseModel):
    ok: bool = True
    session_id: str
    template_dir: str
    item_definition_count: int = Field(default=0, ge=0)
    equipment_definition_count: int = Field(default=0, ge=0)
    interactable_template_count: int = Field(default=0, ge=0)
    last_filled_at: str | None = None


class TemplateLibraryFillRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class TemplateLibraryFillResponse(TemplateLibraryStatusResponse):
    appended_item_definition_ids: list[str] = Field(default_factory=list)
    appended_equipment_definition_ids: list[str] = Field(default_factory=list)
    appended_interactable_template_ids: list[str] = Field(default_factory=list)
    updated_item_definition_ids: list[str] = Field(default_factory=list)
    updated_equipment_definition_ids: list[str] = Field(default_factory=list)
    updated_interactable_template_ids: list[str] = Field(default_factory=list)


class RolePoolListResponse(BaseModel):
    session_id: str
    total: int
    items: list[NpcRoleCard] = Field(default_factory=list)


class RoleRelationUpsertRequest(BaseModel):
    relation_tag: str = Field(default="met", min_length=1)
    note: str = Field(default="", min_length=0)


class RoleRelationSetRequest(BaseModel):
    target_role_id: str = Field(..., min_length=1)
    relation_tag: str = Field(default="neutral", min_length=1)
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
    action_reaction: str = Field(default="", min_length=0)
    speech_reply: str = Field(default="", min_length=0)
    talkative_current: int = Field(default=0, ge=0, le=100)
    talkative_maximum: int = Field(default=0, ge=0, le=100)
    time_spent_min: int = Field(ge=1)
    dialogue_logs: list[NpcDialogueEntry] = Field(default_factory=list)
    scene_events: list[SceneEvent] = Field(default_factory=list)


class ActionCheckRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    action_type: Literal["attack", "check", "item_use"] = "check"
    check_mode: Literal["action", "reaction_save"] = "action"
    action_prompt: str = Field(..., min_length=1)
    actor_role_id: str | None = None
    pending_turn_id: str | None = None
    source_label: str | None = None
    threatened_consequence: str | None = None
    forced_dice_roll: int | None = Field(default=None, ge=1, le=20)
    allow_backend_roll: bool = False
    resolution_context: Literal["standalone", "embedded"] = "standalone"
    planned_ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"] | None = None
    planned_dc: int | None = Field(default=None, ge=5, le=30)
    planned_time_spent_min: int | None = Field(default=None, ge=1, le=180)
    planned_requires_check: bool | None = None
    planned_check_task: str | None = None
    return_state_sync: bool = False
    post_trigger_kind: Literal["random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"] | None = None
    config: ChatConfig | None = None


class ActionCheckPlanRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    action_type: Literal["attack", "check", "item_use"] = "check"
    check_mode: Literal["action", "reaction_save"] = "action"
    action_prompt: str = Field(..., min_length=1)
    actor_role_id: str | None = None
    source_label: str | None = None
    threatened_consequence: str | None = None
    config: ChatConfig | None = None


class ActionCheckPlanResponse(BaseModel):
    ok: bool = True
    session_id: str
    actor_role_id: str
    actor_name: str
    actor_kind: Literal["player", "npc"] = "player"
    action_type: Literal["attack", "check", "item_use"]
    check_mode: Literal["action", "reaction_save"] = "action"
    requires_check: bool
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    ability_modifier: int
    dc: int
    time_spent_min: int = Field(ge=1)
    check_task: str = Field(default="", min_length=0)
    source_label: str | None = None
    threatened_consequence: str | None = None


class ActionCheckResponse(BaseModel):
    ok: bool = True
    session_id: str
    actor_role_id: str
    actor_name: str
    actor_kind: Literal["player", "npc"] = "player"
    action_type: Literal["attack", "check", "item_use"]
    check_mode: Literal["action", "reaction_save"] = "action"
    requires_check: bool
    ability_used: Literal["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    ability_modifier: int
    dc: int
    check_task: str = Field(default="", min_length=0)
    source_label: str | None = None
    threatened_consequence: str | None = None
    dice_roll: int | None = None
    total_score: int | None = None
    success: bool
    critical: Literal["none", "critical_success", "critical_failure"] = "none"
    time_spent_min: int = Field(ge=1)
    narrative: str = Field(..., min_length=1)
    applied_effects: list[str] = Field(default_factory=list)
    relation_tag_suggestion: str | None = None
    scene_events: list[SceneEvent] = Field(default_factory=list)
    state_sync: MapStateSyncBundle | None = None
    post_checks: MapPostChecksBundle | None = None


class QuestDraft(BaseModel):
    source: Literal["normal", "fate"] = "normal"
    offer_mode: Literal["accept_reject", "accept_only"] = "accept_reject"
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    issuer_role_id: str | None = None
    zone_id: str | None = None
    sub_zone_id: str | None = None
    fate_id: str | None = None
    fate_phase_id: str | None = None
    entity_refs: list[EntityRef] = Field(default_factory=list)
    objectives: list[QuestObjective] = Field(default_factory=list)
    rewards: list[QuestReward] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class QuestPublishRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    quest: QuestDraft | None = None
    source: Literal["normal", "fate"] = "normal"
    open_modal: bool = True
    config: ChatConfig | None = None


class QuestStateResponse(BaseModel):
    ok: bool = True
    session_id: str
    quest_state: QuestState
    pending_offers: list[QuestEntry] = Field(default_factory=list)
    tracked_quest: QuestEntry | None = None


class QuestMutationResponse(BaseModel):
    ok: bool = True
    session_id: str
    quest_id: str
    status: Literal["pending_offer", "active", "rejected", "completed", "failed", "superseded", "invalidated"]
    chat_feedback: str = Field(default="", min_length=0)
    quest: QuestEntry
    quest_state: QuestState


class QuestEvaluateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    quest_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class QuestActionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class QuestEvaluateAllRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class EncounterCheckRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    trigger_kind: Literal["random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"] = "random_move"
    config: ChatConfig | None = None


class EncounterCheckResponse(BaseModel):
    ok: bool = True
    generated: bool = False
    encounter_id: str | None = None
    blocked_by_higher_priority_modal: bool = False
    encounter: EncounterEntry | None = None


class EncounterPendingResponse(BaseModel):
    ok: bool = True
    session_id: str
    encounter_state: EncounterState
    pending: list[EncounterEntry] = Field(default_factory=list)
    active_encounter: EncounterEntry | None = None


class EncounterHistoryResponse(BaseModel):
    ok: bool = True
    session_id: str
    items: list[EncounterResolution] = Field(default_factory=list)


class EncounterPresentRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class EncounterPresentResponse(BaseModel):
    ok: bool = True
    session_id: str
    encounter_id: str
    status: Literal["queued", "active", "resolved", "escaped", "expired", "invalidated"]
    encounter: EncounterEntry


class EncounterActRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    player_prompt: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class EncounterActResponse(BaseModel):
    ok: bool = True
    session_id: str
    encounter_id: str
    status: Literal["queued", "active", "resolved", "escaped", "expired", "invalidated"]
    reply: str = Field(..., min_length=1)
    time_spent_min: int = Field(default=1, ge=1)
    encounter: EncounterEntry
    resolution: EncounterResolution
    encounter_state: EncounterState


class EncounterForceToggleRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    enabled: bool | None = None


class EncounterForceToggleResponse(BaseModel):
    ok: bool = True
    session_id: str
    enabled: bool
    encounter_state: EncounterState


class EncounterEscapeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class EncounterEscapeResponse(BaseModel):
    ok: bool = True
    session_id: str
    encounter_id: str
    status: Literal["active", "escaped", "resolved", "expired", "invalidated"]
    reply: str = Field(..., min_length=1)
    time_spent_min: int = Field(default=1, ge=1)
    escape_success: bool = False
    encounter: EncounterEntry
    encounter_state: EncounterState
    action_check: ActionCheckResponse | None = None


class EncounterRejoinRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class EncounterRejoinResponse(BaseModel):
    ok: bool = True
    session_id: str
    encounter_id: str
    status: Literal["active", "escaped", "resolved", "expired", "invalidated"]
    reply: str = Field(..., min_length=1)
    encounter: EncounterEntry
    encounter_state: EncounterState


class EncounterDebugOverviewResponse(BaseModel):
    ok: bool = True
    session_id: str
    active_encounter: EncounterEntry | None = None
    queued_encounters: list[EncounterEntry] = Field(default_factory=list)
    summary: str = Field(default="", min_length=0)


class FateGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class FateCurrentResponse(BaseModel):
    ok: bool = True
    session_id: str
    fate_state: FateState


class FateGenerateResponse(BaseModel):
    ok: bool = True
    session_id: str
    fate_id: str | None = None
    generated: bool = False
    fate: FateLine | None = None


class FateEvaluateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class FateEvaluateResponse(BaseModel):
    ok: bool = True
    session_id: str
    fate_state: FateState
    advanced: bool = False
    generated_quest_id: str | None = None


class StorySnapshotResponse(BaseModel):
    ok: bool = True
    session_id: str
    snapshot: GlobalStorySnapshot


class ReputationStateResponse(BaseModel):
    ok: bool = True
    session_id: str
    reputation_state: ReputationState
    current_entry: SubZoneReputationEntry | None = None


class RoleDrivesResponse(BaseModel):
    ok: bool = True
    session_id: str
    scope: Literal["role", "team", "current_sub_zone"] = "current_sub_zone"
    items: list[RoleDriveSummary] = Field(default_factory=list)


class PublicSceneStateResponse(BaseModel):
    ok: bool = True
    session_id: str
    public_scene_state: PublicSceneState


class NpcKnowledgeResponse(BaseModel):
    ok: bool = True
    session_id: str
    npc_role_id: str
    snapshot: NpcKnowledgeSnapshot


class TeamStateResponse(BaseModel):
    ok: bool = True
    session_id: str
    team_state: TeamState
    members: list[TeamMember] = Field(default_factory=list)


class TeamInviteRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    npc_role_id: str = Field(..., min_length=1)
    player_prompt: str = Field(default="", min_length=0)
    config: ChatConfig | None = None


class TeamLeaveRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    npc_role_id: str = Field(..., min_length=1)
    reason: str = Field(default="", min_length=0)
    config: ChatConfig | None = None


class TeamDebugGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class TeamMutationResponse(BaseModel):
    ok: bool = True
    session_id: str
    team_state: TeamState
    member: TeamMember | None = None
    role: NpcRoleCard | None = None
    accepted: bool = True
    chat_feedback: str = Field(default="", min_length=0)


class TeamChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    player_message: str = Field(..., min_length=1)
    config: ChatConfig | None = None


class TeamChatReply(BaseModel):
    member_role_id: str = Field(..., min_length=1)
    member_name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    response_mode: Literal["speech", "action"] = "speech"
    affinity_delta: int = 0
    trust_delta: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TeamChatResponse(BaseModel):
    ok: bool = True
    session_id: str
    player_message: str = Field(..., min_length=1)
    replies: list[TeamChatReply] = Field(default_factory=list)
    team_state: TeamState
    time_spent_min: int = Field(default=1, ge=1)


class EntityIndexResponse(BaseModel):
    ok: bool = True
    session_id: str
    world_revision: int
    map_revision: int
    zone_ids: list[str] = Field(default_factory=list)
    sub_zone_ids: list[str] = Field(default_factory=list)
    npc_ids: list[str] = Field(default_factory=list)
    quest_ids: list[str] = Field(default_factory=list)
    encounter_ids: list[str] = Field(default_factory=list)
    fate_phase_ids: list[str] = Field(default_factory=list)


class ConsistencyRunRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class ConsistencyStatusResponse(BaseModel):
    ok: bool = True
    session_id: str
    world_state: WorldState
    issue_count: int = 0
    issues: list[ConsistencyIssue] = Field(default_factory=list)


class ConsistencyRunResponse(BaseModel):
    ok: bool = True
    session_id: str
    world_state: WorldState
    issue_count: int = 0
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    changed: bool = False


class InventoryOwnerRef(BaseModel):
    owner_type: Literal["player", "role"]
    role_id: str | None = None

    @model_validator(mode="after")
    def validate_owner(self) -> "InventoryOwnerRef":
        if self.owner_type == "player" and self.role_id:
            raise ValueError("player owner must not include role_id")
        if self.owner_type == "role" and not (self.role_id or "").strip():
            raise ValueError("role owner requires role_id")
        if self.owner_type == "player":
            self.role_id = None
        elif self.role_id is not None:
            self.role_id = self.role_id.strip()
        return self


class InventoryEquipRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    owner: InventoryOwnerRef
    item_id: str = Field(..., min_length=1)
    slot: Literal["weapon", "armor"]


class InventoryUnequipRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    owner: InventoryOwnerRef
    slot: Literal["weapon", "armor"]


class InventoryMutationResponse(BaseModel):
    ok: bool = True
    session_id: str
    owner: InventoryOwnerRef
    message: str = Field(default="", min_length=0)
    item_id: str | None = None
    amount_changed: int = 0
    quantity_after: int | None = None
    uses_left_after: int | None = None
    player: PlayerStaticData | None = None
    role: NpcRoleCard | None = None


class InventoryGrantRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    owner: InventoryOwnerRef
    item: InventoryItem
    reason: str = Field(default="", min_length=0)


class InventoryConsumeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    owner: InventoryOwnerRef
    item_id: str = Field(..., min_length=1)
    amount: int = Field(default=1, ge=1)
    reason: str = Field(default="", min_length=0)
    consume_mode: Literal["auto", "quantity", "uses"] = "auto"


class InventoryInteractRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    owner: InventoryOwnerRef
    item_id: str = Field(..., min_length=1)
    mode: Literal["inspect", "use"] = "inspect"
    prompt: str = Field(default="", min_length=0)
    action_check: ActionCheckResponse | None = None
    config: ChatConfig | None = None


class InventoryInteractResponse(BaseModel):
    ok: bool = True
    session_id: str
    owner: InventoryOwnerRef
    item_id: str = Field(..., min_length=1)
    mode: Literal["inspect", "use"]
    reply: str = Field(..., min_length=1)
    time_spent_min: int = Field(default=1, ge=1)
    action_check: ActionCheckResponse | None = None
    player: PlayerStaticData | None = None
    role: NpcRoleCard | None = None
    scene_events: list[SceneEvent] = Field(default_factory=list)


class PlayerEquipRequest(BaseModel):
    item_id: str = Field(..., min_length=1)
    slot: Literal["weapon", "armor"]


class PlayerUnequipRequest(BaseModel):
    slot: Literal["weapon", "armor"]


class PlayerBuffAddRequest(BaseModel):
    buff: RoleBuff


class PlayerBuffRemoveRequest(BaseModel):
    buff_id: str = Field(..., min_length=1)


class PlayerItemAddRequest(BaseModel):
    item: InventoryItem


class PlayerItemRemoveRequest(BaseModel):
    item_id: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1)


class PlayerSpellSetRequest(BaseModel):
    value: str = Field(..., min_length=1)


class PlayerSkillSetRequest(BaseModel):
    value: str = Field(..., min_length=1)


class PlayerSpellSlotAdjustRequest(BaseModel):
    level: int = Field(..., ge=1, le=9)
    amount: int = Field(default=1, ge=1, le=9)


class PlayerStaminaAdjustRequest(BaseModel):
    amount: int = Field(default=1, ge=1)


class DeathStatusResponse(BaseModel):
    """获取当前死亡状态响应"""
    ok: bool = True
    session_id: str
    life_status: Literal["healthy", "dying", "stable", "dead"] = "healthy"
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)
    can_be_stabilized: bool = False
    nearby_medical_items: list[str] = Field(default_factory=list)
    nearby_allies: list[str] = Field(default_factory=list)


class StabilizeRequest(BaseModel):
    """尝试稳定濒死玩家请求"""
    session_id: str = Field(..., min_length=1)
    target_player_id: str = Field(..., min_length=1)
    method: Literal["medicine_check", "healing_kit", "spell"] = "medicine_check"
    item_instance_id: str | None = None
    medic_role_id: str | None = None


class StabilizeResponse(BaseModel):
    """尝试稳定濒死玩家响应"""
    ok: bool = True
    session_id: str
    success: bool
    stabilized: bool
    roll_result: BattleRollResolution | None = None
    narrative: str = Field(default="", min_length=0)
    scene_events: list[SceneEvent] = Field(default_factory=list)


class ReviveRequest(BaseModel):
    """执行复活请求"""
    session_id: str = Field(..., min_length=1)
    method: Literal["shrine", "item", "teammate"] = "shrine"
    shrine_zone_id: str | None = None
    item_instance_id: str | None = None
    teammate_role_id: str | None = None


class ReviveResponse(BaseModel):
    """执行复活响应"""
    ok: bool = True
    session_id: str
    success: bool
    method: str = "shrine"
    penalties_applied: DeathPenalties = Field(default_factory=DeathPenalties)
    narrative: str = Field(default="", min_length=0)
    scene_events: list[SceneEvent] = Field(default_factory=list)
    state_sync: MapStateSyncBundle | None = None


class DeathDeclareRequest(BaseModel):
    """宣告玩家死亡请求（调试/剧情用）"""
    session_id: str = Field(..., min_length=1)
    cause: str = Field(default="", min_length=0)
    is_instant: bool = False


class DeathDeclareResponse(BaseModel):
    """宣告玩家死亡响应"""
    ok: bool = True
    session_id: str
    declared: bool
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)
    scene_events: list[SceneEvent] = Field(default_factory=list)


RoleDesire.model_rebuild()
PublicSceneState.model_rebuild()
EncounterEntry.model_rebuild()
ChatResponse.model_rebuild()
PendingTurnContinueResponse.model_rebuild()
