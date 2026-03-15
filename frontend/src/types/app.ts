export type UIConfig = {
  theme: string;
};

export type AIProvider = 'openai' | 'deepseek' | 'gemini';

export type AppRuntimeConfig = {
  temperature?: number;
  max_tokens?: number;
  max_completion_tokens?: number;
  structured_output_mode?: 'auto' | 'legacy_tags';
};

export type SubZoneDebugConfig = {
  small_min_count: number;
  small_max_count: number;
  medium_min_count: number;
  medium_max_count: number;
  large_min_count: number;
  large_max_count: number;
  discover_interaction_limit: number;
};

export type PublicSceneConfig = {
  active_actor_limit: number;
  idle_actor_limit: number;
  max_world_pushes: number;
  uncertain_actions_require_check: boolean;
};

export type ProviderScopedConfig = {
  api_key: string;
  base_url_override?: string | null;
  model: string;
  runtime: AppRuntimeConfig;
};

export type ProviderConfigMap = Record<AIProvider, ProviderScopedConfig>;

export type AppConfig = {
  version: string;
  provider: AIProvider;
  api_key: string;
  base_url_override?: string | null;
  model: string;
  stream: boolean;
  runtime: AppRuntimeConfig;
  provider_configs: ProviderConfigMap;
  gm_prompt: string;
  speech_time_per_50_tokens_min: number;
  sub_zone_debug: SubZoneDebugConfig;
  public_scene: PublicSceneConfig;
  ui?: UIConfig;
};

export type ModelCapabilityProfile =
  | 'openai_gpt5'
  | 'openai_standard'
  | 'deepseek_chat'
  | 'deepseek_reasoner'
  | 'gemini_openai_compatible'
  | 'generic_compatible';

export type ModelCapabilityInfo = {
  id: string;
  label: string;
  capability_profile: ModelCapabilityProfile;
  supported_params: Array<'temperature' | 'max_tokens' | 'max_completion_tokens'>;
  defaults: Record<string, string | number | boolean>;
  warning?: string | null;
};

export type ValidateConfigResponse = {
  valid: boolean;
  errors: Array<{ field: string; message: string }>;
  normalized_config?: AppConfig | null;
};

export type ModelDiscoverResponse = {
  models: ModelCapabilityInfo[];
};

export type ModelProfileResponse = {
  model: ModelCapabilityInfo;
};

export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type Usage = {
  input_tokens: number;
  output_tokens: number;
};

export type TokenUsageBucket = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

export type TokenUsageSummary = {
  session_id: string;
  total: TokenUsageBucket;
  sources: {
    chat: TokenUsageBucket;
    map_generation: TokenUsageBucket;
    movement_narration: TokenUsageBucket;
  };
};

export type ChatResponse = {
  session_id: string;
  reply: ChatMessage;
  usage: Usage;
  tool_events?: ToolEvent[];
  scene_events?: SceneEvent[];
  time_spent_min: number;
  archived_sub_zone_turn_id?: string | null;
  main_turn_summary?: MainTurnSummary | null;
  current_zone_metric?: ZoneMetricEntry | null;
};

export type PlayerReactionCheck = {
  reaction_id: string;
  source_kind: 'npc_action' | 'environment' | 'world_push' | 'encounter_effect' | 'npc_chat' | 'map_arrival';
  source_actor_id?: string | null;
  source_actor_name?: string | null;
  source_label: string;
  trigger_summary: string;
  threatened_consequence: string;
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  dc: number;
  check_task: string;
  resolution_context: 'main_chat' | 'encounter' | 'npc_chat' | 'map_move';
  success_hint: string;
  failure_hint: string;
  critical_success_hint: string;
  critical_failure_hint: string;
};

export type PendingTurnContinueResponse = {
  session_id: string;
  pending_turn_id?: string | null;
  flow_kind: 'main_chat' | 'encounter' | 'npc_chat' | 'map_move';
  status: 'awaiting_reaction' | 'completed' | 'cancelled';
  reply_text: string;
  scene_events: SceneEvent[];
  tool_events: ToolEvent[];
  main_turn_summary?: MainTurnSummary | null;
  current_zone_metric?: ZoneMetricEntry | null;
  pending_reaction?: PlayerReactionCheck | null;
  reaction_result?: ActionCheckResult | null;
  archived_sub_zone_turn_id?: string | null;
  npc_role_id?: string | null;
};

export type BattleDamageProfile = {
  dice: string;
  damage_type: string;
  flat_bonus: number;
};

export type BattleFieldState = {
  zone_id?: string | null;
  zone_name: string;
  sub_zone_id?: string | null;
  sub_zone_name: string;
  description: string;
  feature_tags: string[];
  danger_score?: number | null;
  reputation_score?: number | null;
};

export type BattleStepEntry = {
  step_id: string;
  round: number;
  kind:
    | 'setup'
    | 'initiative'
    | 'turn_start'
    | 'attack'
    | 'damage'
    | 'move'
    | 'defend'
    | 'disengage'
    | 'escape'
    | 'observe'
    | 'item_use'
    | 'reaction_prompt'
    | 'reaction_result'
    | 'defeat'
    | 'end'
    | 'system';
  actor_combatant_id?: string | null;
  actor_name: string;
  content: string;
  metadata: Record<string, string | number | boolean>;
  created_at: string;
};

export type CombatantState = {
  combatant_id: string;
  source_kind: 'player' | 'team' | 'npc' | 'test_monster';
  role_id?: string | null;
  display_name: string;
  side: 'player_side' | 'enemy_side';
  template_id?: string | null;
  role_kind: 'brute' | 'skirmisher' | 'ranged' | 'support' | 'beast' | 'adventurer';
  ai_style: string;
  level_hint: number;
  max_hp: number;
  current_hp: number;
  temp_hp: number;
  base_armor_class: number;
  armor_class: number;
  speed: number;
  initiative: number;
  initiative_bonus: number;
  attack_bonus: number;
  damage_profile: BattleDamageProfile;
  ability_modifiers: Dnd5eAbilityModifiers;
  saving_throw_bonuses: Dnd5eAbilityModifiers;
  position_band: 'engaged' | 'near' | 'far' | 'remote';
  position_feature_tags: string[];
  action_available: boolean;
  bonus_action_available: boolean;
  reaction_available: boolean;
  movement_remaining: number;
  conditions: string[];
  alive: boolean;
  downed: boolean;
  escaped: boolean;
  temporary_ac_bonus: number;
  next_attack_bonus_against?: string | null;
  next_attack_bonus_amount: number;
  inventory_item_instance_ids?: string[];
  equipped_weapon_instance_id?: string | null;
  equipped_armor_instance_id?: string | null;
  equipped_shield_instance_id?: string | null;
  inventory_items: InventoryItem[];
};

export type CombatState = {
  round: number;
  phase: 'initiative' | 'turn' | 'resolution' | 'ended';
  active_combatant_id?: string | null;
  initiative_order: string[];
  momentum_value: number;
  combatants: CombatantState[];
  recent_steps: BattleStepEntry[];
  winner_side?: 'player_side' | 'enemy_side' | 'escaped' | 'cancelled' | null;
};

