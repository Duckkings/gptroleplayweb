# 任务系统技术文档（Quest Technical）

## 设计来源
- `docs/design/gamedesign/questdesign.md`
- `docs/design/gamedesign/fatedesign.md`
- `docs/design/gamedesign/encounterdesign.md`
- `docs/design/gamedesign/playflowdesign.md`
- `docs/technical/gameplay-core-technical.md`
- `docs/technical/save-technical.md`

状态：设计草案（2026-03-01）。当前仓库尚未实现任务系统，本文件定义后续落地契约。

## 1. 目标与边界

### 1.1 当前阶段目标
- 提供可持久化的任务数据结构，支持普通任务与命运任务共用一套任务骨架。
- 新任务发放时弹出阻塞式任务弹窗。
- 普通任务支持 `accept/reject`；命运任务仅支持 `accept`。
- 任务可被玩家设置为“当前追踪任务”，并在角色卡区域查看任务列表与任务日志。
- 任务完成状态可由逻辑规则和 AI 判定混合驱动。

### 1.2 当前阶段不做
- 复杂奖励结算（经济系统、装备掉落分发表）。
- 多分支任务树编辑器。
- 多玩家共享任务。

## 2. 核心术语
- `Quest`：玩家需要达成的一组目标。
- `QuestObjective`：任务内部的单个目标。
- `QuestSource`：任务来源，取值 `normal` 或 `fate`。
- `QuestOffer`：尚未被玩家确认的任务发放状态。
- `TrackedQuest`：玩家当前在角色卡中确认/追踪的任务。

## 3. 数据结构

位置建议：
- `backend/app/models/schemas.py`
- `frontend/src/types/app.ts`

### 3.1 枚举
- `QuestSource`: `normal | fate`
- `QuestStatus`: `pending_offer | active | rejected | completed | failed | superseded`
- `QuestOfferMode`: `accept_reject | accept_only`
- `QuestObjectiveKind`: `reach_zone | talk_to_npc | obtain_item | resolve_encounter | complete_quest | manual_text`
- `QuestObjectiveStatus`: `pending | in_progress | completed`
- `QuestRewardKind`: `gold | item | relation | flag | none`

### 3.2 QuestObjective
```json
{
  "objective_id": "obj_001",
  "kind": "talk_to_npc",
  "title": "与前台接待员交谈",
  "description": "在冒险者工会大厅找到接待员并完成对话。",
  "target_ref": {
    "npc_role_id": "npc_guild_clerk"
  },
  "progress_current": 0,
  "progress_target": 1,
  "status": "pending",
  "completed_at": null
}
```

约束：
- `manual_text` 目标允许仅用 AI 判定。
- 结构化目标优先使用 `target_ref`，便于逻辑层硬校验。

### 3.3 QuestReward
```json
{
  "reward_id": "rew_001",
  "kind": "gold",
  "label": "工会酬金",
  "payload": {
    "amount": 50
  }
}
```

### 3.4 QuestLogEntry
```json
{
  "id": "qlog_001",
  "kind": "offer",
  "message": "你获得了新任务【工会的第一份委托】",
  "created_at": "2026-03-01T12:00:00Z"
}
```

`kind` 建议值：
- `offer`
- `accept`
- `reject`
- `progress`
- `complete`
- `fail`
- `system`

### 3.5 QuestEntry
```json
{
  "quest_id": "quest_001",
  "source": "normal",
  "offer_mode": "accept_reject",
  "title": "工会的第一份委托",
  "description": "前往仓库区确认今日补给清单。",
  "issuer_role_id": "npc_guild_clerk",
  "zone_id": "zone_town",
  "sub_zone_id": "sub_zone_guild_hall",
  "fate_id": null,
  "fate_phase_id": null,
  "status": "pending_offer",
  "is_tracked": false,
  "objectives": [],
  "rewards": [],
  "logs": [],
  "offered_at": "2026-03-01T12:00:00Z",
  "accepted_at": null,
  "rejected_at": null,
  "completed_at": null,
  "metadata": {
    "generated_by": "ai"
  }
}
```

规则：
- `source=fate` 时，`offer_mode` 固定为 `accept_only`。
- `fate_id/fate_phase_id` 仅命运任务使用。
- 任一时刻允许多个 `active` 任务，但 `is_tracked=true` 最多 1 个。

### 3.6 QuestState
```json
{
  "version": "0.1.0",
  "tracked_quest_id": "quest_001",
  "quests": [],
  "updated_at": "2026-03-01T12:00:00Z"
}
```

## 4. 存档与兼容策略

逻辑层：
- `SaveFile` 新增 `quest_state: QuestState = Field(default_factory=QuestState)`。

物理分片建议：
- `current-save.json.bundle/quest_state.json`

兼容规则：
- 旧存档读取时自动补齐空 `quest_state`。
- 任务日志独立保存在任务对象内部，不复用 `game_logs` 作为唯一事实源。
- 同步写入 `game_logs` 作为玩家可见审计轨迹。

