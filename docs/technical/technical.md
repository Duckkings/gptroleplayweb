# 技术文档总览

更新日期：`2026-03-09`

## 1. 文档来源
- `docs/design/gamedesign/gamedesign.md`
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/teamdesign.md`
- `docs/design/gamedesign/encounterdesign.md`
- `docs/design/gamedesign/playflowdesign.md`
- `docs/requirements/pending-2026-03-01.md`

## 2. 当前专题文档
- `docs/technical/gameplay-core-technical.md`
- `docs/technical/role-technical.md`
- `docs/technical/team-technical.md`
- `docs/technical/encounter-technical.md`
- `docs/technical/ai-tool-protocol.md`
- `docs/technical/save-technical.md`
- `docs/technical/fate-technical.md`
- `docs/technical/quest-technical.md`
- `docs/technical/area-technical.md`

## 3. 本轮增补文档
- `docs/technical/gameplay-core-technical-2026-03-09-addendum.md`
- `docs/technical/role-technical-2026-03-09-public-scene-director-addendum.md`
- `docs/technical/encounter-technical-2026-03-09-situation-addendum.md`
- `docs/technical/ai-tool-protocol-2026-03-09-addendum.md`
- `docs/technical/current-feature-summary-2026-03-09.md`

## 4. 当前系统能力概览

### 4.1 主聊天与公开场景
- 主聊天现在不是纯 AI 文本通道，而是 `后端玩法路由层 -> AI/工具 -> 公开场景导演器 -> 遭遇推进 -> 日志落库` 的组合流程。
- 公开区域由 `backend/app/services/public_scene_service.py` 统一推进，采用严格轮值导演器。
- `reply.content` 继续只承载 GM 正文；公开动作、声望变化、遭遇推进都通过 `scene_events` 和日志同步给前端。

### 4.2 区域声望
- 声望按 `sub_zone_id` 持久化，定义在 `SaveFile.reputation_state`。
- 当前 band 固定为 `hostile / cold / neutral / trusted / favored`。
- 声望已经接入公开场景、关系偏置、遭遇初值和遭遇结算。

### 4.3 角色主动性
- `NpcRoleCard` 现已持久化 `desires`、`story_beats`、`last_public_turn_at`。
- 角色欲望与队友故事由 `backend/app/services/roleplay_service.py` 负责补齐、浮出和必要时转普通任务。
- 队友故事默认非模态，只作为公开事件或队伍聊天话题出现。

### 4.4 遭遇
- 遭遇系统已从一次性描述升级为带 `situation_value` 的持续推进结构。
- 玩家、NPC、队友都可以通过行动修改局势值。
- 遭遇结束时会生成并清洗 `EncounterOutcomePackage`，真实落地到声望、关系、奖励和资源。

### 4.5 AI 工具与一致性
- 主聊天前置 `route_main_turn_intent(...)`，优先接管确定性玩法动作，防止模型只写文本不触发后端。
- AI 工具已补齐任务、命运、区域声望、角色欲望/故事、公开场景读取能力。
- 新 prompt key 已在 `PromptKeys` 和 `data/ai-prompts.csv` 注册。

### 4.6 前后端同步
- 前端已显示子区块声望、遭遇局势值、结果摘要、角色欲望/故事和新增 scene events。
- 模态优先级保持不变：`Quest/Fate > Encounter > 主聊天`。

## 5. 维护规则
- 只要 `schemas.py` 或 `frontend/src/types/app.ts` 的结构发生变化，必须同步更新对应技术文档。
- 只要新增 `scene_events`、工具 schema、API 路由或 Save bundle 分片，必须更新：
  - `docs/technical/gameplay-core-technical.md`
  - `docs/technical/ai-tool-protocol.md`
  - `docs/technical/save-technical.md`
- 阶段性功能落地完成后，补写一份当前时间点的能力快照文档。

## 6. 建议阅读顺序
1. `docs/technical/current-feature-summary-2026-03-09.md`
2. `docs/technical/gameplay-core-technical.md`
3. `docs/technical/role-technical.md`
4. `docs/technical/team-technical.md`
5. `docs/technical/encounter-technical.md`
6. `docs/technical/ai-tool-protocol.md`
7. `docs/technical/save-technical.md`

## 7. 当前回归入口
```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/tests

cd frontend
npm run build
```
