# AI 工具协议

更新日期：`2026-03-09`

## 1. 目标
- 让模型先读取真实状态，再生成文本。
- 让所有关键玩法写操作都经过后端校验、落库和审计。
- 让主聊天中的玩法行为优先由后端路由，而不是依赖模型“记得去调工具”。

## 2. 当前总流程
1. 前端调用 `/api/v1/chat` 或 `/api/v1/chat/stream`
2. 后端先运行 `route_main_turn_intent(...)`
3. 若未命中确定性动作，再向模型暴露工具 schema
4. 模型通过 `tool_call` 读取或写入状态
5. 后端执行工具，记录 `tool_events`
6. 模型返回最终 GM 文本
7. 主聊天链路继续推进公开场景和遭遇

## 3. 当前读取工具
- `get_player_state`
- `get_story_snapshot`
- `get_entity_index`
- `get_consistency_status`
- `get_npc_knowledge`
- `get_team_state`
- `get_role_inventory`
- `get_map_index`
- `get_game_logs`
- `get_current_sub_zone`
- `get_quest_state`
- `get_fate_state`
- `get_area_reputation`
- `get_role_drives`
- `get_public_scene_state`

## 4. 当前写入工具
- `generate_zone`
- `move_to_zone`
- `move_to_sub_zone`
- `discover_interactions`
- `execute_interaction`
- `run_consistency_check`
- `team_invite_npc`
- `team_remove_npc`
- `team_chat`
- `team_generate_debug_member`
- `player_add_item`
- `player_equip_item`
- `player_apply_buff`
- `player_adjust_resource`
- `role_set_relation`
- `player_set_trait`
- `inventory_mutate`
- `inventory_interact`
- `encounter_act`
- `encounter_escape`
- `encounter_rejoin`
- `quest_track`
- `quest_evaluate`

## 5. 新增读取工具约定

### 5.1 `get_area_reputation`
用途：
- 读取当前或指定 `sub_zone_id` 的声望

关键字段：
- `current_entry`
- `entries`
- `score`
- `band`
- `recent_reasons`

### 5.2 `get_role_drives`
用途：
- 读取指定角色、队伍范围或当前子区块范围内的 desire/story 摘要

关键字段：
- `scope`
- `items[*].role_id`
- `items[*].desires`
- `items[*].story_beats`

### 5.3 `get_public_scene_state`
用途：
- 读取当前公开场景事实，避免模型误判当前场上角色、声望或遭遇

关键字段：
- `sub_zone_id`
- `reputation`
- `visible_roles`
- `surfaced_desires`
- `surfaced_story_beats`
- `candidate_actors`
- `active_encounter_id`

## 6. 主聊天中的调用策略

### 6.1 先路由后工具
以下动作不应再依赖模型自由判断：
- 明确移动
- 明确物品装备/观察/使用
- 明确邀请/移除队友
- 明确遭遇逃离/重返/行动
- 明确点名当前可见 NPC
- `passive_turn`

### 6.2 仍适合工具或模型的情况
- 模糊叙事
- 无合法实体匹配的表达
- 纯情绪/气氛/闲聊
- 需要先查状态再决定是否行动的复杂叙事

## 7. 审计规则
- 所有工具执行都必须进入 `tool_events`
- 所有关键玩法变化仍必须进入 `game_logs`
- 公开场景和遭遇进展不依赖 `tool_events` 向前端展示，而是通过 `scene_events`

## 8. Prompt Keys
当前新增并强制注册的 key：
- `scene.actor.intent.user.v1`
- `role.desire.seed.user.v1`
- `role.desire.surface.user.v1`
- `companion.story.seed.user.v1`
- `companion.story.surface.user.v1`
- `encounter.outcome.package.user.v1`
- `reputation.behavior.user.v1`

## 9. 当前限制
- 模型不能直接写 desire/story 的持久化状态
- 模型不能直接宣告检定结果
- 模型不能直接宣告遭遇奖励落地
- 主聊天不会直接接受 quest accept/reject 作为自由文本写入动作

