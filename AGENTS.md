# AGENTS.md

## 项目概述

`gptroleplayweb` 是一个本地运行的跑团（Tabletop RPG）网页原型。后端负责管理世界状态、游戏存档、任务/命运/遭遇/角色规则以及 AI 编排。前端提供聊天、配置、地图、日志、角色和调试界面。

这是一个**仅限本地运行的原型**（非生产环境产品），正处于持续迭代中。请始终以“当前已实现功能”作为事实来源；有关详细的系统约束和设计取舍，请参阅 `docs/` 目录。

## 新任务启动流程

对于任何涉及本仓库代码、功能、文档或测试的新任务，先按下面顺序建立上下文：
1. 先读 `docs/technical/technical.md`，把它当作仓库功能入口索引。
2. 再读仓库中日期最新的 `docs/technical/capability-snapshot-*.md`，把它当作当前功能状态摘要。
3. 只打开与当前任务直接相关的专题文档和实现文件，不要一开始无差别扫完整个仓库。

补充规则：
- 如果索引文档、专题文档与当前代码不一致，以当前代码和最新能力快照为准，再在任务结束后补回文档。
- 如果任务只是重写、翻译、总结或整理用户已经提供的文本，不需要额外扫仓库。
- 如果任务明显落在某个子系统上，先用索引定位，再下钻到最少文件集。

## 技术栈

### 后端
- **框架**: FastAPI + Uvicorn
- **语言**: Python 3.11 - 3.14 (推荐 3.12 或 3.14)
- **数据校验**: Pydantic v2
- **AI SDK**: OpenAI Python SDK, Google GenAI SDK
- **认证**: `itsdangerous` 用于签名的会话 Cookie
- **CORS**: 为本地开发配置 (端口 5173)

### 前端
- **框架**: React 19 + TypeScript
- **构建工具**: Vite 7
- **代码规范**: ESLint 9 (包含 TypeScript ESLint, React Hooks, React Refresh)
- **包管理器**: npm

### 存储
- **配置**: 本地 JSON 文件 (`config.json`)
- **存档**: 基于 Bundle 的分片 JSON 归档 (世界状态、玩家数据、任务、遭遇等)
- **多用户**: 数据按用户隔离在 `data/users/<username>/` 下

### AI 集成
- **支持的提供商**: OpenAI, DeepSeek, Gemini
- **流式传输**: Server-Sent Events (SSE) 用于实时叙事
- **非流式传输**: 标准 JSON 响应

## 项目结构

```
gptroleplayweb/
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 应用程序入口
│   │   ├── api/             # API 路由
│   │   │   ├── routes.py    # 主要 API 端点
│   │   │   └── auth_routes.py  # 认证端点
│   │   ├── core/            # 核心工具
│   │   │   ├── auth.py      # 会话管理
│   │   │   ├── storage.py   # 文件 I/O 操作
│   │   │   ├── prompt_table.py  # AI 提示词注册表
│   │   │   └── token_usage.py   # Token 消耗追踪
│   │   ├── models/          # Pydantic schemas 数据模型
│   │   │   └── schemas.py   # 数据模型 (配置、存档等)
│   │   └── services/        # 业务逻辑
│   │       ├── world_service.py      # 世界状态管理
│   │       ├── chat_service.py       # 主聊天编排
│   │       ├── stream_chat_service.py # SSE 流式传输
│   │       ├── fate_service.py       # 命运系统
│   │       ├── quest_service.py      # 任务管理
│   │       ├── encounter_service.py  # 遭遇系统
│   │       ├── team_service.py       # 队伍管理
│   │       ├── battle_service.py     # 战斗系统
│   │       └── ...
│   ├── tests/               # 单元测试
│   ├── requirements.txt     # Python 依赖
│   └── Dockerfile           # 后端容器
├── frontend/                # React + TypeScript 前端
│   ├── src/
│   │   ├── App.tsx          # 主应用程序组件
│   │   ├── main.tsx         # 入口文件
│   │   ├── components/      # React 组件
│   │   │   ├── DebugPanel.tsx
│   │   │   ├── QuestModal.tsx
│   │   │   ├── EncounterModal.tsx
│   │   │   ├── FatePanel.tsx
│   │   │   └── ...
│   │   ├── services/        # API 客户端
│   │   │   └── api.ts
│   │   └── types/           # TypeScript 类型定义
│   │       └── app.ts
│   ├── package.json         # npm 依赖
│   ├── vite.config.ts       # Vite 配置
│   ├── tsconfig.json        # TypeScript 配置
│   ├── eslint.config.js     # ESLint 配置
│   └── Dockerfile           # 前端容器
├── data/                    # 运行时数据
│   ├── ai-prompts.csv       # AI 提示词模板
│   ├── config.json          # 全局配置
│   ├── current-save.json    # 当前存档文件 (bundle 格式)
│   ├── users/               # 单个用户数据
│   └── storage/paths.json   # 路径配置
├── shared/                  # 共享 schemas
│   └── schemas/
│       └── config.schema.json
├── docs/                    # 文档目录
│   ├── design/gamedesign/   # 游戏设计文档
│   ├── technical/           # 技术规范
│   └── requirements/        # 需求文档
├── docker-compose.dev.yml   # Docker 开发环境配置
├── start-dev.bat           # Windows 一键启动脚本
└── AGENTS.md               # 当前文件
```

## 构建与开发命令

### 快速开始 (Windows)
```bat
start-dev.bat
```
此脚本将：
- 自动检测 Python (3.11-3.14) 或 `py -3`
- 如果缺失则创建 `backend/.venv314`
- 安装后端和前端依赖 (首次运行)
- 在 `127.0.0.1:8000` 启动后端，在 `127.0.0.1:5173` 启动前端
- 自动打开浏览器

