# 技术文档（Roleplay Web）
## 设计来源
- `docs/design/gamedesign/gamedesign.md`
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/teamdesign.md`

更新于 `2026-03-08`。

## 1. 文档分层
- 设计文档：`docs/design/gamedesign/*.md`
  - 描述玩法目标、体验规则、优先级与取舍。
- 技术文档：`docs/technical/*.md`
  - 描述数据模型、接口契约、状态机、校验规则、实现边界。
- 模块 README：各代码目录下的 `README.md`
  - 描述模块职责、导出接口与依赖关系。

维护规则：
- 只要接口、状态、存档结构或前端交互发生变化，必须同步更新对应技术文档。

## 2. 当前专题文档
- `docs/technical/gameplay-core-technical.md`
- `docs/technical/role-technical.md`
- `docs/technical/save-technical.md`
- `docs/technical/fate-technical.md`
- `docs/technical/quest-technical.md`
- `docs/technical/encounter-technical.md`
- `docs/technical/team-technical.md`
- `docs/technical/ai-tool-protocol.md`

## 3. 当前系统能力概览
### 3.1 聊天与 AI 工具
- 主聊天支持工具调用，后端统一执行业务逻辑并回注模型。
- NPC 单聊具备问候、知识边界、结构化对话日志。
- AI 工具层已覆盖玩家状态、故事快照、一致性状态、NPC 知识边界、队伍状态、角色背包等只读能力。
- AI 工具层已覆盖入队、离队、调试队友生成、队伍聊天、玩家资源修改等写入能力。

### 3.2 世界、一致性与叙事
- 使用 `world_revision / map_revision` 管控地图重生成后的内容失效。
- 命运线、任务、遭遇都绑定来源 revision，并带实体引用校验。
- NPC 回答会受 `NpcKnowledgeSnapshot` 约束，避免引用当前世界中不存在的人物或地点。

### 3.3 角色与队伍
- 玩家、NPC、怪物共用统一角色底座：`PlayerStaticData + Dnd5eCharacterSheet`。
- `NpcRoleCard` 承载个性、背景、关系、认知变化、对话日志。
- 队伍系统当前已实现：
  - 邀请 NPC 入队
  - 调试队友生成与离队销毁
  - 队友跟随同步
  - 主聊天 / 单聊 / 移动 / 检定后的队友反馈
  - 队伍聊天 `team_chat`
  - 队友背包详情查看

### 3.4 存档与日志
- 逻辑层统一对象仍是 `SaveFile`。
- 物理存储为 pointer + bundle 分片。
- 队伍相关持久化包括：
  - `team_state`
  - 队友对话日志（保存在 `role_pool` 的 `NpcRoleCard.dialogue_logs`）
  - `game_logs` 中的 `team_join / team_leave / team_reaction / team_chat / team_debug_generate`

## 4. 当前实现策略
项目保持“规则代码负责事实，AI 负责文本”的边界：
- 后端负责：
  - 存档读写
  - revision 与失效
  - 实体合法性校验
  - 队伍成员状态、跟随、离队
  - 关系与资源写入
- AI 负责：
  - 主叙事与 NPC 文本
  - 任务 / 遭遇草稿文案
  - 入队判断的可选补强
  - 队伍聊天的逐成员回应

## 5. 本轮新增关注点
- 读取 `roledesign.md` 后，角色技术文档补齐了结构化对话日志、背包查看、队伍复用角色卡的约束。
- 读取 `teamdesign.md` 后，落地了新队伍设计：
  - 独立队伍面板
  - 队伍聊天
  - 队友背包详情
  - AI 工具 `team_chat`
- 相关技术文档已同步更新，不再只记录“入队/离队/跟随”。

## 6. 建议阅读顺序
1. 对应设计文档
2. 对应专题技术文档
3. 相关模块 README
4. 相关代码实现与测试

## 7. 常用回归
```powershell
cd backend
python -m unittest discover -s tests -p "test_area_logic.py"
python -m unittest discover -s tests -p "test_consistency_service.py"
python -m unittest discover -s tests -p "test_quest_fate_encounter.py"
python -m unittest discover -s tests -p "test_team_service.py"
```
