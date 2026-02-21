export type UIConfig = {
  theme: string;
};

export type AppConfig = {
  version: string;
  openai_api_key: string;
  model: string;
  stream: boolean;
  temperature: number;
  max_tokens: number;
  gm_prompt: string;
  ui?: UIConfig;
};

export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ChatResponse = {
  session_id: string;
  reply: ChatMessage;
  usage: {
    input_tokens: number;
    output_tokens: number;
  };
};

export const defaultConfig: AppConfig = {
  version: '1.0.0',
  openai_api_key: 'sk-xxxx',
  model: 'gpt-4.1-mini',
  stream: true,
  temperature: 0.8,
  max_tokens: 1200,
  gm_prompt: '你是本次跑团的GM。请保持叙事一致、节奏紧凑，并给出明确选项。',
  ui: {
    theme: 'dark',
  },
};

