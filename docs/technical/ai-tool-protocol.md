# AI 工具协议
更新时间: `2026-03-22`

## 1. 总原则

当前项目的公开回合 AI 协议遵守三条硬约束:
- 前后端不做字符检测，不靠关键词猜动作类型、目标或状态。
- 只把稳定枚举池传给 AI，由 AI 在允许值内选择。
- 不做 fallback，不接受 AI 原生输出之外的推测修补路径。

若输出不满足 schema:
- 进入协议修复流程
- 或直接失败
- 不允许“猜一个最像的值然后继续跑”

## 2. 当前公开回合相关 AI 协议

### 2.1 `attack_assessment`

输入:
- 行动摘要
- 语言摘要
- 场景上下文
- 可见角色列表
- 模板库命中信息

输出必须使用稳定枚举:
- `attack_kind = ordinary_action | targeted_attack | aoe_attack`
- `attack_basis = weapon | spell | other`
- `attack_area_shape = none | sphere | cone | line | burst | emanation`
- `self_target_policy`
- `attack_ability_used`

禁止:
- 返回自由文本类型名再让前后端二次猜测
- 让前后端靠关键字判断是否是 AOE

### 2.2 `aoe_target_selection`

输入:
- AOE 评估结果
- 当前可见目标
- 隐藏目标候选

输出:
- `threatened_target_actor_ids`
- `revealed_target_actor_ids`
- `player_in_danger`

约束:
- 目标 id 必须从候选池中选
- 不允许输出不存在的角色名再由前后端模糊匹配

### 2.3 `attack_response_classification`

输入:
- `PublicTurnAttackPrompt`
- 玩家回应行为
- 玩家回应语言

输出:
- `response_world_impact_type = non_world | world`
- `effective_against_attack = true | false`
- `defense_ability_used`
- `response_summary`

约束:
- 只有 `world + effective_against_attack = true` 才能进入攻击对抗
- 不允许返回自由文本后让后端靠字符规则再判一次

### 2.4 普通互动分类

输入:
- `PublicTurnInteractionPrompt`
- 玩家回应行为
- 玩家回应语言

输出:
- `world_impact_type`
- `consent_state`
- `contest_state`
- `target_label`
- `speech_target_label`

同样要求:
- 使用固定枚举
- 目标必须来自稳定候选池
- 不依赖文本 fallback

## 3. 死亡与无法行动时的确定性分支

以下路径不走 AI 分类:
- 玩家 `role_action_status = death_saving`
- 玩家 `role_action_status = unable_to_act`

处理方式:
- 后端直接清空或拒绝 `action_text`
- 只保留 `speech_text`
- 直接按 non-world speech-only 结算

原因:
- 这是规则确定态，不是意图理解问题
- 不应让 AI 再次决定“玩家到底能不能行动”

## 4. 死亡豁免协议

死亡豁免不属于 AI 决策任务，属于确定性规则结算。

前端与后端交换:
- `DeathSavePrompt`
- `forced_dice_roll`

后端根据规则直接结算:
- `DC = 10`
- `1` 记双失败
- `20` 立即恢复 `1 HP`
- `3` 成功恢复 `1 HP`
- `3` 失败死亡

因此:
- 不存在 AI fallback
- 不存在“死亡豁免解释模型输出”
- 只使用后端原生规则结果和事件

## 5. 协议修复

当前公开回合仍保留协议修复能力，但修复目标是:
- 让 AI 重新输出满足原 schema 的原生结构

不是:
- 在后端本地猜测非法枚举应该映射成什么
- 把自由文本拆词后回填到结构里

相关结构:
- `PublicTurnProtocolRepairNotice`
- `PublicTurnProtocolRepairRequest`
- `continue_kind`

当前 `continue_kind` 已支持:
- `reaction`
- `opposed`
- `attack_defense`
- `death_save`

## 6. Prompt 与模板库

模板库继续作为稳定规则输入，不作为 fallback 文本修补器。

当前攻击相关 prompt key 至少包括:
- `public.turn.segment_plan.*`
- `public.turn.attack_assessment.*`
- `public.turn.attack_response_classification.*`
- `public.turn.aoe_target_selection.*`
- `public.turn.attack_outcome_narration.*`
- `public.turn.damage_plan.*`

模板库相关:
- `equipment_definitions.csv`
- `spell_definitions.csv`

若模板缺失:
- AI 可以返回结构化伤害计划
- 但仍必须满足 schema
- 不能让前后端去猜 spell / damage type / target

## 7. 当前非目标范围

本轮没有改动:
- main chat 的全部 deterministic router
- battle sandbox 的完整 AI 协议
- BUFF / 晕眩等完整 `unable_to_act` 扩展设计

## 8. 角色构筑与 AI 协议边界

玩家与随从构筑系统本轮新增了多组 HTTP 接口，但它们不属于主聊天 tool protocol。

当前边界:
- 构筑页的 `suggest/*` 接口只做表单补全
- 构筑页的 `media/*` 接口只做立绘上传、生成、去背景、确认和看图描述
- 它们不会进入 `route_main_turn_intent()`，也不会生成 scene tool event

约束:
- `suggest/loadout` 只能在后端提供的选项 ID 内返回选择
- `media/describe` 只允许读取已去背景或已确认的立绘
- `player/complete` / `companion/complete` 只接受 `final_portrait`
Current build template sources:
- `equipment_definitions.csv`
- `spell_definitions.csv`
- `war_art_definitions.csv`

Current constraint:
- AI loadout suggestion can only pick backend-provided spell ids and war-art ids.
- AI does not invent new spells or war arts during character build.

## 9. 玩家输入校验协议

玩家输入校验不属于主聊天 tool protocol，也不复用 `route_main_turn_intent()`。它是提交前的独立 AI JSON 协议，供聊天、单聊和公开回合入口统一调用。

当前 prompt key:
- `player.input.validate.system`
- `player.input.validate.user`

当前 JSON 契约固定字段:
- `normalized_action_text`
- `normalized_speech_text`
- `fallback_action_text`
- `issue_codes`
- `resource_kind`
- `resource_name`
- `suggested_action_type`

当前枚举约束:
- `issue_codes[] = multiple_world_actions | claimed_outcome | controls_other_actor`
- `resource_kind = none | spell | war_art | item`
- `suggested_action_type = auto | attack | check | item_use`

当前失败策略:
- 缺少 AI 配置时返回 `AI_CONFIG_REQUIRED: player_input_validation`
- JSON 非法、枚举不合法、修复失败时返回 `PLAYER_INPUT_VALIDATION_FAILED`
- 不做 fail-open
- 不猜测缺失资源，不做多候选歧义消解

当前确定性资源校验:
- spell: 校验已知法术与法术位
- war_art: 校验已知武技、武技点，以及是否已装备任意武器
- item: 校验背包中是否持有对应物品

当前行动状态校验:
- `death_saving` / `unable_to_act` 提交动作时返回 `speech_only_required`
- `dead` 提交动作时返回 `actor_dead`
