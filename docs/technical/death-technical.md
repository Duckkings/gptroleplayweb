# 死亡系统技术文档

> 更新日期：2026-03-15
> 对应设计文档：`docs/design/gamedesign/deathdesign.md`

## 1. 设计原则

- **最小侵入**：复用现有机制（`reaction_prompt`, `conditions`, `buffs`）
- **向后兼容**：现有存档无感知升级
- **渐进实现**：P1 核心流程，P2 完善体验

## 2. 数据模型

### 2.1 新增模型

```python
# backend/app/models/schemas.py

class PlayerDeathState(BaseModel):
    """轻量级死亡状态追踪，嵌入 Dnd5eCharacterSheet"""
    version: str = Field(default="0.1.0")
    
    # 生命状态
    life_status: Literal["healthy", "dying", "stable", "dead"] = "healthy"
    
    # 濒死追踪 (0-3)
    death_save_successes: int = Field(default=0, ge=0, le=3)
    death_save_failures: int = Field(default=0, ge=0, le=3)
    
    # 死亡统计
    death_count: int = Field(default=0, ge=0)
    death_streak_count: int = Field(default=0, ge=0)  # 24小时内
    death_streak_reset_at: str | None = None
    
    # 上次死亡信息
    last_death_at: str | None = None
    last_death_zone_id: str | None = None
    last_death_sub_zone_id: str | None = None
    last_death_cause: str = Field(default="")
    
    # 复活追踪
    revived_at: str | None = None
    revival_method: Literal["shrine", "teammate", "item"] | None = None
    revival_weakness_until: str | None = None
    
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DeathPenalties(BaseModel):
    """死亡惩罚计算结果"""
    gold_lost: int = 0
    exp_lost: int = 0
    items_lost: list[str] = Field(default_factory=list)  # item_instance_ids
    weakness_duration_min: int = 60
```

### 2.2 扩展现有模型

```python
# Dnd5eCharacterSheet 扩展（已有字段保持不变）
class Dnd5eCharacterSheet(BaseModel):
    # ... 现有字段 ...
    
    # 新增/复用字段
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)
    # is_dead: bool = False  # 已存在，复用
    # status_flags: list[str] = []  # 已存在，复用


# CombatantState 复用已有字段
class CombatantState(BaseModel):
    # ... 现有字段 ...
    
    # 复用以下字段管理死亡状态：
    # conditions: list[str] = []  # 添加 "dying", "stable", "unconscious", "prone"
    # alive: bool = True
    # downed: bool = False
    
    # 新增字段（战斗沙盒专用）
    death_state: PlayerDeathState = Field(default_factory=PlayerDeathState)
```

### 2.3 SceneEvent 扩展

```python
# SceneEvent 的 kind 字段扩展（向后兼容）
SceneEventKind = Literal[
    # ... 现有事件 ...
    "player_dying",           # 进入濒死
    "player_death_save",      # 死亡豁免结果
    "player_stabilized",      # 稳定
    "player_died",            # 死亡
    "player_revived",         # 复活
]
```

### 2.4 BattleRollPrompt 扩展

```python
# BattleRollPrompt 的 roll_kind 字段扩展
RollKind = Literal[
    # ... 现有类型 ...
    "initiative",
    "attack",
    "observe",
    "escape",
    "reaction",
    "item_use",
    "death_save",      # 新增：死亡豁免
    "stabilize",       # 新增：稳定检定
]
```

## 3. 服务层设计

### 3.1 DeathService（核心服务）