## 10. 回归测试
- `backend/tests/test_chat_route_scene_rendering.py`
- `backend/tests/test_action_check_routes.py`
- `backend/tests/test_npc_chat_routes.py`
- `backend/tests/test_prompt_registry.py`

## 11. Public Turn Runtime Notes (2026-03-18)

- Mainline public scene orchestration is no longer driven by freeform `/chat`.
- `public turn` uses deterministic backend state plus optional AI actor declaration / action helpers.
- Public-turn output is now split by contract:
  - structured initiative / settlement data goes through API fields and SSE events
  - prose round narration is generated separately at round end and must not include dice/DC/value math
- The runtime still reuses existing public-scene candidate selection, reaction staging, and encounter settlement helpers where practical.
- New SSE event family:
  - `phase`
  - `turn_state`
  - `narration_delta`
  - `scene_event`
  - `impact`
  - `reaction_check_required`
  - `reaction_check_resumed`
  - `round_completed`
  - `error`
  - `end`
- New scene event kinds:
  - `public_turn_phase`
  - `public_turn_initiative`
  - `public_turn_actor_action`
  - `public_turn_actor_resolution`
  - `public_turn_situation`
  - `public_turn_round_end`
  - `public_turn_relation_update`
  - `public_turn_team_update`
  - `public_turn_environment_update`

## Public Turn Check Planning (2026-03-18)

- `/api/v1/actions/check/plan` now accepts `source_context="public_turn"`.
- action check planning / execution now expose:
  - `resolution_rule`
  - `target_role_id`
  - `target_name`
  - `target_actor_kind`
  - `target_ability_used`
  - `target_ability_modifier`
- public-turn direct physical conflict prompts can resolve as `opposed_actor`.
- `/api/v1/public-turn/continue` now accepts `player_action_check`, allowing the frontend roll modal to submit the forced player d20 back into public-turn resolution.
- Public-turn stream events now additionally expose:
  - `initiative_order`
  - `settlement_entry`
  - `round_narration_delta`

## Public Turn Segment Dual-Phase Note (2026-03-19)

- Public turn no longer treats each NPC settlement as an independent LLM narration unit.
- Current contract for an AI-only segment is:
  1. planner returns ordered actor directives for the segment
  2. backend performs all dice / opposed / state settlement locally
  3. narrator returns ordered prose fragments for the resolved anchors
- `PublicTurnSegmentPlan`, `PublicTurnSegmentActorDirective`, `PublicTurnSegmentBoundary`, `PublicTurnNarrationInputItem`, and `PublicTurnNarrationFragmentBatch` are internal backend-only parsing models.
- These internal models are not exposed as public API payloads and are not stored as new save shards.
- `source_context="public_turn"` plus `resolution_context="embedded"` now guarantees that:
  - no extra `_ai_action_plan()` call is made inside `action_check()`
  - no extra `_ai_action_resolution_text()` call is made inside `action_check()`

## Public Turn AI Contract Revision (2026-03-20)

- Public-turn actor execution no longer uses fallback action / speech / reaction text when the model omits fields.
- The public-turn actor contract is now:
  - one actor action call
  - partial payload allowed
  - empty fields preserved as empty strings
  - fully empty actor output allowed
- Public-turn interaction target auto-response follows the same rule:
  - AI output only
  - no fallback response text
  - empty response is treated as empty consent input
- Public-turn continuous narration is no longer an AI protocol responsibility.
- AI still participates in two places:
  - actor / interaction action generation
  - single GM push environment / atmosphere description at round end
- Round-end GM push AI output is descriptive only.
- The GM push outcome itself is backend-deterministic through `1d6`:
  - `1-4` none
  - `5` environment change
  - `6` extra persistent scene NPC intervention
- `PublicTurnEntryType.INITIATIVE` no longer relies on hostile prompt wording to decide which actors enter initiative declaration generation.

## Public Turn Reaction AI Contract Revision (2026-03-20 v3)

- Public-turn post-player reactions are now AI-only on the public-turn path.
- NPC reaction contract:
  - input: player action text, settlement summary, NPC identity/context, relation delta hint
  - output JSON: `reaction_action`, `reaction_speech`
