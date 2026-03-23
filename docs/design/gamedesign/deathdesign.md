# 死亡、濒死与死亡豁免设计

> 更新日期：2026-03-22
> 本文是当前 `HP <= 0`、濒死、死亡豁免、死亡结果窗口、子区块死亡清理的唯一详细设计口径。
> 适用范围：公开回合、遭遇、战斗，以及这些系统触发的结构化交互。

## 1. 目标与废弃口径

### 1.1 目标

- 用一套统一规则覆盖公开回合、遭遇、战斗中的 `HP <= 0` 流程。
- 明确区分玩家、队友 NPC、普通 NPC、遭遇临时 NPC 在 `0 HP` 时的分流。
- 让濒死状态与现有 `world / non_world` 公开互动规则兼容，而不是另开一套独立交互体系。
- 将“死亡后的玩家选择”“队友死亡后的离队处理”“普通 NPC 死亡后的区块清理”写成可直接落地的设计。

### 1.2 本版废弃的旧口径

以下内容不再作为当前死亡设计的约束：

- 不再坚持“死亡豁免必须复用 `reaction_prompt`，不新增专用 UI”。
- 不再坚持“死亡系统不能新增专用暂停状态和专用弹窗”。
- 不再把“神庙复活、死亡惩罚、复活虚弱”作为当前主流程。

### 1.3 当前终局口径

- 玩家死亡后弹出专用死亡结果窗口。
- 当前主流程只保留两个按钮：
  - `回退`
  - `删除存档`

旧版“祭坛复活”“金币经验惩罚”“复活虚弱”保留为历史方案，移入本文末尾的废弃方案附录，不再作为当前功能目标。

## 2. 双状态模型

死亡相关状态分为两层：生命状态与行动状态。

### 2.1 生命状态 `life_status`

```python
LifeStatus = Literal["healthy", "dying", "stable", "dead"]
```

- `healthy`
  - 正常存活。
  - 典型条件：`HP > 0`
- `dying`
  - `HP = 0` 且正在进行死亡豁免。
- `stable`
  - 不再进行死亡豁免，但仍未恢复自由行动能力。
  - 本版只由外部稳定或救援产生，不由“3 次成功”产生。
- `dead`
  - 角色死亡。

### 2.2 角色行动状态 `role_action_status`

```python
RoleActionStatus = Literal["free_action", "death_saving", "dead", "unable_to_act"]
```

- `free_action`
  - 可正常提交行为与语言。
- `death_saving`
  - 正在死亡豁免中。
  - 只能输入语言，不能输入会影响世界的行为。
- `dead`
  - 已死亡。
  - 不再参与主动交互。
- `unable_to_act`
  - 无法自由行动，只能输入语言。
  - 当前先定义枚举，不要求在 BUFF/眩晕系统里全面接入。

### 2.3 映射表

| 场景 | `life_status` | `role_action_status` | 说明 |
|------|---------------|----------------------|------|
| 正常角色 | `healthy` | `free_action` | 正常行动 |
| 进入死亡豁免 | `dying` | `death_saving` | 只能语言，等待豁免 |
| 外部稳定成功 | `stable` | `unable_to_act` | 不再掷死亡豁免，但不能自由行动 |
| 死亡 | `dead` | `dead` | 退出交互 |
| 未来眩晕等限制行动 | `healthy` | `unable_to_act` | 仅预留，不在本轮落功能 |

### 2.4 当前范围说明

- 本轮真正进入实现范围的是：
  - `death_saving`
  - `dead`
  - `stable` 的外部稳定语义
- `unable_to_act` 先作为统一角色行动状态枚举预留。
- `unable_to_act` 与 BUFF、眩晕、主聊天通用限制的完整联动，留给后续状态系统设计。

## 3. HP 归零后的统一分流

### 3.1 玩家

- 玩家 `HP <= 0` 时：
  - 若满足即死条件，直接进入 `dead`
  - 否则进入 `dying + death_saving`
- 玩家进入死亡豁免后：
  - `current_hp = 0`
  - `life_status = "dying"`
  - `role_action_status = "death_saving"`
  - 清空本轮死亡豁免计数并开始新一轮死亡豁免流程

### 3.2 队友 NPC

- 队友 NPC `HP <= 0` 时：
  - 若满足即死条件，直接死亡
  - 否则进入与玩家同类的死亡豁免状态