```python
# backend/app/services/death_service.py

class DeathService:
    """死亡判定与流程管理服务"""
    
    # ========== 死亡判定 ==========
    
    def check_and_apply_damage(
        self,
        save: SaveFile,
        target_id: str,
        damage: int,
        damage_type: str,
        source: DamageSource,
    ) -> DamageResult:
        """
        统一伤害入口：应用伤害并处理可能的死亡流程
        由 battle_runtime, encounter_service, chat_service 调用
        """
    
    def is_instant_death(self, target: CombatantState, damage: int) -> bool:
        """检查是否满足即死条件（超额伤害）"""
        excess = damage - target.current_hp
        return excess >= target.max_hp
    
    # ========== 濒死流程 ==========
    
    def enter_dying_state(
        self,
        state: BattleSandboxState | SaveFile,
        target: CombatantState,
        cause: str,
    ) -> None:
        """使玩家进入濒死状态"""
    
    def make_death_save_prompt(
        self,
        state: BattleSandboxState,
        player: CombatantState,
    ) -> BattleRollPrompt:
        """创建死亡豁免检定提示（复用 reaction_prompt 机制）"""
    
    def resolve_death_save(
        self,
        state: BattleSandboxState,
        player: CombatantState,
        roll_result: BattleRollResolution,
    ) -> Literal["revived", "stabilized", "died", "continues"]:
        """
        处理死亡豁免结果
        返回值表示结果：复活、稳定、死亡、继续濒死
        """
    
    def stabilize(
        self,
        state: BattleSandboxState | SaveFile,
        target: CombatantState,
        stabilizer: CombatantState | None = None,
        method: Literal["medicine", "item"] = "medicine",
    ) -> StabilizeResult:
        """稳定濒死玩家"""
    
    # ========== 死亡与复活 ==========
    
    def declare_death(
        self,
        state: BattleSandboxState | SaveFile,
        player: CombatantState,
        is_instant: bool = False,
    ) -> DeathDeclarationResult:
        """宣告玩家死亡，触发惩罚计算和战斗结束"""
    
    def calculate_penalties(
        self,
        save: SaveFile,
        death_state: PlayerDeathState,
    ) -> DeathPenalties:
        """计算死亡惩罚"""
    
    def revive_at_shrine(
        self,
        save: SaveFile,
        shrine_zone_id: str,
    ) -> RevivalResult:
        """在神庙/祭坛复活"""
    
    def apply_revival_weakness(
        self,
        sheet: Dnd5eCharacterSheet,
        duration_min: int,
    ) -> None:
        """应用复活虚弱 buff"""
    
    # ========== 状态管理 ==========
    
    def update_death_streak(
        self,
        death_state: PlayerDeathState,
        current_time: datetime,
    ) -> None:
        """检查并重置连续死亡计数（24小时）"""
    
    def check_weakness_expired(
        self,
        sheet: Dnd5eCharacterSheet,
        current_time: datetime,
    ) -> bool:
        """检查复活虚弱是否过期，如过期则移除"""
```

### 3.2 与现有服务的集成

```python
# backend/app/services/battle_runtime.py

# 修改 _apply_damage 函数
def _apply_damage(
    state: BattleSandboxState,
    target: CombatantState,
    amount: int,
    *,
    actor: CombatantState | None = None,
    damage_type: str = "",
) -> int:
    # ... 现有伤害计算 ...
    
    # 新增：死亡判定
    if target.source_kind == "player" and target.current_hp <= 0:
        from app.services.death_service import DeathService
        death_svc = DeathService()
        
        if death_svc.is_instant_death(target, amount):
            death_svc.declare_death(state, target, is_instant=True)
        else:
            death_svc.enter_dying_state(state, target, cause="战斗伤害")
            death_svc.make_death_save_prompt(state, target)
    
    return total_applied


# 修改 resolve_pending_roll 函数
def resolve_pending_roll(
    state: BattleSandboxState,
    forced_dice_roll: int,
) -> BattleRollResolution:
    prompt = state.pending_roll
    
    # ... 现有处理 ...
    
    if prompt.roll_kind == "death_save":
        from app.services.death_service import DeathService
        death_svc = DeathService()
        
        player = _find_combatant(state, prompt.actor_combatant_id)
        roll_result = BattleRollResolution(...)  # 构建结果
        
        outcome = death_svc.resolve_death_save(state, player, roll_result)
        
        if outcome == "died":
            # 战斗结束处理已在 declare_death 中完成
            pass
        elif outcome == "revived":
            _advance_to_next_turn(state)
        elif outcome == "continues":
            # 继续濒死，已创建新的 death_save_prompt
            pass
        
        return roll_result
    
    # ... 其他 roll_kind 处理 ...
```

## 4. API 端点

### 4.1 新增端点

```python
# GET /api/v1/death/status
# 获取当前死亡状态（用于濒死 UI）
class DeathStatusResponse(BaseModel):
    life_status: Literal["healthy", "dying", "stable", "dead"]
    death_state: PlayerDeathState
    can_be_stabilized: bool
    nearby_medical_items: list[str]
    nearby_allies: list[str]


# POST /api/v1/death/stabilize
# 尝试稳定濒死玩家（队友操作）
class StabilizeRequest(BaseModel):
    session_id: str
    target_player_id: str
    method: Literal["medicine_check", "healing_kit", "spell"]
    item_instance_id: str | None = None

class StabilizeResponse(BaseModel):
    success: bool
    roll_result: BattleRollResolution
    stabilized: bool
    scene_events: list[SceneEvent]


# POST /api/v1/death/revive
# 执行复活（死亡后）
class ReviveRequest(BaseModel):
    session_id: str
    method: Literal["shrine", "item", "teammate"]
    shrine_zone_id: str | None = None
    item_instance_id: str | None = None

class ReviveResponse(BaseModel):
    success: bool
    method: str
    penalties_applied: DeathPenalties
    scene_events: list[SceneEvent]
    state_sync: MapStateSyncBundle
```

### 4.2 集成到现有端点

```python
# POST /api/v1/battle/{battle_id}/resolve-roll
# 已支持 death_save roll_kind，无需新增端点

# POST /api/v1/encounters/{encounter_id}/act
# 遭遇伤害自动触发死亡检查（通过 death_service.check_and_apply_damage）

# POST /api/v1/chat
# 主聊天中 GM 描述的伤害也可能触发死亡检查
```