export type BattleRollPrompt = {
  prompt_id: string;
  roll_kind: 'initiative' | 'attack' | 'observe' | 'escape' | 'reaction' | 'item_use';
  actor_combatant_id: string;
  actor_name: string;
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier: number;
  dc: number;
  check_task: string;
  source_label?: string | null;
  threatened_consequence?: string | null;
  success_hint?: string | null;
  failure_hint?: string | null;
  target_combatant_id?: string | null;
  action_name: string;
  metadata: Record<string, string | number | boolean>;
};

export type BattleRollResolution = {
  prompt_id: string;
  actor_combatant_id: string;
  actor_name: string;
  roll_kind: 'initiative' | 'attack' | 'observe' | 'escape' | 'reaction' | 'item_use';
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier: number;
  dc: number;
  dice_roll: number;
  total_score: number;
  success: boolean;
  critical: 'none' | 'critical_success' | 'critical_failure';
  summary: string;
};

export type BattleUiFlags = {
  ai_pacing: 'step' | 'auto';
  can_continue_ai: boolean;
};

export type BattleSandboxState = {
  battle_id: string;
  session_id: string;
  status: 'setup' | 'active' | 'awaiting_player_action' | 'awaiting_player_roll' | 'awaiting_ai_continue' | 'ended' | 'cancelled';
  source_kind: 'debug_template' | 'debug_ai_generated';
  created_at: string;
  updated_at: string;
  battlefield: BattleFieldState;
  player_snapshot: CombatantState;
  ally_snapshots: CombatantState[];
  enemy_snapshots: CombatantState[];
  combat_state: CombatState;
  pending_roll?: BattleRollPrompt | null;
  last_roll_result?: BattleRollResolution | null;
  battle_logs: BattleStepEntry[];
  ui_flags: BattleUiFlags;
};

export type BattleStartRequest = {
  session_id: string;
  mode: 'template' | 'ai_generated';
  template_group?: string | null;
  ai_scale: 'single' | 'squad';
  ai_strength: 'weak' | 'standard' | 'strong';
  ai_pacing: 'step' | 'auto';
  config?: AppConfig | null;
};

export type BattleStartResponse = {
  ok: boolean;
  session_id: string;
  battle: BattleSandboxState;
};

export type BattleActionRequest = {
  session_id: string;
  action_kind: 'attack' | 'defend' | 'move' | 'disengage' | 'escape' | 'use_item' | 'observe' | 'end_turn';
  target_combatant_id?: string | null;
  destination_band?: 'engaged' | 'near' | 'far' | 'remote' | null;
  item_id?: string | null;
};

export type BattleActionResponse = {
  ok: boolean;
  session_id: string;
  battle: BattleSandboxState;
};

export type BattleContinueAiRequest = {
  session_id: string;
  ai_pacing?: 'step' | 'auto' | null;
};

export type BattleContinueAiResponse = {
  ok: boolean;
  session_id: string;
  battle: BattleSandboxState;
};

export type BattleResolveRollRequest = {
  session_id: string;
  forced_dice_roll: number;
};

export type BattleResolveRollResponse = {
  ok: boolean;
  session_id: string;
  battle: BattleSandboxState;
  roll_result?: BattleRollResolution | null;
};

export type BattleCurrentResponse = {
  ok: boolean;
  session_id: string;
  battle?: BattleSandboxState | null;
};

export type BattleEndResponse = {
  ok: boolean;
  session_id: string;
  battle_id?: string | null;
  ended: boolean;
};

export type ToolEvent = {
  tool_name: string;
  ok: boolean;
  summary: string;
  payload: Record<string, string | number | boolean>;
};

export type StreamPhaseCode =
  | 'prepare'
  | 'intent_route'
  | 'tool_plan'
  | 'tool_run'
  | 'model_reply'
  | 'bundle_parse'
  | 'apply'
  | 'commit'
  | 'rollback';

export type StreamPhaseEvent = {
  code: StreamPhaseCode;
  label: string;
  status: 'running' | 'done' | 'failed';
  detail: string;
};

export type LiveToolEvent = {
  tool_name: string;
  status: 'running' | 'done' | 'failed';
  summary: string;
  payload: Record<string, string | number | boolean>;
};

export type TurnRollbackPayload = {
  reason: string;
  message: string;
  discarded: true;
};

export type LiveProgressEntry = {
  id: string;
  kind: 'phase' | 'tool';
  label: string;
  status: 'running' | 'done' | 'failed';
  detail: string;
};

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type PublicActorCheckResult = {
  requires_check: boolean;
  ability_used?: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier?: number;
  dice_roll?: number | null;
  total_score?: number | null;
  dc?: number;
  success?: boolean;
  critical?: 'none' | 'critical_success' | 'critical_failure';
  outcome_label?: '无需检定' | '成功' | '失败' | '大成功' | '大失败';
};

export type PublicActorActionMetadata = {
  response_mode?: 'respond' | 'ignore' | 'none';
  incoming_from_actor_id?: string;
  incoming_from_actor_name?: string;
  incoming_summary?: string;
  incoming_reaction_narration?: string;
  incoming_reaction_speech?: string;
  ignore_reason?: string;
  external_action_narration?: string;
  speech_line?: string;
  visible_intent?: string;
  private_goal?: string;
  private_reason?: string;
  expression_cues?: string;
  body_language?: string;
  risk_source?: string;
  risk_object?: string;
  risk_location?: string;
  affiliation_kind?: 'team' | 'public_npc' | 'encounter_temp_npc';
  affiliation_label?: '队友' | '在场NPC' | '遭遇NPC';
  specific_threat?: string;
  target_label?: string;
  needs_check?: boolean;
  action_type?: 'check' | 'attack' | 'item_use';
  situation_delta_hint?: number;
  situation_delta?: number;
  actor_type?: 'npc' | 'team' | 'encounter_temp_npc' | 'system';
  checked_action_label?: string;
  checked_action_prompt?: string;
  gm_result_summary?: string;
  team_affinity_before?: number;
  team_affinity_after?: number;
  team_affinity_delta?: number;
  team_trust_before?: number;
  team_trust_after?: number;
  team_trust_delta?: number;
  check_result?: PublicActorCheckResult;
};

export type PublicActorResolutionMetadata = {
  actor_type?: 'npc' | 'team' | 'encounter_temp_npc' | 'system';
  success?: boolean;
  critical?: 'none' | 'critical_success' | 'critical_failure';
  situation_delta?: number;
  relation_delta?: number;
  reputation_delta?: number;
  affected_object?: string;
  concrete_effect?: string;
  opened_opportunity?: string;
  new_pressure?: string;
};

export type PublicRoundResolutionRow = {
  actor_id: string;
  actor_name: string;
  result: string;
  affected_object: string;
  concrete_effect: string;
  opened_opportunity: string;
  new_pressure: string;
  situation_delta?: number;
  relation_delta?: number;
  reputation_delta?: number;
};

