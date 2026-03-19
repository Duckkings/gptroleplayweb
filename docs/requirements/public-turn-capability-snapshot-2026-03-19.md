# Public Turn Capability Snapshot (2026-03-19)

## Added

- player-targeted non-attack interactions now pause at `awaiting_player_interaction`
- player response text is collected before deciding whether the exchange becomes opposed
- deterministic consent routing:
  - `rejected` -> opposed
  - `accepted` -> non-opposed
  - `ambiguous` -> non-opposed by default
- AI target actors now generate a lightweight response before non-player interaction resolution is classified
- structured interaction target metadata is stored in directive / round / settlement payloads
- modal minimize / restore is available for blocking gameplay modals while keeping main chat submission locked

## Fixed

- public-turn target resolution no longer locks onto the player just because the action text mentions the player
- ally-help and similar cooperative interactions no longer auto-upgrade into opposed checks without a rejecting target response
- public-turn interaction state now restores from saved round state without relying on pending-turn staging

## Verified

- `python -m unittest backend.tests.test_public_turn_runtime`
- `npm run build`