## 5. 后端实现位置建议
- `backend/app/services/quest_service.py`
- `backend/app/api/routes.py`
- `backend/app/models/schemas.py`

不建议继续把整套任务逻辑塞入 `world_service.py`，否则现有服务边界会进一步恶化。

## 6. API 契约（建议）

基础前缀：`/api/v1`

### 6.1 查询
- `GET /quests?session_id=...`
- `GET /quests/current?session_id=...`

返回重点：
- 所有任务列表
- 当前追踪任务
- 当前待确认任务（`status=pending_offer`）

### 6.2 发布任务
- `POST /quests/publish`

请求体：
```json
{
  "session_id": "sess_xxx",
  "quest": {
    "source": "normal",
    "offer_mode": "accept_reject",
    "title": "工会的第一份委托",
    "description": "前往仓库区确认今日补给清单。"
  },
  "open_modal": true
}
```

响应：
```json
{
  "ok": true,
  "quest_id": "quest_001",
  "status": "pending_offer"
}
```

### 6.3 接受/拒绝任务
- `POST /quests/{quest_id}/accept`
- `POST /quests/{quest_id}/reject`

响应建议统一包含：
```json
{
  "ok": true,
  "quest_id": "quest_001",
  "status": "active",
  "chat_feedback": "你接下了这份委托。"
}
```

规则：
- 普通任务允许 `accept/reject`。
- 命运任务调用 `reject` 必须返回冲突错误。
- 非命运任务的接受或拒绝都要回写一条聊天反馈和一条 `game_log`。

### 6.4 设置当前追踪任务
- `POST /quests/{quest_id}/track`

用途：
- 对应设计文档中的“确认当前 quest”。
- 角色卡任务列表中只高亮一个当前追踪任务。

### 6.5 任务完成判定
- `POST /quests/{quest_id}/evaluate`

用途：
- 手动调试或业务链路内部调用。
- 根据任务目标、当前地图、背包、遭遇历史、日志和最近聊天上下文更新任务状态。

### 6.6 Debug
- `POST /quests/debug/generate`

用途：
- Debug 面板生成一个普通任务。

## 7. 判定策略

### 7.1 逻辑硬判定优先
适用目标：
- 到达指定大区块/子区块
- 与指定 NPC 建立关系或进入单聊
- 获得指定物品
- 完成指定遭遇
- 完成另一个任务

### 7.2 AI 软判定补充
适用目标：
- 文本型目标
- “调查清楚”“说服成功”“获得线索”这类开放叙事条件

AI 只负责：
- 读取结构化上下文
- 返回 `completed / not_completed / uncertain`

逻辑层负责：
- 最终状态写入
- 防止 AI 直接越权修改其他任务或玩家状态

## 8. Prompt CSV 与 AI 工具

继续复用现有 `data/ai-prompts.csv` 机制，新增键建议：
- `quest.generate.system`
- `quest.generate.user`
- `quest.evaluate.system`
- `quest.evaluate.user`
- `quest.default.global`
- `quest.accept.narrative.user`
- `quest.reject.narrative.user`

其中：
- `quest.default.global` 用于保存“剑与魔法世界默认任务风格”。
- 当前阶段不新增独立 CSV 解析器，直接挂到现有 `prompt_table`。

AI 工具建议：
- `generate_quest`
- `evaluate_quest_completion`
- `get_quest_board`

## 9. 前端联动

位置建议：
- `frontend/src/components/QuestModal.tsx`
- `frontend/src/components/QuestPanel.tsx`
- `frontend/src/App.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`

交互规则：
- 新任务到达时显示阻塞式任务弹窗。
- 普通任务弹窗按钮：`接受`、`拒绝`。
- 命运任务弹窗按钮：`接受`。
- 弹窗关闭前禁止发送主聊天消息。
- 角色卡区域展示：
  - 当前追踪任务
  - 所有进行中任务
  - 每个任务的任务日志

弹窗优先级规则：
- 先显示 `source=fate` 的待确认任务。
- 再显示普通待确认任务。
- 最后才允许显示遭遇弹窗。

## 10. 日志规则

新增 `game_logs.kind` 建议值：
- `quest_offer`
- `quest_accept`
- `quest_reject`
- `quest_complete`
- `quest_track`

要求：
- `message` 用于日志面板直读。
- 详细字段写入 `payload`，如 `quest_id/source/title`。

## 11. 错误码建议
- `QUEST_NOT_FOUND` -> HTTP 404
- `QUEST_INVALID_STATUS` -> HTTP 409
- `QUEST_REJECT_FORBIDDEN` -> HTTP 409
- `QUEST_TRACK_NOT_ALLOWED` -> HTTP 409
- `QUEST_EVALUATE_FAILED` -> HTTP 502

## 12. 最小回归测试建议
- 普通任务发放后进入 `pending_offer`。
- 普通任务可接受/拒绝，并写入聊天反馈与日志。
- 命运任务拒绝时返回 `409`。
- 任务追踪切换时仅保留一个 `is_tracked=true`。
- 旧存档可补齐 `quest_state`。
