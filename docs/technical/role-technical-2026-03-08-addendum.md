# Role Technical Addendum 2026-03-08

## Design Sources
- `docs/design/gamedesign/roledesign.md`
- `docs/design/gamedesign/teamdesign.md`

## Scope
- Align NPC single-chat behavior with the latest `roledesign`.
- Add public-area NPC reaction rules into the gameplay loop.
- Ensure normal NPCs and team NPCs share the same complete role-card generation path.
- Add explicit save-repair rules so old saves are upgraded on load.

## Data Model Changes

### `NpcRoleCard`
- Added `secret`
- Added `likes`
- Added `talkative_current`
- Added `talkative_maximum`
- Added `last_private_chat_at`

### `NpcChatResponse`
- Added `action_reaction`
- Added `speech_reply`
- Added `talkative_current`
- Added `talkative_maximum`

## NPC Generation Rules

### Unified generation entry
- Backend source: `backend/app/services/world_service.py`
- Shared entry: `_build_npc_profile(...)` + `_ensure_npc_role_complete(...)`
- Trigger points:
  - Area NPC creation in `_ensure_role_pool_from_area(...)`
  - Save load in `get_current_save(...)`
  - Team debug NPC creation via team service

### Complete profile requirements
- Every NPC must have non-empty:
  - `personality`
  - `speaking_style`
  - `appearance`
  - `background`
  - `cognition`
  - `alignment`
  - `secret`
  - `likes`
- Every NPC profile must have usable 5E sheet data:
  - `race`
  - `char_class`
  - `background`
  - `alignment`
  - `saving_throws_proficient`
  - `skills_proficient`
  - `languages`
  - `tool_proficiencies`
  - `features_traits`
  - `backpack.items`
  - `equipment_slots.weapon_item_id`
  - `equipment_slots.armor_item_id`
  - class-appropriate `spells` / `spell_slots` when applicable

### Save upgrade policy
- Old saves do not require migration scripts.
- On load, `_ensure_npc_role_complete(...)` fills missing NPC flavor fields and missing sheet data in-place.
- Existing non-empty custom values are preserved where possible.

## NPC Single-Chat Rules

### Frontend behavior
- Source: `frontend/src/App.tsx`
- Entering NPC chat no longer auto-calls `npc_greet`.
- Entering NPC chat now immediately shows an input-ready state.
- NPC mode input rule:
  - action only: allowed
  - speech only: allowed
  - both: allowed
- Main chat still keeps the old requirement of action + speech together.

### Action/request checks
- In NPC mode, frontend runs `ActionCheck` before `npc_chat` when:
  - action text is present
  - or speech matches request-style wording
- The check result is embedded into `player_intent_v1.action_check_result`.
- Backend NPC prompt consumes action text, speech text, and check result together.

### Backend response protocol
- Backend source: `backend/app/services/world_service.py::npc_chat`
- NPC prompt now returns JSON:
  - `action_reaction`
  - `speech_reply`
  - `relation_tag`
- Final visible reply is composed from `action_reaction + speech_reply`.
- NPC may return only action and no speech.

### Talkative value
- Recover point:
  - recover on each new private chat round, based on world-clock delta from `last_private_chat_at`
- Consume point:
  - every single-chat round changes `talkative_current`
  - in-team NPCs consume slower than non-team NPCs
- Positive content can partially recover value:
  - speaking about `likes`
  - cooperative / grateful wording
- When `talkative_current <= 0`:
  - NPC returns an ignore-style action reaction
  - no longer actively continues the conversation

## Public-Area NPC Reaction Rules

### Entry points
- `POST /api/v1/chat`
- `POST /api/v1/chat/stream`
- `action_check(...)`

### Runtime behavior
- Backend source: `apply_public_npc_reactions_in_save(...)`
- Applies only in public area context, not NPC private chat.
- Reads current sub-zone visible NPCs.
- Excludes `state == "in_team"` members from public-area reactions.
- Writes:
  - player relation updates
  - `cognition_changes` public memory
  - `attitude_changes`
  - `game_logs(kind=public_npc_reaction)`
- Appends a visible summary block to GM/action response:
  - `【周围NPC反应】 ...`

### Current limit
- “NPC主动聊天视作遭遇” is not yet promoted into full encounter-state creation in this round.
- Current implementation stops at public reaction summary + memory/favor writeback.

## Team NPC Alignment
- Team NPCs still use `NpcRoleCard`; no separate lightweight team-only role schema is introduced.
- Team debug NPCs now use the same completion pipeline as normal NPCs.
- Team NPC single-chat continues to use the shared `npc_chat(...)` path.
- Team NPC talkative loss is reduced relative to non-team NPCs.

## Frontend Visibility
- `frontend/src/components/NpcPoolPanel.tsx` now exposes:
  - `secret`
  - `likes`
  - `talkative_current / talkative_maximum`
  - race / class / languages / skills / traits / spells
- This is intended as the inspection surface for verifying NPC completeness.

## Regression Coverage
- `backend/tests/test_role_system.py`
  - old-save NPC completion
  - public NPC reaction memory writeback
- `backend/tests/test_team_service.py`
  - debug teammate complete profile generation

## Known Gaps
- `npc_greet` endpoint is retained for compatibility, but the main frontend no longer depends on it.
- NPC leave-by-intent currently uses frontend intent detection, not a dedicated AI tool or server-side state machine.
- Public-area NPC reactions are heuristic and rule-based; they are not yet a full “area crowd director” system.
