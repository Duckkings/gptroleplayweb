from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.core.storage import storage_state
from app.models.schemas import EquipmentDefinition, InteractableTemplate, InventoryItem, ItemDefinition


ITEM_DEFINITIONS_FILE = "item_definitions.csv"
EQUIPMENT_DEFINITIONS_FILE = "equipment_definitions.csv"
INTERACTABLE_TEMPLATES_FILE = "interactable_templates.csv"

ITEM_DEFINITION_COLUMNS = [
    "definition_id",
    "name",
    "item_kind",
    "sub_kind",
    "description",
    "rarity",
    "weight",
    "value",
    "stackable",
    "max_stack",
    "use_tags",
    "interaction_tags",
    "combat_tags",
    "effect_prompt_hint",
]

EQUIPMENT_DEFINITION_COLUMNS = [
    "definition_id",
    "name",
    "equipment_kind",
    "slot_type",
    "damage_dice",
    "damage_type",
    "attack_bonus",
    "armor_bonus",
    "range_normal",
    "range_long",
    "two_handed",
    "light",
    "heavy",
    "thrown",
    "finesse",
    "ammunition",
    "description",
    "rarity",
    "weight",
    "value",
]

INTERACTABLE_TEMPLATE_COLUMNS = [
    "template_id",
    "name",
    "interactable_kind",
    "description",
    "allowed_actions",
    "initial_state_tags",
    "loot_mode",
    "allowed_item_tags",
    "allowed_definition_ids",
    "can_pick_up",
    "can_drop_into",
    "can_lock",
    "can_break",
    "can_trigger",
]


@dataclass
class TemplateLibraryBundle:
    item_definitions: list[ItemDefinition]
    equipment_definitions: list[EquipmentDefinition]
    interactable_templates: list[InteractableTemplate]


def _template_library_dir() -> Path:
    root = storage_state.save_path.parent
    directory = root / "template-library"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return default


def _parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError:
        return default


def _parse_tags(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: str(value or "") for key, value in row.items()} for row in reader]


def _default_item_rows() -> list[dict[str, object]]:
    return [
        {
            "definition_id": "healing_potion",
            "name": "治疗药水",
            "item_kind": "consumable",
            "sub_kind": "healing",
            "description": "一瓶常见的治疗药水，喝下后能恢复少量体力。",
            "rarity": "common",
            "weight": 0.5,
            "value": 50,
            "stackable": True,
            "max_stack": 10,
            "use_tags": "heal|drink",
            "interaction_tags": "pickup|use|give|drop",
            "combat_tags": "healing",
            "effect_prompt_hint": "恢复少量生命值。",
        },
        {
            "definition_id": "torch",
            "name": "火把",
            "item_kind": "tool",
            "sub_kind": "light",
            "description": "普通火把，可用于照明和点燃易燃物。",
            "rarity": "common",
            "weight": 1.0,
            "value": 2,
            "stackable": True,
            "max_stack": 5,
            "use_tags": "ignite|light",
            "interaction_tags": "pickup|use|drop|give",
            "combat_tags": "fire",
            "effect_prompt_hint": "照明、点火、制造轻微火焰威胁。",
        },
    ]


def _default_equipment_rows() -> list[dict[str, object]]:
    return [
        {
            "definition_id": "rusty_sword",
            "name": "锈剑",
            "equipment_kind": "weapon",
            "slot_type": "weapon",
            "damage_dice": "1d8",
            "damage_type": "slashing",
            "attack_bonus": 0,
            "armor_bonus": 0,
            "range_normal": 1,
            "range_long": 1,
            "two_handed": False,
            "light": False,
            "heavy": False,
            "thrown": False,
            "finesse": False,
            "ammunition": False,
            "description": "一把缺乏保养的旧剑，杀伤力尚可。",
            "rarity": "common",
            "weight": 3.0,
            "value": 8,
        },
        {
            "definition_id": "leather_armor",
            "name": "皮甲",
            "equipment_kind": "armor",
            "slot_type": "armor",
            "damage_dice": "",
            "damage_type": "none",
            "attack_bonus": 0,
            "armor_bonus": 2,
            "range_normal": 0,
            "range_long": 0,
            "two_handed": False,
            "light": False,
            "heavy": False,
            "thrown": False,
            "finesse": False,
            "ammunition": False,
            "description": "轻便的皮革护甲，适合普通冒险者。",
            "rarity": "common",
            "weight": 5.0,
            "value": 10,
        },
        {
            "definition_id": "wooden_shield",
            "name": "木盾",
            "equipment_kind": "shield",
            "slot_type": "shield",
            "damage_dice": "",
            "damage_type": "none",
            "attack_bonus": 0,
            "armor_bonus": 1,
            "range_normal": 0,
            "range_long": 0,
            "two_handed": False,
            "light": False,
            "heavy": False,
            "thrown": False,
            "finesse": False,
            "ammunition": False,
            "description": "一面结实但普通的木盾。",
            "rarity": "common",
            "weight": 4.0,
            "value": 6,
        },
    ]