## 5. AI 工具实现

### 5.1 `get_player_death_state`（读取工具）

```python
# backend/app/services/chat_service.py 中添加

async def tool_get_player_death_state(session_id: str) -> dict:
    """获取玩家死亡状态"""
    save = get_current_save(default_session_id=session_id)
    player = save.player_static_data
    death_state = player.dnd5e_sheet.death_state
    
    return {
        "life_status": death_state.life_status,
        "death_save_progress": {
            "successes": death_state.death_save_successes,
            "failures": death_state.death_save_failures,
        },
        "death_count": death_state.death_count,
        "can_be_stabilized": death_state.life_status == "dying",
        "revival_weakness_active": any(
            b.name == "复活虚弱" for b in player.dnd5e_sheet.buffs
        ),
    }
```

### 5.2 `stabilize_player`（写入工具）

```python
async def tool_stabilize_player(
    session_id: str,
    medic_role_id: str,
    method: str,
    item_instance_id: str | None = None,
) -> dict:
    """队友尝试稳定濒死玩家"""
    save = get_current_save(default_session_id=session_id)
    
    # 执行稳定检定
    result = perform_stabilize_check(save, medic_role_id, method, item_instance_id)
    
    return {
        "success": result.success,
        "stabilized": result.stabilized,
        "narrative": result.narrative,
        "tool_events": [{
            "tool_name": "stabilize_player",
            "ok": result.success,
            "summary": f"{medic_role_id} 尝试稳定玩家" + ("成功" if result.stabilized else "失败"),
        }],
    }
```

## 6. Prompt 注册

在 `app/core/prompt_keys.py` 中注册：

```python
class PromptKeys:
    # ... 现有 keys ...
    
    # 死亡相关
    DEATH_DYING_NARRATIVE = "death.dying.narrative.v1"
    DEATH_SAVE_NARRATIVE = "death.save.narrative.v1"
    DEATH_DECLARATION_NARRATIVE = "death.declaration.narrative.v1"
    DEATH_REVival_NARRATIVE = "death.revival.narrative.v1"
```

## 7. 前端集成

### 7.1 状态管理

```typescript
// 复用现有 UI 状态机
interface DeathUIState {
  lifeStatus: 'healthy' | 'dying' | 'stable' | 'dead';
  deathSaves: {
    successes: number;
    failures: number;
  };
  isRevivalWeaknessActive: boolean;
}

// 监听 SceneEvent
useEffect(() => {
  if (sceneEvent.kind === 'player_dying') {
    showDyingPanel(sceneEvent);
  } else if (sceneEvent.kind === 'player_died') {
    showDeathModal(sceneEvent);
  } else if (sceneEvent.kind === 'player_revived') {
    hideDeathModal();
    showRevivalMessage(sceneEvent);
  }
}, [sceneEvents]);
```

### 7.2 组件复用

- **濒死面板**：复用 `BattleModal` 或 `PlayerReactionCheckPanel`
- **死亡界面**：复用 `QuestModal` 风格的模态框
- **虚弱提示**：复用 `BuffIndicator` 组件

## 8. 测试策略

```python
# backend/tests/test_death_service.py

class TestDeathService:
    def test_damage_to_dying(self):
        """测试伤害导致濒死"""
        
    def test_excess_damage_instant_death(self):
        """测试超额伤害立即致死"""
        
    def test_natural_20_revive(self):
        """测试自然20直接恢复1HP"""
        
    def test_natural_1_double_failure(self):
        """测试自然1算作2次失败"""
        
    def test_medicine_stabilize(self):
        """测试医药检定稳定"""
        
    def test_revival_weakness_buff(self):
        """测试复活虚弱buff应用"""
        
    def test_death_streak_reset(self):
        """测试24小时后死亡连击重置"""
```

## 9. 实现优先级

### P1：核心死亡流程（1-2周）
- [ ] `PlayerDeathState` 数据模型
- [ ] `DeathService` 核心方法
- [ ] `battle_runtime` 集成（伤害判定、死亡豁免）
- [ ] 濒死/稳定/死亡状态流转
- [ ] 基础 SceneEvent 同步

### P2：复活与惩罚（1周）
- [ ] 神庙复活 API
- [ ] 死亡惩罚计算
- [ ] `revival_weakness` buff 系统
- [ ] 死亡界面 UI

### P3：救援与完善（1周）
- [ ] 队友稳定检定
- [ ] AI 叙事生成
- [ ] AI 工具集成
- [ ] 存档兼容处理

## 10. 风险与对策

| 风险 | 对策 |
|------|------|
| 与现有战斗系统冲突 | 在 `battle_runtime` 中统一入口，充分测试 |
| 存档兼容性问题 | 使用 Pydantic 默认值，确保向后兼容 |
| AI 叙事质量不稳定 | 提供 fallback 叙事模板 |
| 玩家挫败感 | 首次死亡减免惩罚，提供详细复活指引 |
