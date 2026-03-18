# 公开回合系统实现计划（设计优先整合版）

基于 [docs/design/gamedesign/publicturndesign.md](/c:/Project/gptroleplayweb/docs/design/gamedesign/publicturndesign.md) 修订。

本版文档采用以下原则：
- 公开回合的总体结构以设计文档为主
- 当前实现不是需求上限，但其中已经验证有效的状态反馈机制必须保留
- 新系统不仅要有“回合流程”，还要有“动作结果如何改变世界状态”的正式规则

因此，这次修订不再走两个极端：
- 不是继续向当前轻量实现妥协
- 也不是只保留设计稿的流程骨架、丢掉当前已有的有效数值反馈

---

## 1. 系统定位

`public turn` 是主聊天公开场景的统一回合系统，用于承载：
- 叙事
- 探索
- 社交
- 局部冲突
- 战斗升级
- 环境演化

核心链路仍然是：

`叙事 -> 局部冲突 -> 战斗 -> 回归叙事`

但这个系统不应只有流程，还必须明确处理以下结果落点：
- 遭遇局势值变化
- 玩家对队友/在场 NPC 关系与好感的影响
- 区域或子区域声望变化
- 场景事件与日志沉淀
- 命运、任务、遭遇、队伍状态的联动

也就是说，公开回合既是“流程调度器”，也是“公开场景状态结算器”。

---

## 2. 设计目标

### 2.1 必须保留的设计目标

- 玩家可选择 `开始下一回合` 或 `优先行动`
- NPC、队友、隐藏 NPC 都可参与同一回合结构
- 抢先声明、常规推进、事态推进是明确阶段
- 攻击、对抗、AOE、环境破坏都能在公开回合内结算
- 玩家被针对时可插入反应检定
- 环境危险可以独立升级
- encounter 是公开回合内部的临时事件实例，而不是外部平行系统

### 2.2 必须保留的现有有效机制

以下现有方向应吸收进正式设计，而不是被删掉：
- 单个角色行动会对 encounter 的 `situation_value` / 局势值产生增减
- 玩家公开行动会对队友 affinity / trust 或 NPC relation 造成影响
- 公开回合结算会影响区域声望或 zone metric
- 回合结果会沉淀为 scene event 和 game log
- 玩家反应检定支持中断、恢复、继续执行

这些不是“临时实现细节”，而应成为公开回合的正式职责。

---

## 3. 目标架构

### 3.1 公开回合状态机

公开回合必须有独立状态机，而不是继续隐藏在主聊天内部流程里。

目标模型：

```python
class PublicTurnPhase(str, Enum):
    IDLE = "idle"
    INITIATIVE_DECLARATION = "initiative_declaration"
    INITIATIVE_EXECUTION = "initiative_execution"
    NORMAL_ADVANCEMENT = "normal_advancement"
    SITUATION_ADVANCEMENT = "situation_advancement"
    AWAITING_PLAYER_REACTION = "awaiting_player_reaction"


class EnvironmentRiskLevel(str, Enum):
    STABLE = "stable"
    RISKY = "risky"
    COLLAPSE = "collapse"


class InitiativeDeclaration(BaseModel):
    actor_id: str
    actor_type: Literal["player", "npc", "team", "hidden_npc"]
    actor_name: str
    declared_action: str
    dex_modifier: int
    roll_d20: int | None = None
    total_initiative: int | None = None
    is_hidden: bool = False
    revealed_by_declaration: bool = False


class PublicTurnImpact(BaseModel):
    actor_id: str
    actor_name: str
    action_summary: str
    check_outcome: Literal["none", "success", "failure", "critical_success", "critical_failure"] = "none"
    situation_delta: int = 0
    zone_reputation_delta: int = 0
    relation_deltas: list[dict[str, object]] = Field(default_factory=list)
    team_affinity_deltas: list[dict[str, object]] = Field(default_factory=list)
    hp_changes: list[dict[str, object]] = Field(default_factory=list)
    environment_shift: int = 0


class PublicTurnRound(BaseModel):
    round_id: str
    round_number: int
    phase: PublicTurnPhase
    initiative_declarations: list[InitiativeDeclaration]
    executed_actor_ids: list[str]
    impacts: list[PublicTurnImpact] = Field(default_factory=list)
    situation_triggered: bool = False
    situation_event: str | None = None
    environment_risk_level: EnvironmentRiskLevel = EnvironmentRiskLevel.STABLE
    situation_dc: int = 10
    pending_reaction_check_id: str | None = None
    created_at: str
    completed_at: str | None = None


class PublicTurnState(BaseModel):
    version: str = "0.1.0"
    current_round: PublicTurnRound | None = None
    round_history: list[PublicTurnRound] = Field(default_factory=list)
    max_history: int = 20
    environment_risk_level: EnvironmentRiskLevel = EnvironmentRiskLevel.STABLE
    situation_dc: int = 10
    awaiting_player_entry: bool = True
    updated_at: str
```

