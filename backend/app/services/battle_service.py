from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from openai import APIError

from app.core.prompt_table import prompt_table
from app.models.schemas import (
    BattleCurrentResponse,
    BattleDamageProfile,
    BattleEndResponse,
    BattleFieldState,
    BattleSandboxState,
    BattleStartRequest,
    BattleStartResponse,
    CombatState,
    CombatantState,
    Dnd5eAbilityModifiers,
    InventoryItem,
    NpcRoleCard,
    PlayerStaticData,
    SaveFile,
    TeamMember,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services.battle_debug_service import clear_current_battle, load_current_battle, save_current_battle
from app.services.battle_runtime import (
    continue_ai_turns,
    initialize_player_initiative_prompt,
    resolve_pending_roll,
    submit_player_action,
)
from app.services.battle_templates import build_group_payloads, fallback_group_for_ai, list_template_group_names
from app.services.inventory_projection_service import resolve_combat_inventory_projection, resolve_equipment_snapshot
from app.services.item_instance_service import ensure_item_system
from app.services.world_service import _new_game_log, get_current_save, save_current
from app.services.zone_metric_service import get_current_zone_metric


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _new_combatant_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _ability_modifier_dict(source: Dnd5eAbilityModifiers) -> Dnd5eAbilityModifiers:
    return Dnd5eAbilityModifiers.model_validate(source.model_dump())


def _saving_throw_bonus(sheet, ability: str) -> int:
    mod = int(getattr(sheet.current_ability_modifiers, ability))
    if ability in list(sheet.saving_throws_proficient or []):
        mod += int(sheet.proficiency_bonus)
    return mod


def _saving_throw_modifiers(sheet) -> Dnd5eAbilityModifiers:
    return Dnd5eAbilityModifiers(
        strength=_saving_throw_bonus(sheet, "strength"),
        dexterity=_saving_throw_bonus(sheet, "dexterity"),
        constitution=_saving_throw_bonus(sheet, "constitution"),
        intelligence=_saving_throw_bonus(sheet, "intelligence"),
        wisdom=_saving_throw_bonus(sheet, "wisdom"),
        charisma=_saving_throw_bonus(sheet, "charisma"),
    )


def _sheet_attack_bonus(sheet) -> int:
    weapon = next((item for item in sheet.backpack.items if item.item_id == sheet.equipment_slots.weapon_item_id), None)
    base = max(int(sheet.current_ability_modifiers.strength), int(sheet.current_ability_modifiers.dexterity))
    proficiency = int(sheet.proficiency_bonus)
    return base + proficiency + int(weapon.attack_bonus if weapon else 0)


def _sheet_damage_profile(sheet) -> BattleDamageProfile:
    weapon = next((item for item in sheet.backpack.items if item.item_id == sheet.equipment_slots.weapon_item_id), None)
    flat_bonus = max(int(sheet.current_ability_modifiers.strength), int(sheet.current_ability_modifiers.dexterity))
    if weapon is not None:
        return BattleDamageProfile(
            dice="1d8",
            damage_type=weapon.item_type or "weapon",
            flat_bonus=flat_bonus + int(weapon.attack_bonus),
        )
    return BattleDamageProfile(dice="1d4", damage_type="bludgeoning", flat_bonus=flat_bonus)


def _snapshot_inventory(items: list[InventoryItem]) -> list[InventoryItem]:
    return [InventoryItem.model_validate(item.model_dump()) for item in items]


def _combatant_from_player(save: SaveFile, player: PlayerStaticData) -> CombatantState:
    sheet = player.dnd5e_sheet
    instance_ids, projected_items = resolve_combat_inventory_projection(save, owner_kind="player", owner_id=player.player_id)
    equipment_snapshot = resolve_equipment_snapshot(save, owner_kind="player", owner_id=player.player_id)
    return CombatantState(
        combatant_id="player_main",
        source_kind="player",
        role_id=player.player_id,
        display_name=player.name,
        side="player_side",
        role_kind="adventurer",
        ai_style="hold_line",
        level_hint=int(sheet.level),
        max_hp=int(sheet.hit_points.maximum),
        current_hp=int(sheet.hit_points.current),
        temp_hp=int(sheet.hit_points.temporary),
        base_armor_class=int(sheet.armor_class),
        armor_class=int(sheet.armor_class),
        speed=max(1, int(sheet.speed_ft) // 10 or 6),
        initiative_bonus=int(sheet.initiative_bonus or sheet.current_ability_modifiers.dexterity),
        attack_bonus=_sheet_attack_bonus(sheet),
        damage_profile=_sheet_damage_profile(sheet),
        ability_modifiers=_ability_modifier_dict(sheet.current_ability_modifiers),
        saving_throw_bonuses=_saving_throw_modifiers(sheet),
        position_band="near",
        position_feature_tags=list(sheet.features_traits or [])[:4],
        movement_remaining=max(1, int(sheet.speed_ft) // 10 or 6),
        inventory_item_instance_ids=instance_ids,
        equipped_weapon_instance_id=equipment_snapshot["weapon_item_instance_id"],
        equipped_armor_instance_id=equipment_snapshot["armor_item_instance_id"],
        equipped_shield_instance_id=equipment_snapshot["shield_item_instance_id"],
        inventory_items=_snapshot_inventory(projected_items),
    )


def _combatant_from_role(save: SaveFile, role: NpcRoleCard, *, source_kind: str = "team", side: str = "player_side") -> CombatantState:
    profile = role.profile
    sheet = profile.dnd5e_sheet
    instance_ids, projected_items = resolve_combat_inventory_projection(save, owner_kind="role", owner_id=role.role_id)
    equipment_snapshot = resolve_equipment_snapshot(save, owner_kind="role", owner_id=role.role_id)
    return CombatantState(
        combatant_id=f"{source_kind}_{role.role_id}",
        source_kind=source_kind,  # type: ignore[arg-type]
        role_id=role.role_id,
        display_name=role.name,
        side=side,  # type: ignore[arg-type]
        role_kind="adventurer" if side == "player_side" else "skirmisher",
        ai_style="protect_player" if side == "player_side" else "rush_target",
        level_hint=int(sheet.level),
        max_hp=int(sheet.hit_points.maximum),
        current_hp=int(sheet.hit_points.current),
        temp_hp=int(sheet.hit_points.temporary),
        base_armor_class=int(sheet.armor_class),
        armor_class=int(sheet.armor_class),
        speed=max(1, int(sheet.speed_ft) // 10 or 6),
        initiative_bonus=int(sheet.initiative_bonus or sheet.current_ability_modifiers.dexterity),
        attack_bonus=_sheet_attack_bonus(sheet),
        damage_profile=_sheet_damage_profile(sheet),
        ability_modifiers=_ability_modifier_dict(sheet.current_ability_modifiers),
        saving_throw_bonuses=_saving_throw_modifiers(sheet),
        position_band="near",
        position_feature_tags=[item for item in [role.personality, role.speaking_style] if item][:3],
        movement_remaining=max(1, int(sheet.speed_ft) // 10 or 6),
        inventory_item_instance_ids=instance_ids,
        equipped_weapon_instance_id=equipment_snapshot["weapon_item_instance_id"],
        equipped_armor_instance_id=equipment_snapshot["armor_item_instance_id"],
        equipped_shield_instance_id=equipment_snapshot["shield_item_instance_id"],
        inventory_items=_snapshot_inventory(projected_items),
    )


def _enemy_from_payload(payload: dict, *, index: int) -> CombatantState:
    ability_modifiers = Dnd5eAbilityModifiers.model_validate(payload.get("ability_modifiers") or {})
    saving_throws = Dnd5eAbilityModifiers.model_validate(payload.get("saving_throw_bonuses") or payload.get("ability_modifiers") or {})
    damage_profile = BattleDamageProfile.model_validate(payload.get("damage_profile") or {})
    name = str(payload.get("name") or "测试怪物").strip() or "测试怪物"
    return CombatantState(
        combatant_id=_new_combatant_id("monster"),
        source_kind="test_monster",
        role_id=None,
        display_name=name if index == 1 else f"{name}#{index}",
        side="enemy_side",
        template_id=(payload.get("template_id") or None),
        role_kind=(payload.get("role_kind") or "brute"),
        ai_style=str(payload.get("ai_style") or "rush_target"),
        level_hint=max(1, int(payload.get("level_hint") or 1)),
        max_hp=max(1, int(payload.get("max_hp") or 10)),
        current_hp=max(1, int(payload.get("max_hp") or 10)),
        temp_hp=0,
        base_armor_class=max(5, int(payload.get("armor_class") or 10)),
        armor_class=max(5, int(payload.get("armor_class") or 10)),
        speed=max(1, int(payload.get("speed") or 6)),
        initiative_bonus=int(ability_modifiers.dexterity),
        attack_bonus=int(payload.get("attack_bonus") or 2),
        damage_profile=damage_profile,
        ability_modifiers=ability_modifiers,
        saving_throw_bonuses=saving_throws,
        position_band="near" if str(payload.get("role_kind") or "") not in {"ranged", "support"} else "far",
        position_feature_tags=list(payload.get("feature_tags") or []),
        movement_remaining=max(1, int(payload.get("speed") or 6)),
    )


def _current_battlefield(save: SaveFile) -> BattleFieldState:
    zone = next((item for item in save.area_snapshot.zones if item.zone_id == save.area_snapshot.current_zone_id), None)
    sub_zone = next((item for item in save.area_snapshot.sub_zones if item.sub_zone_id == save.area_snapshot.current_sub_zone_id), None)
    metric = get_current_zone_metric(save, create=False)
    feature_tags = []
    if sub_zone is not None:
        feature_tags.extend([interaction.name for interaction in sub_zone.key_interactions[:4]])
        feature_tags.extend([npc.name for npc in sub_zone.npcs[:2]])
    return BattleFieldState(
        zone_id=save.area_snapshot.current_zone_id,
        zone_name=zone.name if zone else (save.area_snapshot.current_zone_id or ""),
        sub_zone_id=save.area_snapshot.current_sub_zone_id,
        sub_zone_name=sub_zone.name if sub_zone else (save.area_snapshot.current_sub_zone_id or ""),
        description=sub_zone.description if sub_zone else (zone.description if zone else ""),
        feature_tags=feature_tags[:6],
        danger_score=metric.danger_score if metric else None,
        reputation_score=metric.reputation_score if metric else None,
    )


def _build_allies(save: SaveFile) -> list[CombatantState]:
    role_map = {item.role_id: item for item in save.role_pool}
    members: list[CombatantState] = []
    for member in save.team_state.members:
        if member.status != "active":
            continue
        role = role_map.get(member.role_id)
        if role is None:
            continue
        members.append(_combatant_from_role(save, role, source_kind="team", side="player_side"))
    return members


def _parse_ai_enemy_payloads(content: str) -> list[dict]:
    raw = _clean_json(content)
    rows = raw.get("enemies") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError("BATTLE_AI_ENEMIES_INVALID")
    payloads: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            payloads.append(row)
    if not payloads:
        raise ValueError("BATTLE_AI_ENEMIES_EMPTY")
    return payloads


def _generate_ai_enemies(save: SaveFile, req: BattleStartRequest) -> list[dict]:
    if not has_ai_config(req.config):
        return build_group_payloads(fallback_group_for_ai(req.ai_scale, req.ai_strength))
    battlefield = _current_battlefield(save)
    player = save.player_static_data
    team_names = [member.name for member in save.team_state.members if member.status == "active"]
    system_prompt = prompt_table.get_text("battle.debug.enemy_generate.system", "你是战斗测试怪物生成器，只输出 JSON。所有文本字段使用简体中文。")
    user_prompt = prompt_table.render(
        "battle.debug.enemy_generate.user",
        (
            "请根据以下战场信息生成测试敌人。"
            "只输出 JSON，结构必须为 "
            '{"enemies":[{"name":"","role_kind":"brute|skirmisher|ranged|support|beast","level_hint":1,"max_hp":12,"armor_class":11,"speed":6,"attack_bonus":3,'
            '"damage_profile":{"dice":"1d6","damage_type":"bludgeoning","flat_bonus":1},"ability_modifiers":{"strength":1,"dexterity":0,"constitution":1,"intelligence":0,"wisdom":0,"charisma":0},'
            '"saving_throw_bonuses":{"strength":1,"dexterity":0,"constitution":1,"intelligence":0,"wisdom":0,"charisma":0},"feature_tags":["aggressive"],"ai_style":"rush_target"}]}.'
            "战场大区块：$zone_name。战场子区块：$sub_zone_name。子区块描述：$sub_zone_description。区域危险值：$danger_score。区域名声值：$reputation_score。"
            "玩家：$player_name，等级：$player_level。队友：$team_names。生成规模：$ai_scale。强度档：$ai_strength。"
            "低危险更偏日常或轻冲突，高危险更偏凶狠压迫。"
        ),
        zone_name=battlefield.zone_name or "未知区域",
        sub_zone_name=battlefield.sub_zone_name or "未知子区块",
        sub_zone_description=battlefield.description or "无描述",
        danger_score=battlefield.danger_score if battlefield.danger_score is not None else 50,
        reputation_score=battlefield.reputation_score if battlefield.reputation_score is not None else 50,
        player_name=player.name,
        player_level=player.dnd5e_sheet.level,
        team_names="、".join(team_names) if team_names else "无",
        ai_scale=req.ai_scale,
        ai_strength=req.ai_strength,
    )
    client = create_sync_client(req.config)
    options = build_completion_options(req.config)
    try:
        response = client.chat.completions.create(
            model=req.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            **options,
        )
    except APIError:
        return build_group_payloads(fallback_group_for_ai(req.ai_scale, req.ai_strength))
    content = response.choices[0].message.content or "{}"
    try:
        return _parse_ai_enemy_payloads(content)
    except Exception:
        return build_group_payloads(fallback_group_for_ai(req.ai_scale, req.ai_strength))


def _roll_backend_initiative(combatant: CombatantState) -> None:
    combatant.initiative = random_d20() + int(combatant.initiative_bonus)


def random_d20() -> int:
    import random

    return random.randint(1, 20)


def _build_battle_state(save: SaveFile, req: BattleStartRequest, enemies: list[dict]) -> BattleSandboxState:
    player = _combatant_from_player(save, save.player_static_data)
    allies = _build_allies(save)
    enemy_states = [_enemy_from_payload(payload, index=index + 1) for index, payload in enumerate(enemies)]
    for ally in allies:
        _roll_backend_initiative(ally)
    for enemy in enemy_states:
        _roll_backend_initiative(enemy)
    combatants = [player, *allies, *enemy_states]
    battle = BattleSandboxState(
        battle_id=f"battle_{uuid4().hex}",
        session_id=req.session_id,
        status="setup",
        source_kind="debug_template" if req.mode == "template" else "debug_ai_generated",
        created_at=_utc_now(),
        updated_at=_utc_now(),
        battlefield=_current_battlefield(save),
        player_snapshot=player.model_copy(deep=True),
        ally_snapshots=[item.model_copy(deep=True) for item in allies],
        enemy_snapshots=[item.model_copy(deep=True) for item in enemy_states],
        combat_state=CombatState(round=1, phase="initiative", active_combatant_id=player.combatant_id, initiative_order=[], momentum_value=0, combatants=combatants),
    )
    battle.ui_flags.ai_pacing = req.ai_pacing  # type: ignore[assignment]
    initialize_player_initiative_prompt(battle)
    return battle


def _finalize_battle_logs(session_id: str, battle: BattleSandboxState) -> None:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    summary_message = (
        f"沙盒战斗结束：{battle.battlefield.sub_zone_name or battle.battlefield.zone_name} / "
        f"{battle.combat_state.winner_side or battle.status} / 回合 {battle.combat_state.round}"
    )
    save.game_logs.append(
        _new_game_log(
            session_id,
            "battle_sandbox",
            summary_message,
            {
                "sandbox": True,
                "debug": True,
                "rounds": battle.combat_state.round,
                "ended": True,
            },
        )
    )
    for step in battle.battle_logs[-80:]:
        save.game_logs.append(
            _new_game_log(
                session_id,
                "battle_sandbox_step",
                step.content,
                {
                    "sandbox": True,
                    "debug": True,
                    "round": step.round,
                    "battle_id": battle.battle_id,
                },
            )
        )
    save_current(save)


def start_debug_battle(req: BattleStartRequest) -> BattleStartResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    ensure_item_system(save)
    existing = load_current_battle(req.session_id)
    if existing is not None:
        clear_current_battle(req.session_id)
    if req.mode == "template":
        group_name = req.template_group or list_template_group_names()[0]
        enemies = build_group_payloads(group_name)
    else:
        enemies = _generate_ai_enemies(save, req)
    battle = _build_battle_state(save, req, enemies)
    save_current_battle(battle)
    return BattleStartResponse(session_id=req.session_id, battle=battle)


def get_current_debug_battle(session_id: str) -> BattleCurrentResponse:
    return BattleCurrentResponse(session_id=session_id, battle=load_current_battle(session_id))


def _require_battle(session_id: str, battle_id: str | None = None) -> BattleSandboxState:
    battle = load_current_battle(session_id)
    if battle is None:
        raise ValueError("BATTLE_NOT_FOUND")
    if battle_id and battle.battle_id != battle_id:
        raise ValueError("BATTLE_NOT_FOUND")
    return battle


def handle_player_battle_action(session_id: str, battle_id: str, *, action_kind: str, target_combatant_id: str | None, destination_band: str | None, item_id: str | None):
    battle = _require_battle(session_id, battle_id)
    battle = submit_player_action(
        battle,
        action_kind=action_kind,
        target_combatant_id=target_combatant_id,
        destination_band=destination_band,
        item_id=item_id,
    )
    if battle.status == "ended":
        _finalize_battle_logs(session_id, battle)
        clear_current_battle(session_id)
    else:
        save_current_battle(battle)
    return battle


def handle_continue_battle_ai(session_id: str, battle_id: str, *, ai_pacing: str | None):
    battle = _require_battle(session_id, battle_id)
    battle = continue_ai_turns(battle, ai_pacing=ai_pacing)
    if battle.status == "ended":
        _finalize_battle_logs(session_id, battle)
        clear_current_battle(session_id)
    else:
        save_current_battle(battle)
    return battle


def handle_resolve_battle_roll(session_id: str, battle_id: str, *, forced_dice_roll: int):
    battle = _require_battle(session_id, battle_id)
    result = resolve_pending_roll(battle, forced_dice_roll)
    if battle.status == "ended":
        _finalize_battle_logs(session_id, battle)
        clear_current_battle(session_id)
    else:
        save_current_battle(battle)
    return battle, result


def end_debug_battle(session_id: str, battle_id: str) -> BattleEndResponse:
    battle = _require_battle(session_id, battle_id)
    battle.status = "cancelled"
    battle.combat_state.phase = "ended"
    battle.combat_state.winner_side = "cancelled"
    _finalize_battle_logs(session_id, battle)
    clear_current_battle(session_id)
    return BattleEndResponse(session_id=session_id, battle_id=battle_id, ended=True)
