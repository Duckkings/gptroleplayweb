from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.schemas import (
    AreaInteraction,
    EquipmentDefinition,
    InventoryItem,
    ItemDefinition,
    ItemInstance,
    SaveFile,
    SceneInteractable,
)
from app.services.item_template_service import (
    ensure_definition_for_inventory_item,
    infer_interactable_template_id,
    load_template_library,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_item_instance_id() -> str:
    return f"iteminst_{uuid4().hex}"


def compat_item_id(instance: ItemInstance) -> str:
    raw = instance.metadata.get("compat_item_id") if isinstance(instance.metadata, dict) else None
    text = str(raw or "").strip()
    return text or instance.item_instance_id


def _find_item_instance(save: SaveFile, item_instance_id: str | None) -> ItemInstance | None:
    if not item_instance_id:
        return None
    return next((item for item in save.item_instance_state.items if item.item_instance_id == item_instance_id), None)


def _template_maps() -> tuple[dict[str, ItemDefinition], dict[str, EquipmentDefinition]]:
    library = load_template_library()
    item_defs = {item.definition_id: item for item in library.item_definitions}
    equipment_defs = {item.definition_id: item for item in library.equipment_definitions}
    return item_defs, equipment_defs


def _project_item(instance: ItemInstance, item_defs: dict[str, ItemDefinition], equipment_defs: dict[str, EquipmentDefinition]) -> InventoryItem:
    equipment = equipment_defs.get(instance.definition_id)
    if equipment is not None:
        return InventoryItem(
            item_id=compat_item_id(instance),
            name=instance.display_name or equipment.name,
            item_type=equipment.equipment_kind,
            description=instance.description_override or equipment.description,
            weight=equipment.weight,
            rarity=equipment.rarity,
            value=equipment.value,
            effect="",
            uses_max=instance.uses_max,
            uses_left=instance.uses_left,
            cooldown_min=0,
            bound=False,
            quantity=max(1, instance.quantity),
            slot_type=equipment.slot_type if equipment.slot_type in {"weapon", "armor"} else "misc",
            attack_bonus=equipment.attack_bonus,
            armor_bonus=equipment.armor_bonus,
        )
    item = item_defs.get(instance.definition_id)
    if item is None:
        return InventoryItem(
            item_id=compat_item_id(instance),
            name=instance.display_name or instance.definition_id,
            item_type="misc",
            description=instance.description_override,
            uses_max=instance.uses_max,
            uses_left=instance.uses_left,
            quantity=max(1, instance.quantity),
        )
    slot_type = "misc"
    if "weapon" in item.combat_tags:
        slot_type = "weapon"
    elif "armor" in item.combat_tags:
        slot_type = "armor"
    return InventoryItem(
        item_id=compat_item_id(instance),
        name=instance.display_name or item.name,
        item_type=item.item_kind,
        description=instance.description_override or item.description,
        weight=item.weight,
        rarity=item.rarity,
        value=item.value,
        effect=item.effect_prompt_hint,
        uses_max=instance.uses_max,
        uses_left=instance.uses_left,
        cooldown_min=0,
        bound=False,
        quantity=max(1, instance.quantity),
        slot_type=slot_type,  # type: ignore[arg-type]
        attack_bonus=0,
        armor_bonus=0,
    )


def _ensure_owner_backpack_projection(save: SaveFile) -> None:
    item_defs, equipment_defs = _template_maps()
    player_sheet = save.player_static_data.dnd5e_sheet
    player_items = [item for item in save.item_instance_state.items if item.owner_kind == "player" and item.owner_id == save.player_static_data.player_id and item.quantity > 0]
    player_sheet.backpack.item_instance_ids = [item.item_instance_id for item in player_items]
    player_sheet.backpack.items = [_project_item(item, item_defs, equipment_defs) for item in player_items]
    if player_sheet.equipment_slots.weapon_item_instance_id and not player_sheet.equipment_slots.weapon_item_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.weapon_item_instance_id)
        player_sheet.equipment_slots.weapon_item_id = compat_item_id(item) if item is not None else None
    if player_sheet.equipment_slots.armor_item_instance_id and not player_sheet.equipment_slots.armor_item_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.armor_item_instance_id)
        player_sheet.equipment_slots.armor_item_id = compat_item_id(item) if item is not None else None
    if player_sheet.equipment_slots.shield_item_instance_id and not player_sheet.equipment_slots.shield_item_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.shield_item_instance_id)
        player_sheet.equipment_slots.shield_item_id = compat_item_id(item) if item is not None else None
    if player_sheet.equipment_slots.weapon_item_instance_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.weapon_item_instance_id)
        player_sheet.equipment_slots.weapon_item_id = compat_item_id(item) if item is not None else None
    if player_sheet.equipment_slots.armor_item_instance_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.armor_item_instance_id)
        player_sheet.equipment_slots.armor_item_id = compat_item_id(item) if item is not None else None
    if player_sheet.equipment_slots.shield_item_instance_id:
        item = _find_item_instance(save, player_sheet.equipment_slots.shield_item_instance_id)
        player_sheet.equipment_slots.shield_item_id = compat_item_id(item) if item is not None else None

    for role in save.role_pool:
        sheet = role.profile.dnd5e_sheet
        role_items = [item for item in save.item_instance_state.items if item.owner_kind == "role" and item.owner_id == role.role_id and item.quantity > 0]
        sheet.backpack.item_instance_ids = [item.item_instance_id for item in role_items]
        sheet.backpack.items = [_project_item(item, item_defs, equipment_defs) for item in role_items]
        if sheet.equipment_slots.weapon_item_instance_id and not sheet.equipment_slots.weapon_item_id:
            item = _find_item_instance(save, sheet.equipment_slots.weapon_item_instance_id)
            sheet.equipment_slots.weapon_item_id = compat_item_id(item) if item is not None else None
        if sheet.equipment_slots.armor_item_instance_id and not sheet.equipment_slots.armor_item_id:
            item = _find_item_instance(save, sheet.equipment_slots.armor_item_instance_id)
            sheet.equipment_slots.armor_item_id = compat_item_id(item) if item is not None else None
        if sheet.equipment_slots.shield_item_instance_id and not sheet.equipment_slots.shield_item_id:
            item = _find_item_instance(save, sheet.equipment_slots.shield_item_instance_id)
            sheet.equipment_slots.shield_item_id = compat_item_id(item) if item is not None else None
        if sheet.equipment_slots.weapon_item_instance_id:
            item = _find_item_instance(save, sheet.equipment_slots.weapon_item_instance_id)
            sheet.equipment_slots.weapon_item_id = compat_item_id(item) if item is not None else None
        if sheet.equipment_slots.armor_item_instance_id:
            item = _find_item_instance(save, sheet.equipment_slots.armor_item_instance_id)
            sheet.equipment_slots.armor_item_id = compat_item_id(item) if item is not None else None
        if sheet.equipment_slots.shield_item_instance_id:
            item = _find_item_instance(save, sheet.equipment_slots.shield_item_instance_id)
            sheet.equipment_slots.shield_item_id = compat_item_id(item) if item is not None else None


