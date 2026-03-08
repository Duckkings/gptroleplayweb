# 遭遇系统技术文档（Encounter Technical）

## 设计来源
- `docs/design/gamedesign/encounterdesign.md`
- `docs/design/gamedesign/playflowdesign.md`
- `docs/design/gamedesign/questdesign.md`
- `docs/design/gamedesign/fatedesign.md`
- `docs/technical/area-technical.md`
- `docs/technical/save-technical.md`

状态：设计草案（2026-03-01）。当前仓库尚未实现遭遇系统，本文件定义后续落地契约。

## 1. 目标与边界

### 1.1 当前阶段目标
- 让遭遇成为“地图位置 + 当前任务 + 玩家偏好”的即时事件层。
- 支持 `NPC遭遇`、`事件遭遇`、`异常表现遭遇` 三类。
- 支持移动后或对话后进行遭遇检测。
- 遭遇触发后使用阻塞式弹窗展示描述，并允许玩家输入动作 prompt。
- 遭遇全文必须可在日志面板回看。

### 1.2 当前阶段不做
- 完整战斗系统。
- 遭遇概率权重编辑 UI。
- 复杂场景持续状态机。

## 2. 核心术语
- `Encounter`：一次短时、上下文驱动的事件实例。
- `EncounterTrigger`：遭遇出现的原因。
- `EncounterResolution`：玩家输入动作后得到的结算结果。
- `EncounterHistory`：已发生遭遇的审计记录，用于日志与任务/命运引用。

## 3. 数据结构

位置建议：
- `backend/app/models/schemas.py`
- `frontend/src/types/app.ts`

### 3.1 枚举
- `EncounterType`: `npc | event | anomaly`
- `EncounterStatus`: `queued | presented | resolved | skipped | expired`
- `EncounterTriggerKind`: `random_move | random_dialog | scripted | quest_rule | fate_rule | debug_forced`

### 3.2 EncounterEntry
```json
{
  "encounter_id": "enc_001",
  "type": "event",
  "status": "queued",
  "trigger_kind": "random_move",
  "title": "路边被翻开的货箱",
  "description": "你在巷口看见一只被强行撬开的货箱，木板边缘还留着新鲜裂痕。",
  "zone_id": "zone_town",
  "sub_zone_id": "sub_zone_market",
  "related_quest_ids": ["quest_001"],
  "related_fate_phase_ids": [],
  "generated_prompt_tags": ["investigation", "urban", "loot"],
  "allow_player_prompt": true,
  "created_at": "2026-03-01T12:00:00Z",
  "presented_at": null,
  "resolved_at": null
}
```

### 3.3 EncounterResolution
```json
{
  "encounter_id": "enc_001",
  "player_prompt": "我检查箱盖上的撬痕，看看是不是同一种工具留下的。",
  "reply": "你俯身查看后确认撬痕来自窄刃工具，力道均匀，像是熟手作案。",
  "time_spent_min": 3,
  "quest_updates": ["quest_001:progress"],
  "created_at": "2026-03-01T12:05:00Z"
}
```

### 3.4 EncounterState
```json
{
  "version": "0.1.0",
  "pending_ids": ["enc_001"],
  "active_encounter_id": null,
  "encounters": [],
  "history": [],
  "debug_force_trigger": false,
  "updated_at": "2026-03-01T12:00:00Z"
}
```

规则：
- `pending_ids` 维持等待展示的遭遇顺序。
- `active_encounter_id` 仅在弹窗实际展示期间占用。
- `debug_force_trigger=true` 表示“100% 遭遇一个事件”调试开关开启。

## 4. 存档与兼容策略

逻辑层：
- `SaveFile` 新增 `encounter_state: EncounterState = Field(default_factory=EncounterState)`。

物理分片建议：
- `current-save.json.bundle/encounter_state.json`

兼容规则：
- 旧存档自动补齐空 `encounter_state`。
- 已解析完成的遭遇需保留在 `history`，以供任务、命运和日志回查。

## 5. 生成上下文与检测流程

### 5.1 输入上下文
- 当前 `area_snapshot.current_zone_id/current_sub_zone_id`
- 当前进行中任务
- 当前命运阶段摘要
- 最近游戏日志
- 角色池/NPC 信息
- 全局遭遇偏好 CSV

### 5.2 检测时机
- 玩家完成大区块移动后
- 玩家完成子区块移动后
- 玩家在主聊天或 NPC 单聊完成一轮后
- Debug 强制触发

