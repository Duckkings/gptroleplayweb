from __future__ import annotations

from typing import Callable, Iterable, TypeVar

from app.models.schemas import (
    SaveFile,
    SpellDefinition,
    TemplateLibraryDefinitionsRequest,
    TemplateLibraryDefinitionsResponse,
    WarArtDefinition,
)
from app.services.item_template_service import load_template_library

T = TypeVar("T")


def _clean(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalized_class_tokens(value: str | None) -> set[str]:
    clean = _clean(value)
    if not clean:
        return set()
    parts = {part for part in clean.replace("/", "|").replace(",", "|").split("|") if part}
    parts.add(clean)
    return parts


def _filter_by_ids(definitions: Iterable[T], definition_ids: set[str], *, key_getter: Callable[[T], str]) -> list[T]:
    if not definition_ids:
        return list(definitions)
    return [item for item in definitions if _clean(key_getter(item)) in definition_ids]


def _filter_by_role_class(
    definitions: Iterable[T],
    recommended_class: str | None,
    *,
    class_getter: Callable[[T], list[str]],
) -> list[T]:
    class_tokens = _normalized_class_tokens(recommended_class)
    if not class_tokens:
        return list(definitions)
    filtered: list[T] = []
    for item in definitions:
        rows = [_clean(row) for row in class_getter(item)]
        if not rows:
            filtered.append(item)
            continue
        if any(row in class_tokens or class_tokens.intersection(_normalized_class_tokens(row)) for row in rows):
            filtered.append(item)
    return filtered


def _filter_by_min_level(definitions: Iterable[T], min_level: int | None, *, level_getter: Callable[[T], int]) -> list[T]:
    if min_level is None:
        return list(definitions)
    return [item for item in definitions if int(level_getter(item) or 1) >= int(min_level)]


def _sort_by_priority(
    definitions: Iterable[T],
    *,
    priority_getter: Callable[[T], int],
    name_getter: Callable[[T], str],
) -> list[T]:
    return sorted(definitions, key=lambda item: (-int(priority_getter(item) or 0), str(name_getter(item) or "")))


def query_template_library_definitions(
    req: TemplateLibraryDefinitionsRequest,
    *,
    save: SaveFile | None = None,
) -> TemplateLibraryDefinitionsResponse:
    library = load_template_library()
    recommended_class = req.recommended_class
    min_level = req.min_level
    if save is not None and req.for_role_id:
        if req.for_role_id == save.player_static_data.player_id:
            sheet = save.player_static_data.dnd5e_sheet
        else:
            role = next((item for item in save.role_pool if item.role_id == req.for_role_id), None)
            sheet = role.profile.dnd5e_sheet if role is not None else None
        if sheet is not None:
            recommended_class = recommended_class or sheet.char_class
            min_level = min_level or int(sheet.level or 1)

    definition_ids = {_clean(item) for item in req.definition_ids if _clean(item)}
    spells: list[SpellDefinition] = []
    war_arts: list[WarArtDefinition] = []

    if req.kind in {"spell", "all"}:
        spell_defs = _filter_by_ids(library.spell_definitions, definition_ids, key_getter=lambda item: item.definition_id)
        spell_defs = _filter_by_role_class(spell_defs, recommended_class, class_getter=lambda item: item.recommended_classes)
        spell_defs = _filter_by_min_level(spell_defs, min_level, level_getter=lambda item: item.min_level)
        spells = _sort_by_priority(spell_defs, priority_getter=lambda item: item.npc_priority, name_getter=lambda item: item.name)[: req.limit]

    if req.kind in {"war_art", "all"}:
        war_art_defs = _filter_by_ids(library.war_art_definitions, definition_ids, key_getter=lambda item: item.definition_id)
        war_art_defs = _filter_by_role_class(war_art_defs, recommended_class, class_getter=lambda item: item.recommended_classes)
        war_art_defs = _filter_by_min_level(war_art_defs, min_level, level_getter=lambda item: item.min_level)
        war_arts = _sort_by_priority(war_art_defs, priority_getter=lambda item: item.npc_priority, name_getter=lambda item: item.name)[: req.limit]

    return TemplateLibraryDefinitionsResponse(
        session_id=req.session_id,
        kind=req.kind,
        spell_definitions=spells,
        war_art_definitions=war_arts,
    )
