# AI 工具协议

更新日期：`2026-03-09`

## 1. 目标
- 让模型先读取真实状态，再生成文本。
- 让所有关键玩法写操作都经过后端校验、落库和审计。
- 让主聊天中的玩法行为优先由后端路由，而不是依赖模型“记得去调工具”。

## 2. 当前总流程
1. 前端调用 `/api/v1/chat` 或 `/api/v1/chat/stream`
2. 后端先运行 `route_main_turn_intent(...)`
3. 若未命中确定性动作，再向模型暴露工具 schema
4. 模型通过 `tool_call` 读取或写入状态
5. 后端执行工具，记录 `tool_events`
6. 模型返回最终 GM 文本
7. 主聊天链路继续推进公开场景和遭遇

## 3. 当前读取工具
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
- `get_quest_state`
- `get_fate_state`
- `get_area_reputation`
- `get_role_drives`
- `get_public_scene_state`

## 4. 当前写入工具
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
- `inventory_mutate`
- `inventory_interact`
- `encounter_act`
- `encounter_escape`
- `encounter_rejoin`
- `quest_track`
- `quest_evaluate`

## 5. 新增读取工具约定

### 5.1 `get_area_reputation`
用途：
- 读取当前或指定 `sub_zone_id` 的声望

关键字段：
- `current_entry`
- `entries`
- `score`
- `band`
- `recent_reasons`

### 5.2 `get_role_drives`
用途：
- 读取指定角色、队伍范围或当前子区块范围内的 desire/story 摘要

关键字段：
- `scope`
- `items[*].role_id`
- `items[*].desires`
- `items[*].story_beats`

### 5.3 `get_public_scene_state`
用途：
- 读取当前公开场景事实，避免模型误判当前场上角色、声望或遭遇

关键字段：
- `sub_zone_id`
- `reputation`
- `visible_roles`
- `surfaced_desires`
- `surfaced_story_beats`
- `candidate_actors`
- `active_encounter_id`

## 6. 主聊天中的调用策略

### 6.1 先路由后工具
以下动作不应再依赖模型自由判断：
- 明确移动
- 明确物品装备/观察/使用
- 明确邀请/移除队友
- 明确遭遇逃离/重返/行动
- 明确点名当前可见 NPC
- `passive_turn`

### 6.2 仍适合工具或模型的情况
- 模糊叙事
- 无合法实体匹配的表达
- 纯情绪/气氛/闲聊
- 需要先查状态再决定是否行动的复杂叙事

## 7. 审计规则
- 所有工具执行都必须进入 `tool_events`
- 所有关键玩法变化仍必须进入 `game_logs`
- 公开场景和遭遇进展不依赖 `tool_events` 向前端展示，而是通过 `scene_events`

## 8. Prompt Keys
当前新增并强制注册的 key：
- `scene.actor.intent.user.v1`
- `role.desire.seed.user.v1`
- `role.desire.surface.user.v1`
- `companion.story.seed.user.v1`
- `companion.story.surface.user.v1`
- `encounter.outcome.package.user.v1`
- `reputation.behavior.user.v1`

## 9. 当前限制
- 模型不能直接写 desire/story 的持久化状态
- 模型不能直接宣告检定结果
- 模型不能直接宣告遭遇奖励落地
- 主聊天不会直接接受 quest accept/reject 作为自由文本写入动作

## 10. 回归测试
- `backend/tests/test_chat_route_scene_rendering.py`
- `backend/tests/test_action_check_routes.py`
- `backend/tests/test_npc_chat_routes.py`
- `backend/tests/test_prompt_registry.py`

