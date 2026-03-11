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
import { MapPanel } from './components/MapPanel';
import { NpcPoolPanel } from './components/NpcPoolPanel';
import { PlayerPanel } from './components/PlayerPanel';
import { QuestInspectModal } from './components/QuestInspectModal';
import { QuestModal } from './components/QuestModal';
import { RoleInventoryModal } from './components/RoleInventoryModal';
import { RoleProfileModal } from './components/RoleProfileModal';
import { SceneEventCard } from './components/SceneEventCard';
import { SubZoneContextPanel } from './components/SubZoneContextPanel';
import { TeamPanel } from './components/TeamPanel';
import { ActionCheckPanel } from './components/ActionCheckPanel';
import { ActionCheckRollModal } from './components/ActionCheckRollModal';
import {
  acceptQuest,
  checkEncounters,
  clearSave,
  debugGenerateQuest,
  discoverConfigModels,
  discoverAreaInteractions,
  describeBehavior,
  equipInventoryItem,
  evaluateAllQuests,
  evaluateFate,
  generateFate,
  generateRegions,
  generateDebugTeammate,
  getConsistencyStatus,
  getGameLogs,
  getGameLogSettings,
  getConfigPath,
  getConfigModelProfile,
  getStoredConfig,
  getCurrentArea,
  getCurrentSave,
  getFateState,
  getPendingEncounters,
  getPlayerRuntime,
  getPlayerStatic,
  getQuestState,
  getRoleCard,
  getRolePool,
  getTeamState,
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
  sendTeamChat,
  pickConfigPath,
  pickSavePath,
  planActionCheck,
  presentEncounter,
  regenerateFate,
  rejectQuest,
  rejoinEncounter,
  runActionCheck,
  moveToSubZone,
  renderWorldMap,
  runConsistencyCheck,
  saveConfig,
  sendChat,
  setGameLogSettings,
  setPlayerRuntime,
  setPlayerStatic,
  streamChat,
  streamNpcChat,
  toggleEncounterForce,
  trackQuest,
  toMapSnapshot,
  unequipInventoryItem,
  validateConfig,
} from './services/api';
import {
  defaultPlayerStaticData,
  defaultConfig,
  defaultEncounterState,
  defaultFateState,
  defaultQuestState,
  defaultTeamState,
  defaultWorldState,
  type ActionCheckPlan,
  type ApiDebugEntry,
  type ActionCheckResult,
  type EncounterEntry,
  type EncounterState,
  type AreaSnapshot,
  type AppConfig,
  type ChatMessage,
  type ConsistencyIssue,
  type FateState,
  type GameLogEntry,
  type GlobalStorySnapshot,
  type InventoryOwnerRef,
  type MapSnapshot,
  type ModelCapabilityInfo,
  type PathStatus,
  type PlayerRuntimeData,
  type PlayerStaticData,
  type NpcRoleCard,
  type Position,
  type QuestState,
  type RenderResult,
  type SaveFile,
  type SceneEvent,
  type SubZoneReputationEntry,
  type TeamChatReply,
  type TeamState,
  type TokenUsageSummary,
} from './types/app';

type View = 'boot' | 'config' | 'chat';
type ChatState = 'idle' | 'sending' | 'streaming' | 'error';
type ChatMode = 'main' | 'npc';
type MainOutputStatus = 'idle' | 'streaming' | 'awaiting_archive' | 'error';
type MainOutput = {
  source_kind: 'main_turn' | 'system_output';
  reply_text: string;
  scene_events: SceneEvent[];
  archived_sub_zone_turn_id: string | null;
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
  'reputation_update',
  'encounter_started',
  'encounter_background',
  'encounter_situation_update',
  'encounter_progress',
  'encounter_resolution',
]);

function selectCurrentReputation(save: SaveFile): SubZoneReputationEntry | null {
  const subZoneId = save.area_snapshot?.current_sub_zone_id ?? null;
  if (!subZoneId) return null;
  return save.reputation_state?.entries?.find((item) => item.sub_zone_id === subZoneId) ?? null;
}

function applyModelProfile(config: AppConfig, profile: ModelCapabilityInfo | null): AppConfig {
  if (!profile) {
    return { ...config, runtime: {} };
  }
  const runtime: AppConfig['runtime'] = {};
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
  return { ...config, runtime };
}