- 队友 NPC 的区别不在规则本体，而在交互方式：
  - 玩家手动操作玩家自己的死亡豁免
  - 系统自动处理队友 NPC 的死亡豁免

### 3.3 非队友 NPC

- 非队友 NPC `HP <= 0` 时直接死亡。
- 不进入死亡豁免。
- 不进入稳定状态。
- 不弹玩家可操作的死亡豁免窗口。

### 3.4 遭遇临时 NPC

- 遭遇临时 NPC 视为非队友 NPC。
- `0 HP -> dead`
- 不进入死亡豁免。
- 若该临时 NPC 没有持久化 `NpcRoleCard`，也要写入轻量死亡记录并从当前遭遇可见列表中移除。

### 3.5 “稳定”在本版中的语义

- 旧版“死亡豁免成功 3 次后进入稳定”废弃。
- 本版改为：
  - 累计 `3` 次成功：直接恢复 `1 HP` 并脱离死亡豁免
  - `stable` 只保留给外部稳定、外部救援、医疗检定、特殊道具效果

## 4. 玩家死亡豁免流程

### 4.1 进入死亡豁免

玩家进入死亡豁免时应立即满足：

- `life_status = "dying"`
- `role_action_status = "death_saving"`
- `death_save_successes = 0`
- `death_save_failures = 0`
- 公开回合、遭遇、战斗都应产生进入濒死的 scene event

### 4.2 玩家被作为行动目标时

当玩家已经处于 `death_saving`，且又被其他行动者作为目标时：

- 前端禁止填写 `action_text`
- 前端只允许填写 `speech_text`
- 允许玩家什么都不说，即 `speech_text = ""`
- 后端必须强制把该次响应视为 `non_world`
- 不允许该次响应进入对抗
- 行动方直接按现有公开回合的 `world -> non_world` 路径结算：
  - 需要静态 DC 的走静态 DC
  - 需要直接命中池的走命中池
  - 不再向濒死玩家请求行为性回应

这条规则的核心不是“玩家不能说话”，而是“濒死玩家不能再用行为干预世界状态”。

### 4.3 到玩家自己的回合时

当轮到玩家自己的公开回合、遭遇回合、战斗回合时：

- 玩家不再能提交行为
- 玩家只能提交语言
- 玩家提交语言后，弹出专用“死亡豁免掷骰窗口”
- 死亡豁免窗口是当前唯一允许玩家继续操作的核心交互

### 4.4 玩家死亡豁免规则

死亡豁免固定规则如下：

- `DC = 10`
- `d20 >= 10`：记 `1` 次成功
- `natural 1`：记 `2` 次失败
- `natural 20`：立即恢复 `1 HP`
- 累计 `3` 次成功：恢复 `1 HP`
- 累计 `3` 次失败：进入死亡

### 4.5 玩家在死亡豁免期间再次受伤

当玩家已经处于 `death_saving`，又受到新伤害时：

- 普通再受伤：
  - `death_save_failures += 1`
- 重伤：
  - 直接死亡
- 重伤阈值默认定义为：
  - 单次再受伤伤害 `>= ceil(max_hp * 0.5)`

如果一次伤害同时满足旧版即死条件，则即死优先，直接进入 `dead`。

### 4.6 外部稳定与治疗

对濒死玩家的外部干预保留，且仍是当前设计的一部分：

- 外部稳定：
  - 来源可以是医疗检定、稳定道具、明确的稳定技能
  - 结果改为 `stable + unable_to_act`
  - 不再继续死亡豁免
- 外部治疗：
  - 任何使 `HP > 0` 的效果都应结束死亡豁免
  - 角色回到 `healthy + free_action`

### 4.7 稳定状态的后续规则

稳定状态在本版中的规则如下：

- 不再继续死亡豁免
- 不能自由行动
- 只能输入语言
- 若再次受到伤害：
  - 满足即死条件则死亡
  - 否则重新进入 `dying + death_saving`

## 5. 队友 NPC 死亡豁免流程

### 5.1 队友 NPC 的行动约束

队友 NPC 进入死亡豁免后：

- 只能做“非世界影响微动作 + 语言”
- 不能提交世界影响行为
- 不能对任何角色造成实际影响
- 不能成为有效的对抗方
- 被点名为响应目标时，也只能给出 `non_world` 级别的语言或微动作

### 5.2 队友 NPC 自己回合中的豁免

