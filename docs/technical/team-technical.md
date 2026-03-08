# 队伍系统技术文档（Team Technical）
## 设计来源
- `docs/design/gamedesign/teamdesign.md`
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/debugdesign.md`

状态：MVP 已落地，更新于 `2026-03-08`。

## 1. 目标与边界
### 1.1 目标
- 允许玩家将当前合法 NPC 招募进队伍。
- 队友入队后跟随玩家，并在关键行为后给出反馈。
- 提供独立队伍面板，支持：
  - 查看成员信息
  - 发起队伍聊天
  - 查看队友背包详情
  - 进入队友单聊
  - 手动离队
- 提供调试入口：根据短 prompt 生成调试队友。

### 1.2 当前不做
- 战斗编队、站位和共享战术。
- 队友与队友之间的长期群聊编排。
- 共享背包或队友背包编辑。
- 完整好感度策划表和独立数值 UI。

## 2. 数据结构
位置：`backend/app/models/schemas.py`

### 2.1 `TeamMember`
- `role_id`
- `name`
- `origin_zone_id / origin_sub_zone_id`
- `joined_at`
- `affinity / trust`
- `join_source: story | debug`
- `join_reason`
- `is_debug`
- `debug_prompt`
- `status`
- `last_reaction_at`
- `last_reaction_preview`

### 2.2 `TeamReaction`
- `reaction_id`
- `member_role_id`
- `member_name`
- `trigger_kind`
  - `main_chat`
  - `npc_chat`
  - `zone_move`
  - `sub_zone_move`
  - `action_check`
  - `team_chat`
  - `system`
- `content`
- `affinity_delta`
- `trust_delta`
- `created_at`

### 2.3 `TeamState`
- `version`
- `members: list[TeamMember]`
- `reactions: list[TeamReaction]`
- `updated_at`

### 2.4 队伍聊天契约
- `TeamChatRequest`
  - `session_id`
  - `player_message`
  - `config`
- `TeamChatReply`
  - `member_role_id`
  - `member_name`
  - `content`
  - `response_mode: speech | action`
  - `affinity_delta`
  - `trust_delta`
- `TeamChatResponse`
  - `session_id`
  - `player_message`
  - `replies`
  - `team_state`
  - `time_spent_min`

### 2.5 存档
- `SaveFile` 新增并持久化 `team_state`
- bundle 分片：`current-save.json.bundle/team_state.json`

## 3. 运行时规则
### 3.1 入队
- 接口：`invite_npc_to_team`
- 普通 NPC 入队流程：
  1. 读取 NPC 当前关系标签、个性、背景、认知、阵营。
  2. 若配置了模型，则优先让 AI 返回轻量 JSON 决策。
  3. 若 AI 不可用或失败，则回退到关系标签启发式判断。
  4. 接受后写入 `team_state.members`，并把 NPC 状态改为 `in_team`。
- 接受入队后：
  - 从当前区域的驻留 NPC 列表移除，避免和常驻 NPC 重复显示。
  - 若缺失玩家关系，会为该 NPC 自动补一条玩家关系。

### 3.2 跟随同步
- 队友不维护独立地图轨迹。
- 当前实现使用“与玩家同区/同子区”同步：
  - 大区块移动
  - 子区块移动
  - 读取队伍状态
- 同步目标是 `NpcRoleCard.zone_id / sub_zone_id / state`。

### 3.3 自动反馈
- 当前已接入的触发点：
  - 主聊天 `/chat`、`/chat/stream`
  - NPC 单聊 `npc_chat`
  - 大区块移动 `move_to_zone`
  - 子区块移动 `move_to_sub_zone`
  - 行为检定 `action_check`
- 反馈会写入两处：
  - `team_state.reactions`
  - `game_logs(kind=team_reaction)`
- 数值影响仍是轻量启发式：
  - 合作、感谢、照应类文本小幅增加好感/信任
  - 威胁、攻击、抢劫类文本降低好感/信任
  - 失败结果会触发担忧类反馈

### 3.4 队伍聊天
- 接口：`team_chat`
- 规则：
  1. 玩家发言先按统一语音耗时逻辑推进世界时间。
  2. 当前每个队友都会收到同一条玩家发言。
  3. 玩家发言和队友回应都会写入对应 `NpcRoleCard.dialogue_logs`。
  4. 若有 AI 配置，则逐成员使用 JSON 协议生成短回应：
     - `content`
     - `response_mode`
  5. 若 AI 不可用，则回退到启发式短回应。
  6. 每条队伍聊天会同步写入：
     - `team_state.reactions(trigger_kind=team_chat)`
     - `game_logs(kind=team_chat)`
- `response_mode` 说明：
  - `speech`：直接说话
  - `action`：只做动作反应，不强制输出对白

### 3.5 自动离队
- 当某位队友 `affinity <= 0` 时自动离队。
- 普通队友回到招募前位置。
- 调试队友从 `role_pool` 中直接销毁。

### 3.6 调试队友
- 接口：`generate_debug_teammate`
- 输入一段短 prompt，系统会：
  - 生成一个新的 `NpcRoleCard`
  - 直接以 `debug` 来源加入队伍
  - 赋予较高的初始 `affinity / trust`
- 调试队友离队后不回地图。

### 3.7 队友背包查看
- 前端队伍面板支持查看当前队友背包详情。
- 展示来源仍是角色卡里的 `profile.dnd5e_sheet.backpack + equipment_slots`。
- 当前阶段只读，不支持直接修改队友物品。

## 4. API 契约
基础前缀：`/api/v1`

### 4.1 读取队伍
- `GET /team?session_id=...`

### 4.2 邀请 NPC 入队
- `POST /team/invite`

### 4.3 让队友离队
- `POST /team/leave`

### 4.4 生成调试队友
- `POST /team/debug/generate`

### 4.5 队伍聊天
- `POST /team/chat`
- 请求重点：
  - `session_id`
  - `player_message`
  - `config`
- 返回重点：
  - `replies`
  - `team_state`
  - `time_spent_min`

## 5. AI 工具
当前已向主聊天工具层开放：
- `get_team_state`
- `team_invite_npc`
- `team_remove_npc`
- `get_role_inventory`
- `team_chat`
- `team_generate_debug_member`

规则：
- 招募、离队、队伍聊天都必须经过结构化工具，不允许只靠自由文本假装成功。
- 查看队友背包必须使用 `get_role_inventory` 或前端角色卡缓存，不允许模型自行编造。

## 6. 前端联动
位置：
- `frontend/src/App.tsx`
- `frontend/src/components/TeamPanel.tsx`
- `frontend/src/components/RoleInventoryModal.tsx`
- `frontend/src/components/NpcPoolPanel.tsx`
- `frontend/src/components/DebugPanel.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`

当前行为：
- Debug 面板新增：
  - `当前队伍`
  - `生成调试队友`
- `NpcPoolPanel` 支持：
  - 邀请入队
  - 移出队伍
- `TeamPanel` 支持：
  - 查看当前成员
  - 发送队伍聊天
  - 查看最近队伍聊天回应
  - 查看最近队伍反应
  - 查看队友背包详情
  - 进入队友单聊

## 7. 日志与持久化
- `team_state.reactions` 仅保留最近 100 条。
- `NpcRoleCard.dialogue_logs` 按角色卡保留最近聊天历史。
- 当前队伍相关日志类型：
  - `team_join`
  - `team_leave`
  - `team_reaction`
  - `team_chat`
  - `team_debug_generate`

## 8. 回归覆盖
测试文件：`backend/tests/test_team_service.py`

当前覆盖：
- bundle 中存在 `team_state` 分片
- NPC 入队后状态正确
- 调试队友离队后销毁
- 负向反应会触发自动离队
- 队伍聊天会写入回应和 `team_chat` 反应

## 9. 当前限制
- 队伍聊天仍是“逐成员独立短回应”，不是复杂群聊导演系统。
- 队友背包当前只读展示，没有操作面板。
- 队友单聊仍复用普通 NPC 单聊接口，没有单独的“队友健谈值”模型。
## 2026-03-08 Addendum
### 队友单聊与遭遇打断
- 当前前端状态机新增 `forceReturnToMainChat(...)`
- 当队友/NPC 单聊期间触发遭遇时：
  - 立即退出单聊
  - 遭遇公告只写入主聊天
  - 遭遇结算后保持在主聊天，不自动恢复之前的队友单聊
- `EncounterModal` 现在正式挂载，且遵守“任务/Fate 高于遭遇”的模态优先级。

### 队伍面板新入口
- `TeamPanel` 现在每个队友都有四个入口：
  - `单聊`
  - `属性`
  - `背包`
  - `离队`
- `属性` 会强制刷新最新角色卡后再打开 `RoleProfileModal`
- `背包` 会强制刷新最新角色卡后再打开 `RoleInventoryModal`

### 队友背包交互
- 队友背包不再是只读展示
- 队友和玩家共用同一套 inventory API：
  - 装备武器/护甲
  - 卸下武器/护甲
  - 观察任意背包物品
  - 使用 `misc` 物品
- 队友物品使用时，`actor_role_id` 使用队友自己的 `role_id`

### 调试队友生成升级
- `generate_debug_teammate` 现在不再只弱依赖 prompt 命名
- 改为走 `generate_team_role_from_prompt(...)`
- 新生成队友必须返回完整角色卡：
  - secret
  - likes
  - race / class / background / alignment
  - languages / skills / tools / features / spells
  - backpack.items
  - equipment_slots
