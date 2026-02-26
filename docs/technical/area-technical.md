# 区块系统技术设计（Area Technical）

## 设计来源
- docs/design/gamedesign/areadesign.md

本文档描述当前已实现的区块子系统（M1），用于后端实现、前端联调、回归测试。

## 1. 目标与边界

### 1.1 M1 已实现
- 区块与子区块同批生成并落盘。
- 大区块/子区块移动与耗时计算（含三维距离）。
- 全局时钟初始化与行为推进。
- 关键交互与 NPC 占位闭环。
- 即时发现交互（AI 生成 + schema 校验 + 去重 + fallback）。

### 1.2 M1 未实现
- 真实交互结果结算。
- NPC 深度行为。
- 剧情任务系统。

### 1.3 AI 与逻辑职责
`AI 负责`：语义内容（名称/描述/叙事）、发现交互候选。

`逻辑负责`：
- 结构合法性和字段兜底。
- 半径、数量、坐标约束。
- 非重叠校正。
- 时钟推进。
- 存档一致性。

## 2. 关键数据结构（对应 `backend/app/models/schemas.py`）

### 2.1 Zone（地图区块）
```json
{
  "zone_id": "zone_50_60_0",
  "name": "翠影森林",
  "x": 50,
  "y": 60,
  "z": 0,
  "zone_type": "forest",
  "size": "large",
  "radius_m": 300,
  "description": "...",
  "tags": ["forest"],
  "sub_zones": [
    {"name": "古树之心", "offset_x": 80, "offset_y": 40, "offset_z": 0, "description": "..."}
  ]
}
```

### 2.2 AreaSnapshot（区块运行态快照）
```json
{
  "version": "0.1.0",
  "zones": [],
  "sub_zones": [],
  "current_zone_id": "zone_50_60_0",
  "current_sub_zone_id": "sub_zone_50_60_0_1",
  "clock": {
    "calendar": "fantasy_default",
    "year": 1024,
    "month": 3,
    "day": 14,
    "hour": 9,
    "minute": 30,
    "updated_at": "2026-02-25T00:00:00Z"
  }
}
```

### 2.3 AreaZone / AreaSubZone（前端面板主数据）
```json
{
  "zone_id": "zone_50_60_0",
  "name": "翠影森林",
  "zone_type": "forest",
  "size": "large",
  "center": {"x": 50, "y": 60, "z": 0},
  "radius_m": 300,
  "description": "...",
  "sub_zone_ids": ["sub_zone_50_60_0_1"]
}
```

```json
{
  "sub_zone_id": "sub_zone_50_60_0_1",
  "zone_id": "zone_50_60_0",
  "name": "古树之心",
  "coord": {"x": 130, "y": 100, "z": 0},
  "radius_m": 20,
  "description": "...",
  "generated_mode": "pre",
  "key_interactions": [
    {"interaction_id": "int_x", "name": "观察周边", "type": "scene", "status": "ready", "generated_mode": "pre", "placeholder": true}
  ],
  "npcs": [
    {"npc_id": "npc_x", "name": "向导（占位）", "state": "idle"}
  ]
}
```

### 2.4 RenderMapResponse（地图绘制数据）
```json
{
  "session_id": "sess_xxx",
  "viewport": {"min_x": -100, "max_x": 300, "min_y": -80, "max_y": 260},
  "nodes": [{"zone_id": "zone_a", "name": "白银城", "x": 100, "y": 130}],
  "sub_nodes": [{"sub_zone_id": "sub_zone_a_1", "zone_id": "zone_a", "name": "市场", "x": 120, "y": 140}],
  "circles": [{"zone_id": "zone_a", "center_x": 100, "center_y": 130, "radius_m": 240}],
  "player_marker": {"x": 120, "y": 140}
}
```

### 2.5 AreaMoveResult（子区块移动结果）
```json
{
  "ok": true,
  "from_point": {"zone_id": "zone_a", "sub_zone_id": "sub_zone_a_1", "coord": {"x": 120, "y": 140, "z": 0}},
  "to_point": {"zone_id": "zone_b", "sub_zone_id": "sub_zone_b_2", "coord": {"x": 260, "y": 90, "z": 0}},
  "distance_m": 148.66,
  "duration_min": 2,
  "clock_delta_min": 2,
  "clock_after": {"calendar": "fantasy_default", "year": 1024, "month": 3, "day": 14, "hour": 9, "minute": 32, "updated_at": "..."},
  "movement_feedback": "你移动到【...】..."
}
```

