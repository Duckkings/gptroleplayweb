import { useMemo, useRef, useState } from 'react';
import './App.css';
import { sendChat, streamChat, validateConfig } from './services/api';
import { defaultConfig, type AppConfig, type ChatMessage } from './types/app';

type View = 'boot' | 'config' | 'chat';
type ChatState = 'idle' | 'sending' | 'streaming' | 'error';

function App() {
  const [view, setView] = useState<View>('boot');
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [chatState, setChatState] = useState<ChatState>('idle');
  const [error, setError] = useState('');
  const [configHint, setConfigHint] = useState('');
  const [sessionId, setSessionId] = useState(() => `sess_${Date.now()}`);
  const [configJson, setConfigJson] = useState(() => JSON.stringify(defaultConfig, null, 2));
  const abortRef = useRef<AbortController | null>(null);

  const canSend = input.trim().length > 0 && (chatState === 'idle' || chatState === 'error');

  const statusText = useMemo(() => {
    if (chatState === 'sending') return '发送中...';
    if (chatState === 'streaming') return '生成中...';
    if (chatState === 'error') return `错误: ${error}`;
    return '就绪';
  }, [chatState, error]);

  const formatValidateErrors = (errors: Array<{ field: string; message: string }>) =>
    errors.map((e) => `${e.field}: ${e.message}`).join('; ');

  const onNewConfig = () => {
    setConfig(defaultConfig);
    setConfigJson(JSON.stringify(defaultConfig, null, 2));
    setError('');
    setConfigHint('');
    setView('config');
  };

  const onOpenConfigFromChat = () => {
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
      const result = await validateConfig(parsed);
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

  const onValidateConfigText = async () => {
    setError('');
    setConfigHint('');
    try {
      const parsed = JSON.parse(configJson) as AppConfig;
      const result = await validateConfig(parsed);
      if (!result.valid) {
        setError(`配置校验失败: ${formatValidateErrors(result.errors)}`);
        return;
      }
      setConfig(parsed);
      setError('');
      setConfigHint('');
      setView('chat');
      setChatState('idle');
    } catch (e) {
      setError(`JSON 格式错误: ${e instanceof Error ? e.message : '配置解析失败'}`);
    }
  };

  const onSend = async () => {
    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput('');
    setError('');

    if (config.stream) {
      setChatState('streaming');
      const controller = new AbortController();
      abortRef.current = controller;

      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      try {
        await streamChat(
          {
            session_id: sessionId,
            config,
            messages: nextMessages,
          },
          {
            onDelta: (delta) => {
              setMessages((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                if (last?.role === 'assistant') {
                  copy[copy.length - 1] = { ...last, content: `${last.content}${delta}` };
                }
                return copy;
              });
            },
            onError: (message) => {
              setError(message);
              setChatState('error');
            },
            onEnd: () => {
              setChatState('idle');
            },
          },
          controller.signal,
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
      const response = await sendChat({
        session_id: sessionId,
        config,
        messages: nextMessages,
      });
      setMessages((prev) => [...prev, response.reply]);
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

  const onRetry = async () => {
    if (messages.length === 0) return;
    const trimmed = [...messages];
    if (trimmed[trimmed.length - 1]?.role === 'assistant') {
      trimmed.pop();
    }
    const lastUser = [...trimmed].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;
    setMessages(trimmed);
    setInput(lastUser.content);
  };

  const onClear = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setInput('');
    setSessionId(`sess_${Date.now()}`);
    setError('');
    setChatState('idle');
  };

  if (view === 'boot') {
    return (
      <main className="app-shell">
        <section className="card">
          <h1>Roleplay Web</h1>
          <p>选择读取已有配置，或先编辑一个新配置。</p>
          <div className="actions">
            <label className="file-button">
              读取本地配置
              <input
                type="file"
                accept="application/json"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onLoadConfigFile(file);
                  e.target.value = '';
                }}
              />
            </label>
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
          <textarea value={configJson} onChange={(e) => setConfigJson(e.target.value)} />
          <div className="actions">
            <button onClick={() => setView('boot')}>返回</button>
            <button onClick={onValidateConfigText}>校验并进入聊天</button>
          </div>
          {configHint && <p className="hint">{configHint}</p>}
          {error && <p className="error">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <section className="card chat-card">
        <header className="chat-header">
          <div>
            <h1>跑团聊天</h1>
            <p>{statusText}</p>
          </div>
          <div className="actions">
            <button onClick={onOpenConfigFromChat}>配置</button>
            <button onClick={onClear}>新建会话</button>
          </div>
        </header>

        <section className="messages">
          {messages.length === 0 && <p className="hint">开始你的第一条叙事输入。</p>}
          {messages.map((m, index) => (
            <article key={`${m.role}_${index}`} className={`msg ${m.role}`}>
              <strong>{m.role === 'user' ? '你' : m.role === 'assistant' ? 'GM' : 'System'}</strong>
              <p>{m.content}</p>
            </article>
          ))}
        </section>

        <footer className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入你的行动，例如：我查看桌上的羊皮地图。"
            disabled={chatState === 'sending' || chatState === 'streaming'}
          />
          <div className="actions">
            {chatState === 'streaming' && <button onClick={onStop}>停止生成</button>}
            <button onClick={onRetry}>重新生成</button>
            <button disabled={!canSend} onClick={onSend}>
              发送
            </button>
          </div>
          {error && <p className="error">{error}</p>}
        </footer>
      </section>
    </main>
  );
}

export default App;
