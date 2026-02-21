# gptroleplayweb
## Docs
- `docs/mvp-architecture.md`: MVP 架构、配置 schema、API 契约、开发顺序

## Current Features
- 本地 JSON 配置导入（JSON 语法 + schema 校验）
- 配置确认页（校验通过后需手动确认再进入聊天）
- 非流式聊天 + SSE 流式聊天
- 停止生成、重新生成
- 新建会话（清空当前消息并创建新 `session_id`）
- 一键启动前后端（`start-dev.bat`）

## Quick Start（本地后端 + 网页前端）
0. 一键启动（推荐）：
```bat
start-dev.bat
```

1. 启动后端（默认 `127.0.0.1:8000`）：
```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
如果 `python` 命令不可用，改用 `py -3`。
2. 启动前端（默认 `127.0.0.1:5173`）：
```powershell
cd frontend
npm install
npm run dev
```
3. 在配置页或 `config.json` 中填写 `openai_api_key` 后进入聊天。

完整说明见 `docs/mvp-architecture.md` 第 11 节。