### Docker 开发模式
```bash
docker compose -f docker-compose.dev.yml up --build
```
- 前端: http://localhost:5173
- 后端: http://localhost:8000

### 手动启动后端
```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 手动启动前端
```powershell
cd frontend
npm install
npm run dev
```

### 前端构建
```powershell
cd frontend
npm run build
```

## 测试

### 后端测试
```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/tests
```

测试文件位于 `backend/tests/` 目录，并遵循 `test_*.py` 命名规范：
- `test_config_models.py` - 配置校验
- `test_chat_route_scene_rendering.py` - 聊天场景渲染
- `test_quest_fate_encounter.py` - 任务/命运/遭遇系统
- `test_encounter_service.py` - 遭遇机制
- `test_team_service.py` - 队伍管理
- `test_battle_service.py` - 战斗系统
- 以及更多...

### 前端构建验证
```powershell
cd frontend
npm run build
```

## 代码风格指南

### Python (后端)
- 遵循 PEP 8 规范
- 在实际可行的情况下使用类型提示 (Type hints)
- 使用 Pydantic v2 进行数据校验
- 服务层 (Services) 遵循单一职责原则
- API 路由放在 `api/` 目录，业务逻辑放在 `services/` 目录

### TypeScript (前端)
- ESLint 配置在 `eslint.config.js`
- 强制执行 React Hooks 规则
- 使用 React Refresh 进行热重载
- 推荐使用 TypeScript 严格模式
- 组件使用 `.tsx` 扩展名

### 文档更新规则
- 当 `schemas.py` 或 `frontend/src/types/app.ts` 发生变更时，请更新相应的技术文档。
- 当添加 `scene_events`、工具 schemas、API 路由或 Save bundle 分片时，请更新：
  - `docs/technical/gameplay-core-technical.md`
  - `docs/technical/ai-tool-protocol.md`
  - `docs/technical/save-technical.md`
- 功能完成后，编写能力快照 (capability snapshot) 文档。

## 关键架构模式

### 模态框优先级系统
所有模态框都会阻塞聊天界面。优先级顺序：
1. 命运/任务模态框 (最高)
2. 遭遇模态框
3. 主聊天 (最低)

### 任务类型
- **命运任务 (Fate Quests)**: `accept_only` - 玩家无法拒绝
- **普通任务 (Normal Quests)**: 可 `accept/reject` (接受/拒绝)，并在聊天中输出叙事

### 存档系统
- 使用包含 JSON 分片的 bundle 格式
- 关键分片: `world_state.json`, `player_data.json`, `quest_state.json`, `encounter_state.json`, `fate_state.json`, `game_logs.json`
- 支持旧存档格式的自动迁移

### AI 工具协议
- 主聊天使用 `route_main_turn_intent()` 来拦截确定性的游戏行为
- 可用的 AI 工具包括：任务、命运、区域声望、角色渴望/故事、公开场景读取
- 提示词注册在 `data/ai-prompts.csv`

## 安全注意事项

- `config.json` 包含明文 API 密钥 - **仅限本地使用**
- 会话 Cookie 使用 `itsdangerous` 签名
- CORS 限制为本地开发源
- 敏感数据 (Authorization 请求头、用户隐私) 应在日志中脱敏
- 认证密钥存储在 `data/auth/secret.txt` 中 (如果未提供则自动生成)

## 需求文档

核心需求文档：`docs/requirements/pending-2026-03-01.md` 记录了命运/任务/遭遇的实现范围。

截至 2026-03-15 的当前功能状态：
- ✅ 支持多提供商的 AI 配置
- ✅ 带有 SSE 流式传输的主叙事聊天
- ✅ 世界地图、区域、子区域
- ✅ 命运线生成与推进
- ✅ 任务系统 (接受/拒绝/追踪)
- ✅ 带有情境值的遭遇系统
- ✅ 角色/队伍管理
- ✅ 战斗系统
- ✅ 带有综合工具的 Debug 面板
- ✅ Token 使用统计追踪

## 环境变量

### 后端
- `GRW_AUTH_SECRET` - 会话签名密钥 (可选，如果未设置则自动生成)

### 前端 (Docker)
- `VITE_BACKEND_URL` - 代理后端 URL (默认: `http://127.0.0.1:8000`)
- `VITE_HOST` - 开发服务器 Host (默认: `127.0.0.1`)
- `VITE_PORT` - 开发服务器端口 (默认: `5173`)
- `CHOKIDAR_USEPOLLING` - 启用轮询进行文件监听 (Windows Docker)

## 常见问题

1. **端口冲突**: 在启动命令或 Docker compose 中更改端口
2. **找不到 Python**: 安装 Python 3.11-3.14 并添加到 PATH
3. **找不到 npm**: 安装 Node.js 20+ 并添加到 PATH
4. **CORS 错误**: 确保后端 CORS 允许前端源
5. **Docker 中 Windows 文件监听失败**: 设置 `CHOKIDAR_USEPOLLING=true`

## API 基础 URL

- 开发环境: `http://127.0.0.1:8000/api/v1`
- 健康检查: `GET /api/v1/health`
- WebSocket/SSE: 支持流式聊天

## 联系与参考

- 架构: `docs/technical/mvp-architecture.md`
- 技术索引: `docs/technical/technical.md`
- 游戏设计: `docs/design/gamedesign/gamedesign.md`
- 遭遇偏好存储在本地 CSV 中，用于全局提示词生成