- Team reaction contract:
  - input: player action text, settlement summary, teammate identity/context
  - output JSON: `reaction_action`, `reaction_speech`, `affinity_delta`, `trust_delta`
- `reaction_action` is constrained to expressive-only output and is sanitized server-side; illegal mechanical verbs are dropped.
- No fallback sentence generator is used when these reaction calls return empty output.
- Empty reaction text is valid and must not block the rest of settlement or narration generation.
## 2026-03-20 Public-Turn AI Contract Addendum

- Public-turn actor action payloads now treat `target_label` as the action target only.
- New optional actor payload field:
  - `speech_target_label`
- Public-turn actor prompts must allow action target and speech addressee to diverge.
- Public-turn player-follow-up reaction prompts now require conflict anchoring context:
  - player action target
  - current primary aggressor
  - current primary target
  - prior settlement excerpt
  - scene conflict summary
- Public-turn NPC reaction JSON now supports:
  - `reaction_action`
  - `reaction_speech`
  - `reaction_tone`
  - `reaction_focus_target_name`
  - `reaction_speech_target_name`
  - `reaction_scope`
- Public-turn team reaction JSON now supports the same fields plus `affinity_delta` and `trust_delta`.
- Empty reaction output remains valid and must not trigger fallback text generation.
## 2026-03-20 Public-Turn Interaction AI Contract v7

- Public-turn interaction prompts no longer include a risk / stakes parameter.
- Public-turn actor action payload must now distinguish:
  - `target_label` for the action target
  - `speech_target_label` for the speech addressee
  - `world_impact_type` for `non_world | world`
- `speech_target_label` may differ from the action target, but it must not affect routing.
- Player interaction responses now use a dedicated lightweight classifier that returns:
  - `world_impact_type`
  - `target_label`
  - `speech_target_label`
- Player `response_kind="no_action"` bypasses AI classification and is forced to:
  - empty action
  - empty speech
  - `world_impact_type=non_world`
- Alternation is only legal when a target-side `world` response points back at the original source actor.
- If AI produces a reverse `world` response aimed at a third party, runtime must not open a new interaction branch from that payload.

## 2026-03-21 Public-Turn Delta Hint Addendum

- Public-turn actor action payloads may now include:
  - `situation_delta_hint`
  - `reputation_delta_hint`
- `reputation_delta_hint` is interpreted as direct public reputation impact in the current zone and is clamped to `-3..3`.
- Segment planner actor overrides may also return `reputation_delta_hint`.
- Once a player-facing `interaction` or `opposed` pause is created, runtime now preserves the actor-side structured hints through:
  - `PublicTurnInteractionPrompt.source_situation_delta_hint`
  - `PublicTurnInteractionPrompt.source_reputation_delta_hint`
  - `PublicTurnOpposedPrompt.source_situation_delta_hint`
  - `PublicTurnOpposedPrompt.source_reputation_delta_hint`
- Resume-time settlement must consume these structured hints directly instead of re-deriving deltas from free text.

## 2026-03-20 Enum Contract / Repair Policy

- AI control fields now follow a shared protocol contract layer.
- Backend prompts must explicitly downlink allowed stable ids for control enums.
- Backend no longer does semantic guesswork for illegal control enums.
- Shared control-enum behavior is now:
  1. parse JSON
  2. validate enum membership only
  3. non-public-turn flows repair once inline with the same model
  4. second failure returns `AI_PROTOCOL_REPAIR_FAILED`
- Public-turn is the only flow that stages first-pass enum violations into a user-visible repair state instead of repairing inline.
- Shared error codes:
  - `AI_CONFIG_REQUIRED`
  - `AI_PROVIDER_CALL_FAILED`
  - `AI_PROTOCOL_ENUM_INVALID`
  - `AI_PROTOCOL_REPAIR_FAILED`
- Public-turn targeted actor context is now standardized as prompt-only helper text:
  - action target form: `{actor}对{target}的行为：...`
  - self action form: `{actor}自己的行为：...`
  - speech target form: `{actor}对{speech_target}说：...`
  - untargeted speech form: `{actor}说：...`
