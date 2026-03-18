# Public Turn Capability Snapshot (2026-03-18)

## Implemented

- Backend public turn models were added to `schemas.py` and aligned with frontend types.
- Mainline routes now expose `/api/v1/public-turn/*` sync and stream endpoints.
- Public turn runtime supports round entry, initiative transition, player action submission, AI resolution, situation advancement, reaction pause/resume, and impact generation.
- Existing public scene and encounter logic is reused under the new runtime where practical.
- Frontend main chat composer was replaced by `PublicTurnPanel` for public scenes.
- God Mode idle injection is supported from the main UI.
- Reaction modal resume now supports `public_turn` flow.

## Compatibility

- `/api/v1/scene/public-state` remains available as a derived read-only view.
- `/api/v1/pending-turns/current` and cancel endpoints remain available for reaction recovery and compatibility.
- `/api/v1/chat` and `/api/v1/chat/stream` remain in the codebase for legacy/debug use, but mainline public scenes are blocked unless God Mode is active.
- Debug battle APIs and modal remain available and are no longer the default mainline public conflict flow.

## Known Gaps

- Frontend event cards for new `public_turn_*` kinds still rely mostly on generic rendering.
- The runtime still pragmatically reuses parts of the existing public scene engine instead of a fully isolated second-generation implementation.
- Full automated regression coverage for the new flow has not been added yet.

## Verification

- `python -m compileall backend/app`: passed
- `npx tsc -b`: passed
- `npm run build`: blocked locally by `esbuild` spawn `EPERM`
- `python -m unittest discover -s backend/tests` with `PYTHONPATH=backend`: environment failures unrelated to this feature still exist (`itsdangerous` missing, temp dir permission issues, missing prompt keys)
