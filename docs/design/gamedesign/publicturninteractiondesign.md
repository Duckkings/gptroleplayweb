# 公开回合交互设计

更新时间：`2026-03-23`

## 范围
- 本文定义公开回合里的互动、说服、威胁、信息获取、对抗和后续信息检定。
- 骰点仍保留弹窗。
- 文本回应和上下文阅读统一走主聊天叙述区内联面板。

## 交互分类
- `generic`
  - 一般互动或阻拦。
- `information_gathering`
  - 观察、觉察、发现、洞察、偷听、识别、分析、辨认、推理。
- `social_influence`
  - 说服、劝说、安抚、欺骗、交涉。
- `intimidation`
  - 威胁、压迫、威慑、强势逼迫。

## 属性映射
- `觉察 / 发现 / 洞察 / 观察 / 偷听` -> `wisdom`
- `识别 / 辨认 / 分析 / 推理` -> `intelligence`
- `说服 / 劝说 / 安抚 / 欺骗 / 交涉` -> `charisma`
- `威胁 / 压迫 / 威慑` -> `strength` 或 `charisma` 中更合适者

## notice_state
- `hidden`
  - 行动没有被目标注意到。
- `noticed`
  - 行动被注意到，但不一定是高强度公开冲突。
- `obvious`
  - 行动本身就是公开、直接、强烈的。

AI 需要显式给出 `notice_state`。若缺失，fallback 为：
- 明确潜行、暗中、悄悄、偷听 -> `hidden`
- 明确点名、喊话、强迫、公开施压 -> `obvious`
- 其余 -> `noticed`

## 非世界影响行为也可检定
- 旧规则里“non_world -> non_world 不掷骰”的口径废止。
- 新规则里非世界影响行为也允许：
  - `static_dc`
  - `opposed_actor`
  - `opposed_then_information_dc`

## 信息获取的两段式
- 若 `information_gathering + hidden`
  - 不进入互动回应。
  - 直接做静态 DC。
- 若 `information_gathering + noticed/obvious`
  - 若无人阻碍，直接做静态 DC。
  - 若有有效阻碍，先进入互动 / 对抗。
  - 行动方赢下对抗后，再做一颗信息检定 DC。
  - 行动方输掉对抗，则信息获取失败，不进入第二颗骰。

## 社交与威胁
- `social_influence`
  - 一段式结算。
  - 可能是 `static_dc`，也可能是 `opposed_actor`。
- `intimidation`
  - 一段式结算。
  - 由 AI 结合目标抗拒和现场局势决定是否进入 `opposed_actor`。

## 玩家体验要求
- 需要回应文本时，统一在主聊天叙述区内联完成。
- 需要掷骰时，统一弹出骰点窗口。
- 玩家始终先看到当前轮输出和遭遇目标，再决定输入。

## 结算展示
- settlement 必须展示主检定。
- 若存在“对抗后补信息 DC”，同一张 settlement 还必须展示 `followup_check`。
