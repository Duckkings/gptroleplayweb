# AI Tool Protocol Addendum

更新日期：2026-03-08

## 新增遭遇工具
- `get_active_encounters`
  - 返回当前 `active/escaped` 遭遇、排队遭遇和摘要
- `encounter_act`
  - 推进遭遇一步
- `encounter_escape`
  - 执行逃离尝试
- `encounter_rejoin`
  - 在玩家回到原地点后重返遭遇

## Prompt factsource
- AI prompt 现在统一以 `data/ai-prompts.csv` 为事实源。
- 遭遇、NPC 单聊、公开区域反应、队伍公开反应都改用版本化 key。

## 调用约束
- 涉及遭遇叙事时，先读 `get_active_encounters`。
- 涉及公开区域点名 NPC 时，先读 `get_story_snapshot` / `get_entity_index`，再决定目标是否合法。