def _default_interactable_rows() -> list[dict[str, object]]:
    return [
        {
            "template_id": "generic_scene_object",
            "name": "普通场景物",
            "interactable_kind": "scene",
            "description": "默认的场景可交互物模板。",
            "allowed_actions": "inspect",
            "initial_state_tags": "normal",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": False,
            "can_lock": False,
            "can_break": False,
            "can_trigger": False,
        },
        {
            "template_id": "item_proxy",
            "name": "地面物品",
            "interactable_kind": "item_proxy",
            "description": "代表掉落在场景中的单个物品。",
            "allowed_actions": "inspect|pickup",
            "initial_state_tags": "visible",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": True,
            "can_drop_into": False,
            "can_lock": False,
            "can_break": False,
            "can_trigger": False,
        },
        {
            "template_id": "basic_container",
            "name": "基础容器",
            "interactable_kind": "container",
            "description": "可以开启、搜索并持久化掉落内容的容器。",
            "allowed_actions": "inspect|open|search|take_all|put_in",
            "initial_state_tags": "closed",
            "loot_mode": "ai_first_open",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": True,
            "can_lock": True,
            "can_break": True,
            "can_trigger": False,
        },
        {
            "template_id": "door",
            "name": "门",
            "interactable_kind": "door",
            "description": "门、栅栏或通路阻挡物。",
            "allowed_actions": "inspect|open|close|lock|unlock|enter|force_open",
            "initial_state_tags": "closed",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": False,
            "can_lock": True,
            "can_break": True,
            "can_trigger": False,
        },
        {
            "template_id": "mechanism",
            "name": "机关",
            "interactable_kind": "mechanism",
            "description": "可触发、重置或解除的机关。",
            "allowed_actions": "inspect|trigger|reset|disable",
            "initial_state_tags": "idle",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": False,
            "can_lock": False,
            "can_break": True,
            "can_trigger": True,
        },
        {
            "template_id": "hazard",
            "name": "危险物",
            "interactable_kind": "hazard",
            "description": "可观察、解除、利用或引燃的危险场景物。",
            "allowed_actions": "inspect|trigger|disarm|exploit|ignite|push_into",
            "initial_state_tags": "active",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": False,
            "can_lock": False,
            "can_break": True,
            "can_trigger": True,
        },
        {
            "template_id": "clue",
            "name": "线索",
            "interactable_kind": "clue",
            "description": "可被收集、标记或展示给 NPC 的线索对象。",
            "allowed_actions": "inspect|collect_evidence|mark|show_to_npc",
            "initial_state_tags": "visible",
            "loot_mode": "none",
            "allowed_item_tags": "",
            "allowed_definition_ids": "",
            "can_pick_up": False,
            "can_drop_into": False,
            "can_lock": False,
            "can_break": False,
            "can_trigger": False,
        },
    ]


def ensure_template_library_files() -> Path:
    directory = _template_library_dir()
    item_path = directory / ITEM_DEFINITIONS_FILE
    equipment_path = directory / EQUIPMENT_DEFINITIONS_FILE
    interactable_path = directory / INTERACTABLE_TEMPLATES_FILE
    if not item_path.exists():
        _write_rows(item_path, ITEM_DEFINITION_COLUMNS, _default_item_rows())
    if not equipment_path.exists():
        _write_rows(equipment_path, EQUIPMENT_DEFINITION_COLUMNS, _default_equipment_rows())
    if not interactable_path.exists():
        _write_rows(interactable_path, INTERACTABLE_TEMPLATE_COLUMNS, _default_interactable_rows())
    return directory


