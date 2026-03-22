# 公开回合互动与攻击设计

本文档是公开回合里“互动、攻击、对抗、AOE、伤害结算、暂停恢复”的唯一详细设计口径。其他文档只保留总览和引用，不再重复定义攻击分流规则。

## 1. 总原则

- 公开回合中，角色对角色的定向行为一律先进入互动/攻击评估，不再走旧的 `attack -> reaction` 捷径。
- 玩家在优先回合已经行动过，则不会再在本轮常规推进阶段获得第二次行动。
- `speech_target` 只表示台词听众，不决定谁来回应。
- 互动与攻击都允许“玩家输入行为 + 语言”，但只有真正改变世界状态、且能实质影响当前冲突的回应，才会进入对抗掷骰。

## 2. 普通互动流

适用范围：

- 社交互动
- 威吓、示意、劝阻、抢话、拦路等非攻击定向行为
- 被 AI 识别为 `ordinary_action` 的攻击类输入

流程：

1. 行为方提交行为与语言。
2. 目标方提交行为与语言；玩家手动输入，NPC 由 AI 自动补。
3. AI 根据双方结构化输出判断：
   - `non_world -> non_world`：仅写入叙事与结算，不掷骰。
   - `world -> non_world`：不形成对抗，行动方按静态 DC 或免骰结算。
   - `world -> world`：若目标回应构成明确阻碍，则升级为对抗。
4. 结算生成：
   - settlement card
   - structured consequences
   - AI 结果叙述

`不做任何行动` 的语义固定为：

- `response_kind = "no_action"`
- `action_text = ""`
- `speech_text = ""`
- 该回应永远视为 `non_world`

## 3. 攻击分类

公开回合中的 `action_type = attack` 先做一层 AI `attack_assessment`，输出三类之一：

- `ordinary_action`
  - 实际上不应进入攻击专线。
  - 直接降级回普通互动流。
- `targeted_attack`
  - 单体定向攻击。
  - 例：武器挥砍、射箭、指向性法术、单目标投掷物。
- `aoe_attack`
  - 范围攻击。
  - 例：火球术、喷吐、扇形火焰、爆炸瓶。

同时需要输出：

- `attack_basis = weapon | spell | other`
- `attack_definition_name`
- `attack_area_shape`
- `attack_area_radius_m`
- `attack_area_length_m`
- `can_include_self`
- 候选覆盖目标
- 建议攻击属性

## 4. 单体攻击流程

### 4.1 基本流程

1. 攻击方提交行为与语言。
2. AI 将该行为评估为 `targeted_attack`。
3. 目标方输入如何处理；玩家手动输入，NPC 自动输入。
4. AI 对目标方回应做 `attack_response_classification`，输出：
   - `response_world_impact_type`
   - `effective_against_attack`
   - `defense_ability_used`

### 4.2 是否进入攻击对抗

- 若目标回应是 `world` 且 `effective_against_attack = true`：
  - 进入攻击对抗掷骰。
- 若目标回应是 `non_world`：
  - 不进入对抗。
  - 目标直接进入命中池。
- 若目标回应是 `world` 但 `effective_against_attack = false`：
  - 不进入对抗。
  - 目标直接进入命中池。

### 4.3 攻击对抗规则

公开回合攻击对抗不使用原生 DND AC 命中逻辑，而是使用互动式对抗：

- 攻击方：
  - 武器攻击：按武器模板选择力量、敏捷或 `finesse_choice`
  - 法术攻击：按法术模板的施法属性
  - 其他攻击：由 AI 给出建议属性
- 防御方：
  - 不预设固定属性
  - 由 AI 根据回应行为选择 `defense_ability_used`

结算：

- 攻击方胜利：目标进入命中池，继续伤害结算
- 防御方胜利：目标进入规避池，不进入伤害结算

## 5. AOE 攻击流程

### 5.1 目标池生成

AOE 攻击先做 `aoe_target_selection`：

- AI 根据当前公开场景、距离、站位、遮挡、拥挤程度、法术/武器模板，输出被覆盖的目标池。
- AOE 允许覆盖隐藏角色。
- 若隐藏角色被纳入覆盖范围：
  - 立刻显形
  - 写入 `revealed_target_names`
  - 公开参与这次结算

### 5.2 自身是否被纳入目标池

- AOE 法术：
  - 若模板允许自伤，且场景上属于贴脸或近身施放，自身可以被纳入目标池。
- AOE 武器：
  - 施攻击者自身永远不会被纳入目标池。

### 5.3 响应顺序

1. 先结算非玩家目标：
   - NPC 自动生成回应
   - 若回应有效，则自动掷骰
   - 若回应无效，则直接进入命中池
