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

## 10. Public Turn Baseline (2026-03-18)

- Mainline public scene progression now uses `public turn` instead of freeform `/chat`.
- Backend state machine phases:
  - `idle`
  - `initiative_declaration`
  - `initiative_execution`
  - `normal_advancement`
  - `situation_advancement`
  - `awaiting_player_reaction`
- Mainline entry points:
  - `POST /api/v1/public-turn/entry`
  - `POST /api/v1/public-turn/continue`
  - `POST /api/v1/public-turn/reaction-check`
  - `GET /api/v1/public-turn/state`
- Streaming entry points:
  - `POST /api/v1/public-turn/entry/stream`
  - `POST /api/v1/public-turn/continue/stream`
  - `POST /api/v1/public-turn/reaction-check/stream`
- Public turn now owns situation, relation, affinity/trust, reputation, environment risk, scene event, and archived sub-zone turn settlement.
- Public turn presentation is now split into:
  - `initiative_order` for left-pane initiative display
  - `settlement_entries` for structured per-actor action/check/consequence cards
  - `round_narration` for right-pane whole-round prose generated only after round completion
- Legacy `/api/v1/chat` remains for compatibility and debug, but mainline public scenes return `409 MAIN_CHAT_DISABLED_UNDER_PUBLIC_TURN` unless God Mode is active.

## Public Turn 4.2 Correction Note (2026-03-18)

- `entry(next_round)` now runs internal AI initiative judgment/execution before pausing at the player's `normal_advancement` slot.
- `entry(initiative)` now inserts the player into the initiative order and pauses only when the initiative cursor reaches the player.
- `PublicTurnContinueRequest` now accepts `player_action_check`.
- public-turn player submissions now settle relation / affinity / trust / reputation in the same action resolution pass.
- player-facing public-turn checks must be planned through `/api/v1/actions/check/plan` and rolled in the frontend before `/api/v1/public-turn/continue`.
- opposed public-turn checks are supported through `resolution_rule="opposed_actor"` and are used for direct physical conflict prompts with a resolvable NPC target.

## Public Turn Scheme A Runtime Note (2026-03-19)

- Public-turn runtime now executes AI-only progression as `segment`s instead of per-actor free-running loops.
- Each AI-only segment uses:
  - one batch planner pass
  - one batch narrator pass
- Embedded public-turn `action_check()` no longer calls `_ai_action_plan()` or `_ai_action_resolution_text()`.
- NPC/AI dice, opposed comparison, situation/reputation/relation/team settlement remain backend-deterministic.
- Stream routes no longer wait for the full public-turn request to finish before emitting output.
- The stream now emits after each resolved segment:
  - `settlement_entry`
  - `narrative_fragment_*`
  - `scene_event`
  - `impact`
- Player submissions and opposed resumes are folded into the same segment narration flow by seeding deterministic settlements before the next AI segment or `gm_push`.
- Public-turn actor typing now accepts `encounter_temp_npc` end-to-end in initiative declarations, initiative order, settlements, and frontend state typing.

## Public Turn Interaction Technical Note (2026-03-19)

- New phase:
  - `awaiting_player_interaction`
- New backend / frontend structures:
  - `PublicTurnInteractionPrompt`
  - `PublicTurnInteractionResponseSubmission`
- `PublicTurnRound` now stores `pending_interaction_prompt` so interaction pauses survive save sync and restore without using `PendingTurnState`.
- `PublicTurnResponse` now carries `public_interaction_prompt`.
- `PublicTurnContinueRequest` now accepts `player_interaction_response`.
- `PublicTurnSegmentActorDirective` now carries structured interaction metadata:
  - `interaction_target_actor_id`
  - `interaction_target_name`
  - `interaction_target_kind`
  - `interaction_kind`
  - `interaction_requires_response`
  - `target_response_action_summary`
  - `target_response_speech_text`
  - `consent_state`
  - `resolution_mode`
- Public-turn target resolution is now structured-first:
  - explicit target role id in prompt
  - structured `target_label`
  - limited text fallback
  - no automatic player lock merely because the prompt text mentions the player
- Directed non-attack interactions now use deterministic consent classification:
  - `accepted`
  - `rejected`
  - `ambiguous`
  - `not_applicable`
- Resolution routing is now:
  - `attack` -> existing attack / reaction flow
  - targeted non-attack + `rejected` -> `opposed_actor`
  - targeted non-attack + `accepted|ambiguous` -> `static_dc` or no-roll settlement
- `PublicTurnSettlementEntry` now records:
  - `interaction_target_name`
  - `interaction_resolution`
  - target-side response action / speech for both non-opposed and opposed interaction settlements
- Stream routes now emit `interaction_required` when a player-targeted interaction pause is reached.
- Blocking gameplay modals now support minimize / restore in the frontend while preserving state; minimized workflows still keep chat submission locked.

## Public Turn Settlement And GM Push Technical Note (2026-03-20)

