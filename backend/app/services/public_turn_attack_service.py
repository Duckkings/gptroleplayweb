from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import AreaNpc, PublicTurnActorType, SaveFile
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services.ai_protocol_contract_service import (
    EnumContractField,
    allow_protocol_repair,
    render_enum_pool_text,
    validate_or_repair_json_payload,
)
from app.services.item_template_service import load_template_library
from app.services.public_turn_interaction_service import ResolvedInteractionTarget


_PUBLIC_TURN_ATTACK_ASSESSMENT_FIELDS = (
    EnumContractField(field_path="attack_kind", allowed_ids=("ordinary_action", "targeted_attack", "aoe_attack")),
    EnumContractField(field_path="attack_basis", allowed_ids=("weapon", "spell", "war_art", "other")),
    EnumContractField(field_path="attack_area_shape", allowed_ids=("none", "sphere", "cone", "line", "burst", "emanation")),
    EnumContractField(field_path="self_target_policy", allowed_ids=("never", "can_include_self", "always_include_self")),
    EnumContractField(
        field_path="attack_ability_used",
        allowed_ids=("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
    ),
)

_PUBLIC_TURN_ATTACK_RESPONSE_FIELDS = (
    EnumContractField(field_path="world_impact_type", allowed_ids=("non_world", "world")),
    EnumContractField(
        field_path="defense_ability_used",
        allowed_ids=("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"),
    ),
)


@dataclass
class PublicTurnResolvedAttackTarget:
    actor_id: str
    actor_name: str
    actor_type: PublicTurnActorType
    role: Any | None = None
    is_hidden: bool = False


def clean_attack_label(text: str, *, limit: int = 120) -> str:
    return " ".join(str(text or "").split()).strip()[:limit]


def _definition_by_id(definitions: list[Any]) -> dict[str, Any]:
    return {
        str(getattr(definition, "definition_id", "") or "").strip(): definition
        for definition in definitions
        if str(getattr(definition, "definition_id", "") or "").strip()
    }


def actor_equipped_weapon_name(save: SaveFile, actor_role_id: str) -> str:
    try:
        _, profile = world._get_actor_profile(save, actor_role_id)
    except Exception:
        return ""
    weapon_item_id = str(getattr(profile.dnd5e_sheet.equipment_slots, "weapon_item_id", "") or "")
    if not weapon_item_id:
        return ""
    item = next((entry for entry in profile.dnd5e_sheet.backpack.items if entry.item_id == weapon_item_id), None)
    return str(item.name if item is not None else "").strip()


def resolve_attack_profile(save: SaveFile, actor_role_id: str) -> Any:
    _, profile = world._get_actor_profile(save, actor_role_id)
    return profile


def _attack_definition_pools(
    save: SaveFile,
    actor_role_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[str], list[str], str]:
    library = load_template_library()
    profile = resolve_attack_profile(save, actor_role_id)
    known_spells = [str(item or "").strip() for item in getattr(profile.dnd5e_sheet, "spells", []) or [] if str(item or "").strip()]
    known_war_arts = [str(item or "").strip() for item in getattr(profile.dnd5e_sheet, "war_arts", []) or [] if str(item or "").strip()]
    equipped_weapon_name = actor_equipped_weapon_name(save, actor_role_id)
    spell_pool = [
        {
            "definition_id": definition.definition_id,
            "name": definition.name,
            "attack_mode": definition.attack_mode,
            "casting_ability": definition.casting_ability,
            "area_shape": definition.area_shape,
        }
        for definition in library.spell_definitions
    ]
    equipment_pool = [
        {
            "definition_id": definition.definition_id,
            "name": definition.name,
            "attack_mode": definition.attack_mode,
            "attack_ability_mode": definition.attack_ability_mode,
            "area_shape": definition.area_shape,
        }
        for definition in library.equipment_definitions
        if str(getattr(definition, "slot_type", "") or "") == "weapon"
    ]
    war_art_pool = [
        {
            "definition_id": definition.definition_id,
            "name": definition.name,
            "attack_mode": definition.attack_mode,
            "scaling_ability": definition.scaling_ability,
            "martial_cost": definition.martial_cost,
            "cooldown_rounds": definition.cooldown_rounds,
            "area_shape": definition.area_shape,
        }
        for definition in library.war_art_definitions
    ]
    return spell_pool, equipment_pool, war_art_pool, known_spells, known_war_arts, equipped_weapon_name


def _default_attack_assessment(save: SaveFile, *, actor_role_id: str) -> dict[str, object]:
    _ = resolve_attack_profile(save, actor_role_id)
    return {
        "attack_kind": "ordinary_action",
        "attack_basis": "other",
        "attack_definition_id": "",
        "attack_definition_name": "",
        "attack_area_shape": "none",
        "attack_area_radius_m": 0.0,
        "attack_area_length_m": 0.0,
        "self_target_policy": "never",
        "candidate_target_names": [],
        "attack_ability_used": "strength",
    }


def _coerce_attack_ability_used(save: SaveFile, actor_role_id: str, *, basis: str, definition: Any | None, current_value: str) -> str:
    attack_ability_used = str(current_value or "").strip().lower()
    if definition is not None:
        attack_ability_used = str(
            getattr(definition, "casting_ability", None)
            or getattr(definition, "attack_ability_mode", None)
            or getattr(definition, "scaling_ability", None)
            or attack_ability_used
            or "strength"
        ).strip().lower()
    if attack_ability_used == "finesse_choice":
        profile = resolve_attack_profile(save, actor_role_id)
        strength_mod = int(profile.dnd5e_sheet.current_ability_modifiers.strength)
        dexterity_mod = int(profile.dnd5e_sheet.current_ability_modifiers.dexterity)
        attack_ability_used = "dexterity" if dexterity_mod > strength_mod else "strength"
    if attack_ability_used not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
        attack_ability_used = "intelligence" if basis == "spell" else "strength"
    return attack_ability_used


def resolve_attack_candidates(save: SaveFile, *, include_hidden: bool) -> list[PublicTurnResolvedAttackTarget]:
    candidates: list[PublicTurnResolvedAttackTarget] = [
        PublicTurnResolvedAttackTarget(
            actor_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            actor_type=PublicTurnActorType.PLAYER,
        )
    ]
    team_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
    visible_ids = {role.role_id for role in world._visible_public_roles(save)}
    for role in save.role_pool:
        if world._role_is_dead_for_public_scene(save, role):
            continue
        if role.role_id in visible_ids:
            candidates.append(
                PublicTurnResolvedAttackTarget(
                    actor_id=role.role_id,
                    actor_name=role.name,
                    actor_type=(PublicTurnActorType.TEAM if role.role_id in team_ids else PublicTurnActorType.NPC),
                    role=role,
                )
            )
            continue
        if role.role_id in team_ids:
            candidates.append(
                PublicTurnResolvedAttackTarget(
                    actor_id=role.role_id,
                    actor_name=role.name,
                    actor_type=PublicTurnActorType.TEAM,
                    role=role,
                )
            )
    reserved_name_keys = {public_scene_legacy._normalize_actor_name_key(item.actor_name) for item in candidates}
    temp_npcs = public_scene_legacy._encounter_temp_npcs_for_candidates(save, existing_names=reserved_name_keys)
    for temp_npc in temp_npcs:
        actor_id = str(getattr(temp_npc, "encounter_npc_id", "") or "")
        if not actor_id:
            continue
        candidates.append(
            PublicTurnResolvedAttackTarget(
                actor_id=actor_id,
                actor_name=str(getattr(temp_npc, "name", "") or actor_id),
                actor_type=PublicTurnActorType.ENCOUNTER_TEMP_NPC,
            )
        )
    if include_hidden:
        seen_ids = {item.actor_id for item in candidates}
        current_sub_zone_id = save.area_snapshot.current_sub_zone_id
        for role in save.role_pool:
            if role.role_id in seen_ids or role.sub_zone_id != current_sub_zone_id:
                continue
            state = str(role.state or "").strip().lower()
            if state not in {"hidden", "concealed", "lurking", "ambush"}:
                continue
            candidates.append(
                PublicTurnResolvedAttackTarget(
                    actor_id=role.role_id,
                    actor_name=role.name,
                    actor_type=PublicTurnActorType.HIDDEN_NPC,
                    role=role,
                    is_hidden=True,
                )
            )
    unique: dict[str, PublicTurnResolvedAttackTarget] = {}
    for candidate in candidates:
        unique.setdefault(candidate.actor_id, candidate)
    return list(unique.values())


def reveal_hidden_public_target(save: SaveFile, target: PublicTurnResolvedAttackTarget) -> None:
    if not target.is_hidden or target.role is None:
        return
    target.role.state = "idle"
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    current_sub = next((item for item in save.area_snapshot.sub_zones if item.sub_zone_id == current_sub_zone_id), None)
    if current_sub is None or any(npc.npc_id == target.actor_id for npc in current_sub.npcs):
        return
    current_sub.npcs.append(AreaNpc(npc_id=target.actor_id, name=target.actor_name, state="idle"))


def roll_damage_dice(dice_text: str, bonus: int) -> int:
    clean = str(dice_text or "").strip().lower()
    if not clean:
        return max(0, int(bonus))
    total = 0
    try:
        if "d" in clean:
            count_text, sides_text = clean.split("d", 1)
            count = max(1, int(count_text or "1"))
            modifier = 0
            sides_value = sides_text
            for marker in ("+", "-"):
                if marker in sides_text[1:]:
                    sides_value, modifier_text = sides_text.split(marker, 1)
                    modifier = int(modifier_text or "0") * (1 if marker == "+" else -1)
                    break
            sides = max(1, int(sides_value or "1"))
            for _ in range(count):
                total += random.randint(1, sides)
            total += modifier
        else:
            total = int(clean)
    except Exception:
        total = 0
    return max(0, total + int(bonus))


def definition_damage_payload(definition: Any | None) -> tuple[str, int, str]:
    if definition is None:
        return "", 0, ""
    return (
        str(getattr(definition, "damage_dice", "") or "").strip(),
        int(getattr(definition, "damage_bonus", 0) or 0),
        str(getattr(definition, "damage_type", "") or "").strip(),
    )


def resolve_attack_definition(
    save: SaveFile,
    *,
    actor_role_id: str,
    attack_definition_id: str | None = None,
    attack_basis_hint: str | None = None,
) -> tuple[str, Any | None]:
    # Public-turn attack template resolution is id-only. Do not reintroduce text matching here.
    library = load_template_library()
    definition_id = str(attack_definition_id or "").strip()
    basis_hint = str(attack_basis_hint or "").strip().lower()
    if definition_id:
        if basis_hint == "spell":
            return "spell", _definition_by_id(library.spell_definitions).get(definition_id)
        if basis_hint == "weapon":
            return "weapon", _definition_by_id(library.equipment_definitions).get(definition_id)
        if basis_hint == "war_art":
            return "war_art", _definition_by_id(library.war_art_definitions).get(definition_id)
        spell_definition = _definition_by_id(library.spell_definitions).get(definition_id)
        if spell_definition is not None:
            return "spell", spell_definition
        equipment_definition = _definition_by_id(library.equipment_definitions).get(definition_id)
        if equipment_definition is not None:
            return "weapon", equipment_definition
        war_art_definition = _definition_by_id(library.war_art_definitions).get(definition_id)
        if war_art_definition is not None:
            return "war_art", war_art_definition
    if basis_hint in {"spell", "weapon", "war_art"}:
        return basis_hint, None
    return "other", None


def assess_public_turn_attack(
    save: SaveFile,
    *,
    actor_role_id: str,
    actor_name: str,
    action_summary: str,
    speech_text: str,
    action_prompt: str,
    fallback_target_name: str | None = None,
    config: Any | None,
) -> dict[str, object]:
    # Public-turn attack classification must come from AI structured output, not backend keyword heuristics.
    result = _default_attack_assessment(save, actor_role_id=actor_role_id)
    if not has_ai_config(config):
        return result
    candidate_names = [item.actor_name for item in resolve_attack_candidates(save, include_hidden=False)]
    spell_pool, equipment_pool, war_art_pool, known_spells, known_war_arts, equipped_weapon_name = _attack_definition_pools(save, actor_role_id)
    spell_definition_ids = {str(item.get("definition_id") or "") for item in spell_pool}
    equipment_definition_ids = {str(item.get("definition_id") or "") for item in equipment_pool}
    war_art_definition_ids = {str(item.get("definition_id") or "") for item in war_art_pool}
    try:
        prompt = prompt_table.render(
            "public.turn.attack_assessment.user",
            (
                "Return one JSON object only. Decide whether a public-turn attack is ordinary_action, targeted_attack, or aoe_attack. "
                "If this is a DND 5e style spell, weapon, or war art attack, prefer spell/weapon/war_art basis and use matching area semantics. "
                "You must resolve attack_definition_id yourself from the provided template pools. "
                "The backend will not infer spell, weapon, or war art definitions from action text, aliases, Chinese names, or keywords. "
                "candidate_target_names must only use exact names from visible_target_names_json. "
                "attack_definition_id must be one exact id from spell_definition_pool_json, weapon_definition_pool_json, or war_art_definition_pool_json, or an empty string if no listed template matches. "
                "actor_name=$actor_name; action_summary=$action_summary; speech_text=$speech_text; action_prompt=$action_prompt; "
                "fallback_target_name=$fallback_target_name; visible_target_names_json=$visible_target_names_json; "
                "known_spell_names_json=$known_spell_names_json; known_war_art_names_json=$known_war_art_names_json; equipped_weapon_name=$equipped_weapon_name; "
                "spell_definition_pool_json=$spell_definition_pool_json; weapon_definition_pool_json=$weapon_definition_pool_json; war_art_definition_pool_json=$war_art_definition_pool_json"
            ),
            actor_name=actor_name,
            action_summary=action_summary[:240],
            speech_text=speech_text[:160],
            action_prompt=action_prompt[:280],
            fallback_target_name=str(fallback_target_name or "")[:120],
            visible_target_names_json=json.dumps(candidate_names, ensure_ascii=False),
            known_spell_names_json=json.dumps(known_spells, ensure_ascii=False),
            known_war_art_names_json=json.dumps(known_war_arts, ensure_ascii=False),
            equipped_weapon_name=equipped_weapon_name[:120],
            spell_definition_pool_json=json.dumps(spell_pool, ensure_ascii=False),
            weapon_definition_pool_json=json.dumps(equipment_pool, ensure_ascii=False),
            war_art_definition_pool_json=json.dumps(war_art_pool, ensure_ascii=False),
        )
        prompt = (
            f"{prompt}\nAllowed enum ids:\n{render_enum_pool_text(_PUBLIC_TURN_ATTACK_ASSESSMENT_FIELDS)}\n"
            "Use only the allowed stable ids for attack_kind, attack_basis, attack_area_shape, self_target_policy, and attack_ability_used. "
            "Do not expect any backend text matching fallback."
        )
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("public.turn.attack_assessment.system", "Return JSON only.")},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = (resp.choices[0].message.content or "").strip() or "{}"
        parsed = json.loads(raw_json)
        with allow_protocol_repair():
            parsed = validate_or_repair_json_payload(
                parsed=parsed,
                raw_json=raw_json,
                fields=_PUBLIC_TURN_ATTACK_ASSESSMENT_FIELDS,
                config=config,
                system_prompt=prompt_table.get_text("public.turn.attack_assessment.system", "Return JSON only."),
                original_prompt=prompt,
            )
        result["attack_kind"] = str(parsed.get("attack_kind") or result["attack_kind"]).strip()
        result["attack_basis"] = str(parsed.get("attack_basis") or result["attack_basis"]).strip()
        parsed_definition_id = clean_attack_label(str(parsed.get("attack_definition_id") or ""), limit=160)
        if result["attack_basis"] == "spell":
            parsed_definition_id = parsed_definition_id if parsed_definition_id in spell_definition_ids else ""
        elif result["attack_basis"] == "weapon":
            parsed_definition_id = parsed_definition_id if parsed_definition_id in equipment_definition_ids else ""
        elif result["attack_basis"] == "war_art":
            parsed_definition_id = parsed_definition_id if parsed_definition_id in war_art_definition_ids else ""
        else:
            if parsed_definition_id in war_art_definition_ids:
                result["attack_basis"] = "war_art"
            elif parsed_definition_id in spell_definition_ids:
                result["attack_basis"] = "spell"
            elif parsed_definition_id in equipment_definition_ids:
                result["attack_basis"] = "weapon"
            else:
                parsed_definition_id = ""
        result["attack_definition_id"] = parsed_definition_id
        result["attack_area_shape"] = str(parsed.get("attack_area_shape") or result["attack_area_shape"]).strip()
        result["attack_area_radius_m"] = max(0.0, float(parsed.get("attack_area_radius_m") or result.get("attack_area_radius_m") or 0))
        result["attack_area_length_m"] = max(0.0, float(parsed.get("attack_area_length_m") or result.get("attack_area_length_m") or 0))
        result["self_target_policy"] = str(parsed.get("self_target_policy") or result["self_target_policy"]).strip()
        basis, definition = resolve_attack_definition(
            save,
            actor_role_id=actor_role_id,
            attack_definition_id=parsed_definition_id,
            attack_basis_hint=str(result.get("attack_basis") or ""),
        )
        if definition is not None:
            result["attack_definition_name"] = str(getattr(definition, "name", "") or "").strip()
            result["attack_area_shape"] = str(getattr(definition, "area_shape", result["attack_area_shape"]) or result["attack_area_shape"]).strip()
            result["attack_area_radius_m"] = float(getattr(definition, "area_radius_m", result["attack_area_radius_m"]) or result["attack_area_radius_m"])
            result["attack_area_length_m"] = float(getattr(definition, "area_length_m", result["attack_area_length_m"]) or result["attack_area_length_m"])
            result["self_target_policy"] = str(getattr(definition, "self_target_policy", result["self_target_policy"]) or result["self_target_policy"]).strip()
            if str(getattr(definition, "attack_mode", "") or "").strip():
                result["attack_kind"] = str(getattr(definition, "attack_mode") or result["attack_kind"]).strip()
            result["attack_basis"] = basis
        else:
            result["attack_definition_name"] = clean_attack_label(str(parsed.get("attack_definition_name") or ""), limit=160)
        result["attack_ability_used"] = _coerce_attack_ability_used(
            save,
            actor_role_id,
            basis=str(result.get("attack_basis") or "other"),
            definition=definition,
            current_value=str(parsed.get("attack_ability_used") or result["attack_ability_used"]).strip(),
        )
        allowed_names = set(candidate_names)
        candidate_target_names = []
        for item in list(parsed.get("candidate_target_names") or []):
            label = clean_attack_label(str(item or ""))
            if label and label in allowed_names and label not in candidate_target_names:
                candidate_target_names.append(label)
        result["candidate_target_names"] = candidate_target_names
        return result
    except Exception:
        return result