export type PublicRoundResolutionMetadata = {
  actor_type?: 'system';
  candidate_count?: number;
  reputation_score?: number;
  situation_value_before?: number;
  situation_value_after?: number;
  direction?: 'stabilize' | 'hold' | 'worsen';
  trend?: 'improving' | 'stable' | 'worsening';
  result_rows?: PublicRoundResolutionRow[];
  team_relation_rows?: Array<{
    role_id: string;
    name: string;
    affinity_before: number;
    affinity_after: number;
    affinity_delta: number;
    trust_before: number;
    trust_after: number;
    trust_delta: number;
  }>;
};

export type EncounterSituationMetadata = {
  encounter_id?: string;
  encounter_title?: string;
  situation_value?: number;
  situation_delta?: number;
  situation_value_before?: number;
  player_situation_delta?: number;
  public_actor_situation_delta_total?: number;
  world_push_situation_delta_total?: number;
  turn_total_delta?: number;
  situation_value_after?: number;
  direction?: 'stabilize' | 'hold' | 'worsen';
  trend?: 'improving' | 'stable' | 'worsening';
  summary_basis?: 'numeric' | 'fallback';
  actor_type?: 'npc' | 'team' | 'encounter_temp_npc' | 'system';
};

export type EncounterWorldPushMetadata = {
  encounter_id?: string;
  encounter_title?: string;
  push_kind?: 'new_clue' | 'environment_shift' | 'hazard_escalation' | 'pressure_release' | 'faction_move' | 'npc_arrival';
  opened_window?: string;
  pressure_note?: string;
  situation_delta_hint?: number;
  spawned_role_id?: string;
  spawned_npc_name?: string;
  target_zone_id?: string;
  target_sub_zone_id?: string;
  target_location_label?: string;
  generated_zone?: boolean;
  generated_sub_zone?: boolean;
};

export type SceneEvent = {
  event_id: string;
  kind:
    | 'public_targeted_npc_reply'
    | 'public_bystander_reaction'
    | 'team_public_reaction'
    | 'public_actor_action'
    | 'public_actor_resolution'
    | 'public_round_resolution'
    | 'role_desire_surface'
    | 'companion_story_surface'
    | 'reputation_update'
    | 'encounter_started'
    | 'encounter_progress'
    | 'encounter_resolution'
    | 'encounter_background'
    | 'encounter_situation_update'
    | 'encounter_world_push'
    | 'player_reaction_triggered'
    | 'player_reaction_result';
  actor_role_id: string | null;
  actor_name: string;
  content: string;
  metadata: Record<string, JsonValue>;
  created_at: string;
};

export type ApiDebugEntry = {
  endpoint: string;
  status: number;
  ok: boolean;
  at: string;
  usage?: Usage;
  detail?: string;
};

export type PathStatus = {
  path: string;
  exists: boolean;
  writable: boolean;
};

export type Position = {
  x: number;
  y: number;
  z: number;
  zone_id: string;
};

export type Zone = {
  zone_id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  zone_type: string;
  size: 'small' | 'medium' | 'large';
  radius_m: number;
  description: string;
  tags: string[];
  sub_zones: Array<{
    name: string;
    offset_x: number;
    offset_y: number;
    offset_z: number;
    description: string;
  }>;
};

export type MapSnapshot = {
  player_position: Position | null;
  zones: Zone[];
};

export type PlayerStaticData = {
  player_id: string;
  name: string;
  move_speed_mph: number;
  role_type: 'player' | 'npc' | 'monster';
  dnd5e_sheet: Dnd5eCharacterSheet;
};

export type PlayerRuntimeData = {
  session_id: string;
  current_position: Position | null;
  updated_at: string;
};

export type SaveFile = {
  version: string;
  session_id: string;
  world_state: WorldState;
  map_snapshot: MapSnapshot;
  area_snapshot: AreaSnapshot;
  game_logs: GameLogEntry[];
  game_log_settings: GameLogSettings;
  player_static_data: PlayerStaticData;
  player_runtime_data: PlayerRuntimeData;
  role_pool: NpcRoleCard[];
  team_state: TeamState;
  reputation_state: ReputationState;
  zone_metric_state: ZoneMetricState;
  travel_companion_state: TravelCompanionState;
  quest_state: QuestState;
  encounter_state: EncounterState;
  fate_state: FateState;
  updated_at: string;
};

export type SubZoneReputationEntry = {
  sub_zone_id: string;
  zone_id: string | null;
  score: number;
  band: 'hostile' | 'cold' | 'neutral' | 'trusted' | 'favored';
  recent_reasons: string[];
  updated_at: string;
};

export type ReputationState = {
  version: string;
  entries: SubZoneReputationEntry[];
  updated_at: string;
};

export type QuestObjective = {
  objective_id: string;
  kind: 'reach_zone' | 'talk_to_npc' | 'obtain_item' | 'resolve_encounter' | 'complete_quest' | 'manual_text';
  title: string;
  description: string;
  target_ref: Record<string, string | number | boolean>;
  progress_current: number;
  progress_target: number;
  status: 'pending' | 'in_progress' | 'completed';
  completed_at: string | null;
};

export type QuestReward = {
  reward_id: string;
  kind: 'gold' | 'item' | 'relation' | 'flag' | 'none';
  label: string;
  payload: Record<string, string | number | boolean>;
};

export type QuestLogEntry = {
  id: string;
  kind: 'offer' | 'accept' | 'reject' | 'progress' | 'complete' | 'fail' | 'system';
  message: string;
  created_at: string;
};

export type QuestEntry = {
  quest_id: string;
  source: 'normal' | 'fate';
  offer_mode: 'accept_reject' | 'accept_only';
  title: string;
  description: string;
  issuer_role_id: string | null;
  zone_id: string | null;
  sub_zone_id: string | null;
  fate_id: string | null;
  fate_phase_id: string | null;
  source_world_revision: number;
  source_map_revision: number;
  entity_refs: EntityRef[];
  invalidated_reason: string | null;
  status: 'pending_offer' | 'active' | 'rejected' | 'completed' | 'failed' | 'superseded' | 'invalidated';
  is_tracked: boolean;
  objectives: QuestObjective[];
  rewards: QuestReward[];
  logs: QuestLogEntry[];
  offered_at: string;
  accepted_at: string | null;
  rejected_at: string | null;
  completed_at: string | null;
  metadata: Record<string, string | number | boolean>;
};

export type QuestState = {
  version: string;
  tracked_quest_id: string | null;
  quests: QuestEntry[];
  updated_at: string;
};

export type QuestStateResponse = {
  ok: boolean;
  session_id: string;
  quest_state: QuestState;
  pending_offers: QuestEntry[];
  tracked_quest: QuestEntry | null;
};

export type QuestMutationResponse = {
  ok: boolean;
  session_id: string;
  quest_id: string;
  status: 'pending_offer' | 'active' | 'rejected' | 'completed' | 'failed' | 'superseded' | 'invalidated';
  chat_feedback: string;
  quest: QuestEntry;
  quest_state: QuestState;
};

