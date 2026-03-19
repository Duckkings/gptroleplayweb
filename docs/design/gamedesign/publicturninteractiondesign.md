# Public Turn Interaction Design

This document is the canonical design reference for public-turn interaction, contest routing, and player response handling.

## 1. Core Rule

- `action_target` is the only real interaction target.
- The prompt target, response target, and routing target must all match `action_target`.
- `speech_target` is narration-only metadata. It can change how text is shown, but it must never decide who responds.

## 2. Target Resolution

- Use explicit action target fields first.
- If the action itself is a pure social / language interaction and has no explicit `action_target`, a unique `speech_target` may be promoted into `action_target`.
- If `action_target != player`, the runtime must not open a player interaction modal.
- If planner output requests `player_interaction` or `player_opposed` while `action_target != player`, the runtime ignores that planner suggestion and reroutes using the real target.

## 3. Interaction Prompt

- `PublicTurnInteractionPrompt` no longer contains `stakes_summary`.
- The interaction modal shows:
  - source actor
  - target
  - source action
  - source speech
  - speech addressee only when different from target
- The interaction modal no longer has a cancel path that leaves the round suspended.

## 4. World Impact Classification

- `non_world`
  - greeting
  - conversation
  - verbal provocation
  - expressive gestures
  - light social contact without positional or control impact
- `world`
  - strike
  - shove
  - grab
  - restrain
  - drag
  - block movement
  - forceful spell use
  - item / environment / body-state changes

Classification source:

- AI actor action payload
- AI target response payload
- dedicated player-response classifier
- player `no_action` shortcut, which is forced to `non_world`

## 5. Three Interaction Outcomes

### 5.1 `non_world -> non_world`

- no DC
- no opposed roll
- both sides are written into settlement and narration only

### 5.2 `non_world -> world`

This triggers alternation only when the target-side `world` response points back to the original source actor.

Alternation rules:

- swap source and target once
- `alternation_depth = 1`
- no second alternation is allowed
- if the target-side `world` response points to a third party, alternation is rejected

### 5.3 `world -> *`

- normal public-turn interaction flow
- target responds first
- backend classifies opposed vs non-opposed
- if non-opposed, the acting side resolves through static DC or no-roll settlement depending on the planned action

## 6. Contest Routing

- Role-to-role targeted actions always enter interaction assessment first.
- Public-turn `player_reaction` is reserved for non-actor hazards only:
  - environment danger
  - GM push
  - world / scene hazard not originating from an actor target
- Actor-targeted hostility no longer jumps directly into `player_reaction`.

## 7. Player "No Action"

The interaction modal replaces cancel with `不做任何行动`.

Semantics:

- `response_kind = "no_action"`
- `action_text = ""`
- `speech_text = ""`
- `world_impact_type = non_world`

Design intent:

- the player still gives a valid response
- the interaction always reaches a legal terminal state
- the round can no longer get stuck in `awaiting_player_interaction`

Resolution behavior:

- source `non_world` + target `no_action` -> `non_world_exchange`
- source `world` + target `no_action` -> non-opposed world interaction; resolve the source action normally
- `no_action` never triggers alternation

## 8. Prompt And Save Fields

Interaction-related structures now carry:

- `source_world_impact_type`
- `alternation_depth`
- `interaction_mode`
- `response_kind`
- `interaction_exchange_kind`
- `target_response_kind`

These fields are required so interaction, alternation, replay, and narration stay consistent across pause / resume and save restore.

## 9. Frontend Rules

- Interaction modal:
  - no `风险`
  - no cancel button
  - has `不做任何行动`
- Opposed modal:
  - continues to show opposed context
  - should not expose a cancel path that leaves pending opposed state unresolved
- Settlement cards:
  - `non_world_exchange` hides check display
  - `alternated_exchange` marks that the interaction reversed once

## 10. Documentation Ownership

- This file owns detailed interaction rules.
- `publicturndesign.md` should keep only overview-level public-turn flow and link back here for interaction specifics.
