# 角色系统技术设计（Role Technical）

## 设计来源
- docs/design/gamedesign/roledesign.md
- docs/design/gamedesign/actiondesign.md

本文档描述角色系统当前技术落地（M1），聚焦玩家静态数据中的 DND 5E 角色卡模板。

## 1. 目标与边界
- 在不破坏现有玩法链路（地图、移动、存档、日志）的前提下，扩展角色字段。
- 保持 `GET/POST /api/v1/player/static` 契约稳定，支持新旧存档兼容。
- 当前仅实现数据模型与持久化，前端暂不要求完整编辑所有角色卡字段。

## 2. 数据结构
位置：`backend/app/models/schemas.py`

### 2.1 新增模型
- `Dnd5eAbilityScores`
- `Dnd5eHitPoints`
- `Dnd5eCharacterSheet`

### 2.2 PlayerStaticData 扩展
```json
{
  "player_id": "player_001",
  "name": "玩家",
  "move_speed_mph": 4500,
  "role_type": "player",
  "dnd5e_sheet": {
    "level": 1,
    "race": "",
    "char_class": "",
    "background": "",
    "alignment": "",
    "proficiency_bonus": 2,
    "armor_class": 10,
    "speed_ft": 30,
    "initiative_bonus": 0,
    "hit_dice": "1d8",
    "hit_points": {"current": 10, "maximum": 10, "temporary": 0},
    "ability_scores": {
      "strength": 10,
      "dexterity": 10,
      "constitution": 10,
      "intelligence": 10,
      "wisdom": 10,
      "charisma": 10
    },
    "saving_throws_proficient": [],
    "skills_proficient": [],
    "languages": [],
    "tool_proficiencies": [],
    "equipment": [],
    "features_traits": [],
    "spells": [],
    "notes": ""
  }
}
```

## 3. API 契约影响
- 新增 NPC 角色池与单聊相关接口：
  - `GET /api/v1/role-pool`
  - `GET /api/v1/role-pool/{role_id}`
  - `POST /api/v1/role-pool/{role_id}/relate-player`
  - `POST /api/v1/npc/greet`
  - `POST /api/v1/npc/chat`
  - `POST /api/v1/npc/chat/stream`
- 玩家字段接口保持可用：
  - `GET /api/v1/player/static`
  - `POST /api/v1/player/static`

## 4. 存档兼容策略
- `PlayerStaticData` 新字段均提供默认值（`default` / `default_factory`）。
- 读取旧存档时，Pydantic 自动补齐新字段。
- 写回存档时，新增字段会被完整持久化到 `SaveFile.player_static_data`。
- NPC 角色卡在区块生成时写入存档 `role_pool`，与 bundle 分片一起持久化。

## 5. NPC 角色卡扩展（M2）
位置：`backend/app/models/schemas.py`

### 5.1 新增结构
- `NpcDialogueEntry`
  - `id`
  - `speaker` (`player|npc`)
  - `speaker_role_id`
  - `speaker_name`
  - `content`
  - `world_time_text`
  - `world_time`
  - `created_at`

### 5.2 NpcRoleCard 扩展
- 新增 `dialogue_logs: list[NpcDialogueEntry]`。
- 运行时保留最近 200 条，避免角色卡无限膨胀。

## 6. NPC 单聊流程（后端）
位置：`backend/app/services/world_service.py`

- `npc_greet(req)`：
  - 生成“玩家刚靠近”语境的问候语。
  - 问候语写入 `role.dialogue_logs`。
- `npc_chat(req)`：
  - 先按 token 粗估计算发言耗时并推进世界时钟。
  - 将玩家发言写入 `role.dialogue_logs`（带世界时间）。
  - 取最近历史记录拼接上下文给 AI。
  - 将 NPC 回复写入 `role.dialogue_logs`（带世界时间）。
- `npc_chat/stream`：
  - 事件流 `start/delta/end/error`。
  - `end` 返回 `time_spent_min + dialogue_logs`，前端以结构化记录回填最终显示。

## 7. 前端联动
位置：
- `frontend/src/App.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/app.ts`
- `frontend/src/components/NpcPoolPanel.tsx`

要点：
- 聊天模式区分 `main` 与 `npc`。
- NPC 模式发送优先走 `/npc/chat/stream`（`config.stream=true` 时）。
- 进入 NPC 单聊时显示等待遮罩，问候返回后解除。
- 角色池详情可查看最新结构化聊天记录。

## 8. 前端类型同步
位置：`frontend/src/types/app.ts`

- 新增：`Dnd5eAbilityScores`、`Dnd5eHitPoints`、`Dnd5eCharacterSheet`
- 新增：`NpcDialogueEntry`、`NpcChatResponse`
- 更新：`PlayerStaticData`、`NpcRoleCard`、`defaultPlayerStaticData`

## 9. 已知限制
- `PlayerPanel` 目前仍只编辑玩家 ID、名称、移动速度。
- 角色卡完整编辑 UI 留待后续迭代（不影响数据存储与接口可用性）。
