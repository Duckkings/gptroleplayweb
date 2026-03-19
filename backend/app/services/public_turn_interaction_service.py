import json
from dataclasses import dataclass
from typing import Any, Literal

from app.core.prompt_table import prompt_table
from app.models.schemas import ChatConfig, NpcRoleCard, PublicTurnActorType, PublicTurnWorldImpactType, SaveFile
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import world_service as world
from app.services.public_turn_candidates import actor_name_match

ConsentState = Literal["accepted", "rejected", "ambiguous", "not_applicable"]
ContestState = Literal["opposed", "non_opposed", "not_applicable"]

_TARGETED_INTERACTION_TOKENS = (
    "帮",
    "扶",
    "拉",
    "拖",
    "推",
    "拦",
    "按住",
    "压住",
    "摁住",
    "抓住",
    "抱住",
    "拖走",
    "拖开",
    "带走",
    "带离",
    "抢",
    "夺",
    "塞给",
    "递给",
    "夺下",
    "挡住",
    "阻止",
    "制止",
    "拽",
    "touch",
    "grab",
    "pull",
    "push",
    "drag",
    "block",
    "stop",
    "restrain",
    "help",
    "assist",
    "carry",
    "take",
    "give",
)
_REJECT_TOKENS = (
    "不",
    "不要",
    "别碰",
    "住手",
    "让开",
    "甩开",
    "挣开",
    "挣脱",
    "推开",
    "拦住",
    "不配合",
    "拒绝",
    "挡住",
    "反抗",
    "抗拒",
    "stop",
    "don't",
    "no",
    "refuse",
    "resist",
    "break free",
    "push away",
)
_ACCEPT_TOKENS = (
    "点头",
    "答应",
    "配合",
    "跟上",
    "扶住",
    "任由",
    "让他",
    "接受",
    "顺着",
    "照做",
    "同意",
    "愿意",
    "accept",
    "agree",
    "follow",
    "cooperate",
    "nod",
    "let",
)
_OPPOSE_TOKENS = (
    "反击",
    "顶回去",
    "扛住",
    "硬顶",
    "压回去",
    "撞开",
    "拽住",
    "夺回",
    "摁住",
    "扭住",
    "counter",
    "fight back",
    "hold ground",
    "brace",
    "strike back",
    "contest",
)
_NON_OPPOSE_TOKENS = (
    "后退",
    "让开",
    "退开",
    "顺势",
    "跟着",
    "退后",
    "move aside",
    "step back",
    "yield",
    "back off",
)
_WORLD_IMPACT_TOKENS = (
    "attack",
    "hit",
    "slap",
    "punch",
    "kick",
    "grab",
    "push",
    "pull",
    "drag",
    "restrain",
    "hold down",
    "block",
    "take",
    "snatch",
    "steal",
    "throw",
    "smash",
    "stab",
    "cast",
    "打",
    "扇",
    "推",
    "拉",
    "拽",
    "抓",
    "按住",
    "压住",
    "拖",
    "抢",
    "夺",
    "拦",
    "阻",
    "踹",
    "捅",
    "刺",
    "揍",
)
_SOCIAL_INTERACTION_TOKENS = (
    "hello",
    "hi",
    "greet",
    "talk",
    "warn",
    "taunt",
    "speak",
    "pat",
    "nod",
    "smile",
    "问好",
    "打招呼",
    "说",
    "挑衅",
    "警告",
    "轻拍",
    "拍了拍",
    "点头",
    "示意",
)


