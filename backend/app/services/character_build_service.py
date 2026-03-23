from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.storage import read_json, storage_state, write_json_atomic
from app.models.schemas import (
    CharacterBuildAbilitySuggestResponse,
    CharacterBuildBasicInfo,
    CharacterBuildBasicInfoSuggestResponse,
    CharacterBuildChoiceOption,
    CharacterBuildCompanionCompleteRequest,
    CharacterBuildCompanionCompleteResponse,
    CharacterBuildCompanionFlavor,
    CharacterBuildCompanionFlavorSuggestResponse,
    CharacterBuildLoadoutSelection,
    CharacterBuildLoadoutSuggestResponse,
    CharacterBuildMediaCapabilities,
    CharacterBuildOptionsResponse,
    CharacterBuildPlayerCompleteRequest,
    CharacterBuildPlayerCompleteResponse,
    CharacterBuildPortraitPromptSuggestResponse,
    CharacterBuildStateResponse,
    CompanionBuildSeedListResponse,
    CompanionBuildSeedResponse,
    CompanionBuildSeedSummary,
    Dnd5eAbilityScores,
    NpcRoleCard,
    OriginStamp,
    PlayerBuildSeed,
    PlayerBuildSeedListResponse,
    PlayerBuildSeedResponse,
    PlayerBuildSeedSummary,
    PlayerStaticData,
    TeamMember,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services.character_build_prompt_presets import build_portrait_generation_prompt
from app.services.character_media_service import build_media_capabilities, copy_asset_to_path, load_asset
from app.services.item_template_service import load_template_library
from app.services.retained_npc_service import retained_npc_service
from app.services.team_service import ensure_team_state, sync_team_members_with_player_in_save
from app.services.world_service import (
    _class_template,
    _recompute_player_derived,
    ensure_character_build_state,
    get_current_save,
    save_current,
)


_RECOMMENDED_RACES = ["人类", "精灵", "矮人", "半身人", "半精灵", "侏儒", "提夫林"]
_BODY_TYPES = ["纤细", "匀称", "高挑", "健壮", "结实", "娇小"]
_POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
_BASE_LANGUAGE_BY_RACE = {
    "矮人": ["通用语", "矮人语"],
    "精灵": ["通用语", "精灵语"],
    "半身人": ["通用语", "半身人语"],
}
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_root() -> Path:
    return storage_state.save_path.parent


def _player_build_root() -> Path:
    path = _user_root() / "player-builds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _retained_build_root() -> Path:
    path = _user_root() / "retained-builds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _library_indexes() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    library = load_template_library()
    return (
        {item.definition_id: item for item in library.spell_definitions},
        {item.definition_id: item for item in library.war_art_definitions},
        {item.definition_id: item for item in library.equipment_definitions},
        {item.definition_id: item for item in library.item_definitions},
    )


def _choice(
    option_id: str,
    label: str,
    description: str,
    source_kind: str,
    *,
    definition_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CharacterBuildChoiceOption:
    return CharacterBuildChoiceOption(
        option_id=option_id,
        label=label,
        description=description,
        source_kind=source_kind,  # type: ignore[arg-type]
        definition_id=definition_id,
        metadata=metadata or {},
    )


def _spell_options() -> dict[str, CharacterBuildChoiceOption]:
    spells, _, _, _ = _library_indexes()
    defaults = {
        "fire_bolt": "一束火焰直击单体目标。",
        "magic_missile": "稳定命中的奥术飞弹。",
        "shield": "短暂提升防护。",
        "burning_hands": "近距离锥形火焰。",
        "scorching_ray": "多发火焰射线。",
        "thunderwave": "向外爆发雷鸣冲击。",
        "detect_magic": "感知附近魔法痕迹。",
        "misty_step": "短距离瞬移。",
        "invisibility": "让目标暂时隐形。",
        "fireball": "大范围爆裂火球。",
    }
    options: dict[str, CharacterBuildChoiceOption] = {}
    for spell_id, fallback_desc in defaults.items():
        definition = spells.get(spell_id)
        options[spell_id] = _choice(
            spell_id,
            getattr(definition, "name", spell_id),
            getattr(definition, "description", "") or fallback_desc,
            "spell",
            definition_id=spell_id,
            metadata={"spell_name": getattr(definition, "name", spell_id)},
        )
    return options


def _equipment_options() -> dict[str, CharacterBuildChoiceOption]:
    _, _, equipment, _ = _library_indexes()
    options: dict[str, CharacterBuildChoiceOption] = {}
    base_ids = ["legacy_weapon_法杖", "legacy_weapon_木杖", "legacy_weapon_短剑", "legacy_armor_法袍", "legacy_armor_锁子甲"]
    for equipment_id in base_ids:
        item = equipment.get(equipment_id)
        if item is None:
            continue
        options[equipment_id] = _choice(
            equipment_id,
            item.name,
            item.description or item.name,
            "equipment" if item.equipment_kind != "armor" else "armor",
            definition_id=equipment_id,
            metadata={
                "name": item.name,
                "item_type": item.equipment_kind,
                "slot_type": item.slot_type,
                "description": item.description,
                "effect": item.attack_ability_mode,
                "attack_bonus": item.attack_bonus,
                "armor_bonus": item.armor_bonus,
                "value": item.value,
            },
        )

    starter_heavy = [
        ("starter_longsword", "长剑", "近战常用制式武器", 2, 0),
        ("starter_battleaxe", "战斧", "厚重的单手战斧", 2, 0),
        ("starter_spear", "长矛", "可刺击也可投掷的制式长矛", 1, 0),
        ("starter_warhammer", "战锤", "重击型近战武器", 2, 0),
        ("starter_greatsword", "巨剑", "双手重型大剑", 3, 0),
    ]
    for option_id, name, description, attack_bonus, armor_bonus in starter_heavy:
        options[option_id] = _choice(
            option_id,
            name,
            description,
            "equipment",
            metadata={
                "name": name,
                "item_type": "weapon",
                "slot_type": "weapon",
                "description": description,
                "effect": "strength",
                "attack_bonus": attack_bonus,
                "armor_bonus": armor_bonus,
                "value": 20,
            },
        )
    return options


def _skill_options() -> dict[str, CharacterBuildChoiceOption]:
    return {
        "power_strike": _choice("power_strike", "强力斩", "以力量压制目标的重击。", "skill", metadata={"skill_name": "强力斩"}),
        "shield_bash": _choice("shield_bash", "盾击", "利用盾牌制造硬直。", "skill", metadata={"skill_name": "盾击"}),
        "parry": _choice("parry", "招架", "提高近战防守稳定性。", "skill", metadata={"skill_name": "招架"}),
        "sweeping_slash": _choice("sweeping_slash", "横扫", "适合压制近身敌人的挥砍。", "skill", metadata={"skill_name": "横扫"}),
        "battle_focus": _choice("battle_focus", "战意集中", "在缠斗中保持专注和稳定。", "skill", metadata={"skill_name": "战意集中"}),
    }


def _war_art_options() -> dict[str, CharacterBuildChoiceOption]:
    _, war_arts, _, _ = _library_indexes()
    defaults = {
        "power_strike": ("强力斩", "将重心与爆发力集中到一次沉重斩击中的武技。"),
        "shield_bash": ("盾击", "以盾牌正面撞击目标，打乱其动作与站位。"),
        "parry": ("格挡", "依靠时机与武器控制化解对手攻势的防御武技。"),
        "sweeping_slash": ("横扫斩", "以大幅横斩压迫周边近距离敌人的群体武技。"),
        "battle_focus": ("战意凝神", "通过呼吸、步伐与意志调整，将自身状态稳固到最佳节奏。"),
    }
    options: dict[str, CharacterBuildChoiceOption] = {}
    for war_art_id, (fallback_name, fallback_desc) in defaults.items():
        definition = war_arts.get(war_art_id)
        label = getattr(definition, "name", "") or fallback_name
        options[war_art_id] = _choice(
            war_art_id,
            label,
            getattr(definition, "description", "") or fallback_desc,
            "skill",
            definition_id=war_art_id,
            metadata={
                "skill_name": label,
                "war_art_name": label,
                "martial_cost": int(getattr(definition, "martial_cost", 1) or 1),
            },
        )
    return options


def _granted_item_options() -> list[CharacterBuildChoiceOption]:
    _, _, _, items = _library_indexes()
    potion = items.get("healing_potion")
    return [
        _choice(
            "healing_potion_bundle",
            getattr(potion, "name", "治疗药水"),
            getattr(potion, "description", "") or "起始恢复药水。",
            "item",
            definition_id="healing_potion",
            metadata={
                "name": getattr(potion, "name", "治疗药水"),
                "item_type": "consumable",
                "slot_type": "misc",
                "description": getattr(potion, "description", "") or "起始恢复药水。",
                "value": getattr(potion, "value", 50),
                "quantity": 3,
            },
        )
    ]


def _specialization_bundle(specialization: str) -> dict[str, Any]:
    spell_map = _spell_options()
    equipment_map = _equipment_options()
    skill_map = _war_art_options()
    if specialization == "mage":
        return {
            "char_class": "法师",
            "spell_pick_count": 3,
            "equipment_pick_count": 1,
            "skill_pick_count": 0,
            "spell_options": [spell_map[item] for item in ["fire_bolt", "magic_missile", "shield", "burning_hands", "scorching_ray", "thunderwave", "detect_magic", "misty_step", "invisibility", "fireball"]],
            "equipment_options": [equipment_map[item] for item in ["legacy_weapon_法杖", "legacy_weapon_木杖", "legacy_weapon_短剑"] if item in equipment_map],
            "skill_options": [],
            "granted_armor": equipment_map.get("legacy_armor_法袍"),
        }
    return {
        "char_class": "战士",
        "spell_pick_count": 2,
        "equipment_pick_count": 2,
        "skill_pick_count": 2,
        "spell_options": [spell_map[item] for item in ["shield", "thunderwave", "magic_missile", "detect_magic", "misty_step"]],
        "equipment_options": [equipment_map[item] for item in ["starter_longsword", "starter_battleaxe", "starter_spear", "starter_warhammer", "starter_greatsword"]],
        "skill_options": [skill_map[item] for item in ["power_strike", "shield_bash", "parry", "sweeping_slash", "battle_focus"]],
        "granted_armor": equipment_map.get("legacy_armor_锁子甲"),
    }


def calculate_point_buy_cost(scores: Dnd5eAbilityScores) -> int:
    total = 0
    for field in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
        value = int(getattr(scores, field))
        if value < 8 or value > 15:
            raise ValueError("ability scores must be between 8 and 15 during build")
        total += _POINT_BUY_COSTS[value]
    return total


def _default_score_template(specialization: str | None) -> Dnd5eAbilityScores:
    if specialization == "mage":
        return Dnd5eAbilityScores(strength=8, dexterity=14, constitution=13, intelligence=15, wisdom=12, charisma=10)
    return Dnd5eAbilityScores(strength=15, dexterity=13, constitution=14, intelligence=8, wisdom=10, charisma=12)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _maybe_ai_json(config: Any, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
    if not has_ai_config(config):
        return None
    client = create_sync_client(config)
    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **build_completion_options(config),
        )
    except Exception:
        return None
    text = str(getattr(getattr(response.choices[0], "message", None), "content", "") or "")
    return _extract_json_object(text)


def get_character_build_state(session_id: str) -> CharacterBuildStateResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    ensure_character_build_state(save)
    config = None
    try:
        if storage_state.config_path.exists():
            from app.models.schemas import ChatConfig

            config = ChatConfig.model_validate(read_json(storage_state.config_path))
    except Exception:
        config = None
    capabilities = CharacterBuildMediaCapabilities.model_validate(
        build_media_capabilities(config) if config is not None else {}
    )
    state = save.character_build_state
    return CharacterBuildStateResponse(
        session_id=session_id,
        state=state,
        forced_entry=state.player_status != "completed",
        can_build_companion=state.player_status == "completed",
        companion_offer_pending=state.player_status == "completed" and not state.initial_companion_offer_seen and not save.team_state.members,
        media_capabilities=capabilities,
    )


def get_character_build_options(kind: str, specialization: str) -> CharacterBuildOptionsResponse:
    bundle = _specialization_bundle(specialization)
    return CharacterBuildOptionsResponse(
        kind=kind,  # type: ignore[arg-type]
        specialization=specialization,  # type: ignore[arg-type]
        point_buy_total=27,
        point_buy_costs={str(key): value for key, value in _POINT_BUY_COSTS.items()},
        recommended_races=list(_RECOMMENDED_RACES),
        body_type_suggestions=list(_BODY_TYPES),
        spell_pick_count=bundle["spell_pick_count"],
        equipment_pick_count=bundle["equipment_pick_count"],
        skill_pick_count=bundle["skill_pick_count"],
        spell_options=bundle["spell_options"],
        equipment_options=bundle["equipment_options"],
        skill_options=bundle["skill_options"],
        granted_armor=bundle["granted_armor"],
        granted_items=_granted_item_options(),
    )


def suggest_basic_info(prompt: str, current: CharacterBuildBasicInfo | None = None, config: Any = None) -> CharacterBuildBasicInfoSuggestResponse:
    current = current or CharacterBuildBasicInfo()
    ai = _maybe_ai_json(
        config,
        "Return JSON with name, age, race, height_cm, body_type for a tabletop RPG character.",
        prompt,
    )
    if ai:
        return CharacterBuildBasicInfoSuggestResponse(basic_info=CharacterBuildBasicInfo.model_validate({**current.model_dump(mode="json"), **ai}))

    text = prompt.strip()
    race = next((item for item in _RECOMMENDED_RACES if item in text), current.race or "人类")
    body = next((item for item in _BODY_TYPES if item in text), current.body_type or "匀称")
    numbers = [int(item) for item in re.findall(r"\d{2,3}", text)]
    age = next((item for item in numbers if 10 <= item <= 120), current.age)
    height = next((item for item in numbers if 120 <= item <= 250), current.height_cm)
    name = current.name or "冒险者"
    quoted = re.search(r"[“\"]([^”\"]+)[”\"]", text)
    if quoted:
        name = quoted.group(1)
    return CharacterBuildBasicInfoSuggestResponse(
        basic_info=CharacterBuildBasicInfo(name=name, age=age, race=race, height_cm=height, body_type=body)
    )


def suggest_abilities(prompt: str, specialization: str | None = None, current_scores: Dnd5eAbilityScores | None = None, config: Any = None) -> CharacterBuildAbilitySuggestResponse:
    ai = _maybe_ai_json(
        config,
        "Return JSON with strength,dexterity,constitution,intelligence,wisdom,charisma between 8 and 15 and total point-buy <= 27.",
        prompt,
    )
    if ai:
        scores = Dnd5eAbilityScores.model_validate(ai)
    else:
        scores = current_scores or _default_score_template(specialization)
    points = calculate_point_buy_cost(scores)
    return CharacterBuildAbilitySuggestResponse(ability_scores=scores, points_spent=points)


def suggest_portrait_prompt(prompt: str, basic_info: CharacterBuildBasicInfo | None = None, current_prompt: str = "", config: Any = None) -> CharacterBuildPortraitPromptSuggestResponse:
    basic_info = basic_info or CharacterBuildBasicInfo()
    ai = _maybe_ai_json(
        config,
        "Return JSON with portrait_prompt in Chinese for a character full-body portrait.",
        prompt,
    )
    if ai and str(ai.get("portrait_prompt") or "").strip():
        return CharacterBuildPortraitPromptSuggestResponse(portrait_prompt=str(ai["portrait_prompt"]).strip())
    parts = [current_prompt.strip()] if current_prompt.strip() else []
    if basic_info.race:
        parts.append(f"{basic_info.race}冒险者")
    if basic_info.body_type:
        parts.append(f"{basic_info.body_type}体型")
    if basic_info.height_cm:
        parts.append(f"约{basic_info.height_cm}cm")
    if prompt.strip():
        parts.append(prompt.strip())
    parts.append(_BUILD_BASE_PROMPT)
    return CharacterBuildPortraitPromptSuggestResponse(portrait_prompt="，".join([item for item in parts if item]))


def suggest_portrait_prompt(prompt: str, basic_info: CharacterBuildBasicInfo | None = None, current_prompt: str = "", config: Any = None) -> CharacterBuildPortraitPromptSuggestResponse:
    basic_info = basic_info or CharacterBuildBasicInfo()
    ai = _maybe_ai_json(
        config,
        "Return JSON with portrait_prompt in Chinese for a character full-body portrait.",
        prompt,
    )
    if ai and str(ai.get("portrait_prompt") or "").strip():
        return CharacterBuildPortraitPromptSuggestResponse(
            portrait_prompt=build_portrait_generation_prompt(str(ai["portrait_prompt"]).strip(), basic_info)
        )
    merged_prompt = "，".join([item for item in [current_prompt.strip(), prompt.strip()] if item])
    return CharacterBuildPortraitPromptSuggestResponse(
        portrait_prompt=build_portrait_generation_prompt(merged_prompt, basic_info)
    )


def _pick_first_ids(options: Iterable[str], count: int) -> list[str]:
    result: list[str] = []
    for item in options:
        result.append(item)
        if len(result) >= count:
            break
    return result


def suggest_loadout(
    specialization: str,
    prompt: str = "",
    available_spell_option_ids: list[str] | None = None,
    available_equipment_option_ids: list[str] | None = None,
    available_skill_option_ids: list[str] | None = None,
    config: Any = None,
) -> CharacterBuildLoadoutSuggestResponse:
    bundle = _specialization_bundle(specialization)
    spell_ids = available_spell_option_ids or [item.option_id for item in bundle["spell_options"]]
    equipment_ids = available_equipment_option_ids or [item.option_id for item in bundle["equipment_options"]]
    skill_ids = available_skill_option_ids or [item.option_id for item in bundle["skill_options"]]
    ai = _maybe_ai_json(
        config,
        "Return JSON with spell_option_ids,equipment_option_ids,skill_option_ids. Only use provided IDs.",
        json.dumps(
            {
                "prompt": prompt,
                "spell_option_ids": spell_ids,
                "equipment_option_ids": equipment_ids,
                "skill_option_ids": skill_ids,
            },
            ensure_ascii=False,
        ),
    )
    if ai:
        return CharacterBuildLoadoutSuggestResponse(
            spell_option_ids=[item for item in ai.get("spell_option_ids", []) if item in spell_ids][: bundle["spell_pick_count"]],
            equipment_option_ids=[item for item in ai.get("equipment_option_ids", []) if item in equipment_ids][: bundle["equipment_pick_count"]],
            skill_option_ids=[item for item in ai.get("skill_option_ids", []) if item in skill_ids][: bundle["skill_pick_count"]],
        )
    return CharacterBuildLoadoutSuggestResponse(
        spell_option_ids=_pick_first_ids(spell_ids, bundle["spell_pick_count"]),
        equipment_option_ids=_pick_first_ids(equipment_ids, bundle["equipment_pick_count"]),
        skill_option_ids=_pick_first_ids(skill_ids, bundle["skill_pick_count"]),
    )


def suggest_companion_flavor(
    prompt: str,
    basic_info: CharacterBuildBasicInfo | None = None,
    appearance: str = "",
    current: CharacterBuildCompanionFlavor | None = None,
    config: Any = None,
) -> CharacterBuildCompanionFlavorSuggestResponse:
    current = current or CharacterBuildCompanionFlavor()
    ai = _maybe_ai_json(
        config,
        "Return JSON with personality,speaking_style,cognition,secret,likes for a companion NPC.",
        json.dumps(
            {
                "prompt": prompt,
                "basic_info": (basic_info or CharacterBuildBasicInfo()).model_dump(mode="json"),
                "appearance": appearance,
            },
            ensure_ascii=False,
        ),
    )
    if ai:
        return CharacterBuildCompanionFlavorSuggestResponse(
            flavor=CharacterBuildCompanionFlavor.model_validate({**current.model_dump(mode="json"), **ai})
        )
    text = prompt.strip() or "稳重，话少，但可靠。"
    flavor = CharacterBuildCompanionFlavor(
        personality=current.personality or ("寡言" if "寡言" in text else "稳重"),
        speaking_style=current.speaking_style or ("低声简短" if "寡言" in text else "说话克制"),
        cognition=current.cognition or "重视同伴安全",
        secret=current.secret or "暗中保留了一条未公开的旧线索。",
        likes=current.likes or ["安静的夜晚", "可靠的同伴"],
    )
    return CharacterBuildCompanionFlavorSuggestResponse(flavor=flavor)


def _validate_selection(selection: CharacterBuildLoadoutSelection, specialization: str) -> dict[str, list[CharacterBuildChoiceOption]]:
    bundle = _specialization_bundle(specialization)
    spell_map = {item.option_id: item for item in bundle["spell_options"]}
    equipment_map = {item.option_id: item for item in bundle["equipment_options"]}
    skill_map = {item.option_id: item for item in bundle["skill_options"]}

    if len(set(selection.spell_option_ids)) != bundle["spell_pick_count"]:
        raise ValueError("invalid spell selection count")
    if len(set(selection.equipment_option_ids)) != bundle["equipment_pick_count"]:
        raise ValueError("invalid equipment selection count")
    if len(set(selection.skill_option_ids)) != bundle["skill_pick_count"]:
        raise ValueError("invalid skill selection count")

    chosen_spells = [spell_map[item] for item in selection.spell_option_ids if item in spell_map]
    chosen_equipment = [equipment_map[item] for item in selection.equipment_option_ids if item in equipment_map]
    chosen_skills = [skill_map[item] for item in selection.skill_option_ids if item in skill_map]

    if len(chosen_spells) != bundle["spell_pick_count"] or len(chosen_equipment) != bundle["equipment_pick_count"] or len(chosen_skills) != bundle["skill_pick_count"]:
        raise ValueError("selection contains unknown option ids")
    return {
        "spells": chosen_spells,
        "equipment": chosen_equipment,
        "skills": chosen_skills,
        "granted_items": _granted_item_options(),
        "granted_armor": [bundle["granted_armor"]] if bundle["granted_armor"] is not None else [],
    }


def _origin_stamp(origin_ref: str) -> OriginStamp:
    return OriginStamp(origin_kind="starting_build", origin_ref=origin_ref)


def _language_for_race(race: str) -> list[str]:
    return list(_BASE_LANGUAGE_BY_RACE.get(race, ["通用语"]))


def _con_mod(scores: Dnd5eAbilityScores) -> int:
    return (int(scores.constitution) - 10) // 2


def _build_inventory_item(option: CharacterBuildChoiceOption, item_id: str, origin_ref: str):
    from app.models.schemas import InventoryItem

    metadata = option.metadata
    slot_type = str(metadata.get("slot_type") or ("misc" if option.source_kind == "item" else "weapon"))
    if slot_type not in {"weapon", "armor", "misc"}:
        slot_type = "misc"
    return InventoryItem(
        item_id=item_id,
        name=str(metadata.get("name") or option.label),
        item_type=str(metadata.get("item_type") or option.source_kind),
        description=str(metadata.get("description") or option.description),
        value=int(metadata.get("value") or 0),
        quantity=max(1, int(metadata.get("quantity") or 1)),
        slot_type=slot_type,  # type: ignore[arg-type]
        effect=str(metadata.get("effect") or ""),
        attack_bonus=int(metadata.get("attack_bonus") or 0),
        armor_bonus=int(metadata.get("armor_bonus") or 0),
        origin=_origin_stamp(origin_ref),
    )


def _apply_common_build(
    *,
    profile: PlayerStaticData,
    basic_info: CharacterBuildBasicInfo,
    specialization: str,
    ability_scores: Dnd5eAbilityScores,
    appearance: str,
    portrait,
    loadout: dict[str, list[CharacterBuildChoiceOption]],
    origin_ref: str,
) -> PlayerStaticData:
    template = _class_template("法师" if specialization == "mage" else "战士")
    sheet = profile.dnd5e_sheet
    profile.name = basic_info.name.strip() or profile.name
    profile.age = basic_info.age
    profile.height_cm = basic_info.height_cm
    profile.body_type = basic_info.body_type
    profile.appearance = appearance.strip()
    profile.portrait = portrait
    sheet.race = basic_info.race.strip() or "人类"
    sheet.char_class = "法师" if specialization == "mage" else "战士"
    sheet.background = "起始构筑"
    sheet.level = 1
    sheet.proficiency_bonus = 2
    sheet.ability_scores = ability_scores
    sheet.saving_throws_proficient = list(template.get("saving_throws") or [])
    base_skills = list(template.get("skills") or [])
    chosen_skill_names = [str(item.metadata.get("skill_name") or item.label) for item in loadout["skills"]]
    chosen_war_art_names = [str(item.metadata.get("war_art_name") or item.metadata.get("skill_name") or item.label) for item in loadout["skills"]]
    sheet.skills_proficient = base_skills + chosen_skill_names
    sheet.skill_origins = {skill: _origin_stamp(origin_ref) for skill in chosen_skill_names}
    sheet.war_arts = chosen_war_art_names
    sheet.war_art_origins = {war_art: _origin_stamp(origin_ref) for war_art in chosen_war_art_names}
    sheet.languages = _language_for_race(sheet.race)
    sheet.tool_proficiencies = list(template.get("tools") or [])
    sheet.features_traits = list(template.get("features") or [])
    sheet.spells = [str(item.metadata.get("spell_name") or item.label) for item in loadout["spells"]]
    sheet.spell_origins = {spell: _origin_stamp(origin_ref) for spell in sheet.spells}
    resource_cap = max(1, min(int(sheet.level or 1), 9))
    first_level_slots = resource_cap if sheet.spells else 0
    sheet.spell_slots_max.level_1 = first_level_slots
    sheet.spell_slots_current.level_1 = first_level_slots
    for level in range(2, 10):
        setattr(sheet.spell_slots_max, f"level_{level}", 0)
        setattr(sheet.spell_slots_current, f"level_{level}", 0)
    martial_points = resource_cap if sheet.war_arts else 0
    sheet.martial_points_maximum = martial_points
    sheet.martial_points_current = martial_points
    hit_dice = str(template.get("hit_dice") or "1d8")
    hit_die_size = int(hit_dice.split("d", 1)[1]) if "d" in hit_dice else 8
    con_mod = _con_mod(ability_scores)
    hp_max = max(4, hit_die_size + con_mod)
    sheet.hit_dice = hit_dice
    sheet.hit_points.maximum = hp_max
    sheet.hit_points.current = hp_max
    sheet.speed_ft = 35 if sheet.race == "半精灵" else 30
    sheet.stamina_maximum = max(8, 10 + max(0, con_mod))
    sheet.stamina_current = sheet.stamina_maximum
    profile.move_speed_mph = max(3200, sheet.speed_ft * 140)

    backpack_items = []
    for index, option in enumerate(loadout["equipment"] + loadout["granted_armor"] + loadout["granted_items"], start=1):
        backpack_items.append(_build_inventory_item(option, f"{profile.player_id}_item_{index}", origin_ref))
    sheet.backpack.gold = 50
    sheet.backpack.items = backpack_items
    sheet.equipment = [item.name for item in backpack_items if item.slot_type in {"weapon", "armor"}]
    equipped_weapon = next((item for item in backpack_items if item.slot_type == "weapon"), None)
    equipped_armor = next((item for item in backpack_items if item.slot_type == "armor"), None)
    sheet.equipment_slots.weapon_item_id = equipped_weapon.item_id if equipped_weapon else None
    sheet.equipment_slots.armor_item_id = equipped_armor.item_id if equipped_armor else None
    _recompute_player_derived(profile)
    return profile


def _player_archive_manifest_path(archive_id: str) -> Path:
    root = _player_build_root() / archive_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "manifest.json"


def _player_archive_portrait_path(archive_id: str) -> Path:
    root = _player_build_root() / archive_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "portrait.png"


def _write_player_archive(profile: PlayerStaticData, specialization: str, basic_info: CharacterBuildBasicInfo, archive_id: str) -> None:
    manifest = {
        "archive_id": archive_id,
        "name": profile.name,
        "created_at": _utc_now(),
        "basic_info": basic_info.model_dump(mode="json"),
        "specialization": specialization,
        "player_static_data": profile.model_dump(mode="json"),
    }
    write_json_atomic(_player_archive_manifest_path(archive_id), manifest)


def complete_player_build(payload: CharacterBuildPlayerCompleteRequest) -> CharacterBuildPlayerCompleteResponse:
    save = get_current_save(default_session_id=payload.session_id)
    ensure_character_build_state(save)
    if save.character_build_state.player_status == "completed":
        raise ValueError("player build already completed for this save")
    points = calculate_point_buy_cost(payload.ability_scores)
    if points > 27:
        raise ValueError("point buy exceeds 27")
    asset = load_asset(payload.final_portrait_asset_id)
    if asset.variant_kind != "final_portrait":
        raise ValueError("final_portrait_asset_id must reference a finalized portrait")

    archive_id = _new_id("player_build")
    portrait = copy_asset_to_path(payload.final_portrait_asset_id, _player_archive_portrait_path(archive_id))
    profile = PlayerStaticData(player_id=save.player_static_data.player_id, role_type="player")
    profile.build_archive_id = archive_id
    loadout = _validate_selection(payload.loadout, payload.specialization)
    profile = _apply_common_build(
        profile=profile,
        basic_info=payload.basic_info,
        specialization=payload.specialization,
        ability_scores=payload.ability_scores,
        appearance=payload.appearance,
        portrait=portrait,
        loadout=loadout,
        origin_ref=archive_id,
    )
    save.player_static_data = profile
    save.character_build_state.player_status = "completed"
    save.character_build_state.initial_companion_offer_seen = False
    save.character_build_state.updated_at = _utc_now()
    save_current(save)
    _write_player_archive(profile, payload.specialization, payload.basic_info, archive_id)
    return CharacterBuildPlayerCompleteResponse(session_id=payload.session_id, player=profile, state=save.character_build_state, archive_id=archive_id)


def complete_companion_build(payload: CharacterBuildCompanionCompleteRequest) -> CharacterBuildCompanionCompleteResponse:
    save = get_current_save(default_session_id=payload.session_id)
    ensure_character_build_state(save)
    points = calculate_point_buy_cost(payload.ability_scores)
    if points > 27:
        raise ValueError("point buy exceeds 27")
    asset = load_asset(payload.final_portrait_asset_id)
    if asset.variant_kind != "final_portrait":
        raise ValueError("final_portrait_asset_id must reference a finalized portrait")

    role_id = _new_id("build_companion")
    loadout = _validate_selection(payload.loadout, payload.specialization)
    temp_profile = PlayerStaticData(player_id=role_id, role_type="npc")
    portrait = copy_asset_to_path(payload.final_portrait_asset_id, _retained_build_root() / role_id / "portrait.png")
    profile = _apply_common_build(
        profile=temp_profile,
        basic_info=payload.basic_info,
        specialization=payload.specialization,
        ability_scores=payload.ability_scores,
        appearance=payload.appearance,
        portrait=portrait,
        loadout=loadout,
        origin_ref=role_id,
    )
    role = NpcRoleCard(
        role_id=role_id,
        name=payload.basic_info.name.strip() or "起始随从",
        zone_id=save.area_snapshot.current_zone_id,
        sub_zone_id=save.area_snapshot.current_sub_zone_id,
        state="in_team",
        personality=payload.flavor.personality,
        speaking_style=payload.flavor.speaking_style,
        appearance=payload.appearance,
        background="起始随从构筑",
        cognition=payload.flavor.cognition,
        secret=payload.flavor.secret,
        likes=list(payload.flavor.likes),
        portrait=portrait,
        profile=profile,
    )
    save.role_pool.append(role)
    state = ensure_team_state(save)
    member = TeamMember(
        role_id=role.role_id,
        name=role.name,
        origin_zone_id=save.area_snapshot.current_zone_id,
        origin_sub_zone_id=save.area_snapshot.current_sub_zone_id,
        affinity=70,
        trust=60,
        join_source="story",
        join_reason="起始随从构筑",
        is_debug=False,
    )
    state.members.append(member)
    sync_team_members_with_player_in_save(save)
    retained = retained_npc_service.retain_npc(role)
    role.retained_id = retained.retained_id
    retained_portrait = copy_asset_to_path(payload.final_portrait_asset_id, _retained_build_root() / retained.retained_id / "portrait.png")
    role.portrait = retained_portrait
    role.profile.portrait = retained_portrait
    retained_npc_service.update_role_data(
        retained.retained_id,
        role.model_dump(mode="json"),
        archive_dir=str((_retained_build_root() / retained.retained_id).relative_to(_user_root())).replace("\\", "/"),
    )
    save_current(save)
    return CharacterBuildCompanionCompleteResponse(session_id=payload.session_id, role=role, member=member, retained_id=retained.retained_id)


def mark_companion_offer_seen(session_id: str, seen: bool = True) -> CharacterBuildStateResponse:
    save = get_current_save(default_session_id=session_id)
    ensure_character_build_state(save)
    save.character_build_state.initial_companion_offer_seen = seen
    save.character_build_state.updated_at = _utc_now()
    save_current(save)
    return get_character_build_state(session_id)


def list_player_build_seeds() -> PlayerBuildSeedListResponse:
    items: list[PlayerBuildSeedSummary] = []
    for directory in sorted(_player_build_root().glob("*")):
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            payload = read_json(manifest_path)
        except Exception:
            continue
        player_static_data = payload.get("player_static_data") or {}
        portrait = player_static_data.get("portrait")
        items.append(
            PlayerBuildSeedSummary(
                archive_id=str(payload.get("archive_id") or directory.name),
                name=str(payload.get("name") or "未命名角色"),
                created_at=str(payload.get("created_at") or ""),
                portrait=(portrait if portrait else None),
            )
        )
    return PlayerBuildSeedListResponse(items=items)


def get_player_build_seed(archive_id: str) -> PlayerBuildSeedResponse:
    payload = read_json(_player_archive_manifest_path(archive_id))
    player = PlayerStaticData.model_validate(payload["player_static_data"])
    basic_info = CharacterBuildBasicInfo.model_validate(payload.get("basic_info") or {})
    seed = PlayerBuildSeed(
        archive_id=str(payload.get("archive_id") or archive_id),
        name=str(payload.get("name") or player.name),
        created_at=str(payload.get("created_at") or ""),
        basic_info=basic_info,
        specialization=str(payload.get("specialization") or "warrior"),  # type: ignore[arg-type]
        player_static_data=player,
    )
    return PlayerBuildSeedResponse(seed=seed)


def list_companion_build_seeds() -> CompanionBuildSeedListResponse:
    items = []
    for npc in retained_npc_service.get_all():
        portrait = (npc.role_data or {}).get("portrait") or ((npc.role_data or {}).get("profile") or {}).get("portrait")
        items.append(
            CompanionBuildSeedSummary(
                retained_id=npc.retained_id,
                name=npc.name,
                retained_at=npc.retained_at,
                portrait=portrait if portrait else None,
            )
        )
    return CompanionBuildSeedListResponse(items=items)


def get_companion_build_seed(retained_id: str) -> CompanionBuildSeedResponse:
    npc = retained_npc_service.get_by_id(retained_id)
    if npc is None:
        raise KeyError("retained NPC not found")
    role = NpcRoleCard.model_validate(npc.role_data)
    return CompanionBuildSeedResponse(retained_id=npc.retained_id, retained_at=npc.retained_at, role=role)
