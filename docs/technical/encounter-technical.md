# 遭遇系统技术文档

更新日期：`2026-03-09`

## 1. 范围
当前遭遇系统已经从单步描述演进为带持续局势值的轻量持续场景系统。本文描述现状，而不是未来设计草案。

## 2. 当前状态模型

### 2.1 `EncounterEntry`
当前关键字段：
- `encounter_id`
- `type`
- `status`
- `trigger_kind`
- `title`
- `description`
- `zone_id`
- `sub_zone_id`
- `related_quest_ids`
- `related_fate_phase_ids`
- `termination_conditions`
- `steps`
- `scene_summary`
- `latest_outcome_summary`
- `npc_role_id`
- `player_presence`
- `participant_role_ids`
- `situation_start_value`
- `situation_value`
- `situation_trend`
- `last_outcome_package`
- `background_tick_count`
- `last_advanced_at`

### 2.2 `EncounterResolution`
当前结算记录字段：
- `encounter_id`
- `player_prompt`
- `reply`
- `time_spent_min`
- `quest_updates`
- `created_at`
- `situation_delta`
- `situation_value_after`
- `reputation_delta`
- `applied_outcome_summaries`

### 2.3 `EncounterState`
- `pending_ids`
- `active_encounter_id`
- `encounters`
- `history`
- `debug_force_trigger`
- `updated_at`

## 3. 局势值

### 3.1 初始值
局势值基线为 `50`，再按当前规则修正并夹到 `20..80`：
- 子区块声望 `>= 70`：`+10`
- 子区块声望 `<= 30`：`-10`
- 当前追踪 quest 或 fate phase 直接关联：`+5`
- 玩家 HP 或体力低于 30%：`-5`
- 至少一名队友在场：`+5`

### 3.2 行动增量
玩家、NPC、队友行动都可以修改 `situation_value`。

当前公式：
- `delta = clamp(situation_delta_hint + check_bonus, -20, +20)`
- `check_bonus = +8 / +4 / -4 / -8`

### 3.3 趋势
`situation_trend` 当前使用：
- `improving`
- `stable`
- `worsening`

每次变化都会写一条 `encounter_situation_update` scene event。

## 4. 结束条件
当前满足以下任一条件即结束：
- 终止条件命中
- `situation_value <= 0`
- `situation_value >= 100`

结果判定：
- `>= 100` 强制成功
- `<= 0` 强制失败
- 其他结束时 `>= 50` 视为成功，否则失败

## 5. 结果包

### 5.1 当前结构
`EncounterOutcomePackage` 当前包含：
- `result`
- `reputation_delta`
- `npc_relation_deltas`
- `team_deltas`
- `item_rewards`
- `buff_rewards`
- `resource_deltas`
- `narrative_summary`

### 5.2 当前落地规则
- 结果包会先清洗再写入存档
- 奖励物品目前只允许安全的 `misc`
- 声望变化会回写 `reputation_state`
- 关系和资源会真实写回角色/玩家状态

## 6. 当前接口
- `GET /api/v1/encounters/pending`
- `GET /api/v1/encounters/history`
- `POST /api/v1/encounters/check`
- `POST /api/v1/encounters/{encounter_id}/present`
- `POST /api/v1/encounters/{encounter_id}/act`
- `POST /api/v1/encounters/{encounter_id}/escape`
- `POST /api/v1/encounters/{encounter_id}/rejoin`
- `GET /api/v1/encounters/debug/overview`

## 7. 与公开场景的关系
- 活跃遭遇存在时，公开场景导演器会把当前遭遇锚点角色纳入优先序列
- NPC/队友公开动作也可推动局势值
- 主聊天 route 命中遭遇动作时，会先做真实的遭遇状态推进

## 8. 前端联动
- `frontend/src/components/EncounterLane.tsx`
- `frontend/src/components/EncounterModal.tsx`
- `frontend/src/App.tsx`

当前前端已展示：
- 局势值
- 初始局势值
- 趋势
- 最新结果摘要

## 9. 当前限制
- 这不是完整战斗系统
- 暂无先攻、回合条、技能资源分配面板
- 结果包仍是轻量奖励/惩罚，不是完整掉落表系统

## 10. 回归测试
- `backend/tests/test_encounter_service.py`
- `backend/tests/test_chat_route_scene_rendering.py`
- `backend/tests/test_role_system.py`