function resetProviderSelection(config: AppConfig, updates: Partial<AppConfig>): AppConfig {
  return {
    ...config,
    ...updates,
    model: '',
    runtime: {},
  };
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
  const [view, setView] = useState<View>('boot');
  const [configReturnView, setConfigReturnView] = useState<View>('boot');
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [currentMainOutput, setCurrentMainOutput] = useState<MainOutput | null>(null);
  const [npcChatMessages, setNpcChatMessages] = useState<Record<string, ChatMessage[]>>({});
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

  const [mapEnabled, setMapEnabled] = useState(false);
  const [mapPromptDialogOpen, setMapPromptDialogOpen] = useState(false);
  const [mapWorldPrompt, setMapWorldPrompt] = useState('');
  const [mapPromptInput, setMapPromptInput] = useState('');
  const [mapOpen, setMapOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [areaSnapshot, setAreaSnapshot] = useState<AreaSnapshot | null>(null);
  const [currentReputation, setCurrentReputation] = useState<SubZoneReputationEntry | null>(null);
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

  const abortRef = useRef<AbortController | null>(null);
  const configFileInputRef = useRef<HTMLInputElement | null>(null);
  const announcedEncounterIdsRef = useRef<Set<string>>(new Set());
  const autoRejoinEncounterIdRef = useRef<string | null>(null);
  const pendingActionCheckRef = useRef<ActionCheckPayload | null>(null);
  const actionCheckPromiseRef = useRef<{ resolve: (result: ActionCheckResult | null) => void; reject: (error: Error) => void } | null>(null);
  const actionInputRef = useRef<HTMLTextAreaElement | null>(null);

  const statusText = useMemo(() => {
    if (chatState === 'sending') return '发送中...';
    if (chatState === 'streaming') return '生成中...';
    if (chatState === 'error') return `错误: ${error}`;
    return '就绪';
  }, [chatState, error]);

  useEffect(() => {
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
    pendingQuest || mapPromptDialogOpen || aiWaiting || actionCheckRollState.open || encounterModalBusy || encounterModalOpen,
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
    options?: { archivedSubZoneTurnId?: string | null; status?: MainOutputStatus },
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
    setCurrentMainOutput({
      source_kind: sourceKind,
      reply_text: replyText,
      scene_events: visibleSceneEvents,
      archived_sub_zone_turn_id: options?.archivedSubZoneTurnId ?? null,
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

  useEffect(() => {
    if (!currentMainOutput || currentMainOutput.source_kind !== 'main_turn') return;
    const archivedTurnId = currentMainOutput.archived_sub_zone_turn_id;
    if (!archivedTurnId) return;
    const turns = currentSubZone?.chat_context?.recent_turns ?? [];
    if (!turns.some((turn) => turn.turn_id === archivedTurnId)) return;
    setCurrentMainOutput(null);
  }, [currentMainOutput, currentSubZone]);

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

  const refreshTokenUsage = async (sid: string = sessionId) => {
    try {
      const usage = await getTokenUsage(sid, report);
      setTokenUsage(usage);
    } catch {
      // Ignore token usage refresh failure.
    }
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
        ['encounter_started', 'encounter_background', 'encounter_progress', 'encounter_resolution', 'encounter_situation_update'].includes(event.kind),
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
    try {
      const cachedPrompt = window.localStorage.getItem(MAP_PROMPT_STORAGE_KEY) ?? '';
      if (cachedPrompt) {
        setMapPromptInput(cachedPrompt);
        setMapWorldPrompt(cachedPrompt);
      }
    } catch {
      // Ignore localStorage failures.
    }
  }, []);

  const loadStoredConfig = async (pathStatus: PathStatus | null): Promise<'loaded' | 'missing' | 'error'> => {
    if (!pathStatus?.exists) {
      setHasStoredConfig(false);
      return 'missing';
    }
    try {
      const stored = await getStoredConfig(report);
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
    void (async () => {
      const [cfgPathResult, svPathResult, saveResult] = await Promise.allSettled([
        getConfigPath(report),
        getSavePath(report),
        getCurrentSave(report),
      ]);

      if (cfgPathResult.status === 'fulfilled') {
        setCfgPath(cfgPathResult.value);
        await loadStoredConfig(cfgPathResult.value);
      } else {
        setHasStoredConfig(false);
      }

      if (svPathResult.status === 'fulfilled') {
        setSvPath(svPathResult.value);
      }

      if (saveResult.status !== 'fulfilled') {
        return;
      }

      try {
        const save = saveResult.value;
        setMapSnapshot(toMapSnapshot(save));
        setAreaSnapshot(save.area_snapshot ?? null);
        setCurrentReputation(selectCurrentReputation(save));
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
        setPlayerStaticState(remoteStatic);
        setPlayerRuntimeState(remoteRuntime);
        if (!(save.area_snapshot?.sub_zones?.length ?? 0)) {
          try {
            const area = await getCurrentArea(sid, report);
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
        setQuestState(questResponse.quest_state ?? defaultQuestState);
        setEncounterState(encounterResponse.encounter_state ?? defaultEncounterState);
        setFateState(fateResponse.fate_state ?? defaultFateState);
        setTokenUsage(usage);
      } catch {
        // Ignore boot-time failures; user can continue with manual setup.
      }
    })();
  }, []);

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
    setConfigDraft(hasStoredConfig ? config : defaultConfig);
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onOpenConfigFromChat = () => {
    setConfigReturnView('chat');
    setConfigDraft(config);
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(true);
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onLoadConfigFile = async (file: File) => {
    const text = await file.text();
    setError('');
    setConfigHint('');
    try {
      const parsed = JSON.parse(text) as unknown;
      const result = await validateConfig(parsed, report);
      if (!result.valid) {
        setError(`配置校验失败: ${formatValidateErrors(result.errors)}`);
        setView('config');
        return;
      }
      const normalized = result.normalized_config ?? defaultConfig;
      setConfigDraft(normalized);
      setConfigModels([]);
      setConfigProfile(null);
      setManualModelMode(true);
      setConfigHint('本地配置校验通过，请确认后点击“校验并进入聊天”。');
      setView('config');
    } catch (e) {
      setError(`JSON 格式错误: ${e instanceof Error ? e.message : '读取配置失败'}`);
      setView('config');
    }
  };

  const onPickConfigPath = async () => {
    try {
      const path = await pickConfigPath(report);
      setCfgPath(path);
      const loadResult = await loadStoredConfig(path);
      if (loadResult === 'loaded') {
        setConfigHint(`配置路径已更新，并已加载已有配置: ${path.path}`);
      } else if (loadResult === 'missing') {
        setConfigHint(`配置路径已更新，新路径下暂未发现配置文件: ${path.path}`);
      } else {
        setConfigHint(`配置路径已更新，但读取已有配置失败，请检查配置文件内容: ${path.path}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '配置文件夹选择失败');
    }
  };

  const onConfigProviderChange = (provider: AppConfig['provider']) => {
    setConfigDraft((prev) => resetProviderSelection(prev, { provider }));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(false);
    setError('');
    setConfigHint('');
  };

  const onConfigApiKeyChange = (api_key: string) => {
    setConfigDraft((prev) => resetProviderSelection(prev, { api_key }));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(false);
    setError('');
    setConfigHint('');
  };

  const onConfigBaseUrlChange = (base_url_override: string) => {
    setConfigDraft((prev) => resetProviderSelection(prev, { base_url_override }));
    setConfigModels([]);
    setConfigProfile(null);
    setManualModelMode(false);
    setError('');
    setConfigHint('');
  };

  const onConfigModelChange = (model: string) => {
    setConfigDraft((prev) => ({ ...prev, model }));
    setError('');
    setConfigHint('');
  };

  const onConfigRuntimeChange = (key: keyof AppConfig['runtime'], rawValue: string) => {
    const value = rawValue.trim();
    setConfigDraft((prev) => ({
      ...prev,
      runtime: {
        ...prev.runtime,
        [key]: value ? Number(value) : undefined,
      },
    }));
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
      const normalized = result.normalized_config ?? configDraft;
      await saveConfig(normalized, report);
      const latestPath = await getConfigPath(report);
      setCfgPath(latestPath);
      setConfig(normalized);
      setConfigDraft(normalized);
      setHasStoredConfig(true);
      setView('chat');
      setChatState('idle');
      setConfigHint('配置已保存到后端路径。');
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
    await syncEncounterLaneAfterSceneEvents(mirroredEvents);
    return encounterStarted;
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
    if (!passiveTurn) {
      clearPlayerInput();
    }
    setError('');
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };

    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;
      let streamedSceneEvents: SceneEvent[] = [];
      let streamedReply = '';

      setCurrentMainOutput({
        source_kind: 'main_turn',
        reply_text: '',
        scene_events: [],
        archived_sub_zone_turn_id: null,
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
            onError: (message) => {
              setError(message);
              setCurrentMainOutput((prev) => (prev ? { ...prev, status: 'error' } : prev));
              setChatState('error');
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
            onEnd: ({ archived_sub_zone_turn_id }) => {
              abortRef.current = null;
              if (streamedReply && isAlreadyThereHint(streamedReply)) {
                showAlreadyTherePopup(streamedReply);
                setCurrentMainOutput(null);
              } else {
                setMainOutput('main_turn', streamedReply, streamedSceneEvents, {
                  archivedSubZoneTurnId: archived_sub_zone_turn_id ?? null,
                  status: 'awaiting_archive',
                });
              }
              setChatState('idle');
              void (async () => {
                await syncEncounterLaneAfterSceneEvents(streamedSceneEvents);
                await refreshAreaSnapshot();
                await refreshTokenUsage(sessionId);
                await runNarrativeChecks('random_dialog');
              })();
            },
          },
          controller.signal,
          report,
        );
      } catch (e) {
        abortRef.current = null;
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '流式请求失败');
          setCurrentMainOutput((prev) => (prev ? { ...prev, status: 'error' } : prev));
          setChatState('error');
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
      await syncEncounterLaneAfterSceneEvents(response.scene_events ?? []);
      setMainOutput('main_turn', response.reply.content, response.scene_events ?? [], {
        archivedSubZoneTurnId: response.archived_sub_zone_turn_id ?? null,
        status: 'awaiting_archive',
      });
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
      setChatState('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
      setCurrentMainOutput((prev) => (prev?.source_kind === 'main_turn' ? { ...prev, status: 'error' } : prev));
      setChatState('error');
    }
  };

  const onSend = async () => {
    if (blockingModalOpen) return;
    const actionDescription = actionInput.trim();
    const speechDescription = speechInput.trim();
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
      clearPlayerInput();
      setError('');
      const speakReason = `发言:${activeNpcChat.npcName}`;
      if (config.stream) {
        setChatState('streaming');
        const controller = new AbortController();
        abortRef.current = controller;
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
              onError: (message) => {
                setError(message);
                setChatState('error');
              },
              onTimeSpent: (minutes) => {
                pushTimeNotice(minutes, speakReason);
              },
              onDialogueLogs: (logs) => {
                setNpcChatMessages((prev) => ({
                  ...prev,
                  [activeNpcChat.npcId]: (logs ?? []).map((item) => ({
                    role: item.speaker === 'player' ? 'user' : 'assistant',
                    content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
                  })),
                }));
              },
              onEnd: () => {
                setChatState('idle');
                void (async () => {
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
          if (!controller.signal.aborted) {
            setError(e instanceof Error ? e.message : 'NPC流式聊天失败');
            setChatState('error');
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
          setNpcChatMessages((prev) => ({
            ...prev,
            [activeNpcChat.npcId]: (response.dialogue_logs ?? []).map((item) => ({
              role: item.speaker === 'player' ? 'user' : 'assistant',
              content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
            })),
          }));
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

  const onStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
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
    setCurrentMainOutput(null);
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
      setError(e instanceof Error ? e.message : '邀请 NPC 入队失败');
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

  const onTeamChat = async (playerMessage: string) => {
    try {
      setTeamChatBusy(true);
      const response = await sendTeamChat({ session_id: sessionId, player_message: playerMessage, config }, report);
      setTeamState(response.team_state ?? defaultTeamState);
      setTeamChatReplies(response.replies ?? []);
      pushTimeNotice(response.time_spent_min, '队伍聊天');
      await refreshNpcPool(npcPoolSearch);
      await runNarrativeChecks('random_dialog');
    } catch (e) {
      setError(e instanceof Error ? e.message : '队伍聊天失败');
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
      await refreshAreaSnapshot();
      await runNarrativeChecks('random_move');
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
      await refreshAreaSnapshot();
    } catch (e) {
      setError(e instanceof Error ? e.message : '发现交互失败');
    }
  };

  const onUseAreaItem = async (interactionId: string, itemName: string) => {
    if (encounterEngaged) {
      setError('遭遇进行中，请直接在主聊天描述动作或发言。');
      return;
    }
    const prompt = window.prompt(`你想如何使用/观察【${itemName}】？`);
    if (!prompt || !prompt.trim()) return;
    try {
      const result = await performActionCheckWithRoll({
        action_type: 'item_use',
        action_prompt: `interaction_id=${interactionId}; item=${itemName}; prompt=${prompt.trim()}`,
        actor_role_id: playerStatic.player_id,
        source_context: 'area_item',
        post_close_output: 'main_chat',
        resolution_context: 'standalone',
      });
      if (!result) return;
      setLastActionResult(result);
      await publishActionCheckOutcome(result, 'area_item', 'main_chat');
      pushTimeNotice(result.time_spent_min, `物品使用:${itemName}`);
      await runNarrativeChecks('quest_rule');
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
        await runNarrativeChecks('quest_rule');
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

  const ensureMap = async (forceRegenerate = false, snapshotOverride?: MapSnapshot) => {
    let snapshot = snapshotOverride ?? mapSnapshot;
    if (snapshot.zones.length === 0 || forceRegenerate) {
      setAiWaitingText('正在等待 AI 生成地图区块...');
      setAiWaiting(true);
      try {
        const generated = await generateRegions(
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
        snapshot = {
          player_position: snapshot.player_position ?? DEFAULT_POSITION,
          zones: generated.zones,
        };
        setMapSnapshot(snapshot);
        await refreshTokenUsage(sessionId);
      } finally {
        setAiWaiting(false);
      }
    }

    const render = await renderWorldMap(
      {
        session_id: sessionId,
        zones: snapshot.zones,
        player_position: snapshot.player_position ?? DEFAULT_POSITION,
      },
      report,
    );
    setMapRender(render);
  };

  const onOpenMap = async () => {
    try {
      setLogOpen(false);
      await ensureMap();
      await refreshAreaSnapshot();
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
      await refreshAreaSnapshot();
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
      setAiWaitingText('正在等待 AI 生成移动反馈...');
      setAiWaiting(true);
      const moved = await moveToZone(
        {
          session_id: sessionId,
          from_zone_id: fromId,
          to_zone_id: zoneId,
          player_name: playerStatic.name,
        },
        report,
      );
      pushTimeNotice(moved.duration_min, '大区块移动');

      setMapSnapshot((prev) => ({ ...prev, player_position: moved.new_position }));
      setPlayerRuntimeState((prev) => ({
        ...prev,
        session_id: sessionId,
        current_position: moved.new_position,
        updated_at: new Date().toISOString(),
      }));

      const narrated = await describeBehavior(sessionId, config, moved.movement_log, report);
      setAssistantOnly(narrated.narration);
      await refreshTokenUsage(sessionId);

      const snapshotAfterMove: MapSnapshot = {
        zones: mapSnapshot.zones,
        player_position: moved.new_position,
      };
      await ensureMap(false, snapshotAfterMove);
      await refreshAreaSnapshot();
      await runNarrativeChecks('random_move');
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

  if (view === 'boot') {
    return (
      <main className="app-shell">
        <section className="card">
          <h1>Roleplay Web</h1>
          <p>选择读取已有配置，或先编辑一个新配置。</p>
          {hasStoredConfig && configPath && <p className="hint">已检测到本地配置: {configPath.path}</p>}
          <div className="actions">
            <button onClick={() => configFileInputRef.current?.click()}>读取本地配置</button>
            <input
              ref={configFileInputRef}
              className="hidden-file-input"
              type="file"
              accept="application/json"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onLoadConfigFile(file);
                e.currentTarget.value = '';
              }}
            />
            <button onClick={onNewConfig}>新建/编辑配置</button>
          </div>
        </section>
      </main>
    );
  }

  if (view === 'config') {
    return (
      <main className="app-shell">
        <section className="card config-card">
          <h1>配置编辑</h1>
          <p>选择服务商、填写 API Key、拉取模型，再按模型能力配置参数。</p>
          <div className="config-grid">
            <div className="config-section">
              <h2>连接</h2>
              <label>
                <span>服务商</span>
                <select value={configDraft.provider} onChange={(e) => onConfigProviderChange(e.target.value as AppConfig['provider'])}>
                  <option value="openai">OpenAI</option>
                  <option value="deepseek">DeepSeek</option>
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
                  placeholder={configDraft.provider === 'deepseek' ? '默认 https://api.deepseek.com' : '留空使用官方地址'}
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
                    placeholder="例如 gpt-5 / deepseek-chat"
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
              {configProfile ? (
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
              <h2>存储</h2>
              <div className="actions">
                <button onClick={() => void onPickConfigPath()}>选择配置文件夹</button>
              </div>
              {configPath && <p className="hint">当前配置路径: {configPath.path}</p>}
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
                  </article>
                )}
                {(currentMainOutput?.scene_events ?? []).map((event) => (
                  <SceneEventCard key={event.event_id} event={event} />
                ))}
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
              <div className="composer-input-grid">
                <div className="composer-input-block">
                  <label htmlFor="action-input">动作描述</label>
                  <textarea
                    id="action-input"
                    ref={actionInputRef}
                    value={actionInput}
                    onChange={(e) => setActionInput(e.target.value)}
                    placeholder={
                      pendingQuest
                        ? '请先处理当前任务弹窗。'
                        : chatMode === 'npc'
                          ? '例如：我把徽记放到桌上，向前一步观察他的反应。'
                          : '例如：我走到石门前检查门缝，或只写“我拔剑戒备”。'
                    }
                    disabled={chatState === 'sending' || chatState === 'streaming' || blockingModalOpen}
                  />
                </div>
                <div className="composer-input-block">
                  <label htmlFor="speech-input">语言描述</label>
                  <textarea
                    id="speech-input"
                    value={speechInput}
                    onChange={(e) => setSpeechInput(e.target.value)}
                    placeholder={
                      pendingQuest
                        ? '请先处理当前任务弹窗。'
                        : chatMode === 'npc'
                          ? '例如：我低声说：“我想打听这里最近的怪事。”'
                          : '例如：我低声说：“先别出声，我听到里面有动静。”，也可以只写语言。'
                    }
                    disabled={chatState === 'sending' || chatState === 'streaming' || blockingModalOpen}
                  />
                </div>
              </div>
              <p className="hint">
                {chatMode === 'npc'
                  ? 'NPC 单聊支持只输入动作或只输入语言；若包含动作或向 NPC 提要求，会先进入检定，再把结果一并发给 NPC。'
                  : '主聊天支持只输入动作、只输入语言，或动作加语言一起输入；提交时会按结构化格式发送给 AI。'}
              </p>
              <div className="actions">
                <label className="god-mode-toggle">
                  <input type="checkbox" checked={godMode} onChange={(e) => setGodMode(e.target.checked)} />
                  上帝模式
                </label>
                {chatMode === 'main' && encounterEngaged && (
                  <button disabled={!canAutoAdvance} onClick={() => void onAutoAdvanceTurn()}>
                    自动推进 1 轮
                  </button>
                )}
                {chatState === 'streaming' && <button onClick={onStop}>停止生成</button>}
                <button onClick={onRetry}>重新生成</button>
                <button disabled={!canSend} onClick={() => void onSend()}>
                  发送
                </button>
              </div>
              {pendingQuest && <p className="hint">当前有待确认任务，任务弹窗关闭前无法继续聊天。</p>}
              {error && <p className="error">{error}</p>}
            </footer>
          </div>

          <EncounterLane
            encounter={activeEncounter}
            queuedEncounters={queuedEncounters}
            roleCards={npcPoolItems}
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
        chatReplies={teamChatReplies}
        chatBusy={teamChatBusy}
        chatBlocked={blockingModalOpen || encounterEngaged}
        onRefresh={() => void onOpenTeamPanel()}
        onTeamChat={(playerMessage) => void onTeamChat(playerMessage)}
        onChat={(npcId, npcName) => void onEnterNpcChat(npcId, npcName)}
        onInspectProfile={(npcId) => void onInspectTeamProfile(npcId)}
        onInspectInventory={(npcId) => void onInspectTeamInventory(npcId)}
        onLeave={(npcId) => void onLeaveTeamMember(npcId)}
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

