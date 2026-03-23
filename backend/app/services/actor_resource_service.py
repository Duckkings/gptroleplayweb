from __future__ import annotations

import re
from typing import Any

from app.models.schemas import ChatConfig, PlayerInputResourceStatus, PlayerInputValidationRequest, SaveFile
from app.services.item_template_service import load_template_library
from app.services.player_input_validation_service import validate_player_input


_RESOURCE_LOOKUP_SEPARATORS = re.compile(r"[\s_\-]+")


def _spell_slot_field(level: int) -> str:
    return f"level_{max(1, min(int(level), 9))}"


def _normalize_lookup(value: str) -> str:
    return _RESOURCE_LOOKUP_SEPARATORS.sub("", str(value or "").strip().lower())


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


def _definition_lookup_maps() -> tuple[dict[str, Any], dict[str, Any]]:
    library = load_template_library()
    spell_map: dict[str, Any] = {}
    war_art_map: dict[str, Any] = {}
    for definition in library.spell_definitions:
        for candidate in (getattr(definition, "definition_id", ""), getattr(definition, "name", "")):
            normalized = _normalize_lookup(candidate)
            if normalized:
                spell_map[normalized] = definition
    for definition in library.war_art_definitions:
        for candidate in (getattr(definition, "definition_id", ""), getattr(definition, "name", "")):
            normalized = _normalize_lookup(candidate)
            if normalized:
                war_art_map[normalized] = definition
    return spell_map, war_art_map


def _resolve_definition(definitions: dict[str, Any], *, resource_definition_id: str = "", resource_name: str = "") -> Any | None:
    for candidate in (resource_definition_id, resource_name):
        normalized = _normalize_lookup(candidate)
        if normalized and normalized in definitions:
            return definitions[normalized]
    return None


def _match_definition(definitions: list[Any], known_names: set[str], combined_text: str) -> tuple[Any | None, str]:
    matches: list[tuple[int, Any, str]] = []
    for definition in definitions:
        candidate_names = (
            str(getattr(definition, "definition_id", "") or "").strip(),
            str(getattr(definition, "name", "") or "").strip(),
        )
        if not any(_normalize_lookup(name) in known_names for name in candidate_names if name):
            continue
        matched_name = next((name for name in candidate_names if name and _normalize_lookup(name) in combined_text), "")
        if matched_name:
            matches.append((len(matched_name), definition, matched_name))
    if not matches:
        return None, ""
    _, definition, matched_name = max(matches, key=lambda item: item[0])
    return definition, matched_name


def _current_spell_slots(profile: Any, level: int) -> int:
    key = _spell_slot_field(level)
    return int(getattr(profile.dnd5e_sheet.spell_slots_current, key) or 0)


def _local_resource_status(
    profile: Any,
    *,
    action_text: str,
    speech_text: str,
) -> PlayerInputResourceStatus:
    combined = _normalize_lookup(f"{action_text} {speech_text}")
    if not combined:
        return PlayerInputResourceStatus()

    library = load_template_library()
    known_spell_names = {
        _normalize_lookup(item)
        for item in getattr(profile.dnd5e_sheet, "spells", []) or []
        if _normalize_lookup(item)
    }
    known_war_art_names = {
        _normalize_lookup(item)
        for item in getattr(profile.dnd5e_sheet, "war_arts", []) or []
        if _normalize_lookup(item)
    }

    war_art_definition, war_art_match = _match_definition(library.war_art_definitions, known_war_art_names, combined)
    spell_definition, spell_match = _match_definition(library.spell_definitions, known_spell_names, combined)

    if war_art_definition is None and spell_definition is None:
        return PlayerInputResourceStatus()

    if war_art_definition is not None and (spell_definition is None or len(war_art_match) >= len(spell_match)):
        required_amount = max(1, int(getattr(war_art_definition, "martial_cost", 1) or 1))
        current_amount = int(getattr(profile.dnd5e_sheet, "martial_points_current", 0) or 0)
        return PlayerInputResourceStatus(
            check_status="passed" if current_amount >= required_amount else "failed",
            resource_kind="war_art",
            mentioned_name=war_art_match,
            resolved_name=str(getattr(war_art_definition, "name", "") or war_art_match).strip(),
            resolved_definition_id=str(getattr(war_art_definition, "definition_id", "") or "").strip() or None,
            required_amount=required_amount,
            current_amount=current_amount,
            requirement_summary=f"requires martial points: {required_amount}",
            current_summary=f"current martial points: {current_amount}",
        )

    assert spell_definition is not None
    required_amount = max(1, int(getattr(spell_definition, "spell_cost", 1) or 1))
    current_amount = _current_spell_slots(profile, required_amount)
    return PlayerInputResourceStatus(
        check_status="passed" if current_amount >= 1 else "failed",
        resource_kind="spell",
        mentioned_name=spell_match,
        resolved_name=str(getattr(spell_definition, "name", "") or spell_match).strip(),
        resolved_definition_id=str(getattr(spell_definition, "definition_id", "") or "").strip() or None,
        required_amount=required_amount,
        current_amount=current_amount,
        requirement_summary=f"requires 1 level-{required_amount} spell slot",
        current_summary=f"current level-{required_amount} spell slots: {current_amount}",
    )


