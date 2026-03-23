# 2026-03-20 AI Required / Public-Turn Protocol Addendum

## Scope

- remove `no-AI fallback` from the newly migrated AI gameplay paths
- downlink control-enum pools to AI prompts
- stop silently normalizing illegal AI control enums
- add public-turn protocol-repair pause / continue flow
- add public-turn targeted actor/speech prompt context

## Backend

- Added shared protocol helpers in `app/services/ai_protocol_contract_service.py`.
- Public-turn now stages first-pass enum violations into `awaiting_protocol_repair`.
- Added:
  - `POST /api/v1/public-turn/protocol-repair`
  - `POST /api/v1/public-turn/protocol-repair/stream`
- Non-public-turn AI enum contracts now repair once inline with the same model.
- `SceneEvent.kind` now accepts `system_notice` for scene-interaction execution events.

## Frontend

- `PendingTurnContinueResponse.status` now supports `awaiting_protocol_repair`.
- Public-turn stream handlers now recognize `protocol_repair_required`.
- Frontend auto-continues public-turn protocol repair and shows a transient system notice.

## Prompt Contract

- Stable English ids are the only allowed control values.
- Public-turn targeted helper text is prompt/debug only:
  - `{actor}对{target}的行为：...`
  - `{actor}自己的行为：...`
  - `{actor}对{speech_target}说：...`
  - `{actor}说：...`

## Verification

- `npm run build`
- `python -m unittest backend.tests.test_public_turn_runtime backend.tests.test_team_service backend.tests.test_quest_fate_encounter`
- `python -m unittest backend.tests.test_ai_protocol_contract_service`
