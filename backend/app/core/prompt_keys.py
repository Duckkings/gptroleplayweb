from __future__ import annotations


class PromptKeys:
    CHAT_CONTEXT_RULE = "chat.context_rule.v2"
    CHAT_NARRATION_RULE = "chat.narration_rule.v2"
    CHAT_TURN_CONTEXT_USER = "chat.turn.context.user.v1"
    NPC_GREET_USER = "npc.greet.user.v2"
    NPC_CHAT_USER = "npc.chat.user.v2"
    NPC_PUBLIC_TARGETED_USER = "npc.public.targeted.user.v2"
    NPC_PUBLIC_BYSTANDER_USER = "npc.public.bystander.user.v2"
    TEAM_CHAT_USER = "team.chat.user.v1"
    TEAM_PUBLIC_REACTION_USER = "team.public.reaction.user.v2"
    SCENE_ACTOR_INTENT_USER = "scene.actor.intent.user.v1"
    ROLE_DESIRE_SEED_USER = "role.desire.seed.user.v1"
    ROLE_DESIRE_SURFACE_USER = "role.desire.surface.user.v1"
    COMPANION_STORY_SEED_USER = "companion.story.seed.user.v1"
    COMPANION_STORY_SURFACE_USER = "companion.story.surface.user.v1"
    REPUTATION_BEHAVIOR_USER = "reputation.behavior.user.v1"
    ENCOUNTER_GENERATE_USER = "encounter.generate.user.v2"
    ENCOUNTER_STEP_USER = "encounter.step.user.v2"
    ENCOUNTER_BACKGROUND_TICK_USER = "encounter.background.tick.user.v1"
    ENCOUNTER_ESCAPE_USER = "encounter.escape.user.v1"
    ENCOUNTER_REJOIN_USER = "encounter.rejoin.user.v1"
    ENCOUNTER_DEBUG_SUMMARY_USER = "encounter.debug.summary.user.v1"
    ENCOUNTER_OUTCOME_PACKAGE_USER = "encounter.outcome.package.user.v1"


REQUIRED_PROMPT_KEYS: tuple[str, ...] = (
    PromptKeys.CHAT_CONTEXT_RULE,
    PromptKeys.CHAT_NARRATION_RULE,
    PromptKeys.CHAT_TURN_CONTEXT_USER,
    PromptKeys.NPC_GREET_USER,
    PromptKeys.NPC_CHAT_USER,
    PromptKeys.NPC_PUBLIC_TARGETED_USER,
    PromptKeys.NPC_PUBLIC_BYSTANDER_USER,
    PromptKeys.TEAM_CHAT_USER,
    PromptKeys.TEAM_PUBLIC_REACTION_USER,
    PromptKeys.SCENE_ACTOR_INTENT_USER,
    PromptKeys.ROLE_DESIRE_SEED_USER,
    PromptKeys.ROLE_DESIRE_SURFACE_USER,
    PromptKeys.COMPANION_STORY_SEED_USER,
    PromptKeys.COMPANION_STORY_SURFACE_USER,
    PromptKeys.REPUTATION_BEHAVIOR_USER,
    PromptKeys.ENCOUNTER_GENERATE_USER,
    PromptKeys.ENCOUNTER_STEP_USER,
    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
    PromptKeys.ENCOUNTER_ESCAPE_USER,
    PromptKeys.ENCOUNTER_REJOIN_USER,
    PromptKeys.ENCOUNTER_DEBUG_SUMMARY_USER,
    PromptKeys.ENCOUNTER_OUTCOME_PACKAGE_USER,
)
