from __future__ import annotations

from typing import Any

from app.models.schemas import (
    RoleCapabilityAbilityEntry,
    RoleCapabilityResponse,
    RoleCapabilitySnapshot,
    SaveFile,
)
from app.services.item_template_service import load_template_library


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _sheet_slot_dict(slots: Any) -> dict[str, int]:
    return {
        f"level_{level}": int(getattr(slots, f"level_{level}", 0) or 0)
        for level in range(1, 10)
    }


def _equipped_item_name(sheet: Any, item_id: str | None) -> str | None:
    clean_id = _clean(item_id)
    if not clean_id:
        return None
    item = next((row for row in sheet.backpack.items if row.item_id == clean_id), None)
    return item.name if item is not None else None


def _definition_match_maps() -> tuple[dict[str, Any], dict[str, Any]]:
    library = load_template_library()
    spell_map: dict[str, Any] = {}
    war_art_map: dict[str, Any] = {}
    for definition in library.spell_definitions:
        spell_map[_clean(definition.definition_id).lower()] = definition
        spell_map[_clean(definition.name).lower()] = definition
    for definition in library.war_art_definitions:
        war_art_map[_clean(definition.definition_id).lower()] = definition
        war_art_map[_clean(definition.name).lower()] = definition
    return spell_map, war_art_map


def _resolve_actor_sheet(save: SaveFile, role_id: str):
    if role_id == save.player_static_data.player_id:
        return "player", save.player_static_data.name, save.player_static_data.dnd5e_sheet
    role = next((item for item in save.role_pool if item.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return "npc", role.name, role.profile.dnd5e_sheet


def build_role_capability_snapshot(save: SaveFile, role_id: str) -> RoleCapabilitySnapshot:
    actor_kind, role_name, sheet = _resolve_actor_sheet(save, role_id)
    spell_map, war_art_map = _definition_match_maps()
    spell_slots_current = _sheet_slot_dict(sheet.spell_slots_current)
    spell_slots_max = _sheet_slot_dict(sheet.spell_slots_max)
    available_abilities: list[RoleCapabilityAbilityEntry] = []

    seen_spell_ids: set[str] = set()
    for known_name in list(sheet.spells or []):
        definition = spell_map.get(_clean(known_name).lower())
        if definition is None:
            continue
        if definition.definition_id in seen_spell_ids:
            continue
        seen_spell_ids.add(definition.definition_id)
        level_key = f"level_{max(1, min(int(definition.spell_cost or 1), 9))}"
        available_now = int(spell_slots_current.get(level_key, 0)) >= int(definition.spell_cost or 1)
        available_abilities.append(
            RoleCapabilityAbilityEntry(
                definition_id=definition.definition_id,
                name=definition.name,
                kind="spell",
                resource_cost=int(definition.spell_cost or 1),
                cooldown_rounds=0,
                cooldown_remaining=0,
                available_now=available_now,
                summary=definition.resolution_notes or definition.description,
            )
        )

    cooldowns = {str(key): max(0, int(value or 0)) for key, value in dict(getattr(sheet, "war_art_cooldowns", {}) or {}).items()}
    seen_war_art_ids: set[str] = set()
    for known_name in list(sheet.war_arts or []):
        definition = war_art_map.get(_clean(known_name).lower())
        if definition is None:
            continue
        if definition.definition_id in seen_war_art_ids:
            continue
        seen_war_art_ids.add(definition.definition_id)
        cooldown_remaining = max(0, int(cooldowns.get(definition.definition_id, 0) or 0))
        available_now = int(sheet.martial_points_current or 0) >= int(definition.martial_cost or 1) and cooldown_remaining <= 0
        available_abilities.append(
            RoleCapabilityAbilityEntry(
                definition_id=definition.definition_id,
                name=definition.name,
                kind="war_art",
                resource_cost=int(definition.martial_cost or 1),
                cooldown_rounds=int(definition.cooldown_rounds or 0),
                cooldown_remaining=cooldown_remaining,
                available_now=available_now,
                summary=definition.resolution_notes or definition.description,
            )
        )

    return RoleCapabilitySnapshot(
        role_id=role_id,
        role_name=role_name,
        actor_kind=actor_kind,  # type: ignore[arg-type]
        char_class=_clean(sheet.char_class),
        level=max(1, int(sheet.level or 1)),
        spells_known=[_clean(item) for item in list(sheet.spells or []) if _clean(item)],
        war_arts_known=[_clean(item) for item in list(sheet.war_arts or []) if _clean(item)],
        spell_slots_current=spell_slots_current,
        spell_slots_max=spell_slots_max,
        martial_points_current=max(0, int(sheet.martial_points_current or 0)),
        martial_points_maximum=max(0, int(sheet.martial_points_maximum or 0)),
        war_art_cooldowns=cooldowns,
        equipped_weapon_name=_equipped_item_name(sheet, getattr(sheet.equipment_slots, "weapon_item_id", None)),
        equipped_armor_name=_equipped_item_name(sheet, getattr(sheet.equipment_slots, "armor_item_id", None)),
        available_abilities=available_abilities,
    )


def build_role_capability_response(save: SaveFile, *, session_id: str, role_id: str) -> RoleCapabilityResponse:
    return RoleCapabilityResponse(
        session_id=session_id,
        role_id=role_id,
        snapshot=build_role_capability_snapshot(save, role_id),
    )


def render_role_capability_brief(snapshot: RoleCapabilitySnapshot) -> str:
    spell_text = "、".join(snapshot.spells_known[:6]) if snapshot.spells_known else "无"
    war_art_text = "、".join(snapshot.war_arts_known[:6]) if snapshot.war_arts_known else "无"
    slot_parts = [f"{key}:{value}/{snapshot.spell_slots_max.get(key, 0)}" for key, value in snapshot.spell_slots_current.items() if snapshot.spell_slots_max.get(key, 0)]
    slot_text = "，".join(slot_parts) if slot_parts else "无"
    weapon_text = snapshot.equipped_weapon_name or "无"
    return (
        f"职业={snapshot.char_class or '未知'}；"
        f"已会法术={spell_text}；"
        f"已会武技={war_art_text}；"
        f"法术位={slot_text}；"
        f"武技点={snapshot.martial_points_current}/{snapshot.martial_points_maximum}；"
        f"武器={weapon_text}"
    )
