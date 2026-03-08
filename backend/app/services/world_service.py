from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import ceil, sqrt
import random
import re

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.storage import read_save_payload, storage_state, write_save_payload
from app.core.token_usage import token_usage_store
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    AreaCurrentResponse,
    AreaDiscoverInteractionsRequest,
    AreaDiscoverInteractionsResponse,
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResponse,
    AreaInteraction,
    AreaMovePoint,
    AreaMoveResult,
    AreaMoveSubZoneRequest,
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    BehaviorDescribeResponse,
    ChatConfig,
    Coord3D,
    GameLogAddRequest,
    GameLogEntry,
    GameLogListResponse,
    GameLogSettings,
    GameLogSettingsResponse,
    MapSnapshot,
    MoveRequest,
    MoveResponse,
    MovementLog,
    NpcRoleCard,
    NpcDialogueEntry,
    NpcConversationState,
    NpcChatRequest,
    NpcChatResponse,
    NpcGreetRequest,
    NpcGreetResponse,
    InventoryItem,
    InventoryOwnerRef,
    InventoryEquipRequest,
    InventoryUnequipRequest,
    InventoryMutationResponse,
    InventoryInteractRequest,
    InventoryInteractResponse,
    PlayerRuntimeData,
    PlayerBuffAddRequest,
    PlayerBuffRemoveRequest,
    PlayerEquipRequest,
    PlayerItemAddRequest,
    PlayerItemRemoveRequest,
    PlayerSkillSetRequest,
    PlayerSpellSetRequest,
    PlayerSpellSlotAdjustRequest,
    PlayerStaminaAdjustRequest,
    PlayerUnequipRequest,
    RoleRelationSetRequest,
    PlayerStaticData,
    Position,
    RegionGenerateRequest,
    RegionGenerateResponse,
    RolePoolListResponse,
    RoleRelation,
    RoleBuff,
    Dnd5eAbilityScores,
    Dnd5eAbilityModifiers,
    RenderMapRequest,
    RenderCircle,
    RenderMapResponse,
    RenderNode,
    RenderSubNode,
    SaveFile,
    SceneEvent,
    WorldClock,
    WorldClockInitRequest,
    WorldClockInitResponse,
    Zone,
    ZoneSubZoneSeed,
)
from app.services.consistency_service import (
    build_npc_knowledge_snapshot,
    bump_world_revision,
    ensure_world_state,
    npc_guard_reply,
    player_mentions_unknown_npc,
    reconcile_consistency,
)


class AIRegionGenerationError(RuntimeError):
    pass


class AIBehaviorError(RuntimeError):
    pass


