# Role Technical Addendum

更新日期：2026-03-08

## NPC 会话状态
- NPC 不再只依赖原始聊天历史，还会维护结构化 `conversation_state`。
- 当前已保存字段：
  - `current_topic`
  - `last_open_question`
  - `last_npc_claim`
  - `last_player_intent`
  - `last_referenced_entity`
  - `last_scene_mode`

## 公开区域点名 NPC
- 玩家在公开区域明确点名某个当前可见 NPC 时：
  - 该 NPC 会按“公开目标回复”规则回一轮
  - 仍然停留在主聊天，不自动切入单聊
  - 回复会写入该 NPC 的 `dialogue_logs`
  - `context_kind=public_targeted`

## 旁观反应与队友反应
- 在场可见 NPC 可产生 `public_bystander_reaction`
- 队友可产生 `team_public_reaction`
- 这些反应都属于公开场景层，而不是私聊层