def select_aoe_threatened_targets(
    save: SaveFile,
    *,
    actor_role_id: str,
    actor_name: str,
    action_summary: str,
    attack_assessment: dict[str, object],
    config: Any | None,
) -> tuple[list[PublicTurnResolvedAttackTarget], list[str]]:
    candidates = resolve_attack_candidates(save, include_hidden=True)
    by_name = {item.actor_name: item for item in candidates}
    base_selected_names = [name for name in list(attack_assessment.get("candidate_target_names") or []) if name in by_name]
    selected_names = list(base_selected_names)
    if has_ai_config(config):
        try:
            prompt = prompt_table.render(
                "public.turn.aoe_target_selection.user",
                (
                    "Return one JSON object only. Choose which current public-scene targets are inside this AOE attack. "
                    "You may include hidden targets if the blast or sweep reasonably catches them. "
                    "threatened_target_names must use exact names from the provided lists. "
                    "The backend will not expand the target pool with keyword fallback or guessed names. "
                    "source_actor_name=$source_actor_name; action_summary=$action_summary; attack_assessment_json=$attack_assessment_json; "
                    "visible_names_json=$visible_names_json; hidden_names_json=$hidden_names_json"
                ),
                source_actor_name=actor_name,
                action_summary=action_summary[:240],
                attack_assessment_json=json.dumps(attack_assessment, ensure_ascii=False),
                visible_names_json=json.dumps([item.actor_name for item in candidates if not item.is_hidden], ensure_ascii=False),
                hidden_names_json=json.dumps([item.actor_name for item in candidates if item.is_hidden], ensure_ascii=False),
            )
            client = create_sync_client(config, client_cls=OpenAI)
            resp = client.chat.completions.create(
                model=config.model,
                **build_completion_options(config),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_table.get_text("public.turn.aoe_target_selection.system", "Return JSON only.")},
                    {"role": "user", "content": prompt},
                ],
            )
            parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
            selected_names = []
            for item in list(parsed.get("threatened_target_names") or []):
                label = clean_attack_label(str(item or ""))
                if label in by_name and label not in selected_names:
                    selected_names.append(label)
        except Exception:
            selected_names = list(base_selected_names)
    self_policy = str(attack_assessment.get("self_target_policy") or "never").strip()
    basis = str(attack_assessment.get("attack_basis") or "other").strip()
    source_target = next((item for item in candidates if item.actor_id == actor_role_id), None)
    if source_target is not None and self_policy == "always_include_self" and source_target.actor_name not in selected_names:
        selected_names.append(source_target.actor_name)
    selected_targets: list[PublicTurnResolvedAttackTarget] = []
    revealed_names: list[str] = []
    for name in selected_names:
        target = by_name.get(name)
        if target is None:
            continue
        if target.actor_id == actor_role_id and basis not in {"spell", "war_art"} and self_policy != "always_include_self":
            continue
        selected_targets.append(target)
        if target.is_hidden:
            reveal_hidden_public_target(save, target)
            if target.actor_name not in revealed_names:
                revealed_names.append(target.actor_name)
    return selected_targets, revealed_names