export type EncounterEntry = {
  encounter_id: string;
  type: 'npc' | 'event' | 'anomaly';
  source_world_revision: number;
  source_map_revision: number;
  entity_refs: EntityRef[];
  invalidated_reason: string | null;
  status: 'queued' | 'active' | 'resolved' | 'escaped' | 'expired' | 'invalidated';
  trigger_kind: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced';
  encounter_mode: 'standard' | 'npc_initiated_chat';
  title: string;
  description: string;
  zone_id: string | null;
  sub_zone_id: string | null;
  npc_role_id: string | null;
  player_presence: 'engaged' | 'away';
  related_quest_ids: string[];
  related_fate_phase_ids: string[];
  participant_role_ids: string[];
  temporary_npcs: EncounterTemporaryNpc[];
  generated_prompt_tags: string[];
  allow_player_prompt: boolean;
  termination_conditions: EncounterTerminationCondition[];
  steps: EncounterStepEntry[];
  scene_summary: string;
  latest_outcome_summary: string;
  situation_start_value: number;
  situation_value: number;
  situation_trend: 'improving' | 'stable' | 'worsening';
  last_outcome_package: EncounterOutcomePackage | null;
  background_tick_count: number;
  created_at: string;
  presented_at: string | null;
  resolved_at: string | null;
  last_advanced_at: string | null;
};

export type EncounterTerminationCondition = {
  condition_id: string;
  kind: 'npc_leaves' | 'player_escapes' | 'target_resolved' | 'time_elapsed' | 'manual_custom';
  description: string;
  satisfied: boolean;
  satisfied_at: string | null;
};

export type EncounterStepEntry = {
  step_id: string;
  kind: 'announcement' | 'player_action' | 'gm_update' | 'npc_reaction' | 'team_reaction' | 'temp_npc_action' | 'escape_attempt' | 'background_tick' | 'world_push' | 'resolution';
  actor_type: 'player' | 'npc' | 'team' | 'encounter_temp_npc' | 'system';
  actor_id: string;
  actor_name: string;
  content: string;
  metadata?: Record<string, JsonValue>;
  created_at: string;
};

export type EncounterTemporaryNpc = {
  encounter_npc_id: string;
  name: string;
  title: string;
  description: string;
  speaking_style: string;
  agenda: string;
  state: string;
  zone_id?: string | null;
  sub_zone_id?: string | null;
  introduced_at: string;
};

export type MainTurnSummary = {
  player_situation_delta: number;
  public_actor_situation_delta_total: number;
  world_push_situation_delta_total: number;
  turn_total_delta: number;
  situation_value_before?: number | null;
  situation_value_after?: number | null;
};

export type ZoneMetricEntry = {
  zone_id: string;
  zone_name: string;
  reputation_score: number;
  reputation_band: 'hostile' | 'cold' | 'neutral' | 'trusted' | 'favored';
  danger_score: number;
  danger_band: 'low' | 'medium' | 'high';
  reputation_reasons: string[];
  danger_reasons: string[];
  seed_source: 'ai_generated' | 'migration_backfill' | 'system_default';
  updated_at: string;
};

export type ZoneMetricState = {
  version: string;
  entries: ZoneMetricEntry[];
  updated_at: string;
};

export type TravelCompanionEntry = {
  role_id: string;
  role_name: string;
  source_kind: 'npc' | 'team';
  destination_zone_id: string;
  destination_sub_zone_id?: string | null;
  follow_until_arrival: boolean;
  declared_at: string;
};

export type TravelCompanionState = {
  version: string;
  companions: TravelCompanionEntry[];
  updated_at: string;
};

export type EncounterResolution = {
  encounter_id: string;
  player_prompt: string;
  reply: string;
  time_spent_min: number;
  quest_updates: string[];
  situation_delta: number;
  situation_value_after: number;
  reputation_delta: number;
  applied_outcome_summaries: string[];
  created_at: string;
};

export type EncounterOutcomeChange = {
  target_id: string;
  delta: number;
  summary: string;
};

export type EncounterOutcomePackage = {
  result: 'success' | 'failure';
  reputation_delta: number;
  zone_reputation_delta: number;
  zone_danger_delta: number;
  npc_relation_deltas: EncounterOutcomeChange[];
  team_deltas: EncounterOutcomeChange[];
  item_rewards: InventoryItem[];
  buff_rewards: RoleBuff[];
  resource_deltas: string[];
  narrative_summary: string;
};

export type EncounterState = {
  version: string;
  pending_ids: string[];
  active_encounter_id: string | null;
  encounters: EncounterEntry[];
  history: EncounterResolution[];
  debug_force_trigger: boolean;
  updated_at: string;
};

export type EncounterCheckResponse = {
  ok: boolean;
  generated: boolean;
  encounter_id: string | null;
  blocked_by_higher_priority_modal: boolean;
  encounter: EncounterEntry | null;
};

export type EncounterPendingResponse = {
  ok: boolean;
  session_id: string;
  encounter_state: EncounterState;
  pending: EncounterEntry[];
  active_encounter: EncounterEntry | null;
};

export type EncounterActResponse = {
  ok: boolean;
  session_id: string;
  encounter_id: string;
  status: 'queued' | 'active' | 'resolved' | 'escaped' | 'expired' | 'invalidated';
  reply: string;
  time_spent_min: number;
  encounter: EncounterEntry;
  resolution: EncounterResolution;
  encounter_state: EncounterState;
};

export type EncounterEscapeResponse = {
  ok: boolean;
  session_id: string;
  encounter_id: string;
  status: 'queued' | 'active' | 'resolved' | 'escaped' | 'expired' | 'invalidated';
  reply: string;
  time_spent_min: number;
  escape_success: boolean;
  encounter: EncounterEntry;
  encounter_state: EncounterState;
  action_check: ActionCheckResult | null;
};

export type EncounterRejoinResponse = {
  ok: boolean;
  session_id: string;
  encounter_id: string;
  status: 'queued' | 'active' | 'resolved' | 'escaped' | 'expired' | 'invalidated';
  reply: string;
  encounter: EncounterEntry;
  encounter_state: EncounterState;
};

export type EncounterDebugOverviewResponse = {
  ok: boolean;
  session_id: string;
  active_encounter: EncounterEntry | null;
  queued_encounters: EncounterEntry[];
  summary: string;
};

export type FateTriggerCondition = {
  condition_id: string;
  kind: 'manual' | 'days_elapsed' | 'met_npc' | 'obtained_item' | 'resolved_encounter' | 'completed_quest';
  description: string;
  payload: Record<string, string | number | boolean>;
  satisfied: boolean;
  satisfied_at: string | null;
};

export type FatePhase = {
  phase_id: string;
  index: number;
  title: string;
  description: string;
  source_world_revision: number;
  source_map_revision: number;
  bound_entity_refs: EntityRef[];
  invalidated_reason: string | null;
  status: 'locked' | 'ready' | 'quest_offered' | 'quest_active' | 'completed';
  trigger_conditions: FateTriggerCondition[];
  triggered_at: string | null;
  bound_quest_id: string | null;
  completed_at: string | null;
};

