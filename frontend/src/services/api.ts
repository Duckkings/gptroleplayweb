import type { AppConfig, ChatMessage, ChatResponse } from '../types/app';

const API_BASE = '/api/v1';

export async function validateConfig(config: AppConfig): Promise<{ valid: boolean; errors: Array<{ field: string; message: string }> }> {
  const response = await fetch(`${API_BASE}/config/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    throw new Error(`配置校验失败: ${response.status}`);
  }

  return response.json();
}

export async function sendChat(payload: {
  session_id: string;
  config: AppConfig;
  messages: ChatMessage[];
}): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`聊天失败(${response.status}): ${text}`);
  }

  return response.json();
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
  },
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
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
        const data = JSON.parse(dataLine);
        if (event === 'delta') {
          handlers.onDelta(data.content ?? '');
        } else if (event === 'error') {
          handlers.onError(data.message ?? '未知错误');
        } else if (event === 'end') {
          handlers.onEnd();
        }
      } catch {
        handlers.onError('流消息解析失败');
      }
    }
  }
}
