from __future__ import annotations

import csv
import json
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
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def get_template_library_status_response(session_id: str) -> TemplateLibraryStatusResponse:
    status = get_template_library_status()
    return TemplateLibraryStatusResponse(session_id=session_id, **status)


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
    merged = list(by_id.values())
    return merged, appended, updated


def fill_template_library(req: TemplateLibraryFillRequest) -> TemplateLibraryFillResponse:
    status = get_template_library_status()
    if req.config is None or not (req.config.openai_api_key or "").strip() or not (req.config.model or "").strip():
        return TemplateLibraryFillResponse(session_id=req.session_id, **status)
    library = load_template_library()
    system_prompt = prompt_table.get_text(
        "template.library.fill.system",
        "Return one JSON object only. Add missing RPG item, equipment, and interactable templates. Do not overwrite existing non-empty fields.",
    )
    user_prompt = prompt_table.render(
        "template.library.fill.user",
        (
            "输出 JSON 对象，字段固定为 "
            '{"item_definitions":[],"equipment_definitions":[],"interactable_templates":[]}。'
            "请基于当前世界常见需求，补充少量缺失模板。已有 item definitions: $item_defs。"
            "已有 equipment definitions: $equipment_defs。已有 interactable templates: $interactable_defs。"
            "不要覆盖已有非空字段，优先补充基础消耗品、基础武器护甲、容器、门、机关、hazard、线索。"
        ),
        item_defs="|".join(item.definition_id for item in library.item_definitions[:40]),
        equipment_defs="|".join(item.definition_id for item in library.equipment_definitions[:40]),
        interactable_defs="|".join(item.template_id for item in library.interactable_templates[:40]),
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
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        return TemplateLibraryFillResponse(session_id=req.session_id, **status)
    payload = json.loads(raw)

    directory = _template_dir()
    item_path = directory / ITEM_DEFINITIONS_FILE
    equipment_path = directory / EQUIPMENT_DEFINITIONS_FILE
    interactable_path = directory / INTERACTABLE_TEMPLATES_FILE

    merged_items, appended_items, updated_items = _merge_rows(_read_rows(item_path), list(payload.get("item_definitions") or []), key_field="definition_id")
    merged_equipment, appended_equipment, updated_equipment = _merge_rows(_read_rows(equipment_path), list(payload.get("equipment_definitions") or []), key_field="definition_id")
    merged_interactables, appended_interactables, updated_interactables = _merge_rows(_read_rows(interactable_path), list(payload.get("interactable_templates") or []), key_field="template_id")

    _write_rows(item_path, ITEM_DEFINITION_COLUMNS, merged_items)
    _write_rows(equipment_path, EQUIPMENT_DEFINITION_COLUMNS, merged_equipment)
    _write_rows(interactable_path, INTERACTABLE_TEMPLATE_COLUMNS, merged_interactables)
    mark_template_library_filled()
    status = get_template_library_status()
    return TemplateLibraryFillResponse(
        session_id=req.session_id,
        appended_item_definition_ids=appended_items,
        appended_equipment_definition_ids=appended_equipment,
        appended_interactable_template_ids=appended_interactables,
        updated_item_definition_ids=updated_items,
        updated_equipment_definition_ids=updated_equipment,
        updated_interactable_template_ids=updated_interactables,
        **status,
    )
