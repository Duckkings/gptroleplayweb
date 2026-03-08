# Encounter Technical Addendum

更新日期：2026-03-08

## 持续遭遇状态机
- 状态从旧的 `queued/presented/resolved` 扩展为：
  - `queued`
  - `active`
  - `escaped`
  - `resolved`
  - `expired`
  - `invalidated`
- 旧存档中的 `presented` 会在读取时兼容为 `active`。

## 新增字段
- `encounter_mode`
- `npc_role_id`
- `player_presence`
- `termination_conditions`
- `steps`
- `scene_summary`
- `latest_outcome_summary`
- `background_tick_count`
- `last_advanced_at`

## 新行为
- 地图移动离开遭遇现场前会先做逃离检定。
- 逃离成功后，遭遇保持可见并进入 `escaped + away`。
- 玩家后续任何会推进时间的行为，都可能推动后台遭遇继续发展。
- 玩家回到原遭遇地点后，可执行 `rejoin` 重新介入。

## 前端展示
- 遭遇改为并行栏，不再使用阻塞式遭遇模态。
- Quest / Fate 仍保留更高优先级的阻塞行为。
