# Public Turn Capability Snapshot (2026-03-20 v3)

## Scope

- Player-action-only AI reaction settlements
- Player/team-only zone reputation ownership
- Deterministic player narration fragments that include AI reaction text

## Implemented

- `NPC反应 / 队友反应` now only appear after player-submitted public-turn actions.
- Public-turn NPC reactions now store:
  - `reaction_action`
  - `reaction_speech`
  - `reaction_text` compatibility mirror
- Public-turn team reactions now store:
  - `reaction_action`
  - `reaction_speech`
  - `reaction_text` compatibility mirror
- Non-player actor settlements no longer populate:
  - `relation_deltas`
  - `team_affinity_deltas`
- Team actors no longer gain affinity/trust from their own actions.
- Zone reputation is now emitted only for:
  - player actions
  - team actions
- Deterministic narration formatting now appends AI NPC/team reactions to player settlement fragments.
- Stream emission remains settlement-ordered and now tolerates direct fragment generation from the settlement if the cached narrative entry is missing.

## Verified

- `PYTHONPATH=backend python -m unittest backend.tests.test_public_turn_runtime`
- `npm run build`

## Boundaries

- Main chat and legacy public-scene reaction fallbacks still exist outside the public-turn path.
- Public-turn reaction AI may legally return empty text; mechanical deltas continue to resolve independently.
