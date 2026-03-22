# Public Turn Capability Snapshot (2026-03-21 Attack Rework)

## Scope

This snapshot records the currently implemented public-turn attack model after the 2026-03-21 rework.

## Implemented

- Public-turn attacks now enter `attack_assessment` first.
- Attack classification is now:
  - `ordinary_action`
  - `targeted_attack`
  - `aoe_attack`
- `ordinary_action` falls back to the normal public-turn interaction flow.
- `targeted_attack` collects the target response before deciding whether to open attack defense.
- `aoe_attack` builds a threatened target pool from scene state and can reveal hidden targets.
- Player-targeted public-turn attacks no longer use the old `attack -> player_reaction` shortcut.
- Frontend now supports:
  - attack response modal
  - attack defense roll modal
  - pending restore for attack response / defense
- Settlement cards now expose attack fields from structured public-turn entries.
- Template library status now exposes spell definition counts.
- Debug panel now supports a dedicated spell-table fill action.

## Explicitly Deprecated

- The old attack-direct-to-reaction shortcut
- `interaction_resolution = "attack_flow"` as a new runtime output
- keyword-table routing for public-turn attack contest detection

## Compatibility

- Old settlement/history records remain readable.
- Old pending attack states are not migrated.
- Runtime reads may still encounter historical `attack_flow`, but new executions should not emit it.
