# 公开回合系统实现计划

更新日期：`2026-03-21`

本文档保留公开回合的实现要求与验收口径。设计细则统一引用：

- [../design/gamedesign/publicturninteractiondesign.md](../design/gamedesign/publicturninteractiondesign.md)

## 1. 实现目标

公开回合必须具备：

- 独立状态机
- 玩家入口、抢先、常规推进、GM push
- 结构化结算与存档恢复
- 互动、攻击、AOE、伤害、死亡在同一条公开回合链内结算

## 2. 当前统一口径

以下旧口径已废弃：

- 旧的“攻击直接跳到 reaction”捷径
- “攻击不属于 interaction redesign”
- 依赖关键词词表判断玩家回应是否构成对抗

以下新口径已生效：

- 公开回合攻击先做 `attack_assessment`
- 攻击分类固定为 `ordinary_action / targeted_attack / aoe_attack`
- `ordinary_action` 回落到普通互动流
- `targeted_attack / aoe_attack` 先收集目标回应，再判断是否进入攻击对抗
- 只有 `world + effective_against_attack=true` 才会进入攻击对抗

## 3. 状态机要求

公开回合至少包含以下暂停状态：

- `awaiting_player_interaction`
- `awaiting_player_reaction`
- `awaiting_player_opposed`
- `awaiting_player_attack_response`
- `awaiting_player_attack_defense`

## 4. 攻击要求

### 4.1 单体攻击

- 不再使用公开回合里的 AC 命中捷径
- 目标先回应
- 回应有效时，双方按属性对抗
- 攻击方胜利才进入伤害结算

### 4.2 AOE 攻击

- 由 AI 结合场景生成覆盖目标池
- 允许覆盖隐藏角色
- 命中隐藏角色时要先显形
- 非玩家目标先自动回应和自动掷骰
- 若目标池里有玩家，再暂停给玩家输入

## 5. 数据要求

必须新增并贯通：

- `spell_definitions.csv`
- `PublicTurnAttackPrompt`
- `PublicTurnAttackDefensePrompt`
- settlement attack fields
- pending attack fields

## 6. 兼容策略

- 历史 settlement 可读
- 旧 `attack_flow` 历史记录仅作兼容读取
- 新运行时不再写入 `attack_flow`
- 旧进行中攻击 pending 不迁移；读取到时直接作废并要求重开

## 7. 验收点

- 单体攻击可正确分为 `targeted_attack`
- 火球术等范围法术可正确分为 `aoe_attack`
- AOE 可覆盖多个目标并产出威胁池、命中池、规避池、显形池
- 玩家在攻击回应后若形成有效阻碍，可直接进入攻击对抗掷骰
- 未进入命中池的目标绝不扣血
- 模板库状态能显示法术定义数量
- Debug 面板能触发 `AI 填充法术表`

## 8. 文档引用

- 设计：`docs/design/gamedesign/publicturninteractiondesign.md`
- 运行时：`docs/technical/gameplay-core-technical.md`
- AI 协议：`docs/technical/ai-tool-protocol.md`
- 存档：`docs/technical/save-technical.md`
