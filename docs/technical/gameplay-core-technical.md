# 核心玩法技术文档（Gameplay Core Technical）

## 设计来源
- docs/design/gamedesign/gamedesign.md
- docs/design/gamedesign/worldmapdesign.md
- docs/design/gamedesign/roledesign.md
- docs/design/gamedesign/savedesign.md
- docs/design/gamedesign/debugdesign.md
- docs/design/gamedesign/actiondesign.md

## 1. 核心术语（技术映射）
- `Zone`：地图最小可交互单元。
- `MapSnapshot`：地图状态快照（区块集合 + 玩家位置）。
- `PlayerStaticData`：玩家长期静态数据。
- `PlayerRuntimeData`：玩家会话动态数据。
- `SaveFile`：统一持久化对象（逻辑层）。

## 2. 坐标与耗时计算
- 坐标单位：`x/y` 使用米（meter），`z` 为扩展字段。
- 距离：二维或三维欧氏距离（按功能选择）。
- 统一耗时计算：
  - `distance_m = distance((x1,y1,z1),(x2,y2,z2))`
  - `duration_h = distance_m / move_speed_mph`
  - `duration_min = ceil(duration_h * 60)`

## 3. API 归类（`/api/v1`）
### 3.1 地图
- `POST /world-map/regions/generate`
- `POST /world-map/render`
- `POST /world-map/move`

### 3.2 区块与交互
- `POST /world/clock/init`
- `GET /world/area/current`
- `POST /world/area/move-sub-zone`
- `POST /world/area/interactions/discover`
- `POST /world/area/interactions/execute`

### 3.3 玩家数据
- `GET /player/static`
- `POST /player/static`
- `GET /player/runtime`
- `POST /player/runtime`
- `GET /role-pool`
- `GET /role-pool/{role_id}`
- `POST /role-pool/{role_id}/relate-player`
- `POST /npc/greet`
- `POST /npc/chat`
- `POST /npc/chat/stream`
- `POST /actions/check`

### 3.4 存档与路径
- `GET /storage/config/path`
- `POST /storage/config/path`
- `POST /storage/config/path/pick`
- `GET /storage/config`
- `POST /storage/config`
- `GET /saves/path`
- `POST /saves/path`
- `POST /saves/path/pick`
- `POST /saves/import`
- `GET /saves/current`
- `POST /saves/current`
- `POST /saves/clear`

### 3.5 日志与统计
- `POST /logs/behavior/describe`
- `GET /logs/game`
- `POST /logs/game`
- `GET /logs/game/settings`
- `POST /logs/game/settings`
- `GET /token-usage`

## 4. 状态机（实现层）
### 4.1 地图状态
- `closed` -> `loading` -> `ready` -> (`moving` | `error`)

### 4.2 存档状态
- `idle` -> (`saving` | `loading` | `clearing`) -> (`idle` | `error`)

### 4.3 玩家数据状态
- `idle` -> `editing` -> `saving` -> (`idle` | `error`)

### 4.4 聊天状态
- 主聊天：`idle` -> (`sending` | `streaming`) -> (`idle` | `error`)
- NPC 单聊：`idle` -> `waiting_greet(blocking)` -> (`sending` | `streaming`) -> (`idle` | `error`)

## 5. 错误码约定
- `400` 参数错误
- `404` 资源不存在
- `409` 状态冲突
- `422` schema 校验失败
- `429` 上游限流
- `502` 上游模型错误

## 6. 结构说明
- 设计文档不再放置 JSON 示例结构。
- JSON 数据结构、字段兼容策略、校验规则统一维护在技术文档与 `backend/app/models/schemas.py`。

