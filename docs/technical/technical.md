# 技术文档（Roleplay Web）

## 设计来源
- docs/design/gamedesign/gamedesign.md
- docs/design/gamedesign/areadesign.md
- docs/design/gamedesign/roledesign.md

本文档描述当前代码实现（更新于 2026-02-26），并定义后续开发的文档维护方式。

## 1. 文档分层规范

以后统一采用三层文档，避免每次开发都通读全部代码：

- 设计文档（`docs/design/gamedesign/*.md`）
  - 讲玩法目标、体验规则、取舍。
  - 不写具体代码细节。
- 技术文档（本文件 + `docs/technical/area-technical.md`）
  - 讲数据结构、接口契约、算法、错误码。
- 模块文档（每个代码模块目录下 `README.md`）
  - 讲模块职责、导出接口、调用方法、依赖关系。

维护原则：功能改动必须同步更新对应层级文档。

## 2. 项目结构

```txt
gptroleplayweb/
  backend/
    app/
      api/
      core/
      models/
      services/
      main.py
    tests/
  frontend/
    src/
      components/
      services/
      types/
      App.tsx
  docs/
    design/
      gamedesign/
        gamedesign.md
        areadesign.md
    technical/
      technical.md
      area-technical.md
      role-technical.md
      save-technical.md
      gameplay-core-technical.md
```

## 3. 当前系统能力概览

### 3.1 聊天与工具调用
- `POST /api/v1/chat`
- `POST /api/v1/chat/stream`
- `POST /api/v1/npc/greet`
- `POST /api/v1/npc/chat`
- `POST /api/v1/npc/chat/stream`

特性：
- 仅发送最后一条玩家输入（不带完整聊天历史）。
- 后端统一代理工具调用并回注模型。
- `tool_events` 回传前端调试面板。
- NPC 单聊将结构化聊天记录写入角色卡（含世界日期/时间），并在生成时回带历史上下文。
- 玩家发言会按 token 粗估消耗时间，推进世界时钟并弹出时间提示。

### 3.2 世界地图与区块
- `POST /api/v1/world-map/regions/generate`
- `POST /api/v1/world-map/render`
- `POST /api/v1/world-map/move`
- `POST /api/v1/world/clock/init`
- `GET /api/v1/world/area/current`
- `POST /api/v1/world/area/move-sub-zone`
- `POST /api/v1/world/area/interactions/discover`
- `POST /api/v1/world/area/interactions/execute`

特性：
- 大区块范围圈、子区块点位都可渲染。
- 子区块跨区移动可计算耗时并推进时钟。
- 交互支持即时发现与占位执行。

### 3.3 存档与日志
- 逻辑上仍使用 `SaveFile`，物理存储改为分片 bundle（`current-save.json` 指针 + `*.bundle` 分片文件，按块增量写入）。
- 游戏日志记录玩家输入、GM 回复、移动、区块刷新、占位交互。
- Token 使用量按 `chat/map_generation/movement_narration` 聚合统计。

## 4. AI 生成与逻辑控制关系（实现策略）

当前采用“AI 生成内容，逻辑锁定规则”的混合模式：

- 逻辑层硬约束：
  - 坐标、半径、数量、非重叠、耗时、时钟推进。
  - schema 校验、去重、fallback。
- AI 层软约束：
  - 名称、描述、叙事、发现候选。

这样可以避免：
- 纯逻辑导致内容僵化。
- 纯 prompt 导致状态不可控。

## 5. 模块文档索引

### 后端
- `backend/app/api/README.md`
- `backend/app/core/README.md`
- `backend/app/models/README.md`
- `backend/app/services/README.md`

### 前端
- `frontend/src/components/README.md`
- `frontend/src/services/README.md`
- `frontend/src/types/README.md`

## 6. 开发时快速理解流程（建议固定执行）

每次做新功能，先按顺序读：

1. 对应设计文档（例如 `docs/design/gamedesign/areadesign.md`）。
2. 对应技术文档（例如 `docs/technical/area-technical.md`、`docs/technical/role-technical.md`、`docs/technical/save-technical.md`、`docs/technical/gameplay-core-technical.md`）。
3. 模块 README（例如 `backend/app/services/README.md`）。
4. 只读与本功能直接相关的代码文件。

目标：把“全仓库重读”降到“按模块定点阅读”。

## 7. 文档更新约定（提交前检查）

涉及以下变更时必须同步文档：
- 新增/修改 API 请求或响应字段。
- 规则变化（耗时、坐标、状态推进、生成策略）。
- 存档结构变化。
- 前端交互流程变化（面板、弹窗、按钮行为）。

建议在 PR 描述固定附：
- 变更的设计文档路径。
- 变更的技术文档路径。
- 变更的模块 README 路径。

## 8. 运行与验证

后端：
```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：
```powershell
cd frontend
npm install
npm run dev
```

区块最小回归：
```powershell
cd backend
python -m unittest tests.test_area_logic
```