def _clean_line(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def infer_world_impact_type(
    *,
    action_type: str,
    action_summary: str,
    speech_text: str,
    explicit_value: str | None = None,
) -> PublicTurnWorldImpactType:
    clean_explicit = str(explicit_value or "").strip().lower()
    if clean_explicit == PublicTurnWorldImpactType.WORLD.value:
        return PublicTurnWorldImpactType.WORLD
    if clean_explicit == PublicTurnWorldImpactType.NON_WORLD.value:
        return PublicTurnWorldImpactType.NON_WORLD
    if str(action_type or "").strip().lower() == "attack":
        return PublicTurnWorldImpactType.WORLD
    combined = "\n".join(part.lower() for part in (_clean_line(action_summary), _clean_line(speech_text)) if part)
    if any(token in combined for token in _WORLD_IMPACT_TOKENS):
        return PublicTurnWorldImpactType.WORLD
    return PublicTurnWorldImpactType.NON_WORLD


def is_social_interaction(
    *,
    action_summary: str,
    speech_text: str,
    action_type: str,
) -> bool:
    if str(action_type or "").strip().lower() == "attack":
        return False
    combined = "\n".join(part.lower() for part in (_clean_line(action_summary), _clean_line(speech_text)) if part)
    if not combined:
        return False
    if any(token in combined for token in _WORLD_IMPACT_TOKENS):
        return False
    return any(token in combined for token in _SOCIAL_INTERACTION_TOKENS) or bool(_clean_line(speech_text))


@dataclass
class ResolvedInteractionTarget:
    actor_id: str
    name: str
    actor_kind: Literal["player", "npc"]
    actor_type: PublicTurnActorType
    role: NpcRoleCard | None = None
    actor_row: dict[str, object] | None = None


@dataclass
class InteractionResponseSummary:
    action_summary: str
    speech_text: str
    speech_target_name: str | None
    action_target_actor_id: str | None
    action_target_name: str | None
    action_target_kind: PublicTurnActorType | None
    world_impact_type: PublicTurnWorldImpactType


@dataclass
class InteractionResponseClassification:
    action_text: str
    speech_text: str
    speech_target_label: str | None
    target_label: str | None
    world_impact_type: PublicTurnWorldImpactType


def public_turn_actor_type(value: str | None) -> PublicTurnActorType:
    actor_type = str(value or "npc").strip().lower()
    if actor_type == "player":
        return PublicTurnActorType.PLAYER
    if actor_type == "team":
        return PublicTurnActorType.TEAM
    if actor_type == "encounter_temp_npc":
        return PublicTurnActorType.ENCOUNTER_TEMP_NPC
    if actor_type == "hidden_npc":
        return PublicTurnActorType.HIDDEN_NPC
    if actor_type == "environment":
        return PublicTurnActorType.ENVIRONMENT
    return PublicTurnActorType.NPC


def classify_interaction_consent(action_text: str, speech_text: str) -> ConsentState:
    combined = "\n".join(part.strip().lower() for part in (action_text, speech_text) if str(part or "").strip())
    if not combined:
        return "ambiguous"
    rejected = any(token in combined for token in _REJECT_TOKENS)
    accepted = any(token in combined for token in _ACCEPT_TOKENS)
    if rejected and not accepted:
        return "rejected"
    if accepted and not rejected:
        return "accepted"
    return "ambiguous"


def classify_contest_between_actions(
    source_action: str,
    source_speech: str,
    target_action: str,
    target_speech: str,
    interaction_kind: str,
) -> ContestState:
    del source_action, source_speech, interaction_kind
    combined = "\n".join(part.strip().lower() for part in (target_action, target_speech) if str(part or "").strip())
    if not combined:
        return "non_opposed"
    if any(token in combined for token in _OPPOSE_TOKENS):
        return "opposed"
    consent = classify_interaction_consent(target_action, target_speech)
    if consent == "rejected":
        return "opposed"
    if consent == "accepted":
        return "non_opposed"
    if any(token in combined for token in _NON_OPPOSE_TOKENS):
        return "non_opposed"
    return "non_opposed"


def infer_interaction_kind(action_summary: str, specific_threat: str, action_prompt: str) -> str:
    combined = "\n".join(part.lower() for part in (action_summary, specific_threat, action_prompt) if str(part or "").strip())
    if any(token in combined for token in ("帮", "扶", "assist", "help", "support")):
        return "assist"
    if any(token in combined for token in ("拖", "拉", "带走", "drag", "pull", "carry")):
        return "move_target"
    if any(token in combined for token in ("抢", "夺", "take", "grab", "snatch")):
        return "take_object"
    if any(token in combined for token in ("拦", "挡", "阻止", "stop", "block")):
        return "block"
    if any(token in combined for token in ("按住", "压住", "抓住", "restrain", "hold")):
        return "restrain"
    return "targeted_interaction"


def is_targeted_interaction_candidate(
    *,
    action_type: str,
    action_summary: str,
    speech_text: str,
    specific_threat: str,
    action_prompt: str,
    target_actor_id: str | None,
    target_name: str | None,
) -> bool:
    if not (str(target_actor_id or "").strip() or str(target_name or "").strip()):
        return False
    combined = "\n".join(
        part.lower()
        for part in (action_summary, speech_text, specific_threat, action_prompt)
        if str(part or "").strip()
    )
    if not combined:
        return False
    if action_type == "attack":
        return True
    if is_social_interaction(action_summary=action_summary, speech_text=speech_text, action_type=action_type):
        return True
    return any(token in combined for token in _TARGETED_INTERACTION_TOKENS)


def _current_sub_zone_actor_candidates(save: SaveFile, *, exclude_actor_id: str | None = None) -> list[ResolvedInteractionTarget]:
    current_sub_zone_id = str(save.area_snapshot.current_sub_zone_id or "")
    candidates: list[ResolvedInteractionTarget] = []
    if save.player_static_data.player_id != exclude_actor_id:
        candidates.append(
            ResolvedInteractionTarget(
                actor_id=save.player_static_data.player_id,
                name=save.player_static_data.name,
                actor_kind="player",
                actor_type=PublicTurnActorType.PLAYER,
            )
        )
    for role in save.role_pool:
        if role.role_id == exclude_actor_id:
            continue
        if current_sub_zone_id and role.sub_zone_id and role.sub_zone_id != current_sub_zone_id:
            continue
        actor_type = PublicTurnActorType.TEAM if any(item.role_id == role.role_id for item in getattr(save.team_state, "members", [])) else PublicTurnActorType.NPC
        candidates.append(
            ResolvedInteractionTarget(
                actor_id=role.role_id,
                name=role.name,
                actor_kind="npc",
                actor_type=actor_type,
                role=role,
            )
        )
    active_encounter = world._active_encounter_for_current_sub_zone(save)
    for temp_npc in getattr(active_encounter, "temporary_npcs", []):
        actor_id = str(getattr(temp_npc, "encounter_npc_id", "") or "")
        if not actor_id or actor_id == exclude_actor_id:
            continue
        candidates.append(
            ResolvedInteractionTarget(
                actor_id=actor_id,
                name=str(getattr(temp_npc, "name", "") or actor_id),
                actor_kind="npc",
                actor_type=PublicTurnActorType.ENCOUNTER_TEMP_NPC,
            )
        )
    unique: dict[str, ResolvedInteractionTarget] = {}
    for candidate in candidates:
        unique.setdefault(candidate.actor_id, candidate)
    return list(unique.values())


def resolve_interaction_target(
    save: SaveFile,
    *,
    actor_role_id: str,
    action_prompt: str,
    target_label: str | None,
) -> ResolvedInteractionTarget | None:
    explicit_role_id = world._extract_target_role_id(action_prompt)
    candidates = _current_sub_zone_actor_candidates(save, exclude_actor_id=actor_role_id)
    by_id = {item.actor_id: item for item in candidates}
    if explicit_role_id and explicit_role_id in by_id:
        return by_id[explicit_role_id]

    clean_target_label = str(target_label or "").strip()
    if clean_target_label:
        matched = [item for item in candidates if actor_name_match(item.name, clean_target_label) or clean_target_label in item.name]
        if len(matched) == 1:
            return matched[0]

    search_text = "\n".join(
        part for part in (clean_target_label, world._humanize_action_prompt(action_prompt), action_prompt) if str(part or "").strip()
    )
    matched = [item for item in candidates if actor_name_match(item.name, search_text)]
    if len(matched) == 1:
        return matched[0]
    return None


def resolve_speech_target(
    save: SaveFile,
    *,
    actor_role_id: str,
    action_prompt: str,
    speech_target_label: str | None,
    fallback_target: ResolvedInteractionTarget | None = None,
) -> ResolvedInteractionTarget | None:
    del action_prompt
    candidates = _current_sub_zone_actor_candidates(save, exclude_actor_id=actor_role_id)
    clean_target_label = str(speech_target_label or "").strip()
    if clean_target_label:
        matched = [item for item in candidates if actor_name_match(item.name, clean_target_label) or clean_target_label in item.name]
        if len(matched) == 1:
            return matched[0]
        return None
    return fallback_target


def should_promote_speech_target_to_action_target(
    *,
    action_type: str,
    action_summary: str,
    speech_text: str,
    action_target: ResolvedInteractionTarget | None,
    speech_target: ResolvedInteractionTarget | None,
) -> bool:
    if action_target is not None or speech_target is None:
        return False
    return is_social_interaction(
        action_summary=action_summary,
        speech_text=speech_text,
        action_type=action_type,
    )


def build_ai_interaction_response(
    save: SaveFile,
    *,
    target: ResolvedInteractionTarget,
    source_actor_id: str,
    source_actor_name: str,
    source_action_summary: str,
    source_speech_text: str,
    gm_summary: str,
    config: ChatConfig | None,
) -> InteractionResponseSummary:
    if target.actor_kind == "player":
        return InteractionResponseSummary(
            action_summary="",
            speech_text="",
            speech_target_name=None,
            action_target_actor_id=None,
            action_target_name=None,
            action_target_kind=None,
            world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        )
    actor_row = target.actor_row or {
        "actor_id": target.actor_id,
        "name": target.name,
        "actor_type": ("team" if target.actor_type == PublicTurnActorType.TEAM else ("encounter_temp_npc" if target.actor_type == PublicTurnActorType.ENCOUNTER_TEMP_NPC else "npc")),
        "role": target.role,
    }
    incoming = {
        "source_actor_id": source_actor_id,
        "source_actor_name": source_actor_name,
        "summary": "\n".join(part for part in (source_action_summary, source_speech_text) if str(part or "").strip())[:180],
    }
    payload = public_scene_runtime._ai_actor_action(
        save,
        actor_row,
        player_text=source_action_summary,
        gm_summary=gm_summary,
        scene_context=None,
        incoming_interaction=incoming,
        allow_partial=True,
        config=config,
    )
    if not isinstance(payload, dict):
        return InteractionResponseSummary(
            action_summary="",
            speech_text="",
            speech_target_name=None,
            action_target_actor_id=None,
            action_target_name=None,
            action_target_kind=None,
            world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        )
    action_summary = _clean_line(
        str(payload.get("incoming_reaction_narration") or payload.get("external_action_narration") or payload.get("visible_intent") or "")
    )[:200]
    speech_text = _clean_line(str(payload.get("incoming_reaction_speech") or payload.get("speech_line") or payload.get("speech_summary") or ""))[:200]
    action_target = resolve_interaction_target(
        save,
        actor_role_id=target.actor_id,
        action_prompt=str(payload.get("action_prompt") or ""),
        target_label=str(payload.get("target_label") or ""),
    )
    speech_target = resolve_speech_target(
        save,
        actor_role_id=target.actor_id,
        action_prompt=str(payload.get("action_prompt") or ""),
        speech_target_label=str(payload.get("speech_target_label") or ""),
        fallback_target=next((item for item in _current_sub_zone_actor_candidates(save, exclude_actor_id=target.actor_id) if item.actor_id == source_actor_id), None),
    )
    if should_promote_speech_target_to_action_target(
        action_type=str(payload.get("action_type") or "check"),
        action_summary=action_summary,
        speech_text=speech_text,
        action_target=action_target,
        speech_target=speech_target,
    ):
        action_target = speech_target
    return InteractionResponseSummary(
        action_summary=action_summary,
        speech_text=speech_text,
        speech_target_name=(speech_target.name if speech_target is not None else None),
        action_target_actor_id=(action_target.actor_id if action_target is not None else None),
        action_target_name=(action_target.name if action_target is not None else _clean_line(str(payload.get("target_label") or "")) or None),
        action_target_kind=(action_target.actor_type if action_target is not None else None),
        world_impact_type=infer_world_impact_type(
            action_type=str(payload.get("action_type") or "check"),
            action_summary=action_summary,
            speech_text=speech_text,
            explicit_value=str(payload.get("world_impact_type") or ""),
        ),
    )


def classify_player_interaction_response(
    save: SaveFile,
    *,
    source_actor_id: str,
    source_actor_name: str,
    action_text: str,
    speech_text: str,
    response_kind: str,
    config: ChatConfig | None,
) -> InteractionResponseClassification:
    clean_action = _clean_line(action_text)[:200]
    clean_speech = _clean_line(speech_text)[:200]
    if response_kind == "no_action":
        return InteractionResponseClassification(
            action_text="",
            speech_text="",
            speech_target_label=None,
            target_label=None,
            world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
        )
    if has_ai_config(config):
        assert config is not None
        prompt = prompt_table.render(
            "public.turn.interaction.response_classifier.user",
            (
                "Classify the player's response in a public-turn interaction. "
                "Return JSON with world_impact_type=non_world|world, target_label, speech_target_label. "
                "If the player uses pronouns like 'him' or 'the other side', resolve them against the source actor. "
                "If the player does nothing, use non_world and empty targets. "
                "source_actor_name=$source_actor_name; action_text=$action_text; speech_text=$speech_text"
            ),
            source_actor_name=source_actor_name,
            action_text=clean_action,
            speech_text=clean_speech,
        )
        try:
            client = create_sync_client(config)
            response = client.chat.completions.create(
                model=config.model,
                **build_completion_options(config),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": config.gm_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            parsed = world._extract_json_content((response.choices[0].message.content or "").strip())
            target_label = _clean_line(str(parsed.get("target_label") or ""))[:80] or None
            speech_target_label = _clean_line(str(parsed.get("speech_target_label") or ""))[:80] or None
            if not target_label and clean_action:
                target_label = source_actor_name
            return InteractionResponseClassification(
                action_text=clean_action,
                speech_text=clean_speech,
                speech_target_label=speech_target_label,
                target_label=target_label,
                world_impact_type=infer_world_impact_type(
                    action_type="check",
                    action_summary=clean_action,
                    speech_text=clean_speech,
                    explicit_value=str(parsed.get("world_impact_type") or ""),
                ),
            )
        except Exception:
            pass
    target_label = source_actor_name if clean_action else None
    return InteractionResponseClassification(
        action_text=clean_action,
        speech_text=clean_speech,
        speech_target_label=None,
        target_label=target_label,
        world_impact_type=infer_world_impact_type(
            action_type="check",
            action_summary=clean_action,
            speech_text=clean_speech,
        ),
    )


def validate_prompt_target_alignment(
    *,
    prompt_target_actor_id: str | None,
    prompt_target_actor_name: str | None,
    source_action_target_name: str | None,
    expected_player_id: str,
) -> bool:
    clean_action_target_name = _clean_line(source_action_target_name)
    clean_prompt_target_name = _clean_line(prompt_target_actor_name)
    if prompt_target_actor_id and prompt_target_actor_id != expected_player_id and clean_action_target_name:
        return clean_prompt_target_name == clean_action_target_name
    if clean_action_target_name and clean_prompt_target_name:
        return clean_action_target_name == clean_prompt_target_name
    return True


def resolve_target_ability(save: SaveFile, target: ResolvedInteractionTarget) -> tuple[str, int]:
    if target.actor_kind == "player":
        return world._choose_opposed_target_ability(save.player_static_data, "max_strength_or_dexterity")
    profile = target.role.profile if target.role is not None else None
    if profile is None:
        return "strength", 0
    strength = int(profile.dnd5e_sheet.current_ability_modifiers.strength)
    dexterity = int(profile.dnd5e_sheet.current_ability_modifiers.dexterity)
    if dexterity > strength:
        return "dexterity", dexterity
    return "strength", strength
