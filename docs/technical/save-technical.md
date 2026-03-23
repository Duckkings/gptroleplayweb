# 存档技术文档

更新时间：`2026-03-23`

## EncounterEntry

### 当前字段
- `goal: str`
- `secret: str`
- `scene_summary: str`
- `situation_value: int`
- `situation_trend: improving | stable | worsening`

### 兼容保留字段
- `latest_outcome_summary`
- `background_tick_count`
- `player_presence`
- `status = escaped`

这些字段只为旧档读取保留，不再作为现行设计继续增长或继续公开展示。

## EncounterTemporaryNpc
- `knows_secret: bool = False`

## Public Encounter DTO
- `PublicEncounterEntry`
- `PublicEncounterState`

公开 DTO 会从内部存档脱敏序列化，默认剔除：
- `secret`
- `knows_secret`
- `latest_outcome_summary`
- `background_tick_count`
- `player_presence`

## PublicTurnRound
- `pending_information_check_prompt`

## PublicTurnResponse / PendingTurnContinueResponse
- `public_information_check_prompt`
- `status = awaiting_player_information_check`

## PublicTurnSettlementEntry
- `followup_check`

## 兼容说明
- 旧档中的 `escaped / away` 在运行时会归一化成当前可继续处理的 active encounter 视图。
