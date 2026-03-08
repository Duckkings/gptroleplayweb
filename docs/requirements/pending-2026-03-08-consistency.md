# 游戏状态一致性治理需求文档（2026-03-08）

更新时间：2026-03-08

对照来源：
- `docs/requirements/pending-2026-03-01.md`
- `docs/technical/area-technical.md`
- `docs/technical/fate-technical.md`
- `docs/technical/quest-technical.md`
- `docs/technical/encounter-technical.md`
- `backend/app/services/world_service.py`
- `backend/app/services/fate_service.py`
- `backend/app/services/quest_service.py`
- `backend/app/services/encounter_service.py`
- `backend/app/services/chat_service.py`

## 1. 背景与问题定义

当前项目已经具备地图、区块、NPC 单聊、命运线、任务、遭遇等基础能力，但这些系统仍然主要以“各自读取当前存档的一部分状态、各自拼 prompt、各自解释世界”的方式运行。

这会导致以下高频问题：
- 地图重生成后，命运线/任务/遭遇仍引用旧地图中的区域、人物或事件。
- 命运线提及当前地图中不存在的 NPC，但玩家与当前地图 NPC 对话时，NPC 又会“知道”这些不存在实体。
- NPC 对话、主聊天、命运线、任务、遭遇对“当前世界事实”的理解不一致。
- AI 输出的文本可能引用未定义、已失效或不在当前地图中的对象，后端没有统一校验和修正。

该问题不是单纯的 prompt 质量问题，而是“缺少统一事实源、缺少状态版本、缺少引用校验、缺少知识边界”的系统性问题。

## 2. 目标与边界

### 2.1 本期目标
- 建立统一的游戏事实源视图，供命运线、任务、遭遇、主聊天、NPC 对话共享使用。
- 明确地图重生成、命运线重生成、任务推进、遭遇结算后的状态失效与重建规则。
- 禁止 AI 在未授权范围内自由引用 NPC、区域、任务、遭遇等实体。
- 为 NPC 对话建立“可知事实边界”，避免 NPC 凭空知道当前世界不存在或未接触的内容。
- 将“规则判定”和“自然语言生成”拆开，关键事实由代码判定，AI 仅负责生成文案。

### 2.2 本期不做
- 不做通用长期记忆图谱。
- 不做复杂世界模拟器或全 NPC 社会关系自动演化。
- 不做跨存档共享世界状态。
- 不做开放式“AI 自行创造并落盘新实体”的能力。

## 3. 现状结论

### 3.1 当前风险点
- 地图强制重生成仅清理 `map_snapshot / area_snapshot / role_pool`，没有同步处理 `fate_state / quest_state / encounter_state`，会残留旧剧情引用。
- 命运线默认生成逻辑直接绑定当前 `role_pool[0]` 和当前区域信息，生成后不具备随世界版本变化自动失效的能力。
- 任务与遭遇的 AI 生成逻辑使用当前区域、当前任务、当前命运阶段作为输入，但没有统一上下文构建器，也没有对输出引用做严格校验。
- NPC 对话主要依赖角色卡和历史对话，没有显式限制“只能基于当前合法世界事实回答”。
- 主聊天工具 `get_player_state` 当前不返回完整剧情状态，主聊天 AI 无法获取统一的 fate/quest/encounter 事实视图。

### 3.2 本质原因
- 没有统一的事实快照层。
- 没有世界版本号与依赖版本记录。
- 没有结构化引用校验。
- 没有按场景裁剪的知识边界。

## 4. 核心设计原则

### 4.1 单一事实源
- 所有系统都必须从同一份“结构化上下文快照”读取事实，不允许每个服务自己随意抓取存档片段拼 prompt。

### 4.2 版本驱动失效
- 世界地图、区块结构、NPC 集合发生重构时，相关剧情状态必须按规则失效、归档或重建。

### 4.3 引用先约束后生成
- AI 只能从后端提供的候选实体列表中选择引用目标，不能自由发明核心实体并直接落盘。

### 4.4 规则代码化
- 地图是否存在、NPC 是否存在、任务是否完成、遭遇是否已结算、命运阶段是否可推进等事实判定必须由后端代码完成。
- AI 只负责文案、摘要、氛围文本、台词润色。

