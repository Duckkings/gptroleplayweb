# 队伍系统技术文档

更新日期：`2026-03-09`

## 1. 范围
本文描述队友加入、离队、队伍聊天、公开场景中的队友行动，以及队友欲望/故事在当前实现中的行为。

## 2. 当前数据结构

### 2.1 `TeamMember`
- `role_id`
- `name`
- `origin_zone_id`
- `origin_sub_zone_id`
- `joined_at`
- `affinity`
- `trust`
- `join_source`
- `join_reason`
- `status`
- `last_reaction_at`
- `last_reaction_preview`

### 2.2 `TeamReaction`
- `reaction_id`
- `member_role_id`
- `member_name`
- `trigger_kind`
- `content`
- `affinity_delta`
- `trust_delta`
- `created_at`

### 2.3 `TeamState`
- `version`
- `members`
- `reactions`
- `updated_at`

## 3. 队友与角色卡复用
- 队友不使用独立的 companion schema
- 当前继续直接复用 `NpcRoleCard`
- 因此队友天然拥有：
  - 完整角色底座
  - 背包和装备位
  - 对话日志
  - desires
  - story_beats

## 4. 入队与离队

### 4.1 入队
服务位置：
- `backend/app/services/team_service.py::invite_npc_to_team(...)`

当前流程：
1. 校验 NPC 合法性
2. 结合关系和 AI 决策决定是否接受
3. 写入 `team_state.members`
4. 把角色状态改为 `in_team`
5. 调用 `_ensure_npc_role_complete(...)` 补齐 desire/story

### 4.2 离队
服务位置：
- `backend/app/services/team_service.py::leave_npc_from_team(...)`

当前行为：
- 普通队友离队后回到原区域
- debug 队友离队后可直接从可见队伍状态中移除
- 队友负反馈过低时仍可能自动离队

## 5. 队伍聊天

### 5.1 接口
- `POST /api/v1/team/chat`

### 5.2 当前行为
- 队伍聊天会推进世界时间
- 每个当前队友返回一条结构化短回应
- 玩家发言和队友回应都会写入对应角色的 `dialogue_logs`
- 结果同步写入：
  - `team_state.reactions`
  - `game_logs(kind=team_chat)`

## 6. 队友欲望与故事

### 6.1 补齐规则
- 队友入队时会自动补齐 story beats
- 旧档队友在同步队伍状态时也会补齐

### 6.2 触发方式
队友的 desire/story 目前可以在以下地方浮出：
- 公开场景
- 队伍聊天
- 到达新子区块
- 遭遇后续

### 6.3 当前表现形态
- desire 可以形成公开事件或普通 quest 草案
- story beat 默认形成 `companion_story_surface` 或队伍话题
- 不会强行打断主聊天进入模态

## 7. 公开场景中的队友行动
- 公开场景导演器会把队友纳入候选行动体
- 有 surfaced desire/story 的队友拥有更高优先级
- 队友行动当前也会影响：
  - 子区块声望
  - 角色关系
  - 活跃遭遇局势值

## 8. 前端联动
- `frontend/src/components/TeamPanel.tsx`
- `frontend/src/components/RoleProfileModal.tsx`

当前前端支持：
- 查看当前队伍
- 发起队伍聊天
- 查看 desire/story 摘要
- 查看队友完整资料
- 打开队友背包与互动入口

## 9. 当前限制
- 队伍聊天仍是每名队友独立短回应，不是复杂群聊编排器
- 队友故事还没有独立的 companion quest UI
- 当前没有完整的战术编队、站位和共享行动点系统

## 10. 回归测试
- `backend/tests/test_team_service.py`
- `backend/tests/test_role_system.py`
- `backend/tests/test_inventory_interaction.py`

