# Roleplay Web MVP 架构与接口契约

## 设计来源
- docs/design/gamedesign/gamedesign.md

## 1. 目标
- 先做可用 MVP：本地配置、聊天、可选流式输出、基础错误恢复。
- API Key 放入本地 `config.json`，由后端读取并转发请求。
- 协议先稳定，再迭代 UI/功能，减少返工。

## 2. 推荐技术栈
- 前端：`React + Vite + TypeScript`
- 后端：`FastAPI + Uvicorn + Pydantic`
- 存储：本地 `config.json`（仅保存非敏感配置），会话先内存存储
- 通信：普通请求用 `JSON`，流式回复用 `SSE`

## 3. 目录结构（MVP）
```txt
gptroleplayweb/
  frontend/
    src/
      pages/
      components/
      services/
      store/
      styles/
  backend/
    app/
      main.py
      api/
      core/
      models/
      services/
  shared/
    schemas/
      config.schema.json
  docs/
    technical/
      mvp-architecture.md
```

## 4. 配置文件契约
配置文件存本地运行参数与 `openai_api_key`，后端从请求配置读取 key。

### `config.json`
```json
{
  "version": "1.0.0",
  "openai_api_key": "sk-xxxx",
  "model": "gpt-4.1-mini",
  "stream": true,
  "temperature": 0.8,
  "max_tokens": 1200,
  "gm_prompt": "你是本次跑团的GM...",
  "ui": {
    "theme": "dark"
  }
}
```

### 校验规则
- `version` 必填，语义化版本字符串。
- `openai_api_key` 必填，非空字符串。
- `model` 必填，字符串。
- `stream` 必填，布尔。
- `temperature` 可选，`0` 到 `2`。
- `max_tokens` 可选，正整数。
- `gm_prompt` 必填，非空字符串。

## 5. 后端 API 契约
基础前缀：`/api/v1`

### 5.1 健康检查
- `GET /health`
- 响应：
```json
{
  "ok": true,
  "time": "2026-02-18T12:00:00Z"
}
```

### 5.2 配置校验
- `POST /config/validate`
- 请求体：完整 `config.json`
- 成功响应：
```json
{
  "valid": true,
  "errors": []
}
```
- 失败响应：
```json
{
  "valid": false,
  "errors": [
    {
      "field": "gm_prompt",
      "message": "must not be empty"
    }
  ]
}
```

### 5.3 非流式聊天
- `POST /chat`
- 请求体：
```json
{
  "session_id": "sess_001",
  "config": {
    "openai_api_key": "sk-xxxx",
    "model": "gpt-4.1-mini",
    "stream": false,
    "temperature": 0.8,
    "max_tokens": 1200,
    "gm_prompt": "你是本次跑团的GM..."
  },
  "messages": [
    {"role": "user", "content": "我推开酒馆大门。"}
  ]
}
```
- 响应：
```json
{
  "session_id": "sess_001",
  "reply": {
    "role": "assistant",
    "content": "酒馆里烛火摇曳..."
  },
  "usage": {
    "input_tokens": 123,
    "output_tokens": 98
  }
}
```

### 5.4 流式聊天（SSE）
- `POST /chat/stream`
- 请求体与 `/chat` 相同，`config.stream` 必须为 `true`。
- 响应类型：`text/event-stream`

事件约定：
- `event: start`：开始生成
- `event: delta`：增量文本
- `event: end`：生成结束
- `event: error`：错误信息

示例：
```txt
event: start
data: {"session_id":"sess_001"}

event: delta
data: {"content":"酒馆里"}

event: delta
data: {"content":"烛火摇曳..."}

event: end
data: {"usage":{"input_tokens":123,"output_tokens":98}}
```

### 5.5 错误码（统一）
- `400` 参数错误
- `401` `config.openai_api_key` 缺失或为空
- `429` 上游限流
- `500` 内部错误
- `502` 上游模型服务错误

## 6. 上下文与 Prompt 规则
- 系统层 Prompt 由后端拼接，前端不可覆盖。
- 组装顺序：`system(gm_prompt)` -> 历史消息 -> 最新用户输入。
- 历史保留策略：先按最近轮次保留，再按 token 上限截断。
- 最低要求：保留最近 `12` 条消息（可配置）。

