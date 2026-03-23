# Capability Snapshot 2026-03-23

## Public Turn

- Settlement output now renders as per-actor dialogue cards instead of debug-style text blocks.
- Narrative panes prefer cleaned `gm_resolution_summary` and strip JSON wrappers such as `{"outcome": ...}`.
- `entry.check` is rendered whenever it exists; `non_world_exchange` no longer suppresses visible dice results.
- Public-turn text uses the dim gray reading layer used by encounter-side copy; only the main current-output narrative gets increased line-height.

## Damage And Death

- Added `damage_resolution` scene events with source / target / damage / HP-before / HP-after / life-status metadata.
- Main output and public-turn narrative now show dedicated inline damage cards.
- Party preview cards enter a red-edge shake state after receiving new damage and stay highlighted until the next player-driven input starts.
- Added `POST /api/v1/debug/player/zero-hp` to force the player into the main-chat death-save pending flow.
- Main-chat pending continuation now restores and resolves `awaiting_player_death_save`.
- Invalid saves where the player is `HP <= 0` but still `healthy` are auto-repaired back to full HP during consistency reconciliation.

## NPC Capability Resources

- World NPCs and teammate NPCs continue to share `NpcRoleCard + PlayerStaticData`.
- NPC sheets now consistently carry `war_arts`, `martial_points_current`, `martial_points_maximum`, and `war_art_cooldowns`.
- NPC prompt briefs now include compact capability summaries covering known spells, war arts, spell slots, martial points, and equipped gear.
- Added read APIs / tools:
  - `GET /api/v1/template-library/definitions`
  - `GET /api/v1/roles/{role_id}/capabilities`
  - `get_template_library_definitions`
  - `get_role_capability_snapshot`

## Template Library

- Spell and war-art template rows now support `recommended_classes`, `min_level`, and `npc_priority`.
- Visible spell / war-art text in CSV has been migrated to Simplified Chinese.
- AI fill now requires:
  - Simplified Chinese visible fields
  - ASCII snake_case `definition_id`
  - Rejection of English-only visible rows

## Talkative Recovery

- NPC single-chat talkative recovery is now explicitly tied to completed public-turn settlements.
- Each public-turn round completion restores `+4` talkative once per NPC, deduped by `talkative_recovery_round_cursor`.
- Legacy archived-turn recovery remains as a compatibility fallback for older saves and tests.

## Teammate Memory Summaries

- Teammate private chat no longer auto-generates memory after every reply.
- The player can generate a teammate memory summary manually from the teammate-chat header or when closing teammate chat.
- Close-flow behavior:
  - no unsummarized exchange: close directly
  - unsummarized exchange exists: prompt for `生成摘要后关闭 / 直接关闭 / 继续聊天`
- Summary generation failures are surfaced to the player and do not create fallback memory.
- Teammate memory summaries are stored in `NpcRoleCard.private_chat_memories`.
- Public-turn teammate prompting consumes only the latest 12 summary memories, not raw private-chat logs.

## Resource Tool Update
- `get_role_capability_snapshot` now surfaces stable `definition_id` values for known spells and war arts.
- `actor_adjust_resource` is available for explicit spell-slot / martial-point consume and recover flows on `player` or `role` actors.
