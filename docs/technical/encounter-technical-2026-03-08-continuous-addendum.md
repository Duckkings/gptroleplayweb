# Encounter Continuous Addendum Retired

更新时间：`2026-03-23`

这份 2026-03-08 连续后台推进补丁文档已退役，不再代表当前实现。

## 已退役内容
- `escaped / away` 作为现行运行时状态
- 玩家离场后后台持续推进遭遇
- `background_tick` / `encounter_background` 事件作为正常玩法输出
- `escape / rejoin` 作为正式遭遇流程

## 现行文档
- 主文档改为 [encounter-technical.md](./encounter-technical.md)

## 现行口径
- 遭遇采用 `goal / scene_summary / secret`
- `scene_summary` 是唯一公开局势摘要
- 后台推进与逃离/重返仅作 legacy read，不再作现行设计