## 7. 前端页面与状态机
## 7.1 页面
- `BootPage`：选择“读取配置”或“新建配置”
- `ConfigPage`：编辑配置并校验
- `ChatPage`：主聊天页面

## 7.2 ChatPage 状态
- `idle`：可输入
- `sending`：请求发送中
- `streaming`：流式接收中
- `error`：显示错误并允许重试

## 7.3 最低交互要求
- 发送消息
- 停止生成（流式时可中断）
- 重新生成上一条回复
- 消息失败重试
- 新建会话（清空当前会话并生成新 `session_id`）

## 7.4 当前实现流程（已落地）
1. 进入 `BootPage`，选择“读取本地配置”或“新建/编辑配置”。
2. 读取本地配置时，先做 JSON 语法校验，再调用 `/config/validate`。
3. 校验通过后不会直接进聊天，而是进入 `ConfigPage` 打开该 JSON 供用户确认。
4. 用户点击“校验并进入聊天”后进入 `ChatPage`。
5. 在 `ChatPage` 可发送、流式停止、重新生成，以及“新建会话”。

## 8. 安全基线
- `config.json` 含明文 key，仅建议本机离线自用。
- 日志中脱敏 `Authorization`、用户隐私内容。
- 配置文件读写前后均做 schema 校验。

## 9. 开发顺序（建议）
1. 后端：`/health`、`/config/validate`、`/chat`
2. 后端：`/chat/stream` SSE
3. 前端：`BootPage + ConfigPage`
4. 前端：`ChatPage` 非流式
5. 前端：接入流式与停止生成
6. 补充错误处理和样式统一

## 10. 验收标准（MVP）
- 能通过配置页创建并保存合法 `config.json`
- 非流式和流式聊天都可工作
- 流式可停止，停止后 UI 状态正确恢复
- 配置错误、网络错误、429 均有用户可理解提示

## 11. 本地配置与启动（使用文档）
本项目采用“本地后端 + 本地前端网页”，不需要云服务器。

### 11.1 环境要求
- Python `3.11` 到 `3.14` 稳定版（推荐 `3.12` 或 `3.14`）
- Node.js `20+`
- npm `10+`
- Windows PowerShell（本文命令基于 PowerShell）
- 或直接用根目录 `start-dev.bat` 一键启动

### 11.0 一键启动（推荐）
在项目根目录运行：
```bat
start-dev.bat
```

脚本行为：
- 自动检测 `python` 或 `py -3`
- 自动创建 `backend/.venv314`（若不存在）
- 自动安装后端与前端依赖（首次）
- 同时启动后端 `127.0.0.1:8000` 与前端 `127.0.0.1:5173`
- 自动打开浏览器

### 11.2 配置文件填写 API Key
在配置页或 `config.json` 中填写：
```json
{
  "openai_api_key": "sk-xxxx"
}
```
提示：这是明文存储，仅建议本机个人使用。

### 11.3 后端启动
首次安装依赖：
```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
```

开发启动：
```powershell
cd backend
.\.venv314\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：
- 浏览器打开 `http://127.0.0.1:8000/api/v1/health`
- 返回 `{"ok": true, ...}` 即后端正常。

### 11.4 前端启动
首次安装依赖：
```powershell
cd frontend
npm install
```

开发启动：
```powershell
cd frontend
npm run dev
```

默认访问地址：
- `http://127.0.0.1:5173`

### 11.5 前后端联调配置
前端请求后端基地址建议使用：
- `http://127.0.0.1:8000/api/v1`

如果使用 Vite 代理，`frontend/vite.config.ts` 可配置：
```ts
server: {
  proxy: {
    "/api": "http://127.0.0.1:8000"
  }
}
```

### 11.6 常见问题
- 启动报 `openai_api_key` 缺失：
  - 检查 `config.json` 是否包含非空 `openai_api_key`。
- 前端请求报跨域错误：
  - 后端加 CORS（允许 `http://127.0.0.1:5173`）。
  - 或使用 Vite 代理转发 `/api`。
- 端口占用：
  - 后端改 `--port 8001`，同时更新前端 API 基地址。




