from __future__ import annotations

from app.models.schemas import InventoryItem, SaveFile
from app.services.item_instance_service import ensure_item_system, resolve_owner_instances
from app.services.item_template_service import load_template_library


def projected_player_inventory(save: SaveFile) -> list[InventoryItem]:
    ensure_item_system(save)
    return list(save.player_static_data.dnd5e_sheet.backpack.items)


def projected_role_inventory(save: SaveFile, role_id: str) -> list[InventoryItem]:
    ensure_item_system(save)
    role = next((item for item in save.role_pool if item.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return list(role.profile.dnd5e_sheet.backpack.items)


def resolve_combat_inventory_projection(save: SaveFile, *, owner_kind: str, owner_id: str) -> tuple[list[str], list[InventoryItem]]:
    ensure_item_system(save)
    instance_ids = [item.item_instance_id for item in resolve_owner_instances(save, owner_kind=owner_kind, owner_id=owner_id)]
    if owner_kind == "player":
        return instance_ids, list(save.player_static_data.dnd5e_sheet.backpack.items)
    role = next((item for item in save.role_pool if item.role_id == owner_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return instance_ids, list(role.profile.dnd5e_sheet.backpack.items)


def resolve_equipment_snapshot(save: SaveFile, *, owner_kind: str, owner_id: str) -> dict[str, str | None]:
    ensure_item_system(save)
    if owner_kind == "player":
        slots = save.player_static_data.dnd5e_sheet.equipment_slots
    else:
        role = next((item for item in save.role_pool if item.role_id == owner_id), None)
        if role is None:
            raise KeyError("ROLE_NOT_FOUND")
        slots = role.profile.dnd5e_sheet.equipment_slots
    return {
        "weapon_item_instance_id": slots.weapon_item_instance_id,
        "armor_item_instance_id": slots.armor_item_instance_id,
        "shield_item_instance_id": slots.shield_item_instance_id,
    }


def template_library_counts() -> dict[str, int]:
    library = load_template_library()
    return {
        "item_definitions": len(library.item_definitions),
        "equipment_definitions": len(library.equipment_definitions),
        "interactable_templates": len(library.interactable_templates),
    }
