# AI 上下文分层草案

更新时间：2026-03-24

## 目的

这份草案用于定义当前系统里“会传给 AI 的东西”应该如何分层，目标是把上下文拆成两类：

- **基础层**：长期稳定、作为整局会话的背景事实
- **变化层**：本轮或最近几轮发生变化、需要每次增量传给 AI 的内容

这里的定义是为后续实现“持续 session + 增量喂入 + agent loop”服务的。  
本文件只做分类草案，不改现有业务语义。

## 基本原则

- 基础层尽量稳定，不在每次回合里重复发送完整大块原文。
- 变化层按领域拆分，不把一个大对象整体当作“是否变化”的唯一判断依据。
- AI 每轮输入应当至少包含：
  - 基础层摘要或固定前缀
  - 本轮变化层
  - 工具回执或结算结果
  - 当前待决策目标
- 后端始终是状态真源，AI 只消费状态、生成决策和结构化输出。

## 一、基础层

基础层是“整局游戏里默认成立、短期内不会因为某一轮动作而变化”的内容。  
它可以分为四类。

### 1. 世界规则基础层

这类内容一旦建立，通常只在版本变更、规则切换、存档迁移时变化。

- 系统规则和玩法约定
- 公共回合攻击/对抗/检定的设计语义
- 伤害、命中、AOE、资源消耗的总规则
- 死亡、倒地、死亡豁免、复活的总规则
- 队伍、遭遇、任务、命运线的系统规则
- 各类 prompt 的总约束规则

来源示例：

- `docs/design/gamedesign/publicturninteractiondesign.md`
- `docs/design/gamedesign/deathdesign.md`
- `docs/technical/ai-tool-protocol.md`

### 2. 定义库基础层

这类内容来自本地表或模板库，通常是静态定义，不属于“当前局面变化”。

- 角色职业 / 模板定义
- 技能定义
- 法术定义
- 武技定义
- 装备定义
- 遭遇模板
- 任务模板
- 命运阶段模板
- 区域 / 子区域固定描述
- prompt key 对应的模板文本

来源示例：

- `data/ai-prompts.csv`
- `data/*.csv` 里的人物、法术、武技、装备、任务、遭遇定义

### 3. 会话固定背景层

这类内容是“本局游玩开始时成立”的长期背景，不会因为单轮行动而改变。

- 当前存档所处的大世界状态摘要
- 当前玩家角色的静态档案
- 当前队伍成员的静态档案
- 当前主要 NPC 的静态档案
- 当前区域的长期背景简介
- 当前存档使用的 GM 规则模式 / 配置
- 当前 session 的长期记忆摘要

这里的“静态档案”指不因普通回合推进而变化的内容，例如：

- 姓名、称号、种族、阵营、外观、年龄
- 职业、模板、身份、关系定位
- 人设摘要、说话风格、性格标签
- 已知技能列表、法术列表、武技列表
- 角色固有偏好、厌恶、誓言、目标
- 角色的定义表 ID / CSV 定义 ID
- 角色背景简介

### 4. 稳定指令层

这类内容不是世界事实，但每次都应该长期可见，属于系统性约束。

- 模型输出格式要求
- JSON schema 约束
- 工具调用协议
- 角色扮演边界
- 叙事边界
- 禁止编造的实体和知识边界
- 当前 session 的输出风格约束

## 二、变化层

变化层是“会在本局中不断变化，且应该按增量传给 AI”的内容。  
它不应该以一个超大对象的整体形式传入，而应该拆分成多个子结构。

### 1. 角色运行时变化层

这类变化只描述“角色当前运行时状态发生了什么变化”。

- 当前生命值变化
- 当前最大生命值变化
- 法术位变化
- 武技点变化
- 体力 / 耐力 / 护盾 / 临时生命变化
- 当前状态标记变化
- 倒地 / 死亡 / 稳定 / 死亡豁免状态变化
- 当前可行动性变化
- 当前行动点 / 回合内可用资源变化
- 当前装备 / 持用 / 施放状态变化
- 角色位置变化
- 角色是否在场变化
- 角色当前是否可被选中变化
- 角色关系数值变化
- 角色态度变化

这里不包括角色基础档案、技能列表、法术列表、武技列表、人设简介等静态内容。

### 2. 场景变化层

这类变化描述“当前所在场景现在成了什么样子”。

- 当前区域 / 子区域的变化
- 场景摘要更新
- 场景事件新增
- 时间推进
- 可见对象变化
- 玩家是否仍在场 / 是否离场
- 当前危险度 / 声望 / 情境值变化
- 当前正在进行的遭遇状态变化

### 3. 回合变化层

这类变化描述“这一回合已经推进到了哪里、还剩什么没处理”。

- 回合阶段变化
- 当前 actor / 当前行动者变化
- initiative / 排序变化
- 待处理 actor 列表变化
- pending prompt 变化
- 待玩家确认的输入变化
- 检定结果变化
- 对抗结果变化
- 结构化后果变化
- 结算条目变化
- 当前回合是否暂停变化
- 当前回合是否结束变化

