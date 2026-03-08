# 命运线技术文档（Fate Technical）

## 设计来源
- `docs/design/gamedesign/fatedesign.md`
- `docs/design/gamedesign/questdesign.md`
- `docs/design/gamedesign/encounterdesign.md`
- `docs/design/gamedesign/playflowdesign.md`
- `docs/technical/save-technical.md`

状态：设计草案（2026-03-01）。当前仓库尚未实现命运线系统，本文件定义后续落地契约。

## 1. 目标与边界

### 1.1 当前阶段目标
- 为每个存档提供一条可持久化的长期命运线。
- 命运线由多个阶段组成，每个阶段拥有触发条件与对应命运任务。
- 命运阶段数据先完整建模，但初期生成与查看由 Debug 面板手动触发。
- 命运事件本质上是任务，复用任务系统数据结构与接收流程。

### 1.2 当前阶段不做
- 新游戏自动生成命运线。
- 多条命运线并行。
- 分支式命运树编辑器。

## 2. 核心术语
- `FateLine`：一条长线主目标。
- `FatePhase`：命运线中的单个阶段。
- `FateTriggerCondition`：阶段触发条件。
- `FateQuest`：由命运阶段派生出的任务，`Quest.source=fate`。

## 3. 数据结构

位置建议：
- `backend/app/models/schemas.py`
- `frontend/src/types/app.ts`

### 3.1 枚举
- `FateLineStatus`: `not_generated | active | completed | superseded`
- `FatePhaseStatus`: `locked | ready | quest_offered | quest_active | completed`
- `FateTriggerKind`: `manual | days_elapsed | met_npc | obtained_item | resolved_encounter | completed_quest`

### 3.2 FateTriggerCondition
```json
{
  "condition_id": "fc_001",
  "kind": "met_npc",
  "description": "遇到冒险者工会前台接待员",
  "payload": {
    "npc_role_id": "npc_guild_clerk"
  },
  "satisfied": false,
  "satisfied_at": null
}
```

### 3.3 FatePhase
```json
{
  "phase_id": "phase_001",
  "index": 1,
  "title": "被召唤的起点",
  "description": "你第一次意识到自己卷入了某种更大的安排。",
  "status": "locked",
  "trigger_conditions": [],
  "triggered_at": null,
  "bound_quest_id": null,
  "completed_at": null
}
```

### 3.4 FateLine
```json
{
  "fate_id": "fate_001",
  "title": "群星尽头的回响",
  "summary": "一条围绕古老预言展开的长期主线。",
  "status": "active",
  "current_phase_id": "phase_001",
  "phases": [],
  "generated_at": "2026-03-01T12:00:00Z",
  "updated_at": "2026-03-01T12:00:00Z"
}
```

### 3.5 FateState
```json
{
  "version": "0.1.0",
  "current_fate": null,
  "archive": [],
  "updated_at": "2026-03-01T12:00:00Z"
}
```

规则：
- 一个存档同一时刻只允许一条 `current_fate`。
- 重新生成命运线时，旧命运线进入 `archive`，状态标记为 `superseded`。

## 4. 存档与兼容策略

逻辑层：
- `SaveFile` 新增 `fate_state: FateState = Field(default_factory=FateState)`。

物理分片建议：
- `current-save.json.bundle/fate_state.json`

兼容规则：
- 旧存档自动补齐空 `fate_state`。
- 命运线阶段推进不依赖前端缓存，必须以存档为事实源。

## 5. 阶段与任务关系

核心规则：
- 每个命运阶段必须绑定一个命运任务。
- 命运任务由任务系统统一承载，只是 `Quest.source=fate`。
- 命运任务一旦发放，只允许 `accept`，不允许 `reject`。
- 命运任务完成后，当前阶段才可推进为 `completed`。

推荐状态推进：
- `locked` -> `ready`
- `ready` -> `quest_offered`
- `quest_offered` -> `quest_active`
- `quest_active` -> `completed`

## 6. 触发策略

### 6.1 M1 实现范围
- 不做自动初次触发。
- 仅支持：
  - Debug 手动生成命运线
  - Debug 重新生成命运线
  - Debug 查看命运信息
  - 可选手动执行一次“检查当前阶段条件”

### 6.2 数据模型预留的自动触发能力
阶段条件允许依赖：
- 世界日期推进
- 遇到某 NPC
- 获得某物品
- 完成某遭遇
- 完成某任务

判定数据来源：
- `area_snapshot.clock`
- `role_pool / relations / dialogue_logs`
- `player_static_data.dnd5e_sheet.backpack`
- `quest_state`
- `encounter_state.history`
- `game_logs`

## 7. API 契约（建议）

基础前缀：`/api/v1`

### 7.1 查询
- `GET /fate/current?session_id=...`

返回：
- 当前命运线摘要
- 当前阶段
- 各阶段状态

### 7.2 Debug 生成
- `POST /fate/debug/generate`

请求体：
```json
{
  "session_id": "sess_xxx",
  "config": {}
}
```

响应：
```json
{
  "ok": true,
  "fate_id": "fate_001",
  "generated": true
}
```

### 7.3 Debug 重新生成
- `POST /fate/debug/regenerate`

规则：
- 旧命运线归档。
- 尚未完成的旧命运任务标记为 `superseded`，避免存档内出现悬空主线。

### 7.4 检查阶段条件
- `POST /fate/evaluate`

用途：
- 初期允许由 Debug 面板调用。
- 后续可接入移动、遭遇结算、任务完成链路自动触发。

## 8. Prompt CSV 与 AI 工具

继续复用 `data/ai-prompts.csv`，建议新增键：
- `fate.generate.system`
- `fate.generate.user`
- `fate.phase.check.system`
- `fate.phase.check.user`
- `fate.info.user`

AI 工具建议：
- `generate_fate_line`
- `get_fate_state`
- `check_fate_phase_trigger`

说明：
- `generate_fate_line` 只负责阶段摘要与触发条件草案。
- 阶段真正发放任务时，仍调用任务生成能力。

## 9. 前端联动

位置建议：
- `frontend/src/components/FatePanel.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/DebugPanel.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`

Debug 面板新增入口建议：
- `生成命运线`
- `重新生成命运线`
- `查看命运信息`
- `检查命运阶段`

交互规则：
- 命运任务弹窗属于最高优先级任务弹窗。
- 若存在待确认命运任务，则先显示命运任务，再显示普通任务，再显示遭遇。
- 查看命运信息可以是只读面板，不要求进入聊天。

## 10. 日志规则

新增 `game_logs.kind` 建议值：
- `fate_generated`
- `fate_regenerated`
- `fate_phase_ready`
- `fate_phase_completed`

要求：
- `message` 为玩家可读摘要。
- `payload` 至少保留 `fate_id/phase_id/quest_id`。

## 11. 错误码建议
- `FATE_NOT_FOUND` -> HTTP 404
- `FATE_ALREADY_EXISTS` -> HTTP 409
- `FATE_PHASE_NOT_FOUND` -> HTTP 404
- `FATE_REGENERATE_CONFLICT` -> HTTP 409
- `FATE_EVALUATE_FAILED` -> HTTP 502

## 12. 最小回归测试建议
- Debug 生成后，存档内出现完整 `fate_state.current_fate`。
- 重新生成后，旧命运线进入 `archive`。
- 命运任务必须以 `Quest.source=fate` 写入任务系统。
- 命运任务拒绝请求返回 `409`。
- 旧存档可补齐 `fate_state`。