### 5.3 检测顺序
1. 读取当前活动任务与命运阶段。
2. 判断是否存在脚本型或任务型必触发遭遇。
3. 若无，则按随机规则检测移动后/对话后遭遇。
4. 生成遭遇后先写入 `encounter_state.pending_ids`。
5. 若当前存在命运任务或普通任务待确认弹窗，则遭遇继续排队，不抢占显示。

## 6. API 契约（建议）

基础前缀：`/api/v1`

### 6.1 检测遭遇
- `POST /encounters/check`

请求体：
```json
{
  "session_id": "sess_xxx",
  "trigger_kind": "random_move",
  "config": {}
}
```

响应：
```json
{
  "ok": true,
  "generated": true,
  "encounter_id": "enc_001",
  "blocked_by_higher_priority_modal": true
}
```

### 6.2 查询待展示遭遇
- `GET /encounters/pending?session_id=...`

返回：
- 待展示遭遇列表
- 当前活动遭遇

### 6.3 提交遭遇动作
- `POST /encounters/{encounter_id}/act`

请求体：
```json
{
  "session_id": "sess_xxx",
  "player_prompt": "我先和可疑商贩搭话。"
}
```

响应：
```json
{
  "ok": true,
  "encounter_id": "enc_001",
  "status": "resolved",
  "reply": "商贩先是一愣，随后压低声音回了你一句。",
  "time_spent_min": 4
}
```

### 6.4 历史查询
- `GET /encounters/history?session_id=...`

### 6.5 Debug
- `POST /encounters/debug/force-toggle`

用途：
- 对应设计文档中的“增加一个 debug 勾选 100% 遭遇一个事件”。

## 7. Prompt CSV 与 AI 工具

当前阶段继续复用 `data/ai-prompts.csv`，建议新增键：
- `encounter.generate.system`
- `encounter.generate.user`
- `encounter.resolve.system`
- `encounter.resolve.user`
- `encounter.global.preference`

说明：
- `encounter.global.preference` 存放玩家偏好的全局遭遇体验描述。
- 该偏好是本地 CSV 配置，不写入存档，适合作为跨会话的全局 prompt 基线。

AI 工具建议：
- `generate_encounter`
- `resolve_encounter`
- `get_pending_encounters`

## 8. 逻辑与 AI 分工

逻辑层负责：
- 触发时机
- 队列顺序
- 状态推进
- 时间消耗写回
- 与任务/命运的引用关系

AI 负责：
- 遭遇文案
- 遭遇动作的自然语言结算
- 遭遇与当前区域、任务目标之间的语义耦合

AI 失败时 fallback：
- 使用预设模板生成遭遇：
  - 抢劫
  - 遭遇 NPC
  - 发现宝箱
  - 发现异常痕迹

## 9. 前端联动

位置建议：
- `frontend/src/components/EncounterModal.tsx`
- `frontend/src/App.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`

交互规则：
- 遭遇弹窗必须阻塞聊天输入。
- 弹窗展示：
  - 遭遇标题
  - 遭遇描述
  - 玩家动作输入框
- 若同时存在任务弹窗，则任务弹窗优先，遭遇弹窗在其关闭后显示。
- 玩家提交动作后：
  - 将结果写入主聊天区
  - 写入 `game_logs`
  - 刷新任务/命运状态

## 10. 日志规则

新增 `game_logs.kind` 建议值：
- `encounter_generated`
- `encounter_presented`
- `encounter_resolved`
- `encounter_skipped`

要求：
- `message` 显示摘要。
- `payload` 至少保留 `encounter_id/type/title/description`。
- 日志面板中必须可回看完整遭遇内容。

## 11. 错误码建议
- `ENCOUNTER_NOT_FOUND` -> HTTP 404
- `ENCOUNTER_INVALID_STATUS` -> HTTP 409
- `ENCOUNTER_BLOCKED_BY_MODAL` -> HTTP 409
- `ENCOUNTER_GENERATE_FAILED` -> HTTP 502
- `ENCOUNTER_RESOLVE_FAILED` -> HTTP 502

## 12. 最小回归测试建议
- 强制触发开关开启后，检测接口必定生成遭遇。
- 有待确认命运/普通任务时，遭遇进入排队而不是立即抢占弹窗。
- 提交遭遇动作后，状态从 `queued/presented` 正确推进到 `resolved`。
- 遭遇描述与结算结果同时写入日志历史。
- 旧存档可补齐 `encounter_state`。