def _project_interactables(save: SaveFile) -> None:
    for sub_zone in save.area_snapshot.sub_zones:
        projected = [
            AreaInteraction(
                interaction_id=item.interactable_id,
                name=item.name,
                type=("item" if item.interactable_kind == "item_proxy" else "scene"),
                status=item.status,
                generated_mode=("instant" if item.generated_mode == "instant" else "pre"),
                placeholder=False,
            )
            for item in save.scene_interactable_state.items
            if item.sub_zone_id == sub_zone.sub_zone_id
        ]
        sub_zone.key_interactions = projected


def _migrate_profile_inventory(save: SaveFile) -> bool:
    changed = False
    existing_ids = {item.item_instance_id for item in save.item_instance_state.items}
    for owner_kind, owner_id, sheet in [
        ("player", save.player_static_data.player_id, save.player_static_data.dnd5e_sheet),
        *[("role", role.role_id, role.profile.dnd5e_sheet) for role in save.role_pool],
    ]:
        old_to_new: dict[str, str] = {}
        if sheet.backpack.item_instance_ids:
            for instance_id in sheet.backpack.item_instance_ids:
                if instance_id in existing_ids:
                    old_to_new[instance_id] = instance_id
        for item in sheet.backpack.items:
            if item.item_id in existing_ids:
                old_to_new[item.item_id] = item.item_id
                continue
            definition_id = ensure_definition_for_inventory_item(item)
            instance_id = f"{owner_kind}_{owner_id}_{item.item_id}".replace(" ", "_")
            if instance_id in existing_ids:
                old_to_new[item.item_id] = instance_id
                continue
            instance = ItemInstance(
                item_instance_id=instance_id,
                definition_id=definition_id,
                quantity=max(1, item.quantity),
                uses_left=item.uses_left,
                uses_max=item.uses_max,
                owner_kind=owner_kind,  # type: ignore[arg-type]
                owner_id=owner_id,
                display_name=item.name,
                description_override=item.description,
                metadata={"legacy_item_id": item.item_id, "compat_item_id": item.item_id},
            )
            save.item_instance_state.items.append(instance)
            existing_ids.add(instance_id)
            old_to_new[item.item_id] = instance_id
            changed = True
        desired_ids = [old_to_new.get(item.item_id, item.item_id) for item in sheet.backpack.items if old_to_new.get(item.item_id, item.item_id) in existing_ids]
        if sheet.backpack.item_instance_ids != desired_ids:
            sheet.backpack.item_instance_ids = desired_ids
            changed = True
        slots = sheet.equipment_slots
        if slots.weapon_item_instance_id is None and slots.weapon_item_id:
            slots.weapon_item_instance_id = old_to_new.get(slots.weapon_item_id, slots.weapon_item_id)
            changed = True
        if slots.armor_item_instance_id is None and slots.armor_item_id:
            slots.armor_item_instance_id = old_to_new.get(slots.armor_item_id, slots.armor_item_id)
            changed = True
        if slots.shield_item_instance_id is None and slots.shield_item_id:
            slots.shield_item_instance_id = old_to_new.get(slots.shield_item_id, slots.shield_item_id)
            changed = True
    if changed:
        save.item_instance_state.updated_at = _utc_now()
    return changed


