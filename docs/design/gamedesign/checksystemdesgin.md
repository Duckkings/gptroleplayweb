# 检定系统设计

更新时间：`2026-03-23`

## 核心原则
- 是否掷骰不再只由“是否世界影响”决定。
- 公开回合下，非世界影响行为也可以进入检定与对抗。
- AI 必须先给出检定路线，玩家才开始掷骰。

## 路由类型
- `static_dc`
  - 直接与固定 DC 比较。
- `opposed_actor`
  - 行动方与阻碍方对抗。
- `opposed_then_information_dc`
  - 先对抗，行动方成功后再补一颗信息检定。

## 适用口径
- `information_gathering`
  - 可为 `static_dc` 或 `opposed_then_information_dc`
- `social_influence`
  - 可为 `static_dc` 或 `opposed_actor`
- `intimidation`
  - 可为 `static_dc` 或 `opposed_actor`

## followup_check
- 只用于“信息获取先对抗、后补信息 DC”。
- 不用于普通社交、威胁、攻击。
- 前端必须在 settlement 中展示这颗后续检定。
