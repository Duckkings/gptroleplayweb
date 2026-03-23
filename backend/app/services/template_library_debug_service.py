from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import TemplateLibraryFillRequest, TemplateLibraryFillResponse, TemplateLibraryStatusResponse
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.item_template_service import (
    EQUIPMENT_DEFINITION_COLUMNS,
    EQUIPMENT_DEFINITIONS_FILE,
    INTERACTABLE_TEMPLATE_COLUMNS,
    INTERACTABLE_TEMPLATES_FILE,
    ITEM_DEFINITION_COLUMNS,
    ITEM_DEFINITIONS_FILE,
    SPELL_DEFINITION_COLUMNS,
    SPELL_DEFINITIONS_FILE,
    WAR_ART_DEFINITION_COLUMNS,
    WAR_ART_DEFINITIONS_FILE,
    ensure_template_library_files,
    get_template_library_status,
    load_template_library,
    mark_template_library_filled,
)


def _template_dir() -> Path:
    return ensure_template_library_files()


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: str(value or "") for key, value in row.items()} for row in reader]


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def get_template_library_status_response(session_id: str) -> TemplateLibraryStatusResponse:
    status = get_template_library_status()
    return TemplateLibraryStatusResponse(session_id=session_id, **status)


def _coerce_payload_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("template library AI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("template library AI payload must be a JSON object")
    return payload


def _coerce_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _coerce_payload_list(field_name: str, value: Any) -> list[Any]:
    value = _coerce_json_string(value)
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        for key in ("items", "rows", "definitions", field_name):
            nested = value.get(key)
            nested = _coerce_json_string(nested)
            if isinstance(nested, list):
                return list(nested)
    if isinstance(value, list):
        return list(value)
    raise ValueError(f"template library field '{field_name}' must be a list")


def _coerce_row_object(field_name: str, index: int, row: Any) -> dict[str, Any]:
    row = _coerce_json_string(row)
    if isinstance(row, dict):
        return row
    raise ValueError(f"template library field '{field_name}' item {index} must be an object")


def _extract_payload_rows(payload: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    raw_rows = _coerce_payload_list(field_name, payload.get(field_name))
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        rows.append(_coerce_row_object(field_name, index, row))
    return rows


def _is_spell_only_fill(req: TemplateLibraryFillRequest) -> bool:
    return req.fill_scope == "spells"


def _slugify_identifier(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _looks_non_chinese_visible_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return ascii_letters > 0 and chinese_chars == 0


def _normalize_recommended_classes(value: Any) -> str:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [item.strip() for item in str(value or "").replace(",", "|").split("|") if item.strip()]
    return "|".join(items[:6])


def _normalize_spell_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        definition_id = str(row.get("definition_id") or row.get("id") or row.get("spell_id") or "").strip()
        if not definition_id:
            continue
        definition_id = _slugify_identifier(definition_id)
        if not definition_id:
            continue
        name = str(row.get("name") or "").strip()
        description = str(row.get("description") or "").strip()
        resolution_notes = str(row.get("resolution_notes") or row.get("notes") or "").strip()
        if not name or _looks_non_chinese_visible_text(name) or _looks_non_chinese_visible_text(description) or _looks_non_chinese_visible_text(resolution_notes):
            continue
        attack_mode = str(row.get("attack_mode") or "").strip().lower()
        area_shape = str(row.get("area_shape") or "").strip().lower()
        if attack_mode not in {"targeted_attack", "aoe_attack"}:
            attack_mode = "aoe_attack" if area_shape and area_shape != "none" else "targeted_attack"
        casting_ability = str(
            row.get("casting_ability") or row.get("ability") or row.get("spellcasting_ability") or ""
        ).strip().lower()
        if casting_ability not in {"intelligence", "wisdom", "charisma", "other"}:
            casting_ability = "intelligence"
        normalized_rows.append(
            {
                "definition_id": definition_id,
                "name": name,
                "attack_mode": attack_mode,
                "casting_ability": casting_ability,
                "spell_cost": row.get("spell_cost", 1),
                "damage_dice": str(row.get("damage_dice") or "").strip(),
                "damage_bonus": row.get("damage_bonus", 0),
                "damage_type": str(row.get("damage_type") or "force").strip() or "force",
                "area_shape": area_shape if area_shape in {"none", "sphere", "cone", "line", "burst", "emanation"} else "none",
                "area_radius_m": row.get("area_radius_m", 0),
                "area_length_m": row.get("area_length_m", 0),
                "self_target_policy": (
                    str(row.get("self_target_policy") or "").strip().lower()
                    if str(row.get("self_target_policy") or "").strip().lower() in {"never", "can_include_self", "always_include_self"}
                    else ("can_include_self" if attack_mode == "aoe_attack" else "never")
                ),
                "description": description,
                "resolution_notes": resolution_notes,
                "recommended_classes": _normalize_recommended_classes(row.get("recommended_classes")),
                "min_level": row.get("min_level", 1),
                "npc_priority": row.get("npc_priority", 0),
            }
        )
    return normalized_rows


def _normalize_war_art_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        definition_id = str(row.get("definition_id") or row.get("id") or row.get("war_art_id") or "").strip()
        if not definition_id:
            continue
        definition_id = _slugify_identifier(definition_id)
        if not definition_id:
            continue
        name = str(row.get("name") or "").strip()
        description = str(row.get("description") or "").strip()
        resolution_notes = str(row.get("resolution_notes") or row.get("notes") or "").strip()
        if not name or _looks_non_chinese_visible_text(name) or _looks_non_chinese_visible_text(description) or _looks_non_chinese_visible_text(resolution_notes):
            continue
        attack_mode = str(row.get("attack_mode") or "").strip().lower()
        area_shape = str(row.get("area_shape") or "").strip().lower()
        if attack_mode not in {"targeted_attack", "aoe_attack"}:
            attack_mode = "aoe_attack" if area_shape and area_shape != "none" else "targeted_attack"
        scaling_ability = str(row.get("scaling_ability") or row.get("ability") or "").strip().lower()
        if scaling_ability not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma", "other"}:
            scaling_ability = "strength"
        normalized_rows.append(
            {
                "definition_id": definition_id,
                "name": name,
                "attack_mode": attack_mode,
                "scaling_ability": scaling_ability,
                "martial_cost": row.get("martial_cost", 1),
                "cooldown_rounds": row.get("cooldown_rounds", 0),
                "damage_dice": str(row.get("damage_dice") or "").strip(),
                "damage_bonus": row.get("damage_bonus", 0),
                "damage_type": str(row.get("damage_type") or "bludgeoning").strip() or "bludgeoning",
                "area_shape": area_shape if area_shape in {"none", "sphere", "cone", "line", "burst", "emanation"} else "none",
                "area_radius_m": row.get("area_radius_m", 0),
                "area_length_m": row.get("area_length_m", 0),
                "self_target_policy": (
                    str(row.get("self_target_policy") or "").strip().lower()
                    if str(row.get("self_target_policy") or "").strip().lower() in {"never", "can_include_self", "always_include_self"}
                    else "never"
                ),
                "description": description,
                "resolution_notes": resolution_notes,
                "recommended_classes": _normalize_recommended_classes(row.get("recommended_classes")),
                "min_level": row.get("min_level", 1),
                "npc_priority": row.get("npc_priority", 0),
            }
        )
    return normalized_rows


def _merge_rows(
    current_rows: list[dict[str, str]],
    incoming_rows: list[dict[str, Any]],
    *,
    key_field: str,
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    by_id = {str(row.get(key_field) or "").strip(): dict(row) for row in current_rows if str(row.get(key_field) or "").strip()}
    appended: list[str] = []
    updated: list[str] = []
    for row in incoming_rows:
        key = str(row.get(key_field) or "").strip()
        if not key:
            continue
        if key not in by_id:
            by_id[key] = {str(k): row.get(k, "") for k in row}
            appended.append(key)
            continue
        current = by_id[key]
        changed = False
        for field, value in row.items():
            if field == key_field:
                continue
            existing = str(current.get(field) or "").strip()
            incoming = str(value or "").strip()
            if existing or not incoming:
                continue
            current[field] = incoming
            changed = True
        if changed:
            updated.append(key)
    return list(by_id.values()), appended, updated


def fill_template_library(req: TemplateLibraryFillRequest) -> TemplateLibraryFillResponse:
    status = get_template_library_status()
    if req.config is None or not (req.config.openai_api_key or "").strip() or not (req.config.model or "").strip():
        return TemplateLibraryFillResponse(session_id=req.session_id, **status)

    library = load_template_library()
    spell_only_fill = _is_spell_only_fill(req)
    system_prompt = prompt_table.get_text(
        "template.library.fill.system",
        (
            "Return one JSON object only. Add missing RPG item, equipment, spell, war art, and interactable templates. "
            "Do not overwrite existing non-empty fields. "
            "All player-facing visible text fields must be Simplified Chinese. "
            "definition_id must remain stable ASCII snake_case."
        ),
    )
    if spell_only_fill:
        user_prompt = (
            "Return one JSON object with exactly this top-level field: "
            '{"spell_definitions":[]}. '
            "Only add or patch spell_definitions for the current world. "
            "Do not include item_definitions, equipment_definitions, or interactable_templates. "
            "spell_definitions must be a JSON array of objects; never return stringified rows. "
            "Each spell_definitions item must use these exact keys: "
            "definition_id, name, attack_mode, casting_ability, spell_cost, damage_dice, damage_bonus, damage_type, "
            "area_shape, area_radius_m, area_length_m, self_target_policy, description, resolution_notes, recommended_classes, min_level, npc_priority. "
            "Do not use alias keys like id, spell_id, level, or school. "
            "Existing spell definitions: "
            f"{'|'.join(item.definition_id for item in library.spell_definitions[:60])}. "
            "Do not overwrite any existing non-empty field. "
            "Visible fields such as name/description/resolution_notes must be Simplified Chinese. "
            "recommended_classes should use short class labels separated by |. "
            f"Return at most {req.spell_fill_count} spell_definitions."
        )
    else:
        user_prompt = prompt_table.render(
            "template.library.fill.user",
            (
            "Return one JSON object with exactly these top-level fields: "
            '{"item_definitions":[],"equipment_definitions":[],"spell_definitions":[],"war_art_definitions":[],"interactable_templates":[]}. '
            "Add a small number of broadly useful RPG templates for the current world. "
            "Every field must be a JSON array of objects; never return stringified rows. "
            "Existing item definitions: $item_defs. "
            "Existing equipment definitions: $equipment_defs. "
            "Existing spell definitions: $spell_defs. "
            "Existing war art definitions: $war_art_defs. "
            "Existing interactable templates: $interactable_defs. "
            "Do not overwrite any existing non-empty field. "
            "Prefer common consumables, weapons, armor, spells, martial techniques, containers, doors, mechanisms, hazards, and clues. "
            "All visible text fields must be Simplified Chinese. "
            "Spell and war art rows must include recommended_classes, min_level, npc_priority. "
            "Return at most $spell_fill_count spell_definitions."
        ),
        item_defs="|".join(item.definition_id for item in library.item_definitions[:40]),
        equipment_defs="|".join(item.definition_id for item in library.equipment_definitions[:40]),
        spell_defs="|".join(item.definition_id for item in library.spell_definitions[:60]),
        war_art_defs="|".join(item.definition_id for item in library.war_art_definitions[:40]),
        interactable_defs="|".join(item.template_id for item in library.interactable_templates[:40]),
        spell_fill_count=str(req.spell_fill_count),
    )

    client = create_sync_client(req.config, client_cls=OpenAI)
    response = client.chat.completions.create(
        model=req.config.model,
        response_format={"type": "json_object"},
        **build_completion_options(req.config),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    choices = list(getattr(response, "choices", None) or [])
    if not choices:
        raise ValueError("template library AI returned no choices")

    raw = str(getattr(getattr(choices[0], "message", None), "content", "") or "").strip()
    if not raw:
        return TemplateLibraryFillResponse(session_id=req.session_id, **status)

    payload = _coerce_payload_object(raw)
    spell_rows = _normalize_spell_rows(_extract_payload_rows(payload, "spell_definitions"))
    if spell_only_fill:
        item_rows: list[dict[str, Any]] = []
        equipment_rows: list[dict[str, Any]] = []
        war_art_rows: list[dict[str, Any]] = []
        interactable_rows: list[dict[str, Any]] = []
    else:
        item_rows = _extract_payload_rows(payload, "item_definitions")
        equipment_rows = _extract_payload_rows(payload, "equipment_definitions")
        war_art_rows = _normalize_war_art_rows(_extract_payload_rows(payload, "war_art_definitions"))
        interactable_rows = _extract_payload_rows(payload, "interactable_templates")

    directory = _template_dir()
    item_path = directory / ITEM_DEFINITIONS_FILE
    equipment_path = directory / EQUIPMENT_DEFINITIONS_FILE
    spell_path = directory / SPELL_DEFINITIONS_FILE
    war_art_path = directory / WAR_ART_DEFINITIONS_FILE
    interactable_path = directory / INTERACTABLE_TEMPLATES_FILE

    merged_items, appended_items, updated_items = _merge_rows(_read_rows(item_path), item_rows, key_field="definition_id")
    merged_equipment, appended_equipment, updated_equipment = _merge_rows(_read_rows(equipment_path), equipment_rows, key_field="definition_id")
    merged_spells, appended_spells, updated_spells = _merge_rows(_read_rows(spell_path), spell_rows, key_field="definition_id")
    merged_war_arts, appended_war_arts, updated_war_arts = _merge_rows(_read_rows(war_art_path), war_art_rows, key_field="definition_id")
    merged_interactables, appended_interactables, updated_interactables = _merge_rows(
        _read_rows(interactable_path),
        interactable_rows,
        key_field="template_id",
    )

    _write_rows(item_path, ITEM_DEFINITION_COLUMNS, merged_items)
    _write_rows(equipment_path, EQUIPMENT_DEFINITION_COLUMNS, merged_equipment)
    _write_rows(spell_path, SPELL_DEFINITION_COLUMNS, merged_spells)
    _write_rows(war_art_path, WAR_ART_DEFINITION_COLUMNS, merged_war_arts)
    _write_rows(interactable_path, INTERACTABLE_TEMPLATE_COLUMNS, merged_interactables)
    mark_template_library_filled()
    status = get_template_library_status()
    return TemplateLibraryFillResponse(
        session_id=req.session_id,
        appended_item_definition_ids=appended_items,
        appended_equipment_definition_ids=appended_equipment,
        appended_spell_definition_ids=appended_spells,
        appended_war_art_definition_ids=appended_war_arts,
        appended_interactable_template_ids=appended_interactables,
        updated_item_definition_ids=updated_items,
        updated_equipment_definition_ids=updated_equipment,
        updated_spell_definition_ids=updated_spells,
        updated_war_art_definition_ids=updated_war_arts,
        updated_interactable_template_ids=updated_interactables,
        **status,
    )
