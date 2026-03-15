"""
死亡判定与流程管理服务
对应设计文档: docs/design/gamedesign/deathdesign.md
对应技术文档: docs/technical/death-technical.md
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from app.models.schemas import (
    BattleRollPrompt,
    BattleRollResolution,
    BattleSandboxState,
    BattleStepEntry,
    CombatantState,
    DeathPenalties,
    InventoryItem,
    MapStateSyncBundle,
    PlayerDeathState,
    RoleBuff,
    RoleBuffEffect,
    SaveFile,
    SceneEvent,
)

if TYPE_CHECKING:
    from app.services.battle_runtime import BattleSandboxState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_step_id() -> str:
    return f"bstep_{uuid4().hex}"


def _new_event_id() -> str:
    return f"evt_{uuid4().hex[:12]}"


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


class DeathService:
    """死亡判定与流程管理服务"""

    # ========== 死亡判定 ==========

    def is_instant_death(self, target: CombatantState, damage: int) -> bool:
        """检查是否满足即死条件（超额伤害）
        
        当单次伤害将角色 HP 从正值降至负的最大生命值时触发即死
        """
        if target.current_hp > 0:
            excess = damage - target.current_hp
            return excess >= target.max_hp
        return False

    def check_and_apply_damage(
        self,
        state: BattleSandboxState,
        target: CombatantState,
        damage: int,
        damage_type: str = "",
        actor: CombatantState | None = None,
    ) -> dict:
        """统一伤害入口：应用伤害并处理可能的死亡流程
        
        由 battle_runtime, encounter_service, chat_service 调用
        
        Returns:
            dict: 包含 damage_applied, hp_remaining, triggered_death_check, is_instant_death 等
        """
        result = {
            "damage_applied": 0,
            "hp_remaining": target.current_hp,
            "triggered_death_check": False,
            "is_instant_death": False,
            "entered_dying": False,
            "declared_death": False,
        }

        # 应用伤害（复用 battle_runtime 的逻辑）
        remaining = max(0, int(damage))
        if target.temp_hp > 0:
            absorbed = min(target.temp_hp, remaining)
            target.temp_hp -= absorbed
            remaining -= absorbed
        if remaining > 0:
            target.current_hp = max(0, target.current_hp - remaining)
        
        result["damage_applied"] = damage
        result["hp_remaining"] = target.current_hp

        # 检查死亡流程（仅对玩家）
        if target.source_kind == "player" and target.current_hp <= 0:
            result["triggered_death_check"] = True
            
            # 检查即死
            if self.is_instant_death(target, damage):
                result["is_instant_death"] = True
                self.declare_death(state, target, is_instant=True, cause=f"超额伤害 ({damage})")
                result["declared_death"] = True
            else:
                # 进入濒死
                self.enter_dying_state(state, target, cause=f"战斗伤害 ({damage_type or '未知'})")
                result["entered_dying"] = True
                # 创建死亡豁免提示
                self.make_death_save_prompt(state, target)

        return result

    # ========== 濒死流程 ==========

    def enter_dying_state(
        self,
        state: BattleSandboxState | SaveFile,
        target: CombatantState,
        cause: str = "",
    ) -> None:
        """使玩家进入濒死状态"""
        target.downed = True
        target.alive = True  # 濒死仍算"活着"
        target.conditions = ["dying", "unconscious", "prone"]
        
        # 初始化死亡豁免状态
        death_state = target.death_state
        death_state.life_status = "dying"
        death_state.death_save_successes = 0
        death_state.death_save_failures = 0
        death_state.updated_at = _utc_now()

        # 添加战斗步骤
        if isinstance(state, BattleSandboxState):
            self._add_battle_step(
                state,
                kind="reaction_prompt",
                actor=target,
                content=f"{target.display_name} 重伤倒地，正在失去意识！进入濒死状态。",
                metadata={"cause": cause, "life_status": "dying"},
            )

    def make_death_save_prompt(
        self,
        state: BattleSandboxState,
        player: CombatantState,
    ) -> BattleRollPrompt:
        """创建死亡豁免检定提示（复用 reaction_prompt 机制）"""
        death_state = player.death_state
        
        prompt = BattleRollPrompt(
            prompt_id=f"death_save_{uuid4().hex[:12]}",
            roll_kind="death_save",
            actor_combatant_id=player.combatant_id,
            actor_name=player.display_name,
            ability_used="constitution",
            ability_modifier=0,  # 死亡豁免无加值
            dc=10,
            check_task="死亡豁免 - 与死亡抗争",
            source_label="濒死状态",
            threatened_consequence="如果失败，你离死亡更近一步。",
            success_hint="你顽强地撑住了，伤势没有继续恶化。",
            failure_hint="你感到生命力在流逝...",
            critical_success_hint="奇迹发生！你恢复了意识！",
            critical_failure_hint="情况急剧恶化！",
            metadata={
                "successes": death_state.death_save_successes,
                "failures": death_state.death_save_failures,
            },
        )
        state.pending_roll = prompt
        state.status = "awaiting_player_roll"
        
        self._add_battle_step(
            state,
            kind="reaction_prompt",
            actor=player,
            content=f"{player.display_name} 正在进行死亡豁免... (成功: {death_state.death_save_successes}/3, 失败: {death_state.death_save_failures}/3)",
            metadata={
                "roll_kind": "death_save",
                "successes": death_state.death_save_successes,
                "failures": death_state.death_save_failures,
            },
        )
        return prompt

    def resolve_death_save(
        self,
        state: BattleSandboxState,
        player: CombatantState,
        roll_result: BattleRollResolution,
    ) -> Literal["revived", "stabilized", "died", "continues"]:
        """处理死亡豁免结果
        
        Returns:
            - "revived": 自然20恢复1HP
            - "stabilized": 3次成功后稳定
            - "died": 3次失败后死亡
            - "continues": 继续濒死，已创建新的 death_save_prompt
        """
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
            death_state.updated_at = _utc_now()
            
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=player,
                content=f"奇迹！{player.display_name} 在濒死中恢复了意识！",
                metadata={"natural_20": True, "result": "revived"},
            )
            return "revived"
        
        if is_natural_1:
            # 大失败：2次失败
            death_state.death_save_failures += 2
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=player,
                content=f"情况急剧恶化！{player.display_name} 的伤势严重了。（失败+2）",
                metadata={"natural_1": True, "failures": death_state.death_save_failures},
            )
        elif success:
            death_state.death_save_successes += 1
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=player,
                content=f"{player.display_name} 撑住了这一轮。（成功+1）",
                metadata={"successes": death_state.death_save_successes},
            )
        else:
            death_state.death_save_failures += 1
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=player,
                content=f"{player.display_name} 感到生命力在流逝...（失败+1）",
                metadata={"failures": death_state.death_save_failures},
            )
        
        # 检查是否结束濒死
        if death_state.death_save_successes >= 3:
            # 稳定
            player.conditions = ["stable", "unconscious", "prone"]
            death_state.life_status = "stable"
            death_state.updated_at = _utc_now()
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=player,
                content=f"{player.display_name} 的伤势稳定了下来。",
                metadata={"result": "stabilized"},
            )
            return "stabilized"
        
        if death_state.death_save_failures >= 3:
            # 死亡
            self.declare_death(state, player, is_instant=False)
            return "died"
        
        # 继续濒死，准备下一次豁免
        self.make_death_save_prompt(state, player)
        return "continues"

    def stabilize(
        self,
        state: BattleSandboxState | SaveFile,
        target: CombatantState,
        stabilizer: CombatantState | None = None,
        method: Literal["medicine", "item"] = "medicine",
    ) -> dict:
        """稳定濒死玩家
        
        Returns:
            dict: 包含 success, stabilized, narrative 等
        """
        result = {
            "success": False,
            "stabilized": False,
            "narrative": "",
            "roll_result": None,
        }
        
        if "dying" not in target.conditions:
            result["narrative"] = "目标不在濒死状态"
            return result
        
        if method == "medicine":
            # 医药检定（DC 10）
            modifier = 0
            if stabilizer:
                modifier = stabilizer.ability_modifiers.wisdom
            
            roll = random.randint(1, 20)
            total = roll + modifier
            success = total >= 10
            
            result["roll_result"] = {
                "dice_roll": roll,
                "modifier": modifier,
                "total": total,
                "success": success,
            }
            
            if success:
                target.conditions = ["stable", "unconscious", "prone"]
                target.death_state.life_status = "stable"
                target.death_state.updated_at = _utc_now()
                result["success"] = True
                result["stabilized"] = True
                result["narrative"] = f"{stabilizer.display_name if stabilizer else '救援'}成功稳定了 {target.display_name} 的伤势。"
            else:
                result["narrative"] = f"{stabilizer.display_name if stabilizer else '救援'}未能稳定 {target.display_name} 的伤势。"
        else:
            # 使用物品直接稳定
            target.conditions = ["stable", "unconscious", "prone"]
            target.death_state.life_status = "stable"
            target.death_state.updated_at = _utc_now()
            result["success"] = True
            result["stabilized"] = True
            result["narrative"] = f"{target.display_name} 的伤势被稳定了下来。"
        
        if isinstance(state, BattleSandboxState) and result["stabilized"]:
            self._add_battle_step(
                state,
                kind="reaction_result",
                actor=target,
                content=result["narrative"],
                metadata={"result": "stabilized", "method": method},
            )
        
        return result

    # ========== 死亡与复活 ==========

    def declare_death(
        self,
        state: BattleSandboxState | SaveFile,
        player: CombatantState,
        is_instant: bool = False,
        cause: str = "",
    ) -> dict:
        """宣告玩家死亡，触发惩罚计算和战斗结束"""
        player.alive = False
        player.downed = True
        player.conditions = ["dead"]
        
        death_state = player.death_state
        death_state.life_status = "dead"
        death_state.death_count += 1
        death_state.death_streak_count += 1
        death_state.last_death_at = _utc_now()
        if cause:
            death_state.last_death_cause = cause
        death_state.updated_at = _utc_now()
        
        result = {
            "declared": True,
            "is_instant": is_instant,
            "death_count": death_state.death_count,
        }
        
        # 记录战斗日志
        if isinstance(state, BattleSandboxState):
            self._add_battle_step(
                state,
                kind="defeat",
                actor=player,
                content=f"{player.display_name} 死亡。" + ("（致命一击）" if is_instant else ""),
                metadata={
                    "death_count": death_state.death_count,
                    "is_instant": is_instant,
                    "cause": cause,
                },
            )
            
            # 触发战斗结束（玩家方失败）
            state.status = "ended"
            state.combat_state.phase = "ended"
            state.combat_state.winner_side = "enemy_side"
            self._add_battle_step(
                state,
                kind="end",
                content="战斗结束，玩家方战败。",
            )
        
        return result

    def calculate_penalties(
        self,
        save: SaveFile,
        death_state: PlayerDeathState | None = None,
    ) -> DeathPenalties:
        """计算死亡惩罚"""
        if death_state is None:
            death_state = save.player_static_data.dnd5e_sheet.death_state
        
        streak = death_state.death_streak_count
        
        # 基础惩罚
        gold = max(50, int(save.player_static_data.dnd5e_sheet.backpack.gold * 0.1))
        exp_loss = int(save.player_static_data.dnd5e_sheet.experience_current * 0.1)
        
        # 连续死亡惩罚
        weakness_min = 60 * (2 if streak >= 2 else 1) * (3 if streak >= 3 else 1)
        
        # 随机丢失非绑定物品
        items_lost = self._select_random_unbound_items(save, count=1)
        
        return DeathPenalties(
            gold_lost=gold,
            exp_lost=exp_loss,
            items_lost=items_lost,
            weakness_duration_min=weakness_min,
        )

    def _select_random_unbound_items(self, save: SaveFile, count: int = 1) -> list[str]:
        """随机选择非绑定物品丢失"""
        unbound_items = [
            item.item_id for item in save.player_static_data.dnd5e_sheet.backpack.items
            if not item.bound and item.item_type != "misc"
        ]
        if len(unbound_items) <= count:
            return unbound_items
        return random.sample(unbound_items, count)

    def revive_at_shrine(
        self,
        save: SaveFile,
        shrine_zone_id: str | None = None,
    ) -> dict:
        """在神庙/祭坛复活"""
        player = save.player_static_data
        death_state = player.dnd5e_sheet.death_state
        
        # 计算费用
        base_cost = player.dnd5e_sheet.level * 100
        cost = int(base_cost * (1.2 ** max(0, death_state.death_count - 1)))
        
        # 检查金币
        if player.dnd5e_sheet.backpack.gold < cost:
            return {
                "success": False,
                "error": "insufficient_gold",
                "required": cost,
                "available": player.dnd5e_sheet.backpack.gold,
            }
        
        # 计算惩罚
        penalties = self.calculate_penalties(save)
        
        # 扣费
        player.dnd5e_sheet.backpack.gold -= cost
        
        # 扣经验
        player.dnd5e_sheet.experience_current = max(
            0,
            player.dnd5e_sheet.experience_current - penalties.exp_lost
        )
        
        # 丢失物品
        for item_id in penalties.items_lost:
            player.dnd5e_sheet.backpack.items = [
                item for item in player.dnd5e_sheet.backpack.items
                if item.item_id != item_id
            ]
        
        # 恢复状态
        hp_max = player.dnd5e_sheet.hit_points.maximum
        player.dnd5e_sheet.hit_points.current = int(hp_max * 0.25)
        player.dnd5e_sheet.is_dead = False
        
        # 清除死亡状态
        death_state.life_status = "healthy"
        death_state.death_save_successes = 0
        death_state.death_save_failures = 0
        death_state.revived_at = _utc_now()
        death_state.revival_method = "shrine"
        death_state.updated_at = _utc_now()
        
        # 应用复活虚弱 buff
        self.apply_revival_weakness(player.dnd5e_sheet, penalties.weakness_duration_min)
        
        return {
            "success": True,
            "method": "shrine",
            "cost": cost,
            "penalties_applied": penalties,
            "narrative": f"你在神庙中苏醒，身体仍感到虚弱。花费了 {cost} 金币进行复活。",
        }

    def revive_by_item(
        self,
        save: SaveFile,
        item: InventoryItem,
    ) -> dict:
        """使用复活道具复活"""
        player = save.player_static_data
        death_state = player.dnd5e_sheet.death_state
        
        # 计算惩罚（队友复活惩罚较轻）
        penalties = DeathPenalties(
            gold_lost=0,
            exp_lost=0,
            items_lost=[],
            weakness_duration_min=30,  # 仅30分钟虚弱
        )
        
        # 恢复状态
        hp_max = player.dnd5e_sheet.hit_points.maximum
        player.dnd5e_sheet.hit_points.current = int(hp_max * 0.5)  # 道具复活恢复更多HP
        player.dnd5e_sheet.is_dead = False
        
        # 清除死亡状态
        death_state.life_status = "healthy"
        death_state.death_save_successes = 0
        death_state.death_save_failures = 0
        death_state.revived_at = _utc_now()
        death_state.revival_method = "item"
        death_state.updated_at = _utc_now()
        
        # 应用复活虚弱 buff
        self.apply_revival_weakness(player.dnd5e_sheet, penalties.weakness_duration_min)
        
        return {
            "success": True,
            "method": "item",
            "item_used": item.name,
            "penalties_applied": penalties,
            "narrative": f"{item.name} 的力量让你重新苏醒，虽然仍感到虚弱。",
        }

    def apply_revival_weakness(
        self,
        sheet: "Dnd5eCharacterSheet",
        duration_min: int,
    ) -> RoleBuff:
        """应用复活虚弱 buff"""
        buff = RoleBuff(
            buff_id=f"revival_weakness_{uuid4().hex[:12]}",
            name="复活虚弱",
            description="所有检定劣势，移速减半，无法获得经验。复活后的副作用。",
            source="revival",
            duration_min=duration_min,
            remaining_min=duration_min,
            effect=RoleBuffEffect(
                strength_delta=-2,
                dexterity_delta=-2,
                constitution_delta=-2,
                intelligence_delta=-2,
                wisdom_delta=-2,
                charisma_delta=-2,
                speed_ft_delta=-15,
            ),
        )
        sheet.buffs.append(buff)
        sheet.death_state.revival_weakness_until = (
            datetime.now(timezone.utc) + timedelta(minutes=duration_min)
        ).isoformat()
        return buff

    # ========== 状态管理 ==========

    def update_death_streak(
        self,
        death_state: PlayerDeathState,
        current_time: datetime | None = None,
    ) -> bool:
        """检查并重置连续死亡计数（24小时）
        
        Returns:
            bool: 是否重置了连击计数
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        if death_state.death_streak_reset_at:
            reset_time = datetime.fromisoformat(death_state.death_streak_reset_at)
            if current_time >= reset_time:
                # 超过24小时，重置连击
                death_state.death_streak_count = 0
                death_state.death_streak_reset_at = None
                death_state.updated_at = _utc_now()
                return True
        
        # 更新重置时间（从最后一次死亡开始计算24小时）
        if death_state.last_death_at:
            reset_time = datetime.fromisoformat(death_state.last_death_at) + timedelta(hours=24)
            death_state.death_streak_reset_at = reset_time.isoformat()
        
        return False

    def check_weakness_expired(
        self,
        sheet: "Dnd5eCharacterSheet",
        current_time: datetime | None = None,
    ) -> bool:
        """检查复活虚弱是否过期，如过期则移除
        
        Returns:
            bool: 是否移除了虚弱buff
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        death_state = sheet.death_state
        if death_state.revival_weakness_until:
            expiry = datetime.fromisoformat(death_state.revival_weakness_until)
            if current_time >= expiry:
                # 移除虚弱buff
                sheet.buffs = [
                    b for b in sheet.buffs
                    if b.name != "复活虚弱"
                ]
                death_state.revival_weakness_until = None
                death_state.updated_at = _utc_now()
                return True
        
        return False

    # ========== 辅助方法 ==========

    def _add_battle_step(
        self,
        state: BattleSandboxState,
        *,
        kind: BattleStepEntry.__annotations__["kind"],
        content: str,
        actor: CombatantState | None = None,
        metadata: dict | None = None,
    ) -> BattleStepEntry:
        """添加战斗步骤"""
        step = BattleStepEntry(
            step_id=_new_step_id(),
            round=max(1, state.combat_state.round),
            kind=kind,
            actor_combatant_id=actor.combatant_id if actor else None,
            actor_name=actor.display_name if actor else "",
            content=content,
            metadata=metadata or {},
        )
        state.battle_logs.append(step)
        state.combat_state.recent_steps = [
            item.model_copy(deep=True) for item in state.battle_logs[-40:]
        ]
        state.updated_at = _utc_now()
        return step

    def create_scene_event(
        self,
        kind: str,
        content: str,
        metadata: dict | None = None,
    ) -> SceneEvent:
        """创建场景事件"""
        return SceneEvent(
            event_id=_new_event_id(),
            kind=kind,  # type: ignore[arg-type]
            content=content,
            metadata=metadata or {},
        )


# 单例实例
death_service = DeathService()
