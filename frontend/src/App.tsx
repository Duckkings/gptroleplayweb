import { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';
import { DebugPanel } from './components/DebugPanel';
import { GameLogPanel } from './components/GameLogPanel';
import { MapPanel } from './components/MapPanel';
import { NpcPoolPanel } from './components/NpcPoolPanel';
import { PlayerPanel } from './components/PlayerPanel';
import { ActionCheckPanel } from './components/ActionCheckPanel';
import {
  clearSave,
  discoverAreaInteractions,
  describeBehavior,
  generateRegions,
  getGameLogs,
  getGameLogSettings,
  getConfigPath,
  getCurrentArea,
  getCurrentSave,
  getPlayerRuntime,
  getPlayerStatic,
  getRoleCard,
  getRolePool,
  getSavePath,
  getTokenUsage,
  initWorldClock,
  importSave,
  moveToZone,
  npcChat,
  pickConfigPath,
  pickSavePath,
  npcGreet,
  runActionCheck,
  moveToSubZone,
  renderWorldMap,
  saveConfig,
  sendChat,
  setGameLogSettings,
  setPlayerRuntime,
  setPlayerStatic,
  streamChat,
  streamNpcChat,
  toMapSnapshot,
  validateConfig,
} from './services/api';
import {
  defaultPlayerStaticData,
  defaultConfig,
  type ApiDebugEntry,
  type ActionCheckResult,
  type AreaSnapshot,
  type AppConfig,
  type ChatMessage,
  type GameLogEntry,
  type MapSnapshot,
  type PathStatus,
  type PlayerRuntimeData,
  type PlayerStaticData,
  type NpcRoleCard,
  type Position,
  type RenderResult,
  type SaveFile,
  type TokenUsageSummary,
} from './types/app';

type View = 'boot' | 'config' | 'chat';
type ChatState = 'idle' | 'sending' | 'streaming' | 'error';
type ChatMode = 'main' | 'npc';

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

function App() {
  const [view, setView] = useState<View>('boot');
  const [configReturnView, setConfigReturnView] = useState<View>('boot');
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [mainMessages, setMainMessages] = useState<ChatMessage[]>([]);
  const [npcChatMessages, setNpcChatMessages] = useState<Record<string, ChatMessage[]>>({});
  const [chatMode, setChatMode] = useState<ChatMode>('main');
  const [activeNpcChat, setActiveNpcChat] = useState<{ npcId: string; npcName: string } | null>(null);
  const [lastUserInput, setLastUserInput] = useState('');
  const [input, setInput] = useState('');
  const [tokenUsage, setTokenUsage] = useState<TokenUsageSummary>(EMPTY_TOKEN_USAGE);
  const [chatState, setChatState] = useState<ChatState>('idle');
  const [godMode, setGodMode] = useState(false);
  const [error, setError] = useState('');
  const [configHint, setConfigHint] = useState('');
  const [sessionId, setSessionId] = useState(() => `sess_${Date.now()}`);
  const [configJson, setConfigJson] = useState(() => JSON.stringify(defaultConfig, null, 2));
  const [configPath, setCfgPath] = useState<PathStatus | null>(null);

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
  const [gameLogs, setGameLogs] = useState<GameLogEntry[]>([]);
  const [gameLogFetchLimit, setGameLogFetchLimit] = useState(10);
  const [mapSearch, setMapSearch] = useState('');
  const [mapSnapshot, setMapSnapshot] = useState<MapSnapshot>({ player_position: null, zones: [] });
  const [mapRender, setMapRender] = useState<RenderResult | null>(null);
  const [playerPanelOpen, setPlayerPanelOpen] = useState(false);
  const [npcPoolOpen, setNpcPoolOpen] = useState(false);
  const [npcPoolSearch, setNpcPoolSearch] = useState('');
  const [npcPoolItems, setNpcPoolItems] = useState<NpcRoleCard[]>([]);
  const [npcPoolTotal, setNpcPoolTotal] = useState(0);
  const [npcSelected, setNpcSelected] = useState<NpcRoleCard | null>(null);
  const [actionPanelOpen, setActionPanelOpen] = useState(false);
  const [lastActionResult, setLastActionResult] = useState<ActionCheckResult | null>(null);
  const [timeNotices, setTimeNotices] = useState<Array<{ id: number; text: string }>>([]);
  const [playerStatic, setPlayerStaticState] = useState<PlayerStaticData>(defaultPlayerStaticData);
  const [playerRuntime, setPlayerRuntimeState] = useState<PlayerRuntimeData>({
    session_id: sessionId,
    current_position: DEFAULT_POSITION,
    updated_at: new Date().toISOString(),
  });
  const [aiWaiting, setAiWaiting] = useState(false);
  const [aiWaitingText, setAiWaitingText] = useState('正在等待 AI 生成...');

  const abortRef = useRef<AbortController | null>(null);
  const configFileInputRef = useRef<HTMLInputElement | null>(null);

  const canSend = input.trim().length > 0 && (chatState === 'idle' || chatState === 'error');

  const statusText = useMemo(() => {
    if (chatState === 'sending') return '发送中...';
    if (chatState === 'streaming') return '生成中...';
    if (chatState === 'error') return `错误: ${error}`;
    return '就绪';
  }, [chatState, error]);
  const currentSubZone = useMemo(() => {
    if (!areaSnapshot?.current_sub_zone_id) return null;
    return areaSnapshot.sub_zones.find((s) => s.sub_zone_id === areaSnapshot.current_sub_zone_id) ?? null;
  }, [areaSnapshot]);

  const tokenTotal = tokenUsage.total.total_tokens;
  const displayedMessages =
    chatMode === 'main' ? mainMessages : activeNpcChat ? (npcChatMessages[activeNpcChat.npcId] ?? []) : [];
  const setDisplayedMessages = (next: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    if (chatMode === 'main') {
      setMainMessages((prev) => (typeof next === 'function' ? next(prev) : next));
      return;
    }
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
  const setAssistantOnly = (text: string): void => {
    if (isAlreadyThereHint(text)) {
      showAlreadyTherePopup(text);
      return;
    }
    setDisplayedMessages([{ role: 'assistant', content: text }]);
  };
  const pushTimeNotice = (minutes: number, reason: string) => {
    if (minutes <= 0) return;
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setTimeNotices((prev) => [...prev, { id, text: `时间消耗 +${minutes} 分钟（${reason}）` }]);
    window.setTimeout(() => {
      setTimeNotices((prev) => prev.filter((n) => n.id !== id));
    }, 3200);
  };
  const logsToMessages = (logs: GameLogEntry[]): ChatMessage[] => {
    let lastAssistant: string | null = null;
    for (const item of logs) {
      if (item.kind === 'gm_reply' || item.kind === 'move' || item.kind === 'area_move') {
        lastAssistant = item.message;
      }
    }
    return lastAssistant ? [{ role: 'assistant', content: lastAssistant }] : [];
  };
  const dialogueLogsToMessages = (role: NpcRoleCard): ChatMessage[] =>
    (role.dialogue_logs ?? []).map((item) => ({
      role: item.speaker === 'player' ? 'user' : 'assistant',
      content: `[${item.world_time_text}] ${item.speaker_name}: ${item.content}`,
    }));

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

  const syncStateFromSave = async (sid: string = sessionId) => {
    try {
      const save = await getCurrentSave(report);
      if (save.session_id !== sid) return;
      setMapSnapshot(toMapSnapshot(save));
      setAreaSnapshot(save.area_snapshot ?? null);
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

  useEffect(() => {
    void (async () => {
      try {
        const [cfgPath, svPath, save] = await Promise.all([getConfigPath(report), getSavePath(report), getCurrentSave(report)]);
        setCfgPath(cfgPath);
        setSvPath(svPath);
        setMapSnapshot(toMapSnapshot(save));
        setAreaSnapshot(save.area_snapshot ?? null);
        setMainMessages(logsToMessages(save.game_logs ?? []));
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
        await refreshTokenUsage(sid);
      } catch {
        // Ignore boot-time failures; user can continue with manual setup.
      }
    })();
  }, []);

  const formatValidateErrors = (errors: Array<{ field: string; message: string }>) =>
    errors.map((e) => `${e.field}: ${e.message}`).join('; ');

  const onNewConfig = () => {
    setConfigReturnView('boot');
    setConfig(defaultConfig);
    setConfigJson(JSON.stringify(defaultConfig, null, 2));
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onOpenConfigFromChat = () => {
    setConfigReturnView('chat');
    setConfigJson(JSON.stringify(config, null, 2));
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onLoadConfigFile = async (file: File) => {
    const text = await file.text();
    setConfigJson(text);
    setError('');
    setConfigHint('');
    try {
      const parsed = JSON.parse(text) as AppConfig;
      const result = await validateConfig(parsed, report);
      if (!result.valid) {
        setError(`配置校验失败: ${formatValidateErrors(result.errors)}`);
        setView('config');
        return;
      }
      setConfig(parsed);
      setConfigJson(JSON.stringify(parsed, null, 2));
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
      setConfigHint(`配置路径已更新: ${path.path}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '配置文件夹选择失败');
    }
  };

  const onValidateConfigText = async () => {
    setError('');
    setConfigHint('');
    try {
      const parsed = JSON.parse(configJson) as AppConfig;
      const result = await validateConfig(parsed, report);
      if (!result.valid) {
        setError(`配置校验失败: ${formatValidateErrors(result.errors)}`);
        return;
      }
      await saveConfig(parsed, report);
      setConfig(parsed);
      setView('chat');
      setChatState('idle');
      setConfigHint('配置已保存到后端路径。');
    } catch (e) {
      setError(`JSON 格式错误: ${e instanceof Error ? e.message : '配置解析失败'}`);
    }
  };

  const onSend = async () => {
    const userInput = input.trim();
    if (!userInput) return;
    if (chatMode === 'npc' && activeNpcChat) {
      setLastUserInput(userInput);
      setInput('');
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
            [activeNpcChat.npcId]: [...current, { role: 'user', content: userInput }, { role: 'assistant', content: '' }],
          };
        });
        try {
          await streamNpcChat(
            {
              session_id: sessionId,
              npc_role_id: activeNpcChat.npcId,
              player_message: userInput,
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
                void refreshTokenUsage(sessionId);
                void refreshNpcPool(npcPoolSearch);
                void refreshGameLogs(sessionId);
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
              player_message: userInput,
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
          await refreshGameLogs(sessionId);
          setChatState('idle');
        } catch (e) {
          setError(e instanceof Error ? e.message : 'NPC聊天失败');
          setChatState('error');
        }
      }
      return;
    }
    const npcSystemMessage: ChatMessage[] =
      chatMode === 'npc' && activeNpcChat
        ? [{ role: 'system', content: `当前对话对象为 NPC「${activeNpcChat.npcName}」，请只以该 NPC 身份做出回应。` }]
        : [];
    const nextMessages: ChatMessage[] = [...npcSystemMessage, { role: 'user', content: userInput }];
    const speakReason = chatMode === 'npc' && activeNpcChat ? `发言:${activeNpcChat.npcName}` : '发言';
    setLastUserInput(userInput);
    setInput('');
    setError('');
    const effectivePrompt = `${config.gm_prompt}\n${NARRATOR_STYLE_PROMPT}${godMode ? `\n${GOD_MODE_PROMPT}` : ''}`;
    const effectiveConfig: AppConfig = { ...config, gm_prompt: effectivePrompt };

    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;

      setDisplayedMessages([{ role: 'assistant', content: '' }]);

      try {
        await streamChat(
          {
            session_id: sessionId,
            config: effectiveConfig,
            messages: nextMessages,
          },
          {
            onDelta: (delta) => {
              setDisplayedMessages((prev) => {
                const current = prev[0]?.role === 'assistant' ? prev[0].content : '';
                const next = `${current}${delta}`;
                return [{ role: 'assistant', content: next }];
              });
            },
            onError: (message) => {
              setError(message);
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
            onEnd: () => {
              setDisplayedMessages((prev) => {
                const text = prev[0]?.role === 'assistant' ? prev[0].content : '';
                if (text && isAlreadyThereHint(text)) {
                  showAlreadyTherePopup(text);
                  return [];
                }
                return prev;
              });
              setChatState('idle');
              void refreshTokenUsage(sessionId);
              void syncStateFromSave(sessionId);
              void refreshGameLogs();
            },
          },
          controller.signal,
          report,
        );
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '流式请求失败');
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
      setAssistantOnly(response.reply.content);
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
      await syncStateFromSave(sessionId);
      await refreshGameLogs();
      setChatState('idle');
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
      setChatState('error');
    }
  };

  const onStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setChatState('idle');
  };

  const onRetry = () => {
    if (!lastUserInput) return;
    setInput(lastUserInput);
  };

  const onClear = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMainMessages([]);
    setNpcChatMessages({});
    setChatMode('main');
    setActiveNpcChat(null);
    setInput('');
    const nextSessionId = `sess_${Date.now()}`;
    setSessionId(nextSessionId);
    setTokenUsage({ ...EMPTY_TOKEN_USAGE, session_id: nextSessionId });
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
      const result = await runActionCheck(
        {
          session_id: sessionId,
          action_type: payload.action_type,
          action_prompt: payload.action_prompt,
          actor_role_id: payload.actor_role_id,
          config,
        },
        report,
      );
      setLastActionResult(result);
      setAssistantOnly(result.narrative);
      pushTimeNotice(result.time_spent_min, '行为检定');
      await refreshNpcPool(npcPoolSearch);
      await syncStateFromSave(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '行为检定失败');
    }
  };

  const refreshAreaSnapshot = async () => {
    const area = await getCurrentArea(sessionId, report);
    setAreaSnapshot(area.area_snapshot);
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
      await syncStateFromSave(sessionId);
      await refreshGameLogs(sessionId);
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
    const prompt = window.prompt(`你想如何使用/观察【${itemName}】？`);
    if (!prompt || !prompt.trim()) return;
    try {
      const result = await runActionCheck(
        {
          session_id: sessionId,
          action_type: 'item_use',
          action_prompt: `interaction_id=${interactionId}; item=${itemName}; prompt=${prompt.trim()}`,
          actor_role_id: playerStatic.player_id,
          config,
        },
        report,
      );
      setLastActionResult(result);
      setAssistantOnly(result.narrative);
      pushTimeNotice(result.time_spent_min, `物品使用:${itemName}`);
      await syncStateFromSave(sessionId);
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '物品使用失败');
    }
  };

  const onEnterNpcChat = async (npcId: string, npcName: string) => {
    setChatMode('npc');
    setActiveNpcChat({ npcId, npcName });
    setInput('');
    setError('');
    setAiWaitingText(`正在等待 ${npcName} 的问候...`);
    setAiWaiting(true);
    try {
      const beforeRole = await getRoleCard(sessionId, npcId, report);
      setNpcChatMessages((prev) => ({ ...prev, [npcId]: dialogueLogsToMessages(beforeRole) }));
      const greet = await npcGreet(
        {
          session_id: sessionId,
          npc_role_id: npcId,
          config,
        },
        report,
      );
      const afterRole = await getRoleCard(sessionId, npcId, report);
      const fromSave = dialogueLogsToMessages(afterRole);
      setNpcChatMessages((prev) => ({
        ...prev,
        [npcId]: fromSave.length > 0 ? fromSave : [...(prev[npcId] ?? []), { role: 'assistant', content: greet.greeting }],
      }));
      await refreshGameLogs(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'NPC问候失败');
    } finally {
      setAiWaiting(false);
    }
  };

  const onLeaveNpcChat = () => {
    setChatMode('main');
    setActiveNpcChat(null);
    setInput('');
    setError('');
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
      await refreshGameLogs(sessionId);
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
      setMainMessages(logsToMessages(save.game_logs ?? []));
      setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
      setPlayerRuntimeState(
        save.player_runtime_data ?? {
          session_id: save.session_id,
          current_position: save.map_snapshot?.player_position ?? DEFAULT_POSITION,
          updated_at: new Date().toISOString(),
        },
      );
      await ensureMap();
      await refreshTokenUsage(save.session_id);
      await refreshGameLogs(save.session_id);
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
      setPlayerStaticState(save.player_static_data ?? defaultPlayerStaticData);
      setPlayerRuntimeState(
        save.player_runtime_data ?? {
          session_id: save.session_id,
          current_position: DEFAULT_POSITION,
          updated_at: new Date().toISOString(),
        },
      );
      setMapRender(null);
      setMapOpen(false);
      setLogOpen(false);
      setMapEnabled(false);
      setMapPromptDialogOpen(false);
      setMainMessages([]);
      setNpcChatMessages({});
      setChatMode('main');
      setActiveNpcChat(null);
      setInput('');
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
          <p>请确认配置内容（含 openai_api_key），确认后再进入聊天。</p>
          <div className="actions">
            <button onClick={() => void onPickConfigPath()}>选择配置文件夹</button>
          </div>
          {configPath && <p className="hint">当前配置路径: {configPath.path}</p>}
          <textarea value={configJson} onChange={(e) => setConfigJson(e.target.value)} />
          <div className="actions">
            <button onClick={() => setView(configReturnView)}>返回</button>
            <button onClick={() => void onValidateConfigText()}>校验并进入聊天</button>
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
        onOpenNpcPool={() => void onOpenNpcPool()}
        onOpenActionPanel={() => void onOpenActionPanel()}
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
              Token 消耗(全 AI 请求): in {tokenUsage.total.input_tokens} / out {tokenUsage.total.output_tokens} / total {tokenTotal} | 聊天 {tokenUsage.sources.chat.total_tokens} / 地图 {tokenUsage.sources.map_generation.total_tokens} / 移动反馈 {tokenUsage.sources.movement_narration.total_tokens}
            </p>
          </div>
          <div className="actions">
            {chatMode === 'npc' && <button onClick={onLeaveNpcChat}>返回主聊天</button>}
            <button onClick={onOpenConfigFromChat}>配置</button>
            <button onClick={onClear}>新建会话</button>
            <button onClick={() => void onOpenLogs()}>日志</button>
            <button onClick={() => void onOpenMap()} disabled={!mapEnabled}>
              打开世界地图
            </button>
          </div>
        </header>

        <section className="messages">
          {displayedMessages.length === 0 && <p className="hint">{chatMode === 'npc' ? '点击 NPC 按钮开始单独对话。' : '开始你的第一条叙事输入。'}</p>}
          {displayedMessages.map((m, index) => (
            <article key={`${m.role}_${index}`} className={`msg ${m.role}`}>
              <strong>{m.role === 'user' ? '你' : m.role === 'assistant' ? 'GM' : 'System'}</strong>
              <p>{m.content}</p>
            </article>
          ))}
        </section>

        {chatMode === 'main' && (
          <section className="chat-interactions">
            <h3>可互动物品</h3>
            <div className="actions">
              <button
                onClick={() => {
                  if (!currentSubZone) return;
                  void onDiscoverAreaInteraction(currentSubZone.sub_zone_id, '观察周围细节');
                }}
                disabled={!currentSubZone}
              >
                +发现新交互
              </button>
              {(currentSubZone?.key_interactions ?? []).map((it) => (
                <button key={it.interaction_id} onClick={() => void onUseAreaItem(it.interaction_id, it.name)}>
                  {it.name}
                </button>
              ))}
              {(currentSubZone?.key_interactions?.length ?? 0) === 0 && <p className="hint">当前暂无可互动物品。</p>}
            </div>
          </section>
        )}

        {chatMode === 'main' && (
          <section className="chat-interactions">
            <h3>可交互NPC</h3>
            <div className="actions">
              {(currentSubZone?.npcs ?? []).map((npc) => (
                <button key={npc.npc_id} onClick={() => void onEnterNpcChat(npc.npc_id, npc.name)}>
                  {npc.name}
                </button>
              ))}
              {(currentSubZone?.npcs?.length ?? 0) === 0 && <p className="hint">当前暂无可交互NPC。</p>}
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
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={chatMode === 'npc' && activeNpcChat ? `对 ${activeNpcChat.npcName} 说点什么...` : '输入你的行动，例如：我查看桌上的羊皮地图。'}
            disabled={chatState === 'sending' || chatState === 'streaming'}
          />
          <div className="actions">
            <label className="god-mode-toggle">
              <input type="checkbox" checked={godMode} onChange={(e) => setGodMode(e.target.checked)} />
              上帝模式
            </label>
            {chatState === 'streaming' && <button onClick={onStop}>停止生成</button>}
            <button onClick={onRetry}>重新生成</button>
            <button disabled={!canSend} onClick={() => void onSend()}>
              发送
            </button>
          </div>
          {error && <p className="error">{error}</p>}
        </footer>
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
        open={playerPanelOpen}
        value={playerStatic}
        onClose={() => setPlayerPanelOpen(false)}
        onSave={(next) => void onSavePlayerStatic(next)}
      />

      <NpcPoolPanel
        open={npcPoolOpen}
        items={npcPoolItems}
        total={npcPoolTotal}
        search={npcPoolSearch}
        selected={npcSelected}
        onSearch={onSearchNpcPool}
        onRefresh={() => void refreshNpcPool()}
        onSelect={(roleId) => void onSelectNpcRole(roleId)}
        onClose={() => setNpcPoolOpen(false)}
      />

      <ActionCheckPanel
        open={actionPanelOpen}
        npcs={npcPoolItems}
        playerRoleId={playerStatic.player_id}
        lastResult={lastActionResult}
        onRun={(payload) => void onRunActionCheck(payload)}
        onClose={() => setActionPanelOpen(false)}
      />

      <GameLogPanel
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

