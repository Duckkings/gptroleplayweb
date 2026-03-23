# AI 工具协议

更新时间：`2026-03-23`

## 遭遇相关 prompt key
- `encounter.generate.user.v3`
- `encounter.step.user.v4`
- `encounter.public_turn.summary.user.v1`
- `team.public.reaction.user.v3`
- `public.turn.non_world_route.user.v1`

## 当前遭遇协议
- AI 生成遭遇时必须返回：
  - `goal`
  - `secret`
  - `scene_summary`
  - `temporary_npcs[].knows_secret`
- AI 推进遭遇时必须把 `scene_summary` 当作唯一公开局势摘要。
- AI 不能再输出后台推进、逃离或重返相关设计字段作为现行协议。

## 公开回合非世界行为路由
- AI 需要返回：
  - `public_turn_interaction_kind`
  - `notice_state`
  - `resolution_mode`
  - `ability_used`
  - `followup_ability_used`
  - `followup_dc`
  - `followup_check_task`

## 队友公开反应
- 队友 prompt 可见：
  - `encounter_goal`
  - `scene_summary`
- 队友 prompt 不可见：
  - `secret`

## 工具退役
- `encounter_escape`
- `encounter_rejoin`

## get_active_encounters / 前端公开数据
- 公开返回只包含 active / queued 视角
- 公开返回不包含 `secret`、`knows_secret`、`latest_outcome_summary`、`background_tick_count`

## Resource Tools
- `get_role_capability_snapshot` returns `available_abilities[].definition_id` so the AI can look up the exact spell / war-art row in the local CSV tables.
- `actor_adjust_resource` can consume or recover a spell slot or martial point for either `player` or `role`.
- For spells and war arts, prefer passing `resource_definition_id` instead of relying on display names.
