# 角色系统技术文档

更新日期：`2026-03-09`

## 1. 范围
本文描述当前角色底座、`NpcRoleCard` 扩展字段、欲望/故事状态、公开场景中的角色主动性，以及它们与关系和声望的联动。

## 2. 统一角色底座
玩家和 NPC 共享统一的 DND5E 风格角色底座：
- `PlayerStaticData`
- `Dnd5eCharacterSheet`
- `InventoryItem`
- `InventoryData`
- `EquipmentSlots`
- `RoleBuff`

派生值仍由 `backend/app/services/world_service.py` 统一重算。

## 3. `NpcRoleCard` 当前职责
除基础资料、个性和关系外，`NpcRoleCard` 现在还负责承载：
- 公开区域中的持久状态
- 欲望和队友故事种子
- 对话日志
- 最近公开轮次记忆

当前关键字段：
- `role_id`
- `name`
- `zone_id`
- `sub_zone_id`
- `state`
- `personality`
- `speaking_style`
- `background`
- `cognition`
- `relations`
- `dialogue_logs`
- `desires`
- `story_beats`
- `last_public_turn_at`

## 4. 角色欲望

### 4.1 数据结构
`RoleDesire` 当前字段：
- `desire_id`
- `kind`
- `title`
- `summary`
- `intensity`
- `status`
- `visibility`
- `preferred_surface`
- `target_refs`
- `linked_quest_id`
- `cooldown_until`
- `last_surfaced_at`

### 4.2 当前规则
- 新 NPC 自动补齐 `1-2` 个 desire
- desire 是隐式状态，不要求一创建就向玩家公开
- desire 可以在 `public_scene / team_chat / area_arrival / encounter_aftermath / private_chat` 浮出
- 满足条件时可转成普通 quest，并把 `status` 置为 `quest_linked`

### 4.3 当前实现位置
- `backend/app/services/roleplay_service.py`

## 5. 队友故事

### 5.1 数据结构
`RoleStoryBeat` 当前字段：
- `beat_id`
- `title`
- `summary`
- `affinity_required`
- `min_days_in_team`
- `status`
- `preferred_surface`
- `last_surfaced_at`
- `completed_at`

### 5.2 当前规则
- 只有队友才会自动补齐 story beats
- 默认每名队友补齐 2 个 story beat
- 当前触发门槛：
  - `affinity >= 60`
  - 入队至少 2 天
  - 当前无 active encounter
  - 同角色当天未触发过 story beat
- 默认只作为公开事件或队伍聊天话题，不开模态

## 6. 公开场景中的角色主动性

### 6.1 导演器读取角色状态
公开场景导演器会读取：
- 当前可见角色
- desire/story 的浮出状态
- 最近公开轮次时间
- 当前遭遇锚点
- 与玩家输入的直接关联

### 6.2 行动结果
角色行动会产生：
- `public_actor_resolution`
- `public_targeted_npc_reply`
- `public_bystander_reaction`
- `team_public_reaction`

角色公开动作还可能带来：
- 声望变化
- 关系变化
- 遭遇局势变化

## 7. 关系与声望偏置
- 关系基础仍保存在 `NpcRoleCard.relations`
- 子区块声望高时，正向关系变化会被额外放大
- 子区块声望低时，负向关系变化会被额外放大
- 当前偏置实现位于 `backend/app/services/reputation_service.py::apply_reputation_relation_bias(...)`

## 8. 对话与日志
- NPC 单聊写入 `dialogue_logs`
- 公开点名和公开反应也会写入对话日志，但带不同 `context_kind`
- 队伍聊天与公开反应共享同一角色记忆，而不是另建一套“队友聊天历史”

## 9. 前端展示
- `frontend/src/components/RoleProfileModal.tsx`
- `frontend/src/components/TeamPanel.tsx`
- `frontend/src/components/SubZoneContextPanel.tsx`

当前前端已可展示：
- desire 摘要
- story beat 摘要
- 公开事件中的角色动作

## 10. 回归测试
- `backend/tests/test_role_system.py`
- `backend/tests/test_npc_chat_routes.py`
- `backend/tests/test_chat_route_scene_rendering.py`
