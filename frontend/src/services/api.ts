import type {
  ActionCheckPlan,
  ActionCheckResult,
  AreaDiscoverInteractionsResolvedResponse,
  AreaExecuteInteractionResolvedResponse,
  AreaMoveResolvedResponse,
  AreaSnapshot,
  AppConfig,
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
  ChatMessage,
  ChatResponse,
  ConsistencyRunResponse,
  ConsistencyStatusResponse,
  EncounterActResponse,
  EncounterCheckResponse,
  EncounterDebugOverviewResponse,
  EncounterEntry,
  EncounterEscapeResponse,
  EncounterPendingResponse,
  EncounterRejoinResponse,
  FateCurrentResponse,
  FateEvaluateResponse,
  FateGenerateResponse,
  GameLogEntry,
  GameLogSettings,
  MapBootstrapResponse,
  MapSnapshot,
  MainTurnSummary,
  ModelDiscoverResponse,
  ModelProfileResponse,
  MoveResolvedResponse,
  MovementLog,
  NpcChatResponse,
  NpcGreetResponse,
  NpcKnowledgeResponse,
  NpcRoleCard,
  PendingTurnContinueResponse,
  PlayerReactionCheck,
  PublicTurnOpposedPlanResponse,
  PublicTurnInteractionPrompt,
  PublicTurnOpposedPrompt,
  PublicTurnPresentation,
  QuestMutationResponse,
  PublicTurnActionSubmission,
  PublicTurnEntryType,
  PublicTurnImpact,
  PublicTurnInteractionResponseSubmission,
  PublicTurnInitiativeEntry,
  PublicTurnPlayerActionCheck,
  PublicTurnPhase,
  PublicTurnResponse,
  PublicTurnSettlementEntry,
  PublicTurnState,
  PublicTurnStateResponse,
  QuestStateResponse,
  RoleBuff,
  InventoryItem,
  InventoryInteractResponse,
  InventoryMutationResponse,
  PathStatus,
  PlayerRuntimeData,
  PlayerStaticData,
  PublicSceneStateResponse,
  ReputationStateResponse,
  RenderResult,
  RoleDrivesResponse,
  SaveFile,
  SceneEvent,
  StorySnapshotResponse,
  TeamMutationResponse,
  TeamChatResponse,
  TeamStateResponse,
  TemplateLibraryFillResponse,
  TemplateLibraryStatusResponse,
  LiveToolEvent,
  StreamPhaseEvent,
  ToolEvent,
  TokenUsageSummary,
  TurnRollbackPayload,
  Usage,
  ValidateConfigResponse,
  Zone,
  ZoneMetricState,
} from '../types/app';

const API_BASE = '/api/v1';

export async function authMe(report?: DebugReporter): Promise<{ ok: boolean; username: string }> {
  return requestJson('/auth/me', { method: 'GET' }, report);
}

export async function authLogin(payload: { username: string; password: string }, report?: DebugReporter): Promise<{ ok: boolean; username: string }> {
  return requestJson('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, report);
}

export async function authRegister(payload: { username: string; password: string }, report?: DebugReporter): Promise<{ ok: boolean }> {
  return requestJson('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, report);
}

export async function authResetPassword(
  payload: { username: string; current_password: string; new_password: string },
  report?: DebugReporter,
): Promise<{ ok: boolean }> {
  return requestJson('/auth/reset-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, report);
}

export async function authLogout(report?: DebugReporter): Promise<{ ok: boolean }> {
  return requestJson('/auth/logout', { method: 'POST' }, report);
}


type DebugReporter = (payload: { endpoint: string; status: number; ok: boolean; usage?: Usage; detail?: string }) => void;

async function requestJson<T>(endpoint: string, init: RequestInit, report?: DebugReporter): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, { credentials: 'include', ...init });
  const text = await response.text();
  let parsed: unknown = {};
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { detail: text };
    }
  }

  const usage = typeof parsed === 'object' && parsed && 'usage' in parsed ? (parsed as { usage?: Usage }).usage : undefined;
  report?.({ endpoint, status: response.status, ok: response.ok, usage });

  if (!response.ok) {
    const detail = typeof parsed === 'object' && parsed && 'detail' in parsed ? (parsed as { detail?: string }).detail : text;
    report?.({ endpoint, status: response.status, ok: false, detail });
    throw new Error(`${endpoint} 失败(${response.status}): ${detail ?? text}`);
  }

  return parsed as T;
}

export async function validateConfig(
  config: unknown,
  report?: DebugReporter,
): Promise<ValidateConfigResponse> {
  return requestJson(
    '/config/validate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    },
    report,
  );
}