def consume_action_resources_in_profile(
    profile: Any,
    *,
    action_text: str,
    speech_text: str,
) -> PlayerInputResourceStatus:
    local_status = _local_resource_status(profile, action_text=action_text, speech_text=speech_text)
    if local_status.check_status != "passed" or local_status.resource_kind == "none":
        return local_status

    try:
        if local_status.resource_kind == "spell":
            consume_spell_slots_in_profile(profile, level=max(1, int(local_status.required_amount or 1)), amount=1)
        elif local_status.resource_kind == "war_art":
            consume_martial_points_in_profile(profile, amount=max(1, int(local_status.required_amount or 1)))
    except ValueError:
        return PlayerInputResourceStatus(
            check_status="failed",
            resource_kind=local_status.resource_kind,
            mentioned_name=local_status.mentioned_name,
            resolved_name=local_status.resolved_name,
            resolved_definition_id=local_status.resolved_definition_id,
            required_amount=local_status.required_amount,
            current_amount=local_status.current_amount,
            requirement_summary=local_status.requirement_summary,
            current_summary=local_status.current_summary,
        )
    return local_status


def adjust_actor_resource_in_profile(
    profile: Any,
    *,
    resource_kind: str,
    mode: str = "consume",
    amount: int = 1,
    level: int | None = None,
    resource_definition_id: str = "",
    resource_name: str = "",
) -> PlayerInputResourceStatus:
    normalized_kind = str(resource_kind or "").strip().lower()
    normalized_mode = str(mode or "consume").strip().lower()
    amount = max(1, int(amount or 1))

    if normalized_kind == "spell_slot":
        slot_level = max(1, min(int(level or 1), 9))
        current_amount = _current_spell_slots(profile, slot_level)
        status = PlayerInputResourceStatus(
            check_status="passed" if (normalized_mode != "consume" or current_amount >= amount) else "failed",
            resource_kind="spell",
            mentioned_name="",
            resolved_name="",
            resolved_definition_id=None,
            required_amount=slot_level,
            current_amount=current_amount,
            requirement_summary=f"requires 1 level-{slot_level} spell slot",
            current_summary=f"current level-{slot_level} spell slots: {current_amount}",
        )
        if normalized_mode == "consume" and current_amount >= amount:
            consume_spell_slots_in_profile(profile, level=slot_level, amount=amount)
        elif normalized_mode == "recover":
            recover_spell_slots_in_profile(profile, level=slot_level, amount=amount)
        elif normalized_mode == "consume":
            status.check_status = "failed"
        return status

    if normalized_kind == "martial_point":
        current_amount = int(getattr(profile.dnd5e_sheet, "martial_points_current", 0) or 0)
        maximum = int(getattr(profile.dnd5e_sheet, "martial_points_maximum", 0) or 0)
        status = PlayerInputResourceStatus(
            check_status="passed" if (normalized_mode != "consume" or current_amount >= amount) else "failed",
            resource_kind="war_art",
            mentioned_name="",
            resolved_name="",
            resolved_definition_id=None,
            required_amount=amount,
            current_amount=current_amount,
            requirement_summary=f"requires martial points: {amount}",
            current_summary=f"current martial points: {current_amount}/{maximum}",
        )
        if normalized_mode == "consume" and current_amount >= amount:
            consume_martial_points_in_profile(profile, amount=amount)
        elif normalized_mode == "recover":
            recover_martial_points_in_profile(profile, amount=amount)
        elif normalized_mode == "consume":
            status.check_status = "failed"
        return status

    spell_map, war_art_map = _definition_lookup_maps()
    if normalized_kind == "spell":
        definition = _resolve_definition(
            spell_map,
            resource_definition_id=resource_definition_id,
            resource_name=resource_name,
        )
        if definition is None:
            return PlayerInputResourceStatus(
                check_status="failed",
                resource_kind="spell",
                mentioned_name=resource_name,
                requirement_summary="spell definition not found",
                current_summary="",
            )
        required_amount = max(1, int(getattr(definition, "spell_cost", 1) or 1))
        current_amount = _current_spell_slots(profile, required_amount)
        status = PlayerInputResourceStatus(
            check_status="passed" if (normalized_mode != "consume" or current_amount >= amount) else "failed",
            resource_kind="spell",
            mentioned_name=str(resource_name or getattr(definition, "name", "") or "").strip(),
            resolved_name=str(getattr(definition, "name", "") or "").strip(),
            resolved_definition_id=str(getattr(definition, "definition_id", "") or "").strip() or None,
            required_amount=required_amount,
            current_amount=current_amount,
            requirement_summary=f"requires 1 level-{required_amount} spell slot",
            current_summary=f"current level-{required_amount} spell slots: {current_amount}",
        )
        if normalized_mode == "consume" and current_amount >= amount:
            consume_spell_slots_in_profile(profile, level=required_amount, amount=amount)
        elif normalized_mode == "recover":
            recover_spell_slots_in_profile(profile, level=required_amount, amount=amount)
        elif normalized_mode == "consume":
            status.check_status = "failed"
        return status

    if normalized_kind == "war_art":
        definition = _resolve_definition(
            war_art_map,
            resource_definition_id=resource_definition_id,
            resource_name=resource_name,
        )
        if definition is None:
            return PlayerInputResourceStatus(
                check_status="failed",
                resource_kind="war_art",
                mentioned_name=resource_name,
                requirement_summary="war art definition not found",
                current_summary="",
            )
        required_amount = max(1, int(getattr(definition, "martial_cost", 1) or 1))
        current_amount = int(getattr(profile.dnd5e_sheet, "martial_points_current", 0) or 0)
        maximum = int(getattr(profile.dnd5e_sheet, "martial_points_maximum", 0) or 0)
        status = PlayerInputResourceStatus(
            check_status="passed" if (normalized_mode != "consume" or current_amount >= amount) else "failed",
            resource_kind="war_art",
            mentioned_name=str(resource_name or getattr(definition, "name", "") or "").strip(),
            resolved_name=str(getattr(definition, "name", "") or "").strip(),
            resolved_definition_id=str(getattr(definition, "definition_id", "") or "").strip() or None,
            required_amount=required_amount,
            current_amount=current_amount,
            requirement_summary=f"requires martial points: {required_amount}",
            current_summary=f"current martial points: {current_amount}/{maximum}",
        )
        if normalized_mode == "consume" and current_amount >= amount:
            consume_martial_points_in_profile(profile, amount=amount)
        elif normalized_mode == "recover":
            recover_martial_points_in_profile(profile, amount=amount)
        elif normalized_mode == "consume":
            status.check_status = "failed"
        return status

    return PlayerInputResourceStatus()


