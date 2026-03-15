# 死亡判定与死亡流程设计

> 更新日期：2026-03-15
> 本文档定义玩家角色的死亡判定条件、濒死流程、死亡后处理及复活机制。
> 
> **与现有系统的关联**：
> - 复用现有 `BattleSandboxState` 的战斗状态
> - 复用 `reaction_prompt` 机制进行死亡豁免
> - 复用 `conditions` 列表管理濒死/稳定状态
> - 通过 `scene_events` 同步死亡状态到前端

## 1. 目标

- **核心目标**：建立清晰的死亡判定规则，与现有 DND 5E 战斗系统兼容
- **体验目标**：提供有张力的濒死体验，给予玩家被救回的机会
- **流程目标**：定义死亡后的游戏流程，避免"游戏结束"的硬中断
- **设计约束**：
  - 复用现有 `reaction_prompt` 机制，不新增 UI 类型
  - 复用 `conditions` 字段管理状态，不新增复杂状态机
  - 死亡惩罚适度，避免过度挫败

## 2. 死亡状态定义

### 2.1 生命状态层级

```
健康 (Healthy) —— HP > 0
    ↓ HP降至0
濒死 (Dying) —— HP = 0，进行死亡豁免（复用 reaction_prompt）
    ↓ 豁免成功3次
稳定 (Stable) —— 停止濒死检定，但仍昏迷（conditions: ["stable", "unconscious"]
    ↓ 恢复HP > 0
恢复 (Recovered)
    
濒死 (Dying)
    ↓ 豁免失败3次 或 受到超额伤害
死亡 (Dead) —— is_dead = true，进入死亡流程
    ↓ 复活流程
复活 (Revived) —— 应用复活虚弱 buff
```

### 2.2 与现有数据结构的映射

复用现有字段，**不新增**复杂数据结构：

```python
# 复用 Dnd5eCharacterSheet.is_dead（已存在）
# 复用 Dnd5eCharacterSheet.status_flags（已存在）
# 复用 CombatantState.conditions（已存在）
# 复用 CombatantState.alive / downed（已存在）

# 仅需新增：PlayerDeathState（轻量结构）
class PlayerDeathState(BaseModel):
    life_status: Literal["healthy", "dying", "stable", "dead"] = "healthy"
    death_save_successes: int = 0  # 0-3
    death_save_failures: int = 0   # 0-3
    death_count: int = 0  # 累计死亡次数
    death_streak_count: int = 0  # 24小时内死亡次数
    last_death_at: str | None = None
    revived_at: str | None = None
    revival_weakness_until: str | None = None
```

### 2.3 条件状态映射

复用 `CombatantState.conditions` 列表：

| 状态 | conditions 值 | 说明 |
|------|---------------|------|
| 濒死 | `["dying", "unconscious", "prone"]` | 倒地、昏迷、濒死 |
| 稳定 | `["stable", "unconscious", "prone"]` | 稳定但仍昏迷 |
| 复活虚弱 | `["revival_weakness"]` | Buff 形式存在 |

## 3. 濒死流程（Death Saving Throws）

### 3.1 进入濒死

**触发条件**：
- 玩家角色 `current_hp` 降至 0
- 伤害来源可以是战斗、遭遇或环境

**进入濒死时的处理**：

```python
# 在 battle_runtime._apply_damage 中扩展
def _apply_damage(state, target, amount, ...):
    # ... 现有伤害计算 ...
    
    if target.current_hp <= 0 and target.source_kind == "player":
        # 检查是否即死（超额伤害）
        if amount >= target.max_hp:
            _apply_instant_death(state, target, amount)
            return
        
        # 进入濒死
        target.downed = True
        target.conditions = ["dying", "unconscious", "prone"]
        target.alive = True  # 濒死仍算"活着"
        
        # 初始化死亡豁免状态
        death_state = PlayerDeathState(
            life_status="dying",
            death_save_successes=0,
            death_save_failures=0
        )
        
        # 触发濒死 reaction_prompt
        _make_death_save_prompt(state, target)
```

### 3.2 死亡豁免机制（复用 reaction_prompt）

**核心设计**：复用现有的 `BattleRollPrompt` / `PlayerReactionCheck` 机制