### 4.5 知识按角色裁剪
- NPC 只能知道它“应当知道”的事实。
- 主聊天/GM 视角可以看到更完整的事实。
- 命运线、任务、遭遇各自拿到适合自己的上下文切片。

## 5. 需求总览

### 5.1 需要新增的核心能力
- 统一上下文构建器。
- 世界版本号与依赖版本记录。
- 实体引用校验器。
- NPC 可知事实快照。
- 状态失效与归档策略。
- 一致性调试与日志能力。

## 6. 数据模型需求

### 6.1 SaveFile 新增字段
- [ ] 新增 `world_state` 或等价结构，用于记录全局世界一致性元信息。
- [ ] 至少包含：
  - `world_revision: int`
  - `map_revision: int`
  - `last_consistency_check_at: str | null`
  - `last_world_rebuild_at: str | null`

### 6.2 统一上下文快照模型

建议新增以下只读构建模型，不要求单独持久化为主状态，但允许写入日志或调试输出。

#### GlobalStorySnapshot
- [ ] `session_id`
- [ ] `world_revision`
- [ ] `map_revision`
- [ ] `current_zone_id`
- [ ] `current_sub_zone_id`
- [ ] `current_zone_name`
- [ ] `current_sub_zone_name`
- [ ] `clock`
- [ ] `player_summary`
- [ ] `visible_zone_ids`
- [ ] `visible_sub_zone_ids`
- [ ] `available_npc_ids`
- [ ] `available_npcs`
- [ ] `active_quest_ids`
- [ ] `active_quests`
- [ ] `pending_quest_ids`
- [ ] `current_fate_id`
- [ ] `current_fate_phase_id`
- [ ] `recent_encounter_ids`
- [ ] `recent_game_log_refs`

#### NpcKnowledgeSnapshot
- [ ] `npc_role_id`
- [ ] `npc_name`
- [ ] `world_revision`
- [ ] `map_revision`
- [ ] `current_zone_id`
- [ ] `current_sub_zone_id`
- [ ] `self_profile_summary`
- [ ] `known_player_relation`
- [ ] `known_local_npc_ids`
- [ ] `known_local_zone_ids`
- [ ] `known_active_quest_refs`
- [ ] `recent_dialogue_summary`
- [ ] `forbidden_entity_ids`
- [ ] `response_rules`

### 6.3 各系统状态新增依赖信息

#### FateLine / FatePhase
- [ ] 新增 `source_world_revision`
- [ ] 新增 `source_map_revision`
- [ ] 新增 `bound_entity_refs`
- [ ] 新增 `invalidated_reason`

#### QuestEntry
- [ ] 新增 `source_world_revision`
- [ ] 新增 `source_map_revision`
- [ ] 新增 `entity_refs`
- [ ] 新增 `invalidated_reason`
- [ ] 新增状态值 `invalidated`

#### EncounterEntry
- [ ] 新增 `source_world_revision`
- [ ] 新增 `source_map_revision`
- [ ] 新增 `entity_refs`
- [ ] 新增 `invalidated_reason`
- [ ] 新增状态值 `invalidated`

#### NpcRoleCard
- [ ] 新增 `source_world_revision`
- [ ] 新增 `source_map_revision`
- [ ] 新增 `knowledge_scope`

### 6.4 实体引用结构

建议新增统一结构 `EntityRef`：
- [ ] `entity_type: zone | sub_zone | npc | item | quest | encounter | fate | fate_phase`
- [ ] `entity_id`
- [ ] `label`
- [ ] `required: bool`
- [ ] `source: system | ai | fallback`

要求：
- 命运线、任务、遭遇所有涉及实体引用的地方优先用 `entity_id`，`label` 仅用于展示。
- 不允许仅靠纯文本名称作为主引用。

## 7. 一致性规则需求

### 7.1 世界版本规则
- [ ] 新建存档时 `world_revision=1`，`map_revision=1`。
- [ ] 普通移动、对话、交互、遭遇结算、任务推进不增加 `map_revision`。
- [ ] 强制重生成地图时必须递增 `map_revision`。
- [ ] 若地图重生成造成区域/NPC 集合语义重建，必须同时递增 `world_revision`。