def consume_submission_resources_in_save(
    save: SaveFile,
    *,
    actor_role_id: str,
    action_text: str,
    speech_text: str,
    entry_point: str,
    config: ChatConfig | None = None,
) -> PlayerInputResourceStatus:
    if not (str(action_text or "").strip() or str(speech_text or "").strip()):
        return PlayerInputResourceStatus()

    owner_type = "player" if actor_role_id == save.player_static_data.player_id else "role"
    try:
        profile, _ = resolve_actor_profile(save, owner_type=owner_type, role_id=(None if owner_type == "player" else actor_role_id))
    except KeyError:
        return PlayerInputResourceStatus()

    validated_status: PlayerInputResourceStatus | None = None
    try:
        validation = validate_player_input(
            PlayerInputValidationRequest(
                session_id=save.session_id,
                entry_point=entry_point,  # type: ignore[arg-type]
                action_text=action_text,
                speech_text=speech_text,
                actor_role_id=actor_role_id,
                config=config,
            )
        )
        validated_status = validation.resource_status
    except Exception:
        validated_status = None

    local_status = _local_resource_status(profile, action_text=action_text, speech_text=speech_text)
    status = validated_status or PlayerInputResourceStatus()
    if local_status.check_status == "passed" and (validated_status is None or validated_status.resource_kind == "none"):
        status = local_status

    if status.check_status != "passed" or status.resource_kind == "none":
        return status

    try:
        if status.resource_kind == "spell":
            consume_spell_slots_in_profile(profile, level=max(1, int(status.required_amount or 1)), amount=1)
        elif status.resource_kind == "war_art":
            consume_martial_points_in_profile(profile, amount=max(1, int(status.required_amount or 1)))
    except ValueError:
        pass
    return status