## 3. API 契约（`/api/v1`）

### 3.1 地图与区块生成
- `POST /world-map/regions/generate`
- `POST /world-map/render`
- `POST /world-map/move`

说明：
- `regions/generate` 调用 AI 生成区块，并写入 `map_snapshot + area_snapshot`。
- `render` 返回大区块节点、子区块节点和大区块范围圈。
- `world-map/move` 移动到大区块中心，同时刷新 `area_snapshot.current_zone_id`，并清空 `current_sub_zone_id`。

### 3.2 区块时钟与子区块交互
- `POST /world/clock/init`
- `GET /world/area/current`
- `POST /world/area/move-sub-zone`
- `POST /world/area/interactions/discover`
- `POST /world/area/interactions/execute`

说明：
- `move-sub-zone` 支持跨大区块子区块移动。
- `discover` 为玩家主动触发，返回 `generated_mode=instant`。
- `execute` 当前统一返回占位结果 `message="待开发"`。

## 4. 生成与校验规则

### 4.1 大区块规则
- `size -> 子区块数量范围`
  - small: 3~5
  - medium: 5~10
  - large: 8~15
- `size -> radius_m 范围`
  - small: 60~180
  - medium: 120~300
  - large: 240~500
- 非重叠约束：若 AI 结果重叠，逻辑层执行位移修正。

### 4.2 子区块规则
- `offset_x/offset_y/offset_z` 为相对大区块中心偏移。
- 偏移向量若超出半径，自动按比例裁剪进半径范围。
- AI 返回缺失或质量差时，使用 `_default_sub_zone_seeds` 自动补全。

### 4.3 即时发现交互规则
- AI 提示词要求严格 JSON：`{"interactions":[...]}`。
- 服务端做 schema 校验：必须有合法 `name/type/status`。
- 去重策略：
  - 按名称（小写）去重。
  - 交互 ID 防冲突。
  - 单次最多合并 3 条。
- AI 失败时 fallback：生成 `调查：<intent>` 占位交互。

## 5. 计算规则

### 5.1 距离
- 大区块移动：二维欧氏距离。
- 子区块移动：三维欧氏距离。

### 5.2 耗时
- `duration_min = max(1, ceil(distance_m / move_speed_mph * 60))`

### 5.3 时钟推进
- 移动：推进 `duration_min`。
- 发现交互：推进 1 分钟。
- 执行占位交互：推进 1 分钟。

## 6. 前端契约重点

- 左栏以 `area_snapshot.zones + sub_zones` 构建区块树。
- 子区块预计耗时基于当前坐标动态计算（当前子区块坐标优先，其次当前大区块中心）。
- 地图渲染：
  - `circles` 绘制大区块范围圈与名称。
  - `sub_nodes` 绘制子区块点位与名称。
- 聊天区只展示当前 AI 回复；“你已在xx”改为弹窗提示。

## 7. 存档与日志

### 7.1 存档
`SaveFile` 持久化以下核心字段：
- `map_snapshot`
- `area_snapshot`
- `game_logs`
- `player_static_data`
- `player_runtime_data`
- `role_pool`（新增）：区块生成时产生的 NPC 角色卡集合，供后续交互与调试查看

### 7.2 游戏日志种类（区块相关）
- `area_generate`
- `area_move`
- `area_refresh`
- `area_interaction_placeholder`
- `move`（大区块移动）

### 7.3 Token 统计来源
- `chat`
- `map_generation`
- `movement_narration`

## 8. 错误与状态码
- `AREA_SUB_ZONE_NOT_FOUND` -> HTTP 404
- `AREA_INVALID_INTERACTION` -> HTTP 404
- `AREA_CLOCK_NOT_INIT` -> HTTP 409
- `session mismatch with current save` -> HTTP 409

## 9. 最小回归测试（已补）
文件：`backend/tests/test_area_logic.py`
- 时钟初始化 + 子区块移动耗时推进。
- 占位交互执行推进时钟。
- `discover_interactions` 去重策略。
- 发现交互 schema 校验。

## 10. 后续建议（M2）
- 交互执行从占位升级为可结算结果。
- 发现交互增加上下文约束（昼夜、场景状态、玩家状态）。
- 子区块路径移动可加入地形权重和事件打断。


