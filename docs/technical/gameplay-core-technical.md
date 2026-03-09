# 核心玩法技术文档

更新日期：`2026-03-09`

## 1. 范围
本文描述当前版本的主聊天、公开场景、遭遇、任务/命运阻塞规则，以及前后端之间的主流程约束。

核心目标只有一条：玩家在主聊天中做出的明确玩法行为，必须由后端真实落地，而不是只由 AI 写成一段看似发生过的文本。

## 2. 当前核心流程

### 2.1 主聊天回合
`POST /api/v1/chat` 与 `POST /api/v1/chat/stream` 都走同一条主链路：
1. 读取当前 `SaveFile`
2. 解析最后一条玩家输入
3. 调用 `route_main_turn_intent(...)`
4. 若命中确定性玩法动作，则先执行后端真实逻辑
5. 若未命中，进入模型主聊天与工具调用
6. 推进公开场景导演器
7. 推进活跃遭遇或后台遭遇
8. 写入 `tool_events`、`scene_events`、`game_logs`
9. 返回 `reply.content`

### 2.2 后端路由优先原则
`backend/app/services/chat_service.py::route_main_turn_intent(...)` 当前优先处理：
- `move_to_zone`
- `move_to_sub_zone`
- `inventory_mutate`
- `inventory_interact`
- `team_invite_npc`
- `team_remove_npc`
- `encounter_escape`
- `encounter_rejoin`
- `encounter_act`
- 当前可见 NPC 的公开点名
- `passive_turn`

命中条件固定为：
- 有明确动词
- 有合法实体匹配
- 当前状态允许执行

否则回落给模型自由叙事或工具决策。

## 3. 公开场景导演器

### 3.1 服务位置
- `backend/app/services/public_scene_service.py`
- `backend/app/services/world_service.py::advance_public_scene_in_save(...)` 只是兼容入口，实际逻辑已转发到导演器服务

### 3.2 固定顺序
每个主聊天回合的公开区域推进顺序固定为：
1. 玩家动作
2. GM 直接反馈
3. 导演器选择最多 4 名非玩家行动体逐个行动
4. 其余角色合并为 crowd summary

### 3.3 行动体优先级
- 被玩家点名的当前可见 NPC
- 当前活跃遭遇锚点角色
- 本轮刚浮出 desire/story 的队友
- 与玩家动作直接相关的队友或 NPC
- 其余旁观者

### 3.4 输出约束
- AI 的行动意图只允许输出结构化 actor intent JSON
- 检定结果由后端完成
- 公开动作只能写入 `scene_events`、`SubZoneChatTurn.events`、`game_logs`
- 不允许直接拼进 `reply.content`

### 3.5 当前 scene event
当前主聊天会把以下公开事件送到前端：
- `public_actor_resolution`
- `role_desire_surface`
- `companion_story_surface`
- `reputation_update`
- `encounter_situation_update`
- `encounter_started`
- `encounter_progress`
- `encounter_resolution`

同时仍保留兼容用事件：
- `public_targeted_npc_reply`
- `public_bystander_reaction`
- `team_public_reaction`

## 4. 阻塞规则

### 4.1 模态优先级
固定为：
1. `Quest/Fate`
2. `Encounter`
3. 主聊天

### 4.2 不变规则
- 所有模态都会阻塞聊天输入
- Fate quest 仍是 accept-only
- 普通 quest 仍允许 accept/reject，但走模态
- `quest accept/reject` 仍不开放给主聊天自由文本直接完成

## 5. 主聊天与遭遇的联动

### 5.1 活跃遭遇存在时
- 主聊天回合可能被路由为 `encounter_act`
- 公开场景中的 NPC/队友行动也可以修改当前 `situation_value`
- 主聊天结束后仍会检查活跃遭遇是否需要继续推进或结算

### 5.2 被遭遇打断时
- NPC 单聊会被强制切回主聊天
- 遭遇结果通过 scene events 和 encounter lane 展示
- 结算后不会自动回到之前的 NPC 单聊上下文

## 6. API 总览

### 6.1 主链路
- `POST /api/v1/chat`
- `POST /api/v1/chat/stream`

### 6.2 公开状态读取
- `GET /api/v1/scene/public-state`
- `GET /api/v1/reputation/current`
- `GET /api/v1/role-drives`

### 6.3 遭遇
- `GET /api/v1/encounters/pending`
- `GET /api/v1/encounters/history`
- `POST /api/v1/encounters/check`
- `POST /api/v1/encounters/{encounter_id}/present`
- `POST /api/v1/encounters/{encounter_id}/act`
- `POST /api/v1/encounters/{encounter_id}/escape`
- `POST /api/v1/encounters/{encounter_id}/rejoin`
- `GET /api/v1/encounters/debug/overview`

## 7. 前端联动点
- `frontend/src/App.tsx` 负责主聊天、scene events、encounter lane 和模态优先级
- `frontend/src/components/SubZoneContextPanel.tsx` 渲染公开事件
- `frontend/src/components/EncounterLane.tsx` 与 `frontend/src/components/EncounterModal.tsx` 渲染局势值、趋势和结果摘要
- `frontend/src/components/PlayerPanel.tsx` 渲染当前子区块声望
- `frontend/src/components/TeamPanel.tsx` 与 `frontend/src/components/RoleProfileModal.tsx` 渲染欲望与故事

## 8. 当前限制
- 公开场景导演器是叙事轮值器，不是完整战斗先攻系统
- `crowd_summary` 目前只做摘要，不单独拥有检定和关系结算
- 队友故事默认只是公开话题或队伍聊天入口，不强制升级成任务

## 9. 回归测试
- `backend/tests/test_chat_route_scene_rendering.py`
- `backend/tests/test_action_check_routes.py`
- `backend/tests/test_npc_chat_routes.py`
- `backend/tests/test_role_system.py`
- `backend/tests/test_encounter_service.py`