export type FateLine = {
  fate_id: string;
  title: string;
  summary: string;
  source_world_revision: number;
  source_map_revision: number;
  bound_entity_refs: EntityRef[];
  invalidated_reason: string | null;
  status: 'not_generated' | 'active' | 'completed' | 'superseded' | 'invalidated';
  current_phase_id: string | null;
  phases: FatePhase[];
  generated_at: string;
  updated_at: string;
};

export type FateState = {
  version: string;
  current_fate: FateLine | null;
  archive: FateLine[];
  updated_at: string;
};

export type FateCurrentResponse = {
  ok: boolean;
  session_id: string;
  fate_state: FateState;
};

export type FateGenerateResponse = {
  ok: boolean;
  session_id: string;
  fate_id: string | null;
  generated: boolean;
  fate: FateLine | null;
};

export type FateEvaluateResponse = {
  ok: boolean;
  session_id: string;
  fate_state: FateState;
  advanced: boolean;
  generated_quest_id: string | null;
};

export type Coord3D = {
  x: number;
  y: number;
  z: number;
};

export type WorldClock = {
  calendar: string;
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  updated_at: string;
};

export type AreaInteraction = {
  interaction_id: string;
  name: string;
  type: 'item' | 'npc' | 'scene';
  status: 'ready' | 'disabled' | 'hidden';
  generated_mode: 'pre' | 'instant';
  placeholder: boolean;
};

export type AreaNpc = {
  npc_id: string;
  name: string;
  state: string;
};

export type SubZoneChatTurnEvent = {
  event_kind:
    | 'encounter_progress'
    | 'encounter_resolution'
    | 'npc_reply'
    | 'team_reply'
    | 'system_notice'
    | 'public_actor_action'
    | 'public_actor_resolution'
    | 'public_round_resolution'
    | 'role_desire_surface'
    | 'companion_story_surface'
    | 'reputation_update'
    | 'encounter_situation_update'
    | 'encounter_world_push'
    | 'player_reaction_triggered'
    | 'player_reaction_result';
  actor_type: 'npc' | 'team' | 'encounter_temp_npc' | 'system';
  actor_id: string;
  actor_name: string;
  content: string;
  metadata?: Record<string, JsonValue>;
};

export type SubZoneChatTurn = {
  turn_id: string;
  source: 'main_chat' | 'encounter' | 'system';
  player_mode: 'active' | 'passive';
  world_time_text: string;
  world_time: Record<string, string | number>;
  player_action: string;
  player_speech: string;
  player_action_check: Record<string, string | number | boolean>;
  gm_narration: string;
  active_encounter_id: string | null;
  active_encounter_title: string;
  active_encounter_status: string;
  events: SubZoneChatTurnEvent[];
  created_at: string;
};

export type SubZoneChatContext = {
  version: string;
  recent_turns: SubZoneChatTurn[];
  updated_at: string;
};

export type AreaSubZone = {
  sub_zone_id: string;
  zone_id: string;
  name: string;
  coord: Coord3D;
  radius_m: number;
  description: string;
  generated_mode: 'pre' | 'instant';
  key_interactions: AreaInteraction[];
  npcs: AreaNpc[];
  chat_context: SubZoneChatContext;
};

export type AreaZone = {
  zone_id: string;
  name: string;
  zone_type: string;
  size: 'small' | 'medium' | 'large';
  center: Coord3D;
  radius_m: number;
  description: string;
  sub_zone_ids: string[];
};

export type AreaSnapshot = {
  version: string;
  zones: AreaZone[];
  sub_zones: AreaSubZone[];
  current_zone_id: string | null;
  current_sub_zone_id: string | null;
  clock: WorldClock | null;
};

export type AreaMoveResult = {
  ok: boolean;
  from_point: {
    zone_id: string;
    sub_zone_id?: string | null;
    coord: Coord3D;
  };
  to_point: {
    zone_id: string;
    sub_zone_id?: string | null;
    coord: Coord3D;
  };
  distance_m: number;
  duration_min: number;
  clock_delta_min: number;
  clock_after: WorldClock;
  movement_feedback: string;
};

export type MapNarrativePayload = {
  text: string;
  source: 'ai' | 'deterministic' | 'none';
};

export type RenderNode = {
  zone_id: string;
  name: string;
  x: number;
  y: number;
};

export type MapRenderPayload = {
  viewport: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  nodes: RenderNode[];
  sub_nodes: Array<{
    sub_zone_id: string;
    zone_id: string;
    name: string;
    x: number;
    y: number;
  }>;
  circles: Array<{
    zone_id: string;
    center_x: number;
    center_y: number;
    radius_m: number;
    danger_score?: number | null;
    danger_band?: 'low' | 'medium' | 'high' | null;
    fill_color?: string | null;
  }>;
  player_marker: { x: number; y: number };
};

export type RenderResult = {
  session_id: string;
  viewport: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  nodes: RenderNode[];
  sub_nodes: Array<{
    sub_zone_id: string;
    zone_id: string;
    name: string;
    x: number;
    y: number;
  }>;
  circles: Array<{
    zone_id: string;
    center_x: number;
    center_y: number;
    radius_m: number;
    danger_score?: number | null;
    danger_band?: 'low' | 'medium' | 'high' | null;
    fill_color?: string | null;
  }>;
  player_marker: { x: number; y: number };
};

export type MapPostChecksBundle = {
  trigger_kind: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced' | null;
  quests_evaluated: boolean;
  fate_evaluated: boolean;
  encounter_checked: boolean;
  encounter_generated: boolean;
  generated_encounter_id: string | null;
  blocked_by_higher_priority_modal: boolean;
};

export type MapStateSyncBundle = {
  map_snapshot: MapSnapshot;
  area_snapshot: AreaSnapshot;
  render: MapRenderPayload;
  world_state: WorldState;
  player_static_data: PlayerStaticData;
  player_runtime_data: PlayerRuntimeData;
  role_pool: NpcRoleCard[];
  current_reputation: SubZoneReputationEntry | null;
  current_zone_metric: ZoneMetricEntry | null;
  zone_metric_state: ZoneMetricState;
  quest_state: QuestState;
  pending_offers: QuestEntry[];
  tracked_quest: QuestEntry | null;
  encounter_state: EncounterState;
  pending_encounters: EncounterEntry[];
  active_encounter: EncounterEntry | null;
  fate_state: FateState;
  team_state: TeamState;
  team_members: TeamMember[];
  game_logs: GameLogEntry[];
};

export type MapBootstrapResponse = {
  ok: boolean;
  operation: 'bootstrap';
  generated: boolean;
  narration: MapNarrativePayload;
  state_sync: MapStateSyncBundle;
};

export type MoveResolvedResponse = {
  session_id: string;
  new_position: { x: number; y: number; z: number; zone_id: string };
  duration_min: number;
  movement_log: MovementLog;
  narration: MapNarrativePayload;
  post_checks: MapPostChecksBundle;
  state_sync: MapStateSyncBundle;
  scene_events?: SceneEvent[];
  main_turn_summary?: MainTurnSummary | null;
  current_zone_metric?: ZoneMetricEntry | null;
};

export type AreaMoveResolvedResponse = AreaMoveResult & {
  narration: MapNarrativePayload;
  post_checks: MapPostChecksBundle;
  state_sync: MapStateSyncBundle;
};

