# 存档系统技术文档
更新时间: `2026-03-22`

## 1. 范围

本文档描述当前与公开回合死亡设计、玩家与随从构筑相关的存档形状和恢复规则。

本轮新增独立 shard `character_build_state.json`，同时扩展玩家、NPC 与起始物品来源字段。

## 2. 公开回合持久化位置

公开回合状态仍持久化在:
- `AreaSubZone.chat_context.public_turn_state`

pending turn 仍持久化在:
- `pending-turn-state.json`

## 3. 角色状态持久化

### 3.1 `Dnd5eCharacterSheet`

当前已持久化:
- `hit_points`
- `death_state`
- `role_action_status`

其中:
- `death_state.life_status` 负责生命层状态
- `role_action_status` 负责行动层状态

### 3.2 当前有效值

`death_state.life_status`:
- `healthy`
- `dying`
- `stable`
- `dead`

`role_action_status`:
- `free_action`
- `death_saving`
- `dead`
- `unable_to_act`

## 4. 公开回合轮状态

### 4.1 `PublicTurnRound`

当前关键字段:
- `phase`
- `initiative_order`
- `executed_actor_ids`
- `pending_interaction_prompt`
- `pending_attack_prompt`
- `pending_attack_defense_prompt`
- `pending_death_save_prompt`
- `awaiting_player_action`
- `awaiting_player_action_phase`
- `impacts`
- `settlement_entries`
- `accumulated_narration`
- `round_narration`

### 4.2 死亡豁免暂停点

玩家在自己回合进入死亡豁免时:
- `phase = awaiting_player_death_save`
- `pending_death_save_prompt` 被写入当前轮

这保证了:
- 刷新前端后可恢复死亡豁免窗口
- pending turn 恢复时能直接重建 UI

## 5. Pending Turn 持久化

### 5.1 `PendingTurnState.status`

当前公开回合相关状态包括:
- `awaiting_reaction`
- `awaiting_opposed`
- `awaiting_player_attack_response`
- `awaiting_player_attack_defense`
- `awaiting_player_death_save`
- `awaiting_protocol_repair`

### 5.2 当前新增字段

`PendingTurnState` / `PendingTurnContinueResponse` 新增:
- `death_save_prompt`

恢复逻辑:
- `public_turn_state_store.sync_pending_public_turn_in_save()` 会把 `awaiting_player_death_save` 同步回当前公开回合轮状态
- 前端 `getCurrentPendingTurn()` 恢复后会重建 `PublicTurnDeathSaveModal`

## 6. 子区块死亡记录

### 6.1 存储位置

当前在 `AreaSubZone.state` 下新增:
- `dead_npc_records`

### 6.2 记录结构

每条记录至少包含:
- `role_id`
- `name`
- `death_at`
- `death_cause`
- `was_team_member`

### 6.3 语义

`dead_npc_records` 不是单纯叙事日志，它是恢复时的过滤依据。

具体效果:
- 死亡 NPC 不再重新注入 `AreaSubZone.npcs`
- 不再恢复成 `visible_npcs`
- 不再成为公开回合候选角色

## 7. 非队友 NPC 与队友 NPC 的差异

### 7.1 非队友 NPC

`HP <= 0` 时:
- `NpcRoleCard.state = "dead"`
- `role_action_status = "dead"`
- 立刻写入 `dead_npc_records`

### 7.2 队友 NPC

`HP <= 0` 时:
- 进入 `dying + death_saving`
- 不立即写入 `dead_npc_records`
- 只有真正死亡后才记录

## 8. Scene Event 与结算落档

当前新增事件会跟随回合正常落档:
- `player_entered_death_save`
- `player_death_save_result`
- `player_died`
- `team_npc_entered_death_save`
- `team_npc_death_save_result`
- `team_npc_died`
- `sub_zone_dead_npc_recorded`

同时结算仍写入:
- `PublicTurnImpact.hp_changes`
- `PublicTurnSettlementEntry.hp_changes`

## 9. 前端恢复规则

刷新页面后，前端按以下优先级恢复:
1. `pending-turn-state.json`
2. 当前子区块的 `public_turn_state.current_round`

死亡豁免相关恢复条件:
- 若 pending turn 为 `awaiting_player_death_save`，直接恢复死亡豁免弹窗
- 若当前轮 `phase = awaiting_player_death_save` 且 `pending_death_save_prompt` 存在，也可直接恢复

