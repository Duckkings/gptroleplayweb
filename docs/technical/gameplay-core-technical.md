# 核心玩法技术文档

更新时间：`2026-03-23`

## 本次更新范围
- 遭遇公开模型改为 `goal / scene_summary / secret`
- 主聊天公开回合改成叙述区内联输入
- 非世界影响的信息获取 / 社交 / 威胁行为正式纳入公开回合检定状态机

## 遭遇
- 后端内部模型：
  - `EncounterEntry.goal`
  - `EncounterEntry.secret`
  - `EncounterEntry.scene_summary`
  - `EncounterTemporaryNpc.knows_secret`
- 前端公开模型：
  - `PublicEncounterEntry`
  - `PublicEncounterState`
- 玩家公开视图只显示：
  - `goal`
  - `scene_summary`
  - `situation_value`
  - `situation_trend`

## 公开回合
- 文本输入与确认走内联面板。
- 掷骰保留弹窗。
- 新暂停状态：
  - `awaiting_player_information_check`
- 新 prompt：
  - `PublicTurnInformationCheckPrompt`
- 新结算字段：
  - `PublicTurnSettlementEntry.followup_check`

## 信息获取规则
- `information_gathering + hidden` -> `static_dc`
- `information_gathering + noticed/obvious + 有效阻碍` -> `opposed_then_information_dc`
- `social_influence` / `intimidation` -> `static_dc` 或 `opposed_actor`

## 场景事件
- `encounter_situation_update.content` 直接等于 AI 生成的 `scene_summary`
- 不再生成新的 `encounter_background` / `encounter_background_tick`

## 退役能力
- encounter background advancement
- escape / rejoin 现行玩法
- “最近进展”公开展示
- non-world 行为默认无检定的旧口径