- 队友 NPC 自己回合的死亡豁免由系统自动掷骰
- 系统不为每次队友豁免弹玩家操作窗口
- 结果必须通过以下任一或多项渠道同步给玩家：
  - scene event
  - settlement
  - 公开回合叙事

### 5.3 队友 NPC 的豁免规则

队友 NPC 与玩家使用同一套豁免结果：

- `3` 成功：恢复 `1 HP`
- `3` 失败：死亡
- `natural 1`：`2` 次失败
- `natural 20`：立即恢复 `1 HP`
- 再受伤：
  - 普通伤害：`+1` 次失败
  - 重伤：直接死亡

### 5.4 队友 NPC 的外部稳定与治疗

- 队友 NPC 允许被玩家或其他角色稳定
- 队友 NPC 允许被治疗恢复 `HP > 0`
- 稳定后进入 `stable + unable_to_act`
- 治疗后返回 `healthy + free_action`

### 5.5 队友 NPC 死亡后的处理

当队友 NPC 死亡时：

- 先弹出一段队友死亡叙述
- 再弹出提示窗口，提示玩家进行后续处理
- 该窗口的职责是：
  - 提示该队友需要离队
  - 提示该 NPC 要被放回当前子区块

队友 NPC 死亡后的数据处理目标应当是：

- 从 `team_state.members` 中移除
- 角色位置回填到当前子区块
- 角色状态进入 `dead`
- 同时写入当前子区块死亡记录

## 6. 普通 NPC 与遭遇临时 NPC 死亡

### 6.1 普通 NPC

普通 NPC `0 HP` 后立即进入死亡：

- `NpcRoleCard.state = "dead"`
- `life_status = "dead"`
- `role_action_status = "dead"`
- 从以下列表中立刻退出：
  - 公开回合候选行动体
  - 互动目标候选
  - 可互动 NPC 列表
  - 当前子区块 `AreaSubZone.npcs`

### 6.2 遭遇临时 NPC

遭遇临时 NPC `0 HP` 后：

- 直接死亡
- 从当前遭遇的临时角色列表中移除
- 不再参与后续行动与结算
- 若需要持久叙事痕迹，则写入当前子区块死亡记录

### 6.3 死亡后的场景清理

普通 NPC 或遭遇临时 NPC 死亡后，场景要自动清理：

- 当前公开回合不再把它们纳入候选行动体
- 当前子区块不再把它们当作可互动 NPC
- 玩家离开子区块并再次返回后，这些死亡 NPC 不应重新出现

## 7. 子区块死亡记录与场景清理

### 7.1 记录位置

本版采用“扩展子区块状态”的方案，不新增独立 shard。

建议结构：

```python
class DeadNpcRecord(BaseModel):
    role_id: str
    name: str
    death_at: str
    death_cause: str = ""
    was_team_member: bool = False


class SubZoneState(BaseModel):
    time_segment: str = "day"
    flags: list[str] = ["normal"]
    dead_npc_records: list[DeadNpcRecord] = Field(default_factory=list)
```

### 7.2 记录语义

`dead_npc_records` 不是普通日志，而是“该 NPC 未来是否还应被视为可互动对象”的过滤依据。

它至少用于以下判断：

- 是否还可以写回 `AreaSubZone.npcs`
- 是否还应被 `world_service._visible_public_roles(...)` 视为可见 NPC
- 是否还能进入 `public_turn` 候选行动体
- 是否还能被当作点名目标或互动目标

### 7.3 写入时机

以下时机必须写入 `dead_npc_records`：

- 普通 NPC 当场死亡
- 遭遇临时 NPC 当场死亡
- 队友 NPC 死亡并完成离队回填

### 7.4 读取时机

以下流程必须读取并尊重 `dead_npc_records`：

- 公开场景候选角色生成
- 当前子区块可互动 NPC 列表生成
- 子区块重新进入时的 NPC 注入或恢复
- 队友离队后回填到区域时的可见性判断

## 8. 玩家死亡后的结果窗口

### 8.1 窗口内容

玩家死亡后弹出专用死亡结果窗口：

- 先展示一段玩家死亡叙述
- 再展示两个按钮：
  - `回退`
  - `删除存档`

### 8.2 回退锚点

回退锚点固定为：

- 若死于 `active encounter`
  - 回退到该遭遇开始快照
- 若死于非遭遇
  - 回退到本次进入当前子区块时的快照

### 8.3 回退按钮可用性

- 若对应快照存在：
  - `回退` 按钮可用