export type AreaDiscoverInteractionsResolvedResponse = {
  ok: boolean;
  generated_mode: 'instant';
  new_interactions: NonNullable<AreaSnapshot['sub_zones']>[number]['key_interactions'];
  narration: MapNarrativePayload;
  state_sync: MapStateSyncBundle;
};

export type AreaExecuteInteractionResolvedResponse = {
  ok: boolean;
  status: 'placeholder' | 'ok' | 'fallback';
  message: string;
  reply: string;
  scene_events: SceneEvent[];
  inventory_changes: Record<string, JsonValue>[];
  interactable_updates: Record<string, JsonValue>[];
  state_sync: MapStateSyncBundle;
};

export type MovementLog = {
  id: string;
  summary: string;
  payload: Record<string, string | number>;
  created_at: string;
};

export type GameLogEntry = {
  id: string;
  session_id: string;
  kind: string;
  message: string;
  payload: Record<string, string | number | boolean>;
  created_at: string;
};

export type GameLogSettings = {
  ai_fetch_limit: number;
};

export type Dnd5eAbilityScores = {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
};

export type Dnd5eAbilityModifiers = {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
};

export type Dnd5eHitPoints = {
  current: number;
  maximum: number;
  temporary: number;
};

export type Dnd5eSpellSlots = {
  level_1: number;
  level_2: number;
  level_3: number;
  level_4: number;
  level_5: number;
  level_6: number;
  level_7: number;
  level_8: number;
  level_9: number;
};

export type RoleBuffEffect = {
  strength_delta: number;
  dexterity_delta: number;
  constitution_delta: number;
  intelligence_delta: number;
  wisdom_delta: number;
  charisma_delta: number;
  ac_delta: number;
  dc_delta: number;
  speed_ft_delta: number;
  move_speed_mph_delta: number;
  hp_max_delta: number;
  stamina_max_delta: number;
};

export type RoleBuff = {
  buff_id: string;
  name: string;
  description: string;
  source: string;
  duration_min: number;
  remaining_min: number;
  stackable: boolean;
  effect: RoleBuffEffect;
};

export type InventoryItem = {
  item_id: string;
  name: string;
  item_type: string;
  description: string;
  weight: number;
  rarity: string;
  value: number;
  effect: string;
  uses_max: number | null;
  uses_left: number | null;
  cooldown_min: number;
  bound: boolean;
  quantity: number;
  slot_type: 'weapon' | 'armor' | 'misc';
  attack_bonus: number;
  armor_bonus: number;
};

export type InventoryData = {
  gold: number;
  item_instance_ids?: string[];
  items: InventoryItem[];
};

export type EquipmentSlots = {
  weapon_item_id: string | null;
  armor_item_id: string | null;
  shield_item_id?: string | null;
  weapon_item_instance_id?: string | null;
  armor_item_instance_id?: string | null;
  shield_item_instance_id?: string | null;
};

export type Dnd5eCharacterSheet = {
  level: number;
  experience_current: number;
  experience_to_next_level: number;
  race: string;
  char_class: string;
  background: string;
  alignment: string;
  proficiency_bonus: number;
  armor_class: number;
  difficulty_class: number;
  speed_ft: number;
  initiative_bonus: number;
  stamina_current: number;
  stamina_maximum: number;
  is_dead: boolean;
  status_flags: string[];
  hit_dice: string;
  hit_points: Dnd5eHitPoints;
  ability_scores: Dnd5eAbilityScores;
  current_ability_scores: Dnd5eAbilityScores;
  ability_modifiers: Dnd5eAbilityModifiers;
  current_ability_modifiers: Dnd5eAbilityModifiers;
  saving_throws_proficient: string[];
  skills_proficient: string[];
  languages: string[];
  tool_proficiencies: string[];
  equipment: string[];
  equipment_slots: EquipmentSlots;
  backpack: InventoryData;
  buffs: RoleBuff[];
  features_traits: string[];
  spells: string[];
  spell_slots_max: Dnd5eSpellSlots;
  spell_slots_current: Dnd5eSpellSlots;
  notes: string;
};

export type RoleRelation = {
  target_role_id: string;
  relation_tag: string;
  note: string;
};

export type NpcDialogueEntry = {
  id: string;
  speaker: 'player' | 'npc';
  speaker_role_id: string;
  speaker_name: string;
  content: string;
  context_kind: 'private_chat' | 'public_targeted' | 'public_reaction' | 'team_chat' | 'encounter';
  world_time_text: string;
  world_time: Record<string, string | number>;
  created_at: string;
};

export type NpcConversationState = {
  current_topic: string;
  last_open_question: string;
  last_npc_claim: string;
  last_player_intent: string;
  last_referenced_entity: string;
  last_scene_mode: string;
};

export type RoleDesire = {
  desire_id: string;
  kind: 'item' | 'place' | 'info' | 'bond' | 'secret' | 'help';
  title: string;
  summary: string;
  intensity: number;
  status: 'latent' | 'active' | 'surfaced' | 'quest_linked' | 'resolved' | 'expired';
  visibility: 'hidden' | 'hinted' | 'explicit';
  preferred_surface: 'public_scene' | 'team_chat' | 'area_arrival' | 'encounter_aftermath' | 'private_chat';
  target_refs: EntityRef[];
  linked_quest_id: string | null;
  cooldown_until: string | null;
  last_surfaced_at: string | null;
};

export type RoleStoryBeat = {
  beat_id: string;
  title: string;
  summary: string;
  affinity_required: number;
  min_days_in_team: number;
  status: 'locked' | 'ready' | 'surfaced' | 'completed' | 'cooldown';
  preferred_surface: 'team_chat' | 'area_arrival' | 'passive_turn' | 'encounter_aftermath';
  last_surfaced_at: string | null;
  completed_at: string | null;
};

export type NpcRoleCard = {
  role_id: string;
  name: string;
  zone_id: string | null;
  sub_zone_id: string | null;
  source_world_revision: number;
  source_map_revision: number;
  knowledge_scope: string;
  state: string;
  personality: string;
  speaking_style: string;
  appearance: string;
  background: string;
  cognition: string;
  alignment: string;
  secret: string;
  likes: string[];
  desires: RoleDesire[];
  story_beats: RoleStoryBeat[];
  talkative_current: number;
  talkative_maximum: number;
  last_private_chat_at: string | null;
  last_public_turn_at: string | null;
  profile: PlayerStaticData;
  relations: RoleRelation[];
  cognition_changes: string[];
  attitude_changes: string[];
  dialogue_logs: NpcDialogueEntry[];
  conversation_state?: NpcConversationState;
  generated_at: string;
};

export type NpcGreetResponse = {
  ok: boolean;
  session_id: string;
  npc_role_id: string;
  greeting: string;
};

export type NpcChatResponse = {
  ok: boolean;
  session_id: string;
  npc_role_id: string;
  reply: string;
  action_reaction: string;
  speech_reply: string;
  talkative_current: number;
  talkative_maximum: number;
  time_spent_min: number;
  dialogue_logs: NpcDialogueEntry[];
  scene_events?: SceneEvent[];
};