### 3.2 挂载位置

目标挂载结构：

```python
AreaSubZone
└── chat_context: SubZoneChatContext
    ├── recent_turns: list[SubZoneChatTurn]
    └── public_turn_state: PublicTurnState
```

原因：
- 公开回合是子区域公开场景状态的一部分
- 它要与聊天上下文一起保存
- 不能继续依赖 sidecar 文件承载主状态

### 3.3 pending turn 的地位

`PendingTurnState` 可以保留，但只能是暂停快照，不是主状态。

规则：
- `PublicTurnState` 是主状态
- `PendingTurnState` 只负责中断恢复
- 恢复后必须回写 `PublicTurnState.current_round.phase`

---

## 4. 回合入口与流程

### 4.1 玩家入口

主聊天必须提供两个入口：
- `开始下一回合`
- `优先行动`

定义：

#### 开始下一回合

玩家放弃抢先声明，系统直接进入常规推进阶段。

#### 优先行动

玩家声明立即行动，系统先进入抢先声明，再进入抢先执行。

### 4.2 标准流程

#### 路径 A：优先行动

```text
玩家点击【优先行动】
-> 玩家输入行动内容
-> 抢先声明阶段
-> AI 判断哪些 NPC / hidden NPC / 队友也要抢先
-> initiative 排序
-> 抢先执行阶段
-> 常规推进阶段
-> 事态推进阶段
-> 回合结束
```

#### 路径 B：开始下一回合

```text
玩家点击【开始下一回合】
-> 跳过抢先声明
-> 常规推进阶段
-> 事态推进阶段
-> 回合结束
```

### 4.3 回合的本质

每个回合必须同时完成两件事：
- 决定“谁在什么时候行动”
- 结算“这些行动对场景与状态造成了什么影响”

不能只做前者。

---

## 5. 抢先声明与抢先执行

### 5.1 抢先声明的用途

抢先声明用于处理：
- 突然行动
- 先手攻击
- 打断
- 紧急反应
- 埋伏者现身

参与主体包括：
- 玩家
- 在场 NPC
- 队友
- 隐藏 NPC

### 5.2 触发逻辑

当玩家行为具有明确冲突性时，AI GM 必须判断是否有其他主体也加入抢先。

典型触发：
- 攻击
- 威胁
- 阻止
- 抢夺
- 强闯
- 明显敌对

### 5.3 initiative

默认排序：

`dex modifier + d20`

抢先阶段执行过行动的角色，不能在本回合常规推进阶段再次行动。

这必须由状态机硬约束，而不是仅依赖 prompt。

---

## 6. 常规推进阶段

默认顺序：

`玩家 -> 关键 NPC -> 普通 NPC`

处理内容：
- 对话
- 探索
- 社交互动
- 非抢先冲突行为

已在抢先阶段执行过的角色直接跳过。

---

## 7. 角色行动结算

### 7.1 普通行为

流程：

`行动描述 -> 角色语言 -> 检定 -> GM 结果描述 -> 局势检定（可选）-> 状态影响写入`

### 7.2 对抗行为

流程：

`行动描述 -> 行动方语言 -> 双方并行检定 -> 目标方语言 -> GM 结果描述 -> 状态影响写入`

### 7.3 攻击行为

命中：

`d20 + attack >= AC`

命中后：
- 伤害计算
- 需要时先做豁免
- 生命值变化写入
- 若目标为玩家且需要即时应对，则插入反应检定

### 7.4 AOE 行为

- 群体豁免
- 逐目标计算结果
- 生成群体反应
- 推进环境与局势值

### 7.5 环境破坏行为

例如：
- 砸门
- 推倒重物
- 攻击支撑结构
- 在狭窄空间释放爆炸法术

除普通结算外，还必须触发：
- 事态检定
- 环境风险升级判断
- 必要时插入额外事态推进

---

## 8. 判定体系

公开回合必须统一支持：

### 8.1 静态检定

`d20 + modifier >= DC`

### 8.2 对抗检定

`d20 + modifier vs d20 + modifier`

### 8.3 攻击检定

