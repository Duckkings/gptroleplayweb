# Prompt Governance

更新日期：2026-03-08

## 事实源
- 运行时 prompt 文本以 `data/ai-prompts.csv` 为事实源。
- 代码默认 prompt 只做 key 缺失时的兜底。

## 版本化 key
- 新 prompt 使用版本化 key，例如：
  - `chat.context_rule.v2`
  - `npc.chat.user.v2`
  - `npc.public.targeted.user.v1`
  - `team.public.reaction.user.v1`
  - `encounter.step.user.v1`

## 关键要求
- NPC 私聊、公开区域回复、队伍公开反应、遭遇推进必须使用不同 key，避免混用。
- 后端维护必备 key 列表，并用测试校验 CSV 是否齐全。
- 当业务逻辑切到新 key 后，旧 key 不再被运行时代码继续引用。