### 7.2 地图重生成后的失效规则
- [ ] 强制重生成地图后，所有引用旧地图 NPC/区域的 fate/quest/encounter 必须进入失效处理流程。
- [ ] 失效处理流程支持以下结果：
  - `superseded`：旧主线/旧支线被世界更新替代。
  - `invalidated`：引用实体已不存在，内容失效。
  - `completed`：已完成内容保持历史状态，不回滚。
- [ ] 地图重生成后不得保留“指向不存在 NPC / zone / sub_zone 的 active 或 pending 状态”。

### 7.3 命运线规则
- [ ] 命运线生成必须记录生成时的 `world_revision/map_revision`。
- [ ] 命运线绑定的 NPC、区域、遭遇目标必须写入结构化 `bound_entity_refs`。
- [ ] 命运线阶段推进前必须先做引用校验。
- [ ] 若关键引用实体不存在：
  - 该阶段不得继续推进。
  - 必须标记 `invalidated_reason`。
  - 允许通过 Debug 或自动策略触发“重生成命运线”。

### 7.4 任务规则
- [ ] 任务发布时必须记录依赖的实体引用。
- [ ] 任务目标完成判定只能基于当前事实源，不允许基于 AI 文本推断。
- [ ] 若任务引用实体已失效：
  - `pending_offer` 任务直接失效或撤回。
  - `active` 任务进入 `invalidated` 或 `superseded`。
  - `completed` 保持不变。

### 7.5 遭遇规则
- [ ] 遭遇生成时必须记录依赖实体引用。
- [ ] 遭遇呈现前必须再次校验其相关区域、相关任务、相关命运阶段是否仍有效。
- [ ] 若遭遇依赖对象已失效，则不得弹窗呈现，直接改为 `invalidated` 或丢弃。

### 7.6 NPC 对话规则
- [ ] NPC 对话前必须构建 `NpcKnowledgeSnapshot`。
- [ ] NPC 只能谈论以下范围：
  - 自身信息
  - 当前所在区块合法存在的 NPC/区域
  - 与玩家已发生过的对话和关系
  - 明确属于该 NPC 已知的任务/命运阶段摘要
- [ ] 若玩家询问不存在实体或当前知识边界外内容，NPC 应返回“不知道 / 没听说过 / 不确认”，不得编造。
- [ ] NPC 历史对话不得被视为绝对事实源；若历史中提到的实体已被世界版本淘汰，应自动降级为“旧传闻”或忽略。

### 7.7 主聊天规则
- [ ] 主聊天使用工具获取状态时，必须能拿到统一的剧情事实快照，而不是只拿玩家和地图。
- [ ] 主聊天生成叙事时，不得引用当前事实快照外的核心实体。

## 8. 上下文构建需求

### 8.1 新增统一上下文构建模块
- [ ] 新增独立模块，例如：
  - `backend/app/services/story_context_service.py`
  - 或 `backend/app/services/consistency_service.py`

### 8.2 对外能力
- [ ] `build_global_story_snapshot(save)`
- [ ] `build_npc_knowledge_snapshot(save, npc_role_id)`
- [ ] `validate_entity_refs(save, refs)`
- [ ] `invalidate_stale_content(save)`
- [ ] `reconcile_after_world_regeneration(save)`

### 8.3 使用要求
- [ ] fate/quest/encounter/npc_chat/chat_service 必须接入统一上下文构建器。
- [ ] 不允许各模块继续自行从 `save` 中散落抓取字段拼 prompt 作为最终方案。

## 9. AI 输出约束需求

### 9.1 候选实体输入
- [ ] 当 AI 需要生成命运线、任务、遭遇时，后端必须传入：
  - `allowed_zone_ids`
  - `allowed_sub_zone_ids`
  - `allowed_npc_ids`
  - 可选的 `allowed_quest_ids`
  - 可选的 `allowed_fate_phase_ids`

### 9.2 输出结构
- [ ] AI 输出中涉及实体引用时，必须输出 `entity_id` 或等价字段。
- [ ] 后端必须验证这些 ID 是否存在、是否属于当前世界版本、是否在允许范围内。

