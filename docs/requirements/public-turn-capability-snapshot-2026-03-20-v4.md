# Public Turn Capability Snapshot 2026-03-20 v4

- Public-turn settlements now separate action target from speech addressee.
- Actor-targeted hostility against the player now pauses for player response input instead of jumping straight to `player_reaction`.
- NPC-to-NPC and team-to-NPC targeted actions now use the same source-action / target-response / contest-classification flow.
- Player post-action reactions now carry structured tone, focus target, and speech target metadata.
- Warning / hostile reactions are server-clamped so they cannot emit obviously positive large relation or affinity deltas.
- Deterministic narration and pause previews now render target-aware and addressee-aware text.