```python
# 在 battle_runtime 中新增
def _make_death_save_prompt(state: BattleSandboxState, player: CombatantState) -> BattleRollPrompt:
    """创建死亡豁免检定提示"""
    prompt = BattleRollPrompt(
        prompt_id=f"death_save_{uuid4().hex}",
        roll_kind="death_save",  # 新增 kind
        actor_combatant_id=player.combatant_id,
        actor_name=player.display_name,
        ability_used="constitution",  # 体质相关
        ability_modifier=0,  # 死亡豁免无加值
        dc=10,
        check_task="死亡豁免 - 与死亡抗争",
        source_label="濒死状态",
        threatened_consequence="如果失败，你离死亡更近一步。",
        success_hint="你顽强地撑住了，伤势没有继续恶化。",
        failure_hint="你感到生命力在流逝...",
        critical_success_hint="奇迹发生！你恢复了意识！",
        critical_failure_hint="情况急剧恶化！",
    )
    state.pending_roll = prompt
    state.status = "awaiting_player_roll"
    _add_step(state, kind="death_save_prompt", content=f"{player.display_name} 正在进行死亡豁免...")
    return prompt
```

**豁免结果处理**：

```python
def resolve_death_save(state, player, roll_result):
    d20 = roll_result.dice_roll
    is_natural_20 = d20 == 20
    is_natural_1 = d20 == 1
    success = d20 >= 10 or is_natural_20
    
    death_state = player.death_state
    
    if is_natural_20:
        # 大成功：恢复 1 HP，苏醒
        player.current_hp = 1
        player.downed = False
        player.conditions = []  # 清除所有负面状态
        death_state.life_status = "healthy"
        _add_step(state, kind="death_save", content="奇迹！你在濒死中恢复了意识！")
        return "revived"
    
    if is_natural_1:
        # 大失败：2次失败
        death_state.death_save_failures += 2
        _add_step(state, kind="death_save", content="情况急剧恶化！")
    elif success:
        death_state.death_save_successes += 1
        _add_step(state, kind="death_save", content="你撑住了这一轮。")
    else:
        death_state.death_save_failures += 1
        _add_step(state, kind="death_save", content="你感到生命力在流逝...")
    
    # 检查是否结束濒死
    if death_state.death_save_successes >= 3:
        # 稳定
        player.conditions = ["stable", "unconscious", "prone"]
        death_state.life_status = "stable"
        _add_step(state, kind="stabilized", content=f"{player.display_name} 的伤势稳定了下来。")
        return "stabilized"
    
    if death_state.death_save_failures >= 3:
        # 死亡
        _declare_death(state, player)
        return "died"
    
    # 继续濒死，准备下一次豁免
    _make_death_save_prompt(state, player)
    return "continues"
```

### 3.3 稳定状态

- 不再需要进行死亡豁免
- 仍视为 `unconscious`（昏迷），无法行动
- 1 小时后自动恢复 1 HP（通过世界时间推进触发）
- 若再次受到伤害，重新进入濒死

## 4. 即死规则（Instant Death）

### 4.1 超额伤害

当单次伤害将角色 HP 从正值降至 **负的最大生命值** 时：

```python
def _apply_instant_death(state, target, damage_amount):
    """应用即死"""
    excess = damage_amount - target.current_hp  # 溢出伤害
    if excess >= target.max_hp:
        target.alive = False
        target.downed = True
        target.conditions = ["dead"]
        _add_step(state, kind="instant_death", 
                  content=f"{target.display_name} 遭受了致命一击，当场死亡！")
        _declare_death(state, target, is_instant=True)
```

### 4.2 剧情即死

- 通过 `scene_interactable` 的 `hazard` 类型触发
- 通过遭遇的特殊 `termination_conditions` 触发

## 5. 救援与治疗

### 5.1 队友救援（复用现有动作）

**医疗检定**：复用 `use_item` 或新增 `stabilize` 动作

```python
def submit_stabilize_action(state, medic, target):
    """队友尝试稳定濒死玩家"""
    if "dying" not in target.conditions:
        raise ValueError("目标不在濒死状态")
    
    # 医药检定（DC 10）
    prompt = BattleRollPrompt(
        roll_kind="stabilize",
        ability_used="wisdom",
        ability_modifier=medic.ability_modifiers.wisdom,
        dc=10,
        # ... 其他字段
    )
    # 成功后 target.conditions = ["stable", "unconscious", "prone"]
```

**治疗药水**：复用现有的 `use_item` 逻辑，任何恢复 HP 的效果直接使濒死/稳定角色苏醒。

### 5.2 拖行与掩护

- 复用现有的 `move` 或 `disengage` 动作
- 濒死角色被移动时，移动速度为正常速度的 1/4

## 6. 死亡后流程

### 6.1 战斗中的死亡处理