### 9.3 校验失败策略
- [ ] 校验失败时不得直接落盘。
- [ ] 必须执行以下之一：
  - 回退到 deterministic fallback
  - 自动重试一次
  - 记录日志并报错给调用方

### 9.4 AI 工具协议补齐需求

本节用于补齐“一致性治理”范围内 AI 可调用工具的需求。对应技术落地应与 `docs/technical/ai-tool-protocol.md` 对齐，但本节优先定义业务需求边界。

#### 9.4.1 工具分层
- [ ] AI 工具必须分为两类：
  - 只读工具：读取状态、快照、索引、知识边界、日志。
  - 写入工具：推进世界、生成内容、执行动作、触发调试或一致性协调。
- [ ] 默认仅主聊天/GM 代理允许调用写入工具。
- [ ] NPC 对话默认不允许直接调用会改变全局世界状态的工具。

#### 9.4.2 必备只读工具

##### `get_story_snapshot`
- [ ] 用途：返回统一 `GlobalStorySnapshot`，作为主聊天、命运线、任务、遭遇相关推理的唯一高层事实源。
- [ ] 返回内容必须至少包含：
  - `world_revision`
  - `map_revision`
  - 当前区域/子区块
  - 当前可用 NPC 列表
  - 当前任务状态摘要
  - 当前命运阶段摘要
  - 最近遭遇摘要
- [ ] 主聊天在需要判断世界事实时，应优先调用此工具，而不是拼接多个旧工具结果。

##### `get_npc_knowledge`
- [ ] 用途：返回指定 NPC 的 `NpcKnowledgeSnapshot`。
- [ ] 输入至少包含 `npc_role_id`。
- [ ] 返回必须包含：
  - NPC 当前合法可知事实
  - 当前合法可谈论实体列表
  - 禁止引用实体列表
  - 回答边界规则
- [ ] NPC 对话链路若使用工具模式，必须优先依赖此工具，而不是直接读取完整存档。

##### `get_entity_index`
- [ ] 用途：返回当前世界可引用实体索引，供 AI 选择合法引用对象。
- [ ] 至少支持输出：
  - `zone_ids`
  - `sub_zone_ids`
  - `npc_ids`
  - `quest_ids`
  - `encounter_ids`
  - `fate_phase_ids`
- [ ] 支持按作用域过滤：
  - `scope=current_zone`
  - `scope=current_sub_zone`
  - `scope=global`

##### `get_consistency_status`
- [ ] 用途：返回当前一致性状态摘要，供调试、主聊天或系统自检使用。
- [ ] 至少包含：
  - 当前 revision 信息
  - 最近一次一致性校验时间
  - 待处理失效项数量
  - 最近一次失效/归档摘要

##### `get_gameplay_state`
- [ ] 作为 `get_player_state` 的升级或替代工具。
- [ ] 若保留旧 `get_player_state`，则必须补齐 fate/quest/encounter/world revision 相关字段；否则应新增 `get_gameplay_state` 作为统一读取接口。
- [ ] 不允许主聊天继续长期依赖只含玩家与地图的残缺状态。

#### 9.4.3 必备写入工具

##### `run_consistency_check`
- [ ] 用途：主动执行一次一致性校验与协调。
- [ ] 可用于：
  - 地图重生成后
  - 存档迁移后
  - Debug 面板手动触发
  - AI 在检测到状态冲突时请求系统自检
- [ ] 返回必须包含：
  - 是否发现失效项
  - 处理了哪些 fate/quest/encounter
  - 是否刷新了 world snapshot

##### `invalidate_stale_content`
- [ ] 用途：将已确认失效的命运线/任务/遭遇标记为 `invalidated` 或 `superseded`。
- [ ] 默认不对普通聊天开放，主要用于系统流程或 Debug。
- [ ] 调用必须记录详细审计日志。

##### `rebuild_story_context`
- [ ] 用途：在世界状态变化后重建统一事实快照缓存或派生摘要。
- [ ] 若实现中不使用缓存，也应提供等价内部能力，不可省略该需求含义。

##### `regenerate_fate_line`
- [ ] 用途：在当前命运线依赖失效时重生成命运线。
- [ ] 若开放给 AI 调用，必须要求：
  - 当前命运线已被判定失效或用户明确要求
  - 调用前完成一致性校验
  - 调用后自动处理旧 fate quest 的 `superseded/invalidated`

