# 遭遇技术文档

更新时间：`2026-03-23`

## 当前模型

### 内部模型
- `EncounterEntry.goal: str`
- `EncounterEntry.secret: str`
- `EncounterEntry.scene_summary: str`
- `EncounterTemporaryNpc.knows_secret: bool = False`

兼容保留但停止新写入的字段：
- `latest_outcome_summary`
- `background_tick_count`
- `status = escaped`
- `player_presence = away`
- `EncounterStepEntry.kind = background_tick | escape_attempt`

### 玩家公开 DTO
- `PublicEncounterEntry`
- `PublicEncounterState`

公开 DTO 只暴露：
- `goal`
- `scene_summary`
- `situation_value`
- `situation_trend`
- 基础身份信息
- 终止条件

公开 DTO 不暴露：
- `secret`
- `knows_secret`
- `latest_outcome_summary`
- `background_tick_count`
- `player_presence`

## 运行时规则
- active encounter 的公开展示统一使用 `PublicEncounterEntry`。
- 旧档中 `escaped` 在公开视图里统一映射成 `active`。
- 旧档中 `away` 在运行时归一化为 `engaged`。

## scene_summary
- `scene_summary` 是唯一公开局势摘要。
- 每次公开回合结束后，后端通过 `encounter.public_turn.summary.user.v1` 生成新的 `scene_summary`。
- `encounter_situation_update.content` 直接等于这条摘要。
- 不再使用模板化 concretize 逻辑重写摘要。

## secret 可见范围
- 后端服务可见
- 主遭遇 NPC 恒定可见
- 临时 NPC 仅在 `knows_secret = true` 时可见
- 玩家、队友、前端公开 DTO 默认不可见

## 队友目标注入
- 队友公开反应 prompt 使用 `team.public.reaction.user.v3`
- prompt 会收到 `encounter_goal`
- 不会收到 `secret`

## 后台推进退役
- `advance_active_encounter_in_save()` 已退役为 no-op。
- 主聊天、流式聊天、队友聊天、物品互动、移动、NPC 聊天、行动检定都不再调用后台推进。
- 不再生成新的 `encounter_background` 或 `encounter_background_tick` 事件。

## 逃离/重返退役
- `/encounters/{id}/escape` 与 `/encounters/{id}/rejoin` 返回 `410 Gone`。
- 主聊天与流式聊天中的逃离/重返关键词拦截已移除。
- 旧字段与旧状态只为兼容读取保留。

## 前端展示
- 主聊天主列显示 `遭遇目标: {goal}`
- 侧栏与弹窗只显示 `goal + scene_summary`
- “最近进展”与“最近步骤”不再驱动玩家 UI

## 提示词
- `encounter.generate.user.v3`
- `encounter.step.user.v4`
- `encounter.public_turn.summary.user.v1`

## 回归关注点
- 新遭遇能生成 `goal`、`secret`、`scene_summary`
- 队友只能看到 `goal`
- scene event 正文直接显示 AI 生成的 `scene_summary`