2. 如果目标池里包含玩家：
   - 在 NPC 目标处理完后暂停
   - 打开攻击回应弹窗，让玩家输入行为与语言
   - 若玩家回应有效，再进入攻击对抗掷骰
3. 目标池处理完成后：
   - 对命中池统一进行伤害结算

## 6. 命中池、规避池、显形池

每次攻击结算都要显式产出三类结构化结果：

- `threatened_target_names`
  - 被这次攻击纳入危险范围的目标
- `hit_target_names`
  - 最终进入伤害结算的目标
- `avoided_target_names`
  - 通过有效对抗规避掉本次攻击的目标
- `revealed_target_names`
  - 因 AOE 被迫显形的隐藏目标

结算区必须显示这些字段，不能只依赖叙事文本。

## 7. 伤害结算

伤害不再靠后端词表推断，优先顺序固定如下：

1. 武器模板 `equipment_definitions.csv`
2. 法术模板 `spell_definitions.csv`
3. 模板缺失时，允许 AI 返回结构化伤害兜底

### 7.1 武器模板

扩展字段：

- `attack_mode`
- `attack_ability_mode`
- `damage_bonus`
- `area_shape`
- `area_radius_m`
- `area_length_m`
- `self_target_policy`

默认迁移规则：

- `finesse=true` -> `finesse_choice`
- `range_normal > 1` 或 `ammunition=true` -> `dexterity`
- 其他武器 -> `strength`
- 未声明面积 -> `targeted_attack`

### 7.2 法术模板

`spell_definitions.csv` 至少包含：

- `definition_id`
- `name`
- `attack_mode`
- `casting_ability`
- `damage_dice`
- `damage_bonus`
- `damage_type`
- `area_shape`
- `area_radius_m`
- `area_length_m`
- `self_target_policy`
- `description`
- `resolution_notes`

### 7.3 HP 与死亡

命中池确定后才允许扣血：

- 写入 `PublicTurnImpact.hp_changes`
- 写入 `PublicTurnSettlementEntry.hp_changes`
- 同步更新玩家与 NPC 的当前 HP / downed / dead 状态
- `HP <= 0` 后的详细分流规则，包括玩家/队友 NPC/普通 NPC 的死亡豁免、speech-only 约束、死亡结果窗口、子区块死亡清理，统一以 [deathdesign.md](./deathdesign.md) 为唯一详细口径。
- 本文只定义公开回合里的伤害如何进入扣血与结算；不在本文件重复定义 `0 HP` 后的完整状态机。

未进入命中池的目标绝不能被扣血。

## 8. 暂停与恢复

公开回合新增两个攻击专用暂停状态：

- `awaiting_player_attack_response`
- `awaiting_player_attack_defense`

前端对应两个专用弹窗：

- 攻击回应弹窗
- 攻击对抗掷骰弹窗

恢复规则：

- 旧的进行中 `attack/reaction` pending 状态不做迁移。
- 读取到旧攻击 pending 时，后端直接作废该 pending，并提示“旧攻击暂停状态已失效，请重新开始该轮公开回合攻击”。
- 历史 settlement 保持可读，但新运行时不再写入 `interaction_resolution = "attack_flow"`。

## 9. 前端展示规则

### 9.1 攻击回应弹窗

必须显示：

- 攻击来源
- 攻击分类
- 攻击定义名称
- 当前处理目标
- AOE 范围信息
- 危险目标列表
- 本次显形目标
- 玩家是否处于危险范围

### 9.2 攻击对抗弹窗

必须显示：

- 攻击方与防御方
- 双方行为摘要
- 攻击方属性与修正
- 防御方属性与修正
- 当前 stakes
- AOE 已命中目标与剩余待结算目标数

### 9.3 结算区

每张 settlement card 需要显示：

- 攻击分类
- 攻击来源类型
- 攻击定义名
- 范围形状
- 危险目标池
- 命中池
- 规避池
- 显形目标
- HP 变化
- AI 结果叙述

## 10. AI 结构化契约

公开回合攻击只保留四个 AI 判断步骤：

1. `attack_assessment`
2. `aoe_target_selection`
3. `attack_response_classification`
4. `attack_outcome_narration`

要求：

- 必须输出稳定枚举值
- 不再使用关键词词表判断“是否形成攻击对抗”
- 伤害数值优先读模板，AI 只在缺表时兜底

## 11. 文档归属

- 本文档拥有公开回合互动与攻击的全部细则。
- [publicturndesign.md](./publicturndesign.md) 只保留总览与阶段说明。
- 技术字段与协议细节分别见：
  - `docs/technical/gameplay-core-technical.md`
  - `docs/technical/ai-tool-protocol.md`
  - `docs/technical/save-technical.md`