def _load_item_definitions() -> list[ItemDefinition]:
    rows = _read_rows(_template_library_dir() / ITEM_DEFINITIONS_FILE)
    items: list[ItemDefinition] = []
    for row in rows:
        items.append(
            ItemDefinition(
                definition_id=row["definition_id"].strip(),
                name=row["name"].strip() or row["definition_id"].strip(),
                item_kind=row["item_kind"].strip() or "misc",
                sub_kind=row["sub_kind"].strip(),
                description=row["description"].strip(),
                rarity=row["rarity"].strip() or "common",
                weight=_parse_float(row["weight"]),
                value=_parse_int(row["value"]),
                stackable=_parse_bool(row["stackable"]),
                max_stack=max(1, _parse_int(row["max_stack"], 1)),
                use_tags=_parse_tags(row["use_tags"]),
                interaction_tags=_parse_tags(row["interaction_tags"]),
                combat_tags=_parse_tags(row["combat_tags"]),
                effect_prompt_hint=row["effect_prompt_hint"].strip(),
            )
        )
    return items


def _load_equipment_definitions() -> list[EquipmentDefinition]:
    rows = _read_rows(_template_library_dir() / EQUIPMENT_DEFINITIONS_FILE)
    items: list[EquipmentDefinition] = []
    for row in rows:
        items.append(
            EquipmentDefinition(
                definition_id=row["definition_id"].strip(),
                name=row["name"].strip() or row["definition_id"].strip(),
                equipment_kind=(row["equipment_kind"].strip() or "weapon"),  # type: ignore[arg-type]
                slot_type=(row["slot_type"].strip() or "weapon"),  # type: ignore[arg-type]
                damage_dice=row["damage_dice"].strip(),
                damage_type=row["damage_type"].strip() or "bludgeoning",
                attack_bonus=_parse_int(row["attack_bonus"]),
                armor_bonus=_parse_int(row["armor_bonus"]),
                range_normal=_parse_int(row["range_normal"]),
                range_long=_parse_int(row["range_long"]),
                two_handed=_parse_bool(row["two_handed"]),
                light=_parse_bool(row["light"]),
                heavy=_parse_bool(row["heavy"]),
                thrown=_parse_bool(row["thrown"]),
                finesse=_parse_bool(row["finesse"]),
                ammunition=_parse_bool(row["ammunition"]),
                description=row["description"].strip(),
                rarity=row["rarity"].strip() or "common",
                weight=_parse_float(row["weight"]),
                value=_parse_int(row["value"]),
            )
        )
    return items


def _load_interactable_templates() -> list[InteractableTemplate]:
    rows = _read_rows(_template_library_dir() / INTERACTABLE_TEMPLATES_FILE)
    items: list[InteractableTemplate] = []
    for row in rows:
        items.append(
            InteractableTemplate(
                template_id=row["template_id"].strip(),
                name=row["name"].strip() or row["template_id"].strip(),
                interactable_kind=(row["interactable_kind"].strip() or "scene"),  # type: ignore[arg-type]
                description=row["description"].strip(),
                allowed_actions=_parse_tags(row["allowed_actions"]),
                initial_state_tags=_parse_tags(row["initial_state_tags"]),
                loot_mode=(row["loot_mode"].strip() or "none"),  # type: ignore[arg-type]
                allowed_item_tags=_parse_tags(row["allowed_item_tags"]),
                allowed_definition_ids=_parse_tags(row["allowed_definition_ids"]),
                can_pick_up=_parse_bool(row["can_pick_up"]),
                can_drop_into=_parse_bool(row["can_drop_into"]),
                can_lock=_parse_bool(row["can_lock"]),
                can_break=_parse_bool(row["can_break"]),
                can_trigger=_parse_bool(row["can_trigger"]),
            )
        )
    return items


def load_template_library() -> TemplateLibraryBundle:
    ensure_template_library_files()
    return TemplateLibraryBundle(
        item_definitions=_load_item_definitions(),
        equipment_definitions=_load_equipment_definitions(),
        interactable_templates=_load_interactable_templates(),
    )