##### `publish_quest`
- [ ] 若 AI 通过工具发布任务，任务草稿必须基于 `GlobalStorySnapshot + allowed entity refs` 生成。
- [ ] 后端不得接受纯文本无结构引用的任务草稿直接落盘。

##### `check_or_generate_encounter`
- [ ] 用途：统一遭遇检查与生成入口，避免 AI 绕过一致性校验直接写入 encounter。
- [ ] 必须在内部执行：
  - 当前世界版本检查
  - 关联任务/命运阶段有效性检查
  - 实体引用校验

#### 9.4.4 工具调用顺序约束
- [ ] AI 在需要“判断当前世界真相”时，应先调用只读快照类工具，再决定是否调用写入工具。
- [ ] 涉及地图/NPC/任务/命运/遭遇引用的生成行为，应遵循：
  1. 读取 `get_story_snapshot` 或 `get_entity_index`
  2. 生成结构化候选结果
  3. 后端执行引用校验
  4. 通过后才允许落盘
- [ ] 若 AI 想对某个 NPC 作出越界叙述，系统必须先用 `get_npc_knowledge` 校验边界。

#### 9.4.5 工具响应结构需求
- [ ] AI 工具返回应统一包含：
  - `ok`
  - `error_code`
  - `message`
  - `tool_payload`
  - 可选 `state_patch`
  - 可选 `consistency_patch`
- [ ] 写入工具返回中应明确标识：
  - 是否修改了 `world_revision`
  - 是否修改了 `map_revision`
  - 是否触发一致性协调
  - 是否产生失效项

#### 9.4.6 审计与风控
- [ ] 所有 AI 工具调用必须记录：
  - `session_id`
  - `tool_name`
  - `request_id`
  - `args_hash`
  - `duration_ms`
  - `status`
  - `world_revision_before`
  - `world_revision_after`
  - `map_revision_before`
  - `map_revision_after`
- [ ] 写入工具必须支持幂等保护。
- [ ] 高风险工具必须具备白名单约束：
  - `invalidate_stale_content`
  - `regenerate_fate_line`
  - 一切 revision 递增相关工具

#### 9.4.7 前端联动需求
- [ ] 聊天响应中的 `tool_events` 必须能区分：
  - 普通读取工具
  - 世界状态变更工具
  - 一致性修复工具
- [ ] 若 `tool_events` 包含 revision 变化或一致性协调，前端必须刷新：
  - map/area
  - quest state
  - encounter state
  - fate state
  - 角色池/NPC 面板
- [ ] 若 AI 工具触发了失效处理，前端应显示明确说明，而不是只显示模糊成功提示。

## 10. 失效与重建流程需求

### 10.1 地图强制重生成
- [ ] 先递增 `map_revision/world_revision`
- [ ] 重建 `map_snapshot / area_snapshot / role_pool`
- [ ] 运行一致性协调器：
  - 校验 fate_state
  - 校验 quest_state
  - 校验 encounter_state
  - 标记失效项
  - 必要时归档旧命运线
- [ ] 生成一条玩家可见日志，说明世界结构已更新

### 10.2 命运线重生成
- [ ] 若当前命运线依赖旧版本世界，允许直接归档旧线并重生成。
- [ ] 旧命运任务若未完成，应转为 `superseded` 或 `invalidated`，不能继续活跃。

### 10.3 NPC 角色池重建
- [ ] NPC 重建后不得保留对不存在 NPC 的 relation 引用。
- [ ] 对话日志可保留，但若对应实体已不在当前世界，可标记为旧版本历史，不得继续作为当前事实直接喂给 AI。

## 11. 日志与调试需求

### 11.1 新增日志类型
- [ ] `world_revision_bumped`
- [ ] `consistency_reconciled`
- [ ] `fate_invalidated`
- [ ] `quest_invalidated`
- [ ] `encounter_invalidated`
- [ ] `npc_knowledge_guard_blocked`
- [ ] `entity_ref_validation_failed`

### 11.2 Debug 能力
- [ ] Debug 面板支持查看当前：
  - `world_revision`
  - `map_revision`
  - 当前 GlobalStorySnapshot
  - 指定 NPC 的 NpcKnowledgeSnapshot
  - 最近一次一致性协调结果