- Public-turn presentation no longer depends on AI stitched narration output.
- `PublicTurnPresentation.round_narration`, `accumulated_narration`, and `narrative_entries` are now rebuilt deterministically from `settlement_entries`.
- The deterministic formatter uses settlement order and only includes visible actor content:
  - actor name
  - action summary
  - speech text
  - opposed / interaction target response text
- Actor settlements no longer surface GM summary text; `gm_resolution_summary` stays empty on actor entries for compatibility.
- `PublicTurnSettlementEntry` now distinguishes:
  - `entry_kind="actor"`
  - `entry_kind="gm_push"`
- `PublicTurnGmPushResult` is attached to:
  - `PublicTurnSettlementEntry.gm_push_result`
  - `PublicTurnRound.gm_push_result`
  - `PublicTurnPresentation.gm_push_result`
- Round-end GM push is now a dedicated backend step:
  1. aggregate impacts
  2. roll backend `1d6`
  3. classify outcome as `none | environment_change | extra_npc_intervention`
  4. call AI once for environment / atmosphere text
  5. append one GM settlement card
- `d6=5` raises the round environment risk and emits `public_turn_environment_update`.
- `d6=6` spawns a persistent scene NPC, appends its immediate same-round settlement, and defers its normal initiative participation to later rounds.
- `PublicTurnEntryType.INITIATIVE` now uses full initiative candidate declarations instead of hostile-text filtering, so the player is not auto-first unless `god_override` forces it.
- Public-turn actor planning / interaction response paths no longer call NPC fallback output helpers.
- Public-turn AI payload normalization now allows partial output; missing fields remain empty instead of causing fallback prose generation.

## Public Turn Reaction Ownership Technical Note (2026-03-20 v3)

- Player-action reactions are now a dedicated post-settlement layer and no longer reused by non-player actor turns.
- `PublicTurnRelationDelta` now carries:
  - `reaction_action`
  - `reaction_speech`
  - compatibility `reaction_text`
- `PublicTurnTeamAffinityDelta` now carries:
  - `reaction_action`
  - `reaction_speech`
  - compatibility `reaction_text`
- Only `resolve_player_submission(...)` may populate:
  - `relation_deltas`
  - `team_affinity_deltas`
- `_finalize_ai_actor_turn(...)` now leaves both lists empty for non-player settlements.
- Zone reputation is now actor-gated:
  - allowed for `player`
  - allowed for `team`
  - forced to `0` for all other actor kinds
- Deterministic narration formatting now treats player settlements specially by appending AI NPC/team reaction fragments after the player action/speech.
- Stream emission still uses settlement-order fragments, but now falls back to direct settlement formatting if a compatible `narrative_entry` is not already present in the response payload.
## 2026-03-20 Public-Turn Target / Addressee / Contest Routing

- Public-turn actor directives and settlements now distinguish:
  - action target
  - speech target
- Public-turn targeted actor actions no longer use `attack -> player_reaction` as the primary path.
- New routing rule:
  - role-to-role targeted action -> interaction assessment
  - player target -> pause for player interaction response
  - non-player target -> AI target response
  - source/target actions -> contest classification -> `opposed_actor` or `static_dc` / `none`
- `player_reaction` remains on the public-turn path only for non-actor hazards such as environment or GM push consequences.
- Player post-action reaction payloads now carry:
  - `reaction_tone`
  - `reaction_focus_actor_name`
  - `reaction_speech_target_name`
- Server-side tone clamps prevent warning / hostile reaction text from yielding large positive relation or affinity deltas.
- Deterministic narration formatter now emits target-aware and addressee-aware fragments for settlements and pause previews.
## 2026-03-20 Public Turn Interaction v7

- `PublicTurnInteractionPrompt` no longer carries `stakes_summary`.
- Public-turn interaction routing now has a hard invariant:
  - `target_actor_*` in the prompt must match the resolved `action_target_*`
  - if planner output conflicts with the resolved action target, runtime ignores the planner pause suggestion
- `speech_target_*` is now presentation-only:
  - used by settlement / narration formatting
  - never used to select the responding actor
- Public-turn interaction now records world-impact classification:
  - `source_world_impact_type`
  - `target_response_world_impact_type`
  - `interaction_exchange_kind`
  - `alternation_depth`
  - `target_response_kind`
- `non_world_exchange` never emits:
  - action check
  - opposed prompt
- Alternation flow is supported once per interaction:
  - initial `non_world` source action
  - target-side `world` response aimed at original source
  - source/target swap
  - no second alternation
- Player interaction submission now supports:
  - `response_kind="explicit_response"`
  - `response_kind="no_action"`
- `no_action` is resolved backend-side as:
  - empty action/speech
  - `world_impact_type=non_world`
  - valid terminal interaction response
- Runtime no longer clears the pending interaction prompt before validating / resolving the player's response, so invalid reverse targeting does not destroy the pending pause state.