- 若对应快照不存在：
  - `回退` 按钮禁用
  - UI 应显示禁用原因
- `删除存档` 按钮始终可用

### 8.4 触发顺序

当玩家死亡时，系统顺序应为：

1. 更新死亡状态
2. 结束或冻结当前遭遇/战斗/公开回合
3. 生成死亡叙述
4. 弹出死亡结果窗口

## 9. 即死、外部稳定与治疗

### 9.1 即死

旧版即死规则继续保留：

- 单次伤害将角色从正 HP 打到超过最大生命值的溢出伤害，直接死亡
- 特殊剧情危害、处决、遭遇终止条件也可以直接触发死亡

### 9.2 外部稳定

外部稳定的作用是：

- 将 `dying` 变为 `stable`
- 将 `death_saving` 变为 `unable_to_act`
- 停止继续死亡豁免

### 9.3 外部治疗

外部治疗的作用是：

- 只要 `HP > 0`
- 就结束 `dying` 或 `stable`
- 让角色回到 `healthy + free_action`

## 10. 前端交互、暂停状态与 SceneEvent

### 10.1 新增专用死亡豁免窗口

公开回合、遭遇、战斗中的玩家死亡豁免不再要求复用普通 reaction prompt。

本版允许新增专用 `DeathSavePrompt`：

```python
class DeathSavePrompt(BaseModel):
    actor_id: str
    actor_name: str
    successes: int
    failures: int
    dc: int = 10
    severe_wound_threshold: int
    speech_only: bool = True
```

### 10.2 玩家死亡窗口

玩家死亡后允许使用专用结果窗口，而不是强行塞入现有互动弹窗。

### 10.3 队友 NPC 死亡提示窗口

队友 NPC 死亡后允许使用专用提示窗口，职责是：

- 展示死亡叙述
- 提示该角色需要离队
- 提示该角色被放回当前子区块

### 10.4 新增暂停阶段

公开回合应增加新的暂停阶段：

```python
PublicTurnPhase = Literal[
    ...,
    "awaiting_player_death_save",
]
```

如运行时使用 pause kind，也应新增：

- `player_death_save`

### 10.5 响应载荷扩展

以下结构应增加 `death_save_prompt`：

- `PublicTurnRound`
- `PublicTurnResponse`
- `PendingTurnContinueResponse`

如果 pending 状态本身使用文本 status 表示暂停态，也应同步补充：

- `awaiting_player_death_save`

### 10.6 SceneEvent 扩展

至少补充以下事件类型：

```python
SceneEventKind = Literal[
    ...,
    "player_entered_death_save",
    "player_death_save_result",
    "player_died",
    "team_npc_entered_death_save",
    "team_npc_death_save_result",
    "team_npc_died",
    "sub_zone_dead_npc_recorded",
]
```

### 10.7 `BattleRollPrompt` 兼容扩展

即使公开回合新增 `DeathSavePrompt`，战斗侧的通用掷骰类型也应补齐：

```python
BattleRollPrompt.roll_kind += ["death_save", "stabilize"]
```

这样 battle / encounter 仍可在兼容路径下复用统一的掷骰语义。

## 11. 与现有系统的集成点

### 11.1 `public_turn_resolution.py`

当前公开回合伤害结算已经区分：

- 玩家 `0 HP -> dying`
- 其他角色 `0 HP -> dead`

本版需要把它细化为：

- 玩家 `0 HP -> death_saving`
- 队友 NPC `0 HP -> death_saving`
- 普通 NPC / 遭遇临时 NPC `0 HP -> dead`

### 11.2 `public_turn_interaction_service.py` 与攻击响应流

当目标角色处于：

- `death_saving`
- `unable_to_act`

时，前端与后端都必须限制为“只能语言，不能行为影响世界”。

### 11.3 `public_turn_candidates.py` 与公开场景候选体

以下角色不得再进入公开候选体：

- `role_action_status = dead`
- `NpcRoleCard.state = "dead"`
- 已存在于当前子区块 `dead_npc_records` 的死亡 NPC

### 11.4 `world_service._visible_public_roles(...)`

当前可见 NPC 逻辑只按子区块存在与 `role.state != "in_team"` 过滤。

本版需要额外过滤：

- `NpcRoleCard.state == "dead"`
- 当前子区块 `dead_npc_records`

### 11.5 `team_service.py`

队友 NPC 死亡后的处理要和离队流程衔接：

