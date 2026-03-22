# Debug Test Reset Capability Snapshot

Date: 2026-03-21

## Scope

This snapshot records the currently implemented local debug reset and encounter name-guard behavior.

## Implemented

- Added `POST /api/v1/debug/save-reset`.
- Added frontend Debug panel button `测试重置`.
- `测试重置` preserves map, player data, team members, quests, fate, reputation, world state, and ordinary game logs.
- `测试重置` invalidates active and queued encounters, clears current sub-zone public turn state, clears matching recent turn records, clears pending turn state, and clears teammate memory logs.
- Teammate `affinity`, `trust`, and `NpcRoleCard.relations` remain intact after reset.
- Encounter generation now enforces unique display names for `new_npc` and `temporary_npcs`.
- Duplicate encounter actor names are automatically rewritten to `原名（遭遇NPC）` or `原名（新NPC）`, with numeric suffixes when needed.
- Legacy bad saves with encounter temp NPC name collisions now receive runtime aliases in public scene and public turn candidate assembly.

## Not Changed

- `POST /api/v1/saves/clear` remains a full save wipe.
- Battle flow is outside the scope of `测试重置`.
- `encounter_state.history` remains readable and is not deleted by debug reset.