## 10. 兼容策略

本轮兼容原则:
- 不新增独立 death shard
- 旧存档读取时，若没有 `role_action_status`，默认按当前模型默认值补齐
- 旧存档若没有 `dead_npc_records`，按空数组处理
- 旧公开回合历史记录仍可读，但不会自动补写新死亡字段

## 11. Debug Reset 影响面

调试重置会清理:
- 当前子区块 `public_turn_state.current_round`
- 当前子区块 `public_turn_state.round_history`
- `pending-turn-state.json`

本轮额外要求:
- 若本地 UI 仍保留死亡豁免弹窗状态，前端也必须同步清空
- 但 `dead_npc_records` 是否保留，应以 debug reset 服务当前实现为准，不能在前端假设

## 12. 角色构筑持久化

### 12.1 Save Bundle

当前 save bundle 新增:
- `character_build_state.json`

当前 shard 字段:
- `player_status`
- `initial_companion_offer_seen`
- `updated_at`

语义:
- `player_status=uncreated` 时，新存档必须先完成玩家构筑
- `initial_companion_offer_seen=false` 且队伍为空时，前端会在玩家建成后弹一次首个随从提示

### 12.2 玩家与随从资料

`PlayerStaticData` 新增:
- `age`
- `height_cm`
- `body_type`
- `appearance`
- `portrait`
- `build_archive_id`

`NpcRoleCard` 新增:
- `portrait`
- `retained_id`

`portrait` 使用 `PortraitAssetRef`:
- `asset_id`
- `relative_path`
- `variant_kind`
- `derived_from_asset_id`
- `provider`
- `model`

其中 `variant_kind` 当前有效值:
- `uploaded_raw`
- `generated_raw`
- `bg_removed`
- `final_portrait`

### 12.3 用户级构筑留档

当前新增用户目录:
- `data/users/<username>/build-temp/portrait_assets/`
- `data/users/<username>/player-builds/<archive_id>/`
- `data/users/<username>/retained-builds/<retained_id>/`

其中:
- `build-temp/portrait_assets/` 保存临时原图、去背景图和最终图元数据
- `player-builds/<archive_id>/manifest.json` 保存玩家构筑 seed
- `player-builds/<archive_id>/portrait.png` 保存玩家归档立绘
- `retained-builds/<retained_id>/portrait.png` 保存随从归档立绘

### 12.4 起始授予来源

`InventoryItem.origin` 新增 `OriginStamp`:
- `origin_kind`
- `origin_ref`

`Dnd5eCharacterSheet` 新增:
- `spell_origins`
- `skill_origins`
- `war_arts`
- `war_art_origins`
- `martial_points_current`
- `martial_points_maximum`

当前首发规则里，构筑系统授予的起始法术、武技、武装、药水都写:
- `origin_kind=starting_build`
- `origin_ref=<archive_id or role_id>`

### 12.5 Spell And War Art Resources

Current runtime rule:
- spell slots use a fee model
- war arts use a fee model
- base spell slot cap is `1` when the sheet has spells
- base martial-point cap is `1` when the sheet has war arts
- both caps scale with `Dnd5eCharacterSheet.level`, currently clamped to `1..9`

Recompute behavior:
- `spell_slots_max.level_1` is derived from level
- `spell_slots_current` is clamped to the derived max
- `martial_points_maximum` is derived from level
- `martial_points_current` is clamped to the derived max
- first acquisition of spells or war arts initializes the current resource to the derived max
- `origin_ref=<本次构筑 archive_id 或随从 role_id>`

## 13. 玩家输入校验与存档

`/player-input/validate` 是纯读取型预校验接口，不新增 save shard，也不新增 pending turn 持久化字段。

当前约束:
- 不写 `world_state.json`
- 不写 `pending-turn-state.json`
- 不写任何 validation ticket
- 不记录前端“一次性绕过再次校验”状态

当前接口会读取:
- 当前 `SaveFile`
- 角色自身 `Dnd5eCharacterSheet`
- 模板库中的 `spell_definitions.csv`
- 模板库中的 `war_art_definitions.csv`
- 背包物品对应的 definition 映射

因此本轮与玩家输入校验相关的持久化结论只有:
- 无新 shard
- 无新恢复阶段
- 页面刷新后，前端确认态与一次性绕过态都会失效
