# AI 工具协议（Tool Protocol）
## 设计来源
- `docs/design/gamedesign/gamedesign.md`
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/teamdesign.md`

更新于 `2026-03-08`。

## 1. 目标
- 让模型通过结构化工具读取当前游戏事实，而不是依赖自由记忆。
- 让所有写操作都经过后端校验、日志和存档。
- 让一致性、角色、队伍、任务、遭遇等系统共享同一层工具协议。

## 2. 总体流程
1. 前端调用 `/api/v1/chat` 或 `/api/v1/chat/stream`
2. 后端把工具 schema 附给模型
3. 模型返回 `tool_call`
4. 后端执行：
   - 参数解析
   - schema 校验
   - 业务逻辑
   - 结果序列化
5. 后端将 `tool` 消息回注给模型
6. 模型输出最终自然语言结果
7. 工具执行摘要进入 `tool_events`

## 3. 工具分层
### 3.1 只读工具
- `get_player_state`
- `get_story_snapshot`
- `get_entity_index`
- `get_consistency_status`
- `get_npc_knowledge`
- `get_team_state`
- `get_role_inventory`
- `get_map_index`
- `get_game_logs`
- `get_current_sub_zone`

### 3.2 写入工具
- `generate_zone`
- `move_to_zone`
- `move_to_sub_zone`
- `discover_interactions`
- `execute_interaction`
- `run_consistency_check`
- `team_invite_npc`
- `team_remove_npc`
- `team_chat`
- `team_generate_debug_member`
- `player_add_item`
- `player_equip_item`
- `player_apply_buff`
- `player_adjust_resource`
- `role_set_relation`
- `player_set_trait`

## 4. 当前关键工具说明
### 4.1 `get_player_state`
返回当前完整运行时状态：
- `world_state`
- `player_static_data`
- `player_runtime_data`
- `map_snapshot`
- `area_snapshot`
- `team_state`
- `quest_state`
- `encounter_state`
- `fate_state`
- `role_pool`

### 4.2 `get_story_snapshot`
返回统一故事快照：
- `world_revision / map_revision`
- 当前区块与子区块
- 当前可见 NPC
- 当前队伍成员 ID
- 活动任务
- 当前命运线 / 阶段
- 最近遭遇

### 4.3 `get_entity_index`
返回当前合法实体 ID 集合：
- `zone_ids`
- `sub_zone_ids`
- `npc_ids`
- `quest_ids`
- `encounter_ids`
- `fate_phase_ids`

### 4.4 `get_npc_knowledge`
返回 NPC 的知识边界：
- `known_local_npc_ids`
- `known_local_zone_ids`
- `known_active_quest_refs`
- `forbidden_entity_ids`
- `response_rules`

### 4.5 `get_team_state`
返回当前队伍状态：
- `team_state.members`
- `team_state.reactions`
- 当前成员好感 / 信任
- 最近队伍反馈

### 4.6 `get_role_inventory`
返回目标 NPC 的背包与装备槽：
- `backpack`
- `equipment_slots`

### 4.7 `team_invite_npc`
用途：
- 招募一个合法 NPC 入队

输入：
```json
{
  "npc_role_id": "npc_xxx",
  "player_prompt": "一起行动，彼此照应。"
}
```

输出重点：
- `accepted`
- `chat_feedback`
- `member`
- `team_state`

### 4.8 `team_remove_npc`
用途：
- 让一个当前队友离队

输入：
```json
{
  "npc_role_id": "npc_xxx",
  "reason": "manual"
}
```

### 4.9 `team_chat`
用途：
- 发送一条玩家消息到当前队伍聊天，并返回每个队友的回应

输入：
```json
{
  "player_message": "我们先稳住，不要惊动前面的人。"
}
```

输出重点：
- `replies`
- `team_state`
- `time_spent_min`

说明：
- `replies[*].response_mode` 为 `speech` 或 `action`
- 队伍聊天会推进世界时间，并把对话写入各队友的 `dialogue_logs`

### 4.10 `team_generate_debug_member`
用途：
- 根据短 prompt 生成调试队友并直接加入当前队伍

## 5. 调用顺序约束
### 5.1 一致性相关
当问题涉及以下内容时，应优先先读状态再行动：
- 当前世界事实
- NPC 是否存在
- 当前任务 / 命运阶段
- 当前合法实体引用

推荐顺序：
1. `get_story_snapshot`
2. 必要时 `get_entity_index`
3. 若涉及 NPC 知识边界，再调 `get_npc_knowledge`

### 5.2 队伍相关
- 模型想招募 NPC：
  1. 先确认 NPC 合法存在
  2. 必要时读 `get_team_state`
  3. 再调 `team_invite_npc`

- 模型想查看队友物品：
  1. 先确认目标角色
  2. 再调 `get_role_inventory`

- 模型想让队友整体回应：
  1. 必要时读 `get_team_state`
  2. 再调 `team_chat`

### 5.3 一致性修复
- 当模型怀疑世界状态过期或脏引用存在时：
  1. `get_consistency_status`
  2. 必要时 `run_consistency_check`
  3. 重新读取 `get_story_snapshot`

## 6. 响应与审计规则
- 工具执行失败时必须返回 `ok=false`
- 失败响应必须包含最小可诊断错误摘要
- 所有写操作默认绑定当前 `session_id`
- 后端会把工具执行摘要记录到 `tool_events`
- 关键业务事件仍需写入 `game_logs`

## 7. 与一致性系统的关系
- 任务 / 遭遇生成已经依赖：
  - `GlobalStorySnapshot`
  - `EntityIndex`
  - 输出后二次校验
- 队伍工具则在此基础上补齐了：
  - 结构化队伍状态读取
  - 结构化入队 / 离队
  - 结构化队伍聊天
  - 结构化背包读取

## 8. 前端联动
- 调试面板展示 `tool_events`
- 若工具写入了地图、队伍、一致性状态，前端必须刷新对应状态片段
- 当前已接入的典型联动：
  - 一致性状态面板
  - 当前队伍面板
  - 队伍聊天面板
  - 队友背包详情模态

## 9. 后续建议
- 将 fate 生成也彻底统一到 `allowed entity ids + structured refs`
- 给工具错误补统一 `error_code`
- 若后续做复杂队友协作，再单独拆出“战术工具协议”
## 2026-03-08 Addendum
### 新增或补强的工具能力
- `team_generate_debug_member`
  - 现在底层走 `generate_team_role_from_prompt(...)`
  - prompt 不再只影响命名，而是影响完整角色概念、职业方向、语言、喜好、装备偏好和背包内容
- `inventory_mutate`
  - 统一处理玩家/队友的装备与卸下
- `inventory_interact`
  - 统一处理玩家/队友的物品观察与使用

### 队友生成工具约束
- `team_generate_debug_member` 只接受短 prompt
- 生成时使用固定结构化字段：
  - `display_name`
  - `race`
  - `char_class`
  - `sheet_background`
  - `alignment`
  - `personality`
  - `speaking_style`
  - `appearance`
  - `background`
  - `cognition`
  - `secret`
  - `likes`
  - `languages`
  - `tool_proficiencies`
  - `skills_proficient`
  - `features_traits`
  - `spells`
  - `preferred_weapon`
  - `preferred_armor`
  - `inventory_items`
  - `notes`
  - `ability_bias`
- 后端会对这些字段做清洗，模型不能绕过后端直接写非法装备或非法数值。

### Inventory 工具调用规则
- `inventory_mutate`
  - 入参：
    - `owner_type`
    - `role_id`（仅 owner_type=role 时必填）
    - `mode`
    - `item_id`
    - `slot`
- `inventory_interact`
  - 入参：
    - `owner_type`
    - `role_id`（仅 owner_type=role 时必填）
    - `item_id`
    - `mode=inspect|use`
    - `prompt`
- `use` 仅允许对 `misc` 物品调用
- 队友物品使用时，行为执行者是队友自身，不是玩家
