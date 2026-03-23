from __future__ import annotations

from copy import deepcopy
from typing import Any


BattleMonsterTemplatePayload = dict[str, Any]


MONSTER_TEMPLATES: dict[str, BattleMonsterTemplatePayload] = {
    "rogue": {
        "template_id": "rogue",
        "name": "流氓",
        "role_kind": "skirmisher",
        "level_hint": 1,
        "max_hp": 12,
        "armor_class": 12,
        "speed": 6,
        "attack_bonus": 3,
        "damage_profile": {"dice": "1d6", "damage_type": "bludgeoning", "flat_bonus": 1},
        "ability_modifiers": {"strength": 1, "dexterity": 2, "constitution": 1, "intelligence": 0, "wisdom": 0, "charisma": 0},
        "saving_throw_bonuses": {"strength": 1, "dexterity": 2, "constitution": 1, "intelligence": 0, "wisdom": 0, "charisma": 0},
        "feature_tags": ["aggressive", "street"],
        "ai_style": "rush_target",
    },
    "brute": {
        "template_id": "brute",
        "name": "暴徒",
        "role_kind": "brute",
        "level_hint": 2,
        "max_hp": 18,
        "armor_class": 11,
        "speed": 5,
        "attack_bonus": 4,
        "damage_profile": {"dice": "1d8", "damage_type": "bludgeoning", "flat_bonus": 2},
        "ability_modifiers": {"strength": 3, "dexterity": 0, "constitution": 2, "intelligence": -1, "wisdom": 0, "charisma": 0},
        "saving_throw_bonuses": {"strength": 3, "dexterity": 0, "constitution": 2, "intelligence": -1, "wisdom": 0, "charisma": 0},
        "feature_tags": ["heavy", "aggressive"],
        "ai_style": "hold_line",
    },
    "wild_dog": {
        "template_id": "wild_dog",
        "name": "野狗",
        "role_kind": "beast",
        "level_hint": 1,
        "max_hp": 9,
        "armor_class": 12,
        "speed": 8,
        "attack_bonus": 3,
        "damage_profile": {"dice": "1d4", "damage_type": "piercing", "flat_bonus": 2},
        "ability_modifiers": {"strength": 1, "dexterity": 2, "constitution": 1, "intelligence": -3, "wisdom": 1, "charisma": -3},
        "saving_throw_bonuses": {"strength": 1, "dexterity": 2, "constitution": 1, "intelligence": -3, "wisdom": 1, "charisma": -3},
        "feature_tags": ["pack_hunter", "fast"],
        "ai_style": "harry_weakest",
    },
    "knife_thug": {
        "template_id": "knife_thug",
        "name": "持刀混混",
        "role_kind": "skirmisher",
        "level_hint": 2,
        "max_hp": 14,
        "armor_class": 13,
        "speed": 6,
        "attack_bonus": 4,
        "damage_profile": {"dice": "1d6", "damage_type": "slashing", "flat_bonus": 2},
        "ability_modifiers": {"strength": 1, "dexterity": 3, "constitution": 1, "intelligence": 0, "wisdom": 0, "charisma": 0},
        "saving_throw_bonuses": {"strength": 1, "dexterity": 3, "constitution": 1, "intelligence": 0, "wisdom": 0, "charisma": 0},
        "feature_tags": ["armed", "dirty_fighter"],
        "ai_style": "rush_target",
    },
    "rogue_guard": {
        "template_id": "rogue_guard",
        "name": "失控卫兵",
        "role_kind": "support",
        "level_hint": 2,
        "max_hp": 16,
        "armor_class": 14,
        "speed": 6,
        "attack_bonus": 4,
        "damage_profile": {"dice": "1d8", "damage_type": "bludgeoning", "flat_bonus": 1},
        "ability_modifiers": {"strength": 2, "dexterity": 1, "constitution": 2, "intelligence": 0, "wisdom": 1, "charisma": 0},
        "saving_throw_bonuses": {"strength": 2, "dexterity": 1, "constitution": 2, "intelligence": 0, "wisdom": 1, "charisma": 0},
        "feature_tags": ["disciplined", "shield"],
        "ai_style": "protect_pack",
    },
}


TEMPLATE_GROUPS: dict[str, list[tuple[str, int]]] = {
    "流氓小队": [("rogue", 2), ("knife_thug", 1)],
    "暴徒小队": [("brute", 2), ("rogue", 1)],
    "野狗群": [("wild_dog", 3)],
    "持刀混混": [("knife_thug", 2)],
    "失控卫兵": [("rogue_guard", 2), ("brute", 1)],
}


def list_template_group_names() -> list[str]:
    return list(TEMPLATE_GROUPS.keys())


def get_template_payload(template_id: str) -> BattleMonsterTemplatePayload:
    payload = MONSTER_TEMPLATES.get(template_id)
    if payload is None:
        raise KeyError("BATTLE_TEMPLATE_NOT_FOUND")
    return deepcopy(payload)


def build_group_payloads(group_name: str) -> list[BattleMonsterTemplatePayload]:
    rows = TEMPLATE_GROUPS.get(group_name)
    if rows is None:
        raise KeyError("BATTLE_TEMPLATE_GROUP_NOT_FOUND")
    payloads: list[BattleMonsterTemplatePayload] = []
    for template_id, count in rows:
        for _ in range(max(1, int(count))):
            payloads.append(get_template_payload(template_id))
    return payloads


def fallback_group_for_ai(scale: str, strength: str) -> str:
    if scale == "single":
        return "持刀混混" if strength == "strong" else "失控卫兵" if strength == "standard" else "流氓小队"
    if strength == "weak":
        return "野狗群"
    if strength == "strong":
        return "暴徒小队"
    return "失控卫兵"