```python
def _declare_death(state: BattleSandboxState, player: CombatantState, is_instant=False):
    """宣告玩家死亡"""
    player.alive = False
    player.downed = True
    player.conditions = ["dead"]
    player.death_state.life_status = "dead"
    player.death_state.death_count += 1
    player.death_state.death_streak_count += 1
    player.death_state.last_death_at = _utc_now()
    
    # 记录战斗日志
    _add_step(state, kind="player_death", 
              content=f"{player.display_name} 死亡。",
              metadata={"death_count": player.death_state.death_count})
    
    # 触发战斗结束（玩家方失败）
    state.status = "ended"
    state.combat_state.phase = "ended"
    state.combat_state.winner_side = "enemy_side"
    
    # 生成 SceneEvent 同步到主游戏
    _emit_death_scene_event(state, player)
```

### 6.2 死亡惩罚计算

```python
class DeathPenalties(BaseModel):
    gold_lost: int          # 丢失 10% 金币（最低 50）
    exp_lost: int           # 当前等级经验 -10%（不降级）
    items_lost: list[str]   # 随机丢失的 item_instance_ids
    weakness_duration_min: int  # 复活虚弱持续时间

def calculate_death_penalties(save: SaveFile, death_state: PlayerDeathState) -> DeathPenalties:
    streak = death_state.death_streak_count
    
    # 基础惩罚
    gold = max(50, int(save.player_static_data.dnd5e_sheet.backpack.gold * 0.1))
    exp_loss = int(save.player_static_data.dnd5e_sheet.experience_current * 0.1)
    
    # 连续死亡惩罚
    weakness_min = 60 * (2 if streak >= 2 else 1) * (3 if streak >= 3 else 1)
    
    return DeathPenalties(
        gold_lost=gold,
        exp_lost=exp_loss,
        items_lost=_random_unbound_items(save, count=1),
        weakness_duration_min=weakness_min
    )
```

### 6.3 复活方式

#### 6.3.1 神庙/祭坛复活（主要方式）

**位置**：
- 冒险者工会总部（必定存在）
- 各大城镇的神庙

**代价**：
- 基础费用 = 角色等级 × 100 金币
- 死亡次数越多，费用越高（每次 ×1.2）

**复活后状态**：
- HP = 最大 HP 的 25%
- 获得 `revival_weakness` buff，持续 1 小时（或更长，视连续死亡次数）

```python
def revive_at_shrine(save: SaveFile, shrine_zone_id: str) -> RevivalResult:
    """在神庙复活"""
    player = save.player_static_data
    death_state = player.dnd5e_sheet.death_state
    
    # 计算费用
    cost = player.dnd5e_sheet.level * 100 * (1.2 ** max(0, death_state.death_count - 1))
    
    # 扣费
    save.player_static_data.dnd5e_sheet.backpack.gold -= cost
    
    # 恢复状态
    hp_max = player.dnd5e_sheet.hit_points.maximum
    player.dnd5e_sheet.hit_points.current = int(hp_max * 0.25)
    player.dnd5e_sheet.is_dead = False
    death_state.life_status = "healthy"
    death_state.revived_at = _utc_now()
    
    # 应用复活虚弱 buff
    weakness_duration = calculate_death_penalties(save, death_state).weakness_duration_min
    player.dnd5e_sheet.buffs.append(RoleBuff(
        buff_id=f"revival_weakness_{uuid4().hex}",
        name="复活虚弱",
        description="所有检定劣势，移速减半，无法获得经验",
        duration_min=weakness_duration,
        remaining_min=weakness_duration,
        effect=RoleBuffEffect(
            # 负面效果在 buff 结算时应用
        )
    ))
    
    return RevivalResult(...)
```

#### 6.3.2 队友复活（最佳方式）

- 复用 `use_item` 使用复活道具
- 或使用特定法术（如果有）

#### 6.3.3 存档读取

- 标准读档流程，无特殊处理

## 7. AI 工具

### 7.1 新增 AI 工具列表

| 工具名 | 类型 | 用途 |
|--------|------|------|
| `get_player_death_state` | 读取 | 获取玩家死亡/濒死状态 |
| `stabilize_player` | 写入 | 队友尝试稳定濒死玩家 |
| `player_revive` | 写入 | 执行复活（仅限特定场景）|

### 7.2 `get_player_death_state`（读取工具）

**输入**：`session_id`

**输出**：
```json
{
  "life_status": "dying",
  "death_save_successes": 1,
  "death_save_failures": 0,
  "death_count": 2,
  "can_be_stabilized": true,
  "nearby_medical_items": ["治疗药水 x2"],
  "nearby_allies": ["艾莉娅", "格朗"]
}
```

**使用场景**：
- GM 需要判断当前玩家是否可救援
- 队友 AI 决定是否需要救援

