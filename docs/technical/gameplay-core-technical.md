# 核心玩法技术文档
更新时间: `2026-03-22`

## 1. 范围

本文档描述当前主聊天中的公开回合运行时，以及会阻塞主聊天的角色构筑入口，不覆盖独立 battle sandbox。

当前相关后端模块:
- `backend/app/services/public_turn_runtime.py`
- `backend/app/services/public_turn_resolution.py`
- `backend/app/services/public_turn_service.py`
- `backend/app/services/public_turn_state_store.py`
- `backend/app/services/public_turn_attack_service.py`

当前相关前端模块:
- `frontend/src/App.tsx`
- `frontend/src/components/CharacterBuildModal.tsx`
- `frontend/src/components/PublicTurnPanel.tsx`
- `frontend/src/components/PublicTurnInteractionModal.tsx`
- `frontend/src/components/PublicTurnAttackModal.tsx`
- `frontend/src/components/PublicTurnAttackDefenseModal.tsx`
- `frontend/src/components/PublicTurnDeathSaveModal.tsx`

## 2. 公开回合阶段

当前 `PublicTurnPhase` 包含:
- `idle`
- `initiative_declaration`
- `initiative_execution`
- `normal_advancement`
- `gm_push`
- `situation_advancement`
- `awaiting_player_interaction`
- `awaiting_player_reaction`
- `awaiting_player_opposed`
- `awaiting_player_attack_response`
- `awaiting_player_attack_defense`
- `awaiting_player_death_save`

其中 `awaiting_player_death_save` 是本次新增阶段，用于玩家在公开回合内进入死亡豁免后的专用暂停点。

## 3. 双状态模型

角色生命状态继续使用 `death_state.life_status`:
- `healthy`
- `dying`
- `stable`
- `dead`

角色行动状态新增 `role_action_status`:
- `free_action`
- `death_saving`
- `dead`
- `unable_to_act`

当前映射约束:
- 正常角色: `healthy + free_action`
- 进入死亡豁免: `dying + death_saving`
- 外部稳定成功: `stable + unable_to_act`
- 已死亡: `dead + dead`
- 未来控制类状态: `healthy + unable_to_act`

当前实现里，`death_saving` 和 `dead` 已接入公开回合；`unable_to_act` 仅接入 speech-only 限制，不承担完整 BUFF 系统职责。

## 4. HP 归零分流

### 4.1 玩家

玩家在公开回合中 `HP <= 0` 后:
- 若满足超额伤害即死，直接进入 `dead`
- 否则进入 `dying + death_saving`
- `SceneEvent.kind` 会追加 `player_entered_death_save`

### 4.2 队友 NPC

队友 NPC 在公开回合中 `HP <= 0` 后:
- 进入 `dying + death_saving`
- 不立即写入 `dead_npc_records`
- `SceneEvent.kind` 会追加 `team_npc_entered_death_save`

### 4.3 非队友 NPC

非队友 NPC 与遭遇临时 NPC 在当前规则下:
- `HP <= 0` 直接死亡
- `NpcRoleCard.state = "dead"`
- `role.profile.dnd5e_sheet.role_action_status = "dead"`
- 当前子区块写入 `dead_npc_records`
- `SceneEvent.kind` 追加 `sub_zone_dead_npc_recorded`

## 5. 玩家死亡豁免流程

### 5.1 被他人点名为目标时

若玩家当前 `role_action_status in {"death_saving", "unable_to_act"}`:
- 前端禁用 `action_text`
- 前端只允许输入 `speech_text`
- 后端不做文本检测，不再调用 AI 判断“是不是纯说话”
- 后端直接走确定性 speech-only 分支

其中:
- `death_saving` 会保持等待专用死亡豁免窗口
- `unable_to_act` 只会清空 `action_text`，继续常规结算

若 speech-only 状态仍提交 `action_text`:
- 后端直接抛 `PUBLIC_TURN_SPEECH_ONLY`

### 5.2 到玩家自己回合时

若玩家自己处于 `death_saving`:
- 玩家提交语言后，后端不再做 `planActionCheck`
- 公开回合直接暂停到 `awaiting_player_death_save`
- 返回专用 `death_save_prompt`
- 前端弹出 `PublicTurnDeathSaveModal`

### 5.3 死亡豁免判定

当前固定规则:
- `DC = 10`
- `d20 >= 10` 记 1 次成功
- `natural 1` 记 2 次失败
- `natural 20` 立即恢复 `1 HP`
- `3` 次成功后恢复 `1 HP`
- `3` 次失败后进入 `dead`

再受伤规则:
- 濒死中受到普通伤害: `death_save_failures + 1`
- 单次伤害达到 `ceil(max_hp * 0.5)` 视为重伤，直接死亡

前端死亡豁免分辨率:
- 新增 `POST /public-turn/death-save-check`
- 新增 `POST /public-turn/death-save-check/stream`
- SSE 新增 `death_save_required`

## 6. 队友 NPC 死亡豁免

队友 NPC 在 `death_saving` 时:
- 只能做 non-world 微动作与语言
- 不再产生 world-impact 行为
- 不再成为有效对抗输入方
- 到自己回合时由后端自动掷骰

## 7. 角色构筑入口

### 7.1 入口优先级

当前前端新增 `CharacterBuildModal`，优先级高于主聊天、地图、Debug 面板和普通调试弹窗。

当 `GET /character-build/state` 返回:
- `forced_entry=true`