### 4. 工具回执变化层

这类变化是“工具执行后返回给 AI 的新增事实”。

- 查表结果
- 掷骰结果
- 扣资源结果
- 恢复资源结果
- 目标解析结果
- 伤害结果
- 对抗判定结果
- 检定判定结果
- AI 前一步建议被后端修正后的最终结果
- 工具成功 / 失败
- 工具错误信息
- 重试后的最终值

### 5. 关系变化层

这类变化描述“角色之间关系变了多少”。

- NPC 对玩家的态度变化
- 队友对玩家的态度变化
- 玩家和 NPC 的 affinity / trust / relation tag 变化
- 区域声望变化
- 任务相关关联度变化
- 命运线关联度变化

### 6. 任务 / 命运 / 遭遇变化层

这类变化描述“故事推进到了哪一步”。

- 任务状态变化
- 任务目标完成情况变化
- 命运阶段变化
- 命运线触发 / 推进 / 终止变化
- 遭遇开始 / 进行中 / 结束 / 后台推进变化
- 遭遇终止条件满足情况变化
- 遭遇结果包变化

### 7. 公共回合专有变化层

这是当前最需要细拆的一块。  
它的变化不应该只看一个 `PublicTurnState` 大对象，而要分成以下子类：

- 回合阶段变化
- 当前 actor / 当前阶段 actor 列表变化
- initiative / 排序变化
- 待处理 directive 变化
- pending prompt 变化
- 检定结果变化
- 对抗结果变化
- 伤害 / 后果 / 资源消耗变化
- 结算条目变化
- 结构化后果变化
- 玩家是否被暂停等待输入

### 8. 记忆表面层

这类变化是“AI 之前生成过、但后来又被新事件改写”的内容。

- 角色欲望是否浮出
- 队友故事节点是否浮出
- 公开场景记忆点是否更新
- 角色私有记忆摘要是否更新
- 场景最近回合摘要是否更新
- 角色对当前局势的暂存判断变化

### 9. 系统通知层

这类变化是系统给 AI 的显式状态提示。

- 当前是等待玩家输入
- 当前是等待玩家对抗
- 当前是等待玩家攻击反应
- 当前是等待玩家信息检定
- 当前是等待死亡豁免
- 当前是协议修复中
- 当前会话被暂停
- 当前会话被强制停止

## 三、变化层的推荐拆法

为了避免“一个大结构体有一个字段变了，就整包算变”的问题，建议把变化层按下面的粒度拆分。

### 1. 世界/区域子结构

- `world_state`
- `area_snapshot`
- `zone_metric`
- `sub_zone_chat_context`
- `scene_summary`
- `scene_events`

### 2. 角色子结构

- `player_state`
- `player_sheet_state`
- `npc_state`
- `team_state`
- `npc_relation_state`
- `team_relation_state`

### 3. 回合子结构

- `public_turn_state`
- `public_turn_round`
- `public_turn_segment_plan`
- `public_turn_settlement`
- `public_turn_pending_prompt`

### 4. 故事子结构

- `quest_state`
- `fate_state`
- `encounter_state`
- `memory_surface_state`

### 5. 资源子结构

- `spell_slot_state`
- `martial_point_state`
- `hp_state`
- `stamina_state`
- `inventory_state`
- `item_use_state`

## 四、当前实际会传给 AI 的内容入口

下面按模块列出现有系统里已经在送往 AI 的主要输入。  
这一节是“当前实现清单”，不是理想最终设计。

### 1. 主聊天 / 场景推进

主要输入：

- 主聊天结构化上下文 `main_turn_context_json`
- 近期子区域回合 `sub_zone_recent_turns`
- 当前区域 / 子区域信息
- 世界时间
- 玩家输入拆分结果
- 活跃任务
- 活跃命运线
- 活跃遭遇
- 可见 NPC
- 队伍成员
- GM narration / scene summary

相关入口：

- `backend/app/services/world_service.py`
- `backend/app/services/stream_chat_service.py`
- `backend/app/services/scene_interaction_service.py`

### 2. NPC 问候 / 私聊 / 公开目标 NPC / 旁观 NPC

主要输入：

- `roleplay_brief`
- `world_time_text`
- `knowledge_rules`
- `conversation_state`
- `scene_summary`
- `scene_context_json`
- `player_text`
- `player_action`
- `player_speech`
- `action_check_result`
- `context`

相关 prompt keys：

- `npc.greet.user.v2`
- `npc.chat.user.v2`
- `npc.public.targeted.user.v2`
- `npc.public.bystander.user.v2`

### 3. 队伍聊天 / 队友公开反应

主要输入：

- `roleplay_brief`
- `area_text`
- `scene_summary`
- `scene_context_json`
- `player_text`
- `gm_summary`
- 最近对话 / 记忆上下文

相关 prompt keys：

- `team.chat.user.v1`
- `team.public.reaction.user.v3`
- `team.private_chat.memory.user.v1`

### 4. 公开场景行动体意图 / 行动 / 回合结算