### 7.3 `stabilize_player`（写入工具）

**输入**：
```json
{
  "session_id": "",
  "medic_role_id": "",  // 执行救援的角色
  "method": "medicine_check/item",  // 检定方式
  "item_instance_id": ""  // 如使用物品
}
```

**输出**：检定结果 + 叙事文本

**使用场景**：
- 队友尝试救援濒死玩家
- AI GM 根据检定结果生成叙事

### 7.4 AI 叙事生成

**濒死叙事**（在死亡豁免时生成）：
- 输入：玩家状态、伤害来源、当前豁免进度
- 输出：戏剧性场景描述

**死亡宣告叙事**：
- 输入：死亡原因、地点、累计死亡次数
- 输出：死亡场景 + 对周围影响

**复活叙事**：
- 输入：复活方式、地点、虚弱持续时间
- 输出：复活过程描述

## 8. SceneEvent 扩展

复用现有 `SceneEvent` 机制同步死亡状态：

```python
SceneEventKind = Literal[
    # ... 现有事件 ...
    "player_dying",           # 进入濒死
    "player_death_save",      # 死亡豁免结果
    "player_stabilized",      # 稳定
    "player_died",            # 死亡
    "player_revived",         # 复活
]
```

**事件结构示例**：
```python
SceneEvent(
    event_id="evt_001",
    kind="player_dying",
    content="你受了重伤，正在失去意识！",
    metadata={
        "life_status": "dying",
        "death_save_dc": 10,
        "nearby_allies": ["艾莉娅"],
    }
)
```

## 9. 与现有系统的集成点

### 9.1 战斗系统（`battle_runtime.py`）

修改 `_apply_damage` 函数：
- 检查玩家 HP 降至 0
- 判断即死或濒死
- 触发 `death_save_prompt`

修改 `resolve_pending_roll`：
- 处理 `roll_kind == "death_save"` 的情况

### 9.2 遭遇系统（`encounter_runtime_v2.py`）

- 遭遇效果造成伤害时，复用 `apply_damage_with_death_check`
- 遭遇中玩家死亡时，特殊处理遭遇结果

### 9.3 主聊天系统（`chat_service.py`）

- 在 `route_main_turn_intent` 中处理濒死/死亡状态
- 濒死状态阻塞主聊天（类似 encounter）

### 9.4 公开场景导演器

- 玩家濒死时，队友 AI 行为调整为优先救援
- 通过 `actor_intent` 触发救援动作

## 10. UI 设计（复用现有组件）

### 10.1 濒死状态

复用 `BattleModal` 或 `PlayerReactionCheck` UI：

```
┌─────────────────────────────────────────────────────────┐
│  ☠️ 濒死状态 - 死亡豁免                                  │
│                                                         │
│  你受了重伤，正在失去意识！                              │
│  成功: ●○○  失败: ○○○                                    │
│                                                         │
│  【掷骰】 d20 ≥ 10 成功                                  │
└─────────────────────────────────────────────────────────┘
```

### 10.2 死亡界面

复用 Modal 组件：

```
┌─────────────────────────────────────────────────────┐
│                  你 已 死 亡                        │
├─────────────────────────────────────────────────────┤
│  【死亡地点】荆棘沼泽 - 毒菇洞穴                      │
│  【死亡原因】被荆棘巨魔致命一击                       │
│  【丢失金币】150 G                                    │
├─────────────────────────────────────────────────────┤
│  【选项】                                           │
│  1. 在工会祭坛复活（费用：300 G）                    │
│  2. 读取存档                                        │
└─────────────────────────────────────────────────────┘
```

## 11. 验收标准

- [ ] 玩家 HP 降至 0 时正确进入濒死状态
- [ ] 死亡豁免复用 `reaction_prompt` 机制
- [ ] 自然 20 直接恢复 1 HP
- [ ] 自然 1 算作 2 次失败
- [ ] 成功 3 次后进入稳定状态
- [ ] 失败 3 次后正确宣告死亡
- [ ] 超额伤害直接致死
- [ ] 队友可以治疗/稳定濒死玩家
- [ ] 复活后正确应用 `revival_weakness` buff
- [ ] 连续死亡惩罚正确计算
- [ ] 死亡/复活通过 `scene_events` 同步到前端
- [ ] 战斗死亡后正确结束战斗并返回主游戏

## 12. 未来扩展

- **灵魂领域玩法**：死亡后进入灵魂位面进行特殊任务
- **遗产系统**：永久死亡后新角色继承部分遗产
- **死亡厄运**：连续死亡触发特殊高难度遭遇