前端行为:
- 直接打开玩家构筑模态
- 聊天输入区仍可见，但被模态完全遮挡
- 关闭按钮在强制建角场景下不可用

### 7.2 立绘工作流

当前固定链路:
1. `POST /character-build/media/upload` 或 `POST /character-build/media/generate`
2. 在前端选定 `selected_raw_asset_id`
3. `POST /character-build/media/remove-background`
4. 在 `立绘确认` 页面查看透明 PNG
5. `POST /character-build/media/finalize`
6. `POST /character-build/media/describe`

约束:
- 去背景是必经步骤
- 从确认页返回立绘定制时，不丢 prompt、参考图、上传图和候选图
- `describe` 仅接受 `bg_removed` 或 `final_portrait`

### 7.3 首个随从提示

当前玩家构筑成功后，若:
- `player_status=completed`
- `initial_companion_offer_seen=false`
- 当前队伍为空

前端会弹一次“是否继续创建首个随从”。

用户无论接受还是拒绝，都会调用:
- `POST /character-build/companion-offer`

这样保证该提示只出现一次。

相关事件:
- `team_npc_death_save_result`
- `team_npc_died`

## 7. 普通 NPC 死亡清理

当前子区块死亡 NPC 会被写入:
- `AreaSubZone.state.dead_npc_records`

每条记录至少包含:
- `role_id`
- `name`
- `death_at`
- `death_cause`
- `was_team_member`

运行时过滤位置:
- `world_service._visible_public_roles()`
- `public_turn_interaction_service._current_sub_zone_actor_candidates()`
- `public_turn_candidates.hidden_actor_rows()`
- `team_service._restore_area_presence()`

效果:
- 当前轮起就不再参与公开回合候选
- 不再作为互动目标
- 离开并重返子区块后不再恢复成可互动 NPC

## 8. 关键接口与模型

### 8.1 Schema 变更

`Dnd5eCharacterSheet` 新增:
- `role_action_status`
- `death_state`

`PublicTurnRound` 新增:
- `pending_death_save_prompt`

`PublicTurnResponse` / `PendingTurnContinueResponse` 新增:
- `death_save_prompt`

`PendingTurnState.status` 新增:
- `awaiting_player_death_save`

`SubZoneState` 新增:
- `dead_npc_records`

`BattleRollPrompt.roll_kind` / `BattleRollResolution.roll_kind` 新增:
- `death_save`
- `stabilize`

### 8.2 Scene Event 新增种类

当前至少支持:
- `player_entered_death_save`
- `player_death_save_result`
- `player_died`
- `team_npc_entered_death_save`
- `team_npc_death_save_result`
- `team_npc_died`
- `sub_zone_dead_npc_recorded`

## 9. 前端联动

当前前端新增:
- `death_save_prompt` 的 pending restore
- `speechOnly` 模式的互动 / 攻击回应弹窗
- `PublicTurnDeathSaveModal`
- 玩家 `role_action_status` 透传到 `PublicTurnPanel`

当前 UI 行为:
- `death_saving` / `unable_to_act` 时，主行动面板禁用行为输入
- 被点名响应时，互动与攻击回应弹窗禁用行为输入
- 死亡豁免通过专用 d20 弹窗完成，不复用 reaction prompt

## 10. AI 与确定性边界

本轮相关规则必须遵守:
- 前后端不做字符检测来猜测死亡、speech-only、攻击分类结果
- AI 侧只接收稳定枚举池，必须从允许值中选择
- 不做 fallback 文本兜底，不接受“半结构化 + 猜测修补”作为正常路径

当前确定性分支:
- `death_saving` / `unable_to_act` 的 speech-only 限制
- 非队友 NPC `0 HP -> dead`
- 队友 NPC `0 HP -> death_saving`
- 玩家回合进入死亡豁免窗口

## 11. 已验证项

当前已验证:
- 前端 `npm run build`
- `backend.tests.test_public_turn_runtime`

新增回归覆盖:
- 玩家被打到 `0 HP` 后进入 `death_saving`
- 玩家回合提交语言后返回 `death_save_prompt`
- `death_saving` 状态提交行为文本会抛 `PUBLIC_TURN_SPEECH_ONLY`
- 非队友 NPC 死亡后写入 `dead_npc_records`
- 队友 NPC `0 HP` 后进入 `death_saving` 而非直接死亡

## 附录: 玩家输入校验前置阶段

当前聊天提交流程在真正进入 `ActionCheck`、`continuePublicTurn` 或 `npcChat` 前，新增统一的玩家输入校验阶段。

当前已接入入口:
- `main_chat`
- `npc_chat`
- `teammate_chat`
- `public_turn_action`
- `public_turn_interaction_response`
- `public_turn_attack_response`
- `debug_panel`

前置阶段职责:
- 只校验带 `action_text` 的输入，纯 `speech_text` 直接跳过
- 先用 AI 规范化成单个、自身、无结果宣告的动作
- 再用后端确定性规则校验法术、武技、道具和行动状态
- 不推进时间
- 不执行检定
- 不写存档
- 不写 pending turn

当前前端行为:
- `accepted` 时直接采用 `normalized_action_text` / `normalized_speech_text`
- `needs_player_confirmation` 时弹统一确认模态
- 玩家可选择 `采用建议` 或 `返回修改`
- 采用建议后的再次提交只在前端内存中绕过一次，不持久化

新接口:
- `POST /api/v1/player-input/validate`
