# 角色系统技术设计（Role Technical）
## 设计来源
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/actiondesign.md`
- `docs/design/gamedesign/teamdesign.md`

更新于 `2026-03-08`。

## 1. 目标与边界
- 使用统一角色底座覆盖玩家、NPC、怪物。
- 保持玩家与 NPC 的背包、装备、BUFF、法术、技能模型一致。
- 让 NPC 角色卡不仅服务单聊，也服务关系、队伍、一致性和背包查看。
- 当前重点是数据模型、运行时计算、对话日志和队伍复用，不做完整角色卡编辑器。

## 2. 统一角色底座
位置：`backend/app/models/schemas.py`

### 2.1 核心模型
- `PlayerStaticData`
- `Dnd5eCharacterSheet`
- `Dnd5eAbilityScores`
- `Dnd5eAbilityModifiers`
- `Dnd5eHitPoints`
- `Dnd5eSpellSlots`
- `InventoryItem`
- `InventoryData`
- `EquipmentSlots`
- `RoleBuff`

### 2.2 对 roledesign 的映射
- 等级、经验、升级经验
- 六维能力值及当前值
- 六维修正值及当前修正
- AC / DC
- 背包、装备槽、BUFF、法术、技能
- 体力、HP、死亡状态、状态标记
- 熟练项与特质
- 关系列表

### 2.3 当前字段落点
- 基础属性：`ability_scores`
- 当前属性：`current_ability_scores`
- 基础修正：`ability_modifiers`
- 当前修正：`current_ability_modifiers`
- 背包：`backpack`
- 装备槽：`equipment_slots`
- BUFF：`buffs`
- HP：`hit_points`
- 体力：`stamina_current / stamina_maximum`
- 法术位：`spell_slots_max / spell_slots_current`

## 3. 派生值计算
位置：`backend/app/services/world_service.py`

统一通过 `_recompute_player_derived(...)` 计算：
- 当前属性 = 基础属性 + BUFF 影响
- 当前修正 = 当前属性按 5E 公式换算
- AC = 基础 10 + 护甲加值 + 敏捷修正 + BUFF
- DC = 8 + 熟练加值 + 攻击相关修正 + 武器加值 + BUFF
- 当前 HP / 当前体力 / 当前法术位会被裁剪到合法范围
- HP 归零时自动标记 `is_dead=true`

说明：
- 这是工程化的 5E 映射，不追求完整桌规实现。
- 玩家与 NPC 共用同一套派生逻辑。

## 4. NPC 角色卡
### 4.1 `NpcRoleCard`
除统一角色底座外，还包含：
- `role_id`
- `name`
- `zone_id / sub_zone_id`
- `source_world_revision / source_map_revision`
- `knowledge_scope`
- `state`
- `personality`
- `speaking_style`
- `appearance`
- `background`
- `cognition`
- `alignment`
- `relations`
- `cognition_changes`
- `attitude_changes`
- `dialogue_logs`

### 4.2 关系规则
- 关系结构：`RoleRelation`
  - `target_role_id`
  - `relation_tag`
  - `note`
- 预生成 NPC 初始可带 1~2 条 NPC 之间关系。
- 不在预生成阶段直接写入玩家关系。
- 玩家关系通过单聊、检定、入队等运行时事件追加或更新。

### 4.3 对话日志规则
- 使用 `NpcDialogueEntry`
- 每条记录至少包含：
  - 世界日期 / 时间文本
  - 说话方
  - 文本内容
- 日志保存在角色卡内部，作为后续单聊、队伍聊天的上下文来源。

## 5. NPC 单聊与知识边界
位置：`backend/app/services/world_service.py`

### 5.1 问候
- `npc_greet(req)`
- 语义：玩家刚靠近 NPC 的第一反应
- 输出要求：
  - 短句
  - 口语
  - 不要长段旁白

### 5.2 正式对话
- `npc_chat(req)`
- 核心流程：
  1. 推进玩家发言时间
  2. 写入玩家发言日志
  3. 构建历史上下文
  4. 构建 `NpcKnowledgeSnapshot`
  5. 若玩家提到越界人物/区域，优先走 guard reply
  6. 模型输出后再做非法实体名过滤
  7. 写入 NPC 回应日志

## 6. 与队伍系统的结合
- 队友不另建新角色结构，直接复用 `NpcRoleCard.profile: PlayerStaticData`
- 因此队友天然拥有：
  - 统一 DND 角色卡
  - 背包
  - 装备槽
  - BUFF
  - 法术 / 技能
  - 关系
  - 对话日志

### 6.1 队伍聊天
- 队伍聊天 `team_chat` 会把玩家发言和队友回应分别写入每名队友的 `dialogue_logs`
- 当前队友回应支持：
  - `speech` 直接说话
  - `action` 仅动作反馈
- 队伍聊天与单聊共用同一份角色卡记忆，而不是额外建一份“队友聊天记忆”

### 6.2 队友背包查看
- 前端通过队伍面板查看队友背包详情
- AI 通过 `get_role_inventory` 结构化读取队友背包
- 当前阶段只读，不开放直接编辑队友物品

## 7. API 契约影响
### 7.1 玩家相关
- `GET /api/v1/player/static`
- `POST /api/v1/player/static`
- `GET /api/v1/player/runtime`
- `POST /api/v1/player/runtime`

### 7.2 NPC 与队伍相关
- `GET /api/v1/role-pool`
- `GET /api/v1/role-pool/{role_id}`
- `POST /api/v1/role-pool/{role_id}/relate-player`
- `POST /api/v1/role-pool/{role_id}/relations`
- `POST /api/v1/npc/greet`
- `POST /api/v1/npc/chat`
- `POST /api/v1/npc/chat/stream`
- `GET /api/v1/npc/{npc_role_id}/knowledge`
- `GET /api/v1/team`
- `POST /api/v1/team/invite`
- `POST /api/v1/team/leave`
- `POST /api/v1/team/chat`

## 8. 前端联动
位置：
- `frontend/src/App.tsx`
- `frontend/src/components/NpcPoolPanel.tsx`
- `frontend/src/components/PlayerPanel.tsx`
- `frontend/src/components/TeamPanel.tsx`
- `frontend/src/components/RoleInventoryModal.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`

当前行为：
- 玩家数据仍可即时保存并刷新生效
- `NpcPoolPanel` 可查看角色关系、聊天日志、背包摘要
- `TeamPanel` 可：
  - 查看队友状态
  - 发起队伍聊天
  - 查看队友背包详情
  - 进入队友单聊

## 9. 存档兼容
- 新字段全部带默认值或 `default_factory`
- 旧存档读取时自动补齐：
  - 扩展后的角色卡字段
  - 对话日志
  - 关系
  - `team_state`

## 10. 当前限制
- 玩家角色面板还不是完整的角色卡编辑器。
- 队友关系数值仍是轻量实现，没有完整策划表。
- 队友背包当前没有“使用 / 装备 / 转移”操作入口。
## 2026-03-08 Addendum
### Prompt 驱动的完整队友属性
- 新增共享生成入口：`backend/app/services/team_service.py::generate_team_role_from_prompt(...)`
- 规则是“AI 决定概念，后端决定合法数值”
- 结构化字段包括：
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
- 后端会对 `race`、`char_class`、`ability_bias`、装备偏好、背包物品做枚举/目录清洗，不接受自由文本直接落库为非法装备。

### 新的统一背包协议
- `InventoryOwnerRef` 抽象了物品归属：
  - `owner_type=player`
  - `owner_type=role`
- 新增后端 schema：
  - `InventoryEquipRequest`
  - `InventoryUnequipRequest`
  - `InventoryMutationResponse`
  - `InventoryInteractRequest`
  - `InventoryInteractResponse`
- 玩家和 NPC/队友现在共用同一套装备、卸下、观察、使用协议，不再各走一套前后端逻辑。

### 队友完整属性查看
- 前端新增 `RoleProfileModal`
- 队伍面板支持直接查看队友完整角色卡：
  - 基础信息
  - NPC 设定字段
  - DND5E 数值与资源
  - 技能/语言/法术/特性
  - relations / cognition_changes / attitude_changes / dialogue_logs
