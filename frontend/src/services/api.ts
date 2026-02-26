import type {
  ActionCheckResult,
  AreaMoveResult,
  AreaSnapshot,
  AppConfig,
  ChatMessage,
  ChatResponse,
  GameLogEntry,
  GameLogSettings,
  MapSnapshot,
  MovementLog,
  NpcChatResponse,
  NpcGreetResponse,
  NpcRoleCard,
  PathStatus,
  PlayerRuntimeData,
  PlayerStaticData,
  RenderResult,
  SaveFile,
  ToolEvent,
  TokenUsageSummary,
  Usage,
  Zone,
} from '../types/app';

const API_BASE = '/api/v1';

type DebugReporter = (payload: { endpoint: string; status: number; ok: boolean; usage?: Usage; detail?: string }) => void;

async function requestJson<T>(endpoint: string, init: RequestInit, report?: DebugReporter): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, init);
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
  config: AppConfig,
  report?: DebugReporter,
): Promise<{ valid: boolean; errors: Array<{ field: string; message: string }> }> {
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

export async function sendChat(
  payload: {
    session_id: string;
    config: AppConfig;
    messages: ChatMessage[];
  },
  report?: DebugReporter,
): Promise<ChatResponse> {
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
    onEnd: () => void;
    onUsage: (usage: Usage) => void;
    onTimeSpent: (minutes: number) => void;
    onToolEvents: (events: ToolEvent[]) => void;
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

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      handlers.onEnd();
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
          tool_events?: ToolEvent[];
          time_spent_min?: number;
        };
        if (event === 'delta') {
          handlers.onDelta(data.content ?? '');
        } else if (event === 'error') {
          handlers.onError(data.message ?? '未知错误');
        } else if (event === 'end') {
          handlers.onUsage(data.usage ?? { input_tokens: 0, output_tokens: 0 });
          handlers.onTimeSpent(data.time_spent_min ?? 0);
          handlers.onToolEvents(data.tool_events ?? []);
          handlers.onEnd();
        }
      } catch {
        handlers.onError('流消息解析失败');
      }
    }
  }
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

export async function renderWorldMap(
  payload: { session_id: string; zones: Zone[]; player_position: { x: number; y: number; z: number; zone_id: string } },
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
  payload: { session_id: string; from_zone_id: string; to_zone_id: string; player_name?: string },
  report?: DebugReporter,
): Promise<{ session_id: string; new_position: { x: number; y: number; z: number; zone_id: string }; duration_min: number; movement_log: MovementLog }> {
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
): Promise<NpcChatResponse> {
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
    onTimeSpent: (minutes: number) => void;
    onDialogueLogs: (logs: NpcChatResponse['dialogue_logs']) => void;
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
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      handlers.onEnd();
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
          time_spent_min?: number;
          dialogue_logs?: NpcChatResponse['dialogue_logs'];
        };
        if (event === 'delta') {
          handlers.onDelta(data.content ?? '');
        } else if (event === 'error') {
          handlers.onError(data.message ?? '未知错误');
        } else if (event === 'end') {
          handlers.onTimeSpent(data.time_spent_min ?? 0);
          handlers.onDialogueLogs(data.dialogue_logs ?? []);
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
): Promise<AreaMoveResult> {
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
): Promise<{ ok: boolean; generated_mode: 'instant'; new_interactions: NonNullable<AreaSnapshot['sub_zones']>[number]['key_interactions'] }> {
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
  payload: { session_id: string; interaction_id: string },
  report?: DebugReporter,
): Promise<{ ok: boolean; status: 'placeholder'; message: string }> {
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


export async function runActionCheck(
  payload: {
    session_id: string;
    action_type: 'attack' | 'check' | 'item_use';
    action_prompt: string;
    actor_role_id?: string;
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
