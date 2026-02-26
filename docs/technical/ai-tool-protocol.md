# AI 工具协议（Tool Protocol）

## 设计来源
- docs/design/gamedesign/gamedesign.md
- docs/design/gamedesign/areadesign.md

本文档定义后端开放给 AI 的“工具调用协议”，用于在聊天流程中触发业务能力（如生成区块、移动玩家、读取玩家数据），并将结果回写到前端状态与存档。

## 目标

- 让玩家可以在聊天中用自然语言触发地图/日志等业务能力。
- 保持 AI 不直接访问本地 API，由后端代理执行工具调用。
- 保证工具调用参数可校验、可追踪、可回滚。

## 总体流程

1. 前端发送聊天请求到后端（`/api/v1/chat`）。
2. 后端调用模型，并附带工具定义（tools schema）。
3. 模型返回 `tool_call`（函数名 + JSON 参数）。
4. 后端校验参数并执行对应业务函数。
5. 后端将工具结果作为 `tool` 消息回注给模型，获取最终自然语言回复。
6. 后端返回：
   - `reply`（GM 文本）
   - `tool_events`（本次工具执行摘要）
   - `state_patch`（前端应刷新的状态片段，可选）

## 工具调用约束

- AI 不能直接调用 HTTP API，只能返回工具调用意图。
- 后端必须做 JSON Schema 校验；失败则返回工具错误并要求模型重试。
- 所有写操作工具默认要求 `session_id` 存在且一致。
- 工具执行必须记录日志（调用时间、参数、结果、错误、token 使用）。

## 工具定义（首批）

### `generate_zone`

用途：生成一个或多个新地图区块并写入当前存档。

输入参数：

```json
{
  "session_id": "sess_xxx",
  "world_prompt": "剑与魔法世界",
  "count": 1,
  "near_player": true
}
```

参数说明：

- `session_id`: 会话 ID，必填。
- `world_prompt`: 区块生成约束提示词，必填。
- `count`: 生成数量，默认 `1`，范围建议 `1-3`。
- `near_player`: 是否要求靠近玩家当前位置，默认 `true`。

返回结果：

```json
{
  "ok": true,
  "generated": 1,
  "zones": [
    {
      "zone_id": "zone_120_-80_0",
      "name": "碎石坡驿道",
      "x": 120,
      "y": -80,
      "z": 0,
      "description": "......",
      "tags": ["ai", "generated"]
    }
  ]
}
```

失败结果：

```json
{
  "ok": false,
  "error_code": "INVALID_AI_JSON",
  "message": "模型返回结构不完整"
}
```

### `move_to_zone`

用途：将玩家移动到目标区块，计算耗时，生成移动日志。

输入参数：

```json
{
  "session_id": "sess_xxx",
  "to_zone_id": "zone_120_-80_0"
}
```

返回结果：

```json
{
  "ok": true,
  "new_position": { "x": 120, "y": -80, "z": 0, "zone_id": "zone_120_-80_0" },
  "duration_min": 12,
  "movement_log_id": "log_1730000000"
}
```

### `get_player_state`

用途：读取玩家静态/运行时数据，辅助叙事或决策。

输入参数：

```json
{
  "session_id": "sess_xxx"
}
```

返回结果：

```json
{
  "ok": true,
  "player_static_data": {
    "player_id": "player_001",
    "name": "玩家",
    "move_speed_mph": 4500
  },
  "player_runtime_data": {
    "session_id": "sess_xxx",
    "current_position": { "x": 0, "y": 0, "z": 0, "zone_id": "zone_0_0_0" }
  }
}
```

## 错误码建议

- `INVALID_ARGS`: 参数缺失或类型错误。
- `SESSION_MISMATCH`: 会话与当前存档不一致。
- `ZONE_NOT_FOUND`: 目标区块不存在。
- `AI_TIMEOUT`: 上游模型超时。
- `INVALID_AI_JSON`: 上游模型返回不可解析结构。
- `INTERNAL_ERROR`: 未分类内部错误。

## 安全与风控

- 工具白名单：只允许文档中注册的工具被调用。
- 参数限流：对 `count`、文本长度、调用频率做限制。
- 幂等策略：同一 `request_id` 的重复调用只执行一次。
- 审计字段：`session_id`、`tool_name`、`args_hash`、`duration_ms`、`status`。

## 前端联动建议

- 聊天响应增加 `tool_events` 字段，显示“AI 调用了什么工具”。
- 若 `tool_events` 包含地图变更，前端自动刷新地图快照与二维图。
- 若工具失败，聊天区显示错误摘要，不中断会话。

## 版本

- 文档版本：`v0.1`
- 状态：草案，可随实现迭代更新

