from __future__ import annotations

from app.models.schemas import SaveFile


def _spell_slot_field(level: int) -> str:
    return f"level_{max(1, min(int(level), 9))}"


def resolve_actor_profile(save: SaveFile, *, owner_type: str, role_id: str | None = None):
    kind = str(owner_type or "player").strip().lower()
    if kind == "player":
        return save.player_static_data, None
    if kind != "role" or not role_id:
        raise KeyError("ROLE_NOT_FOUND")
    role = next((item for item in save.role_pool if item.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return role.profile, role


def consume_spell_slots_in_profile(profile, *, level: int, amount: int) -> None:
    key = _spell_slot_field(level)
    current = int(getattr(profile.dnd5e_sheet.spell_slots_current, key) or 0)
    if current < amount:
        raise ValueError("SPELL_SLOT_NOT_ENOUGH")
    setattr(profile.dnd5e_sheet.spell_slots_current, key, current - amount)


def recover_spell_slots_in_profile(profile, *, level: int, amount: int) -> None:
    key = _spell_slot_field(level)
    current = int(getattr(profile.dnd5e_sheet.spell_slots_current, key) or 0)
    maximum = int(getattr(profile.dnd5e_sheet.spell_slots_max, key) or 0)
    setattr(profile.dnd5e_sheet.spell_slots_current, key, min(maximum, current + amount))


def consume_martial_points_in_profile(profile, *, amount: int) -> None:
    current = int(profile.dnd5e_sheet.martial_points_current or 0)
    if current < amount:
        raise ValueError("MARTIAL_POINTS_NOT_ENOUGH")
    profile.dnd5e_sheet.martial_points_current = current - amount


def recover_martial_points_in_profile(profile, *, amount: int) -> None:
    sheet = profile.dnd5e_sheet
    sheet.martial_points_current = min(int(sheet.martial_points_maximum or 0), int(sheet.martial_points_current or 0) + amount)
