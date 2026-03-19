# Public Turn Capability Snapshot (2026-03-20 v2)

## Scope

- Deterministic public-turn narration from settlement order
- Round-end single GM push card with backend `1d6`
- Priority-action initiative declaration fix
- Public-turn AI fallback removal for actor / interaction output

## Implemented

- `PublicTurnSettlementEntry` now distinguishes actor entries and GM push entries through `entry_kind`.
- `PublicTurnGmPushResult` is persisted on settlements, rounds, and presentation payloads.
- Round narration is rebuilt from settlement order instead of AI narration stitching.
- Actor settlements no longer surface GM description text.
- Empty AI actor output now produces an empty actor settlement card instead of fallback prose.
- Player `优先行动` now rolls initiative together with in-scene NPC / team / temporary encounter actors.
- Same-round GM push now rolls backend `1d6`:
  - `1-4` no extra event
  - `5` environment change
  - `6` extra persistent scene NPC intervention with one immediate same-round action
- Public-turn interaction auto-response no longer uses fallback text.

## Verified

- `PYTHONPATH=backend python -m unittest backend.tests.test_public_turn_runtime`
- `npm run build`

## Known Boundaries

- Main chat and legacy public scene paths still retain their older fallback helpers; the fallback removal in this snapshot is scoped to public-turn execution only.
- `data/ai-prompts.csv` may still contain older narration prompt rows, but runtime no longer depends on them for public-turn round narration.