`d20 + attack >= AC`

### 8.4 豁免检定

`d20 + save >= DC`

### 8.5 事态检定

`d20 + situational >= Situation DC`

当前通用 `action_check()` 可以作为底层实现之一，但不能继续代替完整公开回合规则。

---

## 9. 状态反馈层

这是本次修订新增强调的核心部分。

公开回合中的每个角色行动，不仅要产出叙事文本，还要显式产出状态影响。

### 9.1 遭遇局势值

必须保留并正式化当前已有的思路：
- 每个行动都可产生 `situation_delta`
- 多个行动的 `situation_delta` 汇总为本回合 encounter 局势变化
- `situation_value` 是公开回合与 encounter 之间的关键连接点

设计要求：
- 玩家行动、NPC 行动、队友行动都可推动局势值
- 成功、失败、暴击、失误都可以映射到不同幅度的局势变化
- 事态推进阶段可继续修改局势值

### 9.2 关系与好感

必须保留当前“公开行动影响关系”的方向，并升级为正式机制。

要求：
- 玩家公开行为可影响队友 affinity / trust
- 玩家公开行为可影响 NPC relation
- 影响应与行动结果、行动立场、是否帮助/拖累他人有关
- 这些变化必须可追溯到具体回合与具体行动

### 9.3 区域声望

公开回合结算可改变区域或子区域声望。

适用场景：
- 玩家在公开场合帮助众人
- 玩家制造明显混乱
- 玩家伤害公众利益
- 玩家压制灾害或成功控制局势

### 9.4 生命值与战斗结果

若公开回合中发生战斗行为：
- HP 变化必须纳入 impact 记录
- 不应再把战斗影响悬空在回合外

### 9.5 scene events 与 game logs

每回合至少应沉淀：
- 动作事件
- 检定结果事件
- 反应检定事件
- 回合总结事件
- 必要的 game log

scene events 是前端表现层输入，game logs 是系统追踪层输入，两者都必须保留。

---

## 10. 环境风险层

### 10.1 风险等级

独立环境风险等级：
- `stable`
- `risky`
- `collapse`

### 10.2 升级条件

- 破坏性行为失败
- AOE 误伤环境
- 事态检定失败
- 连续失控
- 剧情灾害触发

### 10.3 后果

#### stable
- 场景稳定

#### risky
- 持续环境压力
- 回合末可能插入额外事态推进

#### collapse
- 必然触发严重环境后果
- 可导致伤害、封锁、坍塌、逃生压力、剧情转折

环境风险层不能替代 `situation_value`，两者职责不同：
- `situation_value` 更偏 encounter / 场面压力
- `environment_risk_level` 更偏环境灾害与结构安全

---

## 11. 事态推进阶段

事态推进由 GM 或 AI GM 执行，可在以下时机触发：
- 回合末必定一次
- 任意破坏性行为后插入
- 环境风险达到 `risky` 或 `collapse`
- hidden NPC 暴露引发连锁反应

作用：
- 推进环境变化
- 推进剧情
- 改变 NPC 立场
- 升级 encounter
- 生成强制反应事件
- 对局势值、声望、关系产生二次影响

---

## 12. encounter 与 hidden NPC

### 12.1 encounter

`encounter` 是公开回合内的临时事件实例。

生命周期：
- 生成
- 运行
- 升级
- 结束

它必须与公开回合共享同一套推进与结算逻辑。

### 12.2 hidden NPC

hidden NPC 必须是一等机制：
- 默认不可见
- 可在抢先声明中介入
- 可因攻击或敌对行为暴露
- 可通过感知检定揭露

### 12.3 玩家隐藏状态

如果玩家处于潜行/隐藏状态：
- NPC 必须进行感知检定
- 不能默认所有公开角色都能无条件响应玩家

---

## 13. UI 与 API

### 13.1 前端 UI

主聊天目标 UI：

```text
[开始下一回合]   [优先行动]
```

执行中：
- 隐藏普通输入
- 显示当前回合、当前阶段、当前行动者
- 等待反应时弹出反应检定窗口

### 13.2 目标 API

```python
POST /api/v1/public-turn/entry
POST /api/v1/public-turn/continue
POST /api/v1/public-turn/reaction-check
```

目标响应：

```python
class PublicTurnResponse(BaseModel):
    session_id: str
    phase: PublicTurnPhase
    narration: str
    scene_events: list[SceneEvent]
    reaction_check: PlayerReactionCheck | None
    round_completed: bool
    awaiting_entry: bool
    public_turn_state: PublicTurnState
```

