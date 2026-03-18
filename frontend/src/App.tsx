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
import { PublicTurnPanel } from './components/PublicTurnPanel';
import { QuestInspectModal } from './components/QuestInspectModal';
import { QuestModal } from './components/QuestModal';
import { RoleInventoryModal } from './components/RoleInventoryModal';
import { RoleProfileModal } from './components/RoleProfileModal';
import { SceneEventCard } from './components/SceneEventCard';
import { SubZoneContextPanel } from './components/SubZoneContextPanel';
import { TeamPanel } from './components/TeamPanel';
import { ActionCheckPanel } from './components/ActionCheckPanel';
import { ActionCheckRollModal } from './components/ActionCheckRollModal';
import { AuthPanel } from './components/AuthPanel';
import { BattleModal } from './components/BattleModal';
import { BattleStartDialog } from './components/BattleStartDialog';
import {
  acceptQuest,
  bootstrapWorldMap,
  continueBattleAi,
  continuePublicTurn,
  checkEncounters,
  cancelPendingTurn,
  continuePendingTurn,
  continuePendingTurnStream,
  clearSave,
  debugGenerateQuest,
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
  sendTeamChat,
  pickSavePath,
  planActionCheck,
  presentEncounter,
  regenerateFate,
  rejectQuest,
  rejoinEncounter,
  resolveBattleRoll,
  resolvePublicTurnReaction,
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
  streamResolvePublicTurnReaction,
  toggleEncounterForce,
  trackQuest,
  toMapSnapshot,
  unequipInventoryItem,
  validateConfig,
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
  type BattleRollPrompt,
  type BattleRollResolution,
  type BattleSandboxState,
  type EncounterEntry,
  type EncounterState,
  type AreaSnapshot,
  type AppConfig,
  type ChatMessage,
  type ChatResponse,
  type ConsistencyIssue,
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
  type PlayerRuntimeData,
  type PlayerReactionCheck,
  type PlayerStaticData,
  type NpcRoleCard,
  type TemplateLibraryStatusResponse,
  type NpcChatResponse,
  type Position,
  type PublicTurnEntryType,
  type PublicTurnImpact,
  type PublicTurnResponse,
  type PublicTurnState,
  type ProviderConfigMap,
  type ProviderScopedConfig,
  type QuestState,
  type RenderResult,
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
type ChatState = 'idle' | 'sending' | 'streaming' | 'awaiting_reaction' | 'error';
type ChatMode = 'main' | 'npc';
type MainOutputStatus = 'idle' | 'streaming' | 'awaiting_reaction' | 'awaiting_archive' | 'error';
type MainOutput = {
  source_kind: 'main_turn' | 'system_output';
  reply_text: string;
  scene_events: SceneEvent[];
  archived_sub_zone_turn_id: string | null;
  main_turn_summary: MainTurnSummary | null;
  status: MainOutputStatus;
};
type ActionCheckPayload = {
  action_type: 'attack' | 'check' | 'item_use';
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
type PendingReactionState = {
  pending_turn_id: string;
  flow_kind: PendingTurnContinueResponse['flow_kind'];
  npc_role_id?: string | null;
  pending_reaction: PlayerReactionCheck;
};

function isPendingTurnContinueResponse(
  response: ChatResponse | PendingTurnContinueResponse | NpcChatResponse | PublicTurnResponse,
): response is PendingTurnContinueResponse {
  return 'status' in response && 'reply_text' in response;
}

function isChatTurnResponse(response: ChatResponse | PendingTurnContinueResponse): response is ChatResponse {
  return 'reply' in response;
}

function isNpcTurnResponse(response: NpcChatResponse | PendingTurnContinueResponse): response is NpcChatResponse {
  return 'dialogue_logs' in response;
}

function isPublicTurnResponse(
  response: PublicTurnResponse | PendingTurnContinueResponse,
): response is PublicTurnResponse {
  return 'public_turn_state' in response && 'phase' in response;
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
  const [lastActionInput, setLastActionInput] = useState('');
  const [lastSpeechInput, setLastSpeechInput] = useState('');
  const [actionInput, setActionInput] = useState('');
  const [speechInput, setSpeechInput] = useState('');
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

  const [debugCollapsed, setDebugCollapsed] = useState(true);
  const [debugEntries, setDebugEntries] = useState<ApiDebugEntry[]>([]);
  const [savePath, setSvPath] = useState<PathStatus | null>(null);
  const [templateLibraryStatus, setTemplateLibraryStatus] = useState<TemplateLibraryStatusResponse | null>(null);

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
  const [lastActionResult, setLastActionResult] = useState<ActionCheckResult | null>(null);
  const [actionCheckRollState, setActionCheckRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [reactionCheckRollState, setReactionCheckRollState] = useState<ActionCheckRollState>(DEFAULT_ACTION_CHECK_ROLL_STATE);
  const [pendingReactionState, setPendingReactionState] = useState<PendingReactionState | null>(null);
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

  const abortRef = useRef<AbortController | null>(null);
  const activeStreamRef = useRef<{ kind: 'main' } | { kind: 'npc'; npcId: string; previousMessages: ChatMessage[] } | null>(null);
  const announcedEncounterIdsRef = useRef<Set<string>>(new Set());
  const autoRejoinEncounterIdRef = useRef<string | null>(null);
  const pendingActionCheckRef = useRef<ActionCheckPayload | null>(null);
  const actionCheckPromiseRef = useRef<{ resolve: (result: ActionCheckResult | null) => void; reject: (error: Error) => void } | null>(null);
  const pendingReactionResponseRef = useRef<PendingTurnContinueResponse | null>(null);
  const actionInputRef = useRef<HTMLTextAreaElement | null>(null);

  const statusText = useMemo(() => {
    if (chatState === 'sending') return '发送中...';
    if (chatState === 'streaming') return '生成中...';
    if (chatState === 'awaiting_reaction') return '等待反应检定...';
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
  const publicTurnState: PublicTurnState = currentSubZone?.chat_context?.public_turn_state ?? defaultPublicTurnState;
  const publicTurnRound = publicTurnState.current_round ?? null;
  const publicTurnPhase = publicTurnRound?.phase ?? 'idle';
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
  const blockingModalOpen = Boolean(
    pendingQuest ||
      mapPromptDialogOpen ||
      aiWaiting ||
      actionCheckRollState.open ||
      reactionCheckRollState.open ||
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
    !blockingModalOpen;
  const canAutoAdvance = chatMode === 'main' && encounterEngaged && (chatState === 'idle' || chatState === 'error') && !blockingModalOpen;

  const tokenTotal = tokenUsage.total.total_tokens;
  const npcDisplayedMessages = activeNpcChat ? (npcChatMessages[activeNpcChat.npcId] ?? []) : [];
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
  const dialogueLogsToMessages = (role: NpcRoleCard): ChatMessage[] =>
    (role.dialogue_logs ?? []).map((item) => ({
      role: item.speaker === 'player' ? 'user' : 'assistant',
      content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
    }));
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
  const resetActionCheckRollState = () => {
    setActionCheckRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetReactionCheckRollState = () => {
    setReactionCheckRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
  };
  const resetBattleRollState = () => {
    setBattleRollState(DEFAULT_ACTION_CHECK_ROLL_STATE);
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

  useEffect(() => {
    if (!currentMainOutput || currentMainOutput.source_kind !== 'main_turn') return;
    const archivedTurnId = currentMainOutput.archived_sub_zone_turn_id;
    if (!archivedTurnId) return;
    const turns = currentSubZone?.chat_context?.recent_turns ?? [];
    if (!turns.some((turn) => turn.turn_id === archivedTurnId)) return;
    setCurrentMainOutput(null);
  }, [currentMainOutput, currentSubZone]);

  useEffect(() => {
    setPublicTurnImpacts([]);
  }, [currentSubZone?.sub_zone_id]);

  useEffect(() => {
    if (!sessionId || pendingReactionState || actionCheckRollState.open || reactionCheckRollState.open) return;
    void (async () => {
      try {
        const pending = await getCurrentPendingTurn(sessionId);
        if (!pending || pending.status !== 'awaiting_reaction' || !pending.pending_reaction) return;
        if (pending.flow_kind === 'main_chat') {
          setCurrentMainOutput({
            source_kind: 'main_turn',
            reply_text: pending.reply_text,
            scene_events: pending.scene_events,
            archived_sub_zone_turn_id: pending.archived_sub_zone_turn_id ?? null,
            main_turn_summary: pending.main_turn_summary ?? null,
            status: 'awaiting_reaction',
          });
          setShowFoldedMainSceneEvents(false);
        } else if (pending.flow_kind === 'public_turn') {
          applyPendingPublicTurnState(pending);
        } else if (pending.flow_kind === 'npc_chat') {
          applyPendingNpcTurnState(pending);
        }
        openPendingReaction(pending);
      } catch {
        // Ignore restore failures to avoid blocking the app boot flow.
      }
    })();
  }, [sessionId, pendingReactionState, actionCheckRollState.open, reactionCheckRollState.open]);

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

  const syncStateFromSave = async (sid: string = sessionId) => {
    try {
      const save = await getCurrentSave(report);
      if (save.session_id !== sid) return;
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
      setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
      setPlayerRuntimeState(
        save.player_runtime_data ?? {
          session_id: sid,
          current_position: save.map_snapshot?.player_position ?? DEFAULT_POSITION,
          updated_at: new Date().toISOString(),
        },
      );
      if (mapOpen) {
        const snapshot = toMapSnapshot(save);
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

        const [remoteStatic, remoteRuntime] = await Promise.all([getPlayerStatic(sid, report), getPlayerRuntime(sid, report)]);
        if (cancelled) return;
        setPlayerStaticState(remoteStatic);
        setPlayerRuntimeState(remoteRuntime);
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
    if (pendingQuest || mapPromptDialogOpen || aiWaiting || actionCheckRollState.open || encounterModalBusy || encounterModalOpen) {
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
          action_type: payload.action_type,
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
          action_type: payload.action_type,
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
              action_type: payload.action_type,
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
              let finalResponse: PendingTurnContinueResponse | null = null;
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
                  onTurnState: () => undefined,
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
                      npc_role_id: payload.npc_role_id ?? null,
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
                  onEnd: ({ archived_sub_zone_turn_id }) => {
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
              const resolvedResponse = finalResponse as PendingTurnContinueResponse | null;
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
              if (resolvedResponse.status === 'completed') {
                setCurrentMainOutput({
                  source_kind: 'main_turn',
                  reply_text: resolvedResponse.reply_text,
                  scene_events: resolvedResponse.scene_events,
                  archived_sub_zone_turn_id: resolvedResponse.archived_sub_zone_turn_id ?? null,
                  main_turn_summary: null,
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
              archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
              npc_role_id: null,
            };
            setPublicTurnImpacts(response.impacts ?? []);
            setReactionCheckRollState((current) => ({
              ...current,
              phase: 'resolved',
              result: synthesizedResult,
              errorMessage: '',
            }));
            applyPublicTurnResponse(response, { status: response.round_completed ? 'awaiting_archive' : 'idle' });
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
      if (response.status === 'awaiting_reaction' && response.pending_reaction) {
        handlePendingReactionRequired(response);
        return;
      }
      if (response.status === 'completed') {
        clearPlayerInput();
      }
      abortRef.current = null;
      activeStreamRef.current = null;
      setChatState('idle');
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
      status: 'awaiting_reaction',
    });
    setMainLiveProgress([]);
    if (response.current_zone_metric) {
      setCurrentZoneMetric(response.current_zone_metric);
    }
  };

  const applyPublicTurnResponse = (
    response: PublicTurnResponse,
    options?: { status?: MainOutputStatus },
  ) => {
    setPublicTurnImpacts(response.impacts ?? []);
    setCurrentMainOutput({
      source_kind: 'main_turn',
      reply_text: response.narration,
      scene_events: response.scene_events,
      archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
      main_turn_summary: null,
      status: options?.status ?? (response.round_completed ? 'awaiting_archive' : 'idle'),
    });
    setMainLiveProgress([]);
  };

  const applyPendingPublicTurnState = (response: PendingTurnContinueResponse) => {
    setCurrentMainOutput({
      source_kind: 'main_turn',
      reply_text: response.reply_text,
      scene_events: response.scene_events,
      archived_sub_zone_turn_id: response.archived_sub_zone_turn_id ?? null,
      main_turn_summary: null,
      status: 'awaiting_reaction',
    });
    setMainLiveProgress([]);
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

  const onToggleEncounterForce = async () => {
    try {
      const result = await toggleEncounterForce({ session_id: sessionId }, report);
      setConfigHint(result.enabled ? '已开启 100% 遭遇开关。' : '已关闭 100% 遭遇开关。');
      await refreshEncounterState(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换遭遇调试开关失败');
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
      let streamFailed = false;
      setCurrentMainOutput({
        source_kind: 'main_turn',
        reply_text: '',
        scene_events: [],
        archived_sub_zone_turn_id: null,
        main_turn_summary: null,
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
            onTurnState: () => undefined,
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
                npc_role_id: payload.npc_role_id ?? null,
              });
            },
            onError: (message) => {
              streamFailed = true;
              setError(message);
              setChatState('error');
              abortRef.current = null;
              activeStreamRef.current = null;
            },
            onEnd: ({ archived_sub_zone_turn_id, round_completed }) => {
              if (streamFailed) {
                return;
              }
              abortRef.current = null;
              activeStreamRef.current = null;
              setMainLiveProgress([]);
              setCurrentMainOutput({
                source_kind: 'main_turn',
                reply_text: streamedReply,
                scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                main_turn_summary: null,
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
      if (isPendingTurnContinueResponse(response) && response.status === 'awaiting_reaction') {
        handlePendingReactionRequired(response);
        return;
      }
      if (!isPublicTurnResponse(response)) {
        throw new Error('公开回合响应类型异常');
      }
      applyPublicTurnResponse(response);
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

  const onSend = async () => {
    if (blockingModalOpen) return;
    const actionDescription = actionInput.trim();
    const speechDescription = speechInput.trim();
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };
    const applyPublicTurnStreamState = (replyText: string, sceneEvents: SceneEvent[], status: MainOutputStatus = 'streaming') => {
      setCurrentMainOutput({
        source_kind: 'main_turn',
        reply_text: replyText,
        scene_events: sceneEvents,
        archived_sub_zone_turn_id: null,
        main_turn_summary: null,
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
              onTurnState: () => undefined,
              onDelta: (delta) => {
                streamedReply = `${streamedReply}${delta}`;
                applyPublicTurnStreamState(streamedReply, streamedSceneEvents, 'streaming');
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
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onError: (message) => {
                streamFailed = true;
                setError(message);
                setChatState('error');
                abortRef.current = null;
                activeStreamRef.current = null;
              },
              onEnd: ({ archived_sub_zone_turn_id, round_completed }) => {
                if (streamFailed) {
                  return;
                }
                abortRef.current = null;
                activeStreamRef.current = null;
                setMainLiveProgress([]);
                setCurrentMainOutput({
                  source_kind: 'main_turn',
                  reply_text: streamedReply,
                  scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                  archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                  main_turn_summary: null,
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
        if (isPendingTurnContinueResponse(response) && response.status === 'awaiting_reaction') {
          handlePendingReactionRequired(response);
          return;
        }
        if (!isPublicTurnResponse(response)) {
          throw new Error('公开回合响应类型异常');
        }
        applyPublicTurnResponse(response);
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
      if (!actionDescription && !speechDescription) {
        setError('当前回合至少需要输入行为或语言。');
        return;
      }
      setLastActionInput(actionDescription);
      setLastSpeechInput(speechDescription);
      setError('');
      setMainLiveProgress([]);
      setShowFoldedMainSceneEvents(false);
      const sourcePhase = publicTurnRound?.awaiting_player_action_phase ?? publicTurnRound?.phase ?? publicTurnPhase;
      if (config.stream) {
        setChatState('streaming');
        const controller = new AbortController();
        abortRef.current = controller;
        activeStreamRef.current = { kind: 'main' };
        let streamedReply = '';
        let streamedSceneEvents: SceneEvent[] = [];
        let streamedImpacts: PublicTurnImpact[] = [];
        let streamFailed = false;
        applyPublicTurnStreamState('', [], 'streaming');
        try {
          await streamContinuePublicTurn(
            {
              session_id: sessionId,
              action_submission: {
                actor_id: playerStatic.player_id,
                action_text: actionDescription,
                speech_text: speechDescription,
                source_phase: sourcePhase,
                forced_first: false,
              },
              config: effectiveConfig,
            },
            {
              onPhase: (event) => {
                setMainLiveProgress((prev) => upsertLiveProgress(prev, toPhaseProgressEntry(event)));
              },
              onTurnState: () => undefined,
              onDelta: (delta) => {
                streamedReply = `${streamedReply}${delta}`;
                applyPublicTurnStreamState(streamedReply, streamedSceneEvents, 'streaming');
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
                  npc_role_id: payload.npc_role_id ?? null,
                });
              },
              onError: (message) => {
                streamFailed = true;
                setError(message);
                setChatState('error');
                abortRef.current = null;
                activeStreamRef.current = null;
              },
              onEnd: ({ archived_sub_zone_turn_id, round_completed }) => {
                if (streamFailed) {
                  return;
                }
                abortRef.current = null;
                activeStreamRef.current = null;
                setMainLiveProgress([]);
                setCurrentMainOutput({
                  source_kind: 'main_turn',
                  reply_text: streamedReply,
                  scene_events: filterMainOutputSceneEvents(streamedSceneEvents),
                  archived_sub_zone_turn_id: archived_sub_zone_turn_id ?? null,
                  main_turn_summary: null,
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
          clearPlayerInput();
          await finalizePublicTurnAfterResponse(streamedSceneEvents);
        } catch (e) {
          abortRef.current = null;
          activeStreamRef.current = null;
          setError(e instanceof Error ? e.message : '公开回合提交失败');
          setChatState('error');
        }
        return;
      }

      try {
        setChatState('sending');
        const response = await continuePublicTurn(
          {
            session_id: sessionId,
            action_submission: {
              actor_id: playerStatic.player_id,
              action_text: actionDescription,
              speech_text: speechDescription,
              source_phase: sourcePhase,
              forced_first: false,
            },
            config: effectiveConfig,
          },
          report,
        );
        if (isPendingTurnContinueResponse(response) && response.status === 'awaiting_reaction') {
          handlePendingReactionRequired(response);
          return;
        }
        if (!isPublicTurnResponse(response)) {
          throw new Error('公开回合响应类型异常');
        }
        applyPublicTurnResponse(response);
        clearPlayerInput();
        await finalizePublicTurnAfterResponse(response.scene_events ?? []);
        setChatState('idle');
      } catch (e) {
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
      let actionCheckResult: ActionCheckResult | null = null;
      const shouldLeaveAfterReply = shouldLeaveNpcChatByIntent(actionDescription, speechDescription);
      try {
        actionCheckResult = await performActionCheckWithRoll({
          action_type: 'check',
          action_prompt: `npc_id=${activeNpcChat.npcId}; action=${actionDescription || '-'}; speech=${speechDescription || '-'}`,
          actor_role_id: playerStatic.player_id,
          source_context: 'npc_chat',
          post_close_output: 'suppress',
          resolution_context: 'embedded',
          skip_if_no_check: true,
        });
        if (actionCheckResult) {
          setLastActionResult(actionCheckResult);
          pushTimeNotice(actionCheckResult.time_spent_min, `NPC交互检定:${activeNpcChat.npcName}`);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'NPC交互检定失败');
        return;
      }
      const structuredInput = buildStructuredPlayerInput(actionDescription, speechDescription, actionCheckResult);
      const previewInput = buildPreviewPlayerInput(actionDescription, speechDescription, actionCheckResult);
      setLastActionInput(actionDescription);
      setLastSpeechInput(speechDescription);
      setError('');
      const speakReason = `发言:${activeNpcChat.npcName}`;
      if (config.stream) {
        setChatState('streaming');
        const controller = new AbortController();
        abortRef.current = controller;
        const previousNpcMessages = npcChatMessages[activeNpcChat.npcId] ?? [];
        activeStreamRef.current = { kind: 'npc', npcId: activeNpcChat.npcId, previousMessages: previousNpcMessages };
        let rolledBack = false;
        let streamedNpcSceneEvents: SceneEvent[] = [];
        setNpcLiveProgress((prev) => ({ ...prev, [activeNpcChat.npcId]: [] }));
        setNpcChatMessages((prev) => {
          const current = prev[activeNpcChat.npcId] ?? [];
          return {
            ...prev,
            [activeNpcChat.npcId]: [...current, { role: 'user', content: previewInput }, { role: 'assistant', content: '' }],
          };
        });
        try {
          await streamNpcChat(
            {
              session_id: sessionId,
              npc_role_id: activeNpcChat.npcId,
              player_message: structuredInput,
              config,
            },
            {
              onDelta: (delta) => {
                setNpcChatMessages((prev) => {
                  const current = [...(prev[activeNpcChat.npcId] ?? [])];
                  if (current.length === 0) return prev;
                  const last = current[current.length - 1];
                  if (last.role !== 'assistant') return prev;
                  current[current.length - 1] = { ...last, content: `${last.content}${delta}` };
                  return { ...prev, [activeNpcChat.npcId]: current };
                });
              },
              onPhase: (event) => {
                setNpcLiveProgress((prev) => ({
                  ...prev,
                  [activeNpcChat.npcId]: upsertLiveProgress(prev[activeNpcChat.npcId] ?? [], toPhaseProgressEntry(event)),
                }));
              },
              onToolUpdate: (event) => {
                setNpcLiveProgress((prev) => ({
                  ...prev,
                  [activeNpcChat.npcId]: upsertLiveProgress(prev[activeNpcChat.npcId] ?? [], toToolProgressEntry(event)),
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
                  npc_role_id: payload.npc_role_id ?? activeNpcChat.npcId,
                });
              },
              onError: (message) => {
                setError(message);
                restoreAbortedNpcStream();
                activeStreamRef.current = null;
                if (!rolledBack) {
                  clearNpcLiveProgress(activeNpcChat.npcId);
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
                  [activeNpcChat.npcId]: (logs ?? []).map((item) => ({
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
                clearNpcLiveProgress(activeNpcChat.npcId);
                if (rolledBack) {
                  return;
                }
                setChatState('idle');
                void (async () => {
                  clearPlayerInput();
                  await syncEncounterLaneAfterSceneEvents(streamedNpcSceneEvents);
                  await refreshTokenUsage(sessionId);
                  await refreshNpcPool(npcPoolSearch);
                  await runNarrativeChecks('random_dialog');
                  if (shouldLeaveAfterReply) {
                    onLeaveNpcChat();
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
            clearNpcLiveProgress(activeNpcChat.npcId);
            setError(e instanceof Error ? e.message : 'NPC流式聊天失败');
            window.alert('本轮生成已作废');
            setChatState('idle');
          }
        }
      } else {
        setChatState('sending');
        try {
          const response = await npcChat(
            {
              session_id: sessionId,
              npc_role_id: activeNpcChat.npcId,
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
            [activeNpcChat.npcId]: (response.dialogue_logs ?? []).map((item) => ({
              role: item.speaker === 'player' ? 'user' : 'assistant',
              content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
            })),
          }));
          clearPlayerInput();
          pushTimeNotice(response.time_spent_min, speakReason);
          await refreshTokenUsage(sessionId);
          await refreshNpcPool(npcPoolSearch);
          await runNarrativeChecks('random_dialog');
          if (shouldLeaveAfterReply) {
            onLeaveNpcChat();
          }
          setChatState('idle');
        } catch (e) {
          setError(e instanceof Error ? e.message : 'NPC聊天失败');
          setChatState('error');
        }
      }
      return;
    }
    let actionCheckResult: ActionCheckResult | null = null;
    try {
      actionCheckResult = await performActionCheckWithRoll({
        action_type: 'check',
        action_prompt: `main_chat; action=${actionDescription || '-'}; speech=${speechDescription || '-'}`,
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
    await submitMainChatTurn({ actionDescription, speechDescription, actionCheckResult });
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

  const onOpenInventory = () => {
    setInventoryOpen(true);
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

  const onOpenActionPanel = async () => {
    setActionPanelOpen(true);
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
    try {
      const role = await getRoleCard(sessionId, npcId, report);
      const fromSave = dialogueLogsToMessages(role);
      setNpcChatMessages((prev) => ({
        ...prev,
        [npcId]:
          fromSave.length > 0
            ? fromSave
            : [{ role: 'system', content: `你已接近 ${npcName}，可以只输入动作或只输入语言开始交互。` }],
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '进入 NPC 单聊失败');
    }
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
      const response = await fillTemplateLibrary({ session_id: sessionId, config }, report);
      setTemplateLibraryStatus(response);
      setConfigHint(
        `模板库已更新：新增 物品${response.appended_item_definition_ids.length} / 装备${response.appended_equipment_definition_ids.length} / 交互${response.appended_interactable_template_ids.length}，补空字段 ${response.updated_item_definition_ids.length + response.updated_equipment_definition_ids.length + response.updated_interactable_template_ids.length} 处。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 填充模板库失败');
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
    } catch (e) {
      setError(e instanceof Error ? e.message : '清空存档失败');
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

  return (
    <main className="app-shell chat-shell">
      <DebugPanel
        collapsed={debugCollapsed}
        onToggle={() => setDebugCollapsed((prev) => !prev)}
        entries={debugEntries}
        configPath={configPath}
        savePath={savePath}
        onEnableMap={onEnableMap}
        onOpenPlayerPanel={onOpenPlayerPanel}
        onOpenInventory={onOpenInventory}
        onOpenNpcPool={() => void onOpenNpcPool()}
        onOpenTeamPanel={() => void onOpenTeamPanel()}
        onGenerateDebugTeammate={() => void onGenerateDebugTeamMember()}
        onOpenBattleStart={onOpenBattleStart}
        onFillTemplateLibrary={() => void onFillTemplateLibrary()}
        onOpenActionPanel={() => void onOpenActionPanel()}
        onGenerateQuest={() => void onGenerateQuest()}
        onGenerateFate={() => void onGenerateFate()}
        onRegenerateFate={() => void onRegenerateFate()}
        onOpenFatePanel={onOpenFatePanel}
        onShowConsistencyStatus={() => void onShowConsistencyStatus()}
        onRunConsistencyCheck={() => void onRunConsistencyCheck()}
        onToggleEncounterForce={() => void onToggleEncounterForce()}
        encounterForceEnabled={encounterState.debug_force_trigger}
        onSelectSaveFile={(file) => void onSelectSaveFile(file)}
        onClearSave={() => void onClearSave()}
        onPickSavePath={() => void onPickSavePath()}
        templateLibraryStatus={templateLibraryStatus}
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
                  <p>{currentMainOutput?.source_kind === 'system_output' ? '系统反馈' : '临时输出，归档后会自动收起'}</p>
                </header>
                {!currentMainOutput?.reply_text.trim() && (currentMainOutput?.scene_events.length ?? 0) === 0 && (
                  <p className="hint">主聊天历史已经收进上方地区上下文，这里只显示当前轮输出或系统反馈。</p>
                )}
                {currentMainOutput?.reply_text.trim() && (
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
                )}
                {mainOutputVisibleEvents.map((event) => (
                  <SceneEventCard key={event.event_id} event={event} />
                ))}
                {mainOutputFoldedEvents.length > 0 && (
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
                  busy={chatState === 'sending' || chatState === 'streaming' || blockingModalOpen}
                  godMode={godMode}
                  impacts={publicTurnRound?.impacts ?? publicTurnImpacts}
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
                        disabled={chatState === 'sending' || chatState === 'streaming' || blockingModalOpen}
                      />
                    </div>
                    <div className="composer-input-block">
                      <label htmlFor="speech-input">语言描述</label>
                      <textarea
                        id="speech-input"
                        value={speechInput}
                        onChange={(e) => setSpeechInput(e.target.value)}
                        placeholder={pendingQuest ? '请先处理当前任务弹窗。' : '例如：我低声说：“我想打听这里最近的怪事。”'}
                        disabled={chatState === 'sending' || chatState === 'streaming' || blockingModalOpen}
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
        chatBlocked={blockingModalOpen || encounterEngaged}
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
        busy={battleStartBusy}
        currentZoneName={currentZone?.name ?? areaSnapshot?.current_zone_id ?? '未知大区块'}
        currentSubZoneName={currentSubZone?.name ?? areaSnapshot?.current_sub_zone_id ?? '未知子区块'}
        subZoneDescription={currentSubZone?.description ?? ''}
        dangerScore={currentZoneMetric?.danger_score}
        reputationScore={currentZoneMetric?.reputation_score}
        onClose={() => setBattleStartDialogOpen(false)}
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
        quest={pendingQuest}
        busy={questModalBusy}
        onAccept={(questId) => void onAcceptQuest(questId)}
        onReject={(questId) => void onRejectQuest(questId)}
      />

      <EncounterModal
        encounter={pendingQuest ? null : encounterModalEncounter}
        roleCards={npcPoolItems}
        busy={encounterModalBusy}
        onContinue={onCloseEncounterModal}
      />

      <BattleModal
        open={Boolean(activeBattle)}
        battle={activeBattle}
        busy={battleBusy}
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
        open={reactionCheckRollState.open}
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
      />

      <ActionCheckRollModal
        open={battleRollState.open}
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
      />

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

