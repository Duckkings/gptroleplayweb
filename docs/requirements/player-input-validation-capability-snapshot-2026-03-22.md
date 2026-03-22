# 玩家输入校验能力快照
更新日期: `2026-03-22`

## 范围

当前已实现统一的玩家输入预校验系统，覆盖以下入口:
- 主聊天 `main_chat`
- NPC 单聊 `npc_chat`
- 队友单聊 `teammate_chat`
- 公开回合玩家行动 `public_turn_action`
- 公开回合互动回应 `public_turn_interaction_response`
- 公开回合攻击回应 `public_turn_attack_response`
- Debug 面板 `debug_panel`

当前未接入:
- 队伍群聊 `team_chat`
- 角色创建 prompt
- battle sandbox

## 后端能力

当前新增接口:
- `POST /api/v1/player-input/validate`

当前后端流程:
1. 读取当前角色和存档上下文。
2. 调用 `player.input.validate.*` prompt，将输入规范化为单个、自身、无结果宣告的动作。
3. 对法术、武技、道具和行动状态执行确定性校验。
4. 返回 `accepted` 或 `needs_player_confirmation`。

当前资源与状态规则:
- spell: 需要角色已知，并具备足够法术位
- war_art: 需要角色已知，并具备足够武技点，且装备任意武器
- item: 需要背包内存在对应物品
- `death_saving` / `unable_to_act`: 只能提交语言
- `dead`: 不能再提交动作

当前失败策略:
- AI 配置缺失返回 `AI_CONFIG_REQUIRED: player_input_validation`
- AI JSON 协议失败返回 `PLAYER_INPUT_VALIDATION_FAILED`
- 不做 fail-open

## 前端能力

当前前端在真正发送前统一调用校验接口。

当前行为:
- 无 `action_text` 时直接跳过
- 校验通过时自动采用规范化文本
- 校验失败时弹统一确认模态
- 用户只能选择 `采用建议` 或 `返回修改`
- 采用建议后，前端只对同一份规范化输入跳过一次再次校验

当前 Debug 能力:
- 新增“玩家行为校验测试”入口
- 可选择玩家或 NPC
- 可查看问题列表、资源状态、规范化结果和建议文本
- 可继续使用规范化后的动作做行为检定

## 验证状态

已验证:
- `python -m unittest backend.tests.test_player_input_validation_service backend.tests.test_player_input_validation_routes`
- `npm run build`
