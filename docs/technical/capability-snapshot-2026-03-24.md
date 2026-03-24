# Capability Snapshot - 2026-03-24

This snapshot records the current implemented behavior in the local prototype.

## Chat And Reaction Flow

- Main chat, NPC chat, team chat, and public turn all remain supported.
- NPC private chat pending turns now support a single follow-up reaction continuation per reply chain.
- The pending-turn continuation payload now accepts optional player reaction action/speech text, and NPC continuation prompts can use that text when resolving the reply.
- Repeated reaction checks in the same continued reply are blocked on the backend.
- For npc_chat, the UI keeps the response inline in the teammate chat composer and suppresses the generic reaction-roll modal.

## Teammate Chat

- Teammate chat now uses current affinity and trust values as prompt context for NPC replies.
- Team relationship deltas are now primarily driven by AI output plus conversation context, with private chat deltas allowed in a wider range and trust still scaling off affinity.
- Strong break-up or severance cues now drive the relationship toward zero instead of leaving values unchanged.
- Private teammate chat in the UI now shows an inline reaction banner when a reaction check is pending, with the response submitted from the chat composer.
- Team reaction fallback logic no longer uses keyword-based player text or summary inspection to boost or reduce affinity/trust; it now stays neutral when AI output is unavailable.

## Reaction Checks

- NPC-chat reaction checks no longer expose success/failure hint text in the prompt contract.
- NPC-chat social checks now split into affinity-based social probing, trust-based request/command, and coercive pressure, with DC derived from the corresponding relationship value and coercive prompts floored at 13.
- NPC-chat and related public-scene actor prompts now keep contested incoming narration provisional instead of writing final escape/restrain outcomes too early.
- Public-turn teammate reaction prompts now allow larger affinity and trust deltas, and the server no longer compresses those values back into a tiny `-3..3` band.
- Public-turn NPC relation deltas now also use a wider outcome band for success and critical success/failure.
- The general public-turn opposed-flow interaction remains unchanged.
- Inventory item interactions now recognize display/show-to-NPC prompts as a separate `show_to_npc` path, keeping them from being rewritten as inspection or consuming the item like a normal use action.

## Debug Reset

- `POST /api/v1/debug/save-reset` now still preserves the map, player, and team structure while clearing the same encounter/public-turn/pending-turn/debug-memory state as before.
- The debug reset now also restores active team members' `affinity` and `trust` back to `50`.
- The linked active `NpcRoleCard.talkative_current` now resets back to `80` during the same reset flow, clamped to the role's maximum if needed.

## Verification

- Backend Python modules involved in the change compile successfully.
- Frontend production build succeeds.
