# AI Tool Protocol Addendum

更新日期：`2026-03-09`

## 本轮变化
- 主聊天前增加玩法路由层，减少“AI 只写文本、不触发逻辑”的风险。
- AI 工具新增 quest/fate/public-scene/reputation/role-drive 读取能力。
- 新 prompt key 已注册到 prompt registry 和 CSV。

## 当前新增工具
- `get_quest_state`
- `get_fate_state`
- `get_area_reputation`
- `get_role_drives`
- `get_public_scene_state`
- `quest_track`
- `quest_evaluate`

## 当前原则
- 确定性动作优先由后端路由
- 结构化读取优先于模型自由猜测
- 审计和日志仍由后端统一写入

