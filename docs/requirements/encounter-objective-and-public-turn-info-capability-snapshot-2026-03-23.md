# Encounter Objective And Public Turn Info Capability Snapshot

日期：`2026-03-23`

## 已实现
- 遭遇公开模型切换为 `goal + scene_summary`
- 遭遇内部新增 `secret`
- 临时 NPC 新增 `knows_secret`
- 主聊天列新增遭遇目标提醒条
- 遭遇侧栏/弹窗删除“最近进展”，统一显示当前局势摘要
- `scene_summary` 在公开回合结束后由 AI 摘要刷新
- 公开回合非世界行为新增 `information_gathering / social_influence / intimidation` 路由
- 信息获取支持 `opposed_then_information_dc`
- 前端 settlement 支持展示 `followup_check`
- 后台推进与 escape/rejoin 路由退役

## 用户可见变化
- 玩家更容易理解当前遭遇要完成什么
- 玩家能直接在主聊天叙述区处理公开回合输入
- 遭遇局势摘要不再是固定模板
- 队友在公开回合里会围绕遭遇目标行动

## 已知风险
- 旧的 encounter 相关单测仍有一部分断言后台推进 / 逃离 / 重返旧行为，需要后续按新设计重写
- 全量后端测试在当前环境下还受 `itsdangerous` 缺失影响
