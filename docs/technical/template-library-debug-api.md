# Template Library Debug API
Updated: `2026-03-22`

## Fill Endpoint

`POST /api/v1/debug/template-library/fill`

Request fields:

- `session_id`
- `config`
- `fill_scope = "all" | "spells"`
- `spell_fill_count`

Behavior:

- `fill_scope = "all"` keeps the original strict whole-library fill behavior.
- `fill_scope = "spells"` is spell-only mode.
- In spell-only mode, the backend only asks the model for `spell_definitions`.
- In spell-only mode, the backend only parses `spell_definitions`.
- Malformed `item_definitions`, `equipment_definitions`, or `interactable_templates` payloads are ignored in spell-only mode instead of failing the whole request.
- In `fill_scope = "all"`, the backend also reads and writes `war_art_definitions`.
- `spell_definitions` now includes `spell_cost`.
- `war_art_definitions` uses:
  `definition_id, name, attack_mode, scaling_ability, martial_cost, cooldown_rounds, damage_dice, damage_bonus, damage_type, area_shape, area_radius_m, area_length_m, self_target_policy, description, resolution_notes`

Status payload:

- `TemplateLibraryStatusResponse` includes `war_art_definition_count`.
- `TemplateLibraryFillResponse` includes appended and updated war-art id lists.

Rationale:

- The debug panel now has a dedicated spell-library fill entry.
- Spell-only fill must not fail because the model produced unrelated non-spell rows in the old shared payload format.
- Whole-library fill must stay aligned with the runtime template bundle after `war_art_definitions.csv` was added.
