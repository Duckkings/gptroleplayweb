# Public Turn Attack No-Text-Fallback Rule
Updated: `2026-03-21`

## Scope

This rule applies to public-turn attack assessment, attack response classification, attack template resolution, and public-turn attack damage lookup.

## Required Rule

- The backend must not classify public-turn attacks from free-form text with keyword lists.
- The backend must not resolve spell or weapon templates by string matching against player input, localized spell names, aliases, or raw action text.
- The backend must not infer AOE shape or attack basis from keyword detection such as `fireball`, `cone`, `sphere`, or similar text tokens.
- The backend must not infer `world_impact_type` or `effective_against_attack` from defense response text.

## Required AI Contract

- `attack_assessment` must return stable structured fields.
- When the action matches a known spell or weapon template, `attack_assessment` must return `attack_definition_id`.
- `attack_definition_id` must be selected from the template pools supplied in the prompt.
- If no listed template matches, `attack_definition_id` must be the empty string.
- `attack_response_classification` must explicitly return `world_impact_type`, `effective_against_attack`, and `defense_ability_used`.

## Backend Resolution Rule

- Template lookup is id-only.
- The backend may load template metadata by `attack_definition_id`.
- If `attack_definition_id` is empty or invalid, the backend must treat the template lookup as unresolved.
- When template lookup is unresolved, damage may use AI structured fallback, but the backend must still not perform text matching.

## Regression Requirement

- Tests must cover that a Chinese spell description does not become `aoe_attack` without AI structured output.
- Tests must cover that `id`-style model output is normalized to `definition_id` during template-library spell fill.
- Tests must cover that public-turn attack response classification without AI does not guess an effective defense from response wording.