export type ActionCheckResult = {
  ok: boolean;
  session_id: string;
  actor_role_id: string;
  actor_name: string;
  actor_kind: 'player' | 'npc';
  action_type: 'attack' | 'check' | 'item_use';
  check_mode?: 'action' | 'reaction_save';
  requires_check: boolean;
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier: number;
  dc: number;
  check_task: string;
  dice_roll: number | null;
  total_score: number | null;
  success: boolean;
  critical: 'none' | 'critical_success' | 'critical_failure';
  time_spent_min: number;
  narrative: string;
  applied_effects: string[];
  relation_tag_suggestion: string | null;
  source_label?: string | null;
  threatened_consequence?: string | null;
  scene_events?: SceneEvent[];
  state_sync?: MapStateSyncBundle | null;
  post_checks?: MapPostChecksBundle | null;
};

export type ActionCheckPlan = {
  ok: boolean;
  session_id: string;
  actor_role_id: string;
  actor_name: string;
  actor_kind: 'player' | 'npc';
  action_type: 'attack' | 'check' | 'item_use';
  check_mode?: 'action' | 'reaction_save';
  requires_check: boolean;
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier: number;
  dc: number;
  time_spent_min: number;
  check_task: string;
  source_label?: string | null;
  threatened_consequence?: string | null;
};

export type WorldState = {
  version: string;
  world_revision: number;
  map_revision: number;
  last_consistency_check_at: string | null;
  last_world_rebuild_at: string | null;
};

export type EntityRef = {
  entity_type: 'zone' | 'sub_zone' | 'npc' | 'item' | 'quest' | 'encounter' | 'fate' | 'fate_phase';
  entity_id: string;
  label: string;
  required: boolean;
  source: 'system' | 'ai' | 'fallback';
};

export type ConsistencyIssue = {
  issue_id: string;
  severity: 'info' | 'warning' | 'error';
  issue_type: string;
  entity_type: string;
  entity_id: string;
  message: string;
};

export type PlayerStorySummary = {
  player_id: string;
  name: string;
  level: number;
  hp_current: number;
  hp_maximum: number;
  inventory_item_names: string[];
};

export type StoryNpcSummary = {
  role_id: string;
  name: string;
  zone_id: string | null;
  sub_zone_id: string | null;
  relation_tag: string | null;
};

export type StoryQuestSummary = {
  quest_id: string;
  title: string;
  status: string;
  source: string;
};

export type RoleDriveSummary = {
  role_id: string;
  name: string;
  desires: RoleDesire[];
  story_beats: RoleStoryBeat[];
};

export type PublicSceneActorCandidate = {
  role_id: string;
  name: string;
  actor_type: 'npc' | 'team' | 'encounter_temp_npc';
  priority_reason: string;
  surfaced_desire_ids: string[];
  surfaced_story_beat_ids: string[];
};

export type GlobalStorySnapshot = {
  session_id: string;
  world_revision: number;
  map_revision: number;
  current_zone_id: string | null;
  current_sub_zone_id: string | null;
  current_zone_name: string;
  current_sub_zone_name: string;
  clock: WorldClock | null;
  player_summary: PlayerStorySummary;
  visible_zone_ids: string[];
  visible_sub_zone_ids: string[];
  available_npc_ids: string[];
  available_npcs: StoryNpcSummary[];
  team_member_ids: string[];
  active_quest_ids: string[];
  active_quests: StoryQuestSummary[];
  pending_quest_ids: string[];
  current_fate_id: string | null;
  current_fate_phase_id: string | null;
  recent_encounter_ids: string[];
  recent_game_log_refs: string[];
};

export type PublicSceneState = {
  session_id: string;
  current_zone_id: string | null;
  current_sub_zone_id: string | null;
  current_reputation: SubZoneReputationEntry | null;
  visible_npcs: StoryNpcSummary[];
  team_members: StoryNpcSummary[];
  candidate_actors: PublicSceneActorCandidate[];
  surfaced_drives: RoleDriveSummary[];
  active_encounter: EncounterEntry | null;
};

export type NpcKnowledgeSnapshot = {
  npc_role_id: string;
  npc_name: string;
  world_revision: number;
  map_revision: number;
  current_zone_id: string | null;
  current_sub_zone_id: string | null;
  self_profile_summary: string;
  known_player_relation: string;
  known_local_npc_ids: string[];
  known_local_zone_ids: string[];
  known_active_quest_refs: EntityRef[];
  recent_dialogue_summary: string[];
  forbidden_entity_ids: string[];
  response_rules: string[];
};

export type TeamMember = {
  role_id: string;
  name: string;
  origin_zone_id: string | null;
  origin_sub_zone_id: string | null;
  joined_at: string;
  affinity: number;
  trust: number;
  join_source: 'story' | 'debug';
  join_reason: string;
  is_debug: boolean;
  debug_prompt: string;
  status: 'active' | 'left';
  last_reaction_at: string | null;
  last_reaction_preview: string;
};

export type TeamReaction = {
  reaction_id: string;
  member_role_id: string;
  member_name: string;
  trigger_kind: 'main_chat' | 'npc_chat' | 'zone_move' | 'sub_zone_move' | 'action_check' | 'team_chat' | 'public_chat' | 'public_turn' | 'encounter' | 'system';
  content: string;
  affinity_delta: number;
  trust_delta: number;
  created_at: string;
};

export type TeamState = {
  version: string;
  members: TeamMember[];
  reactions: TeamReaction[];
  updated_at: string;
};

export type ConsistencyStatusResponse = {
  ok: boolean;
  session_id: string;
  world_state: WorldState;
  issue_count: number;
  issues: ConsistencyIssue[];
};

export type ConsistencyRunResponse = ConsistencyStatusResponse & {
  changed: boolean;
};

export type StorySnapshotResponse = {
  ok: boolean;
  session_id: string;
  snapshot: GlobalStorySnapshot;
};

export type ReputationStateResponse = {
  ok: boolean;
  session_id: string;
  reputation_state: ReputationState;
  current_entry: SubZoneReputationEntry | null;
};

export type RoleDrivesResponse = {
  ok: boolean;
  session_id: string;
  scope: 'role' | 'team' | 'current_sub_zone';
  items: RoleDriveSummary[];
};

export type PublicSceneStateResponse = {
  ok: boolean;
  session_id: string;
  public_scene_state: PublicSceneState;
};

export type NpcKnowledgeResponse = {
  ok: boolean;
  session_id: string;
  npc_role_id: string;
  snapshot: NpcKnowledgeSnapshot;
};

export type TeamStateResponse = {
  ok: boolean;
  session_id: string;
  team_state: TeamState;
  members: TeamMember[];
};

export type TeamMutationResponse = {
  ok: boolean;
  session_id: string;
  team_state: TeamState;
  member: TeamMember | null;
  role: NpcRoleCard | null;
  accepted: boolean;
  chat_feedback: string;
};

export type InventoryOwnerRef = {
  owner_type: 'player' | 'role';
  role_id: string | null;
};

