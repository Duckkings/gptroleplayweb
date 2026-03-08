# Team Technical Addendum 2026-03-08

## Design Sources
- `docs/design/gamedesign/teamdesign.md`
- `docs/design/gamedesign/roledesign.md`

## Goal
- Bring team NPCs back under the same NPC rule set instead of treating them as special shallow companions.
- Ensure debug-generated teammates are complete NPC role cards, not partial placeholders.

## Implemented Alignment

### Shared role card contract
- Team members continue to reference `NpcRoleCard`.
- No separate “team-only NPC card” exists.
- Team NPCs therefore inherit:
  - secret
  - likes
  - talkative value
  - dialogue logs
  - relation memory
  - full 5E profile sheet

### Debug teammate generation
- Backend source: `backend/app/services/team_service.py`
- `generate_debug_teammate(...)` now uses `_build_debug_team_role(...)`
- `_build_debug_team_role(...)` reuses:
  - `_build_npc_flavor(...)`
  - `_build_npc_likes(...)`
  - `_build_npc_talkative_maximum(...)`
  - `_build_npc_profile(...)`
  - `_ensure_npc_role_complete(...)`

### Result
- Debug teammates now generate with:
  - flavor text
  - secret
  - likes
  - talkative values
  - inventory + equipment
  - race / class / background / proficiencies

## Team NPC Chat Positioning

### Single chat
- Team NPC single chat still enters the normal NPC private-chat flow from frontend.
- That means team NPCs now follow the same single-chat rules as normal NPCs:
  - no auto-greet requirement
  - action-only / speech-only input allowed
  - action/request can trigger checks
  - action reaction + speech reply are returned separately
  - talkative value is consumed

### Team chat
- `team_chat(...)` remains the group-response path.
- It is still a lightweight multi-member reaction system, not a full group director.
- Existing team chat behavior is preserved:
  - each member returns a short `speech` or `action`
  - replies are written into each role card’s `dialogue_logs`
  - team reactions are recorded into `team_state.reactions`

### Talkative difference
- In-team NPCs consume talkative value slower than normal NPCs during private chat.
- This is implemented in the shared world-service talkative calculation, not duplicated in team service.

## Frontend Inspection
- `NpcPoolPanel` now shows the fields needed to audit team NPC completeness.
- Team panel still reuses role-card data instead of maintaining a second inventory/state source.

## Tests
- `backend/tests/test_team_service.py`
  - added regression coverage for debug teammate complete profile generation

## Known Gaps
- Team private chat does not yet have a dedicated “companion conversation mode”.
- Team NPCs do not yet expose a separate faster-recovery curve beyond the current reduced-consumption rule.
- Team chat still does not coordinate cross-member conversational turns or interruption logic.