def _migrate_area_interactions(save: SaveFile) -> bool:
    changed = False
    existing_ids = {item.interactable_id for item in save.scene_interactable_state.items}
    for sub_zone in save.area_snapshot.sub_zones:
        for interaction in sub_zone.key_interactions:
            if interaction.interaction_id in existing_ids:
                continue
            save.scene_interactable_state.items.append(
                SceneInteractable(
                    interactable_id=interaction.interaction_id,
                    template_id=infer_interactable_template_id(interaction.name, interaction.type),
                    zone_id=sub_zone.zone_id,
                    sub_zone_id=sub_zone.sub_zone_id,
                    name=interaction.name,
                    interactable_kind=("item_proxy" if interaction.type == "item" else "scene"),  # type: ignore[arg-type]
                    description="",
                    allowed_actions=(["inspect", "pickup"] if interaction.type == "item" else ["inspect"]),
                    state_tags=["visible"],
                    status=interaction.status,
                    generated_mode=("migrated" if interaction.generated_mode == "instant" else "pre"),
                    placeholder=interaction.placeholder,
                )
            )
            existing_ids.add(interaction.interaction_id)
            changed = True
    if changed:
        save.scene_interactable_state.updated_at = _utc_now()
    return changed


def ensure_item_system(save: SaveFile) -> bool:
    changed = False
    if _migrate_profile_inventory(save):
        changed = True
    if _migrate_area_interactions(save):
        changed = True
    _ensure_owner_backpack_projection(save)
    _project_interactables(save)
    return changed


def resolve_owner_instances(save: SaveFile, *, owner_kind: str, owner_id: str) -> list[ItemInstance]:
    return [
        item
        for item in save.item_instance_state.items
        if item.owner_kind == owner_kind and item.owner_id == owner_id and item.quantity > 0
    ]


def get_owner_instance(save: SaveFile, *, owner_kind: str, owner_id: str, item_instance_id: str) -> ItemInstance:
    item = _find_item_instance(save, item_instance_id)
    if item is None or item.owner_kind != owner_kind or item.owner_id != owner_id or item.quantity <= 0:
        raise KeyError("ITEM_INSTANCE_NOT_FOUND")
    return item


def get_owner_instance_by_ref(save: SaveFile, *, owner_kind: str, owner_id: str, item_ref: str) -> ItemInstance:
    clean = str(item_ref or "").strip()
    for item in save.item_instance_state.items:
        if item.owner_kind != owner_kind or item.owner_id != owner_id or item.quantity <= 0:
            continue
        if item.item_instance_id == clean or compat_item_id(item) == clean:
            return item
    raise KeyError("ITEM_INSTANCE_NOT_FOUND")


def set_instance_owner(
    save: SaveFile,
    *,
    item_instance_id: str,
    owner_kind: str,
    owner_id: str,
    zone_id: str | None = None,
    sub_zone_id: str | None = None,
) -> ItemInstance:
    item = _find_item_instance(save, item_instance_id)
    if item is None:
        raise KeyError("ITEM_INSTANCE_NOT_FOUND")
    item.owner_kind = owner_kind  # type: ignore[assignment]
    item.owner_id = owner_id
    item.zone_id = zone_id
    item.sub_zone_id = sub_zone_id
    item.updated_at = _utc_now()
    save.item_instance_state.updated_at = item.updated_at
    return item


def remove_item_instance(save: SaveFile, item_instance_id: str) -> None:
    before = len(save.item_instance_state.items)
    save.item_instance_state.items = [item for item in save.item_instance_state.items if item.item_instance_id != item_instance_id]
    if len(save.item_instance_state.items) != before:
        save.item_instance_state.updated_at = _utc_now()


def create_item_instance(
    save: SaveFile,
    *,
    definition_id: str,
    owner_kind: str,
    owner_id: str,
    quantity: int = 1,
    uses_left: int | None = None,
    uses_max: int | None = None,
    display_name: str = "",
    description_override: str = "",
    zone_id: str | None = None,
    sub_zone_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ItemInstance:
    instance = ItemInstance(
        item_instance_id=_new_item_instance_id(),
        definition_id=definition_id,
        quantity=max(0, quantity),
        uses_left=uses_left,
        uses_max=uses_max,
        owner_kind=owner_kind,  # type: ignore[arg-type]
        owner_id=owner_id,
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        display_name=display_name,
        description_override=description_override,
        metadata=dict(metadata or {}),
    )
    save.item_instance_state.items.append(instance)
    save.item_instance_state.updated_at = instance.updated_at
    return instance