export type InventoryEquipRequest = {
  session_id: string;
  owner: InventoryOwnerRef;
  item_id: string;
  slot: 'weapon' | 'armor';
};

export type InventoryUnequipRequest = {
  session_id: string;
  owner: InventoryOwnerRef;
  slot: 'weapon' | 'armor';
};

export type InventoryMutationResponse = {
  ok: boolean;
  session_id: string;
  owner: InventoryOwnerRef;
  message: string;
  item_id?: string | null;
  amount_changed?: number;
  quantity_after?: number;
  uses_left_after?: number | null;
  player: PlayerStaticData | null;
  role: NpcRoleCard | null;
};

export type TemplateLibraryStatusResponse = {
  ok: boolean;
  session_id: string;
  template_dir: string;
  item_definition_count: number;
  equipment_definition_count: number;
  interactable_template_count: number;
  last_filled_at?: string | null;
};

export type TemplateLibraryFillResponse = TemplateLibraryStatusResponse & {
  appended_item_definition_ids: string[];
  appended_equipment_definition_ids: string[];
  appended_interactable_template_ids: string[];
  updated_item_definition_ids: string[];
  updated_equipment_definition_ids: string[];
  updated_interactable_template_ids: string[];
};

export type InventoryInteractRequest = {
  session_id: string;
  owner: InventoryOwnerRef;
  item_id: string;
  mode: 'inspect' | 'use';
  prompt: string;
  action_check?: ActionCheckResult | null;
  config?: AppConfig;
};

export type InventoryInteractResponse = {
  ok: boolean;
  session_id: string;
  owner: InventoryOwnerRef;
  item_id: string;
  mode: 'inspect' | 'use';
  reply: string;
  time_spent_min: number;
  action_check: ActionCheckResult | null;
  player: PlayerStaticData | null;
  role: NpcRoleCard | null;
  scene_events?: SceneEvent[];
};

export type TeamChatReply = {
  member_role_id: string;
  member_name: string;
  content: string;
  response_mode: 'speech' | 'action';
  affinity_delta: number;
  trust_delta: number;
  created_at: string;
};

export type TeamChatResponse = {
  ok: boolean;
  session_id: string;
  player_message: string;
  replies: TeamChatReply[];
  team_state: TeamState;
  time_spent_min: number;
};

export const defaultPlayerStaticData: PlayerStaticData = {
  player_id: 'player_001',
  name: '玩家',
  move_speed_mph: 4500,
  role_type: 'player',
  dnd5e_sheet: {
    level: 1,
    experience_current: 0,
    experience_to_next_level: 300,
    race: '',
    char_class: '',
    background: '',
    alignment: '',
    proficiency_bonus: 2,
    armor_class: 10,
    difficulty_class: 10,
    speed_ft: 30,
    initiative_bonus: 0,
    stamina_current: 10,
    stamina_maximum: 10,
    is_dead: false,
    status_flags: [],
    hit_dice: '1d8',
    hit_points: {
      current: 10,
      maximum: 10,
      temporary: 0,
    },
    ability_scores: {
      strength: 10,
      dexterity: 10,
      constitution: 10,
      intelligence: 10,
      wisdom: 10,
      charisma: 10,
    },
    current_ability_scores: {
      strength: 10,
      dexterity: 10,
      constitution: 10,
      intelligence: 10,
      wisdom: 10,
      charisma: 10,
    },
    ability_modifiers: {
      strength: 0,
      dexterity: 0,
      constitution: 0,
      intelligence: 0,
      wisdom: 0,
      charisma: 0,
    },
    current_ability_modifiers: {
      strength: 0,
      dexterity: 0,
      constitution: 0,
      intelligence: 0,
      wisdom: 0,
      charisma: 0,
    },
    saving_throws_proficient: [],
    skills_proficient: [],
    languages: [],
    tool_proficiencies: [],
    equipment: [],
    equipment_slots: {
      weapon_item_id: null,
      armor_item_id: null,
    },
    backpack: {
      gold: 0,
      items: [],
    },
    buffs: [],
    features_traits: [],
    spells: [],
    spell_slots_max: {
      level_1: 2,
      level_2: 0,
      level_3: 0,
      level_4: 0,
      level_5: 0,
      level_6: 0,
      level_7: 0,
      level_8: 0,
      level_9: 0,
    },
    spell_slots_current: {
      level_1: 2,
      level_2: 0,
      level_3: 0,
      level_4: 0,
      level_5: 0,
      level_6: 0,
      level_7: 0,
      level_8: 0,
      level_9: 0,
    },
    notes: '',
  },
};

export const defaultQuestState: QuestState = {
  version: '0.1.0',
  tracked_quest_id: null,
  quests: [],
  updated_at: new Date(0).toISOString(),
};

export const defaultEncounterState: EncounterState = {
  version: '0.1.0',
  pending_ids: [],
  active_encounter_id: null,
  encounters: [],
  history: [],
  debug_force_trigger: false,
  updated_at: new Date(0).toISOString(),
};

export const defaultFateState: FateState = {
  version: '0.1.0',
  current_fate: null,
  archive: [],
  updated_at: new Date(0).toISOString(),
};

export const defaultWorldState: WorldState = {
  version: '0.1.0',
  world_revision: 1,
  map_revision: 1,
  last_consistency_check_at: null,
  last_world_rebuild_at: null,
};

export const defaultTeamState: TeamState = {
  version: '0.1.0',
  members: [],
  reactions: [],
  updated_at: new Date(0).toISOString(),
};

export const defaultReputationState: ReputationState = {
  version: '0.1.0',
  entries: [],
  updated_at: new Date(0).toISOString(),
};

export const defaultConfig: AppConfig = {
  version: '2.0.0',
  provider: 'openai',
  api_key: 'sk-xxxx',
  base_url_override: '',
  model: 'gpt-5',
  stream: true,
  runtime: {
    temperature: 0.8,
    max_completion_tokens: 1200,
    structured_output_mode: 'auto',
  },
  gm_prompt: '?????????????????????????????????????',
  speech_time_per_50_tokens_min: 1,
  sub_zone_debug: {
    small_min_count: 3,
    small_max_count: 5,
    medium_min_count: 5,
    medium_max_count: 10,
    large_min_count: 8,
    large_max_count: 15,
    discover_interaction_limit: 3,
  },
  public_scene: {
    active_actor_limit: 8,
    idle_actor_limit: 2,
    max_world_pushes: 2,
    uncertain_actions_require_check: true,
  },
  provider_configs: {
    openai: {
      api_key: 'sk-xxxx',
      base_url_override: '',
      model: 'gpt-5',
      runtime: {
        temperature: 0.8,
        max_completion_tokens: 1200,
        structured_output_mode: 'auto',
      },
    },
    deepseek: {
      api_key: '',
      base_url_override: '',
      model: 'deepseek-chat',
      runtime: {
        temperature: 0.8,
        max_tokens: 1200,
        structured_output_mode: 'auto',
      },
    },
    gemini: {
      api_key: '',
      base_url_override: '',
      model: 'gemini-2.5-flash',
      runtime: { structured_output_mode: 'auto' },
    },
  },
  ui: {
    theme: 'dark',
  },
};
