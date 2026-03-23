# Public Turn Capability Snapshot (2026-03-18)

## Implemented

- Backend public turn models were added to `schemas.py` and aligned with frontend types.
- Mainline routes now expose `/api/v1/public-turn/*` sync and stream endpoints.
- Public turn runtime now follows the corrected `4.2` flow:
  - `next_round` runs AI-only initiative judgment/execution first, then pauses at the player `normal_advancement` slot.
  - `initiative` inserts the player into initiative order and pauses only when the initiative cursor reaches the player.
- Public turn runtime supports player action submission, AI resolution, situation advancement, reaction pause/resume, and impact generation.
- Existing public scene and encounter logic is reused under the new runtime where practical.
- Frontend main chat composer was replaced by `PublicTurnPanel` for public scenes.
- God Mode idle injection is supported from the main UI.
- Reaction modal resume now supports `public_turn` flow.
- Player public-turn actions now:
  - write visible NPC relation updates
  - write teammate affinity/trust updates
  - aggregate round reputation through impact settlement
  - emit explicit NPC / teammate reaction rows and scene events
- Public-turn player checks now go through the frontend roll modal and submit `player_action_check` into `/api/v1/public-turn/continue`.
- Public-turn direct physical conflict prompts now support opposed check planning via `resolution_rule="opposed_actor"`.
- Public-turn main output is now split into:
  - left structured settlement (`initiative_order`, `settlement_entries`)
  - right whole-round narration (`round_narration`)
- Public-turn narration no longer mixes phase/pause prompts or raw dice/DC text into the prose channel.
- Public-turn narration now streams per settlement fragment instead of waiting for whole-round post-processing.
- Round end now uses explicit `gm_push` completion behavior instead of the old `situation_advancement`-style implicit finish.
- Public-turn paused continuations now support both:
  - `awaiting_reaction`
  - `awaiting_opposed`
- `NPC -> player` non-attack opposed actions now pause into a dedicated public-turn opposed flow.
- Public-turn opposed resume can stream back into:
  - normal completion
  - another reaction pause
  - another opposed pause
- Current main output now stays visible after archive until the next output replaces it.
- Sub-zone context is expected to render public-turn records in split settlement/narration form and default to folded viewing.
- Public-turn runtime now preserves per-settlement narrative fragments in the round presentation payload (`narrative_entries`, `accumulated_narration`).

## Compatibility

- `/api/v1/scene/public-state` remains available as a derived read-only view.
- `/api/v1/pending-turns/current` and cancel endpoints remain available for reaction recovery and compatibility.
- `/api/v1/chat` and `/api/v1/chat/stream` remain in the codebase for legacy/debug use, but mainline public scenes are blocked unless God Mode is active.
- Debug battle APIs and modal remain available and are no longer the default mainline public conflict flow.

## Known Gaps

- The runtime still pragmatically reuses parts of the existing public scene engine instead of a fully isolated second-generation implementation.
- Full suite `python -m unittest discover -s backend/tests` still has unrelated environment failures outside this feature area.

## Verification

- `python -m compileall backend/app`: passed
- `python -m unittest backend.tests.test_public_turn_runtime` with `PYTHONPATH=backend`: passed
- `npx tsc -b`: passed
- `npm run build`: passed
- `python -m py_compile backend/app/services/public_turn_service.py backend/app/api/routes.py backend/app/services/public_turn_runtime.py`: passed
- `python -m unittest discover -s backend/tests` with `PYTHONPATH=backend`: environment failures unrelated to this feature still exist (`itsdangerous` missing, temp dir permission issues, missing prompt keys)