主要输入：

- `roleplay_brief`
- `scene_summary`
- `area_text`
- `scene_context_json`
- `player_text`
- `gm_summary`

相关 prompt keys：

- `scene.actor.intent.user.v1`
- `scene.actor.action.user.v2`
- `scene.round.resolve.user.v2`

### 5. 欲望 / 故事浮出

主要输入：

- `roleplay_brief`
- `scene_summary`
- `scene_context_json`

相关 prompt keys：

- `role.desire.seed.user.v1`
- `role.desire.surface.user.v1`
- `companion.story.seed.user.v1`
- `companion.story.surface.user.v1`

### 6. 区域声望

主要输入：

- `current_score`
- `scene_summary`
- `player_text`

相关 prompt key：

- `reputation.behavior.user.v1`

### 7. 遭遇系统

主要输入：

- `goal`
- `secret`
- `scene_summary`
- `temporary_npcs`
- `termination_conditions`
- `recent_steps`
- `player_prompt`
- `visible_npcs`
- `team_members`
- `encounter_mode`
- `player_presence`
- `minutes_elapsed`

相关 prompt keys：

- `encounter.generate.user.v3`
- `encounter.step.user.v4`
- `encounter.public_turn.summary.user.v1`
- `encounter.background.tick.user.v2`
- `encounter.escape.user.v1`
- `encounter.rejoin.user.v1`
- `encounter.debug.summary.user.v1`
- `encounter.outcome.package.user.v1`

### 8. 公共回合专用输入

这是当前最需要做“分层”的一块。

主要输入：

- `current_area`
- `world_time`
- `player_input`
- `active_quest`
- `active_fate`
- `active_encounter`
- `visible_npcs`
- `team_members`
- `sub_zone_recent_turns`
- `gm_narration`
- `actor_rows`
- `fallback_directives`
- `planner_overrides`
- `public_turn_segment_plan`
- `public_turn_settlement`
- `pending_interaction_prompt`
- `pending_opposed_prompt`
- `pending_attack_prompt`
- `pending_information_check_prompt`

相关 prompt keys：

- `public.turn.non_world_route.user.v1`
- `public.turn.segment.plan.system`
- `public.turn.attack_assessment.system`
- `public.turn.attack_response_classification.system`
- `public.turn.attack_outcome_narration.system`
- `public.turn.aoe_target_selection.system`
- `public.turn.opposed_resolution.system`
- `public.turn.damage_bundle.system`
- `public.turn.gm_push.system`

## 五、建议的最终分层定义

如果按实现目标来定义，我建议把所有 AI 输入最终统一成四层。

### 1. 固定基础层

本局开始时基本不变的事实。

- 世界规则
- 定义库
- 角色基础档案
- 区域基础背景
- prompt 输出约束
- 会话固定策略

### 2. 滚动摘要层

高频变化但已经被压缩过的长期背景。

- 最近若干回合摘要
- 当前场景简报
- 当前关键角色状态摘要
- 当前任务 / 遭遇 / 命运摘要

### 3. 增量变化层

每轮真正新增的变化。

- 事件
- 状态差分
- 资源变化
- 关系变化
- 检定 / 对抗 / 伤害 / 后果
- 结构化结算

### 4. 工具回执层

工具执行后的结果，通常是 agent loop 的闭环输入。

- 查表结果
- 掷骰结果
- 扣资源结果
- 目标解析结果
- AI 先前建议的最终裁定

## 六、当前实现里最适合做“差分”的对象

优先级从高到低：

- `public_turn_state`
- `npc_state`
- `team_state`
- `quest_state`
- `encounter_state`
- `scene_events`
- `resource_state`
- `relation_state`
- `memory_surface_state`

## 七、当前建议的变化检测策略

- 不建议用一个大对象全量深比较。
- 建议每个子结构单独维护版本号或 hash。
- 哪个子结构变了，就只把那一块打给 AI。
- 对于回合类数据，优先用事件驱动，而不是只靠快照对比。

## 八、待确认问题

下面这些点需要你审阅后再决定是否定稿：

- 基础层是否需要长期保留“原文”还是只保留“摘要”
- 滚动摘要的长度上限是多少
- NPC / 队伍 / 场景状态的最小变化粒度要拆到多细
- 公共回合的 `actor_rows` 是否允许直接进入 AI，还是只给摘要化后的 actor card
- 工具回执是否要统一成一套通用 `tool_result` 结构
- 是否要把“玩家输入原文”和“AI 解析后的意图”分开存放

## 九、结论

当前系统里传给 AI 的内容可以稳定归成三大块：

- **基础层**：世界规则、定义库、会话固定背景、稳定约束
- **变化层**：场景、角色、关系、任务、遭遇、公共回合、记忆表面、系统通知
- **工具回执层**：检定、查表、扣资源、对抗、结算、修正结果

后续如果要做“持续 session + agent loop”，最关键的不是让 AI 自己记忆，而是把这些层次分清，并让后端只把真正变化的子结构送进模型。