def classify_attack_response(
    *,
    source_actor_name: str,
    source_action_summary: str,
    source_speech_text: str,
    target_actor_name: str,
    response_action_text: str,
    response_speech_text: str,
    response_kind: str,
    config: Any | None,
) -> dict[str, object]:
    fallback = {
        "world_impact_type": "non_world",
        "effective_against_attack": False,
        "defense_ability_used": "dexterity",
    }
    if response_kind == "no_action":
        return fallback
    if not has_ai_config(config):
        return fallback
    try:
        prompt = prompt_table.render(
            "public.turn.attack_response_classification.user",
            (
                "Return one JSON object only. Decide whether the target's response is a world-impact defense against the incoming attack, "
                "whether it is effective_against_attack, and which defense_ability_used best fits the defense behavior. "
                "The backend will not infer these states from the response text. "
                "If the response does not clearly alter the attack in the world, return world_impact_type=non_world and effective_against_attack=false. "
                "source_actor_name=$source_actor_name; source_action_summary=$source_action_summary; source_speech_text=$source_speech_text; "
                "target_actor_name=$target_actor_name; response_action_text=$response_action_text; response_speech_text=$response_speech_text"
            ),
            source_actor_name=source_actor_name,
            source_action_summary=source_action_summary[:220],
            source_speech_text=source_speech_text[:160],
            target_actor_name=target_actor_name,
            response_action_text=response_action_text[:220],
            response_speech_text=response_speech_text[:160],
        )
        prompt = (
            f"{prompt}\nAllowed enum ids:\n{render_enum_pool_text(_PUBLIC_TURN_ATTACK_RESPONSE_FIELDS)}\n"
            "Use only the allowed stable ids for world_impact_type and defense_ability_used. "
            "Do not expect any backend keyword fallback."
        )
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("public.turn.attack_response_classification.system", "Return JSON only.")},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = (resp.choices[0].message.content or "").strip() or "{}"
        parsed = json.loads(raw_json)
        with allow_protocol_repair():
            parsed = validate_or_repair_json_payload(
                parsed=parsed,
                raw_json=raw_json,
                fields=_PUBLIC_TURN_ATTACK_RESPONSE_FIELDS,
                config=config,
                system_prompt=prompt_table.get_text("public.turn.attack_response_classification.system", "Return JSON only."),
                original_prompt=prompt,
            )
        fallback["world_impact_type"] = str(parsed.get("world_impact_type") or fallback["world_impact_type"]).strip()
        fallback["effective_against_attack"] = bool(parsed.get("effective_against_attack"))
        fallback["defense_ability_used"] = str(parsed.get("defense_ability_used") or fallback["defense_ability_used"]).strip()
        return fallback
    except Exception:
        return fallback