现有 `scene/public-state`、`pending-turns/current` 等接口只作为兼容层，不定义最终架构。

---

## 14. 与现有代码的整合策略

### 14.1 可复用

- `pending_turn_service.py`
  - 保留为暂停/恢复机制
- `reaction_check_service.py`
  - 保留为反应检定中断/继续机制
- `action_check()`
  - 保留为底层检定实现基础
- 当前 relation / reputation / encounter delta / log 写回逻辑
  - 保留为新回合结算层的参考实现

### 14.2 必须改造

- `SubZoneChatContext`
  - 新增 `public_turn_state`
- `PublicSceneState`
  - 降为公开回合的只读视图，不再承担主状态职责
- `public_scene_runtime_v2.py`
  - 拆分为候选角色筛选、AI 声明生成、回合结算辅助模块
- 主聊天与流式主聊天
  - 改为围绕 `PublicTurnState.phase` 执行

### 14.3 必须吸收而不是丢弃的现有机制

- 角色行动的 `situation_delta`
- 对关系 / affinity / trust 的影响
- 区域 reputation / zone metric 的影响
- scene events 与 game logs 沉淀

这些不是兼容代码，而是新系统正式结算层的一部分。

### 14.4 应废弃的旧假设

- 用候选优先级代替 initiative phase
- 用 pending turn sidecar 代替主状态
- 用 encounter pressure 代替环境风险层
- 把 public scene 视为 public turn 的最终形态

### 14.5 battle 策略

目标不是简单并行保留 battle，而是：
- battle 规则下沉为公共结算模块
- public turn 调用这些模块
- 逐步让 public turn 吸收 battle 的主流程职责

---

## 15. 实施阶段

### P0：建模与存档

- [ ] 新增 `PublicTurnState` 相关模型
- [ ] 在 `SubZoneChatContext` 挂载 `public_turn_state`
- [ ] 为旧存档补迁移
- [ ] 定义 `PublicTurnImpact`

### P1：回合入口与阶段机

- [ ] 新增两按钮入口
- [ ] 新增 `/api/v1/public-turn/*`
- [ ] 建立 phase 状态切换
- [ ] 接入反应检定中断/恢复

### P2：抢先与常规推进

- [ ] AI 抢先声明判断
- [ ] hidden NPC 介入
- [ ] initiative 排序
- [ ] 抢先后跳过已执行角色

### P3：状态结算层

- [ ] 每个行动生成 `PublicTurnImpact`
- [ ] 接入 `situation_delta`
- [ ] 接入 relation / affinity / trust 变化
- [ ] 接入 reputation / zone metric 变化
- [ ] 接入 HP 与伤害结果
- [ ] 统一 scene event / game log 输出

### P4：环境与事态

- [ ] 环境风险层
- [ ] 事态推进阶段
- [ ] collapse 后果

### P5：系统整合

- [ ] encounter 完整纳入公开回合
- [ ] hidden NPC 完整纳入公开回合
- [ ] quest / fate / team 挂接
- [ ] battle 结算模块下沉并统一

---

## 16. 验收标准

### 16.1 流程验收

- [ ] 玩家可使用 `开始下一回合`
- [ ] 玩家可使用 `优先行动`
- [ ] 公开回合具备完整 phase 状态机
- [ ] 抢先执行后不会在常规阶段重复行动
- [ ] 玩家受威胁时可插入反应检定

### 16.2 结算验收

- [ ] 每个行动都能生成明确 impact
- [ ] 回合结算可修改 `situation_value`
- [ ] 回合结算可修改队友 affinity / trust 或 NPC relation
- [ ] 回合结算可修改区域/子区域声望
- [ ] 回合结算可写入 HP 变化、scene events、game logs

### 16.3 系统整合验收

- [ ] encounter 与 hidden NPC 都能纳入公开回合
- [ ] 环境风险层独立运作
- [ ] public turn 能承接战斗推进，而不是冲突时切走到另一套主系统

---

## 17. 结论

这次修订后的结论是：

公开回合应当以设计文档为主建立统一状态机与阶段流程，但新系统必须显式保留并正式化当前已经有价值的状态反馈机制，尤其是：
- 动作对 encounter 局势值的影响
- 动作对关系、好感、信任的影响
- 动作对区域声望的影响
- 回合结果的事件与日志沉淀

最终目标不是只做一个“更像设计稿的流程外壳”，而是做一个既符合设计、又能真实推进世界状态的公开回合系统。

**修订日期**：2026-03-18
**版本**：v4.0
