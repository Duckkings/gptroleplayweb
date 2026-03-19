# Public Turn Capability Snapshot (2026-03-19)

## Implemented

- Public turn now uses Scheme A for AI-only progression:
  - one batch planner call per AI-only segment
  - deterministic backend settlement for checks / opposed / impacts
  - one batch narrator call per AI-only segment
- Public-turn stream routes now emit per resolved segment instead of replaying only after the full request finishes.
- Embedded public-turn `action_check()` no longer falls back into `_ai_action_plan()` or `_ai_action_resolution_text()`.
- Player-originated settlements and opposed-resume settlements are seeded into the same running narration flow before later AI settlements or `gm_push`.
- Existing split presentation remains intact:
  - `initiative_order`
  - `settlement_entries`
  - `narrative_entries`
  - `accumulated_narration`

## Compatibility

- Public routes are unchanged:
  - `/api/v1/public-turn/entry`
  - `/api/v1/public-turn/entry/stream`
  - `/api/v1/public-turn/continue`
  - `/api/v1/public-turn/continue/stream`
  - `/api/v1/public-turn/reaction-check`
  - `/api/v1/public-turn/reaction-check/stream`
  - `/api/v1/public-turn/opposed-check`
  - `/api/v1/public-turn/opposed-check/stream`
- No new save shard was introduced.
- Existing public-turn presentation fields remain the persisted contract.

## Verification

- `python -m py_compile backend/app/services/public_turn_runtime.py backend/app/services/public_turn_segment_service.py backend/app/services/public_turn_narration_service.py backend/app/services/public_turn_service.py backend/app/services/public_scene_service.py backend/app/services/world_service.py backend/app/models/schemas.py`
- `python -m compileall backend/app`
- `PYTHONPATH=backend python -m unittest backend.tests.test_public_turn_runtime`
- `npx tsc -b`
- `npm run build`
