# Encounter Technical Addendum

更新日期：`2026-03-09`

## 本轮变化
- 遭遇新增 `situation_start_value`、`situation_value`、`situation_trend`。
- 玩家、NPC、队友行动现在都能改变局势值。
- 遭遇结算新增 `EncounterOutcomePackage`，并真实回写声望、关系和奖励。

## 当前结果
- 遭遇已经从一次性 prompt 解析升级为持续推进场景。
- 子区块声望和队友在场状态会影响遭遇初始局势。
- 前端已经显示局势值、趋势和结果摘要。