export async function discoverConfigModels(
  payload: { provider: AppConfig['provider']; api_key: string; base_url_override?: string | null },
  report?: DebugReporter,
): Promise<ModelDiscoverResponse> {
  return requestJson(
    '/config/models/discover',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getConfigModelProfile(
  payload: { provider: AppConfig['provider']; model: string; api_key?: string; base_url_override?: string | null },
  report?: DebugReporter,
): Promise<ModelProfileResponse> {
  return requestJson(
    '/config/models/profile',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function sendChat(
  payload: {
    session_id: string;
    config: AppConfig;
    messages: ChatMessage[];
  },
  report?: DebugReporter,
): Promise<ChatResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function streamChat(
  payload: {
    session_id: string;
    config: AppConfig;
    messages: ChatMessage[];
  },
  handlers: {
    onDelta: (delta: string) => void;
    onError: (message: string) => void;
    onEnd: (payload: { archived_sub_zone_turn_id?: string | null; main_turn_summary?: MainTurnSummary | null }) => void;
    onReactionCheckRequired: (payload: {
      pending_turn_id: string;
      flow_kind: PendingTurnContinueResponse['flow_kind'];
      reply_so_far: string;
      scene_events_so_far: SceneEvent[];
      pending_reaction: PlayerReactionCheck | null;
      npc_role_id?: string | null;
    }) => void;
    onPhase: (event: StreamPhaseEvent) => void;
    onToolUpdate: (event: LiveToolEvent) => void;
    onRollback: (payload: TurnRollbackPayload) => void;
    onUsage: (usage: Usage) => void;
    onTimeSpent: (minutes: number) => void;
    onToolEvents: (events: ToolEvent[]) => void;
    onSceneEvents: (events: SceneEvent[]) => void;
  },
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  const endpoint = '/chat/stream';
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    credentials: 'include',
  });

  report?.({ endpoint, status: response.status, ok: response.ok });
  if (!response.ok) {
    const text = await response.text();
    report?.({ endpoint, status: response.status, ok: false, detail: text });
    throw new Error(`流式聊天失败(${response.status}): ${text}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('流响应不可用');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';

    for (const chunk of chunks) {
      const lines = chunk.split('\n');
      const event = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim();
      const dataLine = lines.find((line) => line.startsWith('data:'))?.replace('data:', '').trim() ?? '{}';

      try {
        const data = JSON.parse(dataLine) as {
          content?: string;
          message?: string;
          usage?: Usage;
          code?: string;
          label?: string;
          status?: 'running' | 'done' | 'failed';
          detail?: string;
          tool_name?: string;
          summary?: string;
          payload?: Record<string, string | number | boolean>;
          tool_events?: ToolEvent[];
          scene_events?: SceneEvent[];
          time_spent_min?: number;
          archived_sub_zone_turn_id?: string | null;
          main_turn_summary?: MainTurnSummary | null;
          reason?: string;
          discarded?: true;
          pending_turn_id?: string;
          flow_kind?: PendingTurnContinueResponse['flow_kind'];
          reply_so_far?: string;
          scene_events_so_far?: SceneEvent[];
          pending_reaction?: PlayerReactionCheck | null;
          npc_role_id?: string | null;
        };
        if (event === 'delta') {
          handlers.onDelta(data.content ?? '');
        } else if (event === 'phase') {
          handlers.onPhase({
            code: (data.code ?? 'prepare') as StreamPhaseEvent['code'],
            label: data.label ?? '',
            status: data.status ?? 'running',
            detail: data.detail ?? '',
          });
        } else if (event === 'tool') {
          handlers.onToolUpdate({
            tool_name: data.tool_name ?? '',
            status: data.status ?? 'running',
            summary: data.summary ?? '',
            payload: data.payload ?? {},
          });
        } else if (event === 'rollback') {
          handlers.onRollback({
            reason: data.reason ?? 'error',
            message: data.message ?? '本轮生成已作废',
            discarded: true,
          });
        } else if (event === 'reaction_check_required') {
          terminalEventReceived = true;
          handlers.onReactionCheckRequired({
            pending_turn_id: data.pending_turn_id ?? '',
            flow_kind: data.flow_kind ?? 'main_chat',
            reply_so_far: data.reply_so_far ?? '',
            scene_events_so_far: data.scene_events_so_far ?? [],
            pending_reaction: data.pending_reaction ?? null,
            npc_role_id: data.npc_role_id ?? null,
          });
        } else if (event === 'error') {
          terminalEventReceived = true;
          handlers.onError(data.message ?? '未知错误');
        } else if (event === 'end') {
          terminalEventReceived = true;
          handlers.onUsage(data.usage ?? { input_tokens: 0, output_tokens: 0 });
          handlers.onTimeSpent(data.time_spent_min ?? 0);
          handlers.onToolEvents(data.tool_events ?? []);
          handlers.onSceneEvents(data.scene_events ?? []);
          handlers.onEnd({
            archived_sub_zone_turn_id: data.archived_sub_zone_turn_id ?? null,
            main_turn_summary: data.main_turn_summary ?? null,
          });
        }
      } catch {
        handlers.onError('流消息解析失败');
      }
    }
  }

  if (!terminalEventReceived) {
    handlers.onEnd({ archived_sub_zone_turn_id: null, main_turn_summary: null });
  }
}

export async function continuePendingTurn(
  payload: { session_id: string; pending_turn_id: string; forced_dice_roll: number; config?: AppConfig },
  report?: DebugReporter,
): Promise<PendingTurnContinueResponse> {
  return requestJson(
    '/chat/pending/continue',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function continuePendingTurnStream(
  payload: { session_id: string; pending_turn_id: string; forced_dice_roll: number; config?: AppConfig },
  handlers: {
    onDelta: (delta: string) => void;
    onError: (message: string) => void;
    onEnd: (payload: { archived_sub_zone_turn_id?: string | null; main_turn_summary?: MainTurnSummary | null }) => void;
    onReactionCheckResumed?: (payload: { pending_turn_id: string; reaction_result: ActionCheckResult | null }) => void;
    onReactionCheckRequired: (payload: {
      pending_turn_id: string;
      flow_kind: PendingTurnContinueResponse['flow_kind'];
      reply_so_far: string;
      scene_events_so_far: SceneEvent[];
      pending_reaction: PlayerReactionCheck | null;
      npc_role_id?: string | null;
    }) => void;
    onSceneEvents: (events: SceneEvent[]) => void;
    onTimeSpent?: (minutes: number) => void;
  },
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  const endpoint = '/chat/pending/continue/stream';
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    credentials: 'include',
  });
  report?.({ endpoint, status: response.status, ok: response.ok });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`待续回合续行失败(${response.status}): ${text}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('流响应不可用');
  }
  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';
    for (const chunk of chunks) {
      const lines = chunk.split('\n');
      const event = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim();
      const dataLine = lines.find((line) => line.startsWith('data:'))?.replace('data:', '').trim() ?? '{}';
      const data = JSON.parse(dataLine) as {
        content?: string;
        message?: string;
        pending_turn_id?: string;
        reaction_result?: ActionCheckResult | null;
        flow_kind?: PendingTurnContinueResponse['flow_kind'];
        reply_so_far?: string;
        scene_events_so_far?: SceneEvent[];
        pending_reaction?: PlayerReactionCheck | null;
        npc_role_id?: string | null;
        scene_events?: SceneEvent[];
        archived_sub_zone_turn_id?: string | null;
        main_turn_summary?: MainTurnSummary | null;
        time_spent_min?: number;
      };
      if (event === 'delta') {
        handlers.onDelta(data.content ?? '');
      } else if (event === 'reaction_check_resumed') {
        handlers.onReactionCheckResumed?.({
          pending_turn_id: data.pending_turn_id ?? '',
          reaction_result: data.reaction_result ?? null,
        });
      } else if (event === 'reaction_check_required') {
        terminalEventReceived = true;
        handlers.onReactionCheckRequired({
          pending_turn_id: data.pending_turn_id ?? '',
          flow_kind: data.flow_kind ?? 'main_chat',
          reply_so_far: data.reply_so_far ?? '',
          scene_events_so_far: data.scene_events_so_far ?? [],
          pending_reaction: data.pending_reaction ?? null,
          npc_role_id: data.npc_role_id ?? null,
        });
      } else if (event === 'end') {
        terminalEventReceived = true;
        handlers.onSceneEvents(data.scene_events ?? []);
        handlers.onTimeSpent?.(data.time_spent_min ?? 0);
        handlers.onEnd({
          archived_sub_zone_turn_id: data.archived_sub_zone_turn_id ?? null,
          main_turn_summary: data.main_turn_summary ?? null,
        });
      } else if (event === 'error') {
        terminalEventReceived = true;
        handlers.onError(data.message ?? '未知错误');
      }
    }
  }
  if (!terminalEventReceived) {
    handlers.onEnd({ archived_sub_zone_turn_id: null, main_turn_summary: null });
  }
}

export async function cancelPendingTurn(
  payload: { session_id: string; pending_turn_id: string },
  report?: DebugReporter,
): Promise<PendingTurnContinueResponse> {
  return requestJson(
    `/pending-turns/${encodeURIComponent(payload.pending_turn_id)}/cancel?session_id=${encodeURIComponent(payload.session_id)}`,
    { method: 'POST' },
    report,
  );
}

export async function getCurrentPendingTurn(
  sessionId: string,
  report?: DebugReporter,
): Promise<PendingTurnContinueResponse | null> {
  return requestJson(`/pending-turns/current?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function startDebugBattle(payload: BattleStartRequest, report?: DebugReporter): Promise<BattleStartResponse> {
  return requestJson(
    '/battle/debug/start',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getCurrentDebugBattle(sessionId: string, report?: DebugReporter): Promise<BattleCurrentResponse> {
  return requestJson(`/battle/debug/current?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function submitBattlePlayerAction(
  battleId: string,
  payload: BattleActionRequest,
  report?: DebugReporter,
): Promise<BattleActionResponse> {
  return requestJson(
    `/battle/${encodeURIComponent(battleId)}/player-action`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function continueBattleAi(
  battleId: string,
  payload: BattleContinueAiRequest,
  report?: DebugReporter,
): Promise<BattleContinueAiResponse> {
  return requestJson(
    `/battle/${encodeURIComponent(battleId)}/continue-ai`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function resolveBattleRoll(
  battleId: string,
  payload: BattleResolveRollRequest,
  report?: DebugReporter,
): Promise<BattleResolveRollResponse> {
  return requestJson(
    `/battle/${encodeURIComponent(battleId)}/resolve-roll`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function endDebugBattle(
  battleId: string,
  payload: BattleContinueAiRequest,
  report?: DebugReporter,
): Promise<BattleEndResponse> {
  return requestJson(
    `/battle/${encodeURIComponent(battleId)}/end`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getConfigPath(report?: DebugReporter): Promise<PathStatus> {
  return requestJson('/storage/config/path', { method: 'GET' }, report);
}

export async function setConfigPath(path: string, report?: DebugReporter): Promise<PathStatus> {
  return requestJson(
    '/storage/config/path',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    },
    report,
  );
}

export async function pickConfigPath(report?: DebugReporter): Promise<PathStatus> {
  return requestJson(
    '/storage/config/path/pick',
    {
      method: 'POST',
    },
    report,
  );
}

export async function saveConfig(config: AppConfig, report?: DebugReporter): Promise<{ ok: boolean; path: string }> {
  return requestJson(
    '/storage/config',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    },
    report,
  );
}

export async function getStoredConfig(report?: DebugReporter): Promise<AppConfig> {
  return requestJson('/storage/config', { method: 'GET' }, report);
}

export async function getSavePath(report?: DebugReporter): Promise<PathStatus> {
  return requestJson('/saves/path', { method: 'GET' }, report);
}

export async function setSavePath(path: string, report?: DebugReporter): Promise<PathStatus> {
  return requestJson(
    '/saves/path',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    },
    report,
  );
}

export async function pickSavePath(report?: DebugReporter): Promise<PathStatus> {
  return requestJson(
    '/saves/path/pick',
    {
      method: 'POST',
    },
    report,
  );
}

export async function getCurrentSave(report?: DebugReporter): Promise<SaveFile> {
  return requestJson('/saves/current', { method: 'GET' }, report);
}

export async function importSave(save: SaveFile, report?: DebugReporter): Promise<SaveFile> {
  return requestJson(
    '/saves/import',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ save_data: save }),
    },
    report,
  );
}

export async function clearSave(sessionId: string, report?: DebugReporter): Promise<SaveFile> {
  return requestJson(
    '/saves/clear',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    },
    report,
  );
}

export async function generateRegions(
  payload: {
    session_id: string;
    config: AppConfig;
    player_position: { x: number; y: number; z: number; zone_id: string };
    desired_count: number;
    max_count: number;
    world_prompt: string;
    force_regenerate?: boolean;
  },
  report?: DebugReporter,
): Promise<{ session_id: string; generated: boolean; zones: Zone[] }> {
  return requestJson(
    '/world-map/regions/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function bootstrapWorldMap(
  payload: {
    session_id: string;
    config: AppConfig;
    player_position: { x: number; y: number; z: number; zone_id: string };
    desired_count: number;
    max_count: number;
    world_prompt: string;
    force_regenerate?: boolean;
  },
  report?: DebugReporter,
): Promise<MapBootstrapResponse> {
  return requestJson(
    '/world-map/bootstrap',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function renderWorldMap(
  payload: {
    session_id: string;
    zones: Zone[];
    player_position: { x: number; y: number; z: number; zone_id: string };
    zone_metric_state?: ZoneMetricState;
  },
  report?: DebugReporter,
): Promise<RenderResult> {
  return requestJson(
    '/world-map/render',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function moveToZone(
  payload: { session_id: string; from_zone_id: string; to_zone_id: string; player_name?: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<MoveResolvedResponse> {
  return requestJson(
    '/world-map/move',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function describeBehavior(
  sessionId: string,
  config: AppConfig,
  log: MovementLog,
  report?: DebugReporter,
): Promise<{ session_id: string; narration: string }> {
  return requestJson(
    '/logs/behavior/describe',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, config, log }),
    },
    report,
  );
}

export async function getGameLogs(sessionId: string, limit?: number, report?: DebugReporter): Promise<{ session_id: string; items: GameLogEntry[] }> {
  const suffix = limit ? `&limit=${encodeURIComponent(String(limit))}` : '';
  return requestJson(`/logs/game?session_id=${encodeURIComponent(sessionId)}${suffix}`, { method: 'GET' }, report);
}

export async function addGameLog(
  payload: { session_id: string; kind: string; message: string; payload?: Record<string, string | number | boolean> },
  report?: DebugReporter,
): Promise<{ session_id: string; items: GameLogEntry[] }> {
  return requestJson(
    '/logs/game',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getGameLogSettings(sessionId: string, report?: DebugReporter): Promise<{ session_id: string; settings: GameLogSettings }> {
  return requestJson(`/logs/game/settings?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function setGameLogSettings(
  sessionId: string,
  settings: GameLogSettings,
  report?: DebugReporter,
): Promise<{ session_id: string; settings: GameLogSettings }> {
  return requestJson(
    `/logs/game/settings?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    },
    report,
  );
}

export async function getQuestState(sessionId: string, report?: DebugReporter): Promise<QuestStateResponse> {
  return requestJson(`/quests?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function debugGenerateQuest(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<QuestMutationResponse> {
  return requestJson(
    '/quests/debug/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function acceptQuest(
  payload: { session_id: string; quest_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<QuestMutationResponse> {
  return requestJson(
    `/quests/${encodeURIComponent(payload.quest_id)}/accept`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id, config: payload.config }),
    },
    report,
  );
}

export async function rejectQuest(
  payload: { session_id: string; quest_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<QuestMutationResponse> {
  return requestJson(
    `/quests/${encodeURIComponent(payload.quest_id)}/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id, config: payload.config }),
    },
    report,
  );
}

export async function trackQuest(
  payload: { session_id: string; quest_id: string },
  report?: DebugReporter,
): Promise<QuestMutationResponse> {
  return requestJson(
    `/quests/${encodeURIComponent(payload.quest_id)}/track?session_id=${encodeURIComponent(payload.session_id)}`,
    { method: 'POST' },
    report,
  );
}

export async function evaluateAllQuests(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<QuestStateResponse> {
  return requestJson(
    '/quests/evaluate-all',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getPendingEncounters(sessionId: string, report?: DebugReporter): Promise<EncounterPendingResponse> {
  return requestJson(`/encounters/pending?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function checkEncounters(
  payload: { session_id: string; trigger_kind: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced'; config?: AppConfig },
  report?: DebugReporter,
): Promise<EncounterCheckResponse> {
  return requestJson(
    '/encounters/check',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function presentEncounter(
  payload: { session_id: string; encounter_id: string },
  report?: DebugReporter,
): Promise<{ ok: boolean; session_id: string; encounter_id: string; status: EncounterEntry['status']; encounter: EncounterEntry }> {
  return requestJson(
    `/encounters/${encodeURIComponent(payload.encounter_id)}/present`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id }),
    },
    report,
  );
}

export async function actEncounter(
  payload: { session_id: string; encounter_id: string; player_prompt: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<EncounterActResponse> {
  return requestJson(
    `/encounters/${encodeURIComponent(payload.encounter_id)}/act`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id, player_prompt: payload.player_prompt, config: payload.config }),
    },
    report,
  );
}

export async function escapeEncounter(
  payload: { session_id: string; encounter_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<EncounterEscapeResponse> {
  return requestJson(
    `/encounters/${encodeURIComponent(payload.encounter_id)}/escape`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id, config: payload.config }),
    },
    report,
  );
}

export async function rejoinEncounter(
  payload: { session_id: string; encounter_id: string },
  report?: DebugReporter,
): Promise<EncounterRejoinResponse> {
  return requestJson(
    `/encounters/${encodeURIComponent(payload.encounter_id)}/rejoin`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id }),
    },
    report,
  );
}

export async function getEncounterDebugOverview(sessionId: string, report?: DebugReporter): Promise<EncounterDebugOverviewResponse> {
  return requestJson(`/encounters/debug/overview?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function toggleEncounterForce(
  payload: { session_id: string; enabled?: boolean },
  report?: DebugReporter,
): Promise<{ ok: boolean; session_id: string; enabled: boolean }> {
  return requestJson(
    '/encounters/debug/force-toggle',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getFateState(sessionId: string, report?: DebugReporter): Promise<FateCurrentResponse> {
  return requestJson(`/fate/current?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function getAreaReputation(
  sessionId: string,
  payload?: { sub_zone_id?: string | null },
  report?: DebugReporter,
): Promise<ReputationStateResponse> {
  const suffix = payload?.sub_zone_id ? `&sub_zone_id=${encodeURIComponent(payload.sub_zone_id)}` : '';
  return requestJson(`/reputation/current?session_id=${encodeURIComponent(sessionId)}${suffix}`, { method: 'GET' }, report);
}

export async function getRoleDrives(
  sessionId: string,
  payload?: { scope?: 'role' | 'team' | 'current_sub_zone'; role_id?: string | null },
  report?: DebugReporter,
): Promise<RoleDrivesResponse> {
  const params = new URLSearchParams({ session_id: sessionId });
  if (payload?.scope) {
    params.set('scope', payload.scope);
  }
  if (payload?.role_id) {
    params.set('role_id', payload.role_id);
  }
  return requestJson(`/role-drives?${params.toString()}`, { method: 'GET' }, report);
}

export async function getPublicSceneState(sessionId: string, report?: DebugReporter): Promise<PublicSceneStateResponse> {
  return requestJson(`/scene/public-state?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function getPublicTurnState(sessionId: string, report?: DebugReporter): Promise<PublicTurnStateResponse> {
  return requestJson(`/public-turn/state?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function enterPublicTurn(
  payload: { session_id: string; entry_type: PublicTurnEntryType; player_action?: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<PublicTurnResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/public-turn/entry',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function continuePublicTurn(
  payload: {
    session_id: string;
    action_submission?: PublicTurnActionSubmission | null;
    player_interaction_response?: PublicTurnInteractionResponseSubmission | null;
    player_action_check?: PublicTurnPlayerActionCheck | null;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<PublicTurnResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/public-turn/continue',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function resolvePublicTurnReaction(
  payload: { session_id: string; check_id: string; forced_dice_roll: number; config?: AppConfig },
  report?: DebugReporter,
): Promise<PublicTurnResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/public-turn/reaction-check',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function planPublicTurnOpposedCheck(
  payload: {
    session_id: string;
    round_id: string;
    check_id: string;
    source_actor_id: string;
    target_actor_id: string;
    source_action_summary?: string;
    source_speech_text?: string;
    target_action_summary?: string;
    target_speech_text?: string;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<PublicTurnOpposedPlanResponse> {
  return requestJson(
    '/public-turn/opposed-check/plan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function resolvePublicTurnOpposedCheck(
  payload: {
    session_id: string;
    check_id: string;
    forced_dice_roll: number;
    target_action_summary?: string;
    target_speech_text?: string;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<PublicTurnResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/public-turn/opposed-check',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

async function consumePublicTurnStream(
  endpoint: '/public-turn/entry/stream' | '/public-turn/continue/stream' | '/public-turn/reaction-check/stream' | '/public-turn/opposed-check/stream',
  payload: unknown,
  handlers: {
    onPhase: (event: StreamPhaseEvent) => void;
    onTurnState?: (state: PublicTurnState) => void;
    onInitiativeOrder?: (entries: PublicTurnInitiativeEntry[], meta: { round_id?: string; round_number?: number }) => void;
    onSettlementEntry?: (entry: PublicTurnSettlementEntry) => void;
    onRoundNarrationDelta: (delta: string) => void;
    onSceneEvent: (event: SceneEvent) => void;
    onImpact: (impact: PublicTurnImpact) => void;
    onInteractionRequired?: (payload: PublicTurnInteractionPrompt) => void;
    onReactionCheckRequired: (payload: {
      pending_turn_id: string;
      flow_kind: PendingTurnContinueResponse['flow_kind'];
      reply_so_far: string;
      scene_events_so_far: SceneEvent[];
      pending_reaction: PlayerReactionCheck | null;
      npc_role_id?: string | null;
      public_turn_state?: PublicTurnState | null;
      public_turn_presentation?: PublicTurnPresentation | null;
    }) => void;
    onOpposedCheckRequired?: (payload: {
      pending_turn_id: string;
      flow_kind: PendingTurnContinueResponse['flow_kind'];
      reply_so_far: string;
      scene_events_so_far: SceneEvent[];
      public_opposed_prompt: PublicTurnOpposedPrompt | null;
      npc_role_id?: string | null;
      public_turn_state?: PublicTurnState | null;
      public_turn_presentation?: PublicTurnPresentation | null;
    }) => void;
    onReactionCheckResumed?: (payload: { check_id: string }) => void;
    onOpposedCheckResolved?: (payload: { check_id: string }) => void;
    onRoundCompleted?: (payload: { archived_sub_zone_turn_id?: string | null; phase?: PublicTurnPhase | string }) => void;
    onError: (message: string) => void;
    onEnd: (payload: {
      archived_sub_zone_turn_id?: string | null;
      round_completed?: boolean;
      phase?: PublicTurnPhase | string;
      public_turn_state?: PublicTurnState | null;
      presentation?: PublicTurnPresentation | null;
    }) => void;
  },
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    credentials: 'include',
  });
  report?.({ endpoint, status: response.status, ok: response.ok });
  if (!response.ok) {
    const text = await response.text();
    report?.({ endpoint, status: response.status, ok: false, detail: text });
    throw new Error(`${endpoint} 失败(${response.status}): ${text}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('流响应不可用');
  }
  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';
    for (const chunk of chunks) {
      const lines = chunk.split('\n');
      const event = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim();
      const dataLine = lines.find((line) => line.startsWith('data:'))?.replace('data:', '').trim() ?? '{}';
      try {
        const data = JSON.parse(dataLine) as {
          code?: string;
          label?: string;
          status?: 'running' | 'done' | 'failed';
          detail?: string;
          content?: string;
          pending_turn_id?: string;
          flow_kind?: PendingTurnContinueResponse['flow_kind'];
          reply_so_far?: string;
          scene_events_so_far?: SceneEvent[];
          pending_reaction?: PlayerReactionCheck | null;
          public_interaction_prompt?: PublicTurnInteractionPrompt | null;
          public_opposed_prompt?: PublicTurnOpposedPrompt | null;
          npc_role_id?: string | null;
          archived_sub_zone_turn_id?: string | null;
          round_completed?: boolean;
          phase?: PublicTurnPhase | string;
          public_turn_state?: PublicTurnState | null;
          presentation?: PublicTurnPresentation | null;
          check_id?: string;
          entries?: PublicTurnInitiativeEntry[];
        };
        if (event === 'phase') {
          handlers.onPhase({
            code: 'public_turn',
            label: data.label ?? '',
            status: data.status ?? 'done',
            detail: data.detail ?? '',
          });
        } else if (event === 'turn_state') {
          handlers.onTurnState?.(data as unknown as PublicTurnState);
        } else if (event === 'initiative_order') {
          handlers.onInitiativeOrder?.(data.entries ?? [], {
            round_id: (data as { round_id?: string }).round_id,
            round_number: (data as { round_number?: number }).round_number,
          });
        } else if (event === 'settlement_entry') {
          handlers.onSettlementEntry?.(data as unknown as PublicTurnSettlementEntry);
        } else if (event === 'round_narration_delta' || event === 'narration_delta') {
          handlers.onRoundNarrationDelta(data.content ?? '');
        } else if (event === 'scene_event') {
          handlers.onSceneEvent(data as unknown as SceneEvent);
        } else if (event === 'impact') {
          handlers.onImpact(data as unknown as PublicTurnImpact);
        } else if (event === 'interaction_required') {
          terminalEventReceived = true;
          handlers.onInteractionRequired?.(data as unknown as PublicTurnInteractionPrompt);
        } else if (event === 'reaction_check_required') {
          terminalEventReceived = true;
          handlers.onReactionCheckRequired({
            pending_turn_id: data.pending_turn_id ?? '',
            flow_kind: data.flow_kind ?? 'public_turn',
            reply_so_far: data.reply_so_far ?? '',
            scene_events_so_far: data.scene_events_so_far ?? [],
            pending_reaction: data.pending_reaction ?? null,
            npc_role_id: data.npc_role_id ?? null,
            public_turn_state: data.public_turn_state ?? null,
            public_turn_presentation: data.presentation ?? (data as { public_turn_presentation?: PublicTurnPresentation | null }).public_turn_presentation ?? null,
          });
        } else if (event === 'opposed_check_required') {
          terminalEventReceived = true;
          handlers.onOpposedCheckRequired?.({
            pending_turn_id: data.pending_turn_id ?? '',
            flow_kind: data.flow_kind ?? 'public_turn',
            reply_so_far: data.reply_so_far ?? '',
            scene_events_so_far: data.scene_events_so_far ?? [],
            public_opposed_prompt: data.public_opposed_prompt ?? null,
            npc_role_id: data.npc_role_id ?? null,
            public_turn_state: data.public_turn_state ?? null,
            public_turn_presentation: data.presentation ?? (data as { public_turn_presentation?: PublicTurnPresentation | null }).public_turn_presentation ?? null,
          });
        } else if (event === 'reaction_check_resumed') {
          handlers.onReactionCheckResumed?.({ check_id: data.check_id ?? '' });
        } else if (event === 'opposed_check_resolved') {
          handlers.onOpposedCheckResolved?.({ check_id: data.check_id ?? '' });
        } else if (event === 'round_completed') {
          handlers.onRoundCompleted?.({
            archived_sub_zone_turn_id: data.archived_sub_zone_turn_id ?? null,
            phase: data.phase,
          });
        } else if (event === 'error') {
          terminalEventReceived = true;
          handlers.onError((data as { message?: string }).message ?? '未知错误');
        } else if (event === 'end') {
          terminalEventReceived = true;
          handlers.onEnd({
            archived_sub_zone_turn_id: data.archived_sub_zone_turn_id ?? null,
            round_completed: data.round_completed ?? false,
            phase: data.phase,
            public_turn_state: data.public_turn_state ?? null,
            presentation: data.presentation ?? null,
          });
        }
      } catch {
        handlers.onError('流消息解析失败');
      }
    }
  }
  if (!terminalEventReceived) {
    handlers.onEnd({});
  }
}

export async function streamEnterPublicTurn(
  payload: { session_id: string; entry_type: PublicTurnEntryType; player_action?: string; config?: AppConfig },
  handlers: Parameters<typeof consumePublicTurnStream>[2],
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  return consumePublicTurnStream('/public-turn/entry/stream', payload, handlers, signal, report);
}

export async function streamContinuePublicTurn(
  payload: {
    session_id: string;
    action_submission?: PublicTurnActionSubmission | null;
    player_interaction_response?: PublicTurnInteractionResponseSubmission | null;
    player_action_check?: PublicTurnPlayerActionCheck | null;
    config?: AppConfig;
  },
  handlers: Parameters<typeof consumePublicTurnStream>[2],
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  return consumePublicTurnStream('/public-turn/continue/stream', payload, handlers, signal, report);
}

export async function streamResolvePublicTurnReaction(
  payload: { session_id: string; check_id: string; forced_dice_roll: number; config?: AppConfig },
  handlers: Parameters<typeof consumePublicTurnStream>[2],
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  return consumePublicTurnStream('/public-turn/reaction-check/stream', payload, handlers, signal, report);
}

export async function streamResolvePublicTurnOpposedCheck(
  payload: {
    session_id: string;
    check_id: string;
    forced_dice_roll: number;
    target_action_summary?: string;
    target_speech_text?: string;
    config?: AppConfig;
  },
  handlers: Parameters<typeof consumePublicTurnStream>[2],
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  return consumePublicTurnStream('/public-turn/opposed-check/stream', payload, handlers, signal, report);
}

export async function generateFate(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<FateGenerateResponse> {
  return requestJson(
    '/fate/debug/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function regenerateFate(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<FateGenerateResponse> {
  return requestJson(
    '/fate/debug/regenerate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function evaluateFate(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<FateEvaluateResponse> {
  return requestJson(
    '/fate/evaluate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getStorySnapshot(sessionId: string, report?: DebugReporter): Promise<StorySnapshotResponse> {
  return requestJson(`/story/snapshot?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function getConsistencyStatus(sessionId: string, report?: DebugReporter): Promise<ConsistencyStatusResponse> {
  return requestJson(`/consistency/status?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function runConsistencyCheck(sessionId: string, report?: DebugReporter): Promise<ConsistencyRunResponse> {
  return requestJson(
    '/consistency/run',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    },
    report,
  );
}

export async function getNpcKnowledge(
  sessionId: string,
  npcRoleId: string,
  report?: DebugReporter,
): Promise<NpcKnowledgeResponse> {
  return requestJson(`/npc/${encodeURIComponent(npcRoleId)}/knowledge?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function getTeamState(sessionId: string, report?: DebugReporter): Promise<TeamStateResponse> {
  return requestJson(`/team?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function inviteNpcToTeam(
  payload: { session_id: string; npc_role_id: string; player_prompt?: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<TeamMutationResponse> {
  return requestJson(
    '/team/invite',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function leaveNpcFromTeam(
  payload: { session_id: string; npc_role_id: string; reason?: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<TeamMutationResponse> {
  return requestJson(
    '/team/leave',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function generateDebugTeammate(
  payload: { session_id: string; prompt: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<TeamMutationResponse> {
  return requestJson(
    '/team/debug/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function sendTeamChat(
  payload: { session_id: string; player_message: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<TeamChatResponse> {
  return requestJson(
    '/team/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

// Retained NPC API functions
export async function getRetainedNpcs(
  report?: DebugReporter,
): Promise<{ npcs: Array<{ retained_id: string; name: string; retained_at: string; notes: string }> }> {
  return requestJson('/team/retained', { method: 'GET' }, report);
}

export async function retainNpc(
  payload: { session_id: string; role_id: string; notes?: string },
  report?: DebugReporter,
): Promise<{ ok: boolean; retained_id: string; name: string; message: string }> {
  return requestJson(
    '/team/retain',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function generateFromRetained(
  retainedId: string,
  payload: { session_id: string },
  report?: DebugReporter,
): Promise<TeamMutationResponse> {
  return requestJson(
    `/team/retained/${encodeURIComponent(retainedId)}/generate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function deleteRetainedNpc(
  retainedId: string,
  report?: DebugReporter,
): Promise<{ ok: boolean; message: string }> {
  return requestJson(
    `/team/retained/${encodeURIComponent(retainedId)}`,
    { method: 'DELETE' },
    report,
  );
}

export async function getPlayerStatic(sessionId: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(`/player/static?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function setPlayerStatic(sessionId: string, payload: PlayerStaticData, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/static?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function equipPlayerItem(
  sessionId: string,
  payload: { item_id: string; slot: 'weapon' | 'armor' },
  report?: DebugReporter,
): Promise<PlayerStaticData> {
  return requestJson(
    `/player/equipment/equip?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    report,
  );
}

export async function unequipPlayerItem(
  sessionId: string,
  payload: { slot: 'weapon' | 'armor' },
  report?: DebugReporter,
): Promise<PlayerStaticData> {
  return requestJson(
    `/player/equipment/unequip?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    report,
  );
}

export async function equipInventoryItem(
  payload: {
    session_id: string;
    owner: { owner_type: 'player' | 'role'; role_id: string | null };
    item_id: string;
    slot: 'weapon' | 'armor';
  },
  report?: DebugReporter,
): Promise<InventoryMutationResponse> {
  return requestJson(
    '/inventory/equip',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function unequipInventoryItem(
  payload: {
    session_id: string;
    owner: { owner_type: 'player' | 'role'; role_id: string | null };
    slot: 'weapon' | 'armor';
  },
  report?: DebugReporter,
): Promise<InventoryMutationResponse> {
  return requestJson(
    '/inventory/unequip',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function interactInventoryItem(
  payload: {
    session_id: string;
    owner: { owner_type: 'player' | 'role'; role_id: string | null };
    item_id: string;
    mode: 'inspect' | 'use';
    prompt: string;
    action_check?: ActionCheckResult | null;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<InventoryInteractResponse> {
  return requestJson(
    '/inventory/interact',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function addPlayerBuff(sessionId: string, buff: RoleBuff, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/buffs/add?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ buff }) },
    report,
  );
}

export async function removePlayerBuff(sessionId: string, buffId: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/buffs/remove?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ buff_id: buffId }) },
    report,
  );
}

export async function addPlayerItem(sessionId: string, item: InventoryItem, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/items/add?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item }) },
    report,
  );
}

export async function removePlayerItem(
  sessionId: string,
  payload: { item_id: string; quantity?: number },
  report?: DebugReporter,
): Promise<PlayerStaticData> {
  return requestJson(
    `/player/items/remove?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    report,
  );
}

export async function addPlayerSpell(sessionId: string, value: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/spells/add?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) },
    report,
  );
}

export async function removePlayerSpell(sessionId: string, value: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/spells/remove?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) },
    report,
  );
}

export async function addPlayerSkill(sessionId: string, value: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/skills/add?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) },
    report,
  );
}

export async function removePlayerSkill(sessionId: string, value: string, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/skills/remove?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) },
    report,
  );
}

export async function consumeSpellSlots(
  sessionId: string,
  payload: { level: number; amount?: number },
  report?: DebugReporter,
): Promise<PlayerStaticData> {
  return requestJson(
    `/player/resources/spell-slots/consume?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    report,
  );
}

export async function recoverSpellSlots(
  sessionId: string,
  payload: { level: number; amount?: number },
  report?: DebugReporter,
): Promise<PlayerStaticData> {
  return requestJson(
    `/player/resources/spell-slots/recover?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    report,
  );
}

export async function consumeStamina(sessionId: string, amount = 1, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/resources/stamina/consume?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount }) },
    report,
  );
}

export async function recoverStamina(sessionId: string, amount = 1, report?: DebugReporter): Promise<PlayerStaticData> {
  return requestJson(
    `/player/resources/stamina/recover?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount }) },
    report,
  );
}

export async function getPlayerRuntime(sessionId: string, report?: DebugReporter): Promise<PlayerRuntimeData> {
  return requestJson(`/player/runtime?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function setPlayerRuntime(sessionId: string, payload: PlayerRuntimeData, report?: DebugReporter): Promise<PlayerRuntimeData> {
  return requestJson(
    `/player/runtime?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getTokenUsage(sessionId: string, report?: DebugReporter): Promise<TokenUsageSummary> {
  return requestJson(`/token-usage?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function getRolePool(
  sessionId: string,
  query?: string,
  limit = 200,
  report?: DebugReporter,
): Promise<{ session_id: string; total: number; items: NpcRoleCard[] }> {
  const q = query ? `&q=${encodeURIComponent(query)}` : '';
  const l = `&limit=${encodeURIComponent(String(limit))}`;
  return requestJson(`/role-pool?session_id=${encodeURIComponent(sessionId)}${q}${l}`, { method: 'GET' }, report);
}

export async function getRoleCard(sessionId: string, roleId: string, report?: DebugReporter): Promise<NpcRoleCard> {
  return requestJson(`/role-pool/${encodeURIComponent(roleId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function relatePlayerToRole(
  sessionId: string,
  roleId: string,
  payload: { relation_tag: string; note?: string },
  report?: DebugReporter,
): Promise<NpcRoleCard> {
  return requestJson(
    `/role-pool/${encodeURIComponent(roleId)}/relate-player?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function setRoleRelation(
  sessionId: string,
  roleId: string,
  payload: { target_role_id: string; relation_tag: string; note?: string },
  report?: DebugReporter,
): Promise<NpcRoleCard> {
  return requestJson(
    `/role-pool/${encodeURIComponent(roleId)}/relations?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function npcGreet(
  payload: { session_id: string; npc_role_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<NpcGreetResponse> {
  return requestJson(
    '/npc/greet',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function npcChat(
  payload: { session_id: string; npc_role_id: string; player_message: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<NpcChatResponse | PendingTurnContinueResponse> {
  return requestJson(
    '/npc/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function streamNpcChat(
  payload: { session_id: string; npc_role_id: string; player_message: string; config?: AppConfig },
  handlers: {
    onDelta: (delta: string) => void;
    onError: (message: string) => void;
    onEnd: () => void;
    onReactionCheckRequired: (payload: {
      pending_turn_id: string;
      flow_kind: PendingTurnContinueResponse['flow_kind'];
      reply_so_far: string;
      scene_events_so_far: SceneEvent[];
      pending_reaction: PlayerReactionCheck | null;
      npc_role_id?: string | null;
    }) => void;
    onPhase: (event: StreamPhaseEvent) => void;
    onToolUpdate: (event: LiveToolEvent) => void;
    onRollback: (payload: TurnRollbackPayload) => void;
    onTimeSpent: (minutes: number) => void;
    onDialogueLogs: (logs: NpcChatResponse['dialogue_logs']) => void;
    onSceneEvents: (events: SceneEvent[]) => void;
  },
  signal: AbortSignal,
  report?: DebugReporter,
): Promise<void> {
  const endpoint = '/npc/chat/stream';
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    credentials: 'include',
  });
  report?.({ endpoint, status: response.status, ok: response.ok });
  if (!response.ok) {
    const text = await response.text();
    report?.({ endpoint, status: response.status, ok: false, detail: text });
    throw new Error(`NPC流式聊天失败(${response.status}): ${text}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('流响应不可用');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      if (!terminalEventReceived) {
        handlers.onEnd();
      }
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';
    for (const chunk of chunks) {
      const lines = chunk.split('\n');
      const event = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim();
      const dataLine = lines.find((line) => line.startsWith('data:'))?.replace('data:', '').trim() ?? '{}';
      try {
        const data = JSON.parse(dataLine) as {
          content?: string;
          message?: string;
          code?: string;
          label?: string;
          status?: 'running' | 'done' | 'failed';
          detail?: string;
          tool_name?: string;
          summary?: string;
          payload?: Record<string, string | number | boolean>;
          reason?: string;
          time_spent_min?: number;
          dialogue_logs?: NpcChatResponse['dialogue_logs'];
          scene_events?: SceneEvent[];
          pending_turn_id?: string;
          flow_kind?: PendingTurnContinueResponse['flow_kind'];
          reply_so_far?: string;
          scene_events_so_far?: SceneEvent[];
          pending_reaction?: PlayerReactionCheck | null;
          npc_role_id?: string | null;
        };
        if (event === 'delta') {
          handlers.onDelta(data.content ?? '');
        } else if (event === 'phase') {
          handlers.onPhase({
            code: (data.code ?? 'prepare') as StreamPhaseEvent['code'],
            label: data.label ?? '',
            status: data.status ?? 'running',
            detail: data.detail ?? '',
          });
        } else if (event === 'tool') {
          handlers.onToolUpdate({
            tool_name: data.tool_name ?? '',
            status: data.status ?? 'running',
            summary: data.summary ?? '',
            payload: data.payload ?? {},
          });
        } else if (event === 'rollback') {
          handlers.onRollback({
            reason: data.reason ?? 'error',
            message: data.message ?? '本轮生成已作废',
            discarded: true,
          });
        } else if (event === 'reaction_check_required') {
          terminalEventReceived = true;
          handlers.onReactionCheckRequired({
            pending_turn_id: data.pending_turn_id ?? '',
            flow_kind: data.flow_kind ?? 'npc_chat',
            reply_so_far: data.reply_so_far ?? '',
            scene_events_so_far: data.scene_events_so_far ?? [],
            pending_reaction: data.pending_reaction ?? null,
            npc_role_id: data.npc_role_id ?? null,
          });
        } else if (event === 'error') {
          terminalEventReceived = true;
          handlers.onError(data.message ?? '未知错误');
        } else if (event === 'end') {
          terminalEventReceived = true;
          handlers.onTimeSpent(data.time_spent_min ?? 0);
          handlers.onDialogueLogs(data.dialogue_logs ?? []);
          handlers.onSceneEvents(data.scene_events ?? []);
          handlers.onEnd();
        }
      } catch {
        handlers.onError('流消息解析失败');
      }
    }
  }
}

export function toMapSnapshot(save: SaveFile): MapSnapshot {
  return save.map_snapshot ?? { player_position: null, zones: [] };
}


export async function initWorldClock(
  payload: { session_id: string; calendar?: string },
  report?: DebugReporter,
): Promise<{ ok: boolean; clock: NonNullable<AreaSnapshot['clock']> }> {
  return requestJson(
    '/world/clock/init',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: payload.session_id, calendar: payload.calendar ?? 'fantasy_default' }),
    },
    report,
  );
}

export async function getCurrentArea(sessionId: string, report?: DebugReporter): Promise<{ ok: boolean; area_snapshot: AreaSnapshot }> {
  return requestJson(`/world/area/current?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function moveToSubZone(
  payload: { session_id: string; to_sub_zone_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<AreaMoveResolvedResponse> {
  return requestJson(
    '/world/area/move-sub-zone',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function discoverAreaInteractions(
  payload: { session_id: string; sub_zone_id: string; intent: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<AreaDiscoverInteractionsResolvedResponse> {
  return requestJson(
    '/world/area/interactions/discover',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function executeAreaInteraction(
  payload: {
    session_id: string;
    interaction_id: string;
    action_kind?: string;
    actor_kind?: 'player' | 'role';
    actor_role_id?: string;
    item_instance_id?: string;
    prompt?: string;
    action_check?: ActionCheckResult | null;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<AreaExecuteInteractionResolvedResponse> {
  return requestJson(
    '/world/area/interactions/execute',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}

export async function getTemplateLibraryStatus(
  sessionId: string,
  report?: DebugReporter,
): Promise<TemplateLibraryStatusResponse> {
  return requestJson(`/debug/template-library/status?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET' }, report);
}

export async function fillTemplateLibrary(
  payload: { session_id: string; config?: AppConfig },
  report?: DebugReporter,
): Promise<TemplateLibraryFillResponse> {
  return requestJson(
    '/debug/template-library/fill',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}


export async function planActionCheck(
  payload: {
    session_id: string;
    action_type: 'attack' | 'check' | 'item_use';
    check_mode?: 'action' | 'reaction_save';
    action_prompt: string;
    actor_role_id?: string;
    source_context?: 'generic' | 'public_turn';
    source_label?: string;
    threatened_consequence?: string;
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<ActionCheckPlan> {
  return requestJson(
    '/actions/check/plan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}


export async function runActionCheck(
  payload: {
    session_id: string;
    action_type: 'attack' | 'check' | 'item_use';
    check_mode?: 'action' | 'reaction_save';
    action_prompt: string;
    actor_role_id?: string;
    source_context?: 'generic' | 'public_turn';
    resolution_rule?: 'static_dc' | 'opposed_actor';
    target_role_id?: string | null;
    target_name?: string | null;
    target_actor_kind?: 'player' | 'npc' | null;
    target_ability_used?: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma' | null;
    target_ability_modifier?: number | null;
    pending_turn_id?: string;
    source_label?: string;
    threatened_consequence?: string;
    forced_dice_roll?: number;
    allow_backend_roll?: boolean;
    resolution_context?: 'standalone' | 'embedded';
    planned_ability_used?: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
    planned_dc?: number;
    planned_time_spent_min?: number;
    planned_requires_check?: boolean;
    planned_check_task?: string;
    return_state_sync?: boolean;
    post_trigger_kind?: 'random_move' | 'random_dialog' | 'scripted' | 'quest_rule' | 'fate_rule' | 'debug_forced';
    config?: AppConfig;
  },
  report?: DebugReporter,
): Promise<ActionCheckResult> {
  return requestJson(
    '/actions/check',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    report,
  );
}