- [ ] Debug 面板支持手动执行：
  - `运行一致性校验`
  - `清理失效任务/遭遇`
  - `重建命运线`

## 12. 前端交互需求

### 12.1 玩家反馈
- [ ] 当地图重生成导致旧命运线/旧任务失效时，前端必须给出明确反馈，而不是静默消失。
- [ ] 失效项在任务面板/命运面板中需要有可见状态说明。

### 12.2 文案要求
- [ ] 失效反馈应解释为“世界结构已变化 / 线索已中断 / 旧传闻不再可靠”，而不是程序错误。

## 13. 兼容性要求

### 13.1 老存档补齐
- [ ] 老存档自动补齐 `world_revision/map_revision` 默认值。
- [ ] 老存档加载后首次进入游戏时，应自动运行一次一致性协调。

### 13.2 平滑迁移
- [ ] 对已完成任务、已完成命运阶段、已结算遭遇不做破坏性回滚。
- [ ] 对活跃中的旧引用内容进行最小必要失效处理。

## 14. 验收标准

### 14.1 关键验收场景
- [ ] 强制重生成地图后，当前命运线不能再引用旧地图 NPC。
- [ ] 强制重生成地图后，旧任务/旧遭遇如果引用已不存在实体，会被正确标记为 `superseded` 或 `invalidated`。
- [ ] 玩家询问当前地图 NPC 一个不存在于当前地图且不在其知识边界内的角色时，NPC 不会编造信息。
- [ ] 命运线、任务、遭遇生成结果中的所有结构化实体引用都能通过校验。
- [ ] 主聊天、NPC 对话、任务、遭遇在同一时刻对“当前区域 / 当前 NPC / 当前任务状态”的描述一致。

### 14.2 回归要求
- [ ] 不破坏当前地图移动、对话、任务接受、遭遇结算基础流程。
- [ ] 老存档能正常加载并自动迁移。

## 15. 建议实施顺序

### P0 基础止血
- [ ] 地图重生成时同步处理 `fate_state / quest_state / encounter_state`
- [ ] 新增 `world_revision / map_revision`
- [ ] 新增最基础的失效标记与日志

### P1 统一事实源
- [ ] 抽出 `GlobalStorySnapshot`
- [ ] fate/quest/encounter 全部接入统一上下文构建器
- [ ] 主聊天工具返回完整剧情状态

### P2 知识边界与引用校验
- [ ] 新增 `NpcKnowledgeSnapshot`
- [ ] NPC 对话接入知识边界
- [ ] AI 生成接入候选实体约束和输出校验

### P3 调试与补强
- [ ] Debug 面板支持一致性调试
- [ ] 增补单元测试与回归测试
- [ ] 补文档和技术细节说明

## 16. 最低测试清单

- [ ] 单元测试：地图重生成后会提升 revision 并触发失效协调。
- [ ] 单元测试：引用不存在 NPC 的命运阶段会被阻止推进。
- [ ] 单元测试：引用不存在 sub_zone 的任务会被置为 `invalidated`。
- [ ] 单元测试：遭遇在呈现前校验失败时不会进入弹窗。
- [ ] 单元测试：NPC 询问越界知识时返回受限答复。
- [ ] 集成测试：地图重生成 -> 任务/命运/遭遇状态正确刷新。
- [ ] 集成测试：主聊天与 NPC 对话基于同一份世界快照。

## 17. 开放问题

- [ ] 命运线失效后是否默认自动重生成，还是只给 Debug/玩家手动触发。
- [ ] `invalidated` 与 `superseded` 是否都需要在前端显式展示。
- [ ] 历史对话中提到旧世界实体时，是全部隐藏，还是保留为“旧传闻”文本。
- [ ] 普通地图扩展生成新区域时，是否递增 `map_revision`，还是仅强制重生成才递增。

## 18. 结论

本需求的核心不是“给 AI 更多上下文文本”，而是建立一套可验证、可失效、可重建的统一事实体系。只有在世界状态、剧情状态、NPC 知识边界、AI 引用约束四者同时成立时，地图、命运线、任务、遭遇、对话之间才会稳定一致。