_ACTION_PENALTY_RULES: dict[str, str] = {
    "attack": "hit_points.current",
    "check": "hit_points.current",
    "item_use": "hit_points.current",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_static() -> PlayerStaticData:
    data = PlayerStaticData()
    _recompute_player_derived(data)
    return data


def _default_runtime(session_id: str) -> PlayerRuntimeData:
    return PlayerRuntimeData(
        session_id=session_id,
        current_position=Position(x=0, y=0, z=0, zone_id="zone_0_0_0"),
        updated_at=_utc_now(),
    )


def _empty_save(session_id: str) -> SaveFile:
    return SaveFile(
        session_id=session_id,
        map_snapshot=MapSnapshot(),
        player_static_data=_default_static(),
        player_runtime_data=_default_runtime(session_id),
        updated_at=_utc_now(),
    )


def _new_game_log(session_id: str, kind: str, message: str, payload: dict[str, str | int | float | bool] | None = None) -> GameLogEntry:
    return GameLogEntry(
        id=f"glog_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        session_id=session_id,
        kind=kind,
        message=message,
        payload=payload or {},
    )


def _stable_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _ability_score_with_seed(seed: str, offset: int) -> int:
    base = 8 + ((_stable_int(f"{seed}:{offset}") % 11))
    return max(8, min(18, base))


def _ability_mod(score: int) -> int:
    return int((score - 10) // 2)


def _spell_slot_field(level: int) -> str:
    return f"level_{max(1, min(int(level), 9))}"


def _sum_buff_delta(buffs: list[RoleBuff], key: str) -> int:
    return sum(int(getattr(item.effect, key, 0) or 0) for item in buffs)


def _sanitize_sheet_lists(profile: PlayerStaticData) -> None:
    sheet = profile.dnd5e_sheet
    sheet.skills_proficient = sorted({s.strip() for s in sheet.skills_proficient if s.strip()})
    sheet.spells = sorted({s.strip() for s in sheet.spells if s.strip()})
    sheet.status_flags = sorted({s.strip() for s in sheet.status_flags if s.strip()})
    sheet.equipment = sorted({s.strip() for s in sheet.equipment if s.strip()})


def _ensure_equipped_item_exists(profile: PlayerStaticData) -> None:
    sheet = profile.dnd5e_sheet
    item_ids = {item.item_id for item in sheet.backpack.items}
    if sheet.equipment_slots.weapon_item_id and sheet.equipment_slots.weapon_item_id not in item_ids:
        sheet.equipment_slots.weapon_item_id = None
    if sheet.equipment_slots.armor_item_id and sheet.equipment_slots.armor_item_id not in item_ids:
        sheet.equipment_slots.armor_item_id = None


def _recompute_player_derived(profile: PlayerStaticData) -> None:
    sheet = profile.dnd5e_sheet
    _sanitize_sheet_lists(profile)
    _ensure_equipped_item_exists(profile)

    buffs = sheet.buffs
    base = sheet.ability_scores
    current = Dnd5eAbilityScores(
        strength=max(1, min(30, base.strength + _sum_buff_delta(buffs, "strength_delta"))),
        dexterity=max(1, min(30, base.dexterity + _sum_buff_delta(buffs, "dexterity_delta"))),
        constitution=max(1, min(30, base.constitution + _sum_buff_delta(buffs, "constitution_delta"))),
        intelligence=max(1, min(30, base.intelligence + _sum_buff_delta(buffs, "intelligence_delta"))),
        wisdom=max(1, min(30, base.wisdom + _sum_buff_delta(buffs, "wisdom_delta"))),
        charisma=max(1, min(30, base.charisma + _sum_buff_delta(buffs, "charisma_delta"))),
    )
    sheet.current_ability_scores = current

    base_mod = Dnd5eAbilityModifiers(
        strength=_ability_mod(base.strength),
        dexterity=_ability_mod(base.dexterity),
        constitution=_ability_mod(base.constitution),
        intelligence=_ability_mod(base.intelligence),
        wisdom=_ability_mod(base.wisdom),
        charisma=_ability_mod(base.charisma),
    )
    current_mod = Dnd5eAbilityModifiers(
        strength=_ability_mod(current.strength),
        dexterity=_ability_mod(current.dexterity),
        constitution=_ability_mod(current.constitution),
        intelligence=_ability_mod(current.intelligence),
        wisdom=_ability_mod(current.wisdom),
        charisma=_ability_mod(current.charisma),
    )
    sheet.ability_modifiers = base_mod
    sheet.current_ability_modifiers = current_mod

    equipped_weapon = next((i for i in sheet.backpack.items if i.item_id == sheet.equipment_slots.weapon_item_id), None)
    equipped_armor = next((i for i in sheet.backpack.items if i.item_id == sheet.equipment_slots.armor_item_id), None)
    weapon_attack_bonus = int(equipped_weapon.attack_bonus if equipped_weapon is not None else 0)
    armor_bonus = int(equipped_armor.armor_bonus if equipped_armor is not None else 0)
    buff_ac = _sum_buff_delta(buffs, "ac_delta")
    buff_dc = _sum_buff_delta(buffs, "dc_delta")
    use_dex = bool(equipped_weapon and equipped_weapon.slot_type == "weapon" and "dex" in equipped_weapon.effect.lower())
    attack_mod = current_mod.dexterity if use_dex else current_mod.strength
    sheet.armor_class = max(0, 10 + armor_bonus + current_mod.dexterity + buff_ac)
    sheet.difficulty_class = max(0, 8 + sheet.proficiency_bonus + attack_mod + weapon_attack_bonus + buff_dc)

    sheet.initiative_bonus = current_mod.dexterity

    hp = sheet.hit_points
    hp.current = max(0, min(hp.current, hp.maximum))

    sheet.stamina_current = max(0, min(sheet.stamina_current, sheet.stamina_maximum))
    sheet.is_dead = hp.current <= 0

    for level in range(1, 10):
        key = _spell_slot_field(level)
        max_val = max(0, int(getattr(sheet.spell_slots_max, key)))
        cur_val = max(0, int(getattr(sheet.spell_slots_current, key)))
        setattr(sheet.spell_slots_current, key, min(cur_val, max_val))


def _pick(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    return options[_stable_int(seed) % len(options)]


def _pick_many(seed: str, options: list[str], count: int) -> list[str]:
    unique = [item for item in dict.fromkeys(options) if item]
    if not unique or count <= 0:
        return []
    rng = random.Random(_stable_int(seed))
    if count >= len(unique):
        rng.shuffle(unique)
        return unique
    return rng.sample(unique, count)


def _make_npc_item(
    item_id: str,
    name: str,
    *,
    item_type: str,
    slot_type: str = "misc",
    description: str = "",
    rarity: str = "common",
    value: int = 0,
    effect: str = "",
    attack_bonus: int = 0,
    armor_bonus: int = 0,
) -> InventoryItem:
    return InventoryItem(
        item_id=item_id,
        name=name,
        item_type=item_type,
        slot_type=slot_type,  # type: ignore[arg-type]
        description=description,
        rarity=rarity,
        value=value,
        effect=effect,
        attack_bonus=attack_bonus,
        armor_bonus=armor_bonus,
    )


def _build_npc_likes(npc_id: str) -> list[str]:
    return _pick_many(
        f"{npc_id}:likes",
        [
            "热茶",
            "地方传闻",
            "罕见草药",
            "旧地图",
            "干净的武器",
            "准时赴约",
            "手工点心",
            "安静的夜晚",
            "可靠的同伴",
            "有趣的冒险故事",
        ],
        3,
    )


def _build_npc_flavor(npc_id: str, zone_name: str, sub_name: str, sub_desc: str) -> dict[str, str]:
    personality = _pick(
        f"{npc_id}:personality",
        ["谨慎", "豪爽", "机敏", "稳重", "多疑", "热心", "冷静", "直率", "寡言", "健谈"],
    )
    speaking_style = _pick(
        f"{npc_id}:speech",
        ["语速平缓，措辞克制", "说话简短直接", "喜欢举例说明", "习惯先试探再表态", "带有地方口音", "偶尔会先观察再开口"],
    )
    appearance = _pick(
        f"{npc_id}:appearance",
        ["披着旧斗篷", "佩戴铜制护符", "手上有旧伤疤", "衣着整洁但朴素", "背着工具包", "腰间挂着旧钥匙串"],
    )
    cognition = _pick(
        f"{npc_id}:cognition",
        ["重视秩序", "重视利益交换", "重视同伴承诺", "重视知识与传闻", "重视安全边界"],
    )
    alignment = _pick(
        f"{npc_id}:alignment",
        ["lawful_good", "neutral_good", "true_neutral", "chaotic_neutral", "lawful_neutral"],
    )
    background = f"常驻于【{zone_name}/{sub_name}】。{sub_desc[:42]}".strip()
    secret = _pick(
        f"{npc_id}:secret",
        [
            f"暗中记录【{zone_name}】来往旅人的消息",
            f"私下藏着一份关于【{sub_name}】的旧线索",
            "欠着某位旧识一笔没有还清的人情",
            "曾经参与过一次不愿再提起的失败护送",
            "手里握着一条只在必要时才会透露的情报",
        ],
    )
    return {
        "personality": personality,
        "speaking_style": speaking_style,
        "appearance": appearance,
        "background": background,
        "cognition": cognition,
        "alignment": alignment,
        "secret": secret,
    }


def _build_npc_identity(zone_name: str, sub_name: str, sub_id: str, idx: int = 0) -> tuple[str, str]:
    base_seed = f"{sub_id}:{idx}"
    title = _pick(base_seed + ":title", ["哨卫", "商贩", "学徒", "向导", "巡逻者", "抄写员", "药师", "工匠"])
    surname = _pick(base_seed + ":surname", ["林", "岳", "岚", "霁", "川", "墨", "澜", "宁", "祁", "商"])
    given = _pick(base_seed + ":given", ["安", "洛", "越", "岑", "遥", "珂", "骁", "弈", "乔", "白"])
    role_id = f"npc_{sub_id}_{(_stable_int(base_seed) % 9999):04d}"
    name = f"{zone_name}{title}{surname}{given}"
    return role_id, name


def _build_npc_talkative_maximum(npc_id: str, personality: str) -> int:
    base = 52 + (_stable_int(f"{npc_id}:talkative") % 32)
    if any(token in personality for token in ["健谈", "豪爽", "热心"]):
        base += 10
    if any(token in personality for token in ["寡言", "谨慎", "多疑"]):
        base -= 8
    return max(35, min(96, base))


def _class_template(char_class: str) -> dict[str, object]:
    templates: dict[str, dict[str, object]] = {
        "战士": {
            "saving_throws": ["strength", "constitution"],
            "skills": ["athletics", "intimidation"],
            "tools": ["护甲保养工具"],
            "features": ["第二风息", "战斗风格"],
            "weapon": ("长剑", "近战常用制式武器", "近战力量", 2),
            "armor": ("锁子甲", "常备护甲", 4),
            "extras": [("磨刀石", "misc"), ("水袋", "misc")],
            "spells": [],
            "spell_slots_level_1": 0,
            "hit_dice": "1d10",
        },
        "游荡者": {
            "saving_throws": ["dexterity", "intelligence"],
            "skills": ["stealth", "sleight_of_hand"],
            "tools": ["盗贼工具"],
            "features": ["偷袭", "巧妙动作"],
            "weapon": ("短剑", "轻巧的近战武器", "finesse dex", 2),
            "armor": ("皮甲", "方便行动的轻甲", 2),
            "extras": [("开锁器", "misc"), ("藏钱袋", "misc")],
            "spells": [],
            "spell_slots_level_1": 0,
            "hit_dice": "1d8",
        },
        "牧师": {
            "saving_throws": ["wisdom", "charisma"],
            "skills": ["insight", "medicine"],
            "tools": ["圣徽保养包"],
            "features": ["神圣感知", "祈祷仪式"],
            "weapon": ("钉头锤", "沉稳的单手武器", "近战力量", 1),
            "armor": ("鳞甲", "神职护甲", 3),
            "extras": [("圣徽", "misc"), ("香料包", "misc")],
            "spells": ["疗伤术", "祝福术", "神导术"],
            "spell_slots_level_1": 2,
            "hit_dice": "1d8",
        },
        "法师": {
            "saving_throws": ["intelligence", "wisdom"],
            "skills": ["arcana", "history"],
            "tools": ["抄写工具"],
            "features": ["奥术恢复", "法术书"],
            "weapon": ("法杖", "施法与自卫兼用", "spell focus", 1),
            "armor": ("法袍", "轻便衣袍", 0),
            "extras": [("法术书", "misc"), ("墨水套装", "misc")],
            "spells": ["魔法飞弹", "护盾术", "侦测魔法"],
            "spell_slots_level_1": 3,
            "hit_dice": "1d6",
        },
        "游侠": {
            "saving_throws": ["strength", "dexterity"],
            "skills": ["survival", "perception"],
            "tools": ["猎具维护包"],
            "features": ["偏好地形", "追踪者"],
            "weapon": ("短弓", "远程巡猎武器", "ranged dex", 2),
            "armor": ("皮甲", "轻便护甲", 2),
            "extras": [("箭袋", "misc"), ("干粮包", "misc")],
            "spells": ["猎人印记", "疗伤术"],
            "spell_slots_level_1": 2,
            "hit_dice": "1d10",
        },
        "吟游诗人": {
            "saving_throws": ["dexterity", "charisma"],
            "skills": ["persuasion", "performance"],
            "tools": ["乐器"],
            "features": ["诗人激励", "万事通"],
            "weapon": ("细剑", "便于在表演中携带", "finesse dex", 2),
            "armor": ("皮甲", "做工精致的轻甲", 1),
            "extras": [("鲁特琴", "misc"), ("记事册", "misc")],
            "spells": ["魅惑人类", "治疗真言", "塔莎狂笑术"],
            "spell_slots_level_1": 2,
            "hit_dice": "1d8",
        },
        "武僧": {
            "saving_throws": ["strength", "dexterity"],
            "skills": ["acrobatics", "insight"],
            "tools": ["草药工具"],
            "features": ["疾风连击", "气"],
            "weapon": ("短棍", "便于训练的武器", "monk dex", 1),
            "armor": ("练功服", "并非真正护甲", 0),
            "extras": [("绷带卷", "misc"), ("木珠手串", "misc")],
            "spells": [],
            "spell_slots_level_1": 0,
            "hit_dice": "1d8",
        },
        "德鲁伊": {
            "saving_throws": ["intelligence", "wisdom"],
            "skills": ["nature", "animal_handling"],
            "tools": ["草药包"],
            "features": ["自然感知", "野性变身见闻"],
            "weapon": ("木杖", "沾着草药气味的手杖", "spell focus", 1),
            "armor": ("皮甲", "缝着叶片的轻甲", 1),
            "extras": [("草药袋", "misc"), ("种子囊", "misc")],
            "spells": ["纠缠术", "疗伤术", "造水术"],
            "spell_slots_level_1": 2,
            "hit_dice": "1d8",
        },
    }
    return templates.get(char_class, templates["战士"])


def _build_npc_profile(npc_id: str, npc_name: str) -> PlayerStaticData:
    strength = _ability_score_with_seed(npc_id, 1)
    dexterity = _ability_score_with_seed(npc_id, 2)
    constitution = _ability_score_with_seed(npc_id, 3)
    intelligence = _ability_score_with_seed(npc_id, 4)
    wisdom = _ability_score_with_seed(npc_id, 5)
    charisma = _ability_score_with_seed(npc_id, 6)
    level = 1 + (_stable_int(f"{npc_id}:lvl") % 5)
    race = _pick(
        f"{npc_id}:race",
        ["人类", "精灵", "矮人", "半身人", "半精灵", "侏儒", "提夫林"],
    )
    char_class = _pick(
        f"{npc_id}:class",
        ["战士", "游荡者", "牧师", "法师", "游侠", "吟游诗人", "武僧", "德鲁伊"],
    )
    sheet_background = _pick(
        f"{npc_id}:sheet_background",
        ["城镇守望", "行会学徒", "旅商随员", "边境猎手", "神殿侍者", "抄写员", "草药采集者", "佣兵"],
    )
    alignment = _pick(
        f"{npc_id}:sheet_alignment",
        ["lawful_good", "neutral_good", "true_neutral", "chaotic_neutral", "lawful_neutral"],
    )
    template = _class_template(char_class)
    con_mod = _ability_mod(constitution)
    hit_dice = str(template.get("hit_dice") or "1d8")
    hit_die_size = int(hit_dice.split("d", 1)[1]) if "d" in hit_dice else 8
    hp_max = max(4, hit_die_size + con_mod + max(level - 1, 0) * (max(4, hit_die_size // 2 + 1) + con_mod))
    proficiency = 2 + ((level - 1) // 4)
    speed_ft = 35 if race in {"半精灵"} else 30
    move_speed_mph = max(3200, speed_ft * 140)
    initiative_bonus = _ability_mod(dexterity)
    weapon_name, weapon_desc, weapon_effect, weapon_bonus = template["weapon"]  # type: ignore[index]
    armor_name, armor_desc, armor_bonus = template["armor"]  # type: ignore[index]
    weapon_item = _make_npc_item(
        f"{npc_id}_weapon",
        str(weapon_name),
        item_type="weapon",
        slot_type="weapon",
        description=str(weapon_desc),
        effect=str(weapon_effect),
        attack_bonus=int(weapon_bonus),
        value=10 + level * 3,
    )
    armor_item = _make_npc_item(
        f"{npc_id}_armor",
        str(armor_name),
        item_type="armor",
        slot_type="armor",
        description=str(armor_desc),
        armor_bonus=int(armor_bonus),
        value=12 + level * 3,
    )
    extra_items = [
        _make_npc_item(
            f"{npc_id}_extra_{idx}",
            str(name),
            item_type=str(item_type),
            description=f"{npc_name} 随身携带的物品。",
            value=3 + idx * 2,
        )
        for idx, (name, item_type) in enumerate(template["extras"], start=1)  # type: ignore[index]
    ]
    all_items = [weapon_item, armor_item, *extra_items]
    spell_list = list(template.get("spells") or [])
    first_level_slots = int(template.get("spell_slots_level_1") or 0)
    armor_class = 10 + int(armor_bonus) + _ability_mod(dexterity)

    profile = PlayerStaticData(
        player_id=npc_id,
        name=npc_name,
        move_speed_mph=move_speed_mph,
        role_type="npc",
        dnd5e_sheet={
            "level": level,
            "race": race,
            "char_class": char_class,
            "background": sheet_background,
            "alignment": alignment,
            "proficiency_bonus": proficiency,
            "armor_class": armor_class,
            "speed_ft": speed_ft,
            "initiative_bonus": initiative_bonus,
            "hit_dice": hit_dice,
            "hit_points": {"current": hp_max, "maximum": hp_max, "temporary": 0},
            "ability_scores": {
                "strength": strength,
                "dexterity": dexterity,
                "constitution": constitution,
                "intelligence": intelligence,
                "wisdom": wisdom,
                "charisma": charisma,
            },
            "saving_throws_proficient": list(template.get("saving_throws") or []),
            "skills_proficient": list(template.get("skills") or []),
            "languages": ["通用语", *_pick_many(f"{npc_id}:languages", ["矮人语", "精灵语", "半身人语", "行商黑话"], 1)],
            "tool_proficiencies": list(template.get("tools") or []),
            "equipment": [item.name for item in all_items],
            "equipment_slots": {
                "weapon_item_id": weapon_item.item_id,
                "armor_item_id": armor_item.item_id,
            },
            "backpack": {
                "gold": 8 + (_stable_int(f"{npc_id}:gold") % 37),
                "items": [item.model_dump(mode="json") for item in all_items],
            },
            "features_traits": list(template.get("features") or []),
            "spells": spell_list,
            "spell_slots_max": {
                "level_1": first_level_slots,
                "level_2": 0,
                "level_3": 0,
                "level_4": 0,
                "level_5": 0,
                "level_6": 0,
                "level_7": 0,
                "level_8": 0,
                "level_9": 0,
            },
            "spell_slots_current": {
                "level_1": first_level_slots,
                "level_2": 0,
                "level_3": 0,
                "level_4": 0,
                "level_5": 0,
                "level_6": 0,
                "level_7": 0,
                "level_8": 0,
                "level_9": 0,
            },
            "notes": f"常驻NPC模板：{sheet_background}，职业倾向为{char_class}。",
        },
    )
    _recompute_player_derived(profile)
    return profile


def _spell_slots_total(sheet) -> int:
    return sum(int(getattr(sheet, _spell_slot_field(level))) for level in range(1, 10))


def _ensure_npc_role_complete(save: SaveFile, role: NpcRoleCard) -> bool:
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == role.zone_id), role.zone_id or "当前区域")
    sub = next((item for item in save.area_snapshot.sub_zones if item.sub_zone_id == role.sub_zone_id), None)
    sub_name = sub.name if sub is not None else (role.sub_zone_id or "附近")
    sub_desc = sub.description if sub is not None else ""
    flavor = _build_npc_flavor(role.role_id, zone_name, sub_name, sub_desc)
    profile_template = _build_npc_profile(role.role_id, role.name)
    changed = False

    for field in ("personality", "speaking_style", "appearance", "background", "cognition", "alignment", "secret"):
        if not getattr(role, field, ""):
            setattr(role, field, flavor[field])
            changed = True
    if not role.likes:
        role.likes = _build_npc_likes(role.role_id)
        changed = True
    if getattr(role, "conversation_state", None) is None:
        role.conversation_state = NpcConversationState()
        changed = True

    target_talkative_max = _build_npc_talkative_maximum(role.role_id, role.personality)
    if role.talkative_maximum <= 0 or (role.talkative_maximum == 100 and not role.dialogue_logs):
        role.talkative_maximum = target_talkative_max
        changed = True
    if role.talkative_current > role.talkative_maximum:
        role.talkative_current = role.talkative_maximum
        changed = True
    if role.talkative_current < 0:
        role.talkative_current = 0
        changed = True

    profile = role.profile
    template = profile_template
    template_sheet = template.dnd5e_sheet
    sheet = profile.dnd5e_sheet

    if profile.player_id != role.role_id:
        profile.player_id = role.role_id
        changed = True
    if profile.name != role.name:
        profile.name = role.name
        changed = True
    if profile.role_type != "npc":
        profile.role_type = "npc"
        changed = True
    if profile.move_speed_mph <= 0:
        profile.move_speed_mph = template.move_speed_mph
        changed = True

    for field in ("race", "char_class", "background", "alignment", "hit_dice", "notes"):
        if not getattr(sheet, field, ""):
            setattr(sheet, field, getattr(template_sheet, field))
            changed = True
    if sheet.proficiency_bonus <= 0:
        sheet.proficiency_bonus = template_sheet.proficiency_bonus
        changed = True
    if sheet.speed_ft <= 0:
        sheet.speed_ft = template_sheet.speed_ft
        changed = True
    if sheet.hit_points.maximum <= 0:
        sheet.hit_points.maximum = template_sheet.hit_points.maximum
        sheet.hit_points.current = template_sheet.hit_points.current
        changed = True
    if not sheet.saving_throws_proficient:
        sheet.saving_throws_proficient = list(template_sheet.saving_throws_proficient)
        changed = True
    if not sheet.skills_proficient:
        sheet.skills_proficient = list(template_sheet.skills_proficient)
        changed = True
    if not sheet.languages:
        sheet.languages = list(template_sheet.languages)
        changed = True
    if not sheet.tool_proficiencies:
        sheet.tool_proficiencies = list(template_sheet.tool_proficiencies)
        changed = True
    if not sheet.features_traits:
        sheet.features_traits = list(template_sheet.features_traits)
        changed = True
    if not sheet.backpack.items:
        sheet.backpack = template_sheet.backpack.model_copy(deep=True)
        changed = True
    elif sheet.backpack.gold == 0 and template_sheet.backpack.gold > 0:
        sheet.backpack.gold = template_sheet.backpack.gold
        changed = True
    if not sheet.equipment:
        sheet.equipment = list(template_sheet.equipment)
        changed = True
    if sheet.equipment_slots.weapon_item_id is None and template_sheet.equipment_slots.weapon_item_id is not None:
        sheet.equipment_slots.weapon_item_id = template_sheet.equipment_slots.weapon_item_id
        changed = True
    if sheet.equipment_slots.armor_item_id is None and template_sheet.equipment_slots.armor_item_id is not None:
        sheet.equipment_slots.armor_item_id = template_sheet.equipment_slots.armor_item_id
        changed = True
    if not sheet.spells and template_sheet.spells:
        sheet.spells = list(template_sheet.spells)
        changed = True
    if (_spell_slots_total(sheet.spell_slots_max) == 2 and not sheet.spells and template_sheet.spells) or _spell_slots_total(sheet.spell_slots_max) == 0:
        if _spell_slots_total(template_sheet.spell_slots_max) >= 0:
            sheet.spell_slots_max = template_sheet.spell_slots_max.model_copy(deep=True)
            sheet.spell_slots_current = template_sheet.spell_slots_current.model_copy(deep=True)
            changed = True
    if not sheet.spells and _spell_slots_total(sheet.spell_slots_max) > 0:
        sheet.spell_slots_max = template_sheet.spell_slots_max.model_copy(deep=True)
        sheet.spell_slots_current = template_sheet.spell_slots_current.model_copy(deep=True)
        changed = True

    _recompute_player_derived(profile)
    return changed


def _ensure_role_pool_from_area(save: SaveFile) -> bool:
    changed = False
    world_state = ensure_world_state(save)
    role_map = {r.role_id: r for r in save.role_pool}

    for sub in save.area_snapshot.sub_zones:
        if not sub.npcs:
            zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == sub.zone_id), sub.zone_id)
            npc_id, npc_name = _build_npc_identity(zone_name, sub.name, sub.sub_zone_id, 0)
            sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
            changed = True

        for npc in sub.npcs:
            role = role_map.get(npc.npc_id)
            if role is None:
                zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == sub.zone_id), sub.zone_id)
                flavor = _build_npc_flavor(npc.npc_id, zone_name, sub.name, sub.description)
                role = NpcRoleCard(
                    role_id=npc.npc_id,
                    name=npc.name,
                    zone_id=sub.zone_id,
                    sub_zone_id=sub.sub_zone_id,
                    source_world_revision=world_state.world_revision,
                    source_map_revision=world_state.map_revision,
                    state=npc.state or "idle",
                    personality=flavor["personality"],
                    speaking_style=flavor["speaking_style"],
                    appearance=flavor["appearance"],
                    background=flavor["background"],
                    cognition=flavor["cognition"],
                    alignment=flavor["alignment"],
                    secret=flavor["secret"],
                    likes=_build_npc_likes(npc.npc_id),
                    talkative_maximum=_build_npc_talkative_maximum(npc.npc_id, flavor["personality"]),
                    talkative_current=_build_npc_talkative_maximum(npc.npc_id, flavor["personality"]),
                    profile=_build_npc_profile(npc.npc_id, npc.name),
                    relations=[],
                )
                _ensure_npc_role_complete(save, role)
                save.role_pool.append(role)
                role_map[role.role_id] = role
                changed = True
            else:
                if role.name != npc.name:
                    role.name = npc.name
                    changed = True
                if role.zone_id != sub.zone_id:
                    role.zone_id = sub.zone_id
                    changed = True
                if role.sub_zone_id != sub.sub_zone_id:
                    role.sub_zone_id = sub.sub_zone_id
                    changed = True
                if role.source_world_revision != world_state.world_revision:
                    role.source_world_revision = world_state.world_revision
                    changed = True
                if role.source_map_revision != world_state.map_revision:
                    role.source_map_revision = world_state.map_revision
                    changed = True
                if role.state != (npc.state or "idle"):
                    role.state = npc.state or "idle"
                    changed = True
                if _ensure_npc_role_complete(save, role):
                    changed = True

    role_ids = [r.role_id for r in save.role_pool]
    for idx, role in enumerate(save.role_pool):
        if role.relations:
            continue
        if len(role_ids) <= 1:
            continue
        first_target = role_ids[(idx + 1) % len(role_ids)]
        if first_target == role.role_id:
            continue
        relations = [RoleRelation(target_role_id=first_target, relation_tag="acquaintance", note="初始关联")]
        if len(role_ids) > 2 and idx % 2 == 0:
            second_target = role_ids[(idx + 2) % len(role_ids)]
            if second_target != role.role_id and second_target != first_target:
                relations.append(RoleRelation(target_role_id=second_target, relation_tag="ally", note="初始关联"))
        role.relations = relations[:2]
        changed = True

    return changed


def get_current_save(default_session_id: str = "sess_default") -> SaveFile:
    payload = read_save_payload(storage_state.save_path)
    if payload is None:
        save = _empty_save(default_session_id)
        ensure_world_state(save)
        save_current(save)
        return save

    save = SaveFile.model_validate(payload)
    ensure_world_state(save)
    if not save.player_runtime_data.session_id:
        save.player_runtime_data.session_id = save.session_id
    _recompute_player_derived(save.player_static_data)
    changed = False
    for role in save.role_pool:
        _recompute_player_derived(role.profile)
        if _ensure_npc_role_complete(save, role):
            changed = True
    if _ensure_role_pool_from_area(save):
        changed = True
    _, reconciled = reconcile_consistency(save, session_id=save.session_id or default_session_id, reason="load")
    if changed or reconciled:
        save_current(save)
    return save


def save_current(save: SaveFile) -> None:
    ensure_world_state(save)
    save.updated_at = _utc_now()
    save.player_runtime_data.updated_at = save.updated_at
    write_save_payload(storage_state.save_path, save.model_dump(mode="json"))


def clear_current_save(session_id: str) -> SaveFile:
    save = _empty_save(session_id)
    save_current(save)
    return save


def import_save(save: SaveFile) -> SaveFile:
    save_current(save)
    return save


def get_player_static(session_id: str) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def set_player_static(session_id: str, payload: PlayerStaticData) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.player_static_data = payload
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def get_player_runtime(session_id: str) -> PlayerRuntimeData:
    save = get_current_save(default_session_id=session_id)
    if save.player_runtime_data.session_id != session_id:
        save.player_runtime_data.session_id = session_id
        save_current(save)
    return save.player_runtime_data


def set_player_runtime(session_id: str, payload: PlayerRuntimeData) -> PlayerRuntimeData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    payload.session_id = session_id
    payload.updated_at = _utc_now()
    save.player_runtime_data = payload
    save_current(save)
    return save.player_runtime_data


def _get_player_item(profile: PlayerStaticData, item_id: str):
    return next((item for item in profile.dnd5e_sheet.backpack.items if item.item_id == item_id), None)


def _resolve_inventory_owner(save: SaveFile, owner: InventoryOwnerRef) -> tuple[str, str, PlayerStaticData, NpcRoleCard | None]:
    if owner.owner_type == "player":
        return save.player_static_data.player_id, save.player_static_data.name, save.player_static_data, None
    role = next((item for item in save.role_pool if item.role_id == owner.role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    _ensure_npc_role_complete(save, role)
    return role.role_id, role.name, role.profile, role


def _get_inventory_item_for_owner(profile: PlayerStaticData, item_id: str) -> InventoryItem:
    item = next((entry for entry in profile.dnd5e_sheet.backpack.items if entry.item_id == item_id), None)
    if item is None:
        raise KeyError("ITEM_NOT_FOUND")
    return item


def _equip_profile_item(profile: PlayerStaticData, item_id: str, slot: str) -> InventoryItem:
    item = _get_inventory_item_for_owner(profile, item_id)
    if slot == "weapon" and item.slot_type != "weapon":
        raise ValueError("ITEM_SLOT_MISMATCH")
    if slot == "armor" and item.slot_type != "armor":
        raise ValueError("ITEM_SLOT_MISMATCH")
    if slot == "weapon":
        profile.dnd5e_sheet.equipment_slots.weapon_item_id = item.item_id
    else:
        profile.dnd5e_sheet.equipment_slots.armor_item_id = item.item_id
    return item


def _unequip_profile_item(profile: PlayerStaticData, slot: str) -> str | None:
    if slot == "weapon":
        equipped_id = profile.dnd5e_sheet.equipment_slots.weapon_item_id
        profile.dnd5e_sheet.equipment_slots.weapon_item_id = None
        return equipped_id
    equipped_id = profile.dnd5e_sheet.equipment_slots.armor_item_id
    profile.dnd5e_sheet.equipment_slots.armor_item_id = None
    return equipped_id


def _build_item_interaction_prompt(
    owner_type: str,
    owner_name: str,
    item: InventoryItem,
    mode: str,
    prompt: str,
    action_check_result: ActionCheckResponse | None = None,
) -> str:
    lines = [
        "You narrate one short RPG inventory interaction in Chinese.",
        f"OwnerType={owner_type}",
        f"OwnerName={owner_name}",
        f"Mode={mode}",
        f"ItemName={item.name}",
        f"ItemType={item.item_type}",
        f"ItemDescription={item.description or '-'}",
        f"ItemEffect={item.effect or '-'}",
        f"PlayerPrompt={prompt or '-'}",
    ]
    if action_check_result is not None:
        lines.extend(
            [
                f"ActionSuccess={action_check_result.success}",
                f"ActionCritical={action_check_result.critical}",
                f"ActionNarrative={action_check_result.narrative}",
            ]
        )
    lines.append("Keep it concise, grounded in current gameplay, and do not invent unrelated entities.")
    return "\n".join(lines)


def _fallback_inventory_interaction_reply(
    owner_name: str,
    item: InventoryItem,
    mode: str,
    prompt: str,
    action_check_result: ActionCheckResponse | None = None,
) -> str:
    clean_prompt = prompt.strip()
    if mode == "inspect":
        focus = f" 你特别留意了：{clean_prompt}。" if clean_prompt else ""
        effect = f" 你能感觉到它与“{item.effect}”有关。" if item.effect else ""
        desc = item.description or "这件物品没有更多外观说明，但保存状况还算稳定。"
        return f"{owner_name}仔细观察【{item.name}】。{desc}{effect}{focus}"
    if action_check_result is None:
        return f"{owner_name}尝试使用【{item.name}】。"
    outcome = "顺利发挥了作用" if action_check_result.success else "没能稳定发挥作用"
    effect = item.effect or "它原本的用途"
    focus = f" 你的意图是：{clean_prompt}。" if clean_prompt else ""
    return f"{action_check_result.narrative}\n{owner_name}使用【{item.name}】时，{effect}{outcome}。{focus}"


def _generate_inventory_interaction_reply(
    session_id: str,
    config: ChatConfig | None,
    owner_type: str,
    owner_name: str,
    item: InventoryItem,
    mode: str,
    prompt: str,
    action_check_result: ActionCheckResponse | None = None,
) -> str:
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": "Return plain Chinese text only."},
                        {
                            "role": "user",
                            "content": _build_item_interaction_prompt(owner_type, owner_name, item, mode, prompt, action_check_result),
                        },
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    usage = getattr(resp, "usage", None)
                    if usage is not None:
                        token_usage_store.add(
                            session_id,
                            "chat",
                            int(getattr(usage, "prompt_tokens", 0) or 0),
                            int(getattr(usage, "completion_tokens", 0) or 0),
                        )
                    return content
            except Exception:
                pass
    return _fallback_inventory_interaction_reply(owner_name, item, mode, prompt, action_check_result)


def inventory_equip(payload: InventoryEquipRequest) -> InventoryMutationResponse:
    save = get_current_save(default_session_id=payload.session_id)
    save.session_id = payload.session_id
    owner_id, owner_name, profile, role = _resolve_inventory_owner(save, payload.owner)
    item = _equip_profile_item(profile, payload.item_id, payload.slot)
    _recompute_player_derived(profile)
    if role is not None:
        role.profile = profile
    save_current(save)
    return InventoryMutationResponse(
        session_id=payload.session_id,
        owner=payload.owner,
        message=f"{owner_name} 装备了【{item.name}】。",
        player=profile if payload.owner.owner_type == "player" else None,
        role=role,
    )


def inventory_unequip(payload: InventoryUnequipRequest) -> InventoryMutationResponse:
    save = get_current_save(default_session_id=payload.session_id)
    save.session_id = payload.session_id
    owner_id, owner_name, profile, role = _resolve_inventory_owner(save, payload.owner)
    equipped_id = _unequip_profile_item(profile, payload.slot)
    equipped_name = None
    if equipped_id:
        equipped_name = next((item.name for item in profile.dnd5e_sheet.backpack.items if item.item_id == equipped_id), None)
    _recompute_player_derived(profile)
    if role is not None:
        role.profile = profile
    save_current(save)
    slot_label = "武器" if payload.slot == "weapon" else "护甲"
    return InventoryMutationResponse(
        session_id=payload.session_id,
        owner=payload.owner,
        message=f"{owner_name} 卸下了{slot_label}{f'【{equipped_name}】' if equipped_name else ''}。",
        player=profile if payload.owner.owner_type == "player" else None,
        role=role,
    )


def inventory_interact(payload: InventoryInteractRequest) -> InventoryInteractResponse:
    save = get_current_save(default_session_id=payload.session_id)
    save.session_id = payload.session_id
    owner_id, owner_name, profile, role = _resolve_inventory_owner(save, payload.owner)
    item = _get_inventory_item_for_owner(profile, payload.item_id)
    action_result: ActionCheckResponse | None = None
    time_spent_min = 1
    scene_events: list[SceneEvent] = []

    if payload.mode == "use":
        if item.slot_type != "misc":
            raise ValueError("ITEM_USE_UNSUPPORTED_SLOT")
        if item.uses_left is not None and item.uses_left <= 0:
            raise ValueError("ITEM_DEPLETED")
        action_result = action_check(
            ActionCheckRequest(
                session_id=payload.session_id,
                action_type="item_use",
                action_prompt=(
                    f"owner_type={payload.owner.owner_type}; role_id={owner_id}; "
                    f"item_id={item.item_id}; item_name={item.name}; prompt={payload.prompt.strip() or '-'}"
                ),
                actor_role_id=owner_id,
                config=payload.config,
            )
        )
        time_spent_min = max(1, action_result.time_spent_min)
        save = get_current_save(default_session_id=payload.session_id)
        save.session_id = payload.session_id
        owner_id, owner_name, profile, role = _resolve_inventory_owner(save, payload.owner)
        item = _get_inventory_item_for_owner(profile, payload.item_id)
        if action_result.success and item.uses_left is not None:
            item.uses_left = max(0, item.uses_left - 1)
    reply = _generate_inventory_interaction_reply(
        payload.session_id,
        payload.config,
        payload.owner.owner_type,
        owner_name,
        item,
        payload.mode,
        payload.prompt,
        action_result,
    )
    save.game_logs.append(
        _new_game_log(
            payload.session_id,
            "inventory_interact",
            f"{owner_name} 对【{item.name}】执行了{payload.mode}。",
            {
                "owner_type": payload.owner.owner_type,
                "owner_id": owner_id,
                "item_id": item.item_id,
                "mode": payload.mode,
                "time_spent_min": time_spent_min,
            },
        )
    )
    if payload.owner.owner_type == "player":
        scene_events = advance_public_scene_in_save(
            save,
            payload.session_id,
            f"{payload.mode}:{item.name}; {payload.prompt.strip()}".strip(),
            reply,
            payload.config,
        )
        summary = _scene_events_to_summary(scene_events)
        if summary:
            reply = f"{reply}\n\n{summary}"
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advanced = advance_active_encounter_in_save(save, session_id=payload.session_id, minutes_elapsed=time_spent_min, config=payload.config)
        if advanced is not None:
            scene_events.append(
                _new_scene_event(
                    "encounter_background",
                    advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                    metadata={"encounter_id": advanced.encounter_id},
                )
            )
    except Exception:
        pass
    _recompute_player_derived(profile)
    if role is not None:
        role.profile = profile
    save_current(save)
    return InventoryInteractResponse(
        session_id=payload.session_id,
        owner=payload.owner,
        item_id=item.item_id,
        mode=payload.mode,
        reply=reply,
        time_spent_min=time_spent_min,
        action_check=action_result,
        player=profile if payload.owner.owner_type == "player" else None,
        role=role,
        scene_events=scene_events,
    )


def equip_player_item(session_id: str, payload: PlayerEquipRequest) -> PlayerStaticData:
    response = inventory_equip(
        InventoryEquipRequest(
            session_id=session_id,
            owner=InventoryOwnerRef(owner_type="player"),
            item_id=payload.item_id,
            slot=payload.slot,
        )
    )
    return response.player or get_player_static(session_id)


def unequip_player_item(session_id: str, payload: PlayerUnequipRequest) -> PlayerStaticData:
    response = inventory_unequip(
        InventoryUnequipRequest(
            session_id=session_id,
            owner=InventoryOwnerRef(owner_type="player"),
            slot=payload.slot,
        )
    )
    return response.player or get_player_static(session_id)


def add_player_buff(session_id: str, payload: PlayerBuffAddRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    buffs = [b for b in save.player_static_data.dnd5e_sheet.buffs if b.buff_id != payload.buff.buff_id]
    buffs.append(payload.buff)
    save.player_static_data.dnd5e_sheet.buffs = buffs
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def remove_player_buff(session_id: str, payload: PlayerBuffRemoveRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.player_static_data.dnd5e_sheet.buffs = [
        b for b in save.player_static_data.dnd5e_sheet.buffs if b.buff_id != payload.buff_id
    ]
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def add_player_item(session_id: str, payload: PlayerItemAddRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    items = save.player_static_data.dnd5e_sheet.backpack.items
    existing = next((it for it in items if it.item_id == payload.item.item_id), None)
    if existing is not None:
        existing.quantity += payload.item.quantity
    else:
        items.append(payload.item)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def remove_player_item(session_id: str, payload: PlayerItemRemoveRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    items = save.player_static_data.dnd5e_sheet.backpack.items
    found = next((it for it in items if it.item_id == payload.item_id), None)
    if found is None:
        raise KeyError("ITEM_NOT_FOUND")
    found.quantity -= payload.quantity
    if found.quantity <= 0:
        save.player_static_data.dnd5e_sheet.backpack.items = [it for it in items if it.item_id != payload.item_id]
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def add_player_spell(session_id: str, payload: PlayerSpellSetRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.player_static_data.dnd5e_sheet.spells.append(payload.value)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def remove_player_spell(session_id: str, payload: PlayerSpellSetRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    value = payload.value.strip().lower()
    save.player_static_data.dnd5e_sheet.spells = [
        s for s in save.player_static_data.dnd5e_sheet.spells if s.strip().lower() != value
    ]
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def add_player_skill(session_id: str, payload: PlayerSkillSetRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.player_static_data.dnd5e_sheet.skills_proficient.append(payload.value)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def remove_player_skill(session_id: str, payload: PlayerSkillSetRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    value = payload.value.strip().lower()
    save.player_static_data.dnd5e_sheet.skills_proficient = [
        s for s in save.player_static_data.dnd5e_sheet.skills_proficient if s.strip().lower() != value
    ]
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def consume_spell_slots(session_id: str, payload: PlayerSpellSlotAdjustRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    sheet = save.player_static_data.dnd5e_sheet
    key = _spell_slot_field(payload.level)
    cur = int(getattr(sheet.spell_slots_current, key))
    if cur < payload.amount:
        raise ValueError("SPELL_SLOT_NOT_ENOUGH")
    setattr(sheet.spell_slots_current, key, cur - payload.amount)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def recover_spell_slots(session_id: str, payload: PlayerSpellSlotAdjustRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    sheet = save.player_static_data.dnd5e_sheet
    key = _spell_slot_field(payload.level)
    cur = int(getattr(sheet.spell_slots_current, key))
    max_val = int(getattr(sheet.spell_slots_max, key))
    setattr(sheet.spell_slots_current, key, min(max_val, cur + payload.amount))
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def consume_stamina(session_id: str, payload: PlayerStaminaAdjustRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    sheet = save.player_static_data.dnd5e_sheet
    if sheet.stamina_current < payload.amount:
        raise ValueError("STAMINA_NOT_ENOUGH")
    sheet.stamina_current -= payload.amount
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def recover_stamina(session_id: str, payload: PlayerStaminaAdjustRequest) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    sheet = save.player_static_data.dnd5e_sheet
    sheet.stamina_current = min(sheet.stamina_maximum, sheet.stamina_current + payload.amount)
    _recompute_player_derived(save.player_static_data)
    save_current(save)
    return save.player_static_data


def add_game_log(req: GameLogAddRequest) -> GameLogEntry:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    entry = _new_game_log(req.session_id, req.kind, req.message, req.payload)
    save.game_logs.append(entry)
    save_current(save)
    return entry


def get_game_logs(session_id: str, limit: int | None = None) -> GameLogListResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    safe_limit = max(1, min(limit if limit is not None else save.game_log_settings.ai_fetch_limit, 200))
    return GameLogListResponse(session_id=session_id, items=save.game_logs[-safe_limit:])


def get_game_log_settings(session_id: str) -> GameLogSettingsResponse:
    save = get_current_save(default_session_id=session_id)
    return GameLogSettingsResponse(session_id=session_id, settings=save.game_log_settings)


def set_game_log_settings(session_id: str, settings: GameLogSettings) -> GameLogSettingsResponse:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.game_log_settings = settings
    save_current(save)
    return GameLogSettingsResponse(session_id=session_id, settings=save.game_log_settings)


def _build_region_prompt(center: Position, count: int, world_prompt: str) -> str:
    default_prompt = (
        "根据以下世界设定，生成可探索地图区块。"
        "必须返回严格 JSON，且只返回 JSON。"
        "结构如下："
        "{\"zones\":[{\"name\":\"\",\"zone_type\":\"city|village|forest|mountain|river|desert|coast|cave|ruins|unknown\",\"size\":\"small|medium|large\",\"radius_m\":120,\"x\":0,\"y\":0,\"description\":\"\",\"tags\":[\"\"],\"sub_zones\":[{\"name\":\"\",\"offset_x\":0,\"offset_y\":0,\"offset_z\":0,\"description\":\"\"}]}]}。"
        f"区块数量={count}，玩家当前位置=({center.x},{center.y},{center.z})。"
        "x,y 单位是米。为了可视化，请将坐标限制在玩家中心点半径 300 米内。"
        "至少 1 个区块与玩家当前位置相邻（可在 0-80 米内）。"
        "返回的区块名称必须是语义名称，禁止使用‘区域1/区块1’这类流水号。"
        "子区块数量规则：small=3~5, medium=5~10, large=8~15。"
        "区块半径规则：small=60~180, medium=120~300, large=240~500。"
        "区块间不能重叠：任意两区块中心距离必须大于两者 radius_m 之和。"
        "sub_zones 的 offset_* 是相对区块中心坐标偏移（单位米）。"
        "世界设定提示：$world_prompt"
    )
    return prompt_table.render(
        "world.region.user",
        default_prompt,
        count=count,
        center_x=center.x,
        center_y=center.y,
        center_z=center.z,
        world_prompt=world_prompt,
    )


def _sub_zone_count_range(size: str) -> tuple[int, int]:
    if size == "small":
        return (3, 5)
    if size == "large":
        return (8, 15)
    return (5, 10)


def _zone_radius_range(size: str) -> tuple[int, int]:
    if size == "small":
        return (60, 180)
    if size == "large":
        return (240, 500)
    return (120, 300)


def _default_sub_zone_seeds(size: str, zone_name: str) -> list[ZoneSubZoneSeed]:
    min_count, _ = _sub_zone_count_range(size)
    rmin, rmax = _zone_radius_range(size)
    base_r = int((rmin + rmax) / 2)
    seeds: list[ZoneSubZoneSeed] = []
    for idx in range(min_count):
        angle_bucket = (idx % 6) + 1
        step = max(30, int(base_r * (0.35 + 0.1 * angle_bucket)))
        seeds.append(
            ZoneSubZoneSeed(
                name=f"{zone_name}子区{idx + 1}",
                offset_x=(step if idx % 2 == 0 else -step),
                offset_y=(step // 2 if idx % 3 == 0 else -step // 2),
                offset_z=0,
                description="自动补全的子区块",
            )
        )
    return seeds


def _fit_offset_in_radius(offset_x: int, offset_y: int, radius_m: int) -> tuple[int, int]:
    dist = sqrt(float(offset_x * offset_x + offset_y * offset_y))
    max_dist = max(1.0, float(radius_m))
    if dist <= max_dist:
        return offset_x, offset_y
    ratio = max_dist / dist
    return int(round(offset_x * ratio)), int(round(offset_y * ratio))


def _is_sub_seed_quality_bad(seeds: list[ZoneSubZoneSeed], radius_m: int) -> bool:
    if not seeds:
        return True
    center_threshold = max(8.0, float(radius_m) * 0.08)
    near_center = 0
    coords: set[tuple[int, int, int]] = set()
    for s in seeds:
        dist = sqrt(float(s.offset_x * s.offset_x + s.offset_y * s.offset_y + s.offset_z * s.offset_z))
        if dist <= center_threshold:
            near_center += 1
        coords.add((s.offset_x, s.offset_y, s.offset_z))
    if len(coords) <= 1:
        return True
    if near_center >= max(1, len(seeds) - 1):
        return True
    return False


def _enforce_non_overlap(zones: list[Zone]) -> None:
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            a = zones[i]
            b = zones[j]
            dx = float(b.x - a.x)
            dy = float(b.y - a.y)
            d = sqrt(dx * dx + dy * dy)
            min_d = float(a.radius_m + b.radius_m + 1)
            if d >= min_d:
                continue
            if d == 0:
                b.x += int(min_d)
                continue
            push = (min_d - d) / d
            b.x = int(round(b.x + dx * push))
            b.y = int(round(b.y + dy * push))


def _extract_json_content(content: str) -> dict:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _build_discover_prompt(sub_zone: AreaSubZone, intent: str) -> str:
    default_prompt = (
        "你是跑团场景设计器。"
        "请基于给定子区块和玩家意图，生成 1-3 个新的可交互对象。"
        "只能返回 JSON，不要输出任何额外文本。"
        "结构必须为："
        "{\"interactions\":[{\"name\":\"\",\"type\":\"item|scene|npc\",\"status\":\"ready|disabled|hidden\"}]}"
        "。子区块名称：$sub_zone_name。子区块描述：$sub_zone_description。玩家意图：$intent。"
        "要求：名称具体、可操作，不要与“观察周边”这类通用词重复。"
    )
    return prompt_table.render(
        "world.discover.user",
        default_prompt,
        sub_zone_name=sub_zone.name,
        sub_zone_description=sub_zone.description,
        intent=intent,
    )


def _coerce_interaction_type(raw: str) -> str:
    val = raw.strip().lower()
    if val in {"item", "scene", "npc"}:
        return val
    return "item"


def _coerce_interaction_status(raw: str) -> str:
    val = raw.strip().lower()
    if val in {"ready", "disabled", "hidden"}:
        return val
    return "ready"


def _validate_discovered_interactions(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise AIRegionGenerationError("discover_interactions: AI 返回格式无效")
    raw_list = payload.get("interactions")
    if not isinstance(raw_list, list):
        raise AIRegionGenerationError("discover_interactions: interactions 缺失")

    result: list[dict[str, str]] = []
    for item in raw_list[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        itype = _coerce_interaction_type(str(item.get("type") or "item"))
        status = _coerce_interaction_status(str(item.get("status") or "ready"))
        result.append({"name": name, "type": itype, "status": status})
    if not result:
        raise AIRegionGenerationError("discover_interactions: AI 无有效交互项")
    return result


def _ai_discover_interactions(config: ChatConfig, sub_zone: AreaSubZone, intent: str) -> list[dict[str, str]]:
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIRegionGenerationError("discover_interactions: 缺少模型配置")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=min(max(config.temperature, 0), 2),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt_table.get_text("world.discover.system", "你是可交互内容生成器，只输出 JSON。")},
            {"role": "user", "content": _build_discover_prompt(sub_zone, intent)},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise AIRegionGenerationError("discover_interactions: AI 返回为空")
    parsed = _extract_json_content(content)
    return _validate_discovered_interactions(parsed)


def _ai_generate_zones(session_id: str, center: Position, count: int, world_prompt: str, config: ChatConfig) -> list[Zone]:
    if not world_prompt.strip():
        raise AIRegionGenerationError("world_prompt 不能为空")

    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIRegionGenerationError("缺少有效的模型配置或 API Key")

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("world.region.system", "你是地图设计器，只输出 JSON。")},
                {"role": "user", "content": _build_region_prompt(center, count, world_prompt)},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            session_id,
            "map_generation",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise AIRegionGenerationError("AI 返回为空")

        parsed = _extract_json_content(content)
        raw_zones = parsed.get("zones") if isinstance(parsed, dict) else None
        if not isinstance(raw_zones, list) or len(raw_zones) < count:
            raise AIRegionGenerationError("AI 返回结构缺少 zones")

        zones: list[Zone] = []
        seen_coords: set[tuple[int, int]] = set()
        for item in raw_zones[:count]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.startswith("区域") or name.startswith("区块"):
                raise AIRegionGenerationError("AI 返回了无效区块名称")
            if "x" not in item or "y" not in item or "description" not in item:
                raise AIRegionGenerationError("AI 返回了不完整区块字段")
            x = int(item.get("x"))
            y = int(item.get("y"))
            if abs(x - center.x) > 1000 or abs(y - center.y) > 1000:
                raise AIRegionGenerationError("AI 返回了超出地图可视范围的坐标")
            description = str(item.get("description") or "").strip()
            if not description:
                raise AIRegionGenerationError("AI 返回了空区块描述")
            zone_type = str(item.get("zone_type") or "").strip().lower() or "unknown"
            if zone_type not in {"city", "village", "forest", "mountain", "river", "desert", "coast", "cave", "ruins", "unknown"}:
                zone_type = "unknown"
            size = str(item.get("size") or "").strip().lower() or "medium"
            if size not in {"small", "medium", "large"}:
                size = "medium"
            rmin, rmax = _zone_radius_range(size)
            raw_radius = int(item.get("radius_m") or int((rmin + rmax) / 2))
            radius_m = min(rmax, max(rmin, raw_radius))
            tags_raw = item.get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else ["generated", "ai"]
            sub_raw = item.get("sub_zones")
            seeds: list[ZoneSubZoneSeed] = []
            if isinstance(sub_raw, list):
                for sub in sub_raw[:20]:
                    if not isinstance(sub, dict):
                        continue
                    sub_name = str(sub.get("name") or "").strip()
                    if not sub_name:
                        continue
                    seeds.append(
                        ZoneSubZoneSeed(
                            name=sub_name,
                            offset_x=int(sub.get("offset_x") or 0),
                            offset_y=int(sub.get("offset_y") or 0),
                            offset_z=int(sub.get("offset_z") or 0),
                            description=str(sub.get("description") or "").strip(),
                        )
                    )
            min_count, max_count = _sub_zone_count_range(size)
            if len(seeds) < min_count or len(seeds) > max_count:
                seeds = _default_sub_zone_seeds(size, name)
            if _is_sub_seed_quality_bad(seeds, radius_m):
                seeds = _default_sub_zone_seeds(size, name)
            normalized_seeds: list[ZoneSubZoneSeed] = []
            for s in seeds:
                ox, oy = _fit_offset_in_radius(s.offset_x, s.offset_y, radius_m)
                normalized_seeds.append(
                    ZoneSubZoneSeed(
                        name=s.name,
                        offset_x=ox,
                        offset_y=oy,
                        offset_z=s.offset_z,
                        description=s.description,
                    )
                )
            zone_id = f"zone_{x}_{y}_{center.z}"
            coord = (x, y)
            if coord in seen_coords:
                continue
            seen_coords.add(coord)
            zones.append(
                Zone(
                    zone_id=zone_id,
                    name=name,
                    x=x,
                    y=y,
                    z=center.z,
                    zone_type=zone_type,
                    size=size,
                    radius_m=radius_m,
                    description=description,
                    tags=tags,
                    sub_zones=normalized_seeds,
                )
            )

        if not zones:
            raise AIRegionGenerationError("AI 结果解析后无有效区块")
        _enforce_non_overlap(zones)
        if len(seen_coords) < min(count, 3):
            raise AIRegionGenerationError("AI 返回的区块坐标过于集中")
        return zones
    except AIRegionGenerationError:
        raise
    except Exception as exc:
        raise AIRegionGenerationError(str(exc)) from exc


def generate_regions(req: RegionGenerateRequest) -> RegionGenerateResponse:
    save = get_current_save(default_session_id=req.session_id)
    if (not req.force_regenerate) and save.session_id == req.session_id and save.map_snapshot.zones:
        _ensure_area_snapshot(save)
        save_current(save)
        return RegionGenerateResponse(session_id=req.session_id, generated=False, zones=save.map_snapshot.zones)

    count = min(req.desired_count, req.max_count, 10)
    zones = _ai_generate_zones(req.session_id, req.player_position, count, req.world_prompt, req.config)

    save.session_id = req.session_id
    if req.force_regenerate:
        bump_world_revision(save, world_changed=True, map_changed=True, session_id=req.session_id)
        # Force regenerate must drop stale area/NPC data from previous map generations.
        save.role_pool = []
        save.area_snapshot = AreaSnapshot(clock=save.area_snapshot.clock)
        save.map_snapshot.zones = []
    save.map_snapshot.player_position = req.player_position
    save.map_snapshot.zones = zones
    save.area_snapshot = _area_snapshot_from_map(save)
    _ensure_role_pool_from_area(save)
    if req.force_regenerate:
        reconcile_consistency(save, session_id=req.session_id, reason="map_force_regenerate")
    save.player_runtime_data.session_id = req.session_id
    save.player_runtime_data.current_position = req.player_position
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_generate",
            f"生成区块 {len(zones)} 个",
            {"count": len(zones), "source": "/api/v1/world-map/regions/generate"},
        )
    )
    save_current(save)

    return RegionGenerateResponse(session_id=req.session_id, generated=True, zones=zones)


def generate_zones_for_chat(session_id: str, config: ChatConfig, world_prompt: str, count: int = 1) -> list[Zone]:
    save = get_current_save(default_session_id=session_id)
    center = (
        save.player_runtime_data.current_position
        or save.map_snapshot.player_position
        or Position(x=0, y=0, z=0, zone_id="zone_0_0_0")
    )
    safe_count = max(1, min(int(count or 1), 3))
    generated = _ai_generate_zones(session_id, center, safe_count, world_prompt, config)

    existing = {z.zone_id for z in save.map_snapshot.zones}
    appended: list[Zone] = []
    for zone in generated:
        if zone.zone_id in existing:
            continue
        save.map_snapshot.zones.append(zone)
        existing.add(zone.zone_id)
        appended.append(zone)

    if save.map_snapshot.player_position is None:
        save.map_snapshot.player_position = center
    _ensure_area_snapshot(save)
    for zone in appended:
        if not any(z.zone_id == zone.zone_id for z in save.area_snapshot.zones):
            save.area_snapshot.zones.append(
                AreaZone(
                    zone_id=zone.zone_id,
                    name=zone.name,
                    zone_type=_infer_zone_type(zone.tags),
                    size="medium",
                    center=Coord3D(x=zone.x, y=zone.y, z=zone.z),
                    description=zone.description,
                    sub_zone_ids=[],
                )
            )
        _ensure_zone_subzone_placeholders(save, zone.zone_id)
    _ensure_role_pool_from_area(save)
    save.session_id = session_id
    save.player_runtime_data.session_id = session_id
    if appended:
        save.game_logs.append(
            _new_game_log(
                session_id,
                "area_generate",
                f"聊天生成区块 {len(appended)} 个",
                {"count": len(appended), "source": "tool.generate_zone"},
            )
        )
    save_current(save)
    return appended


def render_map(req: RenderMapRequest) -> RenderMapResponse:
    nodes = [RenderNode(zone_id=z.zone_id, name=z.name, x=z.x, y=z.y) for z in req.zones]
    sub_nodes: list[RenderSubNode] = []
    circles: list[RenderCircle] = []
    for z in req.zones:
        circles.append(RenderCircle(zone_id=z.zone_id, center_x=z.x, center_y=z.y, radius_m=z.radius_m))
        for idx, sub in enumerate(z.sub_zones):
            sub_nodes.append(
                RenderSubNode(
                    sub_zone_id=f"sub_{z.zone_id}_{idx + 1}",
                    zone_id=z.zone_id,
                    name=sub.name,
                    x=z.x + sub.offset_x,
                    y=z.y + sub.offset_y,
                )
            )
    xs = [n.x for n in nodes] + [s.x for s in sub_nodes] or [0]
    ys = [n.y for n in nodes] + [s.y for s in sub_nodes] or [0]
    viewport = {
        "min_x": min(xs) - 10,
        "max_x": max(xs) + 10,
        "min_y": min(ys) - 10,
        "max_y": max(ys) + 10,
    }
    return RenderMapResponse(
        session_id=req.session_id,
        viewport=viewport,
        nodes=nodes,
        sub_nodes=sub_nodes,
        circles=circles,
        player_marker={"x": req.player_position.x, "y": req.player_position.y},
    )


def _distance_m(from_zone: Zone, to_zone: Zone) -> float:
    dx = float(from_zone.x - to_zone.x)
    dy = float(from_zone.y - to_zone.y)
    return sqrt(dx * dx + dy * dy)


def _requires_encounter_escape_before_move(
    save: SaveFile,
    *,
    target_zone_id: str | None,
    target_sub_zone_id: str | None,
) -> str | None:
    state = save.encounter_state
    if state is None or not state.active_encounter_id:
        return None
    encounter = next((item for item in state.encounters if item.encounter_id == state.active_encounter_id), None)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return None
    if encounter.zone_id and target_zone_id and encounter.zone_id != target_zone_id:
        return encounter.encounter_id
    if encounter.sub_zone_id and encounter.sub_zone_id != target_sub_zone_id:
        return encounter.encounter_id
    return None


def _attempt_escape_for_move(
    *,
    session_id: str,
    target_zone_id: str | None,
    target_sub_zone_id: str | None,
    config: ChatConfig | None = None,
) -> None:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    encounter_id = _requires_encounter_escape_before_move(
        save,
        target_zone_id=target_zone_id,
        target_sub_zone_id=target_sub_zone_id,
    )
    if not encounter_id:
        return
    from app.models.schemas import EncounterEscapeRequest
    from app.services.encounter_service import escape_encounter

    result = escape_encounter(
        encounter_id,
        EncounterEscapeRequest(
            session_id=session_id,
            config=config,
        ),
    )
    if not result.escape_success:
        raise ValueError("ENCOUNTER_ESCAPE_BLOCKED")


def move_to_zone(req: MoveRequest) -> MoveResponse:
    _attempt_escape_for_move(
        session_id=req.session_id,
        target_zone_id=req.to_zone_id,
        target_sub_zone_id=None,
    )
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")

    to_zone = next((z for z in save.map_snapshot.zones if z.zone_id == req.to_zone_id), None)
    if to_zone is None:
        raise KeyError("zone not found")

    from_zone = next((z for z in save.map_snapshot.zones if z.zone_id == req.from_zone_id), None)
    if from_zone is None:
        current = save.player_runtime_data.current_position or save.map_snapshot.player_position
        if current is None:
            current = Position(x=0, y=0, z=0, zone_id=req.from_zone_id)
        from_zone = Zone(
            zone_id=current.zone_id or req.from_zone_id,
            name="当前位置",
            x=current.x,
            y=current.y,
            z=current.z,
            description="玩家当前位置",
            tags=["runtime"],
        )

    distance_m = _distance_m(from_zone, to_zone)
    speed_mph = max(1, save.player_static_data.move_speed_mph)
    duration_min = max(1, ceil((distance_m / speed_mph) * 60.0))

    new_position = Position(x=to_zone.x, y=to_zone.y, z=to_zone.z, zone_id=to_zone.zone_id)
    save.map_snapshot.player_position = new_position
    save.player_runtime_data.session_id = req.session_id
    save.player_runtime_data.current_position = new_position
    _ensure_area_snapshot(save)
    _ensure_zone_subzone_placeholders(save, to_zone.zone_id)
    save.area_snapshot.current_zone_id = to_zone.zone_id
    save.area_snapshot.current_sub_zone_id = None
    if save.area_snapshot.clock is not None:
        save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, duration_min)

    actor_name = req.player_name or save.player_static_data.name
    from_name = from_zone.name
    to_name = to_zone.name
    movement_log = MovementLog(
        id=f"log_{int(datetime.now(timezone.utc).timestamp())}",
        summary=f"{actor_name} 从【{from_name}】移动到【{to_name}】，花费了 {duration_min} 分钟",
        payload={
            "from_zone_id": req.from_zone_id,
            "from_zone_name": from_name,
            "to_zone_id": req.to_zone_id,
            "to_zone_name": to_name,
            "from_x": from_zone.x,
            "from_y": from_zone.y,
            "to_x": to_zone.x,
            "to_y": to_zone.y,
            "to_zone_description": to_zone.description,
            "distance_m": round(distance_m, 3),
            "duration_min": duration_min,
        },
    )
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "move",
            movement_log.summary,
            {
                "to_zone_id": to_zone.zone_id,
                "to_zone_name": to_zone.name,
                "duration_min": duration_min,
                "distance_m": round(distance_m, 3),
            },
        )
    )
    try:
        from app.services.team_service import apply_team_reactions_in_save, sync_team_members_with_player_in_save

        sync_team_members_with_player_in_save(save)
        apply_team_reactions_in_save(
            save,
            session_id=req.session_id,
            trigger_kind="zone_move",
            summary=movement_log.summary,
        )
    except Exception:
        pass
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advance_active_encounter_in_save(save, session_id=req.session_id, minutes_elapsed=duration_min)
    except Exception:
        pass
    save_current(save)

    return MoveResponse(
        session_id=req.session_id,
        new_position=new_position,
        duration_min=duration_min,
        movement_log=movement_log,
    )


def _default_world_clock(calendar: str = "fantasy_default") -> WorldClock:
    return WorldClock(
        calendar=calendar,
        year=1024,
        month=3,
        day=14,
        hour=9,
        minute=30,
        updated_at=_utc_now(),
    )


def _clock_to_datetime(clock: WorldClock) -> datetime:
    return datetime(
        year=max(clock.year, 1),
        month=min(max(clock.month, 1), 12),
        day=min(max(clock.day, 1), 28),
        hour=min(max(clock.hour, 0), 23),
        minute=min(max(clock.minute, 0), 59),
        tzinfo=timezone.utc,
    )


def _advance_clock(clock: WorldClock | None, delta_min: int) -> WorldClock:
    base = clock or _default_world_clock()
    dt = _clock_to_datetime(base) + timedelta(minutes=max(delta_min, 0))
    return WorldClock(
        calendar=base.calendar,
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=dt.hour,
        minute=dt.minute,
        updated_at=_utc_now(),
    )


def _distance3d_m(a: Coord3D, b: Coord3D) -> float:
    dx = float(a.x - b.x)
    dy = float(a.y - b.y)
    dz = float(a.z - b.z)
    return sqrt(dx * dx + dy * dy + dz * dz)


def _infer_zone_type(tags: list[str]) -> str:
    norm = {t.strip().lower() for t in tags}
    if {"city", "urban", "town"} & norm:
        return "city"
    if {"village", "rural"} & norm:
        return "village"
    if {"forest", "wood"} & norm:
        return "forest"
    if {"mountain"} & norm:
        return "mountain"
    if {"river"} & norm:
        return "river"
    if {"desert"} & norm:
        return "desert"
    if {"coast", "beach", "sea"} & norm:
        return "coast"
    return "unknown"


def _area_snapshot_from_map(save: SaveFile) -> AreaSnapshot:
    zones: list[AreaZone] = []
    sub_zones: list[AreaSubZone] = []
    for idx, zone in enumerate(save.map_snapshot.zones):
        sub_ids: list[str] = []
        seeds = zone.sub_zones or _default_sub_zone_seeds(zone.size, zone.name)
        for sidx, seed in enumerate(seeds):
            ox, oy = _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)
            sub_id = f"sub_{zone.zone_id}_{sidx + 1}"
            sub_ids.append(sub_id)
            npc_id, npc_name = _build_npc_identity(zone.name, seed.name, sub_id, 0)
            sub_zones.append(
                AreaSubZone(
                    sub_zone_id=sub_id,
                    zone_id=zone.zone_id,
                    name=seed.name,
                    coord=Coord3D(x=zone.x + ox, y=zone.y + oy, z=zone.z + seed.offset_z),
                    description=seed.description or zone.description,
                    generated_mode="pre",
                    key_interactions=[
                        AreaInteraction(
                            interaction_id=f"int_{zone.zone_id}_{sidx + 1}_observe",
                            name="观察周边",
                            type="scene",
                            generated_mode="pre",
                            placeholder=True,
                        )
                    ],
                    npcs=[AreaNpc(npc_id=npc_id, name=npc_name, state="idle")],
                )
            )
        zones.append(
            AreaZone(
                zone_id=zone.zone_id,
                name=zone.name,
                zone_type=(zone.zone_type or _infer_zone_type(zone.tags)),
                size=zone.size,
                center=Coord3D(x=zone.x, y=zone.y, z=zone.z),
                radius_m=zone.radius_m,
                description=zone.description,
                sub_zone_ids=sub_ids,
            )
        )
        if idx > 40:
            break

    current_zone_id = save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None
    current_sub_zone_id = None
    if not current_zone_id and zones:
        current_zone_id = zones[0].zone_id
        current_sub_zone_id = None

    return AreaSnapshot(
        zones=zones,
        sub_zones=sub_zones,
        current_zone_id=current_zone_id,
        current_sub_zone_id=current_sub_zone_id,
        clock=_default_world_clock(),
    )


def _ensure_area_snapshot(save: SaveFile) -> None:
    snap = save.area_snapshot
    if not snap.zones and save.map_snapshot.zones:
        save.area_snapshot = _area_snapshot_from_map(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    _ensure_role_pool_from_area(save)


def _ensure_zone_subzone_placeholders(save: SaveFile, zone_id: str) -> str:
    snap = save.area_snapshot
    zone = next((z for z in snap.zones if z.zone_id == zone_id), None)
    if zone is None:
        map_zone = next((z for z in save.map_snapshot.zones if z.zone_id == zone_id), None)
        zone_name = map_zone.name if map_zone else zone_id
        zone_desc = map_zone.description if map_zone else "自动生成区块"
        zone_size = map_zone.size if map_zone else "medium"
        zone_type = map_zone.zone_type if map_zone else "unknown"
        center_x = map_zone.x if map_zone else 0
        center_y = map_zone.y if map_zone else 0
        center_z = map_zone.z if map_zone else 0
        zone = AreaZone(
            zone_id=zone_id,
            name=zone_name,
            zone_type=zone_type,
            size=zone_size,
            center=Coord3D(x=center_x, y=center_y, z=center_z),
            radius_m=(map_zone.radius_m if map_zone else 120),
            description=zone_desc,
            sub_zone_ids=[],
        )
        snap.zones.append(zone)

    map_zone = next((z for z in save.map_snapshot.zones if z.zone_id == zone_id), None)
    seeds = (map_zone.sub_zones if map_zone and map_zone.sub_zones else _default_sub_zone_seeds(zone.size, zone.name))
    if _is_sub_seed_quality_bad(seeds, zone.radius_m):
        seeds = _default_sub_zone_seeds(zone.size, zone.name)
    first_sub_id = ""
    for sidx, seed in enumerate(seeds):
        sub_id = f"sub_{zone_id}_{sidx + 1}"
        if not first_sub_id:
            first_sub_id = sub_id
        sub = next((s for s in snap.sub_zones if s.sub_zone_id == sub_id), None)
        if sub is None:
            sub = AreaSubZone(
                sub_zone_id=sub_id,
                zone_id=zone_id,
                name=seed.name,
                coord=Coord3D(
                    x=zone.center.x + _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)[0],
                    y=zone.center.y + _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)[1],
                    z=zone.center.z + seed.offset_z,
                ),
                description=seed.description or zone.description or "默认子区块",
                generated_mode="pre",
                key_interactions=[],
                npcs=[],
            )
            snap.sub_zones.append(sub)
        if not sub.key_interactions:
            sub.key_interactions.append(
                AreaInteraction(
                    interaction_id=f"int_{zone_id}_{sidx + 1}_observe",
                    name="观察周边",
                    type="scene",
                    generated_mode="pre",
                    placeholder=True,
                )
            )
        if not sub.npcs:
            npc_id, npc_name = _build_npc_identity(zone.name, sub.name, sub_id, sidx)
            sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
        if sub_id not in zone.sub_zone_ids:
            zone.sub_zone_ids.append(sub_id)
    return first_sub_id


def init_world_clock(req: WorldClockInitRequest) -> WorldClockInitResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    _ensure_area_snapshot(save)
    save.area_snapshot.clock = _default_world_clock(req.calendar)
    save_current(save)
    return WorldClockInitResponse(ok=True, clock=save.area_snapshot.clock)


def get_area_current(session_id: str) -> AreaCurrentResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)
    return AreaCurrentResponse(ok=True, area_snapshot=save.area_snapshot)


def get_role_pool(session_id: str, query: str | None = None, limit: int = 200) -> RolePoolListResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)

    q = (query or "").strip().lower()
    filtered = save.role_pool
    if q:
        filtered = [r for r in save.role_pool if q in r.name.lower() or q in r.role_id.lower()]
    safe_limit = max(1, min(int(limit or 200), 500))
    items = filtered[:safe_limit]
    return RolePoolListResponse(session_id=session_id, total=len(filtered), items=items)


def get_role_card(session_id: str, role_id: str) -> NpcRoleCard:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return role


def _rough_token_count(text: str) -> int:
    clean = text.strip()
    if not clean:
        return 1
    # Rough token estimation for mixed CJK/Latin input.
    return max(1, ceil(len(clean) / 4))


def _speech_time_minutes(text: str, config: ChatConfig | None) -> tuple[int, int]:
    token_count = _rough_token_count(text)
    unit_min = max(1, int((config.speech_time_per_50_tokens_min if config is not None else 1) or 1))
    time_spent_min = max(1, ceil((token_count / 50.0) * unit_min))
    return token_count, time_spent_min


def _world_time_payload(clock: WorldClock | None) -> tuple[str, dict[str, str | int]]:
    if clock is None:
        return "未初始化时钟", {}
    text = f"{clock.year:04d}-{clock.month:02d}-{clock.day:02d} {clock.hour:02d}:{clock.minute:02d}"
    payload: dict[str, str | int] = {
        "calendar": clock.calendar,
        "year": clock.year,
        "month": clock.month,
        "day": clock.day,
        "hour": clock.hour,
        "minute": clock.minute,
    }
    return text, payload


def _normalize_logged_speaker_content(speaker: str, speaker_name: str, content: str) -> str:
    clean = (content or "").strip()
    if speaker != "npc" or not clean or not speaker_name.strip():
        return clean
    name = speaker_name.strip()
    if clean.startswith(name):
        trimmed = clean[len(name) :]
        trimmed = trimmed.lstrip(" ：:，,。.;；")
        if trimmed.startswith("的"):
            trimmed = trimmed[1:].lstrip(" ：:，,。.;；")
        if trimmed:
            return trimmed
    return clean


def _append_npc_dialogue(
    role: NpcRoleCard,
    speaker: str,
    speaker_role_id: str,
    speaker_name: str,
    content: str,
    clock: WorldClock | None,
    context_kind: str = "private_chat",
) -> None:
    world_time_text, world_time = _world_time_payload(clock)
    normalized_content = _normalize_logged_speaker_content(speaker, speaker_name, content)
    role.dialogue_logs.append(
        NpcDialogueEntry(
            id=f"dlg_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{len(role.dialogue_logs)}",
            speaker=("player" if speaker == "player" else "npc"),  # type: ignore[arg-type]
            speaker_role_id=speaker_role_id,
            speaker_name=speaker_name,
            context_kind=context_kind,  # type: ignore[arg-type]
            content=normalized_content,
            world_time_text=world_time_text,
            world_time=world_time,
        )
    )
    # Keep role card compact: only retain the latest 200 entries.
    if len(role.dialogue_logs) > 200:
        role.dialogue_logs = role.dialogue_logs[-200:]


def _build_npc_context(role: NpcRoleCard, recent_count: int = 16) -> str:
    if not role.dialogue_logs:
        return "无历史对话。"
    lines: list[str] = []
    for item in role.dialogue_logs[-recent_count:]:
        who = "玩家" if item.speaker == "player" else role.name
        context_kind = item.context_kind or "private_chat"
        lines.append(f"[{item.world_time_text}] ({context_kind}) {who}: {item.content}")
    return "\n".join(lines)


def _build_npc_prompt_context(role: NpcRoleCard, clock: WorldClock | None, recent_count: int = 12) -> str:
    lines = []
    if clock is not None:
        world_time_text, _ = _world_time_payload(clock)
        lines.append(f"当前世界时间={world_time_text}")
    lines.append(_npc_conversation_state_summary(role))
    lines.append("最近对话:")
    lines.append(_build_npc_context(role, recent_count=recent_count))
    return "\n".join(lines)


def _build_npc_roleplay_brief(role: NpcRoleCard) -> str:
    traits: list[str] = []
    if role.personality:
        traits.append(f"性格={_trim_npc_text(role.personality, 80)}")
    if role.speaking_style:
        traits.append(f"说话方式={_trim_npc_text(role.speaking_style, 80)}")
    if role.cognition:
        traits.append(f"认知={_trim_npc_text(role.cognition, 80)}")
    if role.alignment:
        traits.append(f"阵营={_trim_npc_text(role.alignment, 40)}")
    if role.likes:
        traits.append(f"偏好={' / '.join(role.likes[:5])}")
    traits.append(f"健谈值={role.talkative_current}/{role.talkative_maximum}")
    if role.state == "in_team":
        traits.append("当前是玩家队友，通常会更愿意给出实用反馈，但仍保留个人脾气。")
    if role.secret:
        traits.append("有不愿轻易透露的秘密，对敏感话题会收口或转移。")
    return "；".join(traits) or "保持该 NPC 的既有个性、语气和边界。"


def _upsert_npc_player_relation(role: NpcRoleCard, player_id: str, relation_tag: str, note: str) -> None:
    role.relations = [r for r in role.relations if r.target_role_id != player_id]
    role.relations.append(
        RoleRelation(
            target_role_id=player_id,
            relation_tag=(relation_tag.strip() or "neutral"),
            note=(note or "").strip(),
        )
    )


def apply_speech_time(session_id: str, text: str, config: ChatConfig | None) -> int:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    token_count, time_spent_min = _speech_time_minutes(text, config)
    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    save.game_logs.append(
        _new_game_log(
            session_id,
            "speech_time",
            f"玩家发言消耗时间 {time_spent_min} 分钟",
            {"token_count": token_count, "time_spent_min": time_spent_min},
        )
    )
    save_current(save)
    return time_spent_min


def _parse_player_intent(player_message: str) -> dict[str, object]:
    raw = (player_message or "").strip()
    parsed: dict[str, object] = {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = _extract_json_content(raw)
        except Exception:
            parsed = {}
    action_text = str(parsed.get("action_description") or "").strip()
    speech_text = str(parsed.get("speech_description") or "").strip()
    action_check = parsed.get("action_check_result") if isinstance(parsed.get("action_check_result"), dict) else None
    if not action_text and not speech_text:
        speech_text = raw
    display_lines: list[str] = []
    if action_text:
        display_lines.append(f"动作：{action_text}")
    if speech_text:
        display_lines.append(f"语言：{speech_text}")
    if isinstance(action_check, dict):
        status = "成功" if bool(action_check.get("success")) else "失败"
        critical = str(action_check.get("critical") or "none")
        critical_text = ""
        if critical == "critical_success":
            critical_text = "（大成功）"
        elif critical == "critical_failure":
            critical_text = "（大失败）"
        display_lines.append(f"检定：{status}{critical_text}")
    display_text = "\n".join(display_lines).strip() or raw
    return {
        "action_text": action_text,
        "speech_text": speech_text,
        "display_text": display_text,
        "action_check": action_check,
        "raw_text": raw,
    }


def _contains_any_token(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens if token)


def _world_clock_iso(clock: WorldClock | None) -> str | None:
    if clock is None:
        return None
    return _clock_to_datetime(clock).isoformat()


def _restore_npc_talkative(role: NpcRoleCard, clock: WorldClock | None) -> int:
    if clock is None or not role.last_private_chat_at:
        return 0
    try:
        delta = _clock_to_datetime(clock) - datetime.fromisoformat(role.last_private_chat_at)
    except ValueError:
        return 0
    delta_min = max(0, int(delta.total_seconds() // 60))
    recovered = max(0, (delta_min // 20) * 4)
    if recovered <= 0:
        return 0
    before = role.talkative_current
    role.talkative_current = min(role.talkative_maximum, role.talkative_current + recovered)
    return max(0, role.talkative_current - before)


def _npc_talkative_delta(role: NpcRoleCard, action_text: str, speech_text: str) -> int:
    merged = f"{action_text}\n{speech_text}".strip()
    cost = 16 if action_text and speech_text else 10
    if not merged:
        cost = 6
    if role.state == "in_team":
        cost = max(4, cost - 4)
    bonus = 0
    if any(like and like in merged for like in role.likes):
        bonus += 6
    if _contains_any_token(merged, ["谢谢", "thank", "合作", "帮忙", "一起", "冒险", "线索", "传闻"]):
        bonus += 3
    if _contains_any_token(merged, ["威胁", "threat", "滚开", "抢", "命令", "闭嘴"]):
        bonus -= 8
    if "健谈" in role.personality:
        cost -= 3
    if any(token in role.personality for token in ["寡言", "谨慎", "多疑"]):
        cost += 3
    return bonus - max(4, cost)


def _compose_npc_reply(action_reaction: str, speech_reply: str) -> str:
    parts = [part.strip() for part in [action_reaction, speech_reply] if part.strip()]
    return "\n".join(parts).strip()


def _trim_npc_text(value: str, limit: int = 72) -> str:
    text = " ".join((value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip("，,。.;； ") + "…"


def _clean_conversation_topic(value: str, limit: int = 16) -> str:
    text = _trim_npc_text(value or "", limit).strip("“”\"'，,。.;； ")
    text = re.sub(r"[吗嘛呢啊呀吧]$", "", text)
    return text.strip()


def _ensure_npc_conversation_state(role: NpcRoleCard) -> NpcConversationState:
    state = getattr(role, "conversation_state", None)
    if state is None:
        role.conversation_state = NpcConversationState()
    return role.conversation_state


def _conversation_topic_from_text(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    patterns = [
        r"(?:什么|啥)([^，。？！?、]{1,12})",
        r"([^，。？！?、]{1,12})是什么",
        r"你说的([^，。？！?、]{1,12})",
        r"关于([^，。？！?、]{1,12})",
        r"和([^，。？！?、]{1,12})有关",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return _clean_conversation_topic(match.group(1), 16)
    if "什么意思" in clean or "哪件事" in clean or "这事" in clean:
        return ""
    return ""


def _conversation_claim_topic(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    patterns = [
        r"和([^，。？！?、]{1,12})有关",
        r"关于([^，。？！?、]{1,12})",
        r"我说的([^，。？！?、]{1,12})",
        r"([^，。？！?、]{1,12})这事",
        r"去找([^，。？！?、]{1,12})",
        r"打听([^，。？！?、]{1,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return _clean_conversation_topic(match.group(1), 16)
    return ""


def _looks_like_explicit_follow_up(text: str) -> bool:
    clean = (text or "").strip()
    return any(
        token in clean
        for token in [
            "你说的",
            "你刚说的",
            "你提到的",
            "刚才说的",
            "上一句",
            "上句",
            "刚刚提到",
            "那个",
            "那件事",
            "这事",
            "什么意思",
            "哪件事",
        ]
    )


def _topic_matches_known_topic(topic: str, known_topic: str) -> bool:
    left = _clean_conversation_topic(topic, 16)
    right = _clean_conversation_topic(known_topic, 16)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _npc_follow_up_topic(role: NpcRoleCard, speech_text: str) -> str:
    state = _ensure_npc_conversation_state(role)
    clean = (speech_text or "").strip()
    direct = _conversation_topic_from_text(clean)
    if direct:
        explicit_follow_up = _looks_like_explicit_follow_up(clean)
        question_kind = _npc_question_kind(clean)
        known_topics = [
            state.current_topic,
            _conversation_claim_topic(state.last_npc_claim),
            state.last_referenced_entity,
        ]
        if explicit_follow_up or any(_topic_matches_known_topic(direct, item) for item in known_topics):
            return direct
        if question_kind not in {"identity", "team", "destination", "interest", "reason"} and state.last_npc_claim:
            return direct
    if not clean:
        return ""
    if any(token in clean for token in ["什么意思", "哪件事", "这事", "那个", "那件", "你刚说的"]):
        claim_topic = _conversation_claim_topic(state.last_npc_claim)
        if claim_topic:
            return claim_topic
        return _trim_npc_text(state.current_topic, 16)
    claim_topic = _conversation_claim_topic(state.last_npc_claim)
    if claim_topic and claim_topic in clean:
        return claim_topic
    current_topic = _trim_npc_text(state.current_topic, 16)
    if current_topic and current_topic in clean:
        return current_topic
    return ""


def _npc_conversation_state_summary(role: NpcRoleCard) -> str:
    state = _ensure_npc_conversation_state(role)
    summary = [
        f"- current_topic: {state.current_topic or 'none'}",
        f"- last_open_question: {state.last_open_question or 'none'}",
        f"- last_npc_claim: {state.last_npc_claim or 'none'}",
        f"- last_player_intent: {state.last_player_intent or 'none'}",
        f"- last_referenced_entity: {state.last_referenced_entity or 'none'}",
        f"- last_scene_mode: {state.last_scene_mode or 'unknown'}",
    ]
    return "\n".join(summary)


def _update_npc_conversation_state_from_player(
    role: NpcRoleCard,
    action_text: str,
    speech_text: str,
    player_text: str,
) -> None:
    state = _ensure_npc_conversation_state(role)
    state.last_player_intent = _trim_npc_text(player_text or speech_text or action_text, 120)
    state.last_scene_mode = "private_chat"
    follow_up_topic = _npc_follow_up_topic(role, speech_text)
    if follow_up_topic:
        state.current_topic = follow_up_topic
        state.last_referenced_entity = follow_up_topic
    else:
        for candidate in [*(role.likes or []), role.cognition, role.background, role.profile.dnd5e_sheet.background, role.profile.dnd5e_sheet.char_class]:
            token = _trim_npc_text(str(candidate or ""), 16)
            if token and token in (speech_text or ""):
                state.current_topic = token
                state.last_referenced_entity = token
                break
    if _npc_question_kind(speech_text):
        state.last_open_question = _trim_npc_text(speech_text, 120)
    state.updated_at = _utc_now()


def _update_npc_conversation_state_from_reply(
    role: NpcRoleCard,
    speech_reply: str,
    action_reaction: str,
) -> None:
    state = _ensure_npc_conversation_state(role)
    claim_text = _trim_npc_text(speech_reply or action_reaction, 120)
    if claim_text:
        state.last_npc_claim = claim_text
    state.last_scene_mode = "private_chat"
    claim_topic = _conversation_claim_topic(speech_reply)
    if claim_topic:
        state.current_topic = claim_topic
        state.last_referenced_entity = claim_topic
    elif speech_reply and state.current_topic and state.current_topic in speech_reply:
        state.current_topic = _trim_npc_text(state.current_topic, 16)
    state.updated_at = _utc_now()


def _npc_primary_topic(role: NpcRoleCard) -> str:
    state = _ensure_npc_conversation_state(role)
    for candidate in [
        state.current_topic,
        _conversation_claim_topic(state.last_npc_claim),
        *(role.likes or []),
        role.cognition,
        role.background,
        role.profile.dnd5e_sheet.background,
        role.profile.dnd5e_sheet.char_class,
    ]:
        text = _trim_npc_text(str(candidate or ""), 20)
        if text:
            return text
    return "眼前这摊事"


def _npc_question_kind(speech_text: str) -> str:
    text = (speech_text or "").strip()
    if not text:
        return ""
    if _contains_any_token(text, ["队友", "同伴", "伙伴", "同行", "一伙", "跟我走", "跟着我", "跟我一起"]):
        return "team"
    if _contains_any_token(text, ["你是谁", "叫什么", "名字", "怎么称呼"]):
        return "identity"
    if _contains_any_token(text, ["想去", "去哪", "去哪里", "什么地方", "哪儿", "目的地", "先去", "有什么想去的地方"]):
        return "destination"
    if _contains_any_token(text, ["喜欢什么", "喜欢", "在意什么", "感兴趣", "想聊什么"]):
        return "interest"
    if _contains_any_token(text, ["为什么", "为何", "怎么了", "什么情况", "发生了什么"]):
        return "reason"
    if "？" in text or "?" in text or "吗" in text or _contains_any_token(text, ["什么", "谁", "哪", "怎么"]):
        return "general_question"
    return ""


def _npc_action_has_detail(text: str) -> bool:
    clean = (text or "").strip()
    if len(clean) < 12:
        return False
    detail_tokens = ["眼", "眉", "嘴角", "肩", "手", "指", "步", "身", "视线", "呼吸", "点头", "抬", "侧", "退", "站位"]
    return any(token in clean for token in detail_tokens)


def _npc_speech_is_generic(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return True
    generic_tokens = [
        "我听着",
        "你继续",
        "继续说",
        "我在听",
        "说下去",
        "先把事情做稳",
        "再继续谈",
        "先说重点",
        "慢慢说",
        "看情况",
        "之后再说",
    ]
    return any(token in clean for token in generic_tokens)


def _npc_reply_matches_question(role: NpcRoleCard, question_kind: str, speech_text: str, speech_reply: str) -> bool:
    clean = (speech_reply or "").strip()
    if not question_kind:
        return bool(clean)
    follow_up_topic = _npc_follow_up_topic(role, speech_text)
    if follow_up_topic:
        return follow_up_topic in clean and any(token in clean for token in ["是", "因为", "最近", "意思", "麻烦", "线索", "情况"])
    primary_topic = _trim_npc_text(_npc_primary_topic(role), 12)
    cognition_topic = _trim_npc_text(role.cognition or "", 12)
    tokens_by_kind = {
        "team": ["队友", "同伴", "跟", "一起"],
        "identity": [role.name, "名字", "叫"],
        "destination": ["去", "地方", "线索", "地图", "传闻", "草药", "打听"],
        "interest": ["喜欢", "在意", primary_topic],
        "reason": ["因为", "重视", "在意", cognition_topic, primary_topic],
        "general_question": [primary_topic, "因为", "在意"],
    }
    return any(token and token in clean for token in tokens_by_kind.get(question_kind, []))


def _fallback_npc_action_reaction(
    role: NpcRoleCard,
    action_text: str,
    speech_text: str,
    action_check: dict[str, object] | None,
) -> str:
    merged = f"{action_text}\n{speech_text}".strip()
    if _contains_any_token(merged, ["威胁", "threat", "抢", "闭嘴", "滚开"]):
        return f"{role.name} 眉眼一下沉了下去，肩背也跟着绷紧，手指已经压到随身装备旁，站位明显收得更稳。"
    if action_check is not None and not bool(action_check.get("success")):
        if speech_text:
            return f"{role.name} 先被你的举动逼得肩线一紧，随即往旁边让开半步，视线从你的动作一路抬到脸上，眉眼间的戒备一点没松。"
        return f"{role.name} 下意识侧开身，把重心压回更稳的站位，手也悄悄收到了随身装备旁，神情明显冷了下来。"
    if any(like and like in merged for like in role.likes):
        return f"{role.name} 的眼神明显亮了一下，原本绷着的嘴角也松开些，身子不自觉地朝你这边微微转了过来。"
    if action_text and speech_text:
        if _contains_any_token(action_text, ["踢", "踹", "推", "拍", "抓", "拽", "扯", "撞"]):
            return f"{role.name} 先被你的动作逼得绷紧了肩线，随后才稳住步子重新看向你，眉头还压着，却没有立刻转身走开。"
        return f"{role.name} 先顺着你的动作看了一遍，随后抬眼和你对上视线，指尖轻轻收紧又松开，像是在判断你的来意。"
    if speech_text:
        return f"{role.name} 先抬眼看了你一会儿，神情还算平稳，随后轻轻点了点头，视线没有移开，等着你把话说清楚。"
    if action_text:
        return f"{role.name} 的目光顺着你的动作移动，呼吸放得很轻，脚下没有退开，只是先把你的举动记在心里。"
    return f"{role.name} 抬手理了理衣袖，目光在你身上停了一瞬，脸上的神色没有松，但也没有直接拒人千里。"


def _fallback_npc_speech_reply(
    role: NpcRoleCard,
    speech_text: str,
    action_check: dict[str, object] | None,
) -> str:
    clean = (speech_text or "").strip()
    if not clean:
        return ""
    question_kind = _npc_question_kind(clean)
    primary_topic = _npc_primary_topic(role)
    follow_up_topic = _npc_follow_up_topic(role, clean)
    if action_check is not None and not bool(action_check.get("success")):
        if follow_up_topic:
            return f"“我说的{follow_up_topic}，是这附近最近冒出来的一桩麻烦事。我愿意解释，但你先把动作收住。”"
        if question_kind == "team":
            if role.state == "in_team":
                return "“现在算。既然我已经跟着你走，这一路就先把事办稳。”"
            return "“这话现在还说不上，你先把分寸拿稳。”"
        if question_kind == "destination":
            if "地图" in primary_topic or "线索" in primary_topic:
                return "“地方我有想法，但你先别再乱来。真要走，我更想去找和旧地图有关的线索。”"
            return f"“地方我有想法，但你先别再乱来。真要走，我更想先去摸清和{primary_topic}有关的事。”"
        return "“先把动作收住。你要谈，可以好好谈。”"
    if follow_up_topic:
        return f"“我说的{follow_up_topic}，是这附近最近反复冒头的一桩麻烦事。我现在只摸到些零碎线索，还没把来路完全说死。”"
    if question_kind == "identity":
        return f"“{role.name}。你记住这个名字就行。”"
    if question_kind == "team":
        if role.state == "in_team":
            return "“现在是。既然我在队里，就会跟着你把这段路走完。”"
        return "“是不是队友，要看我们接下来能不能走到一条路上。”"
    if question_kind == "destination":
        if "地图" in primary_topic or "线索" in primary_topic:
            return "“如果由我选，我想先去找和旧地图有关的线索。”"
        if "草药" in primary_topic:
            return "“真要我挑地方，我更想先去找些能用的草药。”"
        if "传闻" in primary_topic:
            return "“我更想先去打听传闻，地方错了，后面都白跑。”"
        return f"“如果由我选，我想先去把和{primary_topic}有关的事摸清。”"
    if question_kind == "interest":
        return f"“我更在意{primary_topic}。这类话题，你提了我就愿意多说两句。”"
    if question_kind == "reason":
        reason_text = _trim_npc_text(role.cognition or primary_topic, 24)
        return f"“因为{reason_text}。这事在我这儿不算小事。”"
    if any(like and like in clean for like in role.likes):
        return f"“{primary_topic}这事我知道一些，也愿意听你继续说。”"
    if question_kind == "general_question":
        return f"“我听明白了。真要说的话，我更在意{primary_topic}。”"
    if _contains_any_token(clean, ["谢谢", "thank", "帮忙", "合作", "一起"]):
        return "“这话我记下了。后面别松劲，我们继续走。”"
    return f"“我听见了。和{primary_topic}有关的事，我会留心。”"


def _normalize_npc_reply_parts(
    role: NpcRoleCard,
    action_text: str,
    speech_text: str,
    action_check: dict[str, object] | None,
    action_reaction: str,
    speech_reply: str,
    *,
    allow_action_repair: bool,
    allow_speech_repair: bool,
) -> tuple[str, str]:
    normalized_action = (action_reaction or "").strip()
    normalized_speech = (speech_reply or "").strip()
    if allow_action_repair and not _npc_action_has_detail(normalized_action):
        normalized_action = _fallback_npc_action_reaction(role, action_text, speech_text, action_check)
    if allow_speech_repair and speech_text.strip():
        question_kind = _npc_question_kind(speech_text)
        if (
            not normalized_speech
            or _npc_speech_is_generic(normalized_speech)
            or (question_kind and not _npc_reply_matches_question(role, question_kind, speech_text, normalized_speech))
        ):
            normalized_speech = _fallback_npc_speech_reply(role, speech_text, action_check)
    return normalized_action.strip(), normalized_speech.strip()


def _fallback_npc_reply_parts(
    role: NpcRoleCard,
    action_text: str,
    speech_text: str,
    action_check: dict[str, object] | None,
) -> tuple[str, str, str]:
    merged = f"{action_text}\n{speech_text}".strip()
    if _contains_any_token(merged, ["威胁", "threat", "抢", "闭嘴", "滚开"]):
        return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), "“我不喜欢这种说话方式。”", "hostile")
    if action_check is not None and not bool(action_check.get("success")):
        if speech_text:
            return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), _fallback_npc_speech_reply(role, speech_text, action_check), "wary")
        return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), "", "wary")
    if any(like and like in merged for like in role.likes):
        if speech_text:
            return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), _fallback_npc_speech_reply(role, speech_text, action_check), "friendly")
        return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), "", "friendly")
    if action_text and not speech_text:
        return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), "", "met")
    return (_fallback_npc_action_reaction(role, action_text, speech_text, action_check), _fallback_npc_speech_reply(role, speech_text, action_check), "met")


def _public_behavior_triggered(action_text: str, speech_text: str, raw_text: str) -> bool:
    if speech_text.strip():
        return True
    merged = f"{action_text}\n{raw_text}".strip()
    return _contains_any_token(merged, ["奔跑", "大喊", "砸", "挥舞", "冲向", "推开", "攻击", "打碎", "翻找"])


def _new_scene_event(
    kind: str,
    content: str,
    *,
    actor_role_id: str = "",
    actor_name: str = "",
    metadata: dict[str, str | int | float | bool] | None = None,
) -> SceneEvent:
    return SceneEvent(
        event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{random.randint(100, 999)}",
        kind=kind,  # type: ignore[arg-type]
        actor_role_id=actor_role_id,
        actor_name=actor_name,
        content=content,
        metadata=metadata or {},
    )


def _visible_public_roles(save: SaveFile) -> list[NpcRoleCard]:
    _ensure_area_snapshot(save)
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    current_sub = next((item for item in save.area_snapshot.sub_zones if item.sub_zone_id == current_sub_zone_id), None)
    if current_sub is None:
        return []
    visible_ids = {npc.npc_id for npc in current_sub.npcs}
    return [role for role in save.role_pool if role.role_id in visible_ids and role.state != "in_team" and role.sub_zone_id == current_sub.sub_zone_id]


def _public_npc_reaction(role: NpcRoleCard, player_text: str, gm_summary: str) -> tuple[str, str]:
    merged = f"{player_text}\n{gm_summary}".strip()
    if _contains_any_token(merged, ["威胁", "threat", "抢", "攻击", "杀"]):
        return (f"{role.name} 的肩背一下绷紧，手也压到了随身物件旁，眼神明显冷了下来。", "wary")
    if _contains_any_token(merged, ["谢谢", "thank", "合作", "帮忙", "保护", "一起"]):
        return (f"{role.name} 朝这边多看了两眼，原本收着的神情也松开了些，还轻轻点了点头。", "friendly")
    if _contains_any_token(merged, [role.name]):
        return (f"{role.name} 闻声转过身来，目光在你脸上停了停，像是在判断要不要靠近。", "met")
    return (f"{role.name} 听见动静后侧过脸看了过来，脚下没有挪开，只是把你的举动先记在心里。", "met")


def _detect_targeted_visible_npc(save: SaveFile, player_text: str) -> NpcRoleCard | None:
    clean = (player_text or "").strip()
    if not clean:
        return None
    visible_roles = _visible_public_roles(save)
    for role in visible_roles:
        if role.name and role.name in clean:
            return role
    return None


def _fallback_targeted_public_npc_reply(
    role: NpcRoleCard,
    player_text: str,
    gm_summary: str,
) -> tuple[str, str, str]:
    action = _fallback_npc_action_reaction(role, "", player_text, None)
    speech = _fallback_npc_speech_reply(role, player_text, None)
    if _contains_any_token(player_text, ["谢谢", "合作", "帮忙", "一起", "队友"]):
        return action, speech, "friendly"
    if _contains_any_token(player_text, ["威胁", "滚开", "抢", "攻击", "闭嘴"]):
        return action, speech, "wary"
    return action, speech, "met"


def _generate_targeted_public_npc_reply(
    save: SaveFile,
    role: NpcRoleCard,
    player_text: str,
    gm_summary: str,
    config: ChatConfig | None,
) -> tuple[str, str, str]:
    knowledge = build_npc_knowledge_snapshot(save, role.role_id)
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
                prompt = prompt_table.render(
                    PromptKeys.NPC_PUBLIC_TARGETED_USER,
                    "你要扮演公开区域里被玩家喊话的NPC，只输出 JSON。",
                    roleplay_brief=_build_npc_roleplay_brief(role),
                    scene_summary=gm_summary or "公开区域中的即时互动",
                    world_time_text=world_time_text,
                    conversation_state=_npc_conversation_state_summary(role),
                    knowledge_rules="\n".join(f"- {item}" for item in knowledge.response_rules),
                    player_text=player_text,
                    context=_build_npc_prompt_context(role, save.area_snapshot.clock, recent_count=8),
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(config.temperature, 0), 2),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                action = str(parsed.get("action_reaction") or "").strip()
                speech = str(parsed.get("speech_reply") or "").strip()
                relation_tag = str(parsed.get("relation_tag") or "met").strip().lower()
                if relation_tag not in {"ally", "friendly", "met", "neutral", "wary", "hostile"}:
                    relation_tag = "met"
                action, speech = _normalize_npc_reply_parts(
                    role,
                    "",
                    player_text,
                    None,
                    action,
                    speech,
                    allow_action_repair=False,
                    allow_speech_repair=False,
                )
                if action or speech:
                    return action, speech, relation_tag
            except Exception:
                pass
    return _fallback_targeted_public_npc_reply(role, player_text, gm_summary)


def _generate_bystander_public_reactions(
    save: SaveFile,
    roles: list[NpcRoleCard],
    player_text: str,
    gm_summary: str,
    config: ChatConfig | None,
) -> list[tuple[NpcRoleCard, str, str]]:
    created: list[tuple[NpcRoleCard, str, str]] = []
    for role in roles[:2]:
        action_reaction = ""
        speech_reply = ""
        relation_tag = "met"
        if config is not None:
            api_key = (config.openai_api_key or "").strip()
            model = (config.model or "").strip()
            if api_key and model:
                try:
                    client = OpenAI(api_key=api_key)
                    prompt = prompt_table.render(
                        PromptKeys.NPC_PUBLIC_BYSTANDER_USER,
                        "你要扮演公开区域中的旁观NPC，只输出 JSON。",
                        roleplay_brief=_build_npc_roleplay_brief(role),
                        scene_summary=gm_summary or "公开区域中的即时互动",
                        player_text=player_text,
                        gm_summary=gm_summary,
                    )
                    resp = client.chat.completions.create(
                        model=model,
                        temperature=min(max(config.temperature, 0), 2),
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": config.gm_prompt},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                    action_reaction = _trim_npc_text(str(parsed.get("action_reaction") or "").strip(), 160)
                    speech_reply = _trim_npc_text(str(parsed.get("speech_reply") or "").strip(), 120)
                    relation_tag = str(parsed.get("relation_tag") or "met").strip().lower()
                except Exception:
                    action_reaction = ""
                    speech_reply = ""
        line = _compose_npc_reply(action_reaction, speech_reply)
        if not line:
            line, relation_tag = _public_npc_reaction(role, player_text, gm_summary)
        if relation_tag not in {"friendly", "met", "wary", "hostile", "neutral"}:
            relation_tag = "met"
        created.append((role, line, relation_tag))
    return created


def advance_public_scene_in_save(
    save: SaveFile,
    session_id: str,
    player_text: str,
    gm_summary: str = "",
    config: ChatConfig | None = None,
) -> list[SceneEvent]:
    _ensure_area_snapshot(save)
    intent = _parse_player_intent(player_text)
    action_text = str(intent["action_text"])
    speech_text = str(intent["speech_text"])
    display_text = str(intent["display_text"])
    if not _public_behavior_triggered(action_text, speech_text, str(intent["raw_text"])):
        return []

    visible_roles = _visible_public_roles(save)
    if not visible_roles:
        return []

    player_id = save.player_static_data.player_id
    events: list[SceneEvent] = []
    targeted_role = _detect_targeted_visible_npc(save, display_text)
    if targeted_role is not None:
        action_reaction, speech_reply, relation_tag = _generate_targeted_public_npc_reply(save, targeted_role, display_text, gm_summary, config)
        _update_npc_conversation_state_from_player(targeted_role, action_text, speech_text, display_text)
        _append_npc_dialogue(
            role=targeted_role,
            speaker="player",
            speaker_role_id=player_id,
            speaker_name=save.player_static_data.name,
            content=display_text,
            clock=save.area_snapshot.clock,
            context_kind="public_targeted",
        )
        _update_npc_conversation_state_from_reply(targeted_role, speech_reply, action_reaction)
        targeted_reply = _compose_npc_reply(action_reaction, speech_reply) or action_reaction or speech_reply
        _append_npc_dialogue(
            role=targeted_role,
            speaker="npc",
            speaker_role_id=targeted_role.role_id,
            speaker_name=targeted_role.name,
            content=targeted_reply,
            clock=save.area_snapshot.clock,
            context_kind="public_targeted",
        )
        _upsert_npc_player_relation(targeted_role, player_id, relation_tag, "公开场景针对性互动")
        targeted_role.cognition_changes.append(f"{_utc_now()} 公开针对性互动: {display_text[:64]}")
        targeted_role.cognition_changes = targeted_role.cognition_changes[-50:]
        targeted_role.attitude_changes.append(f"{_utc_now()} public_targeted->{relation_tag}")
        targeted_role.attitude_changes = targeted_role.attitude_changes[-50:]
        events.append(
            _new_scene_event(
                "public_targeted_npc_reply",
                targeted_reply,
                actor_role_id=targeted_role.role_id,
                actor_name=targeted_role.name,
                metadata={"relation_tag": relation_tag},
            )
        )

    bystander_roles = [role for role in visible_roles if targeted_role is None or role.role_id != targeted_role.role_id]
    for role, line, relation_tag in _generate_bystander_public_reactions(save, bystander_roles, display_text, gm_summary, config):
        _upsert_npc_player_relation(role, player_id, relation_tag, "公开场景行为记忆")
        role.cognition_changes.append(f"{_utc_now()} 公开记忆: {display_text[:64]}")
        role.cognition_changes = role.cognition_changes[-50:]
        role.attitude_changes.append(f"{_utc_now()} public->{relation_tag}")
        role.attitude_changes = role.attitude_changes[-50:]
        events.append(
            _new_scene_event(
                "public_bystander_reaction",
                line,
                actor_role_id=role.role_id,
                actor_name=role.name,
                metadata={"relation_tag": relation_tag},
            )
        )

    try:
        from app.services.team_service import generate_team_public_replies_in_save

        for reaction in generate_team_public_replies_in_save(
            save,
            session_id=session_id,
            player_text=display_text,
            scene_summary=gm_summary,
            config=config,
        )[:2]:
            events.append(
                _new_scene_event(
                    "team_public_reaction",
                    reaction.content,
                    actor_role_id=reaction.member_role_id,
                    actor_name=reaction.member_name,
                    metadata={"trigger_kind": reaction.trigger_kind},
                )
            )
    except Exception:
        pass

    if events:
        save.game_logs.append(
            _new_game_log(
                session_id,
                "public_scene_events",
                f"公开区域产生 {len(events)} 条场景反应",
                {"count": len(events)},
            )
        )
        if any(event.kind == "public_bystander_reaction" for event in events):
            save.game_logs.append(
                _new_game_log(
                    session_id,
                    "public_npc_reaction",
                    "公开区域触发周围NPC反应",
                    {"count": sum(1 for event in events if event.kind == "public_bystander_reaction")},
                )
            )

    if targeted_role is None and any(event.kind == "public_bystander_reaction" for event in events):
        try:
            from app.models.schemas import EncounterCheckRequest
            from app.services.encounter_service import check_for_encounter

            encounter_result = check_for_encounter(EncounterCheckRequest(session_id=session_id, trigger_kind="random_dialog", config=config))
            if encounter_result.generated and encounter_result.encounter is not None:
                events.append(
                    _new_scene_event(
                        "encounter_started",
                        f"【遭遇触发】{encounter_result.encounter.title}\n{encounter_result.encounter.description}",
                        metadata={
                            "encounter_id": encounter_result.encounter.encounter_id,
                            "encounter_title": encounter_result.encounter.title,
                        },
                    )
                )
        except Exception:
            pass

    return events[:5]


def _scene_events_to_summary(events: list[SceneEvent]) -> str:
    if not events:
        return ""
    has_public_reaction = any(
        event.kind in {"public_bystander_reaction", "team_public_reaction"} for event in events
    )
    lines = []
    for event in events:
        prefix = event.actor_name or "场景"
        if event.kind == "public_bystander_reaction":
            lines.append(f"- {prefix}: {event.content}")
        elif event.kind == "team_public_reaction":
            lines.append(f"- 队友 {prefix}: {event.content}")
        else:
            lines.append(f"- {prefix}: {event.content}")
    header = "【场景反应】"
    if has_public_reaction:
        header += "\n周围NPC反应："
    return header + "\n" + "\n".join(lines)


def apply_public_npc_reactions_in_save(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str = "",
    config: ChatConfig | None = None,
) -> str:
    return _scene_events_to_summary(advance_public_scene_in_save(save, session_id, player_text, summary, config))


def npc_greet(req: NpcGreetRequest) -> NpcGreetResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    role = next((r for r in save.role_pool if r.role_id == req.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")

    greeting = f"{role.name} 见你走近，低声打了个招呼：'你好，第一次来这片地方吗？'"
    if req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
                knowledge = build_npc_knowledge_snapshot(save, role.role_id)
                default_prompt = (
                    "你是跑团NPC。场景是：玩家刚刚走到你面前，你注意到对方靠近并开口。"
                    "请生成第一反应式的自然招呼语。"
                    "要求：只输出1句口语化对话（最多35字），不要诗意描写，不要旁白，不要比喻，不要邀请长段剧情。"
                    "语气要像面对面打招呼，内容要贴合当前地点和时间。"
                    "姓名=$name, 性格=$personality, 说话方式=$speaking_style, "
                    "外观=$appearance, 背景=$background, 认知=$cognition, 阵营=$alignment, "
                    "当前世界时间=$world_time_text, 当前知识边界=$knowledge_rules"
                )
                prompt = prompt_table.render(
                    PromptKeys.NPC_GREET_USER,
                    default_prompt,
                    name=role.name,
                    roleplay_brief=_build_npc_roleplay_brief(role),
                    personality=role.personality,
                    speaking_style=role.speaking_style,
                    appearance=role.appearance,
                    background=role.background,
                    cognition=role.cognition,
                    alignment=role.alignment,
                    world_time_text=world_time_text,
                    knowledge_rules=" / ".join(knowledge.response_rules),
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    greeting = content
                usage = resp.usage
                token_usage_store.add(
                    req.session_id,
                    "chat",
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            except Exception:
                pass

    _append_npc_dialogue(
        role=role,
        speaker="npc",
        speaker_role_id=role.role_id,
        speaker_name=role.name,
        content=greeting,
        clock=save.area_snapshot.clock,
    )
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "npc_greet",
            f"{role.name} 向玩家问候",
            {"npc_role_id": role.role_id},
        )
    )
    save_current(save)
    return NpcGreetResponse(session_id=req.session_id, npc_role_id=role.role_id, greeting=greeting)


def npc_chat(req: NpcChatRequest) -> NpcChatResponse:
    time_spent_min = apply_speech_time(req.session_id, req.player_message, req.config)
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    role = next((r for r in save.role_pool if r.role_id == req.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    _ensure_npc_role_complete(save, role)
    player = save.player_static_data
    intent = _parse_player_intent(req.player_message)
    action_text = str(intent["action_text"])
    speech_text = str(intent["speech_text"])
    player_text = str(intent["display_text"]).strip()
    action_check = intent["action_check"] if isinstance(intent["action_check"], dict) else None
    _update_npc_conversation_state_from_player(role, action_text, speech_text, player_text)
    _append_npc_dialogue(
        role=role,
        speaker="player",
        speaker_role_id=player.player_id,
        speaker_name=player.name,
        content=player_text,
        clock=save.area_snapshot.clock,
    )

    recovered_talkative = _restore_npc_talkative(role, save.area_snapshot.clock)
    action_reaction = ""
    speech_reply = ""
    relation_tag = "met"
    allow_action_repair = True
    allow_speech_repair = True
    scene_events: list[SceneEvent] = []
    knowledge = build_npc_knowledge_snapshot(save, role.role_id)
    if role.talkative_current <= 0:
        action_reaction = f"{role.name} 明显不想继续交谈，只是移开了视线。"
        allow_action_repair = False
        allow_speech_repair = False
    elif player_mentions_unknown_npc(save, role.role_id, player_text):
        action_reaction = f"{role.name} 皱起眉，像是在确认你提到的是谁。"
        speech_reply = npc_guard_reply()
        allow_action_repair = False
        allow_speech_repair = False
    elif req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
                context = _build_npc_prompt_context(role, save.area_snapshot.clock)
                conversation_state = _npc_conversation_state_summary(role)
                default_prompt = (
                    "你要扮演一个NPC与玩家进行单独交互。"
                    "必须保持人设一致，结合历史对话、当前世界时间、玩家动作与检定结果作答。"
                    "你只能基于当前合法世界事实回答；若玩家提到不存在、已失效或不在你知识范围内的人物/区域，明确表示不知道或不确认。"
                    "你只输出JSON，不要输出额外解释。"
                    "JSON schema: {\"action_reaction\":\"...\",\"speech_reply\":\"...\",\"relation_tag\":\"ally|friendly|met|neutral|wary|hostile\"}。"
                    "speech_reply 可以为空；NPC允许只做动作不说话。"
                    "action_reaction 必须始终先写，且至少包含神态+一个可见动作或站位变化，不能只写“显得警惕”“显得冷淡”这种概括。"
                    "如果玩家语言里包含问题、确认句或询问身份/关系/去向，speech_reply 必须直接回答该问题，不能只说“继续”“我在听”。"
                    "如果玩家是在追问你上一轮提到的概念、名词或事件，必须先解释那个概念本身，不能切回你自己的静态喜好。"
                    "\nNPC信息: name=$name, personality=$personality, speaking_style=$speaking_style, "
                    "appearance=$appearance, background=$background, cognition=$cognition, alignment=$alignment, secret=$secret, likes=$likes"
                    "\n当前世界时间: $world_time_text"
                    "\n当前健谈值: $talkative_current / $talkative_maximum"
                    "\n当前会话状态:\n$conversation_state"
                    "\n当前知识边界规则:\n$knowledge_rules"
                    "\n当前可知本地NPC IDs: $known_local_npc_ids"
                    "\n当前不可编造实体 IDs: $forbidden_entity_ids"
                    "\n历史对话(按时间顺序):\n$context"
                    "\n玩家动作: $player_action"
                    "\n玩家语言: $player_speech"
                    "\n玩家检定结果: $action_check_result"
                    "\n玩家刚刚完整输入: $player_text"
                )
                prompt = prompt_table.render(
                    PromptKeys.NPC_CHAT_USER,
                    default_prompt,
                    name=role.name,
                    roleplay_brief=_build_npc_roleplay_brief(role),
                    personality=role.personality,
                    speaking_style=role.speaking_style,
                    appearance=role.appearance,
                    background=role.background,
                    cognition=role.cognition,
                    alignment=role.alignment,
                    secret=role.secret,
                    likes=" / ".join(role.likes) or "无特殊偏好",
                    world_time_text=world_time_text,
                    talkative_current=role.talkative_current,
                    talkative_maximum=role.talkative_maximum,
                    conversation_state=conversation_state,
                    knowledge_rules="\n".join(f"- {item}" for item in knowledge.response_rules),
                    known_local_npc_ids=",".join(knowledge.known_local_npc_ids) or "none",
                    forbidden_entity_ids=",".join(knowledge.forbidden_entity_ids) or "none",
                    context=context,
                    player_action=action_text or "无",
                    player_speech=speech_text or "无",
                    action_check_result=json.dumps(action_check or {"status": "none"}, ensure_ascii=False),
                    player_text=player_text,
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                action_reaction = str(parsed.get("action_reaction") or "").strip()
                speech_reply = str(parsed.get("speech_reply") or "").strip()
                tag = str(parsed.get("relation_tag") or "").strip().lower()
                if tag in {"ally", "friendly", "met", "neutral", "wary", "hostile"}:
                    relation_tag = tag
                forbidden_role_names = [
                    item.name
                    for item in save.role_pool
                    if item.role_id not in knowledge.known_local_npc_ids and item.role_id != role.role_id
                ]
                generated_reply = _compose_npc_reply(action_reaction, speech_reply)
                if any(name and name in generated_reply for name in forbidden_role_names):
                    action_reaction = f"{role.name} 迟疑地眯起眼，显然不打算顺着这个话题说下去。"
                    speech_reply = npc_guard_reply()
                    allow_action_repair = False
                    allow_speech_repair = False
                else:
                    allow_action_repair = False
                    allow_speech_repair = False
                usage = resp.usage
                token_usage_store.add(
                    req.session_id,
                    "chat",
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            except Exception:
                action_reaction, speech_reply, relation_tag = _fallback_npc_reply_parts(role, action_text, speech_text, action_check)
        else:
            action_reaction, speech_reply, relation_tag = _fallback_npc_reply_parts(role, action_text, speech_text, action_check)
    else:
        action_reaction, speech_reply, relation_tag = _fallback_npc_reply_parts(role, action_text, speech_text, action_check)

    action_reaction, speech_reply = _normalize_npc_reply_parts(
        role,
        action_text,
        speech_text,
        action_check,
        action_reaction,
        speech_reply,
        allow_action_repair=allow_action_repair,
        allow_speech_repair=allow_speech_repair,
    )
    action_reaction = _normalize_logged_speaker_content("npc", role.name, action_reaction)
    speech_reply = _normalize_logged_speaker_content("npc", role.name, speech_reply)
    if not action_reaction and not speech_reply:
        action_reaction, speech_reply, relation_tag = _fallback_npc_reply_parts(role, action_text, speech_text, action_check)

    talkative_delta = _npc_talkative_delta(role, action_text, speech_text) if role.talkative_current > 0 else 0
    role.talkative_current = max(0, min(role.talkative_maximum, role.talkative_current + talkative_delta))
    role.last_private_chat_at = _world_clock_iso(save.area_snapshot.clock)
    _update_npc_conversation_state_from_reply(role, speech_reply, action_reaction)
    reply = _compose_npc_reply(action_reaction, speech_reply) or f"{role.name} 没有给出明确回应。"

    _append_npc_dialogue(
        role=role,
        speaker="npc",
        speaker_role_id=role.role_id,
        speaker_name=role.name,
        content=reply,
        clock=save.area_snapshot.clock,
    )
    lower_text = player_text.lower()
    if relation_tag not in {"ally", "friendly", "met", "neutral", "wary", "hostile"}:
        relation_tag = "met"
    if relation_tag == "met" and any(k in lower_text for k in ["谢谢", "thank", "help", "帮忙", "合作"]):
        relation_tag = "friendly"
    elif any(k in lower_text for k in ["威胁", "threat", "滚开", "attack", "抢"]):
        relation_tag = "hostile"
    _upsert_npc_player_relation(role, save.player_static_data.player_id, relation_tag, "对话自动更新关系")
    role.attitude_changes.append(f"{_utc_now()} relation->{relation_tag}")
    if len(role.attitude_changes) > 50:
        role.attitude_changes = role.attitude_changes[-50:]
    role.cognition_changes.append(f"{_utc_now()} 单聊记忆: {player_text[:48]}")
    if len(role.cognition_changes) > 50:
        role.cognition_changes = role.cognition_changes[-50:]
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "npc_chat",
            f"玩家与 {role.name} 对话",
            {
                "npc_role_id": role.role_id,
                "time_spent_min": time_spent_min,
                "talkative_current": role.talkative_current,
                "talkative_recovered": recovered_talkative,
            },
        )
    )
    try:
        from app.services.team_service import apply_team_reactions_in_save

        apply_team_reactions_in_save(
            save,
            session_id=req.session_id,
            trigger_kind="npc_chat",
            player_text=player_text,
            summary=reply,
            exclude_role_ids={role.role_id},
        )
    except Exception:
        pass
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advanced = advance_active_encounter_in_save(save, session_id=req.session_id, minutes_elapsed=time_spent_min, config=req.config)
        if advanced is not None:
            scene_events.append(
                _new_scene_event(
                    "encounter_background",
                    advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                    metadata={"encounter_id": advanced.encounter_id},
                )
            )
    except Exception:
        pass
    save_current(save)
    return NpcChatResponse(
        session_id=req.session_id,
        npc_role_id=role.role_id,
        reply=reply,
        action_reaction=action_reaction,
        speech_reply=speech_reply,
        talkative_current=role.talkative_current,
        talkative_maximum=role.talkative_maximum,
        time_spent_min=time_spent_min,
        dialogue_logs=role.dialogue_logs[-20:],
        scene_events=scene_events,
    )


def upsert_player_relation(session_id: str, role_id: str, relation_tag: str, note: str = "") -> NpcRoleCard:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    player_id = save.player_static_data.player_id
    role.relations = [r for r in role.relations if r.target_role_id != player_id]
    role.relations.append(
        RoleRelation(
            target_role_id=player_id,
            relation_tag=(relation_tag.strip() or "met"),
            note=(note or "").strip(),
        )
    )
    save_current(save)
    return role


def set_role_relation(session_id: str, role_id: str, payload: RoleRelationSetRequest) -> NpcRoleCard:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")

    role.relations = [r for r in role.relations if r.target_role_id != payload.target_role_id]
    role.relations.append(
        RoleRelation(
            target_role_id=payload.target_role_id,
            relation_tag=(payload.relation_tag.strip() or "neutral"),
            note=(payload.note or "").strip(),
        )
    )
    save_current(save)
    return role


def _get_actor_profile(save: SaveFile, actor_role_id: str | None) -> tuple[str, PlayerStaticData]:
    if not actor_role_id or actor_role_id == save.player_static_data.player_id:
        _recompute_player_derived(save.player_static_data)
        return save.player_static_data.player_id, save.player_static_data
    role = next((r for r in save.role_pool if r.role_id == actor_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    _recompute_player_derived(role.profile)
    return role.role_id, role.profile


def _ability_modifier(profile: PlayerStaticData, ability: str) -> int:
    score = getattr(profile.dnd5e_sheet.ability_scores, ability, 10)
    return int((score - 10) // 2)


def _fallback_action_plan(action_type: str, action_prompt: str) -> dict[str, int | bool | str]:
    text = action_prompt.lower()
    ability = "wisdom"
    if any(k in text for k in ["attack", "strike", "hit", "砍", "攻击"]):
        ability = "strength"
    elif any(k in text for k in ["sneak", "dodge", "stealth", "潜行", "闪避"]):
        ability = "dexterity"
    elif any(k in text for k in ["investigate", "analyze", "arcana", "调查", "推理"]):
        ability = "intelligence"
    elif any(k in text for k in ["persuade", "deceive", "intimidate", "说服", "威吓"]):
        ability = "charisma"
    requires_check = action_type in {"attack", "check"}
    return {
        "ability_used": ability,
        "dc": 12,
        "time_spent_min": 5 if action_type != "item_use" else 3,
        "requires_check": requires_check,
    }


def _ai_action_plan(req: ActionCheckRequest) -> dict[str, int | bool | str]:
    if req.config is None:
        return _fallback_action_plan(req.action_type, req.action_prompt)
    api_key = (req.config.openai_api_key or "").strip()
    model = (req.config.model or "").strip()
    if not api_key or not model:
        return _fallback_action_plan(req.action_type, req.action_prompt)

    try:
        default_prompt = (
            "你是跑团行动判定助手。基于玩家行动，返回JSON。"
            "字段: ability_used(strength|dexterity|constitution|intelligence|wisdom|charisma),"
            "dc(5-30),time_spent_min(>=1),requires_check(boolean)。"
            "action_type=attack/check/item_use。"
            "action_type=$action_type, action_prompt=$action_prompt"
        )
        prompt = prompt_table.render(
            "action.plan.user",
            default_prompt,
            action_type=req.action_type,
            action_prompt=req.action_prompt,
        )
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(req.config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("action.plan.system", "你只输出JSON。")},
                {"role": "user", "content": prompt},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        parsed = _extract_json_content(content)
        ability = str(parsed.get("ability_used") or "").strip().lower()
        if ability not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
            ability = "wisdom"
        dc = int(parsed.get("dc") or 12)
        dc = max(5, min(30, dc))
        time_spent = int(parsed.get("time_spent_min") or 5)
        time_spent = max(1, min(180, time_spent))
        requires_check = bool(parsed.get("requires_check"))
        if req.action_type in {"attack", "check"}:
            requires_check = True
        return {"ability_used": ability, "dc": dc, "time_spent_min": time_spent, "requires_check": requires_check}
    except Exception:
        return _fallback_action_plan(req.action_type, req.action_prompt)


def _apply_penalty(profile: PlayerStaticData, rule_key: str, fail_gap: int) -> list[str]:
    effects: list[str] = []
    if rule_key == "hit_points.current":
        hp = profile.dnd5e_sheet.hit_points
        hp_loss = max(1, min(5, fail_gap))
        hp.current = max(0, hp.current - hp_loss)
        effects.append(f"HP -{hp_loss}")
        return effects

    if rule_key == "dnd5e_sheet.speed_ft":
        before = profile.dnd5e_sheet.speed_ft
        loss = max(1, min(5, fail_gap))
        profile.dnd5e_sheet.speed_ft = max(5, before - loss)
        effects.append(f"Speed -{loss}ft")
        return effects

    # Unknown rule keys are ignored to keep runtime stable.
    return effects


def _suggest_relation_tag(req: ActionCheckRequest, success: bool, critical: str) -> str | None:
    text = req.action_prompt.lower()
    if "npc_id=" not in text:
        return None

    if req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                default_prompt = (
                    "基于互动行为和结果，输出JSON: {\"relation_tag\":\"ally|friendly|neutral|wary|hostile\"}。"
                    "action_prompt=$action_prompt; success=$success; critical=$critical"
                )
                prompt = prompt_table.render(
                    "relation.tag.user",
                    default_prompt,
                    action_prompt=req.action_prompt,
                    success=success,
                    critical=critical,
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("relation.tag.system", "你只输出JSON。")},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                tag = str(parsed.get("relation_tag") or "").strip().lower()
                if tag in {"ally", "friendly", "neutral", "wary", "hostile"}:
                    return tag
            except Exception:
                pass

    if critical == "critical_success":
        return "ally"
    if critical == "critical_failure":
        return "hostile"
    return "friendly" if success else "wary"


def action_check(req: ActionCheckRequest) -> ActionCheckResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    actor_role_id, profile = _get_actor_profile(save, req.actor_role_id)
    plan = _ai_action_plan(req)
    ability = str(plan["ability_used"])
    dc = int(plan["dc"])
    time_spent_min = int(plan["time_spent_min"])
    requires_check = bool(plan["requires_check"])

    dice_roll: int | None = None
    total_score: int | None = None
    critical = "none"
    success = True
    applied_effects: list[str] = []
    ability_modifier = _ability_modifier(profile, ability)

    if requires_check:
        dice_roll = req.forced_dice_roll if req.forced_dice_roll is not None else random.randint(1, 20)
        total_score = dice_roll + ability_modifier
        if dice_roll == 1:
            critical = "critical_failure"
            success = False
        elif dice_roll == 20:
            critical = "critical_success"
            success = True
        else:
            success = total_score >= dc

    if not success:
        fail_gap = max(1, dc - (total_score if total_score is not None else dc))
        rule_key = _ACTION_PENALTY_RULES.get(req.action_type, "hit_points.current")
        applied_effects.extend(_apply_penalty(profile, rule_key, fail_gap))

    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "action_check",
            f"行为检定: {req.action_type} | {'成功' if success else '失败'} | 耗时 {time_spent_min} 分钟",
            {
                "actor_role_id": actor_role_id,
                "action_type": req.action_type,
                "dc": dc,
                "time_spent_min": time_spent_min,
                "success": success,
            },
        )
    )
    save_current(save)

    narrative = (
        f"{profile.name} 执行了行动，耗时 {time_spent_min} 分钟。"
        f"{'检定成功。' if success else '检定失败，出现负面后果。'}"
    )
    scene_events: list[SceneEvent] = []
    if critical == "critical_success":
        narrative = f"{profile.name} 掷出天然20，行动大成功！耗时 {time_spent_min} 分钟。"
    elif critical == "critical_failure":
        narrative = f"{profile.name} 掷出天然1，行动大失败。耗时 {time_spent_min} 分钟。"

    relation_tag = _suggest_relation_tag(req, success, critical)
    if relation_tag is not None and "npc_id=" in req.action_prompt:
        try:
            npc_id = req.action_prompt.split("npc_id=", 1)[1].split(";", 1)[0].strip()
            if npc_id:
                role = next((r for r in save.role_pool if r.role_id == npc_id), None)
                if role is not None:
                    _upsert_npc_player_relation(role, save.player_static_data.player_id, relation_tag, "行动检定自动更新关系")
                    role.attitude_changes.append(f"{_utc_now()} action->{relation_tag}")
                    if len(role.attitude_changes) > 50:
                        role.attitude_changes = role.attitude_changes[-50:]
        except Exception:
            pass
    try:
        from app.services.team_service import apply_team_reactions_in_save

        apply_team_reactions_in_save(
            save,
            session_id=req.session_id,
            trigger_kind="action_check",
            player_text=req.action_prompt,
            summary=narrative,
            exclude_role_ids=({actor_role_id} if actor_role_id != save.player_static_data.player_id else None),
        )
    except Exception:
        pass
    if actor_role_id == save.player_static_data.player_id:
        scene_events = advance_public_scene_in_save(
            save,
            req.session_id,
            req.action_prompt,
            narrative,
            req.config,
        )
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advanced = advance_active_encounter_in_save(save, session_id=req.session_id, minutes_elapsed=time_spent_min, config=req.config)
        if advanced is not None:
            scene_events.append(
                _new_scene_event(
                    "encounter_background",
                    advanced.latest_outcome_summary or advanced.scene_summary or advanced.description,
                    metadata={"encounter_id": advanced.encounter_id},
                )
            )
    except Exception:
        pass
    save_current(save)

    return ActionCheckResponse(
        session_id=req.session_id,
        actor_role_id=actor_role_id,
        action_type=req.action_type,
        requires_check=requires_check,
        ability_used=ability,  # type: ignore[arg-type]
        ability_modifier=ability_modifier,
        dc=dc,
        dice_roll=dice_roll,
        total_score=total_score,
        success=success,
        critical=critical,  # type: ignore[arg-type]
        time_spent_min=time_spent_min,
        narrative=narrative,
        applied_effects=applied_effects,
        relation_tag_suggestion=relation_tag,
        scene_events=scene_events,
    )


def move_to_sub_zone(req: AreaMoveSubZoneRequest) -> AreaMoveResult:
    _attempt_escape_for_move(
        session_id=req.session_id,
        target_zone_id=None,
        target_sub_zone_id=req.to_sub_zone_id,
        config=req.config,
    )
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)
    snap = save.area_snapshot
    if snap.clock is None:
        raise ValueError("AREA_CLOCK_NOT_INIT")

    to_sub = next((s for s in snap.sub_zones if s.sub_zone_id == req.to_sub_zone_id), None)
    if to_sub is None:
        raise KeyError("AREA_SUB_ZONE_NOT_FOUND")
    if not to_sub.key_interactions:
        to_sub.key_interactions.append(
            AreaInteraction(
                interaction_id=f"int_{to_sub.zone_id}_observe",
                name="观察周边",
                type="scene",
                generated_mode="pre",
                placeholder=True,
            )
        )
    if not to_sub.npcs:
        zone_name = next((z.name for z in snap.zones if z.zone_id == to_sub.zone_id), to_sub.zone_id)
        npc_id, npc_name = _build_npc_identity(zone_name, to_sub.name, to_sub.sub_zone_id, 0)
        to_sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
    to_coord = to_sub.coord

    from_sub = next((s for s in snap.sub_zones if s.sub_zone_id == snap.current_sub_zone_id), None)
    if from_sub is not None:
        from_point = AreaMovePoint(zone_id=from_sub.zone_id, sub_zone_id=from_sub.sub_zone_id, coord=from_sub.coord)
    else:
        from_zone = next((z for z in snap.zones if z.zone_id == (snap.current_zone_id or to_sub.zone_id)), None)
        from_center = from_zone.center if from_zone is not None else Coord3D(x=0, y=0, z=0)
        from_point = AreaMovePoint(zone_id=(from_zone.zone_id if from_zone else to_sub.zone_id), coord=from_center)

    to_point = AreaMovePoint(zone_id=to_sub.zone_id, sub_zone_id=to_sub.sub_zone_id, coord=to_coord)
    if from_point.sub_zone_id == to_point.sub_zone_id:
        return AreaMoveResult(
            ok=True,
            from_point=from_point,
            to_point=to_point,
            distance_m=0.0,
            duration_min=0,
            clock_delta_min=0,
            clock_after=snap.clock,
            movement_feedback=f"你已在【{to_sub.name}】。",
        )
    distance_m = _distance3d_m(from_point.coord, to_point.coord)
    speed_mph = max(1, save.player_static_data.move_speed_mph)
    duration_min = max(1, ceil((distance_m / speed_mph) * 60.0))
    clock_after = _advance_clock(snap.clock, duration_min)

    snap.current_zone_id = to_sub.zone_id
    snap.current_sub_zone_id = to_sub.sub_zone_id
    snap.clock = clock_after
    save.map_snapshot.player_position = Position(
        x=int(round(to_coord.x)),
        y=int(round(to_coord.y)),
        z=int(round(to_coord.z)),
        zone_id=to_sub.zone_id,
    )
    save.player_runtime_data.current_position = save.map_snapshot.player_position
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_move",
            f"移动到子区块【{to_sub.name}】，耗时 {duration_min} 分钟",
            {
                "to_sub_zone_id": to_sub.sub_zone_id,
                "to_zone_id": to_sub.zone_id,
                "duration_min": duration_min,
                "distance_m": round(distance_m, 3),
            },
        )
    )
    save_current(save)

    movement_feedback = f"你移动到【{to_sub.name}】，花费 {duration_min} 分钟。"
    if req.config is not None:
        try:
            api_key = (req.config.openai_api_key or "").strip()
            model = (req.config.model or "").strip()
            if api_key and model:
                client = OpenAI(api_key=api_key)
                default_prompt = (
                    "你是跑团GM。基于以下移动结果写一段50-120字叙事。"
                    "不要编号，不要选项。"
                    "from=$from_id, to=$to_name, distance_m=$distance_m, duration_min=$duration_min"
                )
                prompt = prompt_table.render(
                    "move.subzone.user",
                    default_prompt,
                    from_id=(from_point.sub_zone_id or from_point.zone_id),
                    to_name=to_sub.name,
                    distance_m=round(distance_m, 2),
                    duration_min=duration_min,
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                txt = (resp.choices[0].message.content or "").strip()
                if txt:
                    movement_feedback = txt
        except Exception:
            pass
    try:
        from app.services.team_service import apply_team_reactions_in_save, sync_team_members_with_player_in_save

        sync_team_members_with_player_in_save(save)
        apply_team_reactions_in_save(
            save,
            session_id=req.session_id,
            trigger_kind="sub_zone_move",
            summary=movement_feedback,
        )
    except Exception:
        pass
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advance_active_encounter_in_save(save, session_id=req.session_id, minutes_elapsed=duration_min, config=req.config)
    except Exception:
        pass
    save_current(save)

    return AreaMoveResult(
        ok=True,
        from_point=from_point,
        to_point=to_point,
        distance_m=round(distance_m, 3),
        duration_min=duration_min,
        clock_delta_min=duration_min,
        clock_after=clock_after,
        movement_feedback=movement_feedback,
    )


def discover_interactions(req: AreaDiscoverInteractionsRequest) -> AreaDiscoverInteractionsResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)
    snap = save.area_snapshot
    target = next((s for s in snap.sub_zones if s.sub_zone_id == req.sub_zone_id), None)
    if target is None:
        raise KeyError("AREA_SUB_ZONE_NOT_FOUND")

    generated_raw: list[dict[str, str]]
    if req.config is not None:
        try:
            generated_raw = _ai_discover_interactions(req.config, target, req.intent)
        except Exception:
            generated_raw = [{"name": f"调查：{req.intent[:12]}", "type": "item", "status": "ready"}]
    else:
        generated_raw = [{"name": f"调查：{req.intent[:12]}", "type": "item", "status": "ready"}]

    existing_ids = {it.interaction_id for it in target.key_interactions}
    existing_names = {it.name.strip().lower() for it in target.key_interactions}
    deduped: list[AreaInteraction] = []
    for idx, item in enumerate(generated_raw):
        name = item["name"].strip()
        name_key = name.lower()
        if not name or name_key in existing_names:
            continue
        candidate_id = f"int_{target.sub_zone_id}_{int(datetime.now(timezone.utc).timestamp())}_{idx}"
        while candidate_id in existing_ids:
            candidate_id = f"{candidate_id}_x"
        interaction = AreaInteraction(
            interaction_id=candidate_id,
            name=name,
            type=_coerce_interaction_type(item.get("type", "item")),  # pyright: ignore[reportArgumentType]
            status=_coerce_interaction_status(item.get("status", "ready")),  # pyright: ignore[reportArgumentType]
            generated_mode="instant",
            placeholder=True,
        )
        deduped.append(interaction)
        existing_ids.add(candidate_id)
        existing_names.add(name_key)
        if len(deduped) >= 3:
            break

    if not deduped:
        deduped = [
            AreaInteraction(
                interaction_id=f"int_{target.sub_zone_id}_{int(datetime.now(timezone.utc).timestamp())}",
                name=f"调查：{req.intent[:12]}",
                type="item",
                status="ready",
                generated_mode="instant",
                placeholder=True,
            )
        ]

    target.key_interactions.extend(deduped)
    if snap.clock is not None:
        snap.clock = _advance_clock(snap.clock, 1)

    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_refresh",
            f"在【{target.name}】发现新的可交互项",
            {
                "sub_zone_id": target.sub_zone_id,
                "count": len(deduped),
            },
        )
    )
    save_current(save)
    return AreaDiscoverInteractionsResponse(ok=True, generated_mode="instant", new_interactions=deduped)


def execute_interaction(req: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)

    found = False
    for sub in save.area_snapshot.sub_zones:
        if any(it.interaction_id == req.interaction_id for it in sub.key_interactions):
            found = True
            break
    if not found:
        raise KeyError("AREA_INVALID_INTERACTION")

    if save.area_snapshot.clock is not None:
        save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, 1)
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_interaction_placeholder",
            f"触发交互 {req.interaction_id}（占位）",
            {"interaction_id": req.interaction_id},
        )
    )
    save_current(save)
    return AreaExecuteInteractionResponse(ok=True, status="placeholder", message="待开发")


def describe_behavior(session_id: str, movement_log: MovementLog, config: ChatConfig) -> BehaviorDescribeResponse:
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIBehaviorError("缺少有效的模型配置或 API Key")

    try:
        client = OpenAI(api_key=api_key)
        default_prompt = (
            "你是跑团GM。"
            "请根据移动日志生成一段简短但有氛围感的叙事反馈，100-180字。"
            "你是故事叙述者，默认不要给编号选项，除非玩家明确要求给出选项。"
            "必须优先使用区块名称，不要使用 zone_xxx 这类内部ID。"
            "日志JSON如下："
            "$movement_log_json"
        )
        prompt = prompt_table.render(
            "behavior.describe.user",
            default_prompt,
            movement_log_json=json.dumps(movement_log.model_dump(mode="json"), ensure_ascii=False),
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            session_id,
            "movement_narration",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        narration = (resp.choices[0].message.content or "").strip()
        if not narration:
            raise AIBehaviorError("AI 未返回叙事文本")
        return BehaviorDescribeResponse(session_id=session_id, narration=narration)
    except AIBehaviorError:
        raise
    except Exception as exc:
        raise AIBehaviorError(str(exc)) from exc