def attack_ability_modifier(save: SaveFile, actor_role_id: str, ability_used: str) -> int:
    try:
        profile = resolve_attack_profile(save, actor_role_id)
    except Exception:
        return 0
    return int(world._ability_modifier(profile, ability_used))


def generate_attack_outcome_narration(
    *,
    source_actor_name: str,
    target_actor_name: str | None,
    action_summary: str,
    speech_text: str,
    attack_assessment: dict[str, object],
    defense_action_text: str,
    defense_speech_text: str,
    hit_target_names: list[str],
    avoided_target_names: list[str],
    revealed_target_names: list[str],
    hp_changes: list[dict[str, Any]],
    config: Any | None,
) -> str:
    fallback_parts: list[str] = []
    if hit_target_names:
        fallback_parts.append(f"{source_actor_name}的攻击压中了{'、'.join(hit_target_names)}。")
    if avoided_target_names:
        fallback_parts.append(f"{'、'.join(avoided_target_names)}避开了这次攻势。")
    if revealed_target_names:
        fallback_parts.append(f"{'、'.join(revealed_target_names)}也被卷入其中并暴露了位置。")
    if hp_changes:
        fallback_parts.append("伤害当场落到了命中目标身上。")
    fallback_text = " ".join(fallback_parts).strip() or f"{source_actor_name}的攻击结果已经在公开回合中落地。"
    if not has_ai_config(config):
        return fallback_text
    try:
        prompt = prompt_table.render(
            "public.turn.attack_outcome_narration.user",
            (
                "Write 1-2 short Chinese sentences narrating the concrete outcome of this public-turn attack. "
                "Reflect the attack type, defense attempt, revealed hidden targets, who was hit, who avoided, and any immediate HP consequences. "
                "source_actor_name=$source_actor_name; target_actor_name=$target_actor_name; action_summary=$action_summary; speech_text=$speech_text; "
                "attack_assessment_json=$attack_assessment_json; defense_action_text=$defense_action_text; defense_speech_text=$defense_speech_text; "
                "hit_target_names_json=$hit_target_names_json; avoided_target_names_json=$avoided_target_names_json; revealed_target_names_json=$revealed_target_names_json; hp_changes_json=$hp_changes_json"
            ),
            source_actor_name=source_actor_name,
            target_actor_name=str(target_actor_name or ""),
            action_summary=action_summary[:220],
            speech_text=speech_text[:160],
            attack_assessment_json=json.dumps(attack_assessment, ensure_ascii=False),
            defense_action_text=defense_action_text[:220],
            defense_speech_text=defense_speech_text[:160],
            hit_target_names_json=json.dumps(hit_target_names, ensure_ascii=False),
            avoided_target_names_json=json.dumps(avoided_target_names, ensure_ascii=False),
            revealed_target_names_json=json.dumps(revealed_target_names, ensure_ascii=False),
            hp_changes_json=json.dumps(hp_changes, ensure_ascii=False),
        )
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            messages=[
                {"role": "system", "content": prompt_table.get_text("public.turn.attack_outcome_narration.system", "Write concise narration only.")},
                {"role": "user", "content": prompt},
            ],
        )
        text = clean_attack_label(resp.choices[0].message.content or "", limit=280)
        return text or fallback_text
    except Exception:
        return fallback_text
