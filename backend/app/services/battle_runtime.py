from __future__ import annotations

from datetime import datetime, timezone
import random
import re
from typing import Iterable
from uuid import uuid4

from app.models.schemas import (
    BattleRollPrompt,
    BattleRollResolution,
    BattleSandboxState,
    BattleStepEntry,
    CombatantState,
)


_BAND_ORDER = ["engaged", "near", "far", "remote"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_step_id() -> str:
    return f"bstep_{uuid4().hex}"


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def _roll_dice(expr: str) -> int:
    text = (expr or "1d4").strip().lower()
    match = re.fullmatch(r"(\d+)d(\d+)", text)
    if not match:
        return 1
    count = max(1, int(match.group(1)))
    faces = max(2, int(match.group(2)))
    return sum(random.randint(1, faces) for _ in range(count))


def _critical_label(critical: str, success: bool) -> str:
    if critical == "critical_success":
        return "大成功"
    if critical == "critical_failure":
        return "大失败"
    return "成功" if success else "失败"


def _combatants(state: BattleSandboxState) -> list[CombatantState]:
    return state.combat_state.combatants


def _touch(state: BattleSandboxState) -> None:
    state.updated_at = _utc_now()


def _sync_snapshots(state: BattleSandboxState) -> None:
    combatants = _combatants(state)
    player = next((item for item in combatants if item.source_kind == "player"), None)
    if player is not None:
        state.player_snapshot = player.model_copy(deep=True)
    state.ally_snapshots = [item.model_copy(deep=True) for item in combatants if item.source_kind == "team"]
    state.enemy_snapshots = [item.model_copy(deep=True) for item in combatants if item.side == "enemy_side"]
    state.combat_state.recent_steps = [item.model_copy(deep=True) for item in state.battle_logs[-40:]]
    _touch(state)


def _add_step(
    state: BattleSandboxState,
    *,
    kind: BattleStepEntry.__annotations__["kind"],
    content: str,
    actor: CombatantState | None = None,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> BattleStepEntry:
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
    state.combat_state.recent_steps = [item.model_copy(deep=True) for item in state.battle_logs[-40:]]
    _touch(state)
    return step


def _find_combatant(state: BattleSandboxState, combatant_id: str | None) -> CombatantState | None:
    if not combatant_id:
        return None
    return next((item for item in _combatants(state) if item.combatant_id == combatant_id), None)


def _living_combatants(state: BattleSandboxState, *, side: str | None = None) -> list[CombatantState]:
    items = [item for item in _combatants(state) if item.alive and not item.downed and not item.escaped]
    if side is not None:
        items = [item for item in items if item.side == side]
    return items


def _roll_backend_d20(*, advantage: bool = False, disadvantage: bool = False) -> tuple[int, str]:
    if advantage and not disadvantage:
        first = random.randint(1, 20)
        second = random.randint(1, 20)
        return max(first, second), f"{first}/{second}"
    if disadvantage and not advantage:
        first = random.randint(1, 20)
        second = random.randint(1, 20)
        return min(first, second), f"{first}/{second}"
    value = random.randint(1, 20)
    return value, str(value)


def _critical_from_roll(d20: int) -> str:
    if d20 >= 20:
        return "critical_success"
    if d20 <= 1:
        return "critical_failure"
    return "none"


def _recompute_momentum(state: BattleSandboxState) -> None:
    player_hp = sum(max(0, item.current_hp + item.temp_hp) for item in _living_combatants(state, side="player_side"))
    enemy_hp = sum(max(0, item.current_hp + item.temp_hp) for item in _living_combatants(state, side="enemy_side"))
    state.combat_state.momentum_value = _clamp((player_hp - enemy_hp) * 5, -100, 100)


def _consume_next_attack_bonus(attacker: CombatantState, target_id: str) -> int:
    if attacker.next_attack_bonus_against == target_id and attacker.next_attack_bonus_amount:
        bonus = attacker.next_attack_bonus_amount
        attacker.next_attack_bonus_against = None
        attacker.next_attack_bonus_amount = 0
        return bonus
    return 0


def _refresh_turn_resources(combatant: CombatantState) -> None:
    if combatant.temporary_ac_bonus:
        combatant.armor_class = max(combatant.base_armor_class, combatant.armor_class - combatant.temporary_ac_bonus)
        combatant.temporary_ac_bonus = 0
    combatant.conditions = [item for item in combatant.conditions if item != "defending"]
    combatant.action_available = True
    combatant.bonus_action_available = True
    combatant.reaction_available = True
    combatant.movement_remaining = combatant.speed


def _sorted_initiative_order(state: BattleSandboxState) -> list[str]:
    return [
        item.combatant_id
        for item in sorted(
            _combatants(state),
            key=lambda item: (
                item.initiative,
                1 if item.source_kind == "player" else 0,
                item.display_name.lower(),
            ),
            reverse=True,
        )
        if item.alive and not item.downed and not item.escaped
    ]


def _check_battle_end(state: BattleSandboxState) -> bool:
    player_side = _living_combatants(state, side="player_side")
    enemy_side = _living_combatants(state, side="enemy_side")
    if not player_side:
        state.status = "ended"
        state.combat_state.phase = "ended"
        state.combat_state.winner_side = "enemy_side"
        _add_step(state, kind="end", content="战斗结束，敌方取得优势。")
        _sync_snapshots(state)
        return True
    if not enemy_side:
        state.status = "ended"
        state.combat_state.phase = "ended"
        state.combat_state.winner_side = "player_side"
        _add_step(state, kind="end", content="战斗结束，玩家方取得胜利。")
        _sync_snapshots(state)
        return True
    return False


def _advance_to_next_turn(state: BattleSandboxState) -> None:
    if _check_battle_end(state):
        return
    order = [item for item in state.combat_state.initiative_order if _find_combatant(state, item) and _find_combatant(state, item).alive and not _find_combatant(state, item).escaped]  # type: ignore[union-attr]
    if not order:
        order = _sorted_initiative_order(state)
    current_id = state.combat_state.active_combatant_id
    if current_id in order:
        next_index = order.index(current_id) + 1
    else:
        next_index = 0
    if next_index >= len(order):
        state.combat_state.round += 1
        next_index = 0
    state.combat_state.initiative_order = order
    active_id = order[next_index]
    state.combat_state.active_combatant_id = active_id
    state.combat_state.phase = "turn"
    actor = _find_combatant(state, active_id)
    if actor is None:
        _check_battle_end(state)
        return
    _refresh_turn_resources(actor)
    _add_step(state, kind="turn_start", actor=actor, content=f"第 {state.combat_state.round} 轮，轮到 {actor.display_name} 行动。")
    if actor.source_kind == "player":
        state.status = "awaiting_player_action"
    else:
        state.status = "awaiting_ai_continue"
        state.ui_flags.can_continue_ai = True
    _sync_snapshots(state)


def _apply_damage(state: BattleSandboxState, target: CombatantState, amount: int, *, actor: CombatantState | None = None, damage_type: str = "") -> int:
    remaining = max(0, int(amount))
    if target.temp_hp > 0:
        absorbed = min(target.temp_hp, remaining)
        target.temp_hp -= absorbed
        remaining -= absorbed
    if remaining > 0:
        target.current_hp = max(0, target.current_hp - remaining)
    if target.current_hp <= 0:
        target.downed = True
        target.alive = False
    total_applied = int(amount)
    _add_step(
        state,
        kind="damage",
        actor=actor,
        content=f"{target.display_name} 受到 {total_applied} 点{damage_type or ''}伤害，剩余 HP {target.current_hp}/{target.max_hp}。",
        metadata={"damage": total_applied, "target_hp": target.current_hp},
    )
    if target.downed:
        _add_step(state, kind="defeat", content=f"{target.display_name} 倒下了。", actor=target)
    _recompute_momentum(state)
    return total_applied


def _perform_attack(
    state: BattleSandboxState,
    attacker: CombatantState,
    target: CombatantState,
    *,
    dice_roll: int | None = None,
    bonus_override: int = 0,
) -> tuple[bool, str, int]:
    d20 = dice_roll if dice_roll is not None else random.randint(1, 20)
    critical = _critical_from_roll(d20)
    total = d20 + attacker.attack_bonus + bonus_override
    success = total >= target.armor_class or critical == "critical_success"
    if critical == "critical_failure":
        success = False
    if not success:
        _add_step(
            state,
            kind="attack",
            actor=attacker,
            content=f"{attacker.display_name} 攻击 {target.display_name}，d20={d20}，总值 {total} 对抗 AC {target.armor_class}，未能命中。",
            metadata={"target_ac": target.armor_class, "dice_roll": d20, "total_score": total},
        )
        return False, critical, 0
    damage = _roll_dice(attacker.damage_profile.dice) + attacker.damage_profile.flat_bonus
    if critical == "critical_success":
        damage += _roll_dice(attacker.damage_profile.dice)
    applied = _apply_damage(state, target, damage, actor=attacker, damage_type=attacker.damage_profile.damage_type)
    _add_step(
        state,
        kind="attack",
        actor=attacker,
        content=f"{attacker.display_name} 攻击命中 {target.display_name}，d20={d20}，总值 {total} 对抗 AC {target.armor_class}，造成 {applied} 点伤害。",
        metadata={"target_ac": target.armor_class, "dice_roll": d20, "total_score": total, "damage": applied},
    )
    return True, critical, applied


def _make_reaction_prompt(state: BattleSandboxState, attacker: CombatantState, target: CombatantState) -> BattleRollPrompt:
    dc = _clamp(10 + max(1, attacker.attack_bonus), 8, 20)
    pending = BattleRollPrompt(
        prompt_id=f"broll_{uuid4().hex}",
        roll_kind="reaction",
        actor_combatant_id=target.combatant_id,
        actor_name=target.display_name,
        ability_used="dexterity",
        ability_modifier=int(target.saving_throw_bonuses.dexterity),
        dc=dc,
        check_task=f"躲开 {attacker.display_name} 的攻击",
        source_label=attacker.display_name,
        threatened_consequence=f"{attacker.display_name} 正朝你发动攻击。",
        success_hint="你可能及时躲开，只被迫后退。",
        failure_hint="你可能被正面击中并受到伤害。",
        target_combatant_id=attacker.combatant_id,
        action_name="玩家反应豁免",
        metadata={
            "attacker_id": attacker.combatant_id,
            "damage_dice": attacker.damage_profile.dice,
            "damage_bonus": attacker.damage_profile.flat_bonus,
            "damage_type": attacker.damage_profile.damage_type,
        },
    )
    state.pending_roll = pending
    state.status = "awaiting_player_roll"
    _add_step(state, kind="reaction_prompt", actor=attacker, content=f"{attacker.display_name} 突然朝你扑来，你需要立刻做出反应。")
    _sync_snapshots(state)
    return pending


def _choose_ai_target(state: BattleSandboxState, actor: CombatantState) -> CombatantState | None:
    enemies = _living_combatants(state, side="enemy_side" if actor.side == "player_side" else "player_side")
    if not enemies:
        return None
    if actor.side == "enemy_side":
        player = next((item for item in enemies if item.source_kind == "player"), None)
        if player is not None:
            return player
    return sorted(enemies, key=lambda item: (item.current_hp, item.max_hp, item.display_name.lower()))[0]


def _move_band(current: str, destination: str | None, *, away: bool = False) -> str:
    try:
        index = _BAND_ORDER.index(current)
    except ValueError:
        index = 1
    if destination and destination in _BAND_ORDER:
        target_index = _BAND_ORDER.index(destination)
        if target_index > index:
            return _BAND_ORDER[min(index + 1, target_index)]
        if target_index < index:
            return _BAND_ORDER[max(index - 1, target_index)]
        return current
    if away:
        return _BAND_ORDER[min(len(_BAND_ORDER) - 1, index + 1)]
    return _BAND_ORDER[max(0, index - 1)]


def _normalize_battle(state: BattleSandboxState) -> BattleSandboxState:
    _recompute_momentum(state)
    _sync_snapshots(state)
    return state


def initialize_player_initiative_prompt(state: BattleSandboxState) -> BattleSandboxState:
    player = state.player_snapshot
    state.pending_roll = BattleRollPrompt(
        prompt_id=f"broll_{uuid4().hex}",
        roll_kind="initiative",
        actor_combatant_id=player.combatant_id,
        actor_name=player.display_name,
        ability_used="dexterity",
        ability_modifier=player.initiative_bonus,
        dc=10,
        check_task="掷出本场战斗的先攻",
        source_label=state.battlefield.sub_zone_name or state.battlefield.zone_name,
        threatened_consequence="先攻越高，你越容易抢先行动。",
        success_hint="更高的先攻能让你更快出手。",
        failure_hint="若先攻较低，你可能被敌人先发制人。",
        action_name="先攻",
    )
    state.status = "awaiting_player_roll"
    _add_step(state, kind="setup", content=f"战斗在 {state.battlefield.sub_zone_name or state.battlefield.zone_name} 开始。")
    _sync_snapshots(state)
    return state


def resolve_pending_roll(state: BattleSandboxState, forced_dice_roll: int) -> BattleRollResolution:
    prompt = state.pending_roll
    if prompt is None:
        raise ValueError("BATTLE_ROLL_NOT_PENDING")
    actor = _find_combatant(state, prompt.actor_combatant_id)
    if actor is None:
        raise ValueError("BATTLE_ACTOR_NOT_FOUND")
    roll = _clamp(forced_dice_roll, 1, 20)
    critical = _critical_from_roll(roll)
    total = roll + int(prompt.ability_modifier)
    success = total >= prompt.dc or critical == "critical_success"
    if critical == "critical_failure":
        success = False
    summary = ""
    if prompt.roll_kind == "initiative":
        actor.initiative = total
        state.combat_state.initiative_order = _sorted_initiative_order(state)
        state.combat_state.active_combatant_id = state.combat_state.initiative_order[0] if state.combat_state.initiative_order else None
        state.combat_state.phase = "turn"
        summary = f"{actor.display_name} 的先攻为 {total}。"
        _add_step(state, kind="initiative", actor=actor, content=f"{actor.display_name} 掷出先攻 d20={roll}，总值 {total}。")
        state.pending_roll = None
        if state.combat_state.active_combatant_id == actor.combatant_id:
            state.status = "awaiting_player_action"
            _refresh_turn_resources(actor)
            _add_step(state, kind="turn_start", actor=actor, content=f"第 1 轮开始，{actor.display_name} 抢先行动。")
        else:
            active = _find_combatant(state, state.combat_state.active_combatant_id)
            if active is not None:
                _refresh_turn_resources(active)
                _add_step(state, kind="turn_start", actor=active, content=f"第 1 轮开始，轮到 {active.display_name} 行动。")
            state.status = "awaiting_ai_continue"
            state.ui_flags.can_continue_ai = True
    elif prompt.roll_kind == "attack":
        target = _find_combatant(state, prompt.target_combatant_id)
        if target is None:
            raise ValueError("BATTLE_TARGET_NOT_FOUND")
        bonus = _consume_next_attack_bonus(actor, target.combatant_id)
        hit, _, damage = _perform_attack(state, actor, target, dice_roll=roll, bonus_override=bonus)
        state.pending_roll = None
        summary = f"{actor.display_name} 的攻击{('命中' if hit else '落空')}。"
        state.last_roll_result = BattleRollResolution(
            prompt_id=prompt.prompt_id,
            actor_combatant_id=actor.combatant_id,
            actor_name=actor.display_name,
            roll_kind=prompt.roll_kind,
            ability_used=prompt.ability_used,
            ability_modifier=prompt.ability_modifier,
            dc=prompt.dc,
            dice_roll=roll,
            total_score=total,
            success=hit,
            critical=critical,  # type: ignore[arg-type]
            summary=f"{summary} 伤害 {damage}。",
        )
        _advance_to_next_turn(state)
        _normalize_battle(state)
        return state.last_roll_result
    elif prompt.roll_kind == "observe":
        target = _find_combatant(state, prompt.target_combatant_id)
        if target is None:
            raise ValueError("BATTLE_TARGET_NOT_FOUND")
        if success:
            actor.next_attack_bonus_against = target.combatant_id
            actor.next_attack_bonus_amount = 2
            _add_step(state, kind="observe", actor=actor, content=f"{actor.display_name} 看穿了 {target.display_name} 的破绽，下一次攻击获得 +2。")
        else:
            _add_step(state, kind="observe", actor=actor, content=f"{actor.display_name} 试图观察 {target.display_name}，但没抓到明显破绽。")
        state.pending_roll = None
        summary = f"{actor.display_name} 的观察{_critical_label(critical, success)}。"
        state.last_roll_result = BattleRollResolution(
            prompt_id=prompt.prompt_id,
            actor_combatant_id=actor.combatant_id,
            actor_name=actor.display_name,
            roll_kind=prompt.roll_kind,
            ability_used=prompt.ability_used,
            ability_modifier=prompt.ability_modifier,
            dc=prompt.dc,
            dice_roll=roll,
            total_score=total,
            success=success,
            critical=critical,  # type: ignore[arg-type]
            summary=summary,
        )
        _advance_to_next_turn(state)
        _normalize_battle(state)
        return state.last_roll_result
    elif prompt.roll_kind == "escape":
        state.pending_roll = None
        if success:
            state.status = "ended"
            state.combat_state.phase = "ended"
            state.combat_state.winner_side = "escaped"
            actor.escaped = True
            _add_step(state, kind="escape", actor=actor, content=f"{actor.display_name} 成功脱离了战场。")
            _add_step(state, kind="end", content="战斗以玩家脱离结束。")
        else:
            _add_step(state, kind="escape", actor=actor, content=f"{actor.display_name} 试图脱离战场，但没有成功。")
            _advance_to_next_turn(state)
        summary = f"{actor.display_name} 的逃离检定{_critical_label(critical, success)}。"
    elif prompt.roll_kind == "reaction":
        attacker = _find_combatant(state, str(prompt.metadata.get("attacker_id") or ""))
        state.pending_roll = None
        damage = 0
        if not success and attacker is not None:
            damage = _roll_dice(str(prompt.metadata.get("damage_dice") or "1d4")) + int(prompt.metadata.get("damage_bonus") or 0)
            if critical == "critical_failure":
                damage += 2
            _apply_damage(state, actor, damage, actor=attacker, damage_type=str(prompt.metadata.get("damage_type") or ""))
            _add_step(state, kind="reaction_result", actor=actor, content=f"因为反应检定失败，你被 {attacker.display_name} 击中。")
        else:
            label = "大成功" if critical == "critical_success" else "成功"
            _add_step(state, kind="reaction_result", actor=actor, content=f"因为反应检定{label}，你及时躲开了这次攻击。")
        summary = f"{actor.display_name} 的反应检定{_critical_label(critical, success)}。"
        _advance_to_next_turn(state)
    elif prompt.roll_kind == "item_use":
        state.pending_roll = None
        summary = f"{actor.display_name} 使用物品完成检定。"
        _advance_to_next_turn(state)
    else:
        raise ValueError("BATTLE_ROLL_KIND_UNSUPPORTED")

    resolution = BattleRollResolution(
        prompt_id=prompt.prompt_id,
        actor_combatant_id=actor.combatant_id,
        actor_name=actor.display_name,
        roll_kind=prompt.roll_kind,
        ability_used=prompt.ability_used,
        ability_modifier=prompt.ability_modifier,
        dc=prompt.dc,
        dice_roll=roll,
        total_score=total,
        success=success,
        critical=critical,  # type: ignore[arg-type]
        summary=summary,
    )
    state.last_roll_result = resolution
    _normalize_battle(state)
    return resolution


def submit_player_action(
    state: BattleSandboxState,
    *,
    action_kind: str,
    target_combatant_id: str | None = None,
    destination_band: str | None = None,
    item_id: str | None = None,
) -> BattleSandboxState:
    actor = _find_combatant(state, state.combat_state.active_combatant_id)
    if actor is None or actor.source_kind != "player":
        raise ValueError("BATTLE_NOT_PLAYER_TURN")
    if state.status != "awaiting_player_action":
        raise ValueError("BATTLE_PLAYER_ACTION_NOT_ALLOWED")
    if action_kind == "attack":
        target = _find_combatant(state, target_combatant_id)
        if target is None or target.side == actor.side:
            raise ValueError("BATTLE_TARGET_NOT_FOUND")
        state.pending_roll = BattleRollPrompt(
            prompt_id=f"broll_{uuid4().hex}",
            roll_kind="attack",
            actor_combatant_id=actor.combatant_id,
            actor_name=actor.display_name,
            ability_used="strength",
            ability_modifier=actor.attack_bonus,
            dc=target.armor_class,
            check_task=f"攻击 {target.display_name}",
            source_label=target.display_name,
            threatened_consequence=f"若命中，你将对 {target.display_name} 造成伤害。",
            success_hint="你可能直接打出有效伤害。",
            failure_hint="你会浪费这次进攻机会。",
            target_combatant_id=target.combatant_id,
            action_name="攻击",
        )
        state.status = "awaiting_player_roll"
        _add_step(state, kind="attack", actor=actor, content=f"{actor.display_name} 朝 {target.display_name} 发起攻击。")
    elif action_kind == "defend":
        actor.temporary_ac_bonus = 2
        actor.armor_class = actor.base_armor_class + actor.temporary_ac_bonus
        if "defending" not in actor.conditions:
            actor.conditions.append("defending")
        _add_step(state, kind="defend", actor=actor, content=f"{actor.display_name} 进入防御姿态，本轮 AC +2。")
        _advance_to_next_turn(state)
    elif action_kind == "move":
        next_band = _move_band(actor.position_band, destination_band)
        actor.position_band = next_band  # type: ignore[assignment]
        _add_step(state, kind="move", actor=actor, content=f"{actor.display_name} 调整位置，来到 {next_band} 距离。")
        _advance_to_next_turn(state)
    elif action_kind == "disengage":
        actor.position_band = _move_band(actor.position_band, destination_band, away=True)  # type: ignore[assignment]
        _add_step(state, kind="disengage", actor=actor, content=f"{actor.display_name} 小心脱离接触，退到 {actor.position_band} 距离。")
        _advance_to_next_turn(state)
    elif action_kind == "escape":
        state.pending_roll = BattleRollPrompt(
            prompt_id=f"broll_{uuid4().hex}",
            roll_kind="escape",
            actor_combatant_id=actor.combatant_id,
            actor_name=actor.display_name,
            ability_used="dexterity",
            ability_modifier=int(actor.ability_modifiers.dexterity),
            dc=12,
            check_task="脱离这场测试战斗",
            source_label=state.battlefield.sub_zone_name or state.battlefield.zone_name,
            threatened_consequence="若失败，你会被迫继续留在战场上。",
            success_hint="你将顺利脱离本场测试战斗。",
            failure_hint="你会被拖回战斗节奏里。",
            action_name="逃离",
        )
        state.status = "awaiting_player_roll"
        _add_step(state, kind="escape", actor=actor, content=f"{actor.display_name} 寻找战场缝隙，准备逃离。")
    elif action_kind == "observe":
        target = _find_combatant(state, target_combatant_id)
        if target is None or target.side == actor.side:
            raise ValueError("BATTLE_TARGET_NOT_FOUND")
        state.pending_roll = BattleRollPrompt(
            prompt_id=f"broll_{uuid4().hex}",
            roll_kind="observe",
            actor_combatant_id=actor.combatant_id,
            actor_name=actor.display_name,
            ability_used="wisdom",
            ability_modifier=int(actor.ability_modifiers.wisdom),
            dc=10,
            check_task=f"观察 {target.display_name} 的破绽",
            source_label=target.display_name,
            threatened_consequence="若失败，你会浪费这个回合的观察机会。",
            success_hint="你会找到破绽，下一击更容易命中。",
            failure_hint="你没法看出更清晰的进攻窗口。",
            target_combatant_id=target.combatant_id,
            action_name="观察",
        )
        state.status = "awaiting_player_roll"
        _add_step(state, kind="observe", actor=actor, content=f"{actor.display_name} 盯住 {target.display_name} 的动作，试图找出破绽。")
    elif action_kind == "use_item":
        item = next((entry for entry in actor.inventory_items if entry.item_id == item_id), None)
        if item is None:
            raise ValueError("BATTLE_ITEM_NOT_FOUND")
        heal_amount = 6
        effect_text = f"{item.name} 的效果发动。"
        if any(keyword in f"{item.item_type} {item.name} {item.effect}".lower() for keyword in ["heal", "healing", "回复", "治疗", "potion"]):
            before = actor.current_hp
            actor.current_hp = min(actor.max_hp, actor.current_hp + heal_amount)
            item.quantity = max(0, item.quantity - 1)
            if item.quantity == 0:
                actor.inventory_items = [entry for entry in actor.inventory_items if entry.item_id != item.item_id]
            effect_text = f"{actor.display_name} 使用 {item.name}，恢复了 {actor.current_hp - before} 点 HP。"
        else:
            effect_text = f"{actor.display_name} 使用 {item.name}，但第一阶段只完整支持回复类物品。"
        _add_step(state, kind="item_use", actor=actor, content=effect_text)
        _advance_to_next_turn(state)
    elif action_kind == "end_turn":
        _add_step(state, kind="system", actor=actor, content=f"{actor.display_name} 主动结束了回合。")
        _advance_to_next_turn(state)
    else:
        raise ValueError("BATTLE_ACTION_UNSUPPORTED")
    return _normalize_battle(state)


def continue_ai_turns(state: BattleSandboxState, *, ai_pacing: str | None = None) -> BattleSandboxState:
    if ai_pacing in {"step", "auto"}:
        state.ui_flags.ai_pacing = ai_pacing  # type: ignore[assignment]
    if state.status not in {"awaiting_ai_continue", "active"}:
        raise ValueError("BATTLE_AI_CONTINUE_NOT_ALLOWED")
    while True:
        if _check_battle_end(state):
            break
        actor = _find_combatant(state, state.combat_state.active_combatant_id)
        if actor is None or actor.source_kind == "player":
            if actor is not None:
                state.status = "awaiting_player_action"
            break
        target = _choose_ai_target(state, actor)
        if target is None:
            _check_battle_end(state)
            break
        acted = False
        if actor.current_hp <= max(3, actor.max_hp // 4):
            actor.position_band = _move_band(actor.position_band, None, away=True)  # type: ignore[assignment]
            _add_step(state, kind="move", actor=actor, content=f"{actor.display_name} 察觉不妙，往更安全的位置后撤到 {actor.position_band}。")
            acted = True
        elif actor.ai_style in {"protect_pack", "hold_line"} and "defending" not in actor.conditions and actor.current_hp <= actor.max_hp // 2:
            actor.temporary_ac_bonus = 2
            actor.armor_class = actor.base_armor_class + actor.temporary_ac_bonus
            actor.conditions.append("defending")
            _add_step(state, kind="defend", actor=actor, content=f"{actor.display_name} 收紧架势，准备稳住阵线。")
            acted = True
        else:
            if target.source_kind == "player" and actor.side == "enemy_side":
                _make_reaction_prompt(state, actor, target)
                acted = True
            else:
                _perform_attack(state, actor, target)
                acted = True
        if state.pending_roll is not None:
            state.ui_flags.can_continue_ai = False
            break
        if acted:
            _advance_to_next_turn(state)
        if state.status == "awaiting_player_action" or state.status == "ended":
            break
        if state.ui_flags.ai_pacing == "step":
            break
    return _normalize_battle(state)