def get_template_library_status() -> dict[str, object]:
    directory = ensure_template_library_files()
    library = load_template_library()
    fill_marker = directory / ".fill-status.json"
    last_filled_at = ""
    if fill_marker.exists():
        try:
            import json

            payload = json.loads(fill_marker.read_text(encoding="utf-8"))
            last_filled_at = str(payload.get("last_filled_at") or "")
        except Exception:
            last_filled_at = ""
    return {
        "template_dir": str(directory),
        "item_definition_count": len(library.item_definitions),
        "equipment_definition_count": len(library.equipment_definitions),
        "interactable_template_count": len(library.interactable_templates),
        "last_filled_at": last_filled_at or None,
    }


def _write_fill_status() -> None:
    import json
    from datetime import datetime, timezone

    marker = _template_library_dir() / ".fill-status.json"
    marker.write_text(
        json.dumps({"last_filled_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mark_template_library_filled() -> None:
    ensure_template_library_files()
    _write_fill_status()


def _normalize_legacy_definition_id(item: InventoryItem) -> str:
    if item.item_type in {"weapon", "armor", "shield"} or item.slot_type in {"weapon", "armor"}:
        return f"legacy_{item.slot_type}_{item.name.strip().lower().replace(' ', '_') or item.item_id}"
    return f"legacy_{item.item_type.strip().lower().replace(' ', '_') or 'misc'}_{item.name.strip().lower().replace(' ', '_') or item.item_id}"


def ensure_definition_for_inventory_item(item: InventoryItem) -> str:
    ensure_template_library_files()
    definition_id = _normalize_legacy_definition_id(item)
    if item.slot_type in {"weapon", "armor"}:
        path = _template_library_dir() / EQUIPMENT_DEFINITIONS_FILE
        rows = _read_rows(path)
        if any((row.get("definition_id") or "").strip() == definition_id for row in rows):
            return definition_id
        rows.append(
            {
                "definition_id": definition_id,
                "name": item.name,
                "equipment_kind": ("weapon" if item.slot_type == "weapon" else "armor"),
                "slot_type": item.slot_type,
                "damage_dice": ("1d8" if item.slot_type == "weapon" else ""),
                "damage_type": (item.item_type if item.slot_type == "weapon" else "none"),
                "attack_bonus": item.attack_bonus,
                "armor_bonus": item.armor_bonus,
                "range_normal": 1,
                "range_long": 1,
                "two_handed": False,
                "light": False,
                "heavy": False,
                "thrown": False,
                "finesse": False,
                "ammunition": False,
                "description": item.description,
                "rarity": item.rarity,
                "weight": item.weight,
                "value": item.value,
            }
        )
        _write_rows(path, EQUIPMENT_DEFINITION_COLUMNS, rows)
        return definition_id
    path = _template_library_dir() / ITEM_DEFINITIONS_FILE
    rows = _read_rows(path)
    if any((row.get("definition_id") or "").strip() == definition_id for row in rows):
        return definition_id
    rows.append(
        {
            "definition_id": definition_id,
            "name": item.name,
            "item_kind": item.item_type or "misc",
            "sub_kind": "",
            "description": item.description,
            "rarity": item.rarity,
            "weight": item.weight,
            "value": item.value,
            "stackable": item.quantity > 1,
            "max_stack": max(1, item.quantity),
            "use_tags": "",
            "interaction_tags": "pickup|use|drop|give",
            "combat_tags": "",
            "effect_prompt_hint": item.effect,
        }
    )
    _write_rows(path, ITEM_DEFINITION_COLUMNS, rows)
    return definition_id


def infer_interactable_template_id(name: str, interaction_type: str) -> str:
    clean = (name or "").strip()
    lowered = clean.lower()
    if interaction_type == "item":
        return "item_proxy"
    if any(token in lowered for token in ["门", "gate", "door", "入口"]):
        return "door"
    if any(token in lowered for token in ["箱", "柜", "bag", "chest", "container", "抽屉"]):
        return "basic_container"
    if any(token in lowered for token in ["机关", "lever", "switch", "按钮"]):
        return "mechanism"
    if any(token in lowered for token in ["陷阱", "hazard", "火焰", "毒雾", "危险"]):
        return "hazard"
    if any(token in lowered for token in ["线索", "痕迹", "证据", "clue"]):
        return "clue"
    return "generic_scene_object"
