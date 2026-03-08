# 核心玩法技术文档（Gameplay Core Technical）
## 设计来源
- `docs/design/gamedesign/gamedesign.md`
- `docs/design/gamedesign/worldmapdesign.md`
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/teamdesign.md`
- `docs/design/gamedesign/savedesign.md`
- `docs/design/gamedesign/debugdesign.md`
- `docs/design/gamedesign/actiondesign.md`

更新于 `2026-03-08`。

## 1. 核心术语
- `Zone`：世界地图区块
- `AreaSnapshot`：区域层状态快照
- `MapSnapshot`：地图层状态快照
- `PlayerStaticData`：玩家长期静态数据
- `PlayerRuntimeData`：玩家运行时数据
- `NpcRoleCard`：NPC 角色卡
- `TeamState`：当前队伍状态
- `SaveFile`：统一持久化对象

## 2. 坐标与耗时
- 坐标单位：
  - `x / y` 为米
  - `z` 为扩展字段
- 统一耗时：
  - `distance_m = distance((x1,y1,z1),(x2,y2,z2))`
  - `duration_h = distance_m / move_speed_mph`
  - `duration_min = ceil(duration_h * 60)`

## 3. API 归类（`/api/v1`）
### 3.1 地图
- `POST /world-map/regions/generate`
- `POST /world-map/render`
- `POST /world-map/move`

### 3.2 区域与交互
- `POST /world/clock/init`
- `GET /world/area/current`
- `POST /world/area/move-sub-zone`
- `POST /world/area/interactions/discover`
- `POST /world/area/interactions/execute`

### 3.3 聊天与角色
- `POST /chat`
- `POST /chat/stream`
- `POST /npc/greet`
- `POST /npc/chat`
- `POST /npc/chat/stream`
- `GET /role-pool`
- `GET /role-pool/{role_id}`
- `POST /role-pool/{role_id}/relate-player`
- `POST /role-pool/{role_id}/relations`

### 3.4 队伍
- `GET /team`
- `POST /team/invite`
- `POST /team/leave`
- `POST /team/chat`
- `POST /team/debug/generate`

### 3.5 玩家与检定
- `GET /player/static`
- `POST /player/static`
- `GET /player/runtime`
- `POST /player/runtime`
- `POST /actions/check`

### 3.6 叙事系统
- `GET /quests`
- `POST /quests/publish`
- `POST /quests/{quest_id}/accept`
- `POST /quests/{quest_id}/reject`
- `POST /quests/{quest_id}/track`
- `POST /quests/{quest_id}/evaluate`
- `POST /quests/evaluate-all`
- `GET /encounters/pending`
- `POST /encounters/check`
- `POST /encounters/{encounter_id}/present`
- `POST /encounters/{encounter_id}/act`
- `GET /fate/current`
- `POST /fate/debug/generate`
- `POST /fate/debug/regenerate`
- `POST /fate/evaluate`

### 3.7 一致性与存档
- `GET /story/snapshot`
- `GET /story/entity-index`
- `GET /consistency/status`
- `POST /consistency/run`
- `GET /storage/config/path`
- `POST /storage/config/path`
- `GET /saves/current`
- `POST /saves/import`
- `POST /saves/clear`

## 4. 状态机
### 4.1 地图
- `closed -> loading -> ready -> (moving | error)`

### 4.2 存档
- `idle -> (saving | loading | clearing) -> (idle | error)`

### 4.3 玩家面板
- `idle -> editing -> saving -> (idle | error)`

### 4.4 主聊天 / 单聊
- 主聊天：`idle -> (sending | streaming) -> (idle | error)`
- NPC 单聊：`idle -> waiting_greet(blocking) -> (sending | streaming) -> (idle | error)`

### 4.5 队伍
- 队伍面板：`closed -> loading -> ready -> closed`
- 招募流程：`idle -> inviting -> (accepted | rejected | error)`
- 队友离队：`active -> leaving -> (closed | error)`
- 队伍聊天：`idle -> sending -> (ready | error)`
- 调试队友生成：`idle -> generating -> (ready | error)`
- 队友背包详情：`closed -> ready -> closed`

### 4.6 行为检定
- 检定表单：`idle -> submitting -> idle`
- 投骰模态：`closed -> ready(blocking) -> rolling(blocking) -> resolving(blocking) -> (resolved | error) -> closed`

## 5. 队伍相关核心交互
### 5.1 自动反馈
以下行为后会触发队友反馈：
- 主聊天
- NPC 单聊
- 大区块移动
- 子区块移动
- 行为检定

### 5.2 队伍聊天
- 玩家从队伍面板发送一句话
- 后端推进世界时间
- 每个当前队友返回一次短回应
- 回应写入：
  - 角色卡 `dialogue_logs`
  - `team_state.reactions(trigger_kind=team_chat)`
  - `game_logs(kind=team_chat)`

### 5.3 队友背包查看
- 前端队伍面板通过 `RoleInventoryModal` 展示队友背包
- 数据来自 `NpcRoleCard.profile.dnd5e_sheet`
- 当前阶段只读

## 6. 行为检定协议
### 6.1 前端阶段
1. 记录待执行检定 payload
2. 打开 `ActionCheckRollModal`
3. 玩家点击空白区域，本地生成 `1..20` 的 `d20`
4. 将 `forced_dice_roll` 一并发给后端
5. 后端返回结算结果
6. 前端展示比较并等待继续

### 6.2 后端阶段
- 接口：`POST /actions/check`
- 当 `forced_dice_roll` 存在时，服务端必须使用该点数
- 当前目的：保证前端动画与后端真实结算一致

## 7. 前端实现落点
- 主状态：`frontend/src/App.tsx`
- 队伍面板：`frontend/src/components/TeamPanel.tsx`
- 队友背包模态：`frontend/src/components/RoleInventoryModal.tsx`
- NPC 池：`frontend/src/components/NpcPoolPanel.tsx`
- 投骰模态：`frontend/src/components/ActionCheckRollModal.tsx`
- API 层：`frontend/src/services/api.ts`
- 类型层：`frontend/src/types/app.ts`

## 8. 错误处理
- 若招募失败或被拒绝：
  - 不阻断主会话
  - 只更新配置提示或反馈文案
  - 不污染当前队伍状态
- 若队伍聊天失败：
  - 队伍面板保持打开
  - 不清空现有队伍状态
  - 不写入伪响应
- 若检定请求失败：
  - 投骰模态进入 `error(blocking)`
  - 允许玩家显式退出

## 9. 错误码约定
- `400` 参数错误
- `404` 资源不存在
- `409` 状态冲突
- `422` schema 校验失败
- `429` 上游限流
- `502` 上游模型错误

## 10. 结构说明
- JSON 数据结构统一维护在：
  - `backend/app/models/schemas.py`
  - `frontend/src/types/app.ts`
- 详细协议变化需要同步更新：
  - `team-technical.md`
  - `role-technical.md`
  - `ai-tool-protocol.md`
## 2026-03-08 Addendum
### 新增 Inventory API
- `POST /api/v1/inventory/equip`
- `POST /api/v1/inventory/unequip`
- `POST /api/v1/inventory/interact`

### Inventory 统一规则
- `player` 与 `role` 共用 `InventoryOwnerRef`
- `weapon/armor` 走 `equip/unequip`
- `misc` 物品支持 `inspect/use`
- `inspect` 不走检定
- `use` 只对 `misc` 开放，必要时会进入 `action_check`
- 物品 `uses_left` 仅在成功 `use` 时扣减

### 遭遇模态状态机
- `pendingEncounter` 已进入统一阻塞条件
- 单聊状态下触发遭遇时，前端会先切回主聊天，再展示遭遇模态
- 遭遇结算后的后续输入目标始终是主聊天

### 队友/玩家物品交互前端链路
- 新增共享组件：
  - `CharacterInventoryModal`
  - `ItemInteractionModal`
  - `RoleProfileModal`
- 玩家背包与队友背包现在都走共享 UI 和共享后端协议
