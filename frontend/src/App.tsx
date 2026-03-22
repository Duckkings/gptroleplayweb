import { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';
import { useEffectEvent } from 'react';
import { DebugPanel } from './components/DebugPanel';
import { ConsistencyPanel } from './components/ConsistencyPanel';
import { EncounterLane } from './components/EncounterLane';
import { EncounterModal } from './components/EncounterModal';
import { FatePanel } from './components/FatePanel';
import { GameLogPanel } from './components/GameLogPanel';
import { InventoryModal } from './components/InventoryModal';
import { ItemInteractionModal } from './components/ItemInteractionModal';
import { LiveProgressPanel } from './components/LiveProgressPanel';
import { MapPanel } from './components/MapPanel';
import { NpcPoolPanel } from './components/NpcPoolPanel';
import { PlayerPanel } from './components/PlayerPanel';
import { PlayerInputValidationModal } from './components/PlayerInputValidationModal';
import { PlayerInputValidationPanel } from './components/PlayerInputValidationPanel';
import { PlayerQuickActionModal, type PlayerQuickActionMode } from './components/PlayerQuickActionModal';
import { PublicTurnImpactList } from './components/PublicTurnImpactList';
import { PublicTurnAttackDefenseModal } from './components/PublicTurnAttackDefenseModal';
import { PublicTurnAttackModal } from './components/PublicTurnAttackModal';
import { PublicTurnDeathSaveModal } from './components/PublicTurnDeathSaveModal';
import { PublicTurnInteractionModal } from './components/PublicTurnInteractionModal';
import { PublicTurnNarrativePane } from './components/PublicTurnNarrativePane';
import { PublicTurnOpposedModal } from './components/PublicTurnOpposedModal';
import { PublicTurnPanel } from './components/PublicTurnPanel';
import { PublicTurnSettlementPane } from './components/PublicTurnSettlementPane';
import { QuestInspectModal } from './components/QuestInspectModal';
import { QuestModal } from './components/QuestModal';
import { RoleInventoryModal } from './components/RoleInventoryModal';
import { RoleProfileModal } from './components/RoleProfileModal';
import { SceneEventCard } from './components/SceneEventCard';
import { SubZoneContextPanel } from './components/SubZoneContextPanel';
import { TeamPanel } from './components/TeamPanel';
import { TeammateChatModal } from './components/TeammateChatModal';
import { ActionCheckPanel } from './components/ActionCheckPanel';
import { ActionCheckRollModal } from './components/ActionCheckRollModal';
import { AuthPanel } from './components/AuthPanel';
import { BattleModal } from './components/BattleModal';
import { BattleStartDialog } from './components/BattleStartDialog';
import { CharacterBuildModal } from './components/CharacterBuildModal';
import { PartyPreviewRail, type PartyPreviewEntry } from './components/PartyPreviewRail';
import {
  acceptQuest,
  bootstrapWorldMap,
  continueBattleAi,
  continuePublicTurn,
  continuePublicTurnProtocolRepair,
  checkEncounters,
  cancelPendingTurn,
  continuePendingTurn,
  continuePendingTurnStream,
  clearSave,
  debugSaveReset,
  debugGenerateQuest,
  getCharacterBuildState,
  markCharacterBuildCompanionOfferSeen,
  discoverConfigModels,
  discoverAreaInteractions,
  equipInventoryItem,
  evaluateAllQuests,
  evaluateFate,
  executeAreaInteraction,
  fillTemplateLibrary,
  generateFate,
  generateDebugTeammate,
  getCurrentDebugBattle,
  getConsistencyStatus,
  getGameLogs,
  getGameLogSettings,
  getConfigPath,
  getConfigModelProfile,
  getStoredConfig,
  getCurrentArea,
  getCurrentPendingTurn,
  getCurrentSave,
  getFateState,
  getPendingEncounters,
  getPlayerRuntime,
  getPlayerStatic,
  getQuestState,
  getRoleCard,
  getRolePool,
  getTeamState,
  getTemplateLibraryStatus,
  getSavePath,
  getStorySnapshot,
  getTokenUsage,
  initWorldClock,
  interactInventoryItem,
  importSave,
  inviteNpcToTeam,
  leaveNpcFromTeam,
  moveToZone,
  npcChat,
  endDebugBattle,
  enterPublicTurn,
  planPublicTurnOpposedCheck,
  sendTeamChat,
  pickSavePath,
  planActionCheck,
  presentEncounter,
  regenerateFate,
  rejectQuest,
  rejoinEncounter,
  resolveBattleRoll,
  resolvePublicTurnReaction,
  resolvePublicTurnAttackDefense,
  resolvePublicTurnDeathSave,
  resolvePublicTurnOpposedCheck,
  runActionCheck,
  moveToSubZone,
  renderWorldMap,
  runConsistencyCheck,
  saveConfig,
  startDebugBattle,
  submitBattlePlayerAction,
  sendChat,
  setGameLogSettings,
  setPlayerRuntime,
  setPlayerStatic,
  streamChat,
  streamContinuePublicTurn,
  streamEnterPublicTurn,
  streamNpcChat,
  streamResolvePublicTurnAttackDefense,
  streamResolvePublicTurnDeathSave,
  streamResolvePublicTurnReaction,
  streamResolvePublicTurnOpposedCheck,
  trackQuest,
  toMapSnapshot,
  unequipInventoryItem,
  validateConfig,
  validatePlayerInput,
  authMe,
  authLogin,
  authRegister,
  authLogout,
  authResetPassword,
  retainNpc,
  getRetainedNpcs,
  generateFromRetained,
} from './services/api';
import {
  defaultCharacterBuildState,
  defaultPlayerStaticData,
  defaultConfig,
  defaultEncounterState,
  defaultFateState,
  defaultPublicTurnState,
  defaultQuestState,
  defaultTeamState,
  defaultWorldState,
  type ActionCheckPlan,
  type ApiDebugEntry,
  type ActionCheckResult,
  type BuildMediaConfig,
  type BattleRollPrompt,
  type BattleRollResolution,
  type BattleSandboxState,
  type EncounterEntry,
  type EncounterState,
  type AreaSnapshot,
  type AppConfig,
  type ChatMessage,
  type ChatResponse,
  type CharacterBuildCompanionCompleteResponse,
  type CharacterBuildPlayerCompleteResponse,
  type CharacterBuildStateResponse,
  type ConsistencyIssue,
  type DeathSavePrompt,
  type FateState,
  type GameLogEntry,
  type GlobalStorySnapshot,
  type InventoryOwnerRef,
  type MapSnapshot,
  type MainTurnSummary,
  type MapStateSyncBundle,
  type ModelCapabilityInfo,
  type PathStatus,
  type PendingTurnContinueResponse,
  type PlayerInputValidationEntryPoint,
  type PlayerInputValidationResponse,
  type PlayerRuntimeData,
  type PlayerReactionCheck,
  type PlayerStaticData,
  type NpcRoleCard,
  type TemplateLibraryStatusResponse,
  type NpcChatResponse,
  type Position,
  type PublicTurnEntryType,
  type PublicTurnAttackDefensePrompt,
  type PublicTurnAttackPrompt,
  type PublicTurnImpact,
  type PublicTurnInteractionPrompt,
  type PublicTurnOpposedPlanResponse,
  type PublicTurnOpposedPrompt,
  type PublicTurnPhase,
  type PublicTurnPresentation,
  type PublicTurnPlayerActionCheck,
  type PublicTurnRound,
  type PublicTurnProtocolRepairNotice,
  type PublicTurnProtocolRepairRequest,
  type PublicTurnResponse,
  type PublicTurnSettlementEntry,
  type PublicTurnState,
  type ProviderConfigMap,
  type ProviderBuildMediaConfig,
  type ProviderScopedConfig,
  type QuestState,
  type RenderResult,
  type RoleActionStatus,
  type SaveFile,
  type SceneEvent,
  type LiveProgressEntry,
  type LiveToolEvent,
  type StreamPhaseEvent,
  type SubZoneReputationEntry,
  type TeamChatReply,
  type TeamState,
  type TokenUsageSummary,
  type TurnRollbackPayload,
  type ZoneMetricEntry,
  type ZoneMetricState,
} from './types/app';

type View = 'boot' | 'config' | 'chat';
type ChatState =
  | 'idle'
  | 'sending'
  | 'streaming'
  | 'awaiting_interaction'
  | 'awaiting_attack_response'
  | 'awaiting_attack_defense'
  | 'awaiting_death_save'
  | 'awaiting_reaction'
  | 'awaiting_opposed'
  | 'awaiting_protocol_repair'
  | 'error';
type ChatMode = 'main' | 'npc';
type MainOutputStatus =
  | 'idle'
  | 'streaming'
  | 'awaiting_interaction'
  | 'awaiting_attack_response'
  | 'awaiting_attack_defense'
  | 'awaiting_death_save'
  | 'awaiting_reaction'
  | 'awaiting_opposed'
  | 'awaiting_protocol_repair'
  | 'awaiting_archive'
  | 'error';
type MainOutput = {
  source_kind: 'main_turn' | 'system_output';
  reply_text: string;
  scene_events: SceneEvent[];
  archived_sub_zone_turn_id: string | null;
  main_turn_summary: MainTurnSummary | null;
  public_turn_state?: PublicTurnState | null;
  public_turn_presentation?: PublicTurnPresentation | null;
  status: MainOutputStatus;
};
type ActionCheckPayload = {
  action_type: 'attack' | 'check' | 'item_use' | 'auto';
  action_prompt: string;
  actor_role_id?: string;
  source_context: 'main_chat' | 'npc_chat' | 'encounter_lane' | 'action_panel' | 'area_item' | 'inventory_item';
  post_close_output: 'main_chat' | 'suppress';
  resolution_context?: 'standalone' | 'embedded';
  skip_if_no_check?: boolean;
  return_state_sync?: boolean;
  post_trigger_kind?: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced';
};
type ActionCheckRollPhase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';
type ActionCheckRollState = {
  open: boolean;
  phase: ActionCheckRollPhase;
  plan: ActionCheckPlan | null;
  rollValue: number | null;
  result: ActionCheckResult | null;
  errorMessage: string;
  rotation: { x: number; y: number; z: number };
};
type PendingPublicTurnAction = {
  actionSubmission: {
    actor_id: string;
    action_text: string;
    speech_text: string;
    source_phase: PublicTurnPhase;
    forced_first: boolean;
  };
  playerActionCheck: PublicTurnPlayerActionCheck;
};
type PendingReactionState = {
  pending_turn_id: string;
  flow_kind: PendingTurnContinueResponse['flow_kind'];
  npc_role_id?: string | null;
  pending_reaction: PlayerReactionCheck;
};
type PendingInteractionState = {
  prompt: PublicTurnInteractionPrompt;
};
type PendingAttackState = {
  prompt: PublicTurnAttackPrompt;
};
type PendingAttackDefenseState = {
  prompt: PublicTurnAttackDefensePrompt;
};
type PendingDeathSaveState = {
  prompt: DeathSavePrompt;
};
type PendingOpposedState = {
  pending_turn_id: string;
  flow_kind: PendingTurnContinueResponse['flow_kind'];
  prompt: PublicTurnOpposedPrompt;
  npc_role_id?: string | null;
};
type PublicTurnOpposedRollState = {
  open: boolean;
  phase: ActionCheckRollPhase;
  rollValue: number | null;
  result: ActionCheckResult | null;
  errorMessage: string;
  rotation: { x: number; y: number; z: number };
};
type PublicTurnDeathSaveRollState = {
  open: boolean;
  phase: 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';
  rollValue: number | null;
  errorMessage: string;
  rotation: { x: number; y: number; z: number };
};
type BlockingModalKey =
  | 'quest'
  | 'encounter'
  | 'public_turn_action_roll'
  | 'public_turn_interaction'
  | 'public_turn_attack_response'
  | 'public_turn_attack_defense'
  | 'public_turn_death_save'
  | 'public_turn_opposed'
  | 'reaction_roll'
  | 'battle_start'
  | 'battle'
  | 'battle_roll';
type ActiveTeammateChat = {
  npcId: string;
  npcName: string;
};
type ValidatedPlayerInput = {
  actionText: string;
  speechText: string;
  response: PlayerInputValidationResponse | null;
};
type PlayerInputValidationModalState = {
  entryPoint: PlayerInputValidationEntryPoint;
  originalActionText: string;
  originalSpeechText: string;
  response: PlayerInputValidationResponse;
};
type PlayerInputValidationBypassToken = {
  entryPoint: PlayerInputValidationEntryPoint;
  actorRoleId: string;
  actionText: string;
  speechText: string;
};

function emptyPublicTurnPresentation(): PublicTurnPresentation {
  return {
    round_id: '',
    round_number: 0,
    phase: 'idle',
    initiative_order: [],
    settlement_entries: [],
    gm_push_result: null,
    narrative_entries: [],
    accumulated_narration: '',
    narrative_status: 'empty',
    round_narration: '',
    round_narration_status: 'pending',
  };
}

function publicTurnPresentationFromRound(round: PublicTurnRound | null | undefined): PublicTurnPresentation | null {
  if (!round) return null;
  return {
    round_id: round.round_id,
    round_number: round.round_number,
    phase: round.phase,
    initiative_order: round.initiative_order ?? [],
    settlement_entries: round.settlement_entries ?? [],
    gm_push_result: round.gm_push_result ?? null,
    narrative_entries: round.narrative_entries ?? [],
    accumulated_narration: round.accumulated_narration ?? '',
    narrative_status: round.narrative_status ?? 'empty',
    round_narration: round.round_narration ?? '',
    round_narration_status: round.round_narration_status ?? 'pending',
  };
}

function mergeInitiativeOrder(
  current: PublicTurnPresentation | null | undefined,
  entries: PublicTurnPresentation['initiative_order'],
  meta: { round_id?: string; round_number?: number },
): PublicTurnPresentation {
  const base = current ?? emptyPublicTurnPresentation();
  return {
    ...base,
    round_id: meta.round_id ?? base.round_id,
    round_number: meta.round_number ?? base.round_number,
    initiative_order: entries,
  };
}

function appendSettlementEntry(
  current: PublicTurnPresentation | null | undefined,
  entry: PublicTurnPresentation['settlement_entries'][number],
): PublicTurnPresentation {
  const base = current ?? emptyPublicTurnPresentation();
  return {
    ...base,
    round_id: entry.round_id || base.round_id,
    round_number: base.round_number,
    phase: entry.phase,
    gm_push_result: entry.gm_push_result ?? base.gm_push_result ?? null,
    settlement_entries: [...base.settlement_entries, entry],
  };
}

function withRoundNarration(
  current: PublicTurnPresentation | null | undefined,
  narration: string,
): PublicTurnPresentation {
  const base = current ?? emptyPublicTurnPresentation();
  const accumulated = `${base.accumulated_narration}${narration}`;
  return {
    ...base,
    accumulated_narration: accumulated,
    narrative_status: narration.trim() ? 'streaming' : base.narrative_status,
    round_narration: accumulated,
    round_narration_status: narration.trim() ? 'streaming' : base.round_narration_status,
  };
}

function isPendingTurnContinueResponse(
  response: ChatResponse | PendingTurnContinueResponse | NpcChatResponse | PublicTurnResponse,
): response is PendingTurnContinueResponse {
  return 'status' in response && 'reply_text' in response;
}

function isChatTurnResponse(response: ChatResponse | PendingTurnContinueResponse): response is ChatResponse {
  return 'reply' in response;
}

function getPlayerInputValidationSuggestion(response: PlayerInputValidationResponse): { actionText: string; speechText: string } {
  return {
    actionText: response.fallback_action_text.trim(),
    speechText: response.normalized_speech_text.trim(),
  };
}

function isNpcTurnResponse(response: NpcChatResponse | PendingTurnContinueResponse): response is NpcChatResponse {
  return 'dialogue_logs' in response;
}

function isPublicTurnResponse(
  response: PublicTurnResponse | PendingTurnContinueResponse,
): response is PublicTurnResponse {
  return 'public_turn_state' in response && 'phase' in response;
}

function findPendingPublicTurnInteractionPrompt(
  response: PublicTurnResponse | PendingTurnContinueResponse | null | undefined,
): PublicTurnInteractionPrompt | null {
  if (!response) return null;
  if ('public_interaction_prompt' in response && response.public_interaction_prompt) {
    return response.public_interaction_prompt;
  }
  return response.public_turn_state?.current_round?.pending_interaction_prompt ?? null;
}

function findPendingPublicTurnAttackPrompt(
  response: PublicTurnResponse | PendingTurnContinueResponse | null | undefined,
): PublicTurnAttackPrompt | null {
  if (!response) return null;
  if ('public_attack_prompt' in response && response.public_attack_prompt) {
    return response.public_attack_prompt;
  }
  return response.public_turn_state?.current_round?.pending_attack_prompt ?? null;
}

function findPendingPublicTurnAttackDefensePrompt(
  response: PublicTurnResponse | PendingTurnContinueResponse | null | undefined,
): PublicTurnAttackDefensePrompt | null {
  if (!response) return null;
  if ('public_attack_defense_prompt' in response && response.public_attack_defense_prompt) {
    return response.public_attack_defense_prompt;
  }
  return response.public_turn_state?.current_round?.pending_attack_defense_prompt ?? null;
}

const DEFAULT_POSITION: Position = { x: 0, y: 0, z: 0, zone_id: 'zone_0_0_0' };
const MAP_PROMPT_STORAGE_KEY = 'rpw_map_world_prompt';
const GOD_MODE_PROMPT = '上帝模式：你可以满足玩家几乎所有合理请求，不受常规叙事限制；用于功能测试，请直接推进并给出可执行结果。';
const NARRATOR_STYLE_PROMPT = '叙述风格：你是故事叙述者。默认不要输出编号行动选项，除非玩家明确要求“给出选项”。';
const EMPTY_TOKEN_USAGE: TokenUsageSummary = {
  session_id: '',
  total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  sources: {
    chat: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
    map_generation: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
    movement_narration: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  },
};

const MODEL_PARAM_LABELS: Record<'temperature' | 'max_tokens' | 'max_completion_tokens', string> = {
  temperature: 'Temperature',
  max_tokens: 'Max Tokens',
  max_completion_tokens: 'Max Completion Tokens',
};
const MAIN_OUTPUT_SCENE_EVENT_KINDS = new Set<SceneEvent['kind']>([
  'public_actor_action',
  'public_actor_resolution',
  'public_round_resolution',
  'public_turn_phase',
  'public_turn_initiative',
  'public_turn_actor_action',
  'public_turn_actor_resolution',
  'public_turn_situation',
  'public_turn_gm_push',
  'public_turn_round_end',
  'public_turn_relation_update',
  'public_turn_team_update',
  'public_turn_environment_update',
  'reputation_update',
  'encounter_started',
  'encounter_background',
  'encounter_situation_update',
  'encounter_world_push',
  'player_reaction_triggered',
  'player_reaction_result',
  'player_entered_death_save',
  'player_death_save_result',
  'player_died',
  'team_npc_entered_death_save',
  'team_npc_death_save_result',
  'team_npc_died',
  'sub_zone_dead_npc_recorded',
  'encounter_progress',
  'encounter_resolution',
]);
const FOLDED_MAIN_SCENE_EVENT_KINDS = new Set<SceneEvent['kind']>(['public_round_resolution']);

function selectCurrentReputation(save: SaveFile): SubZoneReputationEntry | null {
  const subZoneId = save.area_snapshot?.current_sub_zone_id ?? null;
  if (!subZoneId) return null;
  return save.reputation_state?.entries?.find((item) => item.sub_zone_id === subZoneId) ?? null;
}

function selectCurrentZoneMetric(save: SaveFile): ZoneMetricEntry | null {
  const zoneId = save.area_snapshot?.current_zone_id ?? null;
  if (!zoneId) return null;
  return save.zone_metric_state?.entries?.find((item) => item.zone_id === zoneId) ?? null;
}

function cloneRuntimeConfig(runtime?: AppConfig['runtime']): AppConfig['runtime'] {
  return { ...(runtime ?? {}) };
}

function cloneProviderConfig(providerConfig: ProviderScopedConfig): ProviderScopedConfig {
  return {
    api_key: providerConfig.api_key ?? '',
    base_url_override: providerConfig.base_url_override ?? '',
    model: providerConfig.model ?? '',
    runtime: cloneRuntimeConfig(providerConfig.runtime),
  };
}

function getDefaultProviderConfig(provider: AppConfig['provider']): ProviderScopedConfig {
  return cloneProviderConfig(defaultConfig.provider_configs[provider]);
}

function cloneBuildMediaProviderConfig(providerConfig?: Partial<ProviderBuildMediaConfig>): ProviderBuildMediaConfig {
  return {
    api_key: providerConfig?.api_key ?? '',
    base_url_override: providerConfig?.base_url_override ?? '',
    generation_model: providerConfig?.generation_model ?? '',
    background_removal_model: providerConfig?.background_removal_model ?? '',
    vision_model: providerConfig?.vision_model ?? '',
  };
}

function buildBuildMediaConfig(config: AppConfig): BuildMediaConfig {
  const rawBuildMedia = config.build_media ?? defaultConfig.build_media;
  return {
    mode: rawBuildMedia.mode ?? defaultConfig.build_media.mode,
    explicit_provider: rawBuildMedia.explicit_provider ?? defaultConfig.build_media.explicit_provider,
    provider_configs: {
      openai: cloneBuildMediaProviderConfig(rawBuildMedia.provider_configs?.openai ?? defaultConfig.build_media.provider_configs.openai),
      deepseek: cloneBuildMediaProviderConfig(rawBuildMedia.provider_configs?.deepseek ?? defaultConfig.build_media.provider_configs.deepseek),
      gemini: cloneBuildMediaProviderConfig(rawBuildMedia.provider_configs?.gemini ?? defaultConfig.build_media.provider_configs.gemini),
    },
  };
}

function buildProviderConfigMap(config: AppConfig): ProviderConfigMap {
  const currentProvider = config.provider ?? defaultConfig.provider;
  const rawConfigs = config.provider_configs;
  const providerConfigs: ProviderConfigMap = {
    openai: cloneProviderConfig(rawConfigs?.openai ?? getDefaultProviderConfig('openai')),
    deepseek: cloneProviderConfig(rawConfigs?.deepseek ?? getDefaultProviderConfig('deepseek')),
    gemini: cloneProviderConfig(rawConfigs?.gemini ?? getDefaultProviderConfig('gemini')),
  };

  providerConfigs[currentProvider] = {
    ...providerConfigs[currentProvider],
    api_key: config.api_key ?? providerConfigs[currentProvider].api_key,
    base_url_override: config.base_url_override ?? providerConfigs[currentProvider].base_url_override ?? '',
    model: config.model ?? providerConfigs[currentProvider].model,
    runtime: cloneRuntimeConfig(config.runtime),
  };
  return providerConfigs;
}

function normalizeConfig(config: AppConfig): AppConfig {
  const providerConfigs = buildProviderConfigMap(config);
  const currentProviderConfig = providerConfigs[config.provider];
  return {
    ...config,
    provider: config.provider,
    api_key: currentProviderConfig.api_key,
    base_url_override: currentProviderConfig.base_url_override ?? '',
    model: currentProviderConfig.model,
    runtime: cloneRuntimeConfig(currentProviderConfig.runtime),
    provider_configs: providerConfigs,
    build_media: buildBuildMediaConfig(config),
    public_scene: {
      ...defaultConfig.public_scene,
      ...(config.public_scene ?? {}),
    },
  };
}

function updateCurrentProviderConfig(config: AppConfig, updates: Partial<ProviderScopedConfig>): AppConfig {
  const currentProvider = config.provider;
  const providerConfigs = buildProviderConfigMap(config);
  const currentProviderConfig: ProviderScopedConfig = {
    ...providerConfigs[currentProvider],
    api_key: updates.api_key ?? config.api_key,
    base_url_override: updates.base_url_override ?? config.base_url_override ?? '',
    model: updates.model ?? config.model,
    runtime: cloneRuntimeConfig(updates.runtime ?? config.runtime),
  };
  providerConfigs[currentProvider] = cloneProviderConfig(currentProviderConfig);
  return {
    ...config,
    api_key: currentProviderConfig.api_key,
    base_url_override: currentProviderConfig.base_url_override ?? '',
    model: currentProviderConfig.model,
    runtime: cloneRuntimeConfig(currentProviderConfig.runtime),
    provider_configs: providerConfigs,
  };
}

function selectProviderConfig(config: AppConfig, provider: AppConfig['provider']): AppConfig {
  const providerConfigs = buildProviderConfigMap(config);
  const nextProviderConfig = providerConfigs[provider];
  return {
    ...config,
    provider,
    api_key: nextProviderConfig.api_key,
    base_url_override: nextProviderConfig.base_url_override ?? '',
    model: nextProviderConfig.model,
    runtime: cloneRuntimeConfig(nextProviderConfig.runtime),
    provider_configs: providerConfigs,
  };
}

function applyModelProfile(config: AppConfig, profile: ModelCapabilityInfo | null): AppConfig {
  if (!profile) {
    return updateCurrentProviderConfig(config, {
      runtime: { structured_output_mode: config.runtime?.structured_output_mode ?? 'auto' },
    });
  }
  const runtime: AppConfig['runtime'] = {
    structured_output_mode: config.runtime?.structured_output_mode ?? 'auto',
  };
  for (const key of profile.supported_params) {
    const current = config.runtime?.[key];
    const fallback = profile.defaults[key];
    if (typeof current === 'number') {
      runtime[key] = current;
      continue;
    }
    if (typeof fallback === 'number') {
      runtime[key] = fallback;
    }
  }
  return updateCurrentProviderConfig(config, { runtime });
}
const DEFAULT_ACTION_CHECK_ROLL_STATE: ActionCheckRollState = {
  open: false,
  phase: 'ready',
  plan: null,
  rollValue: null,
  result: null,
  errorMessage: '',
  rotation: { x: 0, y: 0, z: 0 },
};
const DEFAULT_PUBLIC_TURN_OPPOSED_ROLL_STATE: PublicTurnOpposedRollState = {
  open: false,
  phase: 'ready',
  rollValue: null,
  result: null,
  errorMessage: '',
  rotation: { x: 0, y: 0, z: 0 },
};
const DEFAULT_PUBLIC_TURN_DEATH_SAVE_ROLL_STATE: PublicTurnDeathSaveRollState = {
  open: false,
  phase: 'ready',
  rollValue: null,
  errorMessage: '',
  rotation: { x: 0, y: 0, z: 0 },
};

function sumSpellSlots(slots: Record<string, number>): number {
  return Object.values(slots).reduce((sum, value) => sum + Number(value || 0), 0);
}

function buildPartyPreviewEntries(
  player: PlayerStaticData,
  team: TeamState,
  roleCards: NpcRoleCard[],
): PartyPreviewEntry[] {
  const roleMap = new Map(roleCards.map((role) => [role.role_id, role]));
  const playerSheet = player.dnd5e_sheet;
  const playerEntry: PartyPreviewEntry = {
    id: player.player_id,
    kind: 'player',
    name: player.name,
    portraitAssetId: player.portrait?.asset_id ?? null,
    hpCurrent: playerSheet.hit_points.current,
    hpMax: playerSheet.hit_points.maximum,
    tempHp: playerSheet.hit_points.temporary,
    spellSlotsCurrent: sumSpellSlots(playerSheet.spell_slots_current as Record<string, number>),
    spellSlotsMax: sumSpellSlots(playerSheet.spell_slots_max as Record<string, number>),
    martialPointsCurrent: playerSheet.martial_points_current,
    martialPointsMax: playerSheet.martial_points_maximum,
    roleActionStatus: playerSheet.role_action_status,
    retained: false,
  };

  const teammateEntries = team.members.map((member) => {
    const role = roleMap.get(member.role_id) ?? null;
    const sheet = role?.profile.dnd5e_sheet ?? null;
    return {
      id: member.role_id,
      kind: 'teammate' as const,
      name: member.name,
      portraitAssetId: role?.portrait?.asset_id ?? role?.profile.portrait?.asset_id ?? null,
      hpCurrent: sheet?.hit_points.current ?? 0,
      hpMax: sheet?.hit_points.maximum ?? 0,
      tempHp: sheet?.hit_points.temporary ?? 0,
      spellSlotsCurrent: sumSpellSlots((sheet?.spell_slots_current ?? {}) as Record<string, number>),
      spellSlotsMax: sumSpellSlots((sheet?.spell_slots_max ?? {}) as Record<string, number>),
      martialPointsCurrent: sheet?.martial_points_current ?? 0,
      martialPointsMax: sheet?.martial_points_maximum ?? 0,
      roleActionStatus: sheet?.role_action_status ?? 'free_action',
      retained: Boolean(role?.retained_id),
      loading: role == null,
    };
  });

  return [playerEntry, ...teammateEntries];
}

function App() {
  const [authState, setAuthState] = useState<'checking' | 'authed' | 'guest'>('checking');
  const [authError, setAuthError] = useState<string>('');
  const [authNotice, setAuthNotice] = useState<string>('');
  const [accountConfigReady, setAccountConfigReady] = useState(false);

  const [view, setView] = useState<View>('boot');
  const [configReturnView, setConfigReturnView] = useState<View>('boot');
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [currentMainOutput, setCurrentMainOutput] = useState<MainOutput | null>(null);
  const [publicTurnImpacts, setPublicTurnImpacts] = useState<PublicTurnImpact[]>([]);
  const [showFoldedMainSceneEvents, setShowFoldedMainSceneEvents] = useState(false);
  const [mainLiveProgress, setMainLiveProgress] = useState<LiveProgressEntry[]>([]);
  const [npcChatMessages, setNpcChatMessages] = useState<Record<string, ChatMessage[]>>({});
  const [npcLiveProgress, setNpcLiveProgress] = useState<Record<string, LiveProgressEntry[]>>({});
  const [chatMode, setChatMode] = useState<ChatMode>('main');
  const [activeNpcChat, setActiveNpcChat] = useState<{ npcId: string; npcName: string } | null>(null);
  const [activeTeammateChat, setActiveTeammateChat] = useState<ActiveTeammateChat | null>(null);
  const [teammateChatActionInput, setTeammateChatActionInput] = useState('');
  const [teammateChatSpeechInput, setTeammateChatSpeechInput] = useState('');
  const [teammateChatLastActionInput, setTeammateChatLastActionInput] = useState('');
  const [teammateChatLastSpeechInput, setTeammateChatLastSpeechInput] = useState('');
  const [lastActionInput, setLastActionInput] = useState('');
  const [lastSpeechInput, setLastSpeechInput] = useState('');
  const [actionInput, setActionInput] = useState('');
  const [speechInput, setSpeechInput] = useState('');
  const [playerQuickActionOpen, setPlayerQuickActionOpen] = useState(false);
  const [playerQuickActionMode, setPlayerQuickActionMode] = useState<PlayerQuickActionMode>('root');
  const [tokenUsage, setTokenUsage] = useState<TokenUsageSummary>(EMPTY_TOKEN_USAGE);
  const [chatState, setChatState] = useState<ChatState>('idle');
  const [godMode, setGodMode] = useState(false);
  const [error, setError] = useState('');
  const [configHint, setConfigHint] = useState('');
  const [sessionId, setSessionId] = useState(() => `sess_${Date.now()}`);
  const [configPath, setCfgPath] = useState<PathStatus | null>(null);
  const [configDraft, setConfigDraft] = useState<AppConfig>(defaultConfig);
  const [hasStoredConfig, setHasStoredConfig] = useState(false);
  const [configModels, setConfigModels] = useState<ModelCapabilityInfo[]>([]);
  const [configProfile, setConfigProfile] = useState<ModelCapabilityInfo | null>(null);
  const [configModelsLoading, setConfigModelsLoading] = useState(false);
  const [configProfileLoading, setConfigProfileLoading] = useState(false);
  const [manualModelMode, setManualModelMode] = useState(false);

  const [debugOpen, setDebugOpen] = useState(false);
  const [debugEntries, setDebugEntries] = useState<ApiDebugEntry[]>([]);
  const [savePath, setSvPath] = useState<PathStatus | null>(null);
  const [templateLibraryStatus, setTemplateLibraryStatus] = useState<TemplateLibraryStatusResponse | null>(null);
  const [characterBuildState, setCharacterBuildState] = useState<CharacterBuildStateResponse | null>(null);
  const [characterBuildOpen, setCharacterBuildOpen] = useState(false);
  const [characterBuildMode, setCharacterBuildMode] = useState<'player' | 'companion'>('player');
  const [companionBuildOfferOpen, setCompanionBuildOfferOpen] = useState(false);

  const [mapEnabled, setMapEnabled] = useState(false);
  const [mapPromptDialogOpen, setMapPromptDialogOpen] = useState(false);
  const [mapWorldPrompt, setMapWorldPrompt] = useState('');
  const [mapPromptInput, setMapPromptInput] = useState('');
  const [mapOpen, setMapOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [areaSnapshot, setAreaSnapshot] = useState<AreaSnapshot | null>(null);
  const [currentReputation, setCurrentReputation] = useState<SubZoneReputationEntry | null>(null);
  const [currentZoneMetric, setCurrentZoneMetric] = useState<ZoneMetricEntry | null>(null);
  const [zoneMetricState, setZoneMetricState] = useState<ZoneMetricState>({ version: '0.1.0', entries: [], updated_at: '' });
  const [questState, setQuestState] = useState<QuestState>(defaultQuestState);
  const [encounterState, setEncounterState] = useState<EncounterState>(defaultEncounterState);
  const [fateState, setFateState] = useState<FateState>(defaultFateState);
  const [gameLogs, setGameLogs] = useState<GameLogEntry[]>([]);
  const [gameLogFetchLimit, setGameLogFetchLimit] = useState(10);
  const [mapSearch, setMapSearch] = useState('');
  const [mapSnapshot, setMapSnapshot] = useState<MapSnapshot>({ player_position: null, zones: [] });
  const [mapRender, setMapRender] = useState<RenderResult | null>(null);
  const [playerPanelOpen, setPlayerPanelOpen] = useState(false);
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [inventoryBusy, setInventoryBusy] = useState(false);
  const [teamInventoryRole, setTeamInventoryRole] = useState<NpcRoleCard | null>(null);
  const [teamProfileRole, setTeamProfileRole] = useState<NpcRoleCard | null>(null);
  const [itemInteractionOpen, setItemInteractionOpen] = useState(false);
  const [itemInteractionBusy, setItemInteractionBusy] = useState(false);
  const [itemInteractionOwner, setItemInteractionOwner] = useState<InventoryOwnerRef | null>(null);
  const [itemInteractionItem, setItemInteractionItem] = useState<{ itemId: string; itemName: string } | null>(null);
  const [itemInteractionMode, setItemInteractionMode] = useState<'inspect' | 'use'>('inspect');
  const [itemInteractionPrompt, setItemInteractionPrompt] = useState('');
  const [itemInteractionLastReply, setItemInteractionLastReply] = useState('');
  const [questInspectOpen, setQuestInspectOpen] = useState(false);
  const [fatePanelOpen, setFatePanelOpen] = useState(false);
  const [teamOpen, setTeamOpen] = useState(false);
  const [teamState, setTeamState] = useState<TeamState>(defaultTeamState);
  const [teamChatBusy, setTeamChatBusy] = useState(false);
  const [teamChatReplies, setTeamChatReplies] = useState<TeamChatReply[]>([]);
  const [consistencyOpen, setConsistencyOpen] = useState(false);
  const [consistencyBusy, setConsistencyBusy] = useState(false);
  const [consistencyIssues, setConsistencyIssues] = useState<ConsistencyIssue[]>([]);
  const [consistencyIssueCount, setConsistencyIssueCount] = useState(0);
  const [storySnapshot, setStorySnapshot] = useState<GlobalStorySnapshot | null>(null);
  const [worldState, setWorldState] = useState(defaultWorldState);
  const [npcPoolOpen, setNpcPoolOpen] = useState(false);
  const [npcPoolSearch, setNpcPoolSearch] = useState('');
  const [npcPoolItems, setNpcPoolItems] = useState<NpcRoleCard[]>([]);
  const [npcPoolTotal, setNpcPoolTotal] = useState(0);
  const [npcSelected, setNpcSelected] = useState<NpcRoleCard | null>(null);
  const [actionPanelOpen, setActionPanelOpen] = useState(false);
  const [playerInputValidationPanelOpen, setPlayerInputValidationPanelOpen] = useState(false);
  const [playerInputValidationDebugBusy, setPlayerInputValidationDebugBusy] = useState(false);
  const [playerInputValidationModalState, setPlayerInputValidationModalState] = useState<PlayerInputValidationModalState | null>(null);
  const [lastPlayerInputValidationResult, setLastPlayerInputValidationResult] = useState<PlayerInputValidationResponse | null>(null);
  const [lastActionResult, setLastActionResult] = useState<ActionCheckResult | null>(null);
  const [actionCheckRollState, setActionCheckRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [publicTurnActionRollState, setPublicTurnActionRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [reactionCheckRollState, setReactionCheckRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [pendingReactionState, setPendingReactionState] = useState<PendingReactionState | null>(null);
  const [pendingInteractionState, setPendingInteractionState] = useState<PendingInteractionState | null>(null);
  const [publicTurnInteractionActionInput, setPublicTurnInteractionActionInput] = useState('');
  const [publicTurnInteractionSpeechInput, setPublicTurnInteractionSpeechInput] = useState('');
  const [publicTurnInteractionBusy, setPublicTurnInteractionBusy] = useState(false);
  const [publicTurnInteractionError, setPublicTurnInteractionError] = useState('');
  const [pendingAttackState, setPendingAttackState] = useState<PendingAttackState | null>(null);
  const [publicTurnAttackActionInput, setPublicTurnAttackActionInput] = useState('');
  const [publicTurnAttackSpeechInput, setPublicTurnAttackSpeechInput] = useState('');
  const [publicTurnAttackBusy, setPublicTurnAttackBusy] = useState(false);
  const [publicTurnAttackError, setPublicTurnAttackError] = useState('');
  const [pendingAttackDefenseState, setPendingAttackDefenseState] = useState<PendingAttackDefenseState | null>(null);
  const [publicTurnAttackDefenseRollState, setPublicTurnAttackDefenseRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [pendingDeathSaveState, setPendingDeathSaveState] = useState<PendingDeathSaveState | null>(null);
  const [publicTurnDeathSaveRollState, setPublicTurnDeathSaveRollState] = useState<PublicTurnDeathSaveRollState>(DEFAULT_PUBLIC_TURN_DEATH_SAVE_ROLL_STATE);
  const [publicTurnDeathSaveSummary, setPublicTurnDeathSaveSummary] = useState('');
  const [pendingOpposedState, setPendingOpposedState] = useState<PendingOpposedState | null>(null);
  const [publicTurnOpposedPlan, setPublicTurnOpposedPlan] = useState<PublicTurnOpposedPlanResponse | null>(null);
  const [publicTurnOpposedActionInput, setPublicTurnOpposedActionInput] = useState('');
  const [publicTurnOpposedSpeechInput, setPublicTurnOpposedSpeechInput] = useState('');
  const [publicTurnOpposedRollState, setPublicTurnOpposedRollState] = useState<PublicTurnOpposedRollState>(DEFAULT_PUBLIC_TURN_OPPOSED_ROLL_STATE);
  const [timeNotices, setTimeNotices] = useState<Array<{ id: number; text: string }>>([]);
  const [playerStatic, setPlayerStaticState] = useState<PlayerStaticData>(defaultPlayerStaticData);
  const [playerRuntime, setPlayerRuntimeState] = useState<PlayerRuntimeData>({
    session_id: sessionId,
    current_position: DEFAULT_POSITION,
    updated_at: new Date().toISOString(),
  });
  const [aiWaiting, setAiWaiting] = useState(false);
  const [aiWaitingText, setAiWaitingText] = useState('正在等待 AI 生成...');
  const [questModalBusy, setQuestModalBusy] = useState(false);
  const [encounterModalBusy, setEncounterModalBusy] = useState(false);
  const [encounterModalEncounterId, setEncounterModalEncounterId] = useState<string | null>(null);
  const [battleStartDialogOpen, setBattleStartDialogOpen] = useState(false);
  const [battleStartBusy, setBattleStartBusy] = useState(false);
  const [activeBattle, setActiveBattle] = useState<BattleSandboxState | null>(null);
  const [battleBusy, setBattleBusy] = useState(false);
  const [battleRollState, setBattleRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [minimizedBlockingModal, setMinimizedBlockingModal] = useState<BlockingModalKey | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const activeStreamRef = useRef<{ kind: 'main' } | { kind: 'npc'; npcId: string; previousMessages: ChatMessage[] } | null>(null);
  const announcedEncounterIdsRef = useRef<Set<string>>(new Set());
  const autoRejoinEncounterIdRef = useRef<string | null>(null);
  const pendingActionCheckRef = useRef<ActionCheckPayload | null>(null);
  const actionCheckPromiseRef = useRef<{ resolve: (result: ActionCheckResult | null) => void; reject: (error: Error) => void } | null>(null);
  const playerInputValidationPromiseRef = useRef<{ resolve: (result: ValidatedPlayerInput | null) => void; reject: (error: Error) => void } | null>(null);
  const playerInputValidationBypassRef = useRef<PlayerInputValidationBypassToken | null>(null);
  const pendingPublicTurnActionRef = useRef<PendingPublicTurnAction | null>(null);
  const publicTurnActionResponseRef = useRef<PublicTurnResponse | PendingTurnContinueResponse | null>(null);
  const pendingDeathSaveResponseRef = useRef<PendingTurnContinueResponse | PublicTurnResponse | null>(null);
  const pendingReactionResponseRef = useRef<PendingTurnContinueResponse | PublicTurnResponse | null>(null);
  const pendingOpposedResponseRef = useRef<PendingTurnContinueResponse | PublicTurnResponse | null>(null);
  const actionInputRef = useRef<HTMLTextAreaElement | null>(null);

  const statusText = useMemo(() => {
    if (chatState === 'sending') return '发送中...';
    if (chatState === 'streaming') return '生成中...';
    if (chatState === 'awaiting_interaction') return '等待交互回应...';
    if (chatState === 'awaiting_attack_response') return '等待攻击回应...';
    if (chatState === 'awaiting_attack_defense') return '等待攻击对抗掷骰...';
    if (chatState === 'awaiting_death_save') return '等待死亡豁免...';
    if (chatState === 'awaiting_reaction') return '等待反应检定...';
    if (chatState === 'awaiting_opposed') return '等待对抗回应...';
    if (chatState === 'awaiting_protocol_repair') return '正在修复 AI 协议输出...';
    if (chatState === 'error') return `错误: ${error}`;
    return '就绪';
  }, [chatState, error]);

  const report = (entry: { endpoint: string; status: number; ok: boolean; detail?: string; usage?: { input_tokens: number; output_tokens: number } }) => {
    setDebugEntries((prev) => [
      {
        endpoint: entry.endpoint,
        status: entry.status,
        ok: entry.ok,
        detail: entry.detail,
        usage: entry.usage,
        at: new Date().toLocaleTimeString(),
      },
      ...prev,
    ].slice(0, 20));
  };

  const performPlayerInputValidation = async ({
    entryPoint,
    actorRoleId,
    actionText,
    speechText,
  }: {
    entryPoint: PlayerInputValidationEntryPoint;
    actorRoleId?: string;
    actionText: string;
    speechText: string;
  }): Promise<ValidatedPlayerInput | null> => {
    const trimmedAction = actionText.trim();
    const trimmedSpeech = speechText.trim();
    if (!trimmedAction) {
      return {
        actionText: trimmedAction,
        speechText: trimmedSpeech,
        response: null,
      };
    }

    const effectiveActorRoleId = actorRoleId ?? playerStatic.player_id;
    const bypass = playerInputValidationBypassRef.current;
    if (
      bypass &&
      bypass.entryPoint === entryPoint &&
      bypass.actorRoleId === effectiveActorRoleId &&
      bypass.actionText === trimmedAction &&
      bypass.speechText === trimmedSpeech
    ) {
      playerInputValidationBypassRef.current = null;
      return {
        actionText: trimmedAction,
        speechText: trimmedSpeech,
        response: null,
      };
    }

    const response = await validatePlayerInput(
      {
        session_id: sessionId,
        entry_point: entryPoint,
        action_text: trimmedAction,
        speech_text: trimmedSpeech,
        actor_role_id: effectiveActorRoleId,
        config,
      },
      report,
    );
    setLastPlayerInputValidationResult(response);
    if (response.status === 'accepted') {
      return {
        actionText: response.normalized_action_text.trim(),
        speechText: response.normalized_speech_text.trim(),
        response,
      };
    }
    if (playerInputValidationPromiseRef.current) {
      throw new Error('已有待确认的玩家输入校验结果。');
    }
    setPlayerInputValidationModalState({
      entryPoint,
      originalActionText: trimmedAction,
      originalSpeechText: trimmedSpeech,
      response,
    });
    return new Promise<ValidatedPlayerInput | null>((resolve, reject) => {
      playerInputValidationPromiseRef.current = { resolve, reject };
    });
  };

  const onAcceptPlayerInputValidationSuggestion = () => {
    const pending = playerInputValidationPromiseRef.current;
    const modalState = playerInputValidationModalState;
    if (!pending || !modalState) return;
    const suggestion = getPlayerInputValidationSuggestion(modalState.response);
    playerInputValidationBypassRef.current = {
      entryPoint: modalState.entryPoint,
      actorRoleId: modalState.response.actor_role_id,
      actionText: suggestion.actionText,
      speechText: suggestion.speechText,
    };
    playerInputValidationPromiseRef.current = null;
    setPlayerInputValidationModalState(null);
    pending.resolve({
      actionText: suggestion.actionText,
      speechText: suggestion.speechText,
      response: modalState.response,
    });
  };

  const onReturnToEditPlayerInputValidation = () => {
    const pending = playerInputValidationPromiseRef.current;
    playerInputValidationPromiseRef.current = null;
    setPlayerInputValidationModalState(null);
    if (!pending) return;
    pending.resolve(null);
  };

  useEffect(() => {
    void (async () => {
      try {
        const me = await authMe(report);
        if (me?.ok) {
          setAuthState('authed');
          return;
        }
      } catch {
        // ignore
      }
      setAuthState('guest');
    })();
  }, []);

  useEffect(() => {
    const missingRoleIds = teamState.members
      .filter((member) => !npcPoolItems.some((role) => role.role_id === member.role_id))
      .map((member) => member.role_id);
    if (missingRoleIds.length === 0) return;

    let cancelled = false;
    void (async () => {
      const loadedRoles = await Promise.all(
        missingRoleIds.map(async (roleId) => {
          try {
            return await getRoleCard(sessionId, roleId, report);
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      loadedRoles.filter((role): role is NpcRoleCard => role !== null).forEach((role) => replaceCachedRoleCard(role));
    })();

    return () => {
      cancelled = true;
    };
  }, [npcPoolItems, sessionId, teamState.members]);

  const onDoLogin = async (payload: { username: string; password: string }) => {
    setAuthError('');
    setAuthNotice('');
    try {
      await authLogin(payload, report);
      setAuthState('authed');
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    }
  };

  const onDoRegister = async (payload: { username: string; password: string }) => {
    setAuthError('');
    setAuthNotice('');
    try {
      await authRegister(payload, report);
      await onDoLogin(payload);
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    }
  };

  const onDoResetPassword = async (payload: { username: string; current_password: string; new_password: string }) => {
    setAuthError('');
    setAuthNotice('');
    try {
      await authResetPassword(payload, report);
      setAuthNotice('密码已重置，请使用新密码登录。');
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    }
  };

  const onDoLogout = async () => {
    setAuthError('');
    setAuthNotice('');
    try {
      await authLogout(report);
    } catch {
      // Ignore logout failure and still clear local auth state.
    } finally {
      setAuthState('guest');
      setAccountConfigReady(false);
      setHasStoredConfig(false);
      setView('boot');
      setConfig(defaultConfig);
      setConfigDraft(defaultConfig);
      setConfigHint('');
      setError('');
    }
  };

  useEffect(() => {
    if (authState !== 'authed') return;
    if (view !== 'config') return;
    const model = configDraft.model.trim();
    if (!model) {
      setConfigProfile(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setConfigProfileLoading(true);
      try {
        const result = await getConfigModelProfile(
          {
            provider: configDraft.provider,
            model,
            api_key: configDraft.api_key,
            base_url_override: configDraft.base_url_override,
          },
          report,
        );
        if (cancelled) return;
        setConfigProfile(result.model);
        setConfigDraft((prev) => (prev.model.trim() === model ? applyModelProfile(prev, result.model) : prev));
      } catch (e) {
        if (cancelled) return;
        setConfigProfile(null);
        setError(e instanceof Error ? e.message : '模型能力解析失败');
      } finally {
        if (!cancelled) setConfigProfileLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [view, configDraft.provider, configDraft.base_url_override, configDraft.api_key, configDraft.model]);

  const currentSubZone = useMemo(() => {
    if (!areaSnapshot?.current_sub_zone_id) return null;
    return areaSnapshot.sub_zones.find((s) => s.sub_zone_id === areaSnapshot.current_sub_zone_id) ?? null;
  }, [areaSnapshot]);
  const livePublicTurnState =
    currentMainOutput?.source_kind === 'main_turn' ? currentMainOutput.public_turn_state ?? null : null;
  const livePublicTurnPresentation =
    currentMainOutput?.source_kind === 'main_turn' ? currentMainOutput.public_turn_presentation ?? null : null;
  const publicTurnState: PublicTurnState = livePublicTurnState ?? currentSubZone?.chat_context?.public_turn_state ?? defaultPublicTurnState;
  const publicTurnRound = publicTurnState.current_round ?? null;
  const publicTurnPhase = publicTurnRound?.phase ?? 'idle';
  const playerPublicTurnActionStatus: RoleActionStatus = playerStatic.dnd5e_sheet.role_action_status;
  const playerSpeechOnlyInPublicTurn = playerPublicTurnActionStatus === 'death_saving' || playerPublicTurnActionStatus === 'unable_to_act';
  const publicTurnAwaitingPlayerAction = Boolean(chatMode === 'main' && publicTurnRound?.awaiting_player_action);
  const publicTurnAwaitingEntry = Boolean(chatMode === 'main' && publicTurnState.awaiting_player_entry && !publicTurnRound);
  const publicTurnEnabled = Boolean(chatMode === 'main' && currentSubZone);
  const currentPublicTurnActorName = useMemo(() => {
    const actorId = publicTurnRound?.current_actor_id;
    if (!actorId) return null;
    if (actorId === playerStatic.player_id) return playerStatic.name;
    return (
      teamState.members.find((member) => member.role_id === actorId)?.name ??
      npcPoolItems.find((role) => role.role_id === actorId)?.name ??
      null
    );
  }, [npcPoolItems, playerStatic.name, playerStatic.player_id, publicTurnRound?.current_actor_id, teamState.members]);
  const currentZone = useMemo(() => {
    if (!areaSnapshot?.current_zone_id) return null;
    return areaSnapshot.zones.find((z) => z.zone_id === areaSnapshot.current_zone_id) ?? null;
  }, [areaSnapshot]);
  const pendingQuest = useMemo(() => {
    const pending = [...(questState.quests ?? [])].filter((item) => item.status === 'pending_offer');
    pending.sort((a, b) => {
      if (a.source !== b.source) return a.source === 'fate' ? -1 : 1;
      return a.offered_at.localeCompare(b.offered_at);
    });
    return pending[0] ?? null;
  }, [questState]);
  const currentQuest = useMemo(() => {
    const tracked = (questState.quests ?? []).find((item) => item.is_tracked);
    if (tracked) return tracked;
    return (questState.quests ?? []).find((item) => item.status === 'active') ?? null;
  }, [questState]);
  const activeEncounter = useMemo(() => {
    const active = encounterState.active_encounter_id
      ? encounterState.encounters.find((item) => item.encounter_id === encounterState.active_encounter_id) ?? null
      : null;
    if (active && (active.status === 'active' || active.status === 'escaped')) return active;
    return null;
  }, [encounterState]);
  const queuedEncounters = useMemo(() => {
    const queued: EncounterEntry[] = [];
    for (const encounterId of encounterState.pending_ids) {
      const found = encounterState.encounters.find((item) => item.encounter_id === encounterId);
      if (found && found.status === 'queued') queued.push(found);
    }
    return queued;
  }, [encounterState]);
  const pendingEncounter = activeEncounter ?? queuedEncounters[0] ?? null;
  const encounterEngaged = Boolean(activeEncounter && activeEncounter.status === 'active' && activeEncounter.player_presence === 'engaged');
  const canRejoinActiveEncounter = Boolean(
    activeEncounter &&
      activeEncounter.player_presence === 'away' &&
      activeEncounter.zone_id === areaSnapshot?.current_zone_id &&
      (activeEncounter.sub_zone_id ? activeEncounter.sub_zone_id === areaSnapshot?.current_sub_zone_id : true),
  );
  const encounterModalEncounter = useMemo(() => {
    if (!encounterModalEncounterId) return null;
    return encounterState.encounters.find((item) => item.encounter_id === encounterModalEncounterId) ?? null;
  }, [encounterState.encounters, encounterModalEncounterId]);
  const encounterModalOpen = Boolean(encounterModalEncounter);
  const visibleQuestModal = Boolean(pendingQuest && minimizedBlockingModal !== 'quest');
  const visibleEncounterModal = Boolean(encounterModalOpen && minimizedBlockingModal !== 'encounter');
  const visiblePublicTurnActionRoll = Boolean(publicTurnActionRollState.open && minimizedBlockingModal !== 'public_turn_action_roll');
  const visiblePublicTurnInteraction = Boolean(pendingInteractionState && minimizedBlockingModal !== 'public_turn_interaction');
  const visiblePublicTurnAttackResponse = Boolean(pendingAttackState && minimizedBlockingModal !== 'public_turn_attack_response');
  const visiblePublicTurnAttackDefense = Boolean(
    pendingAttackDefenseState && publicTurnAttackDefenseRollState.open && minimizedBlockingModal !== 'public_turn_attack_defense',
  );
  const visiblePublicTurnDeathSave = Boolean(
    pendingDeathSaveState && publicTurnDeathSaveRollState.open && minimizedBlockingModal !== 'public_turn_death_save',
  );
  const visiblePublicTurnOpposed = Boolean(pendingOpposedState && minimizedBlockingModal !== 'public_turn_opposed');
  const visibleReactionRoll = Boolean(reactionCheckRollState.open && minimizedBlockingModal !== 'reaction_roll');
  const visibleBattleModal = Boolean(activeBattle && minimizedBlockingModal !== 'battle');
  const visibleBattleRoll = Boolean(battleRollState.open && minimizedBlockingModal !== 'battle_roll');
  const playerBuildCompleted = characterBuildState?.state.player_status === 'completed';
  const blockingWorkflowActive = Boolean(
    pendingQuest ||
      mapPromptDialogOpen ||
      aiWaiting ||
      characterBuildOpen ||
      companionBuildOfferOpen ||
      actionCheckRollState.open ||
      publicTurnActionRollState.open ||
      pendingInteractionState ||
      pendingAttackState ||
      publicTurnAttackDefenseRollState.open ||
      publicTurnDeathSaveRollState.open ||
      pendingOpposedState ||
      publicTurnOpposedRollState.open ||
      reactionCheckRollState.open ||
      playerInputValidationModalState ||
      battleRollState.open ||
      battleStartDialogOpen ||
      activeBattle ||
      encounterModalBusy ||
      encounterModalOpen,
  );
  const hasActionInput = actionInput.trim().length > 0;
  const hasSpeechInput = speechInput.trim().length > 0;
  const canSend =
    (chatMode === 'npc' ? hasActionInput || hasSpeechInput : hasActionInput || hasSpeechInput) &&
    (chatState === 'idle' || chatState === 'error') &&
    !blockingWorkflowActive;
  const canAutoAdvance = chatMode === 'main' && encounterEngaged && (chatState === 'idle' || chatState === 'error') && !blockingWorkflowActive;

  useEffect(() => {
    if (!minimizedBlockingModal) return;
    const stillActive =
      (minimizedBlockingModal === 'quest' && Boolean(pendingQuest)) ||
      (minimizedBlockingModal === 'encounter' && encounterModalOpen) ||
      (minimizedBlockingModal === 'public_turn_action_roll' && publicTurnActionRollState.open) ||
      (minimizedBlockingModal === 'public_turn_interaction' && Boolean(pendingInteractionState)) ||
      (minimizedBlockingModal === 'public_turn_attack_response' && Boolean(pendingAttackState)) ||
      (minimizedBlockingModal === 'public_turn_attack_defense' && publicTurnAttackDefenseRollState.open) ||
      (minimizedBlockingModal === 'public_turn_death_save' && publicTurnDeathSaveRollState.open) ||
      (minimizedBlockingModal === 'public_turn_opposed' && Boolean(pendingOpposedState)) ||
      (minimizedBlockingModal === 'reaction_roll' && reactionCheckRollState.open) ||
      (minimizedBlockingModal === 'battle_start' && battleStartDialogOpen) ||
      (minimizedBlockingModal === 'battle' && Boolean(activeBattle)) ||
      (minimizedBlockingModal === 'battle_roll' && battleRollState.open);
    if (!stillActive) {
      setMinimizedBlockingModal(null);
    }
  }, [
    minimizedBlockingModal,
    pendingQuest,
    encounterModalOpen,
    publicTurnActionRollState.open,
    pendingInteractionState,
    pendingAttackState,
    publicTurnAttackDefenseRollState.open,
    publicTurnDeathSaveRollState.open,
    pendingOpposedState,
    reactionCheckRollState.open,
    battleStartDialogOpen,
    activeBattle,
    battleRollState.open,
  ]);

  const tokenTotal = tokenUsage.total.total_tokens;
  const partyPreviewEntries = useMemo(
    () => buildPartyPreviewEntries(playerStatic, teamState, npcPoolItems),
    [npcPoolItems, playerStatic, teamState],
  );
  const npcDisplayedMessages = activeNpcChat ? (npcChatMessages[activeNpcChat.npcId] ?? []) : [];
  const activeTeammateRole = useMemo(
    () => npcPoolItems.find((item) => item.role_id === activeTeammateChat?.npcId) ?? null,
    [activeTeammateChat?.npcId, npcPoolItems],
  );
  const activeTeammateMember = useMemo(
    () => teamState.members.find((item) => item.role_id === activeTeammateChat?.npcId) ?? null,
    [activeTeammateChat?.npcId, teamState.members],
  );
  const activeTeammateMessages = activeTeammateChat ? (npcChatMessages[activeTeammateChat.npcId] ?? []) : [];
  const activeTeammateLiveProgress = activeTeammateChat ? (npcLiveProgress[activeTeammateChat.npcId] ?? []) : [];
  const teammateChatHasInput = teammateChatActionInput.trim().length > 0 || teammateChatSpeechInput.trim().length > 0;
  const teammateChatInputDisabled =
    !activeTeammateRole ||
    blockingWorkflowActive ||
    encounterEngaged ||
    chatState === 'sending' ||
    chatState === 'streaming';
  const teammateChatSendDisabled = teammateChatInputDisabled || !teammateChatHasInput;
  const teammateChatDisabledHint = !activeTeammateRole
    ? '正在载入队友数据，暂时无法发送。'
    : encounterEngaged
      ? '遭遇进行中，请直接在主聊天描述动作或发言。'
      : blockingWorkflowActive
        ? '当前存在未完成流程，需先处理后才能继续与队友单聊。'
        : '';
  const setNpcDisplayedMessages = (next: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    const npcId = activeNpcChat?.npcId;
    if (!npcId) return;
    setNpcChatMessages((prev) => {
      const current = prev[npcId] ?? [];
      const resolved = typeof next === 'function' ? next(current) : next;
      return { ...prev, [npcId]: resolved };
    });
  };
  const upsertLiveProgress = (entries: LiveProgressEntry[], next: LiveProgressEntry): LiveProgressEntry[] => {
    const existingIndex = entries.findIndex((entry) => entry.id === next.id);
    if (existingIndex < 0) {
      return [...entries, next];
    }
    const updated = [...entries];
    updated[existingIndex] = next;
    return updated;
  };
  const toPhaseProgressEntry = (event: StreamPhaseEvent): LiveProgressEntry => ({
    id: `phase:${event.code}`,
    kind: 'phase',
    label: event.label || event.code,
    status: event.status,
    detail: event.detail,
  });
  const toToolProgressEntry = (event: LiveToolEvent): LiveProgressEntry => ({
    id: `tool:${event.tool_name}`,
    kind: 'tool',
    label: event.tool_name,
    status: event.status,
    detail: event.summary,
  });
  const clearLiveProgress = () => {
    setMainLiveProgress([]);
    setNpcLiveProgress({});
  };
  const clearNpcLiveProgress = (npcId: string) => {
    setNpcLiveProgress((prev) => {
      if (!(npcId in prev)) return prev;
      const next = { ...prev };
      delete next[npcId];
      return next;
    });
  };
  const restoreAbortedNpcStream = () => {
    const activeStream = activeStreamRef.current;
    if (!activeStream || activeStream.kind !== 'npc') return;
    setNpcChatMessages((prev) => ({
      ...prev,
      [activeStream.npcId]: activeStream.previousMessages,
    }));
    clearNpcLiveProgress(activeStream.npcId);
    activeStreamRef.current = null;
  };
  const handleStreamRollback = (payload: TurnRollbackPayload) => {
    void payload;
    if (activeStreamRef.current?.kind === 'main') {
      setCurrentMainOutput(null);
    }
    if (activeStreamRef.current?.kind === 'npc') {
      restoreAbortedNpcStream();
    }
    clearLiveProgress();
    activeStreamRef.current = null;
  };
  const isAlreadyThereHint = (text: string): boolean => text.trim().startsWith('你已在');
  const showAlreadyTherePopup = (text: string): void => {
    window.alert(text);
  };
  const filterMainOutputSceneEvents = (sceneEvents: SceneEvent[] = []): SceneEvent[] =>
    sceneEvents.filter((event) => MAIN_OUTPUT_SCENE_EVENT_KINDS.has(event.kind));
  const setMainOutput = (
    sourceKind: MainOutput['source_kind'],
    replyText: string,
    sceneEvents: SceneEvent[] = [],
    options?: { archivedSubZoneTurnId?: string | null; mainTurnSummary?: MainTurnSummary | null; status?: MainOutputStatus },
  ): void => {
    const trimmedReply = replyText.trim();
    if (trimmedReply && isAlreadyThereHint(trimmedReply)) {
      showAlreadyTherePopup(replyText);
      return;
    }
    const visibleSceneEvents = filterMainOutputSceneEvents(sceneEvents);
    if (!trimmedReply && visibleSceneEvents.length === 0) {
      setCurrentMainOutput(null);
      return;
    }
    setShowFoldedMainSceneEvents(false);
    setCurrentMainOutput({
      source_kind: sourceKind,
      reply_text: replyText,
      scene_events: visibleSceneEvents,
      archived_sub_zone_turn_id: options?.archivedSubZoneTurnId ?? null,
      main_turn_summary: options?.mainTurnSummary ?? null,
      public_turn_state: null,
      public_turn_presentation: null,
      status: options?.status ?? 'idle',
    });
  };
  const setAssistantOnly = (text: string): void => {
    if (isAlreadyThereHint(text)) {
      showAlreadyTherePopup(text);
      return;
    }
    if (chatMode === 'npc') {
      setNpcDisplayedMessages([{ role: 'assistant', content: text }]);
      return;
    }
    setMainOutput('system_output', text);
  };
  const setMainAssistantOnly = (text: string): void => {
    if (isAlreadyThereHint(text)) {
      showAlreadyTherePopup(text);
      return;
    }
    setMainOutput('system_output', text);
  };
  const forceReturnToMainChat = (reason: 'encounter_interrupt' | 'manual' | 'narrative_switch') => {
    void reason;
    setChatMode('main');
    setActiveNpcChat(null);
    clearPlayerInput();
  };
  const forceReturnToMainChatEvent = useEffectEvent((reason: 'encounter_interrupt' | 'manual' | 'narrative_switch') => {
    forceReturnToMainChat(reason);
  });
  const focusMainActionInput = () => {
    window.setTimeout(() => {
      actionInputRef.current?.focus();
    }, 0);
  };
  const replaceCachedRoleCard = (role: NpcRoleCard) => {
    setNpcPoolItems((prev) => {
      const next = prev.filter((item) => item.role_id !== role.role_id);
      return [role, ...next];
    });
    setNpcSelected((prev) => (prev?.role_id === role.role_id ? role : prev));
    setTeamInventoryRole((prev) => (prev?.role_id === role.role_id ? role : prev));
    setTeamProfileRole((prev) => (prev?.role_id === role.role_id ? role : prev));
  };
  const pushTimeNotice = (minutes: number, reason: string) => {
    if (minutes <= 0) return;
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setTimeNotices((prev) => [...prev, { id, text: `时间消耗 +${minutes} 分钟（${reason}）` }]);
    window.setTimeout(() => {
      setTimeNotices((prev) => prev.filter((n) => n.id !== id));
    }, 3200);
  };
  const pushSystemNotice = (text: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setTimeNotices((prev) => [...prev, { id, text }]);
    window.setTimeout(() => {
      setTimeNotices((prev) => prev.filter((n) => n.id !== id));
    }, 3200);
  };
  const dialogueLogsToMessages = (role: NpcRoleCard): ChatMessage[] =>
    (role.dialogue_logs ?? []).map((item) => ({
      role: item.speaker === 'player' ? 'user' : 'assistant',
      content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
    }));
  const ensureNpcChatHistoryLoaded = async (npcId: string, npcName: string): Promise<NpcRoleCard | null> => {
    try {
      const role = await getRoleCard(sessionId, npcId, report);
      replaceCachedRoleCard(role);
      const fromSave = dialogueLogsToMessages(role);
      setNpcChatMessages((prev) => ({
        ...prev,
        [npcId]:
          fromSave.length > 0
            ? fromSave
            : [{ role: 'system', content: `你已接近 ${npcName}，可以只输入动作或只输入语言开始交互。` }],
      }));
      return role;
    } catch (e) {
      setError(e instanceof Error ? e.message : '进入 NPC 单聊失败');
      return null;
    }
  };
  const buildStructuredPlayerInput = (
    actionDescription: string,
    speechDescription: string,
    actionCheckResult?: ActionCheckResult | null,
    options?: { passiveTurn?: boolean; passiveMode?: 'observe' },
  ): string =>
    JSON.stringify(
      {
        input_type: 'player_intent_v1',
        action_description: actionDescription,
        speech_description: speechDescription,
        passive_turn: options?.passiveTurn || undefined,
        passive_mode: options?.passiveTurn ? options?.passiveMode ?? 'observe' : undefined,
        action_check_result: actionCheckResult
          ? {
              check_task: actionCheckResult.check_task,
              success: actionCheckResult.success,
              critical: actionCheckResult.critical,
            }
          : undefined,
      },
      null,
      2,
    );
  const buildNpcChatActionCheckPrompt = (
    npcId: string,
    npcName: string,
    actionDescription: string,
    speechDescription: string,
  ): string => {
    const role = npcPoolItems.find((item) => item.role_id === npcId) ?? null;
    const teammate = teamState.members.find((item) => item.role_id === npcId) ?? null;
    const conversationState = role?.conversation_state;
    const lines = [
      '这是一次与 NPC 的私聊互动判定，请结合动作和语言整体理解真实意图。',
      `npc_id=${npcId}`,
      `NPC姓名: ${npcName}`,
      teammate ? '对象身份: 当前队友。' : '对象身份: 场景 NPC。',
      teammate ? `当前关系: 好感度=${teammate.affinity}，信任度=${teammate.trust}。` : '',
      role ? `当前健谈值: ${role.talkative_current}/${role.talkative_maximum}` : '',
      conversationState?.current_topic ? `当前话题: ${conversationState.current_topic}` : '',
      conversationState?.last_player_intent ? `上一轮玩家意图: ${conversationState.last_player_intent}` : '',
      conversationState?.last_npc_claim ? `上一轮 NPC 表态: ${conversationState.last_npc_claim}` : '',
      `动作描述: ${actionDescription || '-'}`,
      `语言描述: ${speechDescription || '-'}`,
      '判定要求: 若动作与语言呈现调情、戏谑、试探、暧昧、双关或隐喻，请优先按社交互动、魅力试探、关系推进来理解。',
      '只有在文本明确提到门锁、箱锁、锁芯、钥匙、撬锁工具、镣铐、手铐或其他实体锁具时，才按物理开锁处理。',
      '如果描述中的“锁”“心门”“防备”“束缚”等更像人物关系或情绪隐喻，也按社交语义理解。',
    ];
    return lines.filter(Boolean).join('\n');
  };
  const buildMainChatActionCheckPrompt = (actionDescription: string, speechDescription: string): string =>
    [
      '这是主叙事聊天中的玩家意图判定，请结合动作和语言整体判断是否需要检定，以及检定目标到底是什么。',
      `动作描述: ${actionDescription || '-'}`,
      `语言描述: ${speechDescription || '-'}`,
    ].join('\n');
  const buildPreviewPlayerInput = (
    actionDescription: string,
    speechDescription: string,
    actionCheckResult?: ActionCheckResult | null,
  ): string => {
    const lines: string[] = [];
    if (actionDescription.trim()) lines.push(`动作描述: ${actionDescription.trim()}`);
    if (speechDescription.trim()) lines.push(`语言描述: ${speechDescription.trim()}`);
    if (actionCheckResult) {
      const criticalLabel =
        actionCheckResult.critical === 'critical_success'
          ? '（大成功）'
          : actionCheckResult.critical === 'critical_failure'
            ? '（大失败）'
            : '';
      lines.push(`检定结果: ${actionCheckResult.success ? '成功' : '失败'}${criticalLabel}`);
    }
    return lines.join('\n');
  };
  const shouldLeaveNpcChatByIntent = (actionDescription: string, speechDescription: string): boolean =>
    /(离开|转身|告辞|先走|退开|退出|回到主聊天)/.test(`${actionDescription}\n${speechDescription}`.trim());
  const clearPlayerInput = () => {
    setActionInput('');
    setSpeechInput('');
  };
  const closeTeammateChatModal = () => {
    if (activeTeammateChat) {
      clearNpcLiveProgress(activeTeammateChat.npcId);
    }
    setActiveTeammateChat(null);
    setTeammateChatActionInput('');
    setTeammateChatSpeechInput('');
    setTeammateChatLastActionInput('');
    setTeammateChatLastSpeechInput('');
  };
  const prefillPlayerActionWithAbility = (name: string) => {
    if (chatMode === 'npc') {
      forceReturnToMainChat('manual');
    }
    setActionInput((prev) => (prev.trim() ? `${prev}\n使用${name}` : `使用${name}`));
    setPlayerQuickActionOpen(false);
    setPlayerQuickActionMode('root');
    focusMainActionInput();
  };
  const resetActionCheckRollState = () => {
    setActionCheckRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetPublicTurnActionRollState = () => {
    setPublicTurnActionRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetPublicTurnInteractionState = () => {
    setPendingInteractionState(null);
    setPublicTurnInteractionActionInput('');
    setPublicTurnInteractionSpeechInput('');
    setPublicTurnInteractionBusy(false);
    setPublicTurnInteractionError('');
  };
  const resetPublicTurnAttackState = () => {
    setPendingAttackState(null);
    setPublicTurnAttackActionInput('');
    setPublicTurnAttackSpeechInput('');
    setPublicTurnAttackBusy(false);
    setPublicTurnAttackError('');
  };
  const resetPublicTurnAttackDefenseState = () => {
    setPendingAttackDefenseState(null);
    setPublicTurnAttackDefenseRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetPublicTurnDeathSaveRollState = () => {
    setPublicTurnDeathSaveRollState(DEFAULT_PUBLIC_TURN_DEATH_SAVE_ROLL_STATE);
    setPublicTurnDeathSaveSummary('');
  };
  const clearPendingDeathSaveState = () => {
    setPendingDeathSaveState(null);
    pendingDeathSaveResponseRef.current = null;
    resetPublicTurnDeathSaveRollState();
  };
  const resetPublicTurnOpposedState = () => {
    setPendingOpposedState(null);
    setPublicTurnOpposedPlan(null);
    setPublicTurnOpposedActionInput('');
    setPublicTurnOpposedSpeechInput('');
    setPublicTurnOpposedRollState(DEFAULT_PUBLIC_TURN_OPPOSED_ROLL_STATE);
  };
  const resetReactionCheckRollState = () => {
    setReactionCheckRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetBattleRollState = () => {
    setBattleRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetPendingTurnWorkflowState = () => {
    pendingPublicTurnActionRef.current = null;
    publicTurnActionResponseRef.current = null;
    pendingDeathSaveResponseRef.current = null;
    pendingReactionResponseRef.current = null;
    pendingOpposedResponseRef.current = null;
    resetPublicTurnActionRollState();
    resetPublicTurnInteractionState();
    resetPublicTurnAttackState();
    resetPublicTurnAttackDefenseState();
    clearPendingDeathSaveState();
    resetPublicTurnOpposedState();
    setPendingReactionState(null);
    resetReactionCheckRollState();
    clearLiveProgress();
    abortRef.current = null;
    activeStreamRef.current = null;
    restoreBlockingModal();
    setChatState('idle');
  };
  const restoreBlockingModal = () => {
    setMinimizedBlockingModal(null);
  };
  const buildReactionPlan = (reaction: PlayerReactionCheck): ActionCheckPlan => ({
    ok: true,
    session_id: sessionId,
    actor_role_id: playerStatic.player_id,
    actor_name: playerStatic.name,
    actor_kind: 'player',
    action_type: 'check',
    check_mode: 'reaction_save',
    requires_check: true,
    ability_used: reaction.ability_used,
    ability_modifier: playerStatic.dnd5e_sheet.current_ability_modifiers[reaction.ability_used],
    dc: reaction.dc,
    time_spent_min: 1,
    check_task: reaction.check_task,
    source_label: reaction.source_label,
    threatened_consequence: reaction.threatened_consequence,
  });
  const buildPublicTurnPlayerActionCheck = (
    plan: ActionCheckPlan,
    forcedDiceRoll: number | null,
  ): PublicTurnPlayerActionCheck => ({
    action_type: plan.action_type,
    source_context: plan.source_context ?? 'public_turn',
    resolution_rule: plan.resolution_rule ?? 'static_dc',
    planned_requires_check: plan.requires_check,
    planned_ability_used: plan.ability_used,
    planned_dc: plan.dc,
    planned_time_spent_min: plan.time_spent_min,
    planned_check_task: plan.check_task,
    forced_dice_roll: forcedDiceRoll,
    target_role_id: plan.target_role_id ?? null,
    target_name: plan.target_name ?? null,
    target_actor_kind: plan.target_actor_kind ?? null,
    target_ability_used: plan.target_ability_used ?? null,
    target_ability_modifier: plan.target_ability_modifier ?? null,
  });
  const buildReactionCheckResult = (reaction: PlayerReactionCheck, forcedRoll: number): ActionCheckResult => {
    const abilityModifier = playerStatic.dnd5e_sheet.current_ability_modifiers[reaction.ability_used];
    const totalScore = forcedRoll + abilityModifier;
    const critical =
      forcedRoll === 20 ? 'critical_success' : forcedRoll === 1 ? 'critical_failure' : 'none';
    const success = critical === 'critical_success' || (critical !== 'critical_failure' && totalScore >= reaction.dc);
    return {
      ok: true,
      session_id: sessionId,
      actor_role_id: playerStatic.player_id,
      actor_name: playerStatic.name,
      actor_kind: 'player',
      action_type: 'check',
      check_mode: 'reaction_save',
      requires_check: true,
      ability_used: reaction.ability_used,
      ability_modifier: abilityModifier,
      dc: reaction.dc,
      check_task: reaction.check_task,
      dice_roll: forcedRoll,
      total_score: totalScore,
      success,
      critical,
      time_spent_min: 1,
      narrative: reaction.trigger_summary,
      applied_effects: [],
      relation_tag_suggestion: null,
      source_label: reaction.source_label,
      threatened_consequence: reaction.threatened_consequence,
    };
  };
  const findLatestPublicTurnOpposedSettlement = (
    presentation: PublicTurnPresentation | null | undefined,
    prompt: PublicTurnOpposedPrompt,
  ): PublicTurnSettlementEntry | null => {
    const entries = presentation?.settlement_entries ?? [];
    for (let index = entries.length - 1; index >= 0; index -= 1) {
      const entry = entries[index];
      if ((entry.check?.resolution_rule ?? 'static_dc') !== 'opposed_actor') continue;
      if (entry.actor_id !== prompt.source_actor_id) continue;
      const targetName = entry.opposed_target_name ?? entry.check?.target_name ?? null;
      if (targetName && targetName !== prompt.target_actor_name) continue;
      return entry;
    }
    return null;
  };
  const buildPublicTurnOpposedResult = (
    prompt: PublicTurnOpposedPrompt,
    plan: PublicTurnOpposedPlanResponse,
    presentation: PublicTurnPresentation | null | undefined,
  ): ActionCheckResult | null => {
    const settlement = findLatestPublicTurnOpposedSettlement(presentation, prompt);
    const check = settlement?.check;
    if (!settlement || !check) return null;
    const playerRoll = check.target_dice_roll ?? null;
    const playerModifier = check.target_ability_modifier ?? plan.target_ability_modifier;
    const playerTotal = check.target_total_score ?? null;
    const opponentRoll = check.dice_roll ?? null;
    const opponentModifier = check.ability_modifier ?? plan.source_ability_modifier;
    const opponentTotal = check.total_score ?? null;
    const critical =
      playerRoll === 20 ? 'critical_success' : playerRoll === 1 ? 'critical_failure' : 'none';
    const success = !check.success;
    return {
      ok: true,
      session_id: sessionId,
      actor_role_id: prompt.target_actor_id,
      actor_name: prompt.target_actor_name,
      actor_kind: 'player',
      action_type: 'check',
      check_mode: 'action',
      source_context: 'public_turn',
      resolution_rule: 'opposed_actor',
      requires_check: true,
      ability_used: check.target_ability_used ?? plan.target_ability_used,
      ability_modifier: playerModifier,
      dc: Math.max(5, Math.min(30, 10 + opponentModifier)),
      check_task: plan.check_task,
      target_role_id: prompt.source_actor_id,
      target_name: prompt.source_actor_name,
      target_actor_kind: 'npc',
      target_ability_used: check.ability_used ?? plan.source_ability_used,
      target_ability_modifier: opponentModifier,
      dice_roll: playerRoll,
      total_score: playerTotal,
      target_dice_roll: opponentRoll,
      target_total_score: opponentTotal,
      contested_success: success,
      success,
      critical,
      time_spent_min: 1,
      narrative: settlement.gm_resolution_summary || check.outcome_text || check.comparison_text,
      applied_effects: [],
      relation_tag_suggestion: null,
    };
  };
  const normalizePublicTurnOpposedResult = (
    prompt: PublicTurnOpposedPrompt,
    plan: PublicTurnOpposedPlanResponse,
    result: ActionCheckResult | null | undefined,
  ): ActionCheckResult | null => {
    if (!result) return null;
    if (result.actor_role_id === prompt.target_actor_id) {
      return result;
    }
    const playerRoll = result.target_dice_roll ?? null;
    const playerModifier = result.target_ability_modifier ?? plan.target_ability_modifier;
    const playerTotal = result.target_total_score ?? null;
    const opponentRoll = result.dice_roll ?? null;
    const opponentModifier = result.ability_modifier ?? plan.source_ability_modifier;
    const opponentTotal = result.total_score ?? null;
    const success = !result.success;
    const critical =
      playerRoll === 20 ? 'critical_success' : playerRoll === 1 ? 'critical_failure' : 'none';
    return {
      ...result,
      actor_role_id: prompt.target_actor_id,
      actor_name: prompt.target_actor_name,
      actor_kind: 'player',
      ability_used: result.target_ability_used ?? plan.target_ability_used,
      ability_modifier: playerModifier,
      dc: Math.max(5, Math.min(30, 10 + opponentModifier)),
      target_role_id: prompt.source_actor_id,
      target_name: prompt.source_actor_name,
      target_actor_kind: 'npc',
      target_ability_used: result.ability_used ?? plan.source_ability_used,
      target_ability_modifier: opponentModifier,
      dice_roll: playerRoll,
      total_score: playerTotal,
      target_dice_roll: opponentRoll,
      target_total_score: opponentTotal,
      contested_success: success,
      success,
      critical,
    };
  };
  const resolvePublicTurnOpposedResult = (
    prompt: PublicTurnOpposedPrompt,
    plan: PublicTurnOpposedPlanResponse,
    presentation: PublicTurnPresentation | null | undefined,
    result: ActionCheckResult | null | undefined = null,
  ): ActionCheckResult | null =>
    buildPublicTurnOpposedResult(prompt, plan, presentation) ??
    normalizePublicTurnOpposedResult(prompt, plan, result);
  const buildBattleRollPlan = (prompt: BattleRollPrompt): ActionCheckPlan => ({
    ok: true,
    session_id: sessionId,
    actor_role_id: prompt.actor_combatant_id,
    actor_name: prompt.actor_name,
    actor_kind: 'player',
    action_type: prompt.roll_kind === 'attack' ? 'attack' : prompt.roll_kind === 'item_use' ? 'item_use' : 'check',
    check_mode: prompt.roll_kind === 'reaction' ? 'reaction_save' : 'action',
    requires_check: true,
    ability_used: prompt.ability_used,
    ability_modifier: prompt.ability_modifier,
    dc: prompt.dc,
    time_spent_min: 1,
    check_task: prompt.check_task,
    source_label: prompt.source_label ?? null,
    threatened_consequence: prompt.threatened_consequence ?? null,
  });
  const buildBattleRollResult = (prompt: BattleRollPrompt, result: BattleRollResolution): ActionCheckResult => ({
    ok: true,
    session_id: sessionId,
    actor_role_id: result.actor_combatant_id,
    actor_name: result.actor_name,
    actor_kind: 'player',
    action_type: result.roll_kind === 'attack' ? 'attack' : result.roll_kind === 'item_use' ? 'item_use' : 'check',
    check_mode: result.roll_kind === 'reaction' ? 'reaction_save' : 'action',
    requires_check: true,
    ability_used: result.ability_used,
    ability_modifier: result.ability_modifier,
    dc: result.dc,
    check_task: prompt.check_task,
    dice_roll: result.dice_roll,
    total_score: result.total_score,
    success: result.success,
    critical: result.critical,
    time_spent_min: 1,
    narrative: result.summary,
    applied_effects: [],
    relation_tag_suggestion: null,
    source_label: prompt.source_label ?? null,
    threatened_consequence: prompt.threatened_consequence ?? null,
  });
  const openBattleRollModal = (battle: BattleSandboxState) => {
    if (!battle.pending_roll) return;
    setBattleRollState({
      ...DEFAULT_ACTION_CHECK_ROLL_STATE,
      open: true,
      plan: buildBattleRollPlan(battle.pending_roll),
    });
  };
  const openPendingInteraction = (prompt: PublicTurnInteractionPrompt) => {
    setPendingInteractionState({ prompt });
    setPublicTurnInteractionActionInput('');
    setPublicTurnInteractionSpeechInput('');
    setPublicTurnInteractionBusy(false);
    setPublicTurnInteractionError('');
    setChatState('awaiting_interaction');
  };
  const openPendingAttackResponse = (prompt: PublicTurnAttackPrompt, prefill?: { action?: string; speech?: string }) => {
    setPendingAttackState({ prompt });
    setPublicTurnAttackActionInput(prefill?.action ?? '');
    setPublicTurnAttackSpeechInput(prefill?.speech ?? '');
    setPublicTurnAttackBusy(false);
    setPublicTurnAttackError('');
    setChatState('awaiting_attack_response');
  };
  const openPendingAttackDefense = (prompt: PublicTurnAttackDefensePrompt) => {
    setPendingAttackDefenseState({ prompt });
    setPublicTurnAttackDefenseRollState({
      ...DEFAULT_ACTION_CHECK_ROLL_STATE,
      open: true,
    });
    setChatState('awaiting_attack_defense');
  };
  const openPendingDeathSave = (prompt: DeathSavePrompt) => {
    pendingDeathSaveResponseRef.current = null;
    setPendingDeathSaveState({ prompt });
    setPublicTurnDeathSaveRollState({
      ...DEFAULT_PUBLIC_TURN_DEATH_SAVE_ROLL_STATE,
      open: true,
    });
    setPublicTurnDeathSaveSummary('');
    setChatState('awaiting_death_save');
  };
  const openPendingReaction = (response: PendingTurnContinueResponse) => {
    if (!response.pending_turn_id || !response.pending_reaction) return;
    pendingReactionResponseRef.current = null;
    setPendingReactionState({
      pending_turn_id: response.pending_turn_id,
      flow_kind: response.flow_kind,
      npc_role_id: response.npc_role_id ?? null,
      pending_reaction: response.pending_reaction,
    });
    setReactionCheckRollState({
      ...DEFAULT_ACTION_CHECK_ROLL_STATE,
      open: true,
      plan: buildReactionPlan(response.pending_reaction),
    });
    setChatState('awaiting_reaction');
  };

  const planPublicTurnOpposedForPrompt = async (
    prompt: PublicTurnOpposedPrompt,
    targetActionSummary: string,
    targetSpeechText: string,
  ) => {
    const cleanAction = targetActionSummary.trim();
    const cleanSpeech = targetSpeechText.trim();
    if (!cleanAction && !cleanSpeech) {
      setPublicTurnOpposedRollState((current) => ({
        ...current,
        phase: 'error',
        errorMessage: '至少需要输入回应行为或语言。',
      }));
      return;
    }
    setError('');
    setPublicTurnOpposedPlan(null);
    setPublicTurnOpposedRollState((current) => ({
      ...current,
      phase: 'resolving',
      result: null,
      errorMessage: '',
    }));
    try {
      const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
      const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
      const plan = await planPublicTurnOpposedCheck(
        {
          session_id: sessionId,
          round_id: prompt.round_id,
          check_id: prompt.check_id,
          source_actor_id: prompt.source_actor_id,
          target_actor_id: prompt.target_actor_id,
          source_action_summary: prompt.source_action_summary,
          source_speech_text: prompt.source_speech_text,
          target_action_summary: cleanAction,
          target_speech_text: cleanSpeech,
          config: effectiveConfig,
        },
        report,
      );
      setPublicTurnOpposedPlan(plan);
      setPublicTurnOpposedRollState((current) => ({
        ...current,
        phase: 'ready',
        errorMessage: '',
      }));
    } catch (e) {
      const message = e instanceof Error ? e.message : '对抗规划失败';
      setPublicTurnOpposedRollState((current) => ({
        ...current,
        phase: 'error',
        errorMessage: message,
      }));
    }
  };

  const openPendingOpposed = (
    response: PendingTurnContinueResponse,
    prefill?: { action?: string; speech?: string },
  ) => {
    if (!response.pending_turn_id || !response.public_opposed_prompt) return;
    pendingOpposedResponseRef.current = null;
    setPendingOpposedState({
      pending_turn_id: response.pending_turn_id,
      flow_kind: response.flow_kind,
      prompt: response.public_opposed_prompt,
      npc_role_id: response.npc_role_id ?? null,
    });
    setPublicTurnOpposedPlan(null);
    setPublicTurnOpposedActionInput(prefill?.action ?? '');
    setPublicTurnOpposedSpeechInput(prefill?.speech ?? '');
    setPublicTurnOpposedRollState({
      ...DEFAULT_PUBLIC_TURN_OPPOSED_ROLL_STATE,
      open: true,
    });
    setChatState('awaiting_opposed');
    if ((prefill?.action ?? '').trim() || (prefill?.speech ?? '').trim()) {
      void planPublicTurnOpposedForPrompt(response.public_opposed_prompt, prefill?.action ?? '', prefill?.speech ?? '');
    }
  };
  const openDirectPublicTurnOpposedPrompt = (
    prompt: PublicTurnOpposedPrompt,
    prefill?: { action?: string; speech?: string },
  ) => {
    setPendingOpposedState({
      pending_turn_id: prompt.round_id,
      flow_kind: 'public_turn',
      prompt,
      npc_role_id: null,
    });
    setPublicTurnOpposedPlan(null);
    setPublicTurnOpposedActionInput(prefill?.action ?? '');
    setPublicTurnOpposedSpeechInput(prefill?.speech ?? '');
    setPublicTurnOpposedRollState({
      ...DEFAULT_PUBLIC_TURN_OPPOSED_ROLL_STATE,
      open: true,
    });
    setChatState('awaiting_opposed');
    if ((prefill?.action ?? '').trim() || (prefill?.speech ?? '').trim()) {
      void planPublicTurnOpposedForPrompt(prompt, prefill?.action ?? '', prefill?.speech ?? '');
    }
  };

  useEffect(() => {
    setPublicTurnImpacts([]);
  }, [currentSubZone?.sub_zone_id]);

  useEffect(() => {
    if (
      !sessionId ||
      pendingInteractionState ||
      pendingAttackState ||
      pendingAttackDefenseState ||
      pendingDeathSaveState ||
      pendingReactionState ||
      pendingOpposedState ||
      actionCheckRollState.open ||
      publicTurnActionRollState.open ||
      publicTurnAttackDefenseRollState.open ||
      publicTurnDeathSaveRollState.open ||
      publicTurnOpposedRollState.open ||
      reactionCheckRollState.open
    ) {
      return;
    }
    void (async () => {
      try {
        const pending = await getCurrentPendingTurn(sessionId);
        if (
          !pending ||
          (
            pending.status !== 'awaiting_reaction' &&
            pending.status !== 'awaiting_opposed' &&
            pending.status !== 'awaiting_player_attack_response' &&
            pending.status !== 'awaiting_player_attack_defense' &&
            pending.status !== 'awaiting_player_death_save' &&
            pending.status !== 'awaiting_protocol_repair'
          )
        ) {
          return;
        }
        if (pending.flow_kind === 'main_chat') {
          const restoredStatus: MainOutputStatus =
            pending.status === 'awaiting_player_attack_response'
              ? 'awaiting_attack_response'
              : pending.status === 'awaiting_player_attack_defense'
                ? 'awaiting_attack_defense'
                : pending.status === 'awaiting_player_death_save'
                  ? 'awaiting_death_save'
                : pending.status === 'awaiting_opposed'
                  ? 'awaiting_opposed'
                  : pending.status === 'awaiting_protocol_repair'
                    ? 'awaiting_protocol_repair'
                    : 'awaiting_reaction';
          setCurrentMainOutput({
            source_kind: 'main_turn',
            reply_text: pending.reply_text,
            scene_events: pending.scene_events,
            archived_sub_zone_turn_id: pending.archived_sub_zone_turn_id ?? null,
            main_turn_summary: pending.main_turn_summary ?? null,
            public_turn_state: null,
            public_turn_presentation: null,
            status: restoredStatus,
          });
          setShowFoldedMainSceneEvents(false);
        } else if (pending.flow_kind === 'public_turn') {
          handlePublicTurnPendingResponse(pending);
          return;
        } else if (pending.flow_kind === 'npc_chat') {
          applyPendingNpcTurnState(pending);
        }
        if (pending.status === 'awaiting_player_attack_defense' && pending.public_attack_defense_prompt) {
          openPendingAttackDefense(pending.public_attack_defense_prompt);
          return;
        }
        if (pending.status === 'awaiting_player_death_save' && pending.death_save_prompt) {
          openPendingDeathSave(pending.death_save_prompt);
          return;
        }
        if (pending.status === 'awaiting_player_attack_response' && pending.public_attack_prompt) {
          openPendingAttackResponse(pending.public_attack_prompt);
          return;
        }
        if (pending.status === 'awaiting_opposed') {
          openPendingOpposed(pending);
          return;
        }
        if (pending.pending_reaction) {
          openPendingReaction(pending);
        }
      } catch {
        // Ignore restore failures to avoid blocking the app boot flow.
      }
    })();
  }, [
    sessionId,
    pendingInteractionState,
    pendingAttackState,
    pendingAttackDefenseState,
    pendingDeathSaveState,
    pendingReactionState,
    pendingOpposedState,
    actionCheckRollState.open,
    publicTurnActionRollState.open,
    publicTurnAttackDefenseRollState.open,
    publicTurnDeathSaveRollState.open,
    publicTurnOpposedRollState.open,
    reactionCheckRollState.open,
  ]);

  useEffect(() => {
    const prompt = publicTurnState.current_round?.pending_interaction_prompt ?? null;
    if (!prompt) return;
    if (pendingInteractionState?.prompt.prompt_id === prompt.prompt_id) return;
    if (publicTurnState.current_round?.phase !== 'awaiting_player_interaction') return;
    openPendingInteraction(prompt);
  }, [publicTurnState, pendingInteractionState]);

  useEffect(() => {
    const prompt = publicTurnState.current_round?.pending_attack_prompt ?? null;
    if (!prompt) return;
    if (pendingAttackState?.prompt.prompt_id === prompt.prompt_id) return;
    if (publicTurnState.current_round?.phase !== 'awaiting_player_attack_response') return;
    openPendingAttackResponse(prompt);
  }, [publicTurnState, pendingAttackState]);

  useEffect(() => {
    const prompt = publicTurnState.current_round?.pending_attack_defense_prompt ?? null;
    if (!prompt) return;
    if (pendingAttackDefenseState?.prompt.check_id === prompt.check_id) return;
    if (publicTurnState.current_round?.phase !== 'awaiting_player_attack_defense') return;
    openPendingAttackDefense(prompt);
  }, [publicTurnState, pendingAttackDefenseState]);

  useEffect(() => {
    const prompt = publicTurnState.current_round?.pending_death_save_prompt ?? null;
    if (!prompt) return;
    if (pendingDeathSaveState?.prompt.prompt_id === prompt.prompt_id) return;
    if (publicTurnState.current_round?.phase !== 'awaiting_player_death_save') return;
    openPendingDeathSave(prompt);
  }, [publicTurnState, pendingDeathSaveState]);

  useEffect(() => {
    if (!sessionId || activeBattle || battleStartDialogOpen || battleRollState.open) return;
    void (async () => {
      try {
        const current = await getCurrentDebugBattle(sessionId, report);
        if (!current.battle) return;
        setActiveBattle(current.battle);
        if (current.battle.pending_roll) {
          openBattleRollModal(current.battle);
        }
      } catch {
        // Ignore restore failures.
      }
    })();
  }, [sessionId, activeBattle, battleStartDialogOpen, battleRollState.open]);

  useEffect(() => {
    if (!sessionId) return;
    void refreshTemplateLibraryStatus();
  }, [sessionId]);

  const refreshTokenUsage = async (sid: string = sessionId) => {
    try {
      const usage = await getTokenUsage(sid, report);
      setTokenUsage(usage);
    } catch {
      // Ignore token usage refresh failure.
    }
  };

  useEffect(() => {
    const zoneId = areaSnapshot?.current_zone_id ?? null;
    if (!zoneId) {
      setCurrentZoneMetric(null);
      return;
    }
    setCurrentZoneMetric(zoneMetricState.entries.find((item) => item.zone_id === zoneId) ?? null);
  }, [areaSnapshot, zoneMetricState]);

  const applyMapStateSync = (sync: MapStateSyncBundle, sid: string = sessionId) => {
    const effectiveSessionId = sync.player_runtime_data?.session_id || sid;
    setMapSnapshot(sync.map_snapshot ?? { zones: [], player_position: DEFAULT_POSITION });
    setAreaSnapshot(sync.area_snapshot ?? null);
    setCurrentReputation(sync.current_reputation ?? null);
    setCurrentZoneMetric(sync.current_zone_metric ?? null);
    setZoneMetricState(sync.zone_metric_state ?? { version: '0.1.0', entries: [], updated_at: '' });
    setQuestState(sync.quest_state ?? defaultQuestState);
    setEncounterState(sync.encounter_state ?? defaultEncounterState);
    setFateState(sync.fate_state ?? defaultFateState);
    setTeamState(sync.team_state ?? defaultTeamState);
    setNpcPoolItems(sync.role_pool ?? []);
    setNpcPoolTotal((sync.role_pool ?? []).length);
    setWorldState(sync.world_state ?? defaultWorldState);
    setPlayerStaticState(sync.player_static_data ?? defaultPlayerStaticData);
    setPlayerRuntimeState(
      sync.player_runtime_data ?? {
        session_id: effectiveSessionId,
        current_position: sync.map_snapshot?.player_position ?? DEFAULT_POSITION,
        updated_at: new Date().toISOString(),
      },
    );
    setMapRender({ session_id: effectiveSessionId, ...sync.render });
    setGameLogs(sync.game_logs ?? []);
  };

  const refreshQuestState = async (sid: string = sessionId) => {
    try {
      const state = await getQuestState(sid, report);
      setQuestState(state.quest_state ?? defaultQuestState);
    } catch {
      // Ignore quest refresh failures.
    }
  };

  const refreshEncounterState = async (sid: string = sessionId) => {
    try {
      const state = await getPendingEncounters(sid, report);
      setEncounterState(state.encounter_state ?? defaultEncounterState);
    } catch {
      // Ignore encounter refresh failures.
    }
  };

  const syncEncounterLaneAfterSceneEvents = async (events: SceneEvent[]) => {
    if (
      events.some((event) =>
        ['encounter_started', 'encounter_background', 'encounter_progress', 'encounter_resolution', 'encounter_situation_update', 'encounter_world_push'].includes(event.kind),
      )
    ) {
      await refreshEncounterState(sessionId);
    }
  };

  const refreshFateState = async (sid: string = sessionId) => {
    try {
      const state = await getFateState(sid, report);
      setFateState(state.fate_state ?? defaultFateState);
    } catch {
      // Ignore fate refresh failures.
    }
  };

  const refreshTeamState = async (sid: string = sessionId) => {
    try {
      const state = await getTeamState(sid, report);
      setTeamState(state.team_state ?? defaultTeamState);
    } catch {
      // Ignore team refresh failures.
    }
  };

  const refreshCharacterBuildState = async (
    sid: string = sessionId,
    options?: { openForcedModal?: boolean; suppressOffer?: boolean },
  ) => {
    try {
      const state = await getCharacterBuildState(sid, report);
      setCharacterBuildState(state);
      if (options?.openForcedModal) {
        setCharacterBuildOpen(state.forced_entry);
        if (state.forced_entry) {
          setCharacterBuildMode('player');
        }
      }
      if (!options?.suppressOffer) {
        setCompanionBuildOfferOpen(state.companion_offer_pending);
      }
      return state;
    } catch {
      setCharacterBuildState({
        session_id: sid,
        state: defaultCharacterBuildState,
        forced_entry: false,
        can_build_companion: false,
        companion_offer_pending: false,
        media_capabilities: {
          active_provider: null,
          supports_generation: false,
          supports_background_removal: false,
          supports_vision: false,
          requires_explicit_provider: false,
          detail: '',
        },
      });
      return null;
    }
  };

  const refreshConsistencyData = async (sid: string = sessionId) => {
    try {
      const [status, snapshot] = await Promise.all([getConsistencyStatus(sid, report), getStorySnapshot(sid, report)]);
      setWorldState(status.world_state ?? defaultWorldState);
      setConsistencyIssues(status.issues ?? []);
      setConsistencyIssueCount(status.issue_count ?? 0);
      setStorySnapshot(snapshot.snapshot ?? null);
    } catch {
      // Ignore consistency refresh failures.
    }
  };

  const refreshNarrativeState = async (sid: string = sessionId) => {
    await Promise.all([refreshQuestState(sid), refreshEncounterState(sid), refreshFateState(sid), refreshTeamState(sid)]);
  };

  const applySaveSnapshot = async (save: SaveFile, sid: string = sessionId) => {
    if (save.session_id !== sid) return;
    const snapshot = toMapSnapshot(save);
    setMapSnapshot(snapshot);
    setAreaSnapshot(save.area_snapshot ?? null);
    setCurrentReputation(selectCurrentReputation(save));
    setCurrentZoneMetric(selectCurrentZoneMetric(save));
    setZoneMetricState(save.zone_metric_state ?? { version: '0.1.0', entries: [], updated_at: '' });
    setQuestState(save.quest_state ?? defaultQuestState);
    setEncounterState(save.encounter_state ?? defaultEncounterState);
    setFateState(save.fate_state ?? defaultFateState);
    setTeamState(save.team_state ?? defaultTeamState);
    setNpcPoolItems(save.role_pool ?? []);
    setNpcPoolTotal((save.role_pool ?? []).length);
    setTeamChatReplies([]);
    setTeamChatBusy(false);
    setWorldState(save.world_state ?? defaultWorldState);
    setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
    setPlayerRuntimeState(
      save.player_runtime_data ?? {
        session_id: sid,
        current_position: save.map_snapshot?.player_position ?? DEFAULT_POSITION,
        updated_at: new Date().toISOString(),
      },
    );
    if (mapOpen) {
      const render = await renderWorldMap(
        {
          session_id: sid,
          zones: snapshot.zones,
          player_position: snapshot.player_position ?? DEFAULT_POSITION,
          zone_metric_state: save.zone_metric_state,
        },
        report,
      );
      setMapRender(render);
    }
  };

  const syncStateFromSave = async (sid: string = sessionId) => {
    try {
      const save = await getCurrentSave(report);
      await applySaveSnapshot(save, sid);
      try {
        const area = await getCurrentArea(sid, report);
        setAreaSnapshot(area.area_snapshot);
      } catch {
        // Ignore area refresh failures.
      }
      await refreshNarrativeState(sid);
      if (consistencyOpen) {
        await refreshConsistencyData(sid);
      }
    } catch {
      // Ignore save sync failures.
    }
  };

  useEffect(() => {
    if (authState !== 'authed') return;
    try {
      const cachedPrompt = window.localStorage.getItem(MAP_PROMPT_STORAGE_KEY) ?? '';
      if (cachedPrompt) {
        setMapPromptInput(cachedPrompt);
        setMapWorldPrompt(cachedPrompt);
      }
    } catch {
      // Ignore localStorage failures.
    }
  }, [authState]);

  const loadStoredConfig = async (pathStatus: PathStatus | null): Promise<'loaded' | 'missing' | 'error'> => {
    if (!pathStatus?.exists) {
      setHasStoredConfig(false);
      return 'missing';
    }
    try {
      const stored = normalizeConfig(await getStoredConfig(report));
      setConfig(stored);
      setConfigDraft(stored);
      setHasStoredConfig(true);
      return 'loaded';
    } catch {
      setHasStoredConfig(false);
      return 'error';
    }
  };

  useEffect(() => {
    if (authState !== 'authed') {
      setAccountConfigReady(false);
      setCharacterBuildState(null);
      setCharacterBuildOpen(false);
      setCompanionBuildOfferOpen(false);
      return;
    }
    let cancelled = false;
    setAccountConfigReady(false);
    void (async () => {
      const [cfgPathResult, svPathResult, saveResult] = await Promise.allSettled([
        getConfigPath(report),
        getSavePath(report),
        getCurrentSave(report),
      ]);

      if (cfgPathResult.status === 'fulfilled') {
        if (cancelled) return;
        setCfgPath(cfgPathResult.value);
        const loadResult = await loadStoredConfig(cfgPathResult.value);
        if (cancelled) return;
        if (loadResult !== 'loaded') {
          setConfig(normalizeConfig(defaultConfig));
          setConfigDraft(normalizeConfig(defaultConfig));
          setConfigModels([]);
          setConfigProfile(null);
          setManualModelMode(true);
          setConfigReturnView('boot');
          setConfigHint('当前账号还没有配置，请先新建并保存。');
          setView('config');
        }
      } else {
        if (cancelled) return;
        setHasStoredConfig(false);
      }

      if (svPathResult.status === 'fulfilled') {
        if (cancelled) return;
        setSvPath(svPathResult.value);
      }

      if (saveResult.status !== 'fulfilled') {
        if (!cancelled) setAccountConfigReady(true);
        return;
      }

      try {
        const save = saveResult.value;
        if (cancelled) return;
        setMapSnapshot(toMapSnapshot(save));
        setAreaSnapshot(save.area_snapshot ?? null);
        setCurrentReputation(selectCurrentReputation(save));
        setCurrentZoneMetric(selectCurrentZoneMetric(save));
        setZoneMetricState(save.zone_metric_state ?? { version: '0.1.0', entries: [], updated_at: '' });
        setQuestState(save.quest_state ?? defaultQuestState);
        setEncounterState(save.encounter_state ?? defaultEncounterState);
        setFateState(save.fate_state ?? defaultFateState);
        setTeamState(save.team_state ?? defaultTeamState);
        setNpcPoolItems(save.role_pool ?? []);
        setNpcPoolTotal((save.role_pool ?? []).length);
        setTeamChatReplies([]);
        setTeamChatBusy(false);
        setWorldState(save.world_state ?? defaultWorldState);
        setConsistencyIssues([]);
        setConsistencyIssueCount(0);
        setStorySnapshot(null);
        setCurrentMainOutput(null);
        const sid = save.session_id || `sess_${Date.now()}`;
        setSessionId(sid);
        setTokenUsage({ ...EMPTY_TOKEN_USAGE, session_id: sid });
        setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
        setPlayerRuntimeState(
          save.player_runtime_data ?? {
            session_id: sid,
            current_position: save.map_snapshot?.player_position ?? DEFAULT_POSITION,
            updated_at: new Date().toISOString(),
          },
        );

        const [remoteStatic, remoteRuntime, buildState] = await Promise.all([
          getPlayerStatic(sid, report),
          getPlayerRuntime(sid, report),
          getCharacterBuildState(sid, report),
        ]);
        if (cancelled) return;
        setPlayerStaticState(remoteStatic);
        setPlayerRuntimeState(remoteRuntime);
        setCharacterBuildState(buildState);
        setCharacterBuildOpen(buildState.forced_entry);
        setCharacterBuildMode((current) => (buildState.forced_entry ? 'player' : current));
        setCompanionBuildOfferOpen(buildState.companion_offer_pending);
        if (!(save.area_snapshot?.sub_zones?.length ?? 0)) {
          try {
            const area = await getCurrentArea(sid, report);
            if (cancelled) return;
            setAreaSnapshot(area.area_snapshot);
          } catch {
            // Ignore area load failures.
          }
        }
        const [questResponse, encounterResponse, fateResponse, usage] = await Promise.all([
          getQuestState(sid, report),
          getPendingEncounters(sid, report),
          getFateState(sid, report),
          getTokenUsage(sid, report),
        ]);
        if (cancelled) return;
        setQuestState(questResponse.quest_state ?? defaultQuestState);
        setEncounterState(encounterResponse.encounter_state ?? defaultEncounterState);
        setFateState(fateResponse.fate_state ?? defaultFateState);
        setTokenUsage(usage);
      } catch {
        // Ignore boot-time failures; user can continue with manual setup.
      } finally {
        if (!cancelled) setAccountConfigReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authState]);

  useEffect(() => {
    announcedEncounterIdsRef.current = new Set();
    autoRejoinEncounterIdRef.current = null;
  }, [sessionId]);

  const presentPendingEncounterEvent = useEffectEvent(async (encounterId: string) => {
    try {
      setEncounterModalBusy(true);
      forceReturnToMainChat('encounter_interrupt');
      await presentEncounter({ session_id: sessionId, encounter_id: encounterId }, report);
      const state = await getPendingEncounters(sessionId, report);
      setEncounterState(state.encounter_state ?? defaultEncounterState);
    } catch {
      // Ignore encounter present failures.
    } finally {
      setEncounterModalBusy(false);
    }
  });

  const autoRejoinEncounterEvent = useEffectEvent(async (encounter: EncounterEntry) => {
    try {
      setEncounterModalBusy(true);
      forceReturnToMainChat('encounter_interrupt');
      const response = await rejoinEncounter({ session_id: sessionId, encounter_id: encounter.encounter_id }, report);
      setEncounterState(response.encounter_state ?? defaultEncounterState);
      setMainAssistantOnly(response.reply);
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '自动重返遭遇失败');
    } finally {
      setEncounterModalBusy(false);
    }
  });

  useEffect(() => {
    if (pendingQuest || !pendingEncounter) return;
    const encounterId = pendingEncounter.encounter_id;
    if (pendingEncounter.status === 'active' || pendingEncounter.status === 'escaped') {
      if (announcedEncounterIdsRef.current.has(encounterId) || encounterModalEncounterId === encounterId) return;
      forceReturnToMainChatEvent('encounter_interrupt');
      setEncounterModalEncounterId(encounterId);
      return;
    }
    if (pendingEncounter.status !== 'queued') return;
    if (activeEncounter?.encounter_id) return;
    void presentPendingEncounterEvent(encounterId);
  }, [pendingQuest, pendingEncounter, activeEncounter?.encounter_id, encounterModalEncounterId]);

  useEffect(() => {
    if (!canRejoinActiveEncounter || !activeEncounter) {
      autoRejoinEncounterIdRef.current = null;
      return;
    }
    if (
      pendingQuest ||
      mapPromptDialogOpen ||
      aiWaiting ||
      actionCheckRollState.open ||
      publicTurnActionRollState.open ||
      encounterModalBusy ||
      encounterModalOpen
    ) {
      return;
    }
    if (autoRejoinEncounterIdRef.current === activeEncounter.encounter_id) return;
    autoRejoinEncounterIdRef.current = activeEncounter.encounter_id;
    void autoRejoinEncounterEvent(activeEncounter);
  }, [
    canRejoinActiveEncounter,
    activeEncounter,
    pendingQuest,
    mapPromptDialogOpen,
    aiWaiting,
    actionCheckRollState.open,
    publicTurnActionRollState.open,
    encounterModalBusy,
    encounterModalOpen,
  ]);

  const formatValidateErrors = (errors: Array<{ field: string; message: string }>) =>
    errors.map((e) => `${e.field}: ${e.message}`).join('; ');

  const onNewConfig = () => {
    setConfigReturnView('boot');
    setConfigDraft(normalizeConfig(hasStoredConfig ? config : defaultConfig));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onOpenConfigFromChat = () => {
    setConfigReturnView('chat');
    setConfigDraft(normalizeConfig(config));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onConfigProviderChange = (provider: AppConfig['provider']) => {
    setConfigDraft((prev) => selectProviderConfig(prev, provider));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
  };

  const onConfigApiKeyChange = (api_key: string) => {
    setConfigDraft((prev) => updateCurrentProviderConfig(prev, { api_key }));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
  };

  const onConfigBaseUrlChange = (base_url_override: string) => {
    setConfigDraft((prev) => updateCurrentProviderConfig(prev, { base_url_override }));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
  };

  const onConfigModelChange = (model: string) => {
    setConfigDraft((prev) => updateCurrentProviderConfig(prev, { model }));
    setError('');
    setConfigHint('');
  };

  const onConfigRuntimeChange = (key: keyof AppConfig['runtime'], rawValue: string) => {
    const value = rawValue.trim();
    setConfigDraft((prev) => {
      const runtime = {
        ...prev.runtime,
        [key]: value ? Number(value) : undefined,
      };
      return updateCurrentProviderConfig(prev, { runtime });
    });
  };

  const onFetchConfigModels = async () => {
    const apiKey = configDraft.api_key.trim();
    if (!apiKey) {
      setError('请先填写 API Key。');
      return;
    }
    setError('');
    setConfigHint('');
    setConfigModelsLoading(true);
    try {
      const result = await discoverConfigModels(
        {
          provider: configDraft.provider,
          api_key: apiKey,
          base_url_override: configDraft.base_url_override,
        },
        report,
      );
      setConfigModels(result.models);
      setManualModelMode(false);
      setConfigHint(`已加载 ${result.models.length} 个模型。`);
    } catch (e) {
      setConfigModels([]);
      setManualModelMode(true);
      setError(e instanceof Error ? e.message : '模型列表拉取失败');
      setConfigHint('模型列表拉取失败，已切换为手动输入模型名。');
    } finally {
      setConfigModelsLoading(false);
    }
  };

  const onValidateAndSaveConfig = async () => {
    setError('');
    setConfigHint('');
    try {
      const result = await validateConfig(configDraft, report);
      if (!result.valid) {
        setError(`配置校验失败: ${formatValidateErrors(result.errors)}`);
        return;
      }
      const normalized = normalizeConfig(result.normalized_config ?? configDraft);
      await saveConfig(normalized, report);
      const latestPath = await getConfigPath(report);
      setCfgPath(latestPath);
      setConfig(normalized);
      setConfigDraft(normalized);
      setHasStoredConfig(true);
      setView('chat');
      setChatState('idle');
      setConfigHint('配置已保存到当前账号目录。');
    } catch (e) {
      setError(e instanceof Error ? e.message : '配置保存失败');
    }
  };

  const runNarrativeChecks = async (triggerKind?: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced') => {
    await evaluateAllQuests({ session_id: sessionId, config }, report);
    await evaluateFate({ session_id: sessionId, config }, report);
    if (triggerKind) {
      await checkEncounters({ session_id: sessionId, trigger_kind: triggerKind, config }, report);
    }
    await refreshNarrativeState(sessionId);
    await refreshGameLogs(sessionId);
    await syncStateFromSave(sessionId);
  };

  const performActionCheckWithRoll = async (payload: ActionCheckPayload): Promise<ActionCheckResult | null> => {
    if (actionCheckPromiseRef.current) {
      throw new Error('已有检定进行中，请先完成当前投骰。');
    }
    const plan = await planActionCheck(
      {
        session_id: sessionId,
        action_type: payload.action_type,
        action_prompt: payload.action_prompt,
        actor_role_id: payload.actor_role_id,
        config,
      },
      report,
    );
    if (!plan.requires_check) {
      if (payload.skip_if_no_check) {
        return null;
      }
      return runActionCheck(
        {
          session_id: sessionId,
          action_type: plan.action_type,
          action_prompt: payload.action_prompt,
          actor_role_id: plan.actor_role_id,
          resolution_context: payload.resolution_context ?? 'standalone',
          planned_ability_used: plan.ability_used,
          planned_dc: plan.dc,
          planned_time_spent_min: plan.time_spent_min,
          planned_requires_check: plan.requires_check,
          planned_check_task: plan.check_task,
          return_state_sync: payload.return_state_sync,
          post_trigger_kind: payload.post_trigger_kind,
          config,
        },
        report,
      );
    }
    if (plan.actor_kind === 'npc') {
      return runActionCheck(
        {
          session_id: sessionId,
          action_type: plan.action_type,
          action_prompt: payload.action_prompt,
          actor_role_id: plan.actor_role_id,
          allow_backend_roll: true,
          resolution_context: payload.resolution_context ?? 'standalone',
          planned_ability_used: plan.ability_used,
          planned_dc: plan.dc,
          planned_time_spent_min: plan.time_spent_min,
          planned_requires_check: plan.requires_check,
          planned_check_task: plan.check_task,
          return_state_sync: payload.return_state_sync,
          post_trigger_kind: payload.post_trigger_kind,
          config,
        },
        report,
      );
    }
    pendingActionCheckRef.current = payload;
    setActionCheckRollState({
      ...DEFAULT_ACTION_CHECK_ROLL_STATE,
      open: true,
      plan,
    });
    return new Promise<ActionCheckResult | null>((resolve, reject) => {
      actionCheckPromiseRef.current = { resolve, reject };
    });
  };

  const onTriggerActionCheckRoll = () => {
    if (actionCheckRollState.phase !== 'ready') return;
    const payload = pendingActionCheckRef.current;
    const plan = actionCheckRollState.plan;
    if (!payload || !plan) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setActionCheckRollState({
      open: true,
      phase: 'rolling',
      plan,
      rollValue,
      result: null,
      errorMessage: '',
      rotation,
    });
    window.setTimeout(() => {
      void (async () => {
        setActionCheckRollState((current) => ({
          ...current,
          phase: 'resolving',
          rollValue,
        }));
        try {
          const result = await runActionCheck(
            {
              session_id: sessionId,
              action_type: plan.action_type,
              action_prompt: payload.action_prompt,
              actor_role_id: plan.actor_role_id,
              forced_dice_roll: rollValue,
              resolution_context: payload.resolution_context ?? 'standalone',
              planned_ability_used: plan.ability_used,
              planned_dc: plan.dc,
              planned_time_spent_min: plan.time_spent_min,
              planned_requires_check: plan.requires_check,
              planned_check_task: plan.check_task,
              return_state_sync: payload.return_state_sync,
              post_trigger_kind: payload.post_trigger_kind,
              config,
            },
            report,
          );
          setActionCheckRollState((current) => ({
            ...current,
            phase: 'resolved',
            rollValue: result.dice_roll ?? rollValue,
            result,
            errorMessage: '',
          }));
        } catch (e) {
          const message = e instanceof Error ? e.message : '行为检定失败';
          setActionCheckRollState((current) => ({
            ...current,
            phase: 'error',
            errorMessage: message,
          }));
        }
      })();
    }, 1650);
  };

  const onCloseActionCheckRoll = () => {
    const pending = actionCheckPromiseRef.current;
    const result = actionCheckRollState.result;
    const errorMessage = actionCheckRollState.errorMessage || '行为检定失败';
    actionCheckPromiseRef.current = null;
    pendingActionCheckRef.current = null;
    resetActionCheckRollState();
    if (!pending) return;
    if (result) {
      pending.resolve(result);
      return;
    }
    pending.reject(new Error(errorMessage));
  };

  const onTriggerReactionCheckRoll = () => {
    if (reactionCheckRollState.phase !== 'ready' || !pendingReactionState || !reactionCheckRollState.plan) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setReactionCheckRollState((current) => ({
      ...current,
      phase: 'rolling',
      rollValue,
      result: null,
      errorMessage: '',
      rotation,
    }));
    window.setTimeout(() => {
      void (async () => {
        setReactionCheckRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        try {
          const pending = pendingReactionState;
          if (!pending) {
            throw new Error('待续回合不存在');
          }
          if (pending.flow_kind === 'public_turn') {
            const synthesizedResult = buildReactionCheckResult(pending.pending_reaction, rollValue);
            if (config.stream) {
              const controller = new AbortController();
              abortRef.current = controller;
              let streamedReply = currentMainOutput?.reply_text ?? pending.pending_reaction.trigger_summary;
              let streamedSceneEvents = currentMainOutput?.scene_events ?? [];
              let streamedImpacts = [...publicTurnImpacts];
              let streamedTurnState = currentMainOutput?.public_turn_state ?? null;
              let streamedPresentation = currentMainOutput?.public_turn_presentation ?? null;
              let finalResponse: PendingTurnContinueResponse | PublicTurnResponse | null = null;
              let streamFailed = false;

              await streamResolvePublicTurnReaction(
                {
                  session_id: sessionId,
                  check_id: pending.pending_reaction.reaction_id,
                  forced_dice_roll: rollValue,
                  config,
                },
                {
                  onPhase: (event) => {
                    setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
                  },
                  onTurnState: (state) => {
                    streamedTurnState = state;
                    setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
                  },
                  onInitiativeOrder: (entries, meta) => {
                    streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                    setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                  },
                  onSettlementEntry: (entry) => {
                    streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                    setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                  },
                  onRoundNarrationDelta: (delta) => {
                    streamedReply = `${streamedReply}${delta}`;
                    streamedPresentation = withRoundNarration(streamedPresentation, delta);
                    setCurrentMainOutput((prev) =>
                      prev
                        ? {
                            ...prev,
                            reply_text: streamedReply,
                            public_turn_presentation: streamedPresentation,
                            status: 'streaming',
                          }
                        : prev,
                    );
                  },
                  onSceneEvent: (event) => {
                    streamedSceneEvents = [...streamedSceneEvents, event];
                    setCurrentMainOutput((prev) =>
                      prev
                        ? {
                            ...prev,
                            scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                          }
                        : prev,
                    );
                  },
                  onImpact: (impact) => {
                    streamedImpacts = [...streamedImpacts, impact];
                    setPublicTurnImpacts(streamedImpacts);
                  },
                  onInteractionRequired: (prompt) => {
                    finalResponse = {
                      ok: true,
                      session_id: sessionId,
                      phase: prompt.phase,
                      narration: streamedReply,
                      scene_events: streamedSceneEvents,
                      reaction_check: null,
                      public_interaction_prompt: prompt,
                      public_opposed_prompt: null,
                      round_completed: false,
                      awaiting_entry: false,
                      public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                      archived_sub_zone_turn_id: null,
                      impacts: streamedImpacts,
                      player_action_check_result: synthesizedResult,
                      presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                    };
                  },
                  onAttackResponseRequired: (payload) => {
                    finalResponse = buildPendingAttackResponseFromStream({
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      reply_so_far: payload.reply_so_far,
                      scene_events_so_far: payload.scene_events_so_far,
                      public_attack_prompt: payload.public_attack_prompt,
                      npc_role_id: payload.npc_role_id ?? null,
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    });
                  },
                  onAttackDefenseRequired: (payload) => {
                    finalResponse = buildPendingAttackDefenseFromStream({
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      reply_so_far: payload.reply_so_far,
                      scene_events_so_far: payload.scene_events_so_far,
                      public_attack_defense_prompt: payload.public_attack_defense_prompt,
                      npc_role_id: payload.npc_role_id ?? null,
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    });
                  },
                  onDeathSaveRequired: (payload) => {
                    finalResponse = buildPendingDeathSaveFromStream({
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      reply_so_far: payload.reply_so_far,
                      scene_events_so_far: payload.scene_events_so_far,
                      death_save_prompt: payload.death_save_prompt,
                      npc_role_id: payload.npc_role_id ?? null,
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    });
                  },
                  onReactionCheckRequired: (payload) => {
                    finalResponse = {
                      session_id: sessionId,
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      status: 'awaiting_reaction',
                      reply_text: payload.reply_so_far,
                      scene_events: payload.scene_events_so_far,
                      tool_events: [],
                      pending_reaction: payload.pending_reaction,
                      reaction_result: synthesizedResult,
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                      npc_role_id: payload.npc_role_id ?? null,
                    };
                  },
                  onOpposedCheckRequired: (payload) => {
                    finalResponse = {
                      session_id: sessionId,
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      status: 'awaiting_opposed',
                      reply_text: payload.reply_so_far,
                      scene_events: payload.scene_events_so_far,
                      tool_events: [],
                      pending_reaction: null,
                      public_opposed_prompt: payload.public_opposed_prompt,
                      reaction_result: synthesizedResult,
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                      npc_role_id: payload.npc_role_id ?? null,
                    };
                  },
                  onProtocolRepairRequired: (payload) => {
                    finalResponse = {
                      session_id: sessionId,
                      pending_turn_id: payload.pending_turn_id,
                      flow_kind: payload.flow_kind,
                      status: 'awaiting_protocol_repair',
                      reply_text: payload.reply_so_far,
                      scene_events: payload.scene_events_so_far,
                      tool_events: [],
                      public_turn_state: payload.public_turn_state ?? streamedTurnState,
                      public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                      npc_role_id: payload.npc_role_id ?? null,
                      public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                      public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                    };
                  },
                  onReactionCheckResumed: () => undefined,
                  onRoundCompleted: () => undefined,
                  onError: (message) => {
                    streamFailed = true;
                    setError(message);
                    setChatState('error');
                    abortRef.current = null;
                  },
                  onEnd: ({ archived_sub_zone_turn_id, public_turn_state, presentation }) => {
                    if (streamFailed) {
                      return;
                    }
                    finalResponse = {
                      session_id: sessionId,
                      pending_turn_id: null,
                      flow_kind: 'public_turn',
                      status: 'completed',
                      reply_text: streamedReply,
                      scene_events: streamedSceneEvents,
                      tool_events: [],
                      pending_reaction: null,
                      reaction_result: synthesizedResult,
                      public_turn_state: public_turn_state ?? streamedTurnState,
                      public_turn_presentation: presentation ?? streamedPresentation,
                      archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                      npc_role_id: null,
                    };
                  },
                },
                controller.signal,
                report,
              );

              abortRef.current = null;
              if (streamFailed) {
                return;
              }
            const resolvedResponse = finalResponse as PendingTurnContinueResponse | PublicTurnResponse | null;
            if (!resolvedResponse) {
              throw new Error('公开回合反应续行未返回结果');
            }
            pendingReactionResponseRef.current = resolvedResponse;
            setReactionCheckRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: synthesizedResult,
              errorMessage: '',
            }));
            if (isPendingTurnContinueResponse(resolvedResponse) && resolvedResponse.status === 'completed') {
              applyPublicTurnMainOutput({
                reply_text: resolvedResponse.reply_text,
                scene_events: resolvedResponse.scene_events,
                public_turn_state: resolvedResponse.public_turn_state ?? streamedTurnState,
                public_turn_presentation: resolvedResponse.public_turn_presentation ?? streamedPresentation,
                archived_sub_zone_turn_id: resolvedResponse.archived_sub_zone_turn_id ?? null,
                status: 'awaiting_archive',
              });
            }
              return;
            }

            const response = await resolvePublicTurnReaction(
              {
                session_id: sessionId,
                check_id: pending.pending_reaction.reaction_id,
                forced_dice_roll: rollValue,
                config,
              },
              report,
            );
            if (isPendingTurnContinueResponse(response)) {
              pendingReactionResponseRef.current = {
                ...response,
                reaction_result: synthesizedResult,
              };
            } else {
              pendingReactionResponseRef.current = {
                session_id: sessionId,
                pending_turn_id: null,
                flow_kind: 'public_turn',
                status: 'completed',
                reply_text: response.narration,
                scene_events: response.scene_events,
                tool_events: [],
                pending_reaction: null,
                reaction_result: synthesizedResult,
                public_turn_state: response.public_turn_state,
                public_turn_presentation: response.presentation,
                archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
                npc_role_id: null,
              };
              setPublicTurnImpacts(response.impacts ?? []);
            }
            setReactionCheckRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: synthesizedResult,
              errorMessage: '',
            }));
            if (isPublicTurnResponse(response)) {
              applyPublicTurnResponse(response, { status: response.round_completed ? 'awaiting_archive' : 'idle', mergeImpacts: true });
            }
            return;
          }
          if (config.stream && (pending.flow_kind === 'main_chat' || pending.flow_kind === 'npc_chat')) {
            const controller = new AbortController();
            abortRef.current = controller;
            let streamedReply =
              pending.flow_kind === 'main_chat'
                ? currentMainOutput?.reply_text ?? pending.pending_reaction.trigger_summary
                : pending.npc_role_id
                  ? npcChatMessages[pending.npc_role_id]?.[npcChatMessages[pending.npc_role_id].length - 1]?.content ?? pending.pending_reaction.trigger_summary
                  : pending.pending_reaction.trigger_summary;
            let streamedSceneEvents = pending.flow_kind === 'main_chat' ? currentMainOutput?.scene_events ?? [] : [];
            let finalResponse: PendingTurnContinueResponse | null = null;
            let resumedResult: ActionCheckResult | null = null;

            await continuePendingTurnStream(
              {
                session_id: sessionId,
                pending_turn_id: pending.pending_turn_id,
                forced_dice_roll: rollValue,
                config,
              },
              {
                onDelta: (delta) => {
                  streamedReply = `${streamedReply}${delta}`;
                  if (pending.flow_kind === 'main_chat') {
                    setCurrentMainOutput((prev) =>
                      prev
                        ? {
                            ...prev,
                            reply_text: streamedReply,
                            status: 'streaming',
                          }
                        : prev,
                    );
                  } else if (pending.flow_kind === 'npc_chat' && pending.npc_role_id) {
                    setNpcChatMessages((prev) => {
                      const current = [...(prev[pending.npc_role_id!] ?? [])];
                      if (current.length > 0 && current[current.length - 1]?.role === 'assistant') {
                        current[current.length - 1] = { ...current[current.length - 1], content: streamedReply };
                      }
                      return { ...prev, [pending.npc_role_id!]: current };
                    });
                  }
                },
                onReactionCheckResumed: ({ reaction_result }) => {
                  resumedResult = reaction_result;
                },
                onReactionCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_reaction',
                    reply_text: streamedReply,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: payload.pending_reaction,
                    reaction_result: resumedResult,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onSceneEvents: (events) => {
                  streamedSceneEvents = events;
                },
                onEnd: ({ archived_sub_zone_turn_id, main_turn_summary }) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: null,
                    flow_kind: pending.flow_kind,
                    status: 'completed',
                    reply_text: streamedReply,
                    scene_events: streamedSceneEvents,
                    tool_events: [],
                    main_turn_summary: main_turn_summary ?? null,
                    pending_reaction: null,
                    reaction_result: resumedResult,
                    archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                    npc_role_id: pending.npc_role_id ?? null,
                  };
                },
                onError: (message) => {
                  throw new Error(message);
                },
              },
              controller.signal,
              report,
            );

            abortRef.current = null;
            const resolvedResponse = finalResponse as PendingTurnContinueResponse | null;
            if (!resolvedResponse) {
              throw new Error('待续回合流式续行未返回结果');
            }
            pendingReactionResponseRef.current = resolvedResponse;
            setReactionCheckRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: resolvedResponse.reaction_result ?? null,
              errorMessage: '',
            }));
            if (resolvedResponse.flow_kind === 'main_chat') {
              setCurrentMainOutput({
                source_kind: 'main_turn',
                reply_text: resolvedResponse.reply_text,
                scene_events: resolvedResponse.scene_events,
                archived_sub_zone_turn_id: resolvedResponse.archived_sub_zone_turn_id ?? null,
                main_turn_summary: resolvedResponse.main_turn_summary ?? null,
                status: resolvedResponse.status === 'completed' ? 'awaiting_archive' : 'awaiting_reaction',
              });
            }
          } else {
            const response = await continuePendingTurn(
              {
                session_id: sessionId,
                pending_turn_id: pending.pending_turn_id,
                forced_dice_roll: rollValue,
                config,
              },
              report,
            );
            pendingReactionResponseRef.current = response;
            setReactionCheckRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: response.reaction_result ?? null,
              errorMessage: '',
            }));
            if (response.flow_kind === 'main_chat') {
              setCurrentMainOutput({
                source_kind: 'main_turn',
                reply_text: response.reply_text,
                scene_events: response.scene_events,
                archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
                main_turn_summary: response.main_turn_summary ?? null,
                status: response.status === 'completed' ? 'awaiting_archive' : 'awaiting_reaction',
              });
              setCurrentZoneMetric(response.current_zone_metric ?? null);
            } else if (response.flow_kind === 'npc_chat' && pending.npc_role_id) {
              setNpcChatMessages((prev) => {
                const current = [...(prev[pending.npc_role_id!] ?? [])];
                if (current.length > 0 && current[current.length - 1]?.role === 'assistant') {
                  current[current.length - 1] = { ...current[current.length - 1], content: response.reply_text };
                }
                return { ...prev, [pending.npc_role_id!]: current };
              });
            }
          }
        } catch (e) {
          const message = e instanceof Error ? e.message : '反应检定续行失败';
          setReactionCheckRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
          setChatState('error');
        }
      })();
    }, 1650);
  };

  const onCloseReactionCheckRoll = () => {
    const pending = pendingReactionState;
    const response = pendingReactionResponseRef.current;
    resetReactionCheckRollState();
    pendingReactionResponseRef.current = null;
    if (response) {
      setPendingReactionState(null);
      if (isPendingTurnContinueResponse(response)) {
        if (response.status !== 'completed') {
          if (response.flow_kind === 'public_turn') {
            handlePublicTurnPendingResponse(response);
          } else if (response.status === 'awaiting_reaction' && response.pending_reaction) {
            handlePendingReactionRequired(response);
          }
          return;
        }
        clearPlayerInput();
        abortRef.current = null;
        activeStreamRef.current = null;
        setChatState('idle');
        if (response.flow_kind === 'public_turn') {
          const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
          if (attackDefensePrompt) {
            openPendingAttackDefense(attackDefensePrompt);
            return;
          }
          const attackPrompt = findPendingPublicTurnAttackPrompt(response);
          if (attackPrompt) {
            openPendingAttackResponse(attackPrompt);
            return;
          }
          const prompt = findPendingPublicTurnInteractionPrompt(response);
          if (prompt) {
            openPendingInteraction(prompt);
            return;
          }
        }
        void (async () => {
          await refreshAreaSnapshot();
          await syncStateFromSave(sessionId);
        })();
        return;
      }
      abortRef.current = null;
      activeStreamRef.current = null;
      setChatState('idle');
      const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
      if (attackDefensePrompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(attackDefensePrompt);
        return;
      }
      const attackPrompt = findPendingPublicTurnAttackPrompt(response);
      if (attackPrompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(attackPrompt);
        return;
      }
      if (findPendingPublicTurnInteractionPrompt(response)) {
        handlePublicTurnInteractionRequired(response);
        return;
      }
      applyPublicTurnResponse(response, { status: response.round_completed ? 'awaiting_archive' : 'idle', mergeImpacts: true });
      void (async () => {
        await refreshAreaSnapshot();
        await syncStateFromSave(sessionId);
      })();
      return;
    }
    setPendingReactionState(null);
    if (!pending) {
      setChatState('idle');
      return;
    }
    void (async () => {
      try {
        await cancelPendingTurn({ session_id: sessionId, pending_turn_id: pending.pending_turn_id }, report);
      } catch {
        // Ignore cancel failures and still reset the local UI.
      }
      if (pending.flow_kind === 'main_chat') {
        setCurrentMainOutput(null);
      } else if (pending.flow_kind === 'npc_chat') {
        const active = activeStreamRef.current;
        if (active && active.kind === 'npc' && active.npcId === pending.npc_role_id) {
          setNpcChatMessages((prev) => ({ ...prev, [active.npcId]: active.previousMessages }));
        }
      }
      abortRef.current = null;
      activeStreamRef.current = null;
      setMainLiveProgress([]);
      setChatState('idle');
      window.alert('本轮已作废');
    })();
  };

  const publishActionCheckOutcome = async (
    result: ActionCheckResult,
    sourceContext: ActionCheckPayload['source_context'],
    postCloseOutput: ActionCheckPayload['post_close_output'],
  ): Promise<boolean> => {
    const sceneEvents = result.scene_events ?? [];
    const mirroredEvents =
      sourceContext === 'npc_chat'
        ? sceneEvents.filter(
            (event) =>
              event.kind === 'encounter_started' ||
              event.kind === 'encounter_background' ||
              event.kind === 'encounter_progress' ||
              event.kind === 'encounter_resolution' ||
              event.kind === 'encounter_situation_update',
          )
        : sceneEvents;
    const encounterStarted = mirroredEvents.some((event) => event.kind === 'encounter_started');
    if (encounterStarted && sourceContext === 'npc_chat') {
      forceReturnToMainChat('encounter_interrupt');
    }
    if (postCloseOutput === 'main_chat') {
      setMainOutput('system_output', result.narrative, mirroredEvents);
    } else if (mirroredEvents.length > 0) {
      setMainOutput('system_output', '', mirroredEvents);
    }
    if (result.state_sync) {
      applyMapStateSync(result.state_sync, result.session_id);
    } else {
      await syncEncounterLaneAfterSceneEvents(mirroredEvents);
    }
    return encounterStarted;
  };

  const applyPendingMainTurnState = (response: PendingTurnContinueResponse) => {
    setCurrentMainOutput({
      source_kind: 'main_turn',
      reply_text: response.reply_text,
      scene_events: response.scene_events,
      archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
      main_turn_summary: response.main_turn_summary ?? null,
      public_turn_state: null,
      public_turn_presentation: null,
      status: 'awaiting_reaction',
    });
    setMainLiveProgress([]);
    if (response.current_zone_metric) {
      setCurrentZoneMetric(response.current_zone_metric);
    }
  };

  const applyPublicTurnMainOutput = (payload: {
    reply_text: string;
    scene_events: SceneEvent[];
    public_turn_state?: PublicTurnState | null;
    public_turn_presentation?: PublicTurnPresentation | null;
    archived_sub_zone_turn_id?: string | null;
    status: MainOutputStatus;
  }) => {
    setCurrentMainOutput({
      source_kind: 'main_turn',
      reply_text: payload.reply_text,
      scene_events: payload.scene_events,
      archived_sub_zone_turn_id: payload.archived_sub_zone_turn_id ?? null,
      main_turn_summary: null,
      public_turn_state: payload.public_turn_state ?? null,
      public_turn_presentation: payload.public_turn_presentation ?? null,
      status: payload.status,
    });
  };

  const applyPublicTurnResponse = (
    response: PublicTurnResponse,
    options?: { status?: MainOutputStatus; mergeImpacts?: boolean },
  ) => {
    setPublicTurnImpacts((prev) => (options?.mergeImpacts ? [...prev, ...(response.impacts ?? [])] : response.impacts ?? []));
    applyPublicTurnMainOutput({
      reply_text: response.narration,
      scene_events: response.scene_events,
      public_turn_state: response.public_turn_state,
      public_turn_presentation: response.presentation,
      archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
      status:
        options?.status ??
        (response.public_attack_defense_prompt
          ? 'awaiting_attack_defense'
          : response.public_attack_prompt
            ? 'awaiting_attack_response'
            : response.death_save_prompt
              ? 'awaiting_death_save'
            : response.public_interaction_prompt
              ? 'awaiting_interaction'
              : response.round_completed
              ? 'awaiting_archive'
              : 'idle'),
    });
    setMainLiveProgress([]);
  };

  const applyPendingPublicTurnState = (response: PendingTurnContinueResponse) => {
    applyPublicTurnMainOutput({
      reply_text: response.reply_text,
      scene_events: response.scene_events,
      public_turn_state: response.public_turn_state ?? null,
      public_turn_presentation: response.public_turn_presentation ?? null,
      archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
      status:
        response.status === 'awaiting_player_attack_response'
          ? 'awaiting_attack_response'
          : response.status === 'awaiting_player_attack_defense'
            ? 'awaiting_attack_defense'
            : response.status === 'awaiting_player_death_save'
              ? 'awaiting_death_save'
            : response.status === 'awaiting_opposed'
              ? 'awaiting_opposed'
              : response.status === 'awaiting_protocol_repair'
              ? 'awaiting_protocol_repair'
              : 'awaiting_reaction',
    });
    setMainLiveProgress([]);
  };

  const buildPendingAttackResponseFromStream = (payload: {
    pending_turn_id: string;
    flow_kind: PendingTurnContinueResponse['flow_kind'];
    reply_so_far: string;
    scene_events_so_far: SceneEvent[];
    public_attack_prompt: PublicTurnAttackPrompt | null;
    npc_role_id?: string | null;
    public_turn_state?: PublicTurnState | null;
    public_turn_presentation?: PublicTurnPresentation | null;
  }): PendingTurnContinueResponse => ({
    session_id: sessionId,
    pending_turn_id: payload.pending_turn_id,
    flow_kind: payload.flow_kind,
    status: 'awaiting_player_attack_response',
    reply_text: payload.reply_so_far,
    scene_events: payload.scene_events_so_far,
    tool_events: [],
    public_attack_prompt: payload.public_attack_prompt,
    public_turn_state: payload.public_turn_state ?? null,
    public_turn_presentation: payload.public_turn_presentation ?? null,
    npc_role_id: payload.npc_role_id ?? null,
  });

  const buildPendingAttackDefenseFromStream = (payload: {
    pending_turn_id: string;
    flow_kind: PendingTurnContinueResponse['flow_kind'];
    reply_so_far: string;
    scene_events_so_far: SceneEvent[];
    public_attack_defense_prompt: PublicTurnAttackDefensePrompt | null;
    npc_role_id?: string | null;
    public_turn_state?: PublicTurnState | null;
    public_turn_presentation?: PublicTurnPresentation | null;
  }): PendingTurnContinueResponse => ({
    session_id: sessionId,
    pending_turn_id: payload.pending_turn_id,
    flow_kind: payload.flow_kind,
    status: 'awaiting_player_attack_defense',
    reply_text: payload.reply_so_far,
    scene_events: payload.scene_events_so_far,
    tool_events: [],
    public_attack_defense_prompt: payload.public_attack_defense_prompt,
    public_turn_state: payload.public_turn_state ?? null,
    public_turn_presentation: payload.public_turn_presentation ?? null,
    npc_role_id: payload.npc_role_id ?? null,
  });

  const buildPendingDeathSaveFromStream = (payload: {
    pending_turn_id: string;
    flow_kind: PendingTurnContinueResponse['flow_kind'];
    reply_so_far: string;
    scene_events_so_far: SceneEvent[];
    death_save_prompt: DeathSavePrompt | null;
    npc_role_id?: string | null;
    public_turn_state?: PublicTurnState | null;
    public_turn_presentation?: PublicTurnPresentation | null;
  }): PendingTurnContinueResponse => ({
    session_id: sessionId,
    pending_turn_id: payload.pending_turn_id,
    flow_kind: payload.flow_kind,
    status: 'awaiting_player_death_save',
    reply_text: payload.reply_so_far,
    scene_events: payload.scene_events_so_far,
    tool_events: [],
    death_save_prompt: payload.death_save_prompt,
    public_turn_state: payload.public_turn_state ?? null,
    public_turn_presentation: payload.public_turn_presentation ?? null,
    npc_role_id: payload.npc_role_id ?? null,
  });

  const extractDeathSaveSummary = (response: PendingTurnContinueResponse | PublicTurnResponse | null): string => {
    if (!response) return '';
    const latest = [...(response.scene_events ?? [])]
      .reverse()
      .find((event) => event.kind === 'player_died' || event.kind === 'player_death_save_result');
    return latest?.content?.trim() ?? '';
  };

  const buildEffectivePublicTurnConfig = (): AppConfig => {
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    return { ...config, gm_prompt: effectivePrompt };
  };

  const autoContinuePublicTurnProtocolRepair = async (
    repairRequest: PublicTurnProtocolRepairRequest,
    notice?: PublicTurnProtocolRepairNotice | null,
  ) => {
    const effectiveConfig = buildEffectivePublicTurnConfig();
    const requestPayload: PublicTurnProtocolRepairRequest = {
      ...repairRequest,
      config: effectiveConfig,
    };
    applyPublicTurnMainOutput({
      reply_text: '',
      scene_events: [],
      public_turn_state: currentMainOutput?.public_turn_state ?? null,
      public_turn_presentation: currentMainOutput?.public_turn_presentation ?? null,
      archived_sub_zone_turn_id: null,
      status: 'awaiting_protocol_repair',
    });
    setChatState('awaiting_protocol_repair');
    pushSystemNotice(notice?.message ?? 'AI 首次输出协议错误，正在自动修复并续跑...');
    try {
      const repaired = await continuePublicTurnProtocolRepair(requestPayload, report);
      setChatState('idle');
      if (isPendingTurnContinueResponse(repaired) && repaired.status !== 'completed') {
        handlePublicTurnPendingResponse(repaired);
        return;
      }
      if (!isPublicTurnResponse(repaired)) {
        throw new Error('公开回合协议修复返回了异常响应类型');
      }
      if (repaired.public_attack_defense_prompt) {
        applyPublicTurnResponse(repaired, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(repaired.public_attack_defense_prompt);
        return;
      }
      if (repaired.public_attack_prompt) {
        applyPublicTurnResponse(repaired, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(repaired.public_attack_prompt);
        return;
      }
      if (repaired.public_interaction_prompt) {
        handlePublicTurnInteractionRequired(repaired);
        return;
      }
      applyPublicTurnResponse(repaired, {
        status: repaired.round_completed ? 'awaiting_archive' : 'idle',
        mergeImpacts: true,
      });
      await syncEncounterLaneAfterSceneEvents(repaired.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '公开回合协议修复失败');
      setChatState('error');
    }
  };

  const applyPendingNpcTurnState = (response: PendingTurnContinueResponse) => {
    const npcRoleId = response.npc_role_id;
    if (!npcRoleId) return;
    setNpcChatMessages((prev) => {
      const current = [...(prev[npcRoleId] ?? [])];
      if (current.length > 0 && current[current.length - 1]?.role === 'assistant') {
        current[current.length - 1] = { ...current[current.length - 1], content: response.reply_text };
      } else {
        current.push({ role: 'assistant', content: response.reply_text });
      }
      return { ...prev, [npcRoleId]: current };
    });
    setNpcLiveProgress((prev) => ({ ...prev, [npcRoleId]: [] }));
  };

  const handlePendingReactionRequired = (response: PendingTurnContinueResponse) => {
    if (response.flow_kind === 'main_chat') {
      applyPendingMainTurnState(response);
    } else if (response.flow_kind === 'public_turn') {
      applyPendingPublicTurnState(response);
    } else if (response.flow_kind === 'npc_chat') {
      applyPendingNpcTurnState(response);
    }
    openPendingReaction(response);
  };

  const handlePendingAttackResponseRequired = (
    response: PendingTurnContinueResponse,
    prefill?: { action?: string; speech?: string },
  ) => {
    if (response.flow_kind === 'public_turn') {
      applyPendingPublicTurnState(response);
    }
    if (response.public_attack_prompt) {
      openPendingAttackResponse(response.public_attack_prompt, prefill);
    }
  };

  const handlePendingAttackDefenseRequired = (response: PendingTurnContinueResponse) => {
    if (response.flow_kind === 'public_turn') {
      applyPendingPublicTurnState(response);
    }
    if (response.public_attack_defense_prompt) {
      openPendingAttackDefense(response.public_attack_defense_prompt);
    }
  };

  const handlePendingDeathSaveRequired = (response: PendingTurnContinueResponse) => {
    if (response.flow_kind === 'public_turn') {
      applyPendingPublicTurnState(response);
    }
    if (response.death_save_prompt) {
      openPendingDeathSave(response.death_save_prompt);
    }
  };

  const handlePendingOpposedRequired = (
    response: PendingTurnContinueResponse,
    prefill?: { action?: string; speech?: string },
  ) => {
    if (response.flow_kind === 'public_turn') {
      applyPendingPublicTurnState(response);
    }
    openPendingOpposed(response, prefill);
  };

  const handlePublicTurnInteractionRequired = (response: PublicTurnResponse) => {
    applyPublicTurnResponse(response, { status: 'awaiting_interaction', mergeImpacts: true });
    if (response.public_interaction_prompt) {
      openPendingInteraction(response.public_interaction_prompt);
    }
  };

  const handlePublicTurnPendingResponse = (response: PendingTurnContinueResponse) => {
    if (response.status === 'awaiting_protocol_repair' && response.public_turn_protocol_repair_request) {
      applyPendingPublicTurnState(response);
      void autoContinuePublicTurnProtocolRepair(
        response.public_turn_protocol_repair_request,
        response.public_turn_protocol_repair_notice,
      );
      return;
    }
    if (response.status === 'awaiting_player_attack_defense' && response.public_attack_defense_prompt) {
      handlePendingAttackDefenseRequired(response);
      return;
    }
    if (response.status === 'awaiting_player_attack_response' && response.public_attack_prompt) {
      handlePendingAttackResponseRequired(response);
      return;
    }
    if (response.status === 'awaiting_player_death_save' && response.death_save_prompt) {
      handlePendingDeathSaveRequired(response);
      return;
    }
    if (response.status === 'awaiting_opposed' && response.public_opposed_prompt) {
      handlePendingOpposedRequired(response);
      return;
    }
    if (response.status === 'awaiting_reaction' && response.pending_reaction) {
      handlePendingReactionRequired(response);
    }
  };

  const onSubmitPublicTurnInteraction = async () => {
    const pending = pendingInteractionState;
    if (!pending) return;
    const actionText = publicTurnInteractionActionInput.trim();
    const speechText = publicTurnInteractionSpeechInput.trim();
    if (!actionText && !speechText) {
      setPublicTurnInteractionError('至少需要输入回应行为或语言。');
      return;
    }

    let finalActionText = actionText;
    let finalSpeechText = speechText;
    try {
      const validated = await performPlayerInputValidation({
        entryPoint: 'public_turn_interaction_response',
        actorRoleId: playerStatic.player_id,
        actionText,
        speechText,
      });
      if (!validated) {
        return;
      }
      finalActionText = validated.actionText;
      finalSpeechText = validated.speechText;
    } catch (e) {
      setPublicTurnInteractionError(e instanceof Error ? e.message : '玩家输入校验失败');
      return;
    }
    if (!finalActionText && !finalSpeechText) {
      setPublicTurnInteractionError('校验建议后没有可提交内容，请返回修改。');
      return;
    }

    setPublicTurnInteractionBusy(true);
    setPublicTurnInteractionError('');
    try {
      const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
      const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
      const response = await continuePublicTurn(
        {
          session_id: sessionId,
          player_interaction_response: {
            prompt_id: pending.prompt.prompt_id,
            action_text: finalActionText,
            speech_text: finalSpeechText,
            response_kind: 'explicit_response',
          },
          config: effectiveConfig,
        },
        report,
      );
      if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
        resetPublicTurnInteractionState();
        setChatState('idle');
        if (response.status === 'awaiting_opposed' && response.public_opposed_prompt) {
          handlePendingOpposedRequired(response, { action: finalActionText, speech: finalSpeechText });
          return;
        }
        handlePublicTurnPendingResponse(response);
        return;
      }
      if (!isPublicTurnResponse(response)) {
        setError('公开回合交互响应类型异常');
        setChatState('error');
        return;
      }
      if (response.public_attack_defense_prompt) {
        resetPublicTurnInteractionState();
        setChatState('idle');
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(response.public_attack_defense_prompt);
        return;
      }
      if (response.public_attack_prompt) {
        resetPublicTurnInteractionState();
        setChatState('idle');
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(response.public_attack_prompt);
        return;
      }
      if (response.public_opposed_prompt) {
        resetPublicTurnInteractionState();
        setChatState('idle');
        applyPublicTurnResponse(response, { status: 'awaiting_opposed', mergeImpacts: true });
        openDirectPublicTurnOpposedPrompt(response.public_opposed_prompt, { action: finalActionText, speech: finalSpeechText });
        return;
      }
      if (response.public_interaction_prompt) {
        resetPublicTurnInteractionState();
        setChatState('idle');
        handlePublicTurnInteractionRequired(response);
        return;
      }
      resetPublicTurnInteractionState();
      setChatState('idle');
      applyPublicTurnResponse(response, {
        status: response.round_completed ? 'awaiting_archive' : 'idle',
        mergeImpacts: true,
      });
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setPublicTurnInteractionError(e instanceof Error ? e.message : '公开回合交互提交失败');
      setChatState('error');
    } finally {
      setPublicTurnInteractionBusy(false);
    }
  };

  const onSubmitPublicTurnInteractionNoAction = async () => {
    const pending = pendingInteractionState;
    if (!pending) return;
    setPublicTurnInteractionBusy(true);
    setPublicTurnInteractionError('');
    try {
      const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
      const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
      const response = await continuePublicTurn(
        {
          session_id: sessionId,
          player_interaction_response: {
            prompt_id: pending.prompt.prompt_id,
            action_text: '',
            speech_text: '',
            response_kind: 'no_action',
          },
          config: effectiveConfig,
        },
        report,
      );
      if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
        resetPublicTurnInteractionState();
        setChatState('idle');
        handlePublicTurnPendingResponse(response);
        return;
      }
      if (!isPublicTurnResponse(response)) {
        setError('公开回合交互响应类型异常');
        setChatState('error');
        return;
      }
      resetPublicTurnInteractionState();
      setChatState('idle');
      if (response.public_attack_defense_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(response.public_attack_defense_prompt);
        return;
      }
      if (response.public_attack_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(response.public_attack_prompt);
        return;
      }
      if (response.public_interaction_prompt) {
        handlePublicTurnInteractionRequired(response);
        return;
      }
      if (response.public_opposed_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_opposed', mergeImpacts: true });
        openDirectPublicTurnOpposedPrompt(response.public_opposed_prompt);
        return;
      }
      applyPublicTurnResponse(response, {
        status: response.round_completed ? 'awaiting_archive' : 'idle',
        mergeImpacts: true,
      });
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setPublicTurnInteractionError(e instanceof Error ? e.message : '公开回合交互提交失败');
      setChatState('error');
    } finally {
      setPublicTurnInteractionBusy(false);
    }
  };

  const onSubmitPublicTurnAttackResponse = async () => {
    const pending = pendingAttackState;
    if (!pending) return;
    const actionText = publicTurnAttackActionInput.trim();
    const speechText = publicTurnAttackSpeechInput.trim();
    if (!actionText && !speechText) {
      setPublicTurnAttackError('至少需要输入回应行为或语言。');
      return;
    }

    let finalActionText = actionText;
    let finalSpeechText = speechText;
    try {
      const validated = await performPlayerInputValidation({
        entryPoint: 'public_turn_attack_response',
        actorRoleId: playerStatic.player_id,
        actionText,
        speechText,
      });
      if (!validated) {
        return;
      }
      finalActionText = validated.actionText;
      finalSpeechText = validated.speechText;
    } catch (e) {
      setPublicTurnAttackError(e instanceof Error ? e.message : '玩家输入校验失败');
      return;
    }
    if (!finalActionText && !finalSpeechText) {
      setPublicTurnAttackError('校验建议后没有可提交内容，请返回修改。');
      return;
    }

    setPublicTurnAttackBusy(true);
    setPublicTurnAttackError('');
    try {
      const effectiveConfig = buildEffectivePublicTurnConfig();
      const response = await continuePublicTurn(
        {
          session_id: sessionId,
          player_attack_response: {
            prompt_id: pending.prompt.prompt_id,
            target_actor_id: pending.prompt.current_target_actor_id,
            action_text: finalActionText,
            speech_text: finalSpeechText,
            response_kind: 'explicit_response',
          },
          config: effectiveConfig,
        },
        report,
      );
      resetPublicTurnAttackState();
      setChatState('idle');
      if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
        if (response.status === 'awaiting_player_attack_response' && response.public_attack_prompt) {
          handlePendingAttackResponseRequired(response, { action: finalActionText, speech: finalSpeechText });
          return;
        }
        handlePublicTurnPendingResponse(response);
        return;
      }
      if (!isPublicTurnResponse(response)) {
        setError('公开回合攻击回应响应类型异常');
        setChatState('error');
        return;
      }
      if (response.public_attack_defense_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(response.public_attack_defense_prompt);
        return;
      }
      if (response.public_attack_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(response.public_attack_prompt);
        return;
      }
      if (response.public_interaction_prompt) {
        handlePublicTurnInteractionRequired(response);
        return;
      }
      if (response.public_opposed_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_opposed', mergeImpacts: true });
        openDirectPublicTurnOpposedPrompt(response.public_opposed_prompt);
        return;
      }
      applyPublicTurnResponse(response, {
        status: response.round_completed ? 'awaiting_archive' : 'idle',
        mergeImpacts: true,
      });
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setPublicTurnAttackError(e instanceof Error ? e.message : '公开回合攻击回应提交失败');
      setChatState('error');
    } finally {
      setPublicTurnAttackBusy(false);
    }
  };

  const onSubmitPublicTurnAttackNoAction = async () => {
    const pending = pendingAttackState;
    if (!pending) return;
    setPublicTurnAttackBusy(true);
    setPublicTurnAttackError('');
    try {
      const effectiveConfig = buildEffectivePublicTurnConfig();
      const response = await continuePublicTurn(
        {
          session_id: sessionId,
          player_attack_response: {
            prompt_id: pending.prompt.prompt_id,
            target_actor_id: pending.prompt.current_target_actor_id,
            action_text: '',
            speech_text: '',
            response_kind: 'no_action',
          },
          config: effectiveConfig,
        },
        report,
      );
      resetPublicTurnAttackState();
      setChatState('idle');
      if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
        handlePublicTurnPendingResponse(response);
        return;
      }
      if (!isPublicTurnResponse(response)) {
        setError('公开回合攻击回应响应类型异常');
        setChatState('error');
        return;
      }
      if (response.public_attack_defense_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(response.public_attack_defense_prompt);
        return;
      }
      if (response.public_attack_prompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(response.public_attack_prompt);
        return;
      }
      applyPublicTurnResponse(response, {
        status: response.round_completed ? 'awaiting_archive' : 'idle',
        mergeImpacts: true,
      });
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setPublicTurnAttackError(e instanceof Error ? e.message : '公开回合攻击回应提交失败');
      setChatState('error');
    } finally {
      setPublicTurnAttackBusy(false);
    }
  };

  const onTriggerPublicTurnAttackDefenseRoll = () => {
    if (publicTurnAttackDefenseRollState.phase !== 'ready') return;
    const pending = pendingAttackDefenseState;
    if (!pending) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setPublicTurnAttackDefenseRollState((current) => ({
      ...current,
      phase: 'rolling',
      rollValue,
      result: null,
      errorMessage: '',
      rotation,
    }));
    window.setTimeout(() => {
      void (async () => {
        setPublicTurnAttackDefenseRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        try {
          const effectiveConfig = buildEffectivePublicTurnConfig();
          let response: PublicTurnResponse | PendingTurnContinueResponse;
          if (config.stream) {
            let finalResponse: PublicTurnResponse | PendingTurnContinueResponse | null = null;
            let streamedReply = currentMainOutput?.reply_text ?? '';
            let streamedSceneEvents = currentMainOutput?.scene_events ?? [];
            let streamedImpacts = [...publicTurnImpacts];
            let streamedTurnState = currentMainOutput?.public_turn_state ?? null;
            let streamedPresentation = currentMainOutput?.public_turn_presentation ?? null;
            let streamFailed = false;
            const controller = new AbortController();
            abortRef.current = controller;
            activeStreamRef.current = { kind: 'main' };
            await streamResolvePublicTurnAttackDefense(
              {
                session_id: sessionId,
                check_id: pending.prompt.check_id,
                forced_dice_roll: rollValue,
                config: effectiveConfig,
              },
              {
                onPhase: (event) => {
                  setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
                },
                onTurnState: (state) => {
                  streamedTurnState = state;
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
                },
                onInitiativeOrder: (entries, meta) => {
                  streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onSettlementEntry: (entry) => {
                  streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onRoundNarrationDelta: (delta) => {
                  streamedReply = `${streamedReply}${delta}`;
                  streamedPresentation = withRoundNarration(streamedPresentation, delta);
                  applyPublicTurnMainOutput({
                    reply_text: streamedReply,
                    scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                    public_turn_state: streamedTurnState,
                    public_turn_presentation: streamedPresentation,
                    archived_sub_zone_turn_id: null,
                    status: 'streaming',
                  });
                },
                onSceneEvent: (event) => {
                  streamedSceneEvents = [...streamedSceneEvents, event];
                  setCurrentMainOutput((prev) =>
                    prev
                      ? {
                          ...prev,
                          scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                        }
                      : prev,
                  );
                },
                onImpact: (impact) => {
                  streamedImpacts = [...streamedImpacts, impact];
                  setPublicTurnImpacts(streamedImpacts);
                },
                onInteractionRequired: (prompt) => {
                  finalResponse = {
                    ok: true,
                    session_id: sessionId,
                    phase: prompt.phase,
                    narration: streamedReply,
                    scene_events: streamedSceneEvents,
                    reaction_check: null,
                    public_interaction_prompt: prompt,
                    public_attack_prompt: null,
                    public_attack_defense_prompt: null,
                    public_opposed_prompt: null,
                    round_completed: false,
                    awaiting_entry: false,
                    public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                    archived_sub_zone_turn_id: null,
                    impacts: streamedImpacts,
                    player_action_check_result: null,
                    presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                  };
                },
                onAttackResponseRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_player_attack_response',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_attack_prompt: payload.public_attack_prompt,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onAttackDefenseRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_player_attack_defense',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_attack_defense_prompt: payload.public_attack_defense_prompt,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onDeathSaveRequired: (payload) => {
                  finalResponse = buildPendingDeathSaveFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    death_save_prompt: payload.death_save_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onReactionCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_reaction',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: payload.pending_reaction,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onOpposedCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_opposed',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_opposed_prompt: payload.public_opposed_prompt,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onProtocolRepairRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_protocol_repair',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                    public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                  };
                },
                onError: (message) => {
                  streamFailed = true;
                  setError(message);
                  setChatState('error');
                  abortRef.current = null;
                  activeStreamRef.current = null;
                },
                onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
                  if (streamFailed) return;
                  if (!finalResponse) {
                    finalResponse = {
                      ok: true,
                      session_id: sessionId,
                      phase: (public_turn_state?.current_round?.phase ?? 'idle') as PublicTurnPhase,
                      narration: streamedReply,
                      scene_events: streamedSceneEvents,
                      reaction_check: null,
                      public_interaction_prompt: null,
                      public_attack_prompt: null,
                      public_attack_defense_prompt: null,
                      public_opposed_prompt: null,
                      round_completed: round_completed ?? false,
                      awaiting_entry: false,
                      public_turn_state: public_turn_state ?? streamedTurnState ?? defaultPublicTurnState,
                      archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                      impacts: streamedImpacts,
                      player_action_check_result: null,
                      presentation: presentation ?? streamedPresentation ?? emptyPublicTurnPresentation(),
                    };
                  }
                },
              },
              controller.signal,
              report,
            );
            if (streamFailed || !finalResponse) {
              return;
            }
            response = finalResponse;
          } else {
            response = await resolvePublicTurnAttackDefense(
              {
                session_id: sessionId,
                check_id: pending.prompt.check_id,
                forced_dice_roll: rollValue,
                config: effectiveConfig,
              },
              report,
            );
          }
          const result = response.player_action_check_result ?? null;
          if (!result) {
            throw new Error('公开回合攻击对抗检定结果缺失');
          }
          setPublicTurnAttackDefenseRollState((current) => ({
            ...current,
            phase: 'resolved',
            rollValue: result.dice_roll ?? rollValue,
            result,
            errorMessage: '',
          }));
          publicTurnActionResponseRef.current = response;
        } catch (e) {
          const message = e instanceof Error ? e.message : '公开回合攻击对抗检定失败';
          setPublicTurnAttackDefenseRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
        }
      })();
    }, 1650);
  };

  const onClosePublicTurnAttackDefenseModal = () => {
    const response = publicTurnActionResponseRef.current;
    publicTurnActionResponseRef.current = null;
    resetPublicTurnAttackDefenseState();
    abortRef.current = null;
    activeStreamRef.current = null;
    setChatState('idle');
    if (!response) {
      return;
    }
    if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
      handlePublicTurnPendingResponse(response);
      return;
    }
    if (!isPublicTurnResponse(response)) {
      setError('公开回合攻击对抗响应类型异常');
      setChatState('error');
      return;
    }
    if (response.public_attack_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
      openPendingAttackResponse(response.public_attack_prompt);
      return;
    }
    if (response.public_attack_defense_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
      openPendingAttackDefense(response.public_attack_defense_prompt);
      return;
    }
    if (response.public_interaction_prompt) {
      handlePublicTurnInteractionRequired(response);
      return;
    }
    if (response.public_opposed_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_opposed', mergeImpacts: true });
      openDirectPublicTurnOpposedPrompt(response.public_opposed_prompt);
      return;
    }
    applyPublicTurnResponse(response, {
      status: response.round_completed ? 'awaiting_archive' : 'idle',
      mergeImpacts: true,
    });
    void (async () => {
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    })();
  };

  const onPlanPublicTurnOpposed = async () => {
    const pending = pendingOpposedState;
    if (!pending) return;
    await planPublicTurnOpposedForPrompt(
      pending.prompt,
      publicTurnOpposedActionInput,
      publicTurnOpposedSpeechInput,
    );
  };

  const onTriggerPublicTurnOpposedRoll = () => {
    if (publicTurnOpposedRollState.phase !== 'ready') return;
    const pending = pendingOpposedState;
    const plan = publicTurnOpposedPlan;
    if (!pending || !plan) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setPublicTurnOpposedRollState((current) => ({
      ...current,
      phase: 'rolling',
      rollValue,
      result: null,
      errorMessage: '',
      rotation,
    }));
    window.setTimeout(() => {
      void (async () => {
        setPublicTurnOpposedRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        try {
          const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
          const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
          if (config.stream) {
            const controller = new AbortController();
            abortRef.current = controller;
            activeStreamRef.current = { kind: 'main' };
            let streamedReply = currentMainOutput?.reply_text ?? '';
            let streamedSceneEvents = currentMainOutput?.scene_events ?? [];
            let streamedImpacts = [...publicTurnImpacts];
            let streamedTurnState = currentMainOutput?.public_turn_state ?? null;
            let streamedPresentation = currentMainOutput?.public_turn_presentation ?? null;
            let finalResponse: PendingTurnContinueResponse | PublicTurnResponse | null = null;
            let streamFailed = false;

            await streamResolvePublicTurnOpposedCheck(
              {
                session_id: sessionId,
                check_id: pending.prompt.check_id,
                forced_dice_roll: rollValue,
                target_action_summary: plan.target_action_summary,
                target_speech_text: plan.target_speech_text,
                config: effectiveConfig,
              },
              {
                onPhase: (event) => {
                  setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
                },
                onTurnState: (state) => {
                  streamedTurnState = state;
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
                },
                onInitiativeOrder: (entries, meta) => {
                  streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onSettlementEntry: (entry) => {
                  streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onRoundNarrationDelta: (delta) => {
                  streamedReply = `${streamedReply}${delta}`;
                  streamedPresentation = withRoundNarration(streamedPresentation, delta);
                  applyPublicTurnMainOutput({
                    reply_text: streamedReply,
                    scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                    public_turn_state: streamedTurnState,
                    public_turn_presentation: streamedPresentation,
                    archived_sub_zone_turn_id: null,
                    status: 'streaming',
                  });
                },
                onSceneEvent: (event) => {
                  streamedSceneEvents = [...streamedSceneEvents, event];
                  setCurrentMainOutput((prev) =>
                    prev
                      ? {
                          ...prev,
                          scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                        }
                      : prev,
                  );
                },
                onImpact: (impact) => {
                  streamedImpacts = [...streamedImpacts, impact];
                  setPublicTurnImpacts(streamedImpacts);
                },
                onInteractionRequired: (prompt) => {
                  finalResponse = {
                    ok: true,
                    session_id: sessionId,
                    phase: prompt.phase,
                    narration: streamedReply,
                    scene_events: streamedSceneEvents,
                    reaction_check: null,
                    public_interaction_prompt: prompt,
                    public_opposed_prompt: null,
                    round_completed: false,
                    awaiting_entry: false,
                    public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                    archived_sub_zone_turn_id: null,
                    impacts: streamedImpacts,
                    player_action_check_result: resolvePublicTurnOpposedResult(
                      pending.prompt,
                      plan,
                      streamedPresentation,
                    ),
                    presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                  };
                },
                onAttackResponseRequired: (payload) => {
                  finalResponse = buildPendingAttackResponseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_prompt: payload.public_attack_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onAttackDefenseRequired: (payload) => {
                  finalResponse = buildPendingAttackDefenseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_defense_prompt: payload.public_attack_defense_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onDeathSaveRequired: (payload) => {
                  finalResponse = buildPendingDeathSaveFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    death_save_prompt: payload.death_save_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onReactionCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_reaction',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: payload.pending_reaction,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                    player_action_check_result: resolvePublicTurnOpposedResult(
                      pending.prompt,
                      plan,
                      payload.public_turn_presentation ?? streamedPresentation,
                    ),
                  };
                },
                onOpposedCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_opposed',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: null,
                    public_opposed_prompt: payload.public_opposed_prompt,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                    player_action_check_result: resolvePublicTurnOpposedResult(
                      pending.prompt,
                      plan,
                      payload.public_turn_presentation ?? streamedPresentation,
                    ),
                  };
                },
                onProtocolRepairRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_protocol_repair',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                    public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                    player_action_check_result: resolvePublicTurnOpposedResult(
                      pending.prompt,
                      plan,
                      payload.public_turn_presentation ?? streamedPresentation,
                    ),
                  };
                },
                onOpposedCheckResolved: () => undefined,
                onError: (message) => {
                  streamFailed = true;
                  setError(message);
                  setChatState('error');
                  abortRef.current = null;
                  activeStreamRef.current = null;
                },
                onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
                  if (streamFailed) {
                    return;
                  }
                  finalResponse = {
                    ok: true,
                    session_id: sessionId,
                    phase:
                      (public_turn_state?.current_round?.phase ??
                        presentation?.phase ??
                        streamedTurnState?.current_round?.phase ??
                        'normal_advancement') as PublicTurnPhase,
                    narration: streamedReply,
                    scene_events: streamedSceneEvents,
                    reaction_check: null,
                    public_interaction_prompt: null,
                    public_opposed_prompt: null,
                    round_completed: round_completed ?? false,
                    awaiting_entry: public_turn_state?.awaiting_player_entry ?? false,
                    public_turn_state: public_turn_state ?? streamedTurnState ?? defaultPublicTurnState,
                    archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                    impacts: streamedImpacts,
                    player_action_check_result: resolvePublicTurnOpposedResult(
                      pending.prompt,
                      plan,
                      presentation ?? streamedPresentation,
                    ),
                    presentation: presentation ?? streamedPresentation ?? emptyPublicTurnPresentation(),
                  };
                  abortRef.current = null;
                  activeStreamRef.current = null;
                },
              },
              controller.signal,
              report,
            );

            abortRef.current = null;
            activeStreamRef.current = null;
            if (streamFailed) {
              return;
            }
            if (!finalResponse) {
              throw new Error('公开回合对抗续行未返回结果');
            }
            const resolvedResponse = finalResponse as PendingTurnContinueResponse | PublicTurnResponse;
            pendingOpposedResponseRef.current = resolvedResponse;
            let opposedResult: ActionCheckResult | null = null;
            if ('phase' in resolvedResponse) {
              opposedResult =
                resolvedResponse.player_action_check_result ??
                resolvePublicTurnOpposedResult(pending.prompt, plan, resolvedResponse.presentation);
            } else {
              opposedResult = resolvePublicTurnOpposedResult(
                pending.prompt,
                plan,
                resolvedResponse.public_turn_presentation,
                resolvedResponse.player_action_check_result,
              );
            }
            setPublicTurnOpposedRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: opposedResult,
              errorMessage: '',
            }));
            return;
          }

          const response = await resolvePublicTurnOpposedCheck(
            {
              session_id: sessionId,
              check_id: pending.prompt.check_id,
              forced_dice_roll: rollValue,
              target_action_summary: plan.target_action_summary,
              target_speech_text: plan.target_speech_text,
              config: effectiveConfig,
            },
            report,
          );
          pendingOpposedResponseRef.current = response;
          setPublicTurnOpposedRollState((current) => ({
            ...current,
            phase: 'resolved',
            result: isPendingTurnContinueResponse(response)
              ? resolvePublicTurnOpposedResult(
                pending.prompt,
                plan,
                response.public_turn_presentation,
                response.player_action_check_result,
              )
              : resolvePublicTurnOpposedResult(
                pending.prompt,
                plan,
                response.presentation,
                response.player_action_check_result,
              ),
            errorMessage: '',
          }));
        } catch (e) {
          const message = e instanceof Error ? e.message : '公开回合对抗失败';
          setPublicTurnOpposedRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
          setChatState('error');
        }
      })();
    }, 1650);
  };

  const onClosePublicTurnOpposedModal = () => {
    const pending = pendingOpposedState;
    const response = pendingOpposedResponseRef.current;
    resetPublicTurnOpposedState();
    pendingOpposedResponseRef.current = null;
    if (response) {
      abortRef.current = null;
      activeStreamRef.current = null;
      setChatState('idle');
      if (isPendingTurnContinueResponse(response)) {
        handlePublicTurnPendingResponse(response);
        return;
      }
      const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
      if (attackDefensePrompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(attackDefensePrompt);
        return;
      }
      const attackPrompt = findPendingPublicTurnAttackPrompt(response);
      if (attackPrompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
        openPendingAttackResponse(attackPrompt);
        return;
      }
      const interactionPrompt = findPendingPublicTurnInteractionPrompt(response);
      if (interactionPrompt) {
        handlePublicTurnInteractionRequired(response);
        return;
      }
      applyPublicTurnResponse(response, { status: response.round_completed ? 'awaiting_archive' : 'idle', mergeImpacts: true });
      void (async () => {
        await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
        await refreshAreaSnapshot();
        await refreshGameLogs(sessionId);
        await syncStateFromSave(sessionId);
      })();
      return;
    }
    if (!pending) {
      setChatState('idle');
      return;
    }
    void (async () => {
      try {
        await cancelPendingTurn({ session_id: sessionId, pending_turn_id: pending.pending_turn_id }, report);
      } catch {
        // Ignore cancel failures and still reset the local UI.
      }
      abortRef.current = null;
      activeStreamRef.current = null;
      setMainLiveProgress([]);
      setChatState('idle');
      window.alert('本轮对抗已作废');
    })();
  };

  const onTriggerPublicTurnActionRoll = () => {
    if (publicTurnActionRollState.phase !== 'ready') return;
    const pending = pendingPublicTurnActionRef.current;
    const plan = publicTurnActionRollState.plan;
    if (!pending || !plan) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setPublicTurnActionRollState((current) => ({
      ...current,
      phase: 'rolling',
      rollValue,
      result: null,
      errorMessage: '',
      rotation,
    }));
    window.setTimeout(() => {
      void (async () => {
        setPublicTurnActionRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        try {
          const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
          const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
          const response = await continuePublicTurn(
            {
              session_id: sessionId,
              action_submission: pending.actionSubmission,
              player_action_check: {
                ...pending.playerActionCheck,
                forced_dice_roll: rollValue,
              },
              config: effectiveConfig,
            },
            report,
          );
          publicTurnActionResponseRef.current = response;
          const result = response.player_action_check_result ?? null;
          if (!result) {
            throw new Error('公开回合检定结果缺失');
          }
          setPublicTurnActionRollState((current) => ({
            ...current,
            phase: 'resolved',
            rollValue: result.dice_roll ?? rollValue,
            result,
            errorMessage: '',
          }));
        } catch (e) {
          const message = e instanceof Error ? e.message : '公开回合检定失败';
          setPublicTurnActionRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
        }
      })();
    }, 1650);
  };

  const onClosePublicTurnActionRoll = () => {
    const response = publicTurnActionResponseRef.current;
    pendingPublicTurnActionRef.current = null;
    publicTurnActionResponseRef.current = null;
    resetPublicTurnActionRollState();
    if (!response) {
      return;
    }
    clearPlayerInput();
    abortRef.current = null;
    activeStreamRef.current = null;
    setChatState('idle');
    if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
      handlePublicTurnPendingResponse(response);
      return;
    }
    if (!isPublicTurnResponse(response)) {
      setError('公开回合响应类型异常');
      setChatState('error');
      return;
    }
    if (findPendingPublicTurnAttackDefensePrompt(response)) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
      openPendingAttackDefense(findPendingPublicTurnAttackDefensePrompt(response)!);
      return;
    }
    if (findPendingPublicTurnAttackPrompt(response)) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
      openPendingAttackResponse(findPendingPublicTurnAttackPrompt(response)!);
      return;
    }
    if (findPendingPublicTurnInteractionPrompt(response)) {
      handlePublicTurnInteractionRequired(response);
      return;
    }
    applyPublicTurnResponse(response, { status: response.round_completed ? 'awaiting_archive' : 'idle' });
    void (async () => {
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    })();
  };

  const onTriggerPublicTurnDeathSaveRoll = () => {
    if (publicTurnDeathSaveRollState.phase !== 'ready') return;
    const pending = pendingDeathSaveState;
    if (!pending) return;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: 1080 + Math.floor(Math.random() * 720),
      y: 1440 + Math.floor(Math.random() * 720),
      z: 900 + Math.floor(Math.random() * 720),
    };
    setPublicTurnDeathSaveRollState((current) => ({
      ...current,
      phase: 'rolling',
      rollValue,
      errorMessage: '',
      rotation,
    }));
    window.setTimeout(() => {
      void (async () => {
        setPublicTurnDeathSaveRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        try {
          const effectiveConfig = buildEffectivePublicTurnConfig();
          let response: PendingTurnContinueResponse | PublicTurnResponse;
          if (config.stream) {
            const controller = new AbortController();
            abortRef.current = controller;
            activeStreamRef.current = { kind: 'main' };
            let streamedReply = currentMainOutput?.reply_text ?? '';
            let streamedSceneEvents = currentMainOutput?.scene_events ?? [];
            let streamedImpacts = [...publicTurnImpacts];
            let streamedTurnState = currentMainOutput?.public_turn_state ?? null;
            let streamedPresentation = currentMainOutput?.public_turn_presentation ?? null;
            let finalResponse: PendingTurnContinueResponse | PublicTurnResponse | null = null;
            let streamFailed = false;

            await streamResolvePublicTurnDeathSave(
              {
                session_id: sessionId,
                prompt_id: pending.prompt.prompt_id,
                forced_dice_roll: rollValue,
                config: effectiveConfig,
              },
              {
                onPhase: (event) => {
                  setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
                },
                onTurnState: (state) => {
                  streamedTurnState = state;
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
                },
                onInitiativeOrder: (entries, meta) => {
                  streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onSettlementEntry: (entry) => {
                  streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                  setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
                },
                onRoundNarrationDelta: (delta) => {
                  streamedReply = `${streamedReply}${delta}`;
                  streamedPresentation = withRoundNarration(streamedPresentation, delta);
                  applyPublicTurnMainOutput({
                    reply_text: streamedReply,
                    scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                    public_turn_state: streamedTurnState,
                    public_turn_presentation: streamedPresentation,
                    archived_sub_zone_turn_id: null,
                    status: 'streaming',
                  });
                },
                onSceneEvent: (event) => {
                  streamedSceneEvents = [...streamedSceneEvents, event];
                  setCurrentMainOutput((prev) =>
                    prev
                      ? {
                          ...prev,
                          scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                        }
                      : prev,
                  );
                },
                onImpact: (impact) => {
                  streamedImpacts = [...streamedImpacts, impact];
                  setPublicTurnImpacts(streamedImpacts);
                },
                onInteractionRequired: (prompt) => {
                  finalResponse = {
                    ok: true,
                    session_id: sessionId,
                    phase: prompt.phase,
                    narration: streamedReply,
                    scene_events: streamedSceneEvents,
                    reaction_check: null,
                    public_interaction_prompt: prompt,
                    public_attack_prompt: null,
                    public_attack_defense_prompt: null,
                    public_opposed_prompt: null,
                    round_completed: false,
                    awaiting_entry: false,
                    public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                    archived_sub_zone_turn_id: null,
                    impacts: streamedImpacts,
                    player_action_check_result: null,
                    presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                  };
                },
                onAttackResponseRequired: (payload) => {
                  finalResponse = buildPendingAttackResponseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_prompt: payload.public_attack_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onAttackDefenseRequired: (payload) => {
                  finalResponse = buildPendingAttackDefenseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_defense_prompt: payload.public_attack_defense_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onDeathSaveRequired: (payload) => {
                  finalResponse = buildPendingDeathSaveFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    death_save_prompt: payload.death_save_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  });
                },
                onReactionCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_reaction',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: payload.pending_reaction,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onOpposedCheckRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_opposed',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    pending_reaction: null,
                    public_opposed_prompt: payload.public_opposed_prompt,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                  };
                },
                onProtocolRepairRequired: (payload) => {
                  finalResponse = {
                    session_id: sessionId,
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    status: 'awaiting_protocol_repair',
                    reply_text: payload.reply_so_far,
                    scene_events: payload.scene_events_so_far,
                    tool_events: [],
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                    public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                  };
                },
                onError: (message) => {
                  streamFailed = true;
                  setError(message);
                  setChatState('error');
                  abortRef.current = null;
                  activeStreamRef.current = null;
                },
                onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
                  if (streamFailed || finalResponse) {
                    return;
                  }
                  finalResponse = {
                    ok: true,
                    session_id: sessionId,
                    phase:
                      (public_turn_state?.current_round?.phase ??
                        presentation?.phase ??
                        streamedTurnState?.current_round?.phase ??
                        'normal_advancement') as PublicTurnPhase,
                    narration: streamedReply,
                    scene_events: streamedSceneEvents,
                    reaction_check: null,
                    public_interaction_prompt: null,
                    public_attack_prompt: null,
                    public_attack_defense_prompt: null,
                    public_opposed_prompt: null,
                    round_completed: round_completed ?? false,
                    awaiting_entry: public_turn_state?.awaiting_player_entry ?? false,
                    public_turn_state: public_turn_state ?? streamedTurnState ?? defaultPublicTurnState,
                    archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                    impacts: streamedImpacts,
                    player_action_check_result: null,
                    presentation: presentation ?? streamedPresentation ?? emptyPublicTurnPresentation(),
                  };
                  abortRef.current = null;
                  activeStreamRef.current = null;
                },
              },
              controller.signal,
              report,
            );

            abortRef.current = null;
            activeStreamRef.current = null;
            if (streamFailed || !finalResponse) {
              return;
            }
            response = finalResponse;
          } else {
            response = await resolvePublicTurnDeathSave(
              {
                session_id: sessionId,
                prompt_id: pending.prompt.prompt_id,
                forced_dice_roll: rollValue,
                config: effectiveConfig,
              },
              report,
            );
          }
          pendingDeathSaveResponseRef.current = response;
          setPublicTurnDeathSaveSummary(extractDeathSaveSummary(response));
          setPublicTurnDeathSaveRollState((current) => ({
            ...current,
            phase: 'resolved',
            rollValue,
            errorMessage: '',
          }));
        } catch (e) {
          const message = e instanceof Error ? e.message : '死亡豁免检定失败';
          setPublicTurnDeathSaveRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
        }
      })();
    }, 1650);
  };

  const onClosePublicTurnDeathSaveModal = () => {
    if (publicTurnDeathSaveRollState.phase === 'error') {
      setPublicTurnDeathSaveRollState({
        ...DEFAULT_PUBLIC_TURN_DEATH_SAVE_ROLL_STATE,
        open: true,
      });
      setPublicTurnDeathSaveSummary('');
      setChatState('awaiting_death_save');
      return;
    }
    const response = pendingDeathSaveResponseRef.current;
    clearPendingDeathSaveState();
    abortRef.current = null;
    activeStreamRef.current = null;
    setChatState('idle');
    if (!response) {
      return;
    }
    if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
      handlePublicTurnPendingResponse(response);
      return;
    }
    if (!isPublicTurnResponse(response)) {
      setError('公开回合死亡豁免响应类型异常');
      setChatState('error');
      return;
    }
    if (response.public_attack_defense_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
      openPendingAttackDefense(response.public_attack_defense_prompt);
      return;
    }
    if (response.public_attack_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
      openPendingAttackResponse(response.public_attack_prompt);
      return;
    }
    if (response.public_interaction_prompt) {
      handlePublicTurnInteractionRequired(response);
      return;
    }
    if (response.public_opposed_prompt) {
      applyPublicTurnResponse(response, { status: 'awaiting_opposed', mergeImpacts: true });
      openDirectPublicTurnOpposedPrompt(response.public_opposed_prompt);
      return;
    }
    applyPublicTurnResponse(response, {
      status: response.round_completed ? 'awaiting_archive' : 'idle',
      mergeImpacts: true,
    });
    void (async () => {
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    })();
  };

  const onAcceptQuest = async (questId: string) => {
    setQuestModalBusy(true);
    try {
      const response = await acceptQuest({ session_id: sessionId, quest_id: questId, config }, report);
      if (response.chat_feedback) {
        setAssistantOnly(response.chat_feedback);
      }
      setQuestState(response.quest_state);
      await runNarrativeChecks(response.quest.source === 'fate' ? 'fate_rule' : 'quest_rule');
    } catch (e) {
      setError(e instanceof Error ? e.message : '接受任务失败');
    } finally {
      setQuestModalBusy(false);
    }
  };

  const onRejectQuest = async (questId: string) => {
    setQuestModalBusy(true);
    try {
      const response = await rejectQuest({ session_id: sessionId, quest_id: questId, config }, report);
      if (response.chat_feedback) {
        setAssistantOnly(response.chat_feedback);
      }
      setQuestState(response.quest_state);
      await refreshNarrativeState(sessionId);
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '拒绝任务失败');
    } finally {
      setQuestModalBusy(false);
    }
  };

  const onTrackQuest = async (questId: string) => {
    try {
      const response = await trackQuest({ session_id: sessionId, quest_id: questId }, report);
      setQuestState(response.quest_state);
      if (response.chat_feedback) {
        setConfigHint(response.chat_feedback);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换当前任务失败');
    }
  };

  const onEvaluateQuest = async (questId: string) => {
    try {
      const response = await evaluateAllQuests({ session_id: sessionId, config }, report);
      setQuestState(response.quest_state);
      await refreshNarrativeState(sessionId);
      await refreshGameLogs(sessionId);
      const updated = response.quest_state.quests.find((item) => item.quest_id === questId);
      if (updated?.status === 'completed') {
        setAssistantOnly(`任务【${updated.title}】已完成。`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '任务判定失败');
    }
  };

  const onGenerateQuest = async () => {
    setAiWaitingText('正在生成任务...');
    setAiWaiting(true);
    try {
      const response = await debugGenerateQuest({ session_id: sessionId, config }, report);
      setQuestState(response.quest_state);
      await refreshNarrativeState(sessionId);
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成任务失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onGenerateFate = async () => {
    setAiWaitingText('正在生成命运线...');
    setAiWaiting(true);
    try {
      await generateFate({ session_id: sessionId, config }, report);
      await refreshNarrativeState(sessionId);
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成命运线失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onRegenerateFate = async () => {
    setAiWaitingText('正在重新生成命运线...');
    setAiWaiting(true);
    try {
      await regenerateFate({ session_id: sessionId, config }, report);
      await refreshNarrativeState(sessionId);
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新生成命运线失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onGenerateEncounter = async () => {
    setAiWaitingText('正在立刻生成遭遇...');
    setAiWaiting(true);
    try {
      const result = await checkEncounters({ session_id: sessionId, trigger_kind: 'debug_forced', config }, report);
      await Promise.all([refreshEncounterState(sessionId), refreshGameLogs(sessionId)]);
      if (result.generated) {
        const title = result.encounter?.title?.trim();
        setConfigHint(
          result.blocked_by_higher_priority_modal
            ? `遭遇已生成${title ? `：《${title}》` : ''}。当前有更高优先级弹窗，处理后会自动切入。`
            : `遭遇已生成${title ? `：《${title}》` : ''}。`,
        );
        return;
      }
      setConfigHint('未生成新遭遇：当前已有活跃遭遇，或排队遭遇已达到上限。');
    } catch (e) {
      setError(e instanceof Error ? e.message : '立即生成遭遇失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onShowConsistencyStatus = async () => {
    setConsistencyBusy(true);
    setConsistencyOpen(true);
    try {
      await refreshConsistencyData(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '读取一致性状态失败');
    } finally {
      setConsistencyBusy(false);
    }
  };

  const onRunConsistencyCheck = async () => {
    setConsistencyBusy(true);
    setConsistencyOpen(true);
    try {
      const result = await runConsistencyCheck(sessionId, report);
      await syncStateFromSave(sessionId);
      await refreshGameLogs(sessionId);
      await refreshConsistencyData(sessionId);
      setConfigHint(
        `一致性校验完成: ${result.changed ? '已修正状态' : '未发现需变更项'}，world_revision=${result.world_state.world_revision}，map_revision=${result.world_state.map_revision}，issue_count=${result.issue_count}`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '执行一致性校验失败');
    } finally {
      setConsistencyBusy(false);
    }
  };

  const onCloseEncounterModal = () => {
    if (encounterModalEncounterId) {
      announcedEncounterIdsRef.current.add(encounterModalEncounterId);
    }
    setEncounterModalEncounterId(null);
    forceReturnToMainChat('encounter_interrupt');
    focusMainActionInput();
  };

  const submitMainChatTurn = async ({
    actionDescription,
    speechDescription,
    actionCheckResult = null,
    passiveTurn = false,
    passiveMode = 'observe',
  }: {
    actionDescription: string;
    speechDescription: string;
    actionCheckResult?: ActionCheckResult | null;
    passiveTurn?: boolean;
    passiveMode?: 'observe';
  }) => {
    const structuredInput = buildStructuredPlayerInput(
      actionDescription,
      speechDescription,
      actionCheckResult,
      passiveTurn ? { passiveTurn: true, passiveMode } : undefined,
    );
    const nextMessages: ChatMessage[] = [{ role: 'user', content: structuredInput }];
    const speakReason = passiveTurn ? '自动推进' : '发言';
    setLastActionInput(passiveTurn ? '' : actionDescription);
    setLastSpeechInput(passiveTurn ? '' : speechDescription);
    setError('');
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };

    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;
      activeStreamRef.current = { kind: 'main' };
      let streamedSceneEvents: SceneEvent[] = [];
      let streamedReply = '';
      let rolledBack = false;
      setMainLiveProgress([]);
      setShowFoldedMainSceneEvents(false);

      setCurrentMainOutput({
        source_kind: 'main_turn',
        reply_text: '',
        scene_events: [],
        archived_sub_zone_turn_id: null,
        main_turn_summary: null,
        status: 'streaming',
      });

      try {
        await streamChat(
          {
            session_id: sessionId,
            config: effectiveConfig,
            messages: nextMessages,
          },
          {
            onDelta: (delta) => {
              streamedReply = `${streamedReply}${delta}`;
              setCurrentMainOutput((prev) =>
                prev
                  ? {
                      ...prev,
                      reply_text: streamedReply,
                      status: 'streaming',
                    }
                  : prev,
              );
            },
            onPhase: (event) => {
              setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
            },
            onToolUpdate: (event) => {
              setMainLiveProgress((prev) => upsertLiveProgress(prev, toToolProgressEntry(event)));
            },
            onRollback: (payload) => {
              rolledBack = true;
              handleStreamRollback(payload);
              window.alert(payload.message);
              setChatState('idle');
            },
            onReactionCheckRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              streamedSceneEvents = payload.scene_events_so_far;
              handlePendingReactionRequired({
                session_id: sessionId,
                pending_turn_id: payload.pending_turn_id,
                flow_kind: payload.flow_kind,
                status: 'awaiting_reaction',
                reply_text: payload.reply_so_far,
                scene_events: payload.scene_events_so_far,
                tool_events: [],
                pending_reaction: payload.pending_reaction,
                npc_role_id: payload.npc_role_id ?? null,
              });
            },
            onError: (message) => {
              setError(message);
              setCurrentMainOutput(null);
              setMainLiveProgress([]);
              activeStreamRef.current = null;
              if (!rolledBack) {
                window.alert('本轮生成已作废');
              }
              setChatState('idle');
            },
            onUsage: (usage) => {
              report({ endpoint: '/chat/stream', status: 200, ok: true, usage });
            },
            onTimeSpent: (minutes) => {
              pushTimeNotice(minutes, speakReason);
            },
            onToolEvents: (events) => {
              if (events.length > 0) {
                setConfigHint(`本轮触发工具调用 ${events.length} 次`);
                setDebugEntries((prev) => [
                  ...events.map((event) => ({
                    endpoint: `/tool/${event.tool_name}`,
                    status: event.ok ? 200 : 500,
                    ok: event.ok,
                    detail: event.summary,
                    at: new Date().toLocaleTimeString(),
                  })),
                  ...prev,
                ].slice(0, 20));
              }
            },
            onSceneEvents: (events) => {
              streamedSceneEvents = events;
            },
            onEnd: ({ archived_sub_zone_turn_id, main_turn_summary }) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              setMainLiveProgress([]);
              if (rolledBack) {
                return;
              }
              if (streamedReply && isAlreadyThereHint(streamedReply)) {
                showAlreadyTherePopup(streamedReply);
                setCurrentMainOutput(null);
              } else {
                setMainOutput('main_turn', streamedReply, streamedSceneEvents, {
                  archivedSubZoneTurnId: archived_sub_zone_turn_id ?? null,
                  mainTurnSummary: main_turn_summary ?? null,
                  status: 'awaiting_archive',
                });
              }
              if (!passiveTurn) {
                clearPlayerInput();
              }
              setChatState('idle');
              void (async () => {
                await syncEncounterLaneAfterSceneEvents(streamedSceneEvents);
                await refreshAreaSnapshot();
                await refreshTokenUsage(sessionId);
                await runNarrativeChecks('random_dialog');
                await syncStateFromSave(sessionId);
              })();
            },
          },
          controller.signal,
          report,
        );
      } catch (e) {
        abortRef.current = null;
        activeStreamRef.current = null;
        if (!controller.signal.aborted && !rolledBack) {
          setError(e instanceof Error ? e.message : '流式请求失败');
          setCurrentMainOutput(null);
          setMainLiveProgress([]);
          window.alert('本轮生成已作废');
          setChatState('idle');
        }
      }
      return;
    }

    setChatState('sending');
    try {
      const response = await sendChat(
        {
          session_id: sessionId,
          config: effectiveConfig,
          messages: nextMessages,
        },
        report,
      );
      if (isPendingTurnContinueResponse(response) && response.status === 'awaiting_reaction') {
        handlePendingReactionRequired(response);
        return;
      }
      if (!isChatTurnResponse(response)) {
        throw new Error('主聊天响应类型异常');
      }
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      setMainOutput('main_turn', response.reply.content, response.scene_events ?? [], {
        archivedSubZoneTurnId: response.archived_sub_zone_turn_id ?? null,
        mainTurnSummary: response.main_turn_summary ?? null,
        status: 'awaiting_archive',
      });
      if (!passiveTurn) {
        clearPlayerInput();
      }
      setCurrentZoneMetric(response.current_zone_metric ?? null);
      await refreshAreaSnapshot();
      pushTimeNotice(response.time_spent_min ?? 0, speakReason);
      if ((response.tool_events?.length ?? 0) > 0) {
        setConfigHint(`本轮触发工具调用 ${response.tool_events?.length ?? 0} 次`);
        setDebugEntries((prev) => [
          ...(response.tool_events ?? []).map((event) => ({
            endpoint: `/tool/${event.tool_name}`,
            status: event.ok ? 200 : 500,
            ok: event.ok,
            detail: event.summary,
            at: new Date().toLocaleTimeString(),
          })),
          ...prev,
        ].slice(0, 20));
      }
      await refreshTokenUsage(sessionId);
      await runNarrativeChecks('random_dialog');
      await syncStateFromSave(sessionId);
      setChatState('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
      setCurrentMainOutput((prev) => (prev?.source_kind === 'main_turn' ? { ...prev, status: 'error' } : prev));
      setChatState('error');
    }
  };

  const runPublicTurnEntry = async (entryType: PublicTurnEntryType, playerAction?: string) => {
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
    const finalizePublicTurnAfterResponse = async (sceneEvents: SceneEvent[]) => {
      await syncEncounterLaneAfterSceneEvents(sceneEvents);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    };

    setError('');
    setMainLiveProgress([]);
    setShowFoldedMainSceneEvents(false);
    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;
      activeStreamRef.current = { kind: 'main' };
      let streamedReply = '';
      let streamedSceneEvents: SceneEvent[] = [];
      let streamedImpacts: PublicTurnImpact[] = [];
      let streamedTurnState: PublicTurnState | null = null;
      let streamedPresentation: PublicTurnPresentation | null = null;
      let streamFailed = false;
      applyPublicTurnMainOutput({
        reply_text: '',
        scene_events: [],
        public_turn_state: livePublicTurnState ?? publicTurnState,
        public_turn_presentation: livePublicTurnPresentation ?? null,
        archived_sub_zone_turn_id: null,
        status: 'streaming',
      });
      try {
        await streamEnterPublicTurn(
          {
            session_id: sessionId,
            entry_type: entryType,
            player_action: playerAction,
            config: effectiveConfig,
          },
          {
            onPhase: (event) => {
              setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
            },
            onTurnState: (state) => {
              streamedTurnState = state;
              setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
            },
            onInitiativeOrder: (entries, meta) => {
              streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
              setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
            },
            onSettlementEntry: (entry) => {
              streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
              setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
            },
            onRoundNarrationDelta: (delta) => {
              streamedReply = `${streamedReply}${delta}`;
              setCurrentMainOutput((prev) =>
                prev
                  ? {
                      ...prev,
                      reply_text: streamedReply,
                      public_turn_presentation: withRoundNarration(streamedPresentation, delta),
                      status: 'streaming',
                    }
                  : prev,
              );
              streamedPresentation = withRoundNarration(streamedPresentation, delta);
            },
            onSceneEvent: (event) => {
              streamedSceneEvents = [...streamedSceneEvents, event];
              setCurrentMainOutput((prev) =>
                prev
                  ? {
                      ...prev,
                      scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                    }
                  : prev,
              );
            },
            onImpact: (impact) => {
              streamedImpacts = [...streamedImpacts, impact];
              setPublicTurnImpacts(streamedImpacts);
            },
            onInteractionRequired: (prompt) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePublicTurnInteractionRequired({
                ok: true,
                session_id: sessionId,
                phase: prompt.phase,
                narration: streamedReply,
                scene_events: streamedSceneEvents,
                reaction_check: null,
                public_interaction_prompt: prompt,
                public_opposed_prompt: null,
                round_completed: false,
                awaiting_entry: false,
                public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                archived_sub_zone_turn_id: null,
                impacts: streamedImpacts,
                player_action_check_result: null,
                presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
              });
            },
            onAttackResponseRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePendingAttackResponseRequired(
                buildPendingAttackResponseFromStream({
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  reply_so_far: payload.reply_so_far,
                  scene_events_so_far: payload.scene_events_so_far,
                  public_attack_prompt: payload.public_attack_prompt,
                  npc_role_id: payload.npc_role_id ?? null,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                }),
              );
            },
            onAttackDefenseRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePendingAttackDefenseRequired(
                buildPendingAttackDefenseFromStream({
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  reply_so_far: payload.reply_so_far,
                  scene_events_so_far: payload.scene_events_so_far,
                  public_attack_defense_prompt: payload.public_attack_defense_prompt,
                  npc_role_id: payload.npc_role_id ?? null,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                }),
              );
            },
            onReactionCheckRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePendingReactionRequired({
                session_id: sessionId,
                pending_turn_id: payload.pending_turn_id,
                flow_kind: payload.flow_kind,
                status: 'awaiting_reaction',
                reply_text: payload.reply_so_far,
                scene_events: payload.scene_events_so_far,
                tool_events: [],
                pending_reaction: payload.pending_reaction,
                public_turn_state: payload.public_turn_state ?? streamedTurnState,
                public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                npc_role_id: payload.npc_role_id ?? null,
              });
            },
            onOpposedCheckRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePendingOpposedRequired({
                session_id: sessionId,
                pending_turn_id: payload.pending_turn_id,
                flow_kind: payload.flow_kind,
                status: 'awaiting_opposed',
                reply_text: payload.reply_so_far,
                scene_events: payload.scene_events_so_far,
                tool_events: [],
                pending_reaction: null,
                public_opposed_prompt: payload.public_opposed_prompt,
                public_turn_state: payload.public_turn_state ?? streamedTurnState,
                public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                npc_role_id: payload.npc_role_id ?? null,
              });
            },
            onProtocolRepairRequired: (payload) => {
              abortRef.current = null;
              activeStreamRef.current = null;
              handlePublicTurnPendingResponse({
                session_id: sessionId,
                pending_turn_id: payload.pending_turn_id,
                flow_kind: payload.flow_kind,
                status: 'awaiting_protocol_repair',
                reply_text: payload.reply_so_far,
                scene_events: payload.scene_events_so_far,
                tool_events: [],
                public_turn_state: payload.public_turn_state ?? streamedTurnState,
                public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                npc_role_id: payload.npc_role_id ?? null,
                public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
              });
            },
            onError: (message) => {
              streamFailed = true;
              setError(message);
              setChatState('error');
              abortRef.current = null;
              activeStreamRef.current = null;
            },
            onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
              if (streamFailed) {
                return;
              }
              abortRef.current = null;
              activeStreamRef.current = null;
              setMainLiveProgress([]);
              applyPublicTurnMainOutput({
                reply_text: streamedReply,
                scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                public_turn_state: public_turn_state ?? streamedTurnState,
                public_turn_presentation: presentation ?? streamedPresentation,
                archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                status: round_completed ? 'awaiting_archive' : 'idle',
              });
              setChatState('idle');
            },
          },
          controller.signal,
          report,
        );
        if (streamFailed) {
          return;
        }
        if (playerAction) {
          clearPlayerInput();
        }
        await finalizePublicTurnAfterResponse(streamedSceneEvents);
      } catch (e) {
        abortRef.current = null;
        activeStreamRef.current = null;
        setError(e instanceof Error ? e.message : '公开回合失败');
        setChatState('error');
      }
      return;
    }

    try {
      setChatState('sending');
      const response = await enterPublicTurn(
        {
          session_id: sessionId,
          entry_type: entryType,
          player_action: playerAction,
          config: effectiveConfig,
        },
        report,
      );
      if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
        handlePublicTurnPendingResponse(response);
        if (playerAction) {
          clearPlayerInput();
        }
        return;
      }
      if (!isPublicTurnResponse(response)) {
        throw new Error('公开回合响应类型异常');
      }
      const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
      if (attackDefensePrompt) {
        applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
        openPendingAttackDefense(attackDefensePrompt);
      } else {
        const attackPrompt = findPendingPublicTurnAttackPrompt(response);
        if (attackPrompt) {
          applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
          openPendingAttackResponse(attackPrompt);
        } else if (findPendingPublicTurnInteractionPrompt(response)) {
          handlePublicTurnInteractionRequired(response);
        } else {
          applyPublicTurnResponse(response);
        }
      }
      if (playerAction) {
        clearPlayerInput();
      }
      await finalizePublicTurnAfterResponse(response.scene_events ?? []);
      setChatState('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : '公开回合失败');
      setChatState('error');
    }
  };

  const onStartNextPublicTurnRound = async () => {
    await runPublicTurnEntry('next_round');
  };

  const onStartPublicTurnInitiative = async () => {
    await runPublicTurnEntry('initiative');
  };

  const submitNpcChatTurn = async ({
    npcId,
    npcName,
    actionDescription,
    speechDescription,
    entryPoint,
    rememberDraft,
    clearDraft,
    closeConversation,
  }: {
    npcId: string;
    npcName: string;
    actionDescription: string;
    speechDescription: string;
    entryPoint: 'npc_chat' | 'teammate_chat';
    rememberDraft: (action: string, speech: string) => void;
    clearDraft: () => void;
    closeConversation: () => void;
  }) => {
    let validatedActionDescription = actionDescription;
    let validatedSpeechDescription = speechDescription;
    try {
      const validated = await performPlayerInputValidation({
        entryPoint,
        actorRoleId: playerStatic.player_id,
        actionText: actionDescription,
        speechText: speechDescription,
      });
      if (!validated) {
        return;
      }
      validatedActionDescription = validated.actionText;
      validatedSpeechDescription = validated.speechText;
    } catch (e) {
      setError(e instanceof Error ? e.message : '玩家输入校验失败');
      return;
    }
    if (!validatedActionDescription && !validatedSpeechDescription) {
      setError('校验建议后没有可提交内容，请直接修改输入。');
      return;
    }

    let actionCheckResult: ActionCheckResult | null = null;
    const shouldLeaveAfterReply = shouldLeaveNpcChatByIntent(validatedActionDescription, validatedSpeechDescription);
    try {
      actionCheckResult = await performActionCheckWithRoll({
        action_type: 'auto',
        action_prompt: buildNpcChatActionCheckPrompt(npcId, npcName, validatedActionDescription, validatedSpeechDescription),
        actor_role_id: playerStatic.player_id,
        source_context: 'npc_chat',
        post_close_output: 'suppress',
        resolution_context: 'embedded',
        skip_if_no_check: true,
      });
      if (actionCheckResult) {
        setLastActionResult(actionCheckResult);
        pushTimeNotice(actionCheckResult.time_spent_min, `NPC交互检定:${npcName}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NPC交互检定失败');
      return;
    }

    const structuredInput = buildStructuredPlayerInput(validatedActionDescription, validatedSpeechDescription, actionCheckResult);
    const previewInput = buildPreviewPlayerInput(validatedActionDescription, validatedSpeechDescription, actionCheckResult);
    rememberDraft(validatedActionDescription, validatedSpeechDescription);
    setError('');
    const speakReason = `发言:${npcName}`;

    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;
      const previousNpcMessages = npcChatMessages[npcId] ?? [];
      activeStreamRef.current = { kind: 'npc', npcId, previousMessages: previousNpcMessages };
      let rolledBack = false;
      let streamedNpcSceneEvents: SceneEvent[] = [];
      setNpcLiveProgress((prev) => ({ ...prev, [npcId]: [] }));
      setNpcChatMessages((prev) => {
        const current = prev[npcId] ?? [];
        return {
          ...prev,
          [npcId]: [...current, { role: 'user', content: previewInput }, { role: 'assistant', content: '' }],
        };
      });
      try {
        await streamNpcChat(
          {
            session_id: sessionId,
            npc_role_id: npcId,
            player_message: structuredInput,
            config,
          },
          {
            onDelta: (delta) => {
              setNpcChatMessages((prev) => {
                const current = [...(prev[npcId] ?? [])];
                if (current.length === 0) return prev;
                const last = current[current.length - 1];
                if (last.role !== 'assistant') return prev;
                current[current.length - 1] = { ...last, content: `${last.content}${delta}` };
                return { ...prev, [npcId]: current };
              });
            },
            onPhase: (event) => {
              setNpcLiveProgress((prev) => ({
                ...prev,
                [npcId]: upsertLiveProgress(prev[npcId] ?? [], toPhaseProgressEntry(event)),
              }));
            },
            onToolUpdate: (event) => {
              setNpcLiveProgress((prev) => ({
                ...prev,
                [npcId]: upsertLiveProgress(prev[npcId] ?? [], toToolProgressEntry(event)),
              }));
            },
            onRollback: (payload) => {
              rolledBack = true;
              handleStreamRollback(payload);
              window.alert(payload.message);
              setChatState('idle');
            },
            onReactionCheckRequired: (payload) => {
              abortRef.current = null;
              handlePendingReactionRequired({
                session_id: sessionId,
                pending_turn_id: payload.pending_turn_id,
                flow_kind: payload.flow_kind,
                status: 'awaiting_reaction',
                reply_text: payload.reply_so_far,
                scene_events: payload.scene_events_so_far,
                tool_events: [],
                pending_reaction: payload.pending_reaction,
                npc_role_id: payload.npc_role_id ?? npcId,
              });
            },
            onError: (message) => {
              setError(message);
              restoreAbortedNpcStream();
              activeStreamRef.current = null;
              if (!rolledBack) {
                clearNpcLiveProgress(npcId);
                window.alert('本轮生成已作废');
              }
              setChatState('idle');
            },
            onTimeSpent: (minutes) => {
              pushTimeNotice(minutes, speakReason);
            },
            onDialogueLogs: (logs) => {
              if (rolledBack) return;
              setNpcChatMessages((prev) => ({
                ...prev,
                [npcId]: (logs ?? []).map((item) => ({
                  role: item.speaker === 'player' ? 'user' : 'assistant',
                  content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
                })),
              }));
            },
            onSceneEvents: (events) => {
              streamedNpcSceneEvents = events;
            },
            onEnd: () => {
              abortRef.current = null;
              activeStreamRef.current = null;
              clearNpcLiveProgress(npcId);
              if (rolledBack) {
                return;
              }
              setChatState('idle');
              void (async () => {
                clearDraft();
                await syncEncounterLaneAfterSceneEvents(streamedNpcSceneEvents);
                await refreshTokenUsage(sessionId);
                await refreshNpcPool(npcPoolSearch);
                await runNarrativeChecks('random_dialog');
                if (shouldLeaveAfterReply) {
                  closeConversation();
                }
              })();
            },
          },
          controller.signal,
          report,
        );
      } catch (e) {
        abortRef.current = null;
        activeStreamRef.current = null;
        if (!controller.signal.aborted && !rolledBack) {
          restoreAbortedNpcStream();
          clearNpcLiveProgress(npcId);
          setError(e instanceof Error ? e.message : 'NPC流式聊天失败');
          window.alert('本轮生成已作废');
          setChatState('idle');
        }
      }
      return;
    }

    setChatState('sending');
    try {
      const response = await npcChat(
        {
          session_id: sessionId,
          npc_role_id: npcId,
          player_message: structuredInput,
          config,
        },
        report,
      );
      if (isPendingTurnContinueResponse(response) && response.status === 'awaiting_reaction') {
        handlePendingReactionRequired(response);
        return;
      }
      if (!isNpcTurnResponse(response)) {
        throw new Error('NPC 单聊响应类型异常');
      }
      setNpcChatMessages((prev) => ({
        ...prev,
        [npcId]: (response.dialogue_logs ?? []).map((item) => ({
          role: item.speaker === 'player' ? 'user' : 'assistant',
          content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
        })),
      }));
      clearDraft();
      pushTimeNotice(response.time_spent_min, speakReason);
      await refreshTokenUsage(sessionId);
      await refreshNpcPool(npcPoolSearch);
      await runNarrativeChecks('random_dialog');
      if (shouldLeaveAfterReply) {
        closeConversation();
      }
      setChatState('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NPC聊天失败');
      setChatState('error');
    }
  };

  const onSend = async () => {
    if (blockingWorkflowActive) return;
    const actionDescription = actionInput.trim();
    const speechDescription = speechInput.trim();
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
    const applyPublicTurnStreamState = (
      replyText: string,
      sceneEvents: SceneEvent[],
      status: MainOutputStatus = 'streaming',
      publicTurnRuntimeState?: PublicTurnState | null,
      publicTurnPresentation?: PublicTurnPresentation | null,
    ) => {
      applyPublicTurnMainOutput({
        reply_text: replyText,
        scene_events: sceneEvents,
        public_turn_state: publicTurnRuntimeState ?? livePublicTurnState ?? publicTurnState,
        public_turn_presentation: publicTurnPresentation ?? livePublicTurnPresentation ?? null,
        archived_sub_zone_turn_id: null,
        status,
      });
    };
    const finalizePublicTurnAfterResponse = async (sceneEvents: SceneEvent[]) => {
      await syncEncounterLaneAfterSceneEvents(sceneEvents);
      await refreshAreaSnapshot();
      await refreshGameLogs(sessionId);
      await syncStateFromSave(sessionId);
    };

    const onStartPublicTurn = async (entryType: PublicTurnEntryType, playerAction?: string) => {
      setError('');
      setMainLiveProgress([]);
      setShowFoldedMainSceneEvents(false);
      if (config.stream) {
        setChatState('streaming');
        const controller = new AbortController();
        abortRef.current = controller;
        activeStreamRef.current = { kind: 'main' };
        let streamedReply = '';
        let streamedSceneEvents: SceneEvent[] = [];
        let streamedImpacts: PublicTurnImpact[] = [];
        let streamedTurnState: PublicTurnState | null = null;
        let streamedPresentation: PublicTurnPresentation | null = null;
        let streamFailed = false;
        applyPublicTurnStreamState('', [], 'streaming');
        try {
          await streamEnterPublicTurn(
            {
              session_id: sessionId,
              entry_type: entryType,
              player_action: playerAction,
              config: effectiveConfig,
            },
            {
              onPhase: (event) => {
                setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
              },
              onTurnState: (state) => {
                streamedTurnState = state;
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
              },
              onInitiativeOrder: (entries, meta) => {
                streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
              },
              onSettlementEntry: (entry) => {
                streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
              },
              onRoundNarrationDelta: (delta) => {
                streamedReply = `${streamedReply}${delta}`;
                streamedPresentation = withRoundNarration(streamedPresentation, delta);
                applyPublicTurnStreamState(streamedReply, streamedSceneEvents, 'streaming', streamedTurnState, streamedPresentation);
              },
              onSceneEvent: (event) => {
                streamedSceneEvents = [...streamedSceneEvents, event];
                setCurrentMainOutput((prev) =>
                  prev
                    ? {
                        ...prev,
                        scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                      }
                    : prev,
                );
              },
              onImpact: (impact) => {
                streamedImpacts = [...streamedImpacts, impact];
                setPublicTurnImpacts(streamedImpacts);
              },
              onInteractionRequired: (prompt) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePublicTurnInteractionRequired({
                  ok: true,
                  session_id: sessionId,
                  phase: prompt.phase,
                  narration: streamedReply,
                  scene_events: streamedSceneEvents,
                  reaction_check: null,
                  public_interaction_prompt: prompt,
                  public_opposed_prompt: null,
                  round_completed: false,
                  awaiting_entry: false,
                  public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                  archived_sub_zone_turn_id: null,
                  impacts: streamedImpacts,
                  player_action_check_result: null,
                  presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                });
              },
              onAttackResponseRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingAttackResponseRequired(
                  buildPendingAttackResponseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_prompt: payload.public_attack_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  }),
                );
              },
              onAttackDefenseRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingAttackDefenseRequired(
                  buildPendingAttackDefenseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_defense_prompt: payload.public_attack_defense_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  }),
                );
              },
              onReactionCheckRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingReactionRequired({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_reaction',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  pending_reaction: payload.pending_reaction,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onOpposedCheckRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingOpposedRequired({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_opposed',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  pending_reaction: null,
                  public_opposed_prompt: payload.public_opposed_prompt,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onProtocolRepairRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePublicTurnPendingResponse({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_protocol_repair',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                  public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                  public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                });
              },
              onError: (message) => {
                streamFailed = true;
                setError(message);
                setChatState('error');
                abortRef.current = null;
                activeStreamRef.current = null;
              },
              onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
                if (streamFailed) {
                  return;
                }
                abortRef.current = null;
                activeStreamRef.current = null;
                setMainLiveProgress([]);
                applyPublicTurnMainOutput({
                  reply_text: streamedReply,
                  scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                  public_turn_state: public_turn_state ?? streamedTurnState,
                  public_turn_presentation: presentation ?? streamedPresentation,
                  archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                  status: round_completed ? 'awaiting_archive' : 'idle',
                });
                setChatState('idle');
              },
            },
            controller.signal,
            report,
          );
          if (streamFailed) {
            return;
          }
          if (playerAction) {
            clearPlayerInput();
          }
          await finalizePublicTurnAfterResponse(streamedSceneEvents);
        } catch (e) {
          abortRef.current = null;
          activeStreamRef.current = null;
          setError(e instanceof Error ? e.message : '公开回合失败');
          setChatState('error');
        }
        return;
      }

      try {
        setChatState('sending');
        const response = await enterPublicTurn(
          {
            session_id: sessionId,
            entry_type: entryType,
            player_action: playerAction,
            config: effectiveConfig,
          },
          report,
        );
        if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
          handlePublicTurnPendingResponse(response);
          if (playerAction) {
            clearPlayerInput();
          }
          return;
        }
        if (!isPublicTurnResponse(response)) {
          throw new Error('公开回合响应类型异常');
        }
        const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
        if (attackDefensePrompt) {
          applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
          openPendingAttackDefense(attackDefensePrompt);
          clearPlayerInput();
          return;
        }
        const attackPrompt = findPendingPublicTurnAttackPrompt(response);
        if (attackPrompt) {
          applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
          openPendingAttackResponse(attackPrompt);
          clearPlayerInput();
          return;
        }
        if (findPendingPublicTurnInteractionPrompt(response)) {
          handlePublicTurnInteractionRequired(response);
        } else {
          applyPublicTurnResponse(response);
        }
        if (playerAction) {
          clearPlayerInput();
        }
        await finalizePublicTurnAfterResponse(response.scene_events ?? []);
        setChatState('idle');
      } catch (e) {
        setError(e instanceof Error ? e.message : '公开回合失败');
        setChatState('error');
      }
    };

    const onSubmitPublicTurnAction = async () => {
      const speechOnlySubmission = playerSpeechOnlyInPublicTurn;
      if (!speechOnlySubmission && !actionDescription && !speechDescription) {
        setError('当前回合至少需要输入行为或语言。');
        return;
      }

      let validatedActionDescription = actionDescription;
      let validatedSpeechDescription = speechDescription;
      if (!speechOnlySubmission) {
        try {
          const validated = await performPlayerInputValidation({
            entryPoint: 'public_turn_action',
            actorRoleId: playerStatic.player_id,
            actionText: actionDescription,
            speechText: speechDescription,
          });
          if (!validated) {
            return;
          }
          validatedActionDescription = validated.actionText;
          validatedSpeechDescription = validated.speechText;
        } catch (e) {
          setError(e instanceof Error ? e.message : '玩家输入校验失败');
          return;
        }
      }
      if (!validatedActionDescription && !validatedSpeechDescription) {
        setError('校验建议后没有可提交内容，请直接修改输入。');
        return;
      }

      setLastActionInput(validatedActionDescription);
      setLastSpeechInput(validatedSpeechDescription);
      setError('');
      setMainLiveProgress([]);
      setShowFoldedMainSceneEvents(false);
      const sourcePhase = publicTurnRound?.awaiting_player_action_phase ?? publicTurnRound?.phase ?? publicTurnPhase;
      const actionSubmission = {
        actor_id: playerStatic.player_id,
        action_text: speechOnlySubmission ? '' : validatedActionDescription,
        speech_text: validatedSpeechDescription,
        source_phase: sourcePhase,
        forced_first: false,
      };
      const actionPrompt = speechOnlySubmission
        ? validatedSpeechDescription.trim()
        : [validatedActionDescription, validatedSpeechDescription].filter(Boolean).join('\n').trim();

      try {
        let playerActionCheck: PublicTurnPlayerActionCheck | null = null;
        if (!speechOnlySubmission) {
          setChatState('sending');
          const plan = await planActionCheck(
            {
              session_id: sessionId,
              action_type: 'auto',
              action_prompt: actionPrompt,
              actor_role_id: playerStatic.player_id,
              source_context: 'public_turn',
              config: effectiveConfig,
            },
            report,
          );
          playerActionCheck = buildPublicTurnPlayerActionCheck(plan, null);
          if (plan.requires_check) {
            if (plan.actor_kind !== 'player') {
              throw new Error('公开回合玩家行动检定规划异常');
            }
            pendingPublicTurnActionRef.current = {
              actionSubmission,
              playerActionCheck,
            };
            publicTurnActionResponseRef.current = null;
            setPublicTurnActionRollState({
              ...DEFAULT_ACTION_CHECK_ROLL_STATE,
              open: true,
              plan,
            });
            setChatState('idle');
            return;
          }
        }
        if (config.stream) {
          setChatState('streaming');
          const controller = new AbortController();
          abortRef.current = controller;
          activeStreamRef.current = { kind: 'main' };
          let streamedReply = '';
          let streamedSceneEvents: SceneEvent[] = [];
          let streamedImpacts: PublicTurnImpact[] = [];
          let streamedTurnState: PublicTurnState | null = null;
          let streamedPresentation: PublicTurnPresentation | null = null;
          let streamFailed = false;
          applyPublicTurnStreamState('', [], 'streaming');
          await streamContinuePublicTurn(
            {
              session_id: sessionId,
              action_submission: actionSubmission,
              player_action_check: playerActionCheck,
              config: effectiveConfig,
            },
            {
              onPhase: (event) => {
                setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
              },
              onTurnState: (state) => {
                streamedTurnState = state;
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_state: state } : prev));
              },
              onInitiativeOrder: (entries, meta) => {
                streamedPresentation = mergeInitiativeOrder(streamedPresentation, entries, meta);
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
              },
              onSettlementEntry: (entry) => {
                streamedPresentation = appendSettlementEntry(streamedPresentation, entry);
                setCurrentMainOutput((prev) => (prev ? { ...prev, public_turn_presentation: streamedPresentation } : prev));
              },
              onRoundNarrationDelta: (delta) => {
                streamedReply = `${streamedReply}${delta}`;
                streamedPresentation = withRoundNarration(streamedPresentation, delta);
                applyPublicTurnStreamState(streamedReply, streamedSceneEvents, 'streaming', streamedTurnState, streamedPresentation);
              },
              onSceneEvent: (event) => {
                streamedSceneEvents = [...streamedSceneEvents, event];
                setCurrentMainOutput((prev) =>
                  prev
                    ? {
                        ...prev,
                        scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                      }
                    : prev,
                );
              },
              onImpact: (impact) => {
                streamedImpacts = [...streamedImpacts, impact];
                setPublicTurnImpacts(streamedImpacts);
              },
              onInteractionRequired: (prompt) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePublicTurnInteractionRequired({
                  ok: true,
                  session_id: sessionId,
                  phase: prompt.phase,
                  narration: streamedReply,
                  scene_events: streamedSceneEvents,
                  reaction_check: null,
                  public_interaction_prompt: prompt,
                  public_opposed_prompt: null,
                  round_completed: false,
                  awaiting_entry: false,
                  public_turn_state: streamedTurnState ?? defaultPublicTurnState,
                  archived_sub_zone_turn_id: null,
                  impacts: streamedImpacts,
                  player_action_check_result: null,
                  presentation: streamedPresentation ?? emptyPublicTurnPresentation(),
                });
              },
              onAttackResponseRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingAttackResponseRequired(
                  buildPendingAttackResponseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_prompt: payload.public_attack_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  }),
                );
              },
              onAttackDefenseRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingAttackDefenseRequired(
                  buildPendingAttackDefenseFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    public_attack_defense_prompt: payload.public_attack_defense_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  }),
                );
              },
              onDeathSaveRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingDeathSaveRequired(
                  buildPendingDeathSaveFromStream({
                    pending_turn_id: payload.pending_turn_id,
                    flow_kind: payload.flow_kind,
                    reply_so_far: payload.reply_so_far,
                    scene_events_so_far: payload.scene_events_so_far,
                    death_save_prompt: payload.death_save_prompt,
                    npc_role_id: payload.npc_role_id ?? null,
                    public_turn_state: payload.public_turn_state ?? streamedTurnState,
                    public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  }),
                );
              },
              onReactionCheckRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingReactionRequired({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_reaction',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  pending_reaction: payload.pending_reaction,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onOpposedCheckRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePendingOpposedRequired({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_opposed',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  pending_reaction: null,
                  public_opposed_prompt: payload.public_opposed_prompt,
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onProtocolRepairRequired: (payload) => {
                abortRef.current = null;
                activeStreamRef.current = null;
                handlePublicTurnPendingResponse({
                  session_id: sessionId,
                  pending_turn_id: payload.pending_turn_id,
                  flow_kind: payload.flow_kind,
                  status: 'awaiting_protocol_repair',
                  reply_text: payload.reply_so_far,
                  scene_events: payload.scene_events_so_far,
                  tool_events: [],
                  public_turn_state: payload.public_turn_state ?? streamedTurnState,
                  public_turn_presentation: payload.public_turn_presentation ?? streamedPresentation,
                  npc_role_id: payload.npc_role_id ?? null,
                  public_turn_protocol_repair_notice: payload.public_turn_protocol_repair_notice,
                  public_turn_protocol_repair_request: payload.public_turn_protocol_repair_request,
                });
              },
              onError: (message) => {
                streamFailed = true;
                setError(message);
                setChatState('error');
                abortRef.current = null;
                activeStreamRef.current = null;
              },
              onEnd: ({ archived_sub_zone_turn_id, round_completed, public_turn_state, presentation }) => {
                if (streamFailed) {
                  return;
                }
                abortRef.current = null;
                activeStreamRef.current = null;
                setMainLiveProgress([]);
                applyPublicTurnMainOutput({
                  reply_text: streamedReply,
                  scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                  public_turn_state: public_turn_state ?? streamedTurnState,
                  public_turn_presentation: presentation ?? streamedPresentation,
                  archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                  status: round_completed ? 'awaiting_archive' : 'idle',
                });
                setChatState('idle');
              },
            },
            controller.signal,
            report,
          );
          if (!streamFailed) {
            clearPlayerInput();
            await finalizePublicTurnAfterResponse(streamedSceneEvents);
          }
          return;
        }

        setChatState('sending');
        const response = await continuePublicTurn(
          {
            session_id: sessionId,
            action_submission: actionSubmission,
            player_action_check: playerActionCheck,
            config: effectiveConfig,
          },
          report,
        );
        if (isPendingTurnContinueResponse(response) && response.status !== 'completed') {
          handlePublicTurnPendingResponse(response);
          clearPlayerInput();
          return;
        }
        if (!isPublicTurnResponse(response)) {
          throw new Error('公开回合响应类型异常');
        }
        const attackDefensePrompt = findPendingPublicTurnAttackDefensePrompt(response);
        if (attackDefensePrompt) {
          applyPublicTurnResponse(response, { status: 'awaiting_attack_defense', mergeImpacts: true });
          openPendingAttackDefense(attackDefensePrompt);
        } else if (findPendingPublicTurnAttackPrompt(response)) {
          applyPublicTurnResponse(response, { status: 'awaiting_attack_response', mergeImpacts: true });
          openPendingAttackResponse(findPendingPublicTurnAttackPrompt(response)!);
        } else if (findPendingPublicTurnInteractionPrompt(response)) {
          handlePublicTurnInteractionRequired(response);
        } else {
          applyPublicTurnResponse(response);
        }
        clearPlayerInput();
        await finalizePublicTurnAfterResponse(response.scene_events ?? []);
        setChatState('idle');
      } catch (e) {
        abortRef.current = null;
        activeStreamRef.current = null;
        setError(e instanceof Error ? e.message : '公开回合提交失败');
        setChatState('error');
      }
    };

    if (publicTurnEnabled) {
      if (publicTurnAwaitingPlayerAction) {
        await onSubmitPublicTurnAction();
        return;
      }
      if (publicTurnAwaitingEntry) {
        if (godMode && (actionDescription || speechDescription)) {
          await onStartPublicTurn('god_override', `${actionDescription}\n${speechDescription}`.trim());
          return;
        }
        setError('公开回合待机中，请使用“开始下一回合”或“优先行动”按钮。');
        return;
      }
      setError('当前公开回合阶段不接受直接输入。');
      return;
    }

    if (chatMode === 'npc' ? !actionDescription && !speechDescription : !actionDescription && !speechDescription) {
      setError(chatMode === 'npc' ? 'NPC 单聊至少需要输入动作或语言其中一项。' : '主聊天至少需要输入动作或语言其中一项。');
      return;
    }
    if (chatMode === 'npc' && activeNpcChat) {
      await submitNpcChatTurn({
        npcId: activeNpcChat.npcId,
        npcName: activeNpcChat.npcName,
        actionDescription,
        speechDescription,
        entryPoint: 'npc_chat',
        rememberDraft: (action, speech) => {
          setLastActionInput(action);
          setLastSpeechInput(speech);
        },
        clearDraft: clearPlayerInput,
        closeConversation: onLeaveNpcChat,
      });
      return;
    }

    let validatedActionDescription = actionDescription;
    let validatedSpeechDescription = speechDescription;
    try {
      const validated = await performPlayerInputValidation({
        entryPoint: 'main_chat',
        actorRoleId: playerStatic.player_id,
        actionText: actionDescription,
        speechText: speechDescription,
      });
      if (!validated) {
        return;
      }
      validatedActionDescription = validated.actionText;
      validatedSpeechDescription = validated.speechText;
    } catch (e) {
      setError(e instanceof Error ? e.message : '玩家输入校验失败');
      return;
    }
    if (!validatedActionDescription && !validatedSpeechDescription) {
      setError('校验建议后没有可提交内容，请直接修改输入。');
      return;
    }

    let actionCheckResult: ActionCheckResult | null = null;
    try {
      actionCheckResult = await performActionCheckWithRoll({
        action_type: 'auto',
        action_prompt: buildMainChatActionCheckPrompt(validatedActionDescription, validatedSpeechDescription),
        actor_role_id: playerStatic.player_id,
        source_context: 'main_chat',
        post_close_output: 'suppress',
        resolution_context: 'embedded',
        skip_if_no_check: true,
      });
      if (actionCheckResult) {
        setLastActionResult(actionCheckResult);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '主聊天检定失败');
      return;
    }
    await submitMainChatTurn({
      actionDescription: validatedActionDescription,
      speechDescription: validatedSpeechDescription,
      actionCheckResult,
    });
  };

  const onAutoAdvanceTurn = async () => {
    if (!canAutoAdvance) return;
    await submitMainChatTurn({ actionDescription: '', speechDescription: '', passiveTurn: true, passiveMode: 'observe' });
  };
  void onAutoAdvanceTurn;

  const onStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setCurrentMainOutput(null);
    restoreAbortedNpcStream();
    clearLiveProgress();
    activeStreamRef.current = null;
    setPendingReactionState(null);
    resetReactionCheckRollState();
    window.alert('本轮生成已作废');
    setChatState('idle');
  };

  const onRetry = () => {
    if (!lastActionInput && !lastSpeechInput) return;
    setActionInput(lastActionInput);
    setSpeechInput(lastSpeechInput);
  };

  const onRetryTeammateChat = () => {
    if (!teammateChatLastActionInput && !teammateChatLastSpeechInput) return;
    setTeammateChatActionInput(teammateChatLastActionInput);
    setTeammateChatSpeechInput(teammateChatLastSpeechInput);
  };

  const onSendTeammateChat = async () => {
    if (!activeTeammateChat || teammateChatSendDisabled) return;
    await submitNpcChatTurn({
      npcId: activeTeammateChat.npcId,
      npcName: activeTeammateChat.npcName,
      actionDescription: teammateChatActionInput.trim(),
      speechDescription: teammateChatSpeechInput.trim(),
      entryPoint: 'teammate_chat',
      rememberDraft: (action, speech) => {
        setTeammateChatLastActionInput(action);
        setTeammateChatLastSpeechInput(speech);
      },
      clearDraft: () => {
        setTeammateChatActionInput('');
        setTeammateChatSpeechInput('');
      },
      closeConversation: closeTeammateChatModal,
    });
  };

  const onClear = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    activeStreamRef.current = null;
    setPendingReactionState(null);
    resetReactionCheckRollState();
    setCurrentMainOutput(null);
    clearLiveProgress();
    setNpcChatMessages({});
    setChatMode('main');
    setActiveNpcChat(null);
    closeTeammateChatModal();
    setPlayerInputValidationPanelOpen(false);
    setPlayerInputValidationModalState(null);
    playerInputValidationPromiseRef.current = null;
    playerInputValidationBypassRef.current = null;
    setPlayerQuickActionOpen(false);
    setPlayerQuickActionMode('root');
    setInventoryOpen(false);
    setInventoryBusy(false);
    setTeamInventoryRole(null);
    setTeamProfileRole(null);
    setItemInteractionOpen(false);
    setItemInteractionBusy(false);
    setItemInteractionOwner(null);
    setItemInteractionItem(null);
    setItemInteractionPrompt('');
    setItemInteractionLastReply('');
    setQuestInspectOpen(false);
    setEncounterModalBusy(false);
    setEncounterModalEncounterId(null);
    clearPlayerInput();
    setLastActionInput('');
    setLastSpeechInput('');
    const nextSessionId = `sess_${Date.now()}`;
    setSessionId(nextSessionId);
    setTokenUsage({ ...EMPTY_TOKEN_USAGE, session_id: nextSessionId });
    setQuestState(defaultQuestState);
    setEncounterState(defaultEncounterState);
    setFateState(defaultFateState);
    setTeamState(defaultTeamState);
    setTeamChatReplies([]);
    setTeamChatBusy(false);
    setWorldState(defaultWorldState);
    setConsistencyIssues([]);
    setConsistencyIssueCount(0);
    setStorySnapshot(null);
    setTeamOpen(false);
    setConsistencyOpen(false);
    setError('');
    setChatState('idle');
    void refreshTokenUsage(nextSessionId);
  };

  const onEnableMap = () => setMapPromptDialogOpen(true);

  const onConfirmEnableMap = () => {
    const prompt = mapPromptInput.trim();
    setMapWorldPrompt(prompt);
    try {
      window.localStorage.setItem(MAP_PROMPT_STORAGE_KEY, prompt);
    } catch {
      // Ignore localStorage failures.
    }
    setMapSnapshot((prev) => ({ ...prev, zones: [] }));
    setMapRender(null);
    setMapEnabled(true);
    setMapPromptDialogOpen(false);
    setConfigHint('世界地图测试入口已启用。');
  };

  const onOpenPlayerPanel = () => {
    setPlayerPanelOpen(true);
  };

  const onOpenCharacterBuildPlayer = () => {
    if (playerBuildCompleted) {
      window.alert('当前存档的玩家已经完成构筑。如需重新创建，请先新建或清空存档。');
      return;
    }
    setCharacterBuildMode('player');
    setCharacterBuildOpen(true);
    setCompanionBuildOfferOpen(false);
  };

  const onOpenCharacterBuildCompanion = () => {
    if (!playerBuildCompleted) {
      window.alert('需要先完成玩家构筑，才能创建随从。');
      return;
    }
    setCharacterBuildMode('companion');
    setCharacterBuildOpen(true);
    setCompanionBuildOfferOpen(false);
  };

  const onCharacterBuildCompleted = async (
    result: CharacterBuildPlayerCompleteResponse | CharacterBuildCompanionCompleteResponse,
  ) => {
    setCharacterBuildOpen(false);
    if ('player' in result) {
      setPlayerStaticState(result.player);
    } else {
      setNpcPoolItems((current) => [...current, result.role]);
      setNpcPoolTotal((current) => current + 1);
      setTeamState((current) => ({
        ...current,
        members: [...current.members, result.member],
        updated_at: new Date().toISOString(),
      }));
    }
    await syncStateFromSave(sessionId);
    const nextState = await refreshCharacterBuildState(sessionId, { openForcedModal: false });
    if ('player' in result) {
      setCompanionBuildOfferOpen(Boolean(nextState?.companion_offer_pending));
    }
  };

  const onDismissCompanionBuildOffer = async (accept: boolean) => {
    setCompanionBuildOfferOpen(false);
    try {
      const nextState = await markCharacterBuildCompanionOfferSeen({ session_id: sessionId, seen: true }, report);
      setCharacterBuildState(nextState);
      if (accept) {
        setCharacterBuildMode('companion');
        setCharacterBuildOpen(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '随从构筑提示更新失败');
    }
  };

  const onOpenInventory = () => {
    setInventoryOpen(true);
  };

  const onOpenPlayerQuickAction = () => {
    setPlayerQuickActionMode('root');
    setPlayerQuickActionOpen(true);
  };

  const onOpenCurrentQuest = () => {
    if (!currentQuest) return;
    setQuestInspectOpen(true);
  };

  const onOpenFatePanel = () => {
    setFatePanelOpen(true);
  };

  const onOpenTeamPanel = async () => {
    setTeamOpen(true);
    await refreshTeamState(sessionId);
    setNpcPoolSearch('');
    await refreshNpcPool('');
  };

  const refreshNpcPool = async (query: string = npcPoolSearch) => {
    try {
      const resp = await getRolePool(sessionId, query, 200, report);
      setNpcPoolItems(resp.items);
      setNpcPoolTotal(resp.total);
      if (resp.items.length === 0) {
        setNpcSelected(null);
      } else if (!npcSelected || !resp.items.some((item) => item.role_id === npcSelected.role_id)) {
        setNpcSelected(resp.items[0]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NPC角色池加载失败');
    }
  };

  const onOpenNpcPool = async () => {
    setNpcPoolOpen(true);
    await refreshNpcPool('');
  };

  const onGenerateDebugTeamMember = async () => {
    // 首先询问用户是选择保留的角色还是生成新角色
    const choice = window.confirm(
      '生成调试队友：\n\n点击"确定"：使用已保留的角色\n点击"取消"：生成新角色'
    );

    if (choice) {
      // 使用保留的角色
      try {
        const retainedResponse = await getRetainedNpcs(report);
        const npcs = retainedResponse.npcs || [];

        if (npcs.length === 0) {
          window.alert('没有保留的角色，请先生成并保留一个角色。');
          return;
        }

        // 构建选择列表
        const options = npcs.map((npc, index) => `${index + 1}. ${npc.name}${npc.notes ? ` (${npc.notes})` : ''}`).join('\n');
        const input = window.prompt(`选择要使用的保留角色（输入编号）：\n\n${options}`);

        if (!input || !input.trim()) return;

        const selectedIndex = parseInt(input.trim(), 10) - 1;
        if (isNaN(selectedIndex) || selectedIndex < 0 || selectedIndex >= npcs.length) {
          window.alert('无效的选择');
          return;
        }

        const selectedNpc = npcs[selectedIndex];

        setAiWaitingText('正在从保留角色生成队友...');
        setAiWaiting(true);

        const response = await generateFromRetained(
          selectedNpc.retained_id,
          { session_id: sessionId },
          report
        );

        setTeamState(response.team_state ?? defaultTeamState);
        setTeamChatReplies([]);
        await refreshNpcPool(npcPoolSearch);
        setTeamOpen(true);
        setConfigHint(response.chat_feedback || `保留角色 ${selectedNpc.name} 已加入队伍。`);
      } catch (e) {
        setError(e instanceof Error ? e.message : '从保留角色生成队友失败');
      } finally {
        setAiWaiting(false);
      }
    } else {
      // 生成新角色
      const prompt = window.prompt('输入用于生成调试队友的描述');
      if (!prompt || !prompt.trim()) return;
      setAiWaitingText('正在生成调试队友...');
      setAiWaiting(true);
      try {
        const response = await generateDebugTeammate({ session_id: sessionId, prompt: prompt.trim(), config }, report);
        setTeamState(response.team_state ?? defaultTeamState);
        setTeamChatReplies([]);
        await refreshNpcPool(npcPoolSearch);
        setTeamOpen(true);
        setConfigHint(response.chat_feedback || '调试队友已加入队伍。');
      } catch (e) {
        setError(e instanceof Error ? e.message : '生成调试队友失败');
      } finally {
        setAiWaiting(false);
      }
    }
  };

  const onInviteNpcToTeam = async (roleId: string, npcName: string) => {
    const playerPrompt = window.prompt(`你想如何邀请 ${npcName} 加入队伍？`, '一起行动，彼此照应。') ?? '';
    try {
      const response = await inviteNpcToTeam(
        {
          session_id: sessionId,
          npc_role_id: roleId,
          player_prompt: playerPrompt,
          config,
        },
        report,
      );
      setTeamState(response.team_state ?? defaultTeamState);
      setTeamChatReplies([]);
      await refreshNpcPool(npcPoolSearch);
      setConfigHint(response.chat_feedback || (response.accepted ? `${npcName} 已加入队伍。` : `${npcName} 拒绝加入队伍。`));
      if (response.accepted) {
        setTeamOpen(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '邀请NPC入队失败');
    }
  };

  const onLeaveTeamMember = async (roleId: string) => {
    try {
      const response = await leaveNpcFromTeam({ session_id: sessionId, npc_role_id: roleId, reason: 'manual', config }, report);
      setTeamState(response.team_state ?? defaultTeamState);
      setTeamChatReplies([]);
      await refreshNpcPool(npcPoolSearch);
      setConfigHint(response.chat_feedback || '队友已离队。');
    } catch (e) {
      setError(e instanceof Error ? e.message : '队友离队失败');
    }
  };

  const onRetainTeamMember = async (roleId: string, npcName: string) => {
    try {
      const notes = window.prompt(`为 ${npcName} 添加保留备注（可选）`) ?? '';
      const response = await retainNpc({ session_id: sessionId, role_id: roleId, notes }, report);
      try {
        const role = await getRoleCard(sessionId, roleId, report);
        replaceCachedRoleCard(role);
      } catch {
        // Ignore stale role refresh failures after retain.
      }
      setConfigHint(response.message || `${npcName} 已保留到账户中。`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '保留队友失败');
    }
  };

  const onTeamChat = async (playerMessage: string) => {
    try {
      setTeamChatBusy(true);
      const response = await sendTeamChat({ session_id: sessionId, player_message: playerMessage, config }, report);
      setTeamState(response.team_state ?? defaultTeamState);
      setTeamChatReplies(response.replies ?? []);
      setConfigHint('队伍聊天已发送。');
      pushTimeNotice(response.time_spent_min, '队伍聊天');
    } catch (e) {
      setError(e instanceof Error ? e.message : '队伍聊天发送失败');
    } finally {
      setTeamChatBusy(false);
    }
  };

  const onInspectTeamInventory = async (roleId: string) => {
    try {
      const role = await getRoleCard(sessionId, roleId, report);
      replaceCachedRoleCard(role);
      setTeamInventoryRole(role);
    } catch (e) {
      setError(e instanceof Error ? e.message : '队友背包读取失败');
    }
  };

  const onInspectTeamProfile = async (roleId: string) => {
    try {
      const role = await getRoleCard(sessionId, roleId, report);
      replaceCachedRoleCard(role);
      setTeamProfileRole(role);
    } catch (e) {
      setError(e instanceof Error ? e.message : '队友属性读取失败');
    }
  };

  const onOpenTeammateChatModal = async (npcId: string, npcName: string) => {
    if (chatMode === 'npc') {
      onLeaveNpcChat();
    }
    setError('');
    setActiveTeammateChat({ npcId, npcName });
    setTeammateChatActionInput('');
    setTeammateChatSpeechInput('');
    setTeammateChatLastActionInput('');
    setTeammateChatLastSpeechInput('');
    await ensureNpcChatHistoryLoaded(npcId, npcName);
  };

  const onOpenActionPanel = async () => {
    setActionPanelOpen(true);
    await refreshNpcPool('');
  };

  const onOpenPlayerInputValidationPanel = async () => {
    setPlayerInputValidationPanelOpen(true);
    await refreshNpcPool('');
  };

  const onSelectNpcRole = async (roleId: string) => {
    try {
      const role = await getRoleCard(sessionId, roleId, report);
      setNpcSelected(role);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NPC角色卡读取失败');
    }
  };

  const onSearchNpcPool = (next: string) => {
    setNpcPoolSearch(next);
    void refreshNpcPool(next);
  };

  const onRunActionCheck = async (payload: { action_type: 'attack' | 'check' | 'item_use'; action_prompt: string; actor_role_id?: string }) => {
    try {
      const result = await performActionCheckWithRoll({
        ...payload,
        source_context: 'action_panel',
        post_close_output: 'main_chat',
        resolution_context: 'standalone',
      });
      if (!result) return;
      setLastActionResult(result);
      await publishActionCheckOutcome(result, 'action_panel', 'main_chat');
      pushTimeNotice(result.time_spent_min, '行为检定');
      await refreshNpcPool(npcPoolSearch);
      await runNarrativeChecks('quest_rule');
    } catch (e) {
      setError(e instanceof Error ? e.message : '行为检定失败');
    }
  };

  const refreshAreaSnapshot = async () => {
    const area = await getCurrentArea(sessionId, report);
    setAreaSnapshot(area.area_snapshot);
    try {
      const save = await getCurrentSave(report);
      if (save.session_id === sessionId) {
        setCurrentReputation(selectCurrentReputation(save));
      }
    } catch {
      // Ignore reputation refresh failures.
    }
  };

  const refreshTemplateLibraryStatus = async () => {
    try {
      const status = await getTemplateLibraryStatus(sessionId, report);
      setTemplateLibraryStatus(status);
    } catch {
      // Ignore template library status failures during passive refresh.
    }
  };

  const onInitAreaClock = async () => {
    try {
      await initWorldClock({ session_id: sessionId, calendar: 'fantasy_default' }, report);
      await refreshAreaSnapshot();
    } catch (e) {
      setError(e instanceof Error ? e.message : '初始化时钟失败');
    }
  };

  const onMoveSubZone = async (subZoneId: string) => {
    try {
      setAiWaitingText('正在等待 AI 生成子区块移动反馈...');
      setAiWaiting(true);
      const moved = await moveToSubZone({ session_id: sessionId, to_sub_zone_id: subZoneId, config }, report);
      setAssistantOnly(moved.movement_feedback);
      pushTimeNotice(moved.duration_min, '子区块移动');
      applyMapStateSync(moved.state_sync, sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '子区块移动失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onDiscoverAreaInteraction = async (subZoneId: string, intent: string) => {
    try {
      const discovered = await discoverAreaInteractions(
        { session_id: sessionId, sub_zone_id: subZoneId, intent, config },
        report,
      );
      setConfigHint(`发现 ${discovered.new_interactions.length} 个新交互`);
      applyMapStateSync(discovered.state_sync, sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '发现交互失败');
    }
  };

  const inferSceneActionKind = (prompt: string): string => {
    const text = prompt.trim();
    if (!text) return 'inspect';
    if (/(拾起|拿起|捡起|收起|带走|pickup|take)/i.test(text)) return 'pickup';
    if (/(打开|搜索|翻找|open|search)/i.test(text)) return text.includes('搜索') || /search/i.test(text) ? 'search' : 'open';
    if (/(全部拿走|take all)/i.test(text)) return 'take_all';
    if (/(放进|塞进|put in)/i.test(text)) return 'put_in';
    if (/(装备|穿上|拿在手里|equip)/i.test(text)) return 'equip';
    if (/(丢下|drop)/i.test(text)) return 'drop';
    if (/(交给|give)/i.test(text)) return 'give';
    if (/(使用|use)/i.test(text)) return 'use';
    if (/(触发|拉下|按下|trigger)/i.test(text)) return 'trigger';
    if (/(重置|reset)/i.test(text)) return 'reset';
    if (/(解除|disable|拆除)/i.test(text)) return 'disable';
    if (/(进入|穿过|通过|enter)/i.test(text)) return 'enter';
    if (/(强行打开|force)/i.test(text)) return 'force_open';
    if (/(点燃|ignite)/i.test(text)) return 'ignite';
    if (/(利用|exploit)/i.test(text)) return 'exploit';
    if (/(解除陷阱|拆陷阱|disarm)/i.test(text)) return 'disarm';
    if (/(收集证据|取证|collect evidence)/i.test(text)) return 'collect_evidence';
    if (/(标记|mark)/i.test(text)) return 'mark';
    if (/(给npc看|展示|show)/i.test(text)) return 'show_to_npc';
    return 'inspect';
  };

  const onUseAreaItem = async (interactionId: string, itemName: string) => {
    if (encounterEngaged) {
      setError('遭遇进行中，请直接在主聊天描述动作或发言。');
      return;
    }
    const prompt = window.prompt(`你想如何使用/观察【${itemName}】？`);
    if (!prompt || !prompt.trim()) return;
    try {
      const actionKind = inferSceneActionKind(prompt);
      const response = await executeAreaInteraction(
        {
          session_id: sessionId,
          interaction_id: interactionId,
          action_kind: actionKind,
          actor_kind: 'player',
          prompt: prompt.trim(),
          config,
        },
        report,
      );
      applyMapStateSync(response.state_sync, sessionId);
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      setMainOutput('system_output', response.reply || response.message, response.scene_events ?? []);
      pushTimeNotice(1, `场景交互:${itemName}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '物品使用失败');
    }
  };

  const onEnterNpcChat = async (npcId: string, npcName: string) => {
    if (encounterEngaged) {
      setError('遭遇进行中，请直接在主聊天描述动作或发言。');
      return;
    }
    setChatMode('npc');
    setActiveNpcChat({ npcId, npcName });
    clearPlayerInput();
    setError('');
    await ensureNpcChatHistoryLoaded(npcId, npcName);
  };

  const onLeaveNpcChat = () => {
    if (activeNpcChat) {
      clearNpcLiveProgress(activeNpcChat.npcId);
    }
    forceReturnToMainChat('manual');
    setError('');
  };

  const openItemInteraction = (
    owner: InventoryOwnerRef,
    mode: 'inspect' | 'use',
    itemId: string,
    itemName: string,
  ) => {
    setItemInteractionOwner(owner);
    setItemInteractionMode(mode);
    setItemInteractionItem({ itemId, itemName });
    setItemInteractionPrompt('');
    setItemInteractionLastReply('');
    setItemInteractionOpen(true);
  };

  const onEquipInventory = async (owner: InventoryOwnerRef, itemId: string, slot: 'weapon' | 'armor') => {
    try {
      setInventoryBusy(true);
      const response = await equipInventoryItem({ session_id: sessionId, owner, item_id: itemId, slot }, report);
      if (response.player) setPlayerStaticState(response.player);
      if (response.role) replaceCachedRoleCard(response.role);
      setConfigHint(response.message || '装备已更新。');
      await refreshTeamState(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '装备物品失败');
    } finally {
      setInventoryBusy(false);
    }
  };

  const onUnequipInventory = async (owner: InventoryOwnerRef, slot: 'weapon' | 'armor') => {
    try {
      setInventoryBusy(true);
      const response = await unequipInventoryItem({ session_id: sessionId, owner, slot }, report);
      if (response.player) setPlayerStaticState(response.player);
      if (response.role) replaceCachedRoleCard(response.role);
      setConfigHint(response.message || '装备已更新。');
      await refreshTeamState(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '卸下物品失败');
    } finally {
      setInventoryBusy(false);
    }
  };

  const onSubmitItemInteraction = async () => {
    if (!itemInteractionOwner || !itemInteractionItem) return;
    try {
      setItemInteractionBusy(true);
      forceReturnToMainChat('narrative_switch');
      let actionCheckResult: ActionCheckResult | null = null;
      if (itemInteractionMode === 'use') {
        actionCheckResult = await performActionCheckWithRoll({
          action_type: 'item_use',
          action_prompt: `owner_type=${itemInteractionOwner.owner_type}; role_id=${itemInteractionOwner.role_id ?? playerStatic.player_id}; item_id=${itemInteractionItem.itemId}; item_name=${itemInteractionItem.itemName}; prompt=${itemInteractionPrompt.trim() || '-'}`,
          actor_role_id: itemInteractionOwner.owner_type === 'role' ? (itemInteractionOwner.role_id ?? undefined) : playerStatic.player_id,
          source_context: 'inventory_item',
          post_close_output: 'suppress',
          resolution_context: 'embedded',
          skip_if_no_check: false,
          return_state_sync: true,
          post_trigger_kind: 'quest_rule',
        });
        if (actionCheckResult) {
          setLastActionResult(actionCheckResult);
        }
      }
      const response = await interactInventoryItem(
        {
          session_id: sessionId,
          owner: itemInteractionOwner,
          item_id: itemInteractionItem.itemId,
          mode: itemInteractionMode,
          prompt: itemInteractionPrompt.trim(),
          action_check: actionCheckResult,
          config,
        },
        report,
      );
      if (response.player) setPlayerStaticState(response.player);
      if (response.role) replaceCachedRoleCard(response.role);
      setItemInteractionLastReply(response.reply);
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      setMainOutput('system_output', response.reply, response.scene_events ?? []);
      pushTimeNotice(
        response.time_spent_min,
        `${itemInteractionMode === 'inspect' ? '观察物品' : '使用物品'}:${itemInteractionItem.itemName}`,
      );
      setItemInteractionOpen(false);
      if (response.mode === 'use') {
        if (actionCheckResult?.state_sync) {
          const mergedRolePool = response.role
            ? [response.role, ...actionCheckResult.state_sync.role_pool.filter((item) => item.role_id !== response.role?.role_id)]
            : actionCheckResult.state_sync.role_pool;
          applyMapStateSync(
            {
              ...actionCheckResult.state_sync,
              player_static_data: response.player ?? actionCheckResult.state_sync.player_static_data,
              role_pool: mergedRolePool,
            },
            actionCheckResult.session_id,
          );
        } else {
          await runNarrativeChecks('quest_rule');
        }
      } else {
        await syncStateFromSave(sessionId);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '物品交互失败');
    } finally {
      setItemInteractionBusy(false);
    }
  };

  const onSavePlayerStatic = async (next: PlayerStaticData) => {
    try {
      const payload: PlayerStaticData = {
        player_id: next.player_id.trim() || defaultPlayerStaticData.player_id,
        name: next.name.trim() || defaultPlayerStaticData.name,
        age: Math.max(0, Math.floor(next.age || defaultPlayerStaticData.age)),
        height_cm: Math.max(50, Math.floor(next.height_cm || defaultPlayerStaticData.height_cm)),
        body_type: next.body_type ?? defaultPlayerStaticData.body_type,
        appearance: next.appearance ?? defaultPlayerStaticData.appearance,
        portrait: next.portrait ?? defaultPlayerStaticData.portrait,
        build_archive_id: next.build_archive_id ?? defaultPlayerStaticData.build_archive_id,
        move_speed_mph: Math.max(1, Math.floor(next.move_speed_mph || 1)),
        role_type: next.role_type || defaultPlayerStaticData.role_type,
        dnd5e_sheet: next.dnd5e_sheet || defaultPlayerStaticData.dnd5e_sheet,
      };
      const saved = await setPlayerStatic(sessionId, payload, report);
      setPlayerStaticState(saved);

      const runtimePayload: PlayerRuntimeData = {
        ...playerRuntime,
        session_id: sessionId,
      };
      const runtimeSaved = await setPlayerRuntime(sessionId, runtimePayload, report);
      setPlayerRuntimeState(runtimeSaved);
      setPlayerPanelOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存玩家数据失败');
    }
  };

  const ensureMap = async (forceRegenerate = false) => {
    const snapshot = mapSnapshot;
    setAiWaitingText('正在等待 AI 生成地图区块...');
    setAiWaiting(true);
    try {
      const generated = await bootstrapWorldMap(
        {
          session_id: sessionId,
          config,
          player_position: snapshot.player_position ?? DEFAULT_POSITION,
          desired_count: 6,
          max_count: 10,
          world_prompt: mapWorldPrompt,
          force_regenerate: forceRegenerate,
        },
        report,
      );
      applyMapStateSync(generated.state_sync, sessionId);
      if (generated.narration.text) {
        setConfigHint(generated.narration.text);
      }
      await refreshTokenUsage(sessionId);
    } finally {
      setAiWaiting(false);
    }
  };

  const onFillTemplateLibrary = async () => {
    setAiWaitingText('正在请求 AI 补全模板库...');
    setAiWaiting(true);
    try {
      const response = await fillTemplateLibrary({ session_id: sessionId, fill_scope: 'all', config }, report);
      setTemplateLibraryStatus(response);
      setConfigHint(
        `模板库已更新：新增 物品${response.appended_item_definition_ids.length} / 装备${response.appended_equipment_definition_ids.length} / 法术${response.appended_spell_definition_ids.length} / 武技${response.appended_war_art_definition_ids.length} / 交互${response.appended_interactable_template_ids.length}，补空字段 ${response.updated_item_definition_ids.length + response.updated_equipment_definition_ids.length + response.updated_spell_definition_ids.length + response.updated_war_art_definition_ids.length + response.updated_interactable_template_ids.length} 处。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 填充模板库失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onRunPlayerInputValidation = async (payload: { actor_role_id?: string; action_text: string; speech_text: string }) => {
    try {
      setPlayerInputValidationDebugBusy(true);
      const result = await validatePlayerInput(
        {
          session_id: sessionId,
          entry_point: 'debug_panel',
          action_text: payload.action_text,
          speech_text: payload.speech_text,
          actor_role_id: payload.actor_role_id ?? playerStatic.player_id,
          config,
        },
        report,
      );
      setLastPlayerInputValidationResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : '玩家输入校验失败');
    } finally {
      setPlayerInputValidationDebugBusy(false);
    }
  };

  const onRunActionCheckFromPlayerInputValidation = async (payload: { actor_role_id?: string; action_prompt: string }) => {
    try {
      const result = await performActionCheckWithRoll({
        action_type: 'auto',
        action_prompt: payload.action_prompt,
        actor_role_id: payload.actor_role_id,
        source_context: 'action_panel',
        post_close_output: 'main_chat',
        resolution_context: 'standalone',
      });
      if (!result) return;
      setLastActionResult(result);
      await publishActionCheckOutcome(result, 'action_panel', 'main_chat');
      pushTimeNotice(result.time_spent_min, '玩家输入校验后检定');
      await refreshNpcPool(npcPoolSearch);
      await runNarrativeChecks('debug_forced');
    } catch (e) {
      setError(e instanceof Error ? e.message : '行为检定失败');
    }
  };

  const onFillSpellLibrary = async () => {
    const raw = window.prompt('要让 AI 追加/补全多少条法术定义？(1-100)', '20');
    if (raw === null) return;
    const spellFillCount = Number.parseInt(raw.trim(), 10);
    if (!Number.isFinite(spellFillCount) || spellFillCount < 1 || spellFillCount > 100) {
      setError('法术填充数量必须是 1 到 100 之间的整数。');
      return;
    }
    setAiWaitingText('正在请求 AI 填充法术表...');
    setAiWaiting(true);
    try {
      const response = await fillTemplateLibrary(
        { session_id: sessionId, fill_scope: 'spells', spell_fill_count: spellFillCount, config },
        report,
      );
      setTemplateLibraryStatus(response);
      setConfigHint(
        `法术表已更新：新增 ${response.appended_spell_definition_ids.length} 条，补空字段 ${response.updated_spell_definition_ids.length} 处，当前法术定义总数 ${response.spell_definition_count}。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 填充法术表失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const syncBattleState = (battle: BattleSandboxState | null) => {
    setActiveBattle(battle);
    if (!battle?.pending_roll) {
      resetBattleRollState();
      return;
    }
    openBattleRollModal(battle);
  };

  const onOpenBattleStart = () => {
    setBattleStartDialogOpen(true);
  };

  const onConfirmBattleStart = async (payload: {
    mode: 'template' | 'ai_generated';
    template_group?: string | null;
    ai_scale: 'single' | 'squad';
    ai_strength: 'weak' | 'standard' | 'strong';
    ai_pacing: 'step' | 'auto';
    config?: AppConfig | null;
  }) => {
    try {
      setBattleStartBusy(true);
      const response = await startDebugBattle(
        {
          session_id: sessionId,
          mode: payload.mode,
          template_group: payload.template_group ?? null,
          ai_scale: payload.ai_scale,
          ai_strength: payload.ai_strength,
          ai_pacing: payload.ai_pacing,
          config: payload.config ?? null,
        },
        report,
      );
      setBattleStartDialogOpen(false);
      syncBattleState(response.battle);
      setConfigHint('战斗测试已启动。');
    } catch (e) {
      setError(e instanceof Error ? e.message : '启动战斗测试失败');
    } finally {
      setBattleStartBusy(false);
    }
  };

  const onBattleAction = async (payload: {
    action_kind: 'attack' | 'defend' | 'move' | 'disengage' | 'escape' | 'use_item' | 'observe' | 'end_turn';
    target_combatant_id?: string | null;
    destination_band?: 'engaged' | 'near' | 'far' | 'remote' | null;
    item_id?: string | null;
  }) => {
    if (!activeBattle) return;
    try {
      setBattleBusy(true);
      const response = await submitBattlePlayerAction(
        activeBattle.battle_id,
        {
          session_id: sessionId,
          action_kind: payload.action_kind,
          target_combatant_id: payload.target_combatant_id ?? null,
          destination_band: payload.destination_band ?? null,
          item_id: payload.item_id ?? null,
        },
        report,
      );
      syncBattleState(response.battle);
    } catch (e) {
      setError(e instanceof Error ? e.message : '战斗动作提交失败');
    } finally {
      setBattleBusy(false);
    }
  };

  const onBattleContinueAi = async (aiPacing: 'step' | 'auto') => {
    if (!activeBattle) return;
    try {
      setBattleBusy(true);
      const response = await continueBattleAi(activeBattle.battle_id, { session_id: sessionId, ai_pacing: aiPacing }, report);
      syncBattleState(response.battle);
    } catch (e) {
      setError(e instanceof Error ? e.message : '推进 AI 行动失败');
    } finally {
      setBattleBusy(false);
    }
  };

  const onSetBattleAiPacing = (aiPacing: 'step' | 'auto') => {
    setActiveBattle((prev) => (prev ? { ...prev, ui_flags: { ...prev.ui_flags, ai_pacing: aiPacing } } : prev));
  };

  const onTriggerBattleRoll = () => {
    if (battleRollState.phase !== 'ready' || !activeBattle?.pending_roll) return;
    const prompt = activeBattle.pending_roll;
    const rollValue = Math.floor(Math.random() * 20) + 1;
    const rotation = {
      x: Math.floor(Math.random() * 720),
      y: Math.floor(Math.random() * 720),
      z: Math.floor(Math.random() * 720),
    };
    setBattleRollState((current) => ({ ...current, phase: 'rolling', rollValue, rotation }));
    window.setTimeout(async () => {
      try {
        setBattleRollState((current) => ({ ...current, phase: 'resolving', rollValue }));
        const response = await resolveBattleRoll(activeBattle.battle_id, { session_id: sessionId, forced_dice_roll: rollValue }, report);
        syncBattleState(response.battle);
        setBattleRollState((current) => ({
          ...current,
          phase: 'resolved',
          result: response.roll_result ? buildBattleRollResult(prompt, response.roll_result) : null,
        }));
      } catch (e) {
        const message = e instanceof Error ? e.message : '战斗掷骰失败';
        setBattleRollState((current) => ({ ...current, phase: 'error', errorMessage: message }));
      }
    }, 900);
  };

  const onCloseBattleRoll = () => {
    resetBattleRollState();
    if (activeBattle?.status === 'ended') {
      setConfigHint('战斗已结束，可关闭战斗窗口查看结果。');
    }
  };

  const onEndBattle = async () => {
    if (!activeBattle) return;
    if (activeBattle.status === 'ended' || activeBattle.status === 'cancelled') {
      setActiveBattle(null);
      resetBattleRollState();
      setConfigHint('战斗测试已关闭。');
      return;
    }
    try {
      setBattleBusy(true);
      await endDebugBattle(activeBattle.battle_id, { session_id: sessionId, ai_pacing: activeBattle.ui_flags.ai_pacing }, report);
      setActiveBattle(null);
      resetBattleRollState();
      setConfigHint('战斗测试已结束，日志已写入 sandbox/debug。');
    } catch (e) {
      setError(e instanceof Error ? e.message : '结束战斗测试失败');
    } finally {
      setBattleBusy(false);
    }
  };

  const onOpenMap = async () => {
    try {
      setLogOpen(false);
      await ensureMap();
      setMapOpen(true);
      setQuestInspectOpen(false);
    } catch (e) {
      setAiWaiting(false);
      const msg = e instanceof Error ? e.message : '地图打开失败';
      setError(msg);
      window.alert(msg);
    }
  };

  const onForceRegenerateMap = async () => {
    try {
      setLogOpen(false);
      await ensureMap(true);
      setMapOpen(true);
    } catch (e) {
      setAiWaiting(false);
      const msg = e instanceof Error ? e.message : '地图重新生成失败';
      setError(msg);
      window.alert(msg);
    }
  };

  const onMoveToZone = async (zoneId: string) => {
    const fromId = mapSnapshot.player_position?.zone_id ?? DEFAULT_POSITION.zone_id;
    if (zoneId === fromId) {
      showAlreadyTherePopup('你已在当前大区块。');
      return;
    }

    try {
      setAiWaitingText('正在执行区块移动与遭遇判定...');
      setAiWaiting(true);
      const moved = await moveToZone(
        {
          session_id: sessionId,
          from_zone_id: fromId,
          to_zone_id: zoneId,
          player_name: playerStatic.name,
          config,
        },
        report,
      );
      pushTimeNotice(moved.duration_min, '大区块移动');
      applyMapStateSync(moved.state_sync, sessionId);
      setMainOutput('main_turn', moved.narration.text || moved.movement_log.summary, moved.scene_events ?? [], {
        mainTurnSummary: moved.main_turn_summary ?? null,
      });
      await refreshTokenUsage(sessionId);
      setAiWaiting(false);
    } catch (e) {
      setAiWaiting(false);
      const msg = e instanceof Error ? e.message : '移动失败';
      setError(msg);
      window.alert(msg);
    }
  };

  const onSelectSaveFile = async (file: File) => {
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as SaveFile;
      const save = await importSave(parsed, report);
      setSessionId(save.session_id);
      setTokenUsage({ ...EMPTY_TOKEN_USAGE, session_id: save.session_id });
      setMapSnapshot(toMapSnapshot(save));
      setAreaSnapshot(save.area_snapshot ?? null);
      setCurrentReputation(selectCurrentReputation(save));
      setCurrentZoneMetric(selectCurrentZoneMetric(save));
      setZoneMetricState(save.zone_metric_state ?? { version: '0.1.0', entries: [], updated_at: '' });
      setQuestState(save.quest_state ?? defaultQuestState);
      setEncounterState(save.encounter_state ?? defaultEncounterState);
      setFateState(save.fate_state ?? defaultFateState);
      setTeamState(save.team_state ?? defaultTeamState);
      setNpcPoolItems(save.role_pool ?? []);
      setNpcPoolTotal((save.role_pool ?? []).length);
      setTeamChatReplies([]);
      setTeamChatBusy(false);
      setWorldState(save.world_state ?? defaultWorldState);
      setConsistencyIssues([]);
      setConsistencyIssueCount(0);
      setStorySnapshot(null);
      setCurrentMainOutput(null);
      setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
      setPlayerRuntimeState(
        save.player_runtime_data ?? {
          session_id: save.session_id,
          current_position: save.map_snapshot?.player_position ?? DEFAULT_POSITION,
          updated_at: new Date().toISOString(),
        },
      );
      await refreshCharacterBuildState(save.session_id, { openForcedModal: true });
      await ensureMap();
      await refreshNarrativeState(save.session_id);
      await refreshTokenUsage(save.session_id);
      await refreshGameLogs(save.session_id);
      await refreshConsistencyData(save.session_id);
      setInventoryOpen(false);
      setInventoryBusy(false);
      setTeamInventoryRole(null);
      setTeamProfileRole(null);
      setItemInteractionOpen(false);
      setItemInteractionBusy(false);
      setItemInteractionOwner(null);
      setItemInteractionItem(null);
      setItemInteractionPrompt('');
      setItemInteractionLastReply('');
      setEncounterModalBusy(false);
      setEncounterModalEncounterId(null);
      setMapOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入存档失败');
    }
  };

  const onClearSave = async () => {
    if (!window.confirm('确认清空当前存档信息吗？')) return;
    try {
      const save = await clearSave(sessionId, report);
      setMapSnapshot(toMapSnapshot(save));
      setAreaSnapshot(save.area_snapshot ?? null);
      setCurrentReputation(selectCurrentReputation(save));
      setCurrentZoneMetric(selectCurrentZoneMetric(save));
      setZoneMetricState(save.zone_metric_state ?? { version: '0.1.0', entries: [], updated_at: '' });
      setQuestState(save.quest_state ?? defaultQuestState);
      setEncounterState(save.encounter_state ?? defaultEncounterState);
      setFateState(save.fate_state ?? defaultFateState);
      setTeamState(save.team_state ?? defaultTeamState);
      setNpcPoolItems(save.role_pool ?? []);
      setNpcPoolTotal((save.role_pool ?? []).length);
      setTeamChatReplies([]);
      setTeamChatBusy(false);
      setWorldState(save.world_state ?? defaultWorldState);
      setConsistencyIssues([]);
      setConsistencyIssueCount(0);
      setStorySnapshot(null);
      setConsistencyOpen(false);
      setTeamOpen(false);
      setTeamInventoryRole(null);
      setTeamProfileRole(null);
      setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
      setPlayerRuntimeState(
        save.player_runtime_data ?? {
          session_id: save.session_id,
          current_position: DEFAULT_POSITION,
          updated_at: new Date().toISOString(),
        },
      );
      setInventoryOpen(false);
      setInventoryBusy(false);
      setItemInteractionOpen(false);
      setItemInteractionBusy(false);
      setItemInteractionOwner(null);
      setItemInteractionItem(null);
      setItemInteractionPrompt('');
      setItemInteractionLastReply('');
      setMapRender(null);
      setMapOpen(false);
      setLogOpen(false);
      setMapEnabled(false);
      setMapPromptDialogOpen(false);
      setCurrentMainOutput(null);
      setNpcChatMessages({});
      setChatMode('main');
      setActiveNpcChat(null);
      setQuestInspectOpen(false);
      setEncounterModalBusy(false);
      setEncounterModalEncounterId(null);
      clearPlayerInput();
      setLastActionInput('');
      setLastSpeechInput('');
      setError('');
      await refreshCharacterBuildState(save.session_id, { openForcedModal: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : '清空存档失败');
    }
  };

  const onDebugSaveReset = async () => {
    if (!window.confirm('确认执行测试重置吗？这会保留地图、玩家和队伍，只清遭遇、公开回合、pending turn 和队友记忆。')) return;
    try {
      const response = await debugSaveReset(sessionId, report);
      setCurrentMainOutput(null);
      await applySaveSnapshot(response.save, sessionId);
      resetPendingTurnWorkflowState();
      setEncounterModalEncounterId(null);
      setEncounterModalBusy(false);
      setError('');
      await syncStateFromSave(sessionId);
      setConfigHint(response.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : '测试重置失败');
    }
  };

  const onPickSavePath = async () => {
    try {
      const next = await pickSavePath(report);
      setSvPath(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : '存档文件夹选择失败');
    }
  };

  const refreshGameLogs = async (sid: string = sessionId) => {
    try {
      const [list, settings] = await Promise.all([getGameLogs(sid, 200, report), getGameLogSettings(sid, report)]);
      setGameLogs(list.items ?? []);
      setGameLogFetchLimit(settings.settings.ai_fetch_limit);
    } catch {
      // Ignore log refresh failures.
    }
  };

  const onOpenLogs = async () => {
    setMapOpen(false);
    await refreshGameLogs();
    setLogOpen(true);
  };

  const onSetLogLimit = async (next: number) => {
    try {
      const saved = await setGameLogSettings(sessionId, { ai_fetch_limit: next }, report);
      setGameLogFetchLimit(saved.settings.ai_fetch_limit);
      await refreshGameLogs();
    } catch (e) {
      setError(e instanceof Error ? e.message : '日志配置保存失败');
    }
  };

  if (authState !== 'authed') {
    return (
      <main className="app-shell" style={{ minHeight: '100vh' }}>
        {authState === 'checking' ? (
          <div style={{ color: 'rgba(255,255,255,0.72)', textAlign: 'center', marginTop: '12vh' }}>正在检查登录状态...</div>
        ) : (
          <AuthPanel onLogin={onDoLogin} onRegister={onDoRegister} onResetPassword={onDoResetPassword} error={authError} notice={authNotice} />
        )}
      </main>
    );
  }

  if (!accountConfigReady) {
    return (
      <main className="app-shell" style={{ minHeight: '100vh' }}>
        <div style={{ color: 'rgba(255,255,255,0.72)', textAlign: 'center', marginTop: '12vh' }}>正在加载当前账号配置...</div>
      </main>
    );
  }

  if (view === 'boot') {
    return (
      <main className="app-shell">
        <section className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <h1 style={{ margin: 0 }}>{hasStoredConfig ? '账号配置已就绪' : '创建账号配置'}</h1>
            <button onClick={() => void onDoLogout()}>退出登录</button>
          </div>
          <p>{hasStoredConfig ? '检测到当前账号已有配置。你可以直接进入聊天，或先编辑账号配置。' : '当前账号还没有配置，请先新建并保存。'}</p>
          {configPath && <p className="hint">账号配置路径: {configPath.path}</p>}
          <div className="actions">
            {hasStoredConfig && <button onClick={() => setView('chat')}>使用已有配置</button>}
            <button onClick={onNewConfig}>{hasStoredConfig ? '编辑账号配置' : '新建账号配置'}</button>
          </div>
        </section>
      </main>
    );
  }

  if (view === 'config') {
    return (
      <main className="app-shell">
        <section className="card config-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <h1 style={{ margin: 0 }}>配置编辑</h1>
            <button onClick={() => void onDoLogout()}>退出登录</button>
          </div>
          <p>选择服务商、填写 API Key、拉取模型，再按模型能力配置参数。</p>
          <div className="config-grid">
            <div className="config-section">
              <h2>连接</h2>
              <label>
                <span>服务商</span>
                <select value={configDraft.provider} onChange={(e) => onConfigProviderChange(e.target.value as AppConfig['provider'])}>
                  <option value="openai">OpenAI</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="gemini">Gemini</option>
                </select>
              </label>
              <label>
                <span>API Key</span>
                <input
                  type="password"
                  value={configDraft.api_key}
                  onChange={(e) => onConfigApiKeyChange(e.target.value)}
                  placeholder="输入 API Key"
                />
              </label>
              <label>
                <span>自定义 Base URL</span>
                <input
                  type="text"
                  value={configDraft.base_url_override ?? ''}
                  onChange={(e) => onConfigBaseUrlChange(e.target.value)}
                  placeholder={
                    configDraft.provider === 'deepseek'
                      ? '默认 https://api.deepseek.com'
                      : configDraft.provider === 'gemini'
                        ? '默认 Gemini OpenAI 兼容地址'
                        : '留空使用官方地址'
                  }
                />
              </label>
              <div className="actions">
                <button onClick={() => void onFetchConfigModels()} disabled={configModelsLoading}>
                  {configModelsLoading ? '加载模型中...' : '获取模型'}
                </button>
                <button type="button" onClick={() => setManualModelMode((prev) => !prev)}>
                  {manualModelMode ? '使用下拉选择' : '手动输入模型'}
                </button>
              </div>
            </div>

            <div className="config-section">
              <h2>模型</h2>
              {!manualModelMode ? (
                <label>
                  <span>模型列表</span>
                  <select value={configDraft.model} onChange={(e) => onConfigModelChange(e.target.value)}>
                    <option value="">请选择模型</option>
                    {configModels.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label>
                  <span>手动模型名</span>
                  <input
                    type="text"
                    value={configDraft.model}
                    onChange={(e) => onConfigModelChange(e.target.value)}
                    placeholder="例如 gpt-5 / deepseek-chat / gemini-2.5-flash"
                  />
                </label>
              )}
              <p className="hint">
                {configProfileLoading
                  ? '正在解析模型能力...'
                  : configProfile
                    ? `能力档位: ${configProfile.capability_profile}`
                    : '选择模型后自动解析可配置参数。'}
              </p>
              {configProfile?.warning && <p className="hint">{configProfile.warning}</p>}
            </div>

            <div className="config-section">
              <h2>参数</h2>
              {configProfile && configProfile.supported_params.length > 0 ? (
                <div className="config-fields">
                  {configProfile.supported_params.map((paramKey) => (
                    <label key={paramKey}>
                      <span>{MODEL_PARAM_LABELS[paramKey]}</span>
                      <input
                        type="number"
                        step={paramKey === 'temperature' ? '0.1' : '1'}
                        value={configDraft.runtime[paramKey] ?? ''}
                        onChange={(e) => onConfigRuntimeChange(paramKey, e.target.value)}
                      />
                    </label>
                  ))}
                </div>
              ) : configProfile ? (
                <p className="hint">当前模型能力档位不需要额外运行参数，聊天请求将仅发送基础字段。</p>
              ) : (
                <p className="hint">当前模型尚未解析，参数区暂不可用。</p>
              )}
            </div>

            <div className="config-section">
              <h2>通用</h2>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={configDraft.stream}
                  onChange={(e) => setConfigDraft((prev) => ({ ...prev, stream: e.target.checked }))}
                />
                <span>启用流式输出</span>
              </label>
              <label>
                <span>每 50 tokens 折算分钟</span>
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={configDraft.speech_time_per_50_tokens_min}
                  onChange={(e) =>
                    setConfigDraft((prev) => ({
                      ...prev,
                      speech_time_per_50_tokens_min: Number(e.target.value || 1),
                    }))
                  }
                />
              </label>
              <label>
                <span>GM Prompt</span>
                <textarea
                  value={configDraft.gm_prompt}
                  onChange={(e) => setConfigDraft((prev) => ({ ...prev, gm_prompt: e.target.value }))}
                />
              </label>
            </div>

            <div className="config-section">
              <h2>Build Media</h2>
              <label>
                <span>媒体 Provider 模式</span>
                <select
                  value={configDraft.build_media.mode}
                  onChange={(e) =>
                    setConfigDraft((prev) => ({
                      ...prev,
                      build_media: {
                        ...prev.build_media,
                        mode: e.target.value as BuildMediaConfig['mode'],
                      },
                    }))
                  }
                >
                  <option value="follow_chat_provider">跟随聊天 Provider</option>
                  <option value="explicit_provider">显式指定媒体 Provider</option>
                </select>
              </label>
              <label>
                <span>显式媒体 Provider</span>
                <select
                  value={configDraft.build_media.explicit_provider ?? 'openai'}
                  disabled={configDraft.build_media.mode !== 'explicit_provider'}
                  onChange={(e) =>
                    setConfigDraft((prev) => ({
                      ...prev,
                      build_media: {
                        ...prev.build_media,
                        explicit_provider: e.target.value as BuildMediaConfig['explicit_provider'],
                      },
                    }))
                  }
                >
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                </select>
              </label>
              <p className="hint">DeepSeek 不支持立绘生成、去背景和看图描述。若聊天使用 DeepSeek，请切到 explicit_provider。</p>
              {(['openai', 'deepseek', 'gemini'] as const).map((provider) => (
                <div key={provider} className="config-subsection">
                  <h3 style={{ margin: '8px 0 0' }}>{provider.toUpperCase()}</h3>
                  <div className="config-fields">
                    <label>
                      <span>媒体 API Key</span>
                      <input
                        type="password"
                        value={configDraft.build_media.provider_configs[provider].api_key}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...prev,
                            build_media: {
                              ...prev.build_media,
                              provider_configs: {
                                ...prev.build_media.provider_configs,
                                [provider]: {
                                  ...prev.build_media.provider_configs[provider],
                                  api_key: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>媒体 Base URL</span>
                      <input
                        type="text"
                        value={configDraft.build_media.provider_configs[provider].base_url_override ?? ''}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...prev,
                            build_media: {
                              ...prev.build_media,
                              provider_configs: {
                                ...prev.build_media.provider_configs,
                                [provider]: {
                                  ...prev.build_media.provider_configs[provider],
                                  base_url_override: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>generation_model</span>
                      <input
                        type="text"
                        value={configDraft.build_media.provider_configs[provider].generation_model}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...prev,
                            build_media: {
                              ...prev.build_media,
                              provider_configs: {
                                ...prev.build_media.provider_configs,
                                [provider]: {
                                  ...prev.build_media.provider_configs[provider],
                                  generation_model: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>background_removal_model</span>
                      <input
                        type="text"
                        value={configDraft.build_media.provider_configs[provider].background_removal_model}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...prev,
                            build_media: {
                              ...prev.build_media,
                              provider_configs: {
                                ...prev.build_media.provider_configs,
                                [provider]: {
                                  ...prev.build_media.provider_configs[provider],
                                  background_removal_model: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>vision_model</span>
                      <input
                        type="text"
                        value={configDraft.build_media.provider_configs[provider].vision_model}
                        onChange={(e) =>
                          setConfigDraft((prev) => ({
                            ...prev,
                            build_media: {
                              ...prev.build_media,
                              provider_configs: {
                                ...prev.build_media.provider_configs,
                                [provider]: {
                                  ...prev.build_media.provider_configs[provider],
                                  vision_model: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>

            <div className="config-section">
              <h2>Sub-Zone 调试</h2>
              <div className="config-fields">
                <label>
                  <span>small 最小数</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={configDraft.sub_zone_debug.small_min_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          small_min_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>small 最大数</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={configDraft.sub_zone_debug.small_max_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          small_max_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>medium 最小数</span>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={configDraft.sub_zone_debug.medium_min_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          medium_min_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>medium 最大数</span>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={configDraft.sub_zone_debug.medium_max_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          medium_max_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>large 最小数</span>
                  <input
                    type="number"
                    min={1}
                    max={40}
                    value={configDraft.sub_zone_debug.large_min_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          large_min_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>large 最大数</span>
                  <input
                    type="number"
                    min={1}
                    max={40}
                    value={configDraft.sub_zone_debug.large_max_count}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          large_max_count: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
                <label>
                  <span>发现交互上限</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={configDraft.sub_zone_debug.discover_interaction_limit}
                    onChange={(e) =>
                      setConfigDraft((prev) => ({
                        ...prev,
                        sub_zone_debug: {
                          ...prev.sub_zone_debug,
                          discover_interaction_limit: Number(e.target.value || 1),
                        },
                      }))
                    }
                  />
                </label>
              </div>
            </div>

            <div className="config-section">
              <h2>账号存储</h2>
              <p className="hint">多用户模式下，配置文件会自动保存到当前账号目录，不支持选择本地目录。</p>
              {configPath && <p className="hint">当前账号配置路径: {configPath.path}</p>}
            </div>
          </div>
          <div className="actions">
            <button onClick={() => setView(configReturnView)}>返回</button>
            <button onClick={() => void onValidateAndSaveConfig()}>校验并进入聊天</button>
          </div>
          {configHint && <p className="hint">{configHint}</p>}
          {error && <p className="error">{error}</p>}
        </section>
      </main>
    );
  }

  const mainOutputVisibleEvents = (currentMainOutput?.scene_events ?? []).filter(
    (event) => !FOLDED_MAIN_SCENE_EVENT_KINDS.has(event.kind),
  );
  const mainOutputFoldedEvents = (currentMainOutput?.scene_events ?? []).filter((event) =>
    FOLDED_MAIN_SCENE_EVENT_KINDS.has(event.kind),
  );
  const restoredPublicTurnPresentation = publicTurnPresentationFromRound(publicTurnRound);
  const structuredPublicTurnOutput =
    currentMainOutput?.public_turn_presentation ?? livePublicTurnPresentation ?? restoredPublicTurnPresentation ?? null;
  const visiblePublicTurnImpacts = structuredPublicTurnOutput ? (publicTurnImpacts.length > 0 ? publicTurnImpacts : publicTurnRound?.impacts ?? []) : publicTurnImpacts;

  return (
    <main className="app-shell chat-shell">
      {debugOpen && (
        <div className="modal-mask">
          <DebugPanel
            onClose={() => setDebugOpen(false)}
            entries={debugEntries}
            configPath={configPath}
            savePath={savePath}
            onEnableMap={onEnableMap}
            onOpenPlayerPanel={onOpenPlayerPanel}
            onOpenInventory={onOpenInventory}
            onOpenNpcPool={() => void onOpenNpcPool()}
            onOpenTeamPanel={() => void onOpenTeamPanel()}
            onOpenCharacterBuildPlayer={onOpenCharacterBuildPlayer}
            onOpenCharacterBuildCompanion={onOpenCharacterBuildCompanion}
            playerBuildCompleted={playerBuildCompleted}
            onGenerateDebugTeammate={() => void onGenerateDebugTeamMember()}
            onOpenBattleStart={onOpenBattleStart}
            onFillTemplateLibrary={() => void onFillTemplateLibrary()}
            onFillSpellLibrary={() => void onFillSpellLibrary()}
            onOpenActionPanel={() => void onOpenActionPanel()}
            onOpenPlayerInputValidationPanel={() => void onOpenPlayerInputValidationPanel()}
            onGenerateQuest={() => void onGenerateQuest()}
            onGenerateFate={() => void onGenerateFate()}
            onRegenerateFate={() => void onRegenerateFate()}
            onOpenFatePanel={onOpenFatePanel}
            onShowConsistencyStatus={() => void onShowConsistencyStatus()}
            onRunConsistencyCheck={() => void onRunConsistencyCheck()}
            onGenerateEncounter={() => void onGenerateEncounter()}
            onSelectSaveFile={(file) => void onSelectSaveFile(file)}
            onClearSave={() => void onClearSave()}
            onDebugSaveReset={() => void onDebugSaveReset()}
            onPickSavePath={() => void onPickSavePath()}
            templateLibraryStatus={templateLibraryStatus}
          />
        </div>
      )}

      <CharacterBuildModal
        open={characterBuildOpen}
        forced={characterBuildMode === 'player' && characterBuildState?.forced_entry === true}
        mode={characterBuildMode}
        sessionId={sessionId}
        config={config}
        initialState={characterBuildState}
        onClose={() => setCharacterBuildOpen(false)}
        onConfigRequired={onOpenConfigFromChat}
        onCompleted={(result) => void onCharacterBuildCompleted(result)}
      />

      {companionBuildOfferOpen && !characterBuildOpen && (
        <div className="modal-mask">
          <div className="modal-card modal-medium">
            <h3>继续创建首个随从？</h3>
            <p>玩家构筑已完成。是否现在继续创建你的首个随从队友？</p>
            <div className="actions">
              <button onClick={() => void onDismissCompanionBuildOffer(false)}>暂时不用</button>
              <button onClick={() => void onDismissCompanionBuildOffer(true)}>继续创建随从</button>
            </div>
          </div>
        </div>
      )}

      <PartyPreviewRail
        entries={partyPreviewEntries}
        onOpenPlayerPanel={onOpenPlayerPanel}
        onOpenTeamPanel={() => void onOpenTeamPanel()}
        onSelectPlayer={onOpenPlayerQuickAction}
        onSelectTeammate={(roleId, roleName) => void onOpenTeammateChatModal(roleId, roleName)}
      />

      <section className="card chat-card">
        <header className="chat-header">
          <div>
            <h1>跑团聊天</h1>
            <p>{statusText}</p>
            <p>{chatMode === 'npc' && activeNpcChat ? `当前对话: ${activeNpcChat.npcName}` : '当前对话: 主叙事聊天'}</p>
            <p>
              当前任务: {currentQuest?.title ?? '无'} | 当前命运: {fateState.current_fate?.title ?? '未生成'}
            </p>
            <p>
              当前位置: {currentZone?.name ?? areaSnapshot?.current_zone_id ?? '未知'} / {currentSubZone?.name ?? areaSnapshot?.current_sub_zone_id ?? '未知'}
            </p>
            <p>
              区域名声: {typeof currentZoneMetric?.reputation_score === 'number' ? currentZoneMetric.reputation_score : '-'}
              {currentZoneMetric?.reputation_band ? ` / ${currentZoneMetric.reputation_band}` : ''}
              {' | '}
              区域危险: {typeof currentZoneMetric?.danger_score === 'number' ? currentZoneMetric.danger_score : '-'}
              {currentZoneMetric?.danger_band ? ` / ${currentZoneMetric.danger_band}` : ''}
            </p>
            <p>
              Token 消耗(全 AI 请求): in {tokenUsage.total.input_tokens} / out {tokenUsage.total.output_tokens} / total {tokenTotal} | 聊天 {tokenUsage.sources.chat.total_tokens} / 地图 {tokenUsage.sources.map_generation.total_tokens} / 移动反馈 {tokenUsage.sources.movement_narration.total_tokens}
            </p>
          </div>
          <div className="actions">
            {chatMode === 'npc' && <button onClick={onLeaveNpcChat}>返回主聊天</button>}
            <button onClick={() => setDebugOpen(true)}>Debug</button>
            <button onClick={onOpenCurrentQuest} disabled={!currentQuest}>
              查看当前任务
            </button>
            <button onClick={onOpenConfigFromChat}>配置</button>
            <button onClick={onClear}>新建会话</button>
            <button onClick={() => void onOpenLogs()}>日志</button>
            <button onClick={() => void onOpenMap()} disabled={!mapEnabled}>
              打开世界地图
            </button>
          </div>
        </header>

        <div className="chat-grid">
          <div className="chat-main-column">
            {chatMode === 'main' && <SubZoneContextPanel subZone={currentSubZone} />}

            {chatMode === 'main' ? (
              <section className="messages current-output-panel">
                <header className="current-output-header">
                  <h3>当前轮输出</h3>
                  <p>
                    {currentMainOutput?.source_kind === 'system_output'
                      ? '系统反馈'
                      : currentMainOutput?.status === 'awaiting_archive'
                        ? '上一轮输出（等待下一次输出覆盖）'
                        : '当前轮公开回合输出'}
                  </p>
                </header>
                {!structuredPublicTurnOutput &&
                  !currentMainOutput?.reply_text.trim() &&
                  (currentMainOutput?.scene_events.length ?? 0) === 0 && (
                  <p className="hint">主聊天历史已经收进上方地区上下文，这里只显示当前轮输出或系统反馈。</p>
                )}
                {structuredPublicTurnOutput ? (
                  <div className="public-turn-output-layout">
                    <PublicTurnSettlementPane presentation={structuredPublicTurnOutput} roundActive={Boolean(publicTurnRound)} />
                    <PublicTurnNarrativePane presentation={structuredPublicTurnOutput} />
                  </div>
                ) : (
                  currentMainOutput?.reply_text.trim() && (
                  <article className="msg assistant">
                    <strong>GM</strong>
                    <p>{currentMainOutput.reply_text}</p>
                    {currentMainOutput.source_kind === 'main_turn' &&
                      typeof currentMainOutput.main_turn_summary?.player_situation_delta === 'number' && (
                        <p className="hint">
                          玩家本轮局势变化：
                          {currentMainOutput.main_turn_summary.player_situation_delta >= 0
                            ? `+${currentMainOutput.main_turn_summary.player_situation_delta}`
                            : currentMainOutput.main_turn_summary.player_situation_delta}
                        </p>
                      )}
                  </article>
                  )
                )}
                {!structuredPublicTurnOutput &&
                  mainOutputVisibleEvents.map((event) => <SceneEventCard key={event.event_id} event={event} />)}
                {structuredPublicTurnOutput && (visiblePublicTurnImpacts.length > 0 || mainOutputFoldedEvents.length > 0) && (
                  <div className="scene-event-fold-group">
                    <button
                      type="button"
                      className="scene-event-fold-toggle"
                      onClick={() => setShowFoldedMainSceneEvents((prev) => !prev)}
                    >
                      {showFoldedMainSceneEvents ? `收起结构化调试（${visiblePublicTurnImpacts.length + mainOutputFoldedEvents.length}）` : `展开结构化调试（${visiblePublicTurnImpacts.length + mainOutputFoldedEvents.length}）`}
                    </button>
                    {showFoldedMainSceneEvents && (
                      <>
                        <PublicTurnImpactList impacts={visiblePublicTurnImpacts} />
                        {mainOutputFoldedEvents.map((event) => <SceneEventCard key={event.event_id} event={event} />)}
                      </>
                    )}
                  </div>
                )}
                {!structuredPublicTurnOutput && mainOutputFoldedEvents.length > 0 && (
                  <div className="scene-event-fold-group">
                    <button
                      type="button"
                      className="scene-event-fold-toggle"
                      onClick={() => setShowFoldedMainSceneEvents((prev) => !prev)}
                    >
                      {showFoldedMainSceneEvents ? `收起公开结算（${mainOutputFoldedEvents.length}）` : `展开公开结算（${mainOutputFoldedEvents.length}）`}
                    </button>
                    {showFoldedMainSceneEvents &&
                      mainOutputFoldedEvents.map((event) => <SceneEventCard key={event.event_id} event={event} />)}
                  </div>
                )}
                <LiveProgressPanel entries={mainLiveProgress} />
              </section>
            ) : (
              <section className="messages">
                {npcDisplayedMessages.length === 0 && <p className="hint">你已接近该 NPC，可输入动作或语言开始交互。</p>}
                {npcDisplayedMessages.map((m, index) => (
                  <article key={`${m.role}_${index}`} className={`msg ${m.role}`}>
                    <strong>{m.role === 'user' ? '你' : m.role === 'assistant' ? 'GM' : 'System'}</strong>
                    <p>{m.content}</p>
                  </article>
                ))}
                <LiveProgressPanel entries={activeNpcChat ? (npcLiveProgress[activeNpcChat.npcId] ?? []) : []} compact />
              </section>
            )}

            {chatMode === 'main' && (
              <section className="chat-interactions">
                <h3>可互动物品</h3>
                <div className="actions">
                  <button
                    onClick={() => {
                      if (!currentSubZone) return;
                      void onDiscoverAreaInteraction(currentSubZone.sub_zone_id, '观察周围细节');
                    }}
                    disabled={!currentSubZone || encounterEngaged}
                  >
                    +发现新交互
                  </button>
                  {(currentSubZone?.key_interactions ?? []).map((it) => (
                    <button key={it.interaction_id} onClick={() => void onUseAreaItem(it.interaction_id, it.name)} disabled={encounterEngaged}>
                      {it.name}
                    </button>
                  ))}
                  {(currentSubZone?.key_interactions?.length ?? 0) === 0 && <p className="hint">当前暂无可互动物品。</p>}
                  {encounterEngaged && <p className="hint">遭遇进行中，请直接在主聊天描述动作或发言。</p>}
                </div>
              </section>
            )}

            {chatMode === 'main' && (
              <section className="chat-interactions">
                <h3>可交互NPC</h3>
                <div className="actions">
                  {(currentSubZone?.npcs ?? []).map((npc) => (
                    <button key={npc.npc_id} onClick={() => void onEnterNpcChat(npc.npc_id, npc.name)} disabled={encounterEngaged}>
                      {npc.name}
                    </button>
                  ))}
                  {(currentSubZone?.npcs?.length ?? 0) === 0 && <p className="hint">当前暂无可交互NPC。</p>}
                  {encounterEngaged && <p className="hint">遭遇进行中，请直接在主聊天描述动作或发言。</p>}
                </div>
              </section>
            )}

            {mapEnabled && (
              <div className="actions">
                <button onClick={() => void onOpenMap()}>打开世界地图（聊天入口）</button>
                <button onClick={() => void onOpenLogs()}>打开日志（聊天入口）</button>
              </div>
            )}

            <footer className="composer">
              <div className="actions">
                <label className="god-mode-toggle">
                  <input type="checkbox" checked={godMode} onChange={(e) => setGodMode(e.target.checked)} />
                  上帝模式
                </label>
                {chatState === 'streaming' && <button onClick={onStop}>停止生成</button>}
                {chatMode === 'npc' && <button onClick={onRetry}>重新生成</button>}
              </div>

              {chatMode === 'main' ? (
                <PublicTurnPanel
                  state={publicTurnState}
                  currentActorName={currentPublicTurnActorName}
                  currentSituationValue={activeEncounter?.situation_value ?? null}
                  actionValue={actionInput}
                  speechValue={speechInput}
                  busy={chatState === 'sending' || chatState === 'streaming' || blockingWorkflowActive}
                  godMode={godMode}
                  playerActionStatus={playerPublicTurnActionStatus}
                  onActionChange={setActionInput}
                  onSpeechChange={setSpeechInput}
                  onStartNextRound={() => void onStartNextPublicTurnRound()}
                  onStartInitiative={() => void onStartPublicTurnInitiative()}
                  onSubmitAction={() => void onSend()}
                  onSubmitGodOverride={() => void onSend()}
                />
              ) : (
                <>
                  <div className="composer-input-grid">
                    <div className="composer-input-block">
                      <label htmlFor="action-input">动作描述</label>
                      <textarea
                        id="action-input"
                        ref={actionInputRef}
                        value={actionInput}
                        onChange={(e) => setActionInput(e.target.value)}
                        placeholder={pendingQuest ? '请先处理当前任务弹窗。' : '例如：我把徽记放到桌上，向前一步观察他的反应。'}
                        disabled={chatState === 'sending' || chatState === 'streaming' || blockingWorkflowActive}
                      />
                    </div>
                    <div className="composer-input-block">
                      <label htmlFor="speech-input">语言描述</label>
                      <textarea
                        id="speech-input"
                        value={speechInput}
                        onChange={(e) => setSpeechInput(e.target.value)}
                        placeholder={pendingQuest ? '请先处理当前任务弹窗。' : '例如：我低声说：“我想打听这里最近的怪事。”'}
                        disabled={chatState === 'sending' || chatState === 'streaming' || blockingWorkflowActive}
                      />
                    </div>
                  </div>
                  <p className="hint">NPC 单聊支持只输入动作或只输入语言；若包含动作或向 NPC 提要求，会先进入检定，再把结果一并发给 NPC。</p>
                  <div className="actions">
                    <button disabled={!canSend} onClick={() => void onSend()}>
                      发送
                    </button>
                  </div>
                </>
              )}
              {pendingQuest && <p className="hint">当前有待确认任务，任务弹窗关闭前无法继续聊天。</p>}
              {minimizedBlockingModal && <p className="hint">当前有未完成弹窗，需恢复后处理；最小化期间只能查看主聊天。</p>}
              {error && <p className="error">{error}</p>}
            </footer>
          </div>

          <EncounterLane
            encounter={activeEncounter}
            queuedEncounters={queuedEncounters}
            roleCards={npcPoolItems}
            areaSnapshot={areaSnapshot}
            busy={encounterModalBusy}
            canRejoin={canRejoinActiveEncounter}
          />
        </div>
      </section>

      <MapPanel
        open={mapOpen && !logOpen}
        zones={mapSnapshot.zones}
        areaSnapshot={areaSnapshot}
        render={mapRender}
        playerPosition={mapSnapshot.player_position}
        currentZoneMetric={currentZoneMetric}
        zoneMetricState={zoneMetricState}
        playerSpeedMph={playerStatic.move_speed_mph}
        search={mapSearch}
        onSearch={setMapSearch}
        onClose={() => setMapOpen(false)}
        onForceRegenerate={() => void onForceRegenerateMap()}
        onMove={(zoneId) => void onMoveToZone(zoneId)}
        onMoveSubZone={(subZoneId) => void onMoveSubZone(subZoneId)}
        onInitClock={() => void onInitAreaClock()}
      />

      <PlayerPanel
        key={`${playerPanelOpen ? 'open' : 'closed'}_${playerStatic.player_id}`}
        open={playerPanelOpen}
        value={playerStatic}
        questState={questState}
        currentReputation={currentReputation}
        onClose={() => setPlayerPanelOpen(false)}
        onSave={(next) => void onSavePlayerStatic(next)}
        onTrackQuest={(questId) => void onTrackQuest(questId)}
        onEvaluateQuest={(questId) => void onEvaluateQuest(questId)}
      />

      <InventoryModal
        open={inventoryOpen}
        player={playerStatic}
        busy={inventoryBusy}
        onClose={() => setInventoryOpen(false)}
        onEquip={(itemId, slot) => void onEquipInventory({ owner_type: 'player', role_id: null }, itemId, slot)}
        onUnequip={(slot) => void onUnequipInventory({ owner_type: 'player', role_id: null }, slot)}
        onInspect={(itemId, itemName) => openItemInteraction({ owner_type: 'player', role_id: null }, 'inspect', itemId, itemName)}
        onUse={(itemId, itemName) => openItemInteraction({ owner_type: 'player', role_id: null }, 'use', itemId, itemName)}
      />

      <PlayerQuickActionModal
        open={playerQuickActionOpen}
        mode={playerQuickActionMode}
        player={playerStatic}
        onClose={() => {
          setPlayerQuickActionOpen(false);
          setPlayerQuickActionMode('root');
        }}
        onBack={() => setPlayerQuickActionMode('root')}
        onOpenInventory={() => {
          setPlayerQuickActionOpen(false);
          setPlayerQuickActionMode('root');
          onOpenInventory();
        }}
        onShowSpells={() => setPlayerQuickActionMode('spell')}
        onShowWarArts={() => setPlayerQuickActionMode('war_art')}
        onSelectSpell={prefillPlayerActionWithAbility}
        onSelectWarArt={prefillPlayerActionWithAbility}
      />

      <RoleInventoryModal
        open={Boolean(teamInventoryRole)}
        role={teamInventoryRole}
        busy={inventoryBusy}
        onClose={() => setTeamInventoryRole(null)}
        onEquip={(itemId, slot) =>
          void onEquipInventory(
            { owner_type: 'role', role_id: teamInventoryRole?.role_id ?? null },
            itemId,
            slot,
          )
        }
        onUnequip={(slot) =>
          void onUnequipInventory(
            { owner_type: 'role', role_id: teamInventoryRole?.role_id ?? null },
            slot,
          )
        }
        onInspect={(itemId, itemName) =>
          openItemInteraction(
            { owner_type: 'role', role_id: teamInventoryRole?.role_id ?? null },
            'inspect',
            itemId,
            itemName,
          )
        }
        onUse={(itemId, itemName) =>
          openItemInteraction(
            { owner_type: 'role', role_id: teamInventoryRole?.role_id ?? null },
            'use',
            itemId,
            itemName,
          )
        }
      />

      <RoleProfileModal open={Boolean(teamProfileRole)} role={teamProfileRole} onClose={() => setTeamProfileRole(null)} />

      <TeammateChatModal
        open={Boolean(activeTeammateChat)}
        role={activeTeammateRole}
        affinity={activeTeammateMember?.affinity ?? null}
        trust={activeTeammateMember?.trust ?? null}
        messages={activeTeammateMessages}
        liveProgress={activeTeammateLiveProgress}
        actionValue={teammateChatActionInput}
        speechValue={teammateChatSpeechInput}
        busy={chatState === 'sending' || chatState === 'streaming'}
        inputDisabled={teammateChatInputDisabled}
        sendDisabled={teammateChatSendDisabled}
        disabledHint={teammateChatDisabledHint}
        errorMessage={error}
        onActionChange={setTeammateChatActionInput}
        onSpeechChange={setTeammateChatSpeechInput}
        onSend={() => void onSendTeammateChat()}
        onRetry={onRetryTeammateChat}
        onOpenInventory={() => {
          if (!activeTeammateChat) return;
          void onInspectTeamInventory(activeTeammateChat.npcId);
        }}
        onOpenProfile={() => {
          if (!activeTeammateChat) return;
          void onInspectTeamProfile(activeTeammateChat.npcId);
        }}
        onRetain={() => {
          if (!activeTeammateChat) return;
          void onRetainTeamMember(activeTeammateChat.npcId, activeTeammateChat.npcName);
        }}
        onClose={closeTeammateChatModal}
      />

      <FatePanel open={fatePanelOpen} state={fateState} onClose={() => setFatePanelOpen(false)} />

      <ConsistencyPanel
        open={consistencyOpen}
        busy={consistencyBusy}
        worldState={worldState}
        snapshot={storySnapshot}
        issueCount={consistencyIssueCount}
        issues={consistencyIssues}
        onRefresh={() => void onShowConsistencyStatus()}
        onRunCheck={() => void onRunConsistencyCheck()}
        onClose={() => setConsistencyOpen(false)}
      />

      <NpcPoolPanel
        open={npcPoolOpen}
        items={npcPoolItems}
        total={npcPoolTotal}
        search={npcPoolSearch}
        selected={npcSelected}
        teamMemberIds={teamState.members.map((item) => item.role_id)}
        onSearch={onSearchNpcPool}
        onRefresh={() => void refreshNpcPool()}
        onSelect={(roleId) => void onSelectNpcRole(roleId)}
        onInviteTeam={(roleId, npcName) => void onInviteNpcToTeam(roleId, npcName)}
        onLeaveTeam={(roleId) => void onLeaveTeamMember(roleId)}
        onClose={() => setNpcPoolOpen(false)}
      />

      <TeamPanel
        open={teamOpen}
        state={teamState}
        roleCards={npcPoolItems}
        areaSnapshot={areaSnapshot}
        chatReplies={teamChatReplies}
        chatBusy={teamChatBusy}
        chatBlocked={blockingWorkflowActive || encounterEngaged}
        onRefresh={() => void onOpenTeamPanel()}
        onTeamChat={(playerMessage) => void onTeamChat(playerMessage)}
        onChat={(npcId, npcName) => void onEnterNpcChat(npcId, npcName)}
        onInspectProfile={(npcId) => void onInspectTeamProfile(npcId)}
        onInspectInventory={(npcId) => void onInspectTeamInventory(npcId)}
        onLeave={(npcId) => void onLeaveTeamMember(npcId)}
        onRetain={(npcId, npcName) => void onRetainTeamMember(npcId, npcName)}
        onClose={() => setTeamOpen(false)}
      />

      <ActionCheckPanel
        key={`${actionPanelOpen ? 'open' : 'closed'}_${playerStatic.player_id}`}
        open={actionPanelOpen}
        npcs={npcPoolItems}
        playerRoleId={playerStatic.player_id}
        lastResult={lastActionResult}
        busy={actionCheckRollState.open}
        onRun={(payload) => void onRunActionCheck(payload)}
        onClose={() => setActionPanelOpen(false)}
      />

      <PlayerInputValidationPanel
        key={`${playerInputValidationPanelOpen ? 'open' : 'closed'}_${playerStatic.player_id}`}
        open={playerInputValidationPanelOpen}
        npcs={npcPoolItems}
        playerRoleId={playerStatic.player_id}
        lastResult={lastPlayerInputValidationResult}
        busy={playerInputValidationDebugBusy}
        onRun={(payload) => void onRunPlayerInputValidation(payload)}
        onContinueActionCheck={(payload) => void onRunActionCheckFromPlayerInputValidation(payload)}
        onClose={() => setPlayerInputValidationPanelOpen(false)}
      />

      <GameLogPanel
        key={`${logOpen ? 'open' : 'closed'}_${gameLogFetchLimit}`}
        open={logOpen && !mapOpen}
        items={gameLogs}
        aiFetchLimit={gameLogFetchLimit}
        onClose={() => setLogOpen(false)}
        onSetLimit={(next) => void onSetLogLimit(next)}
      />

      {mapPromptDialogOpen && (
        <div className="modal-mask">
          <div className="modal-card">
            <h3>世界地图生成设置</h3>
            <p>输入用于约束区块内容的 Prompt，例如：剑与魔法世界的地区。</p>
            <textarea
              value={mapPromptInput}
              onChange={(e) => setMapPromptInput(e.target.value)}
              placeholder="输入地图生成 Prompt"
            />
            <div className="actions">
              <button onClick={() => setMapPromptDialogOpen(false)}>返回</button>
              <button onClick={onConfirmEnableMap} disabled={!mapPromptInput.trim()}>
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      <BattleStartDialog
        open={battleStartDialogOpen}
        minimized={minimizedBlockingModal === 'battle_start'}
        busy={battleStartBusy}
        currentZoneName={currentZone?.name ?? areaSnapshot?.current_zone_id ?? '未知大区块'}
        currentSubZoneName={currentSubZone?.name ?? areaSnapshot?.current_sub_zone_id ?? '未知子区块'}
        subZoneDescription={currentSubZone?.description ?? ''}
        dangerScore={currentZoneMetric?.danger_score}
        reputationScore={currentZoneMetric?.reputation_score}
        onClose={() => setBattleStartDialogOpen(false)}
        onMinimize={() => setMinimizedBlockingModal('battle_start')}
        onConfirm={onConfirmBattleStart}
        sessionId={sessionId}
        configPayload={config}
      />

      {aiWaiting && (
        <div className="modal-mask">
          <div className="modal-card">
            <h3>请稍候</h3>
            <p>{aiWaitingText}</p>
          </div>
        </div>
      )}

      <QuestModal
        quest={visibleQuestModal ? pendingQuest : null}
        busy={questModalBusy}
        onAccept={(questId) => void onAcceptQuest(questId)}
        onReject={(questId) => void onRejectQuest(questId)}
        onMinimize={() => setMinimizedBlockingModal('quest')}
      />

      <EncounterModal
        encounter={pendingQuest || !visibleEncounterModal ? null : encounterModalEncounter}
        roleCards={npcPoolItems}
        busy={encounterModalBusy}
        onContinue={onCloseEncounterModal}
        onMinimize={() => setMinimizedBlockingModal('encounter')}
      />

      <PlayerInputValidationModal
        open={Boolean(playerInputValidationModalState)}
        response={playerInputValidationModalState?.response ?? null}
        originalActionText={playerInputValidationModalState?.originalActionText ?? ''}
        originalSpeechText={playerInputValidationModalState?.originalSpeechText ?? ''}
        onAcceptSuggestion={onAcceptPlayerInputValidationSuggestion}
        onReturnToEdit={onReturnToEditPlayerInputValidation}
      />

      <BattleModal
        open={visibleBattleModal}
        battle={activeBattle}
        busy={battleBusy}
        onMinimize={() => setMinimizedBlockingModal('battle')}
        onClose={() => {
          if (activeBattle?.status === 'ended' || activeBattle?.status === 'cancelled') {
            setActiveBattle(null);
          }
        }}
        onAction={onBattleAction}
        onContinueAi={onBattleContinueAi}
        onSetAiPacing={onSetBattleAiPacing}
        onEndBattle={() => void onEndBattle()}
      />

      <QuestInspectModal quest={questInspectOpen ? currentQuest : null} onClose={() => setQuestInspectOpen(false)} />

      <ItemInteractionModal
        open={itemInteractionOpen}
        title={itemInteractionItem ? `${itemInteractionItem.itemName} / ${itemInteractionMode === 'inspect' ? '观察' : '使用'}` : ''}
        mode={itemInteractionMode}
        prompt={itemInteractionPrompt}
        busy={itemInteractionBusy}
        lastReply={itemInteractionLastReply}
        onPromptChange={setItemInteractionPrompt}
        onSubmit={() => void onSubmitItemInteraction()}
        onClose={() => setItemInteractionOpen(false)}
      />

      <ActionCheckRollModal
        open={actionCheckRollState.open}
        phase={actionCheckRollState.phase}
        plan={actionCheckRollState.plan}
        rollValue={actionCheckRollState.rollValue}
        result={actionCheckRollState.result}
        errorMessage={actionCheckRollState.errorMessage}
        rotation={actionCheckRollState.rotation}
        onTrigger={onTriggerActionCheckRoll}
        onClose={onCloseActionCheckRoll}
      />

      <ActionCheckRollModal
        open={visiblePublicTurnActionRoll}
        phase={publicTurnActionRollState.phase}
        plan={publicTurnActionRollState.plan}
        rollValue={publicTurnActionRollState.rollValue}
        result={publicTurnActionRollState.result}
        errorMessage={publicTurnActionRollState.errorMessage}
        rotation={publicTurnActionRollState.rotation}
        title="本回合行动检定"
        subtitle="先掷出这次公开回合行动的 d20，再继续本轮结算。"
        onTrigger={onTriggerPublicTurnActionRoll}
        onClose={onClosePublicTurnActionRoll}
        onMinimize={() => setMinimizedBlockingModal('public_turn_action_roll')}
      />

      <PublicTurnInteractionModal
        open={visiblePublicTurnInteraction}
        prompt={pendingInteractionState?.prompt ?? null}
        actionValue={publicTurnInteractionActionInput}
        speechValue={publicTurnInteractionSpeechInput}
        busy={publicTurnInteractionBusy}
        errorMessage={publicTurnInteractionError}
        speechOnly={playerSpeechOnlyInPublicTurn}
        onActionChange={setPublicTurnInteractionActionInput}
        onSpeechChange={setPublicTurnInteractionSpeechInput}
        onSubmit={() => void onSubmitPublicTurnInteraction()}
        onNoAction={() => void onSubmitPublicTurnInteractionNoAction()}
        onMinimize={() => setMinimizedBlockingModal('public_turn_interaction')}
      />

      <PublicTurnAttackModal
        open={visiblePublicTurnAttackResponse}
        prompt={pendingAttackState?.prompt ?? null}
        actionValue={publicTurnAttackActionInput}
        speechValue={publicTurnAttackSpeechInput}
        busy={publicTurnAttackBusy}
        errorMessage={publicTurnAttackError}
        speechOnly={playerSpeechOnlyInPublicTurn}
        onActionChange={setPublicTurnAttackActionInput}
        onSpeechChange={setPublicTurnAttackSpeechInput}
        onSubmit={() => void onSubmitPublicTurnAttackResponse()}
        onNoAction={() => void onSubmitPublicTurnAttackNoAction()}
        onMinimize={() => setMinimizedBlockingModal('public_turn_attack_response')}
      />

      <PublicTurnAttackDefenseModal
        open={visiblePublicTurnAttackDefense}
        prompt={pendingAttackDefenseState?.prompt ?? null}
        phase={publicTurnAttackDefenseRollState.phase}
        rollValue={publicTurnAttackDefenseRollState.rollValue}
        result={publicTurnAttackDefenseRollState.result}
        errorMessage={publicTurnAttackDefenseRollState.errorMessage}
        rotation={publicTurnAttackDefenseRollState.rotation}
        onTrigger={onTriggerPublicTurnAttackDefenseRoll}
        onClose={onClosePublicTurnAttackDefenseModal}
        onMinimize={() => setMinimizedBlockingModal('public_turn_attack_defense')}
      />

      <PublicTurnDeathSaveModal
        open={visiblePublicTurnDeathSave}
        prompt={pendingDeathSaveState?.prompt ?? null}
        phase={publicTurnDeathSaveRollState.phase}
        rollValue={publicTurnDeathSaveRollState.rollValue}
        summaryText={publicTurnDeathSaveSummary}
        errorMessage={publicTurnDeathSaveRollState.errorMessage}
        rotation={publicTurnDeathSaveRollState.rotation}
        onTrigger={onTriggerPublicTurnDeathSaveRoll}
        onClose={onClosePublicTurnDeathSaveModal}
        onMinimize={() => setMinimizedBlockingModal('public_turn_death_save')}
      />

      <PublicTurnOpposedModal
        open={visiblePublicTurnOpposed}
        prompt={pendingOpposedState?.prompt ?? null}
        plan={publicTurnOpposedPlan}
        phase={publicTurnOpposedRollState.phase}
        rollValue={publicTurnOpposedRollState.rollValue}
        result={publicTurnOpposedRollState.result}
        errorMessage={publicTurnOpposedRollState.errorMessage}
        rotation={publicTurnOpposedRollState.rotation}
        actionValue={publicTurnOpposedActionInput}
        speechValue={publicTurnOpposedSpeechInput}
        onActionChange={setPublicTurnOpposedActionInput}
        onSpeechChange={setPublicTurnOpposedSpeechInput}
        onPlan={() => void onPlanPublicTurnOpposed()}
        onTrigger={onTriggerPublicTurnOpposedRoll}
        onClose={onClosePublicTurnOpposedModal}
        onMinimize={() => setMinimizedBlockingModal('public_turn_opposed')}
      />

      <ActionCheckRollModal
        open={visibleReactionRoll}
        phase={reactionCheckRollState.phase}
        plan={reactionCheckRollState.plan}
        rollValue={reactionCheckRollState.rollValue}
        result={reactionCheckRollState.result}
        errorMessage={reactionCheckRollState.errorMessage}
        rotation={reactionCheckRollState.rotation}
        title="反应检定"
        subtitle="先确认眼前威胁，再掷骰决定你能否扛住这一击。"
        sourceLabel={pendingReactionState?.pending_reaction.source_label}
        threatenedConsequence={pendingReactionState?.pending_reaction.threatened_consequence}
        successHint={pendingReactionState?.pending_reaction.success_hint}
        failureHint={pendingReactionState?.pending_reaction.failure_hint}
        onTrigger={onTriggerReactionCheckRoll}
        onClose={onCloseReactionCheckRoll}
        onMinimize={() => setMinimizedBlockingModal('reaction_roll')}
      />

      <ActionCheckRollModal
        open={visibleBattleRoll}
        phase={battleRollState.phase}
        plan={battleRollState.plan}
        rollValue={battleRollState.rollValue}
        result={battleRollState.result}
        errorMessage={battleRollState.errorMessage}
        rotation={battleRollState.rotation}
        title={activeBattle?.pending_roll?.roll_kind === 'reaction' ? '战斗反应检定' : '战斗掷骰'}
        subtitle={activeBattle?.pending_roll?.check_task ?? '点击骰子结算当前战斗检定。'}
        sourceLabel={activeBattle?.pending_roll?.source_label ?? undefined}
        threatenedConsequence={activeBattle?.pending_roll?.threatened_consequence ?? undefined}
        successHint={activeBattle?.pending_roll?.success_hint ?? undefined}
        failureHint={activeBattle?.pending_roll?.failure_hint ?? undefined}
        onTrigger={onTriggerBattleRoll}
        onClose={onCloseBattleRoll}
        onMinimize={() => setMinimizedBlockingModal('battle_roll')}
      />

      {minimizedBlockingModal && (
        <div className="modal-restore-bar">
          <span>有未完成弹窗</span>
          <button type="button" onClick={restoreBlockingModal}>
            恢复处理
          </button>
        </div>
      )}

      <div className="time-notice-stack">
        {timeNotices.map((notice) => (
          <article key={notice.id} className="time-notice">
            {notice.text}
          </article>
        ))}
      </div>
    </main>
  );
}

export default App;

