# 当前功能总结

日期：`2026-03-09`

## 1. 当前已实现能力
- 主聊天、NPC 单聊、任务、命运、遭遇、队伍、背包与行动检定已经串成统一存档流。
- 前后端共用同一套 schema，主界面可以实时反映主聊天、scene events、遭遇和队伍状态。
- Save bundle 已稳定分片，支持旧档兼容读取与新字段补齐。

## 2. 本轮新增能力
- 公开区域已切换为后端主导的严格轮值导演器。
- 新增按 `sub_zone_id` 持久化的区域声望。
- 新增 NPC 欲望与队友故事状态，并已接入公开场景和队伍展示。
- 遭遇新增局势值、趋势和结果包，并与声望/关系/奖励打通。
- 主聊天新增玩法路由层，能优先处理明确的移动、物品、队伍、遭遇和点名动作。
- AI 工具已补齐 quest/fate/reputation/role drives/public scene 读取能力。

## 3. 当前系统边界 / 已知不做
- 当前不做完整战斗先攻系统。
- 当前不做 zone 级声望继承。
- 当前不做商店、执法和经济系统。
- 队友故事默认非模态，不单独弹剧情窗口。
- quest accept/reject 继续只走模态，不接受主聊天自由文本直接确认。

## 4. 前后端联动清单
- 主聊天 `reply.content` 与 `scene_events` 已分离。
- `PlayerPanel` 显示当前子区块声望。
- `TeamPanel` 和 `RoleProfileModal` 显示 desire/story 摘要。
- `EncounterLane` 与 `EncounterModal` 显示局势值、趋势和结果摘要。
- `SubZoneContextPanel` 可以回看新增公开事件与遭遇推进事件。

## 5. AI 工具现状
- 读取工具已覆盖玩家、世界、任务、命运、队伍、背包、声望、角色欲望/故事和公开场景。
- 写入工具已覆盖移动、队伍、背包互动、遭遇推进和 quest 追踪/评估。
- 主聊天前置后端路由层后，AI 工具主要承担“读事实、补文本、补结构化意图”的角色。

## 6. 推荐阅读顺序
1. `docs/technical/gameplay-core-technical.md`
2. `docs/technical/role-technical.md`
3. `docs/technical/team-technical.md`
4. `docs/technical/encounter-technical.md`
5. `docs/technical/ai-tool-protocol.md`
6. `docs/technical/save-technical.md`

## 7. 回归测试入口
```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/tests

cd frontend
npm run build
```
