# Public Turn Capability Snapshot 2026-03-20 v7

## Scope

This snapshot records the currently implemented public-turn interaction updates delivered in v7.

## Implemented

- Public-turn interaction prompt no longer shows or persists `stakes_summary`.
- Public-turn interaction target is now unified:
  - action target
  - prompt target
  - responding actor
  must match
- `speech_target` is kept for narration only and no longer affects routing.
- Public-turn interaction now distinguishes:
  - `non_world`
  - `world`
- `non_world -> non_world` exchanges no longer create a DC or opposed flow.
- One-step alternated interaction is supported for:
  - source `non_world`
  - target response `world`
  - reverse target equals original source
- Player interaction modal no longer exposes cancel.
- Player can submit `不做任何行动`, which is stored as:
  - `response_kind="no_action"`
  - `world_impact_type=non_world`
- Invalid reverse targeting no longer destroys the pending interaction state.
- Settlement payloads now persist:
  - source / target world-impact fields
  - exchange kind
  - alternation depth
  - target response kind
- Frontend settlement cards now hide check display for `non_world_exchange`.

## Notes

- Opposed prompt still keeps opposed-context summary; the v7 removal only applies to the interaction prompt.
- Alternation is limited to one reversal and does not allow third-party reverse targeting.