- 队友死亡不是“直接消失”
- 应先落死亡状态
- 再执行离队
- 再回填到当前子区块
- 最后写入 `dead_npc_records`

### 11.6 遭遇与战斗运行时

`battle_runtime.py` 与 `encounter_runtime_v2.py` 应共用同一死亡规则：

- 玩家 / 队友进入死亡豁免
- 普通 NPC 直接死亡
- 即死规则一致
- 稳定与治疗结果一致

### 11.7 快照策略

玩家死亡后的回退依赖两个快照锚点：

- `encounter_start_snapshot`
- `sub_zone_entry_snapshot`

这两个快照必须在运行时明确生成与维护，否则只能禁用回退按钮。

## 12. 接口与类型变更清单

### 12.1 `Dnd5eCharacterSheet`

```python
class Dnd5eCharacterSheet(BaseModel):
    ...
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)
    role_action_status: Literal["free_action", "death_saving", "dead", "unable_to_act"] = "free_action"
```

### 12.2 `PlayerDeathState`

保留现有结构，但语义改为：

- `3` 成功恢复 `1 HP`
- `stable` 仅供外部稳定与救援使用

### 12.3 `NpcRoleCard.state`

虽然当前字段仍是 `str`，但设计上应把以下值视为合法状态之一：

- `dead`

### 12.4 `SubZoneState`

```python
class SubZoneState(BaseModel):
    ...
    dead_npc_records: list[DeadNpcRecord] = Field(default_factory=list)
```

### 12.5 `PublicTurnPhase` 与 pause kind

- 新增 `awaiting_player_death_save`
- pause kind 新增 `player_death_save`

### 12.6 公开回合返回结构

以下结构增加 `death_save_prompt`：

- `PublicTurnRound`
- `PublicTurnResponse`
- `PendingTurnContinueResponse`

### 12.7 专用 `DeathSavePrompt`

至少包含：

- `actor_id`
- `actor_name`
- `successes`
- `failures`
- `dc`
- `severe_wound_threshold`
- `speech_only`

### 12.8 `SceneEvent.kind`

至少增加：

- `player_entered_death_save`
- `player_death_save_result`
- `player_died`
- `team_npc_entered_death_save`
- `team_npc_death_save_result`
- `team_npc_died`
- `sub_zone_dead_npc_recorded`

### 12.9 `BattleRollPrompt`

前后端类型要同步补齐：

- `death_save`
- `stabilize`

## 13. 验收标准

- [ ] 玩家在公开回合被打到 `0 HP` 后，下一次被点名响应时只能输入语言，不能输入行为。
- [ ] 玩家在自己回合提交语言后会弹死亡豁免窗口，而不是普通互动/攻击窗口。
- [ ] 玩家累计 `3` 次成功后恢复 `1 HP`，不进入 `stable`。
- [ ] 玩家在死亡豁免期间受到普通伤害只累计失败，受到重伤直接死亡。
- [ ] 玩家死亡窗口只出现“回退/删档”两个按钮，且回退锚点按“遭遇开始 / 子区块进入”切换。
- [ ] 队友 NPC `0 HP` 后不再产生 `world-impact` 行为，系统会自动掷死亡豁免。
- [ ] 队友 NPC `3` 次失败后弹提示窗口，要求玩家把该 NPC 离队并回填到当前子区块。
- [ ] 普通 NPC `0 HP` 后立即死亡，当前轮起就不再可互动；离开并重返子区块后也不会重新出现。
- [ ] 子区块 `dead_npc_records` 能阻止已死 NPC 被重新注入 `visible_npcs` / `AreaSubZone.npcs`。
- [ ] 外部稳定会把角色置为 `stable + unable_to_act`，而不是恢复自由行动。
- [ ] 外部治疗只要使 `HP > 0`，就能结束死亡豁免或稳定状态。

## 14. 当前不纳入本轮实现

- `unable_to_act` 与 BUFF、眩晕、主聊天通用限制的全面联动
- 完整的复活系统
- 死亡惩罚、金币损失、经验损失、复活虚弱
- 灵魂位面、遗产系统、死亡厄运等扩展玩法

## 附录：废弃方案与历史口径

以下内容不再作为当前设计目标，但可以保留给未来版本参考：

- 神庙/祭坛复活主流程
- `player_revive` 作为死亡后的核心按钮路径
- 以金币、经验、道具丢失为主的死亡惩罚
- 复活虚弱 `buff`
- “3 次成功进入 stable”的旧版口径
