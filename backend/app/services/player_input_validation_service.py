from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ChatConfig,
    PlayerInputResourceStatus,
    PlayerInputValidationIssue,
    PlayerInputValidationRequest,
    PlayerInputValidationResponse,
)
from app.services import world_service as world
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.ai_protocol_contract_service import (
    AI_CONFIG_REQUIRED,
    AI_PROTOCOL_ENUM_INVALID,
    AI_PROTOCOL_REPAIR_FAILED,
    AI_PROVIDER_CALL_FAILED,
    AiProtocolContractError,
    EnumContractField,
    allow_protocol_repair,
    require_ai_config,
    validate_or_repair_json_payload,
)
from app.services.item_template_service import ensure_definition_for_inventory_item, load_template_library

PLAYER_INPUT_VALIDATION_FAILED = "PLAYER_INPUT_VALIDATION_FAILED"

_VALIDATION_ISSUE_CODES = (
    "multiple_world_actions",
    "claimed_outcome",
    "controls_other_actor",
)
_VALIDATION_FIELDS = (
    EnumContractField(field_path="resource_kind", allowed_ids=("none", "spell", "war_art", "item")),
    EnumContractField(field_path="suggested_action_type", allowed_ids=("auto", "attack", "check", "item_use")),
    EnumContractField(field_path="issue_codes[]", allowed_ids=_VALIDATION_ISSUE_CODES, required=False),
)
_LOOKUP_SEPARATORS = re.compile(r"[\s_\-]+")
_SYSTEM_PROMPT = (
    "You validate tabletop RPG player input before it is submitted. "
    "Return JSON only."
)
_USER_PROMPT = (
    "Normalize the player input before submission.\n"
    "Rules:\n"
    "1. Keep at most one world-impacting action. If multiple actions are present, keep only the first.\n"
    "2. Remove claimed outcomes. Rewrite them as attempts.\n"
    "3. Remove direct control over other actors' actions, reactions, or outcomes.\n"
    "4. Keep speech_text close to the original intent.\n"
    "5. If action_text depends on a spell, war art, or item, set resource_kind and resource_name.\n"
    "6. normalized_action_text must be the corrected action that can be submitted after structural fixes.\n"
    "7. fallback_action_text must be a visible fallback attempt or stance that does not require the spell, war art, or item to succeed.\n"
    "8. issue_codes may only contain: multiple_world_actions, claimed_outcome, controls_other_actor.\n"
    "9. suggested_action_type may only contain: auto, attack, check, item_use.\n"
    "10. Return valid JSON with exactly these keys: normalized_action_text, normalized_speech_text, fallback_action_text, issue_codes, resource_kind, resource_name, suggested_action_type.\n"
    "actor_name=$actor_name\n"
    "entry_point=$entry_point\n"
    "role_action_status=$role_action_status\n"
    "action_text=$action_text\n"
    "speech_text=$speech_text\n"
    "known_spells_json=$known_spells_json\n"
    "spell_slots_current_json=$spell_slots_current_json\n"
    "known_war_arts_json=$known_war_arts_json\n"
    "martial_points_current=$martial_points_current\n"
    "equipped_weapon_name=$equipped_weapon_name\n"
    "inventory_item_names_json=$inventory_item_names_json"
)


def _normalize_lookup(value: str) -> str:
    return _LOOKUP_SEPARATORS.sub("", str(value or "").strip().lower())


def _compose_display_text(action_text: str, speech_text: str) -> str:
    lines: list[str] = []
    if action_text.strip():
        lines.append(f"Action: {action_text.strip()}")
    if speech_text.strip():
        lines.append(f"Speech: {speech_text.strip()}")
    return "\n".join(lines).strip()


def _spell_slot_field(level: int) -> str:
    return f"level_{max(1, min(int(level or 1), 9))}"


def _current_spell_slots(sheet: Any, level: int) -> int:
    slots = getattr(sheet, "spell_slots_current", None)
    return int(getattr(slots, _spell_slot_field(level), 0) or 0)


def _equipped_weapon_name(profile: Any) -> str:
    equipment = getattr(profile.dnd5e_sheet, "equipment_slots", None)
    backpack = getattr(getattr(profile.dnd5e_sheet, "backpack", None), "items", []) or []
    weapon_item_id = str(getattr(equipment, "weapon_item_id", "") or "").strip()
    if not weapon_item_id:
        return ""
    item = next((entry for entry in backpack if entry.item_id == weapon_item_id), None)
    return str(getattr(item, "name", "") or "").strip()


def _has_equipped_weapon(profile: Any) -> bool:
    equipment = getattr(profile.dnd5e_sheet, "equipment_slots", None)
    backpack = getattr(getattr(profile.dnd5e_sheet, "backpack", None), "items", []) or []
    weapon_item_id = str(getattr(equipment, "weapon_item_id", "") or "").strip()
    if not weapon_item_id:
        return False
    item = next((entry for entry in backpack if entry.item_id == weapon_item_id), None)
    return bool(item is not None and getattr(item, "slot_type", "") == "weapon")


def _issue_message(code: str, resource_name: str = "") -> tuple[str, str]:
    if code == "multiple_world_actions":
        return "一次只能提交一个会影响世界状态的动作。", "action_text"
    if code == "claimed_outcome":
        return "输入里不能直接宣告动作结果，只能描述尝试。", "action_text"
    if code == "controls_other_actor":
        return "输入里不能直接指定其他角色的动作、反应或结果。", "action_text"
    if code == "spell_not_known":
        if resource_name:
            return f"当前角色未掌握法术“{resource_name}”。", "action_text"
        return "当前角色未掌握该法术。", "action_text"
    if code == "spell_slot_insufficient":
        if resource_name:
            return f"当前法术位不足，无法使用“{resource_name}”。", "action_text"
        return "当前法术位不足。", "action_text"
    if code == "war_art_not_known":
        if resource_name:
            return f"当前角色未掌握武技“{resource_name}”。", "action_text"
        return "当前角色未掌握该武技。", "action_text"
    if code == "war_art_points_insufficient":
        if resource_name:
            return f"当前武技点不足，无法使用“{resource_name}”。", "action_text"
        return "当前武技点不足。", "action_text"
    if code == "war_art_requires_weapon":
        if resource_name:
            return f"使用武技“{resource_name}”前需要先装备任意武器。", "action_text"
        return "使用该武技前需要先装备任意武器。", "action_text"
    if code == "item_not_owned":
        if resource_name:
            return f"当前背包里没有“{resource_name}”。", "action_text"
        return "当前背包里没有该道具。", "action_text"
    if code == "speech_only_required":
        return "当前状态下只能输入语言，不能提交会影响世界的动作。", "action_text"
    if code == "actor_dead":
        return "当前角色已死亡，不能再提交动作。", "action_text"
    return code, "action_text"


def _append_issue(
    issues: list[PlayerInputValidationIssue],
    seen: set[str],
    code: str,
    resource_name: str = "",
) -> None:
    if code in seen:
        return
    seen.add(code)
    message, field = _issue_message(code, resource_name)
    issues.append(PlayerInputValidationIssue(code=code, message=message, field=field))  # type: ignore[arg-type]


def _known_spell_names(profile: Any) -> list[str]:
    return [
        str(item or "").strip()
        for item in getattr(profile.dnd5e_sheet, "spells", []) or []
        if str(item or "").strip()
    ]


def _known_war_art_names(profile: Any) -> list[str]:
    return [
        str(item or "").strip()
        for item in getattr(profile.dnd5e_sheet, "war_arts", []) or []
        if str(item or "").strip()
    ]


def _inventory_item_names(profile: Any) -> list[str]:
    names: list[str] = []
    for item in getattr(getattr(profile.dnd5e_sheet, "backpack", None), "items", []) or []:
        item_name = str(getattr(item, "name", "") or "").strip()
        item_id = str(getattr(item, "item_id", "") or "").strip()
        if item_name:
            names.append(item_name)
        if item_id:
            names.append(item_id)
    return names


def _validation_prompt(
    *,
    actor_name: str,
    entry_point: str,
    action_text: str,
    speech_text: str,
    role_action_status: str,
    known_spells: list[str],
    spell_slots_current: dict[str, int],
    known_war_arts: list[str],
    martial_points_current: int,
    equipped_weapon_name: str,
    inventory_item_names: list[str],
) -> str:
    return prompt_table.render(
        "player.input.validate.user",
        _USER_PROMPT,
        actor_name=actor_name,
        entry_point=entry_point,
        role_action_status=role_action_status,
        action_text=action_text,
        speech_text=speech_text,
        known_spells_json=json.dumps(known_spells, ensure_ascii=False),
        spell_slots_current_json=json.dumps(spell_slots_current, ensure_ascii=False),
        known_war_arts_json=json.dumps(known_war_arts, ensure_ascii=False),
        martial_points_current=str(martial_points_current),
        equipped_weapon_name=equipped_weapon_name,
        inventory_item_names_json=json.dumps(inventory_item_names, ensure_ascii=False),
    )


def _validation_system_prompt() -> str:
    return prompt_table.get_text("player.input.validate.system", _SYSTEM_PROMPT)


def _call_validation_model(
    *,
    config: ChatConfig | None,
    actor_name: str,
    entry_point: str,
    action_text: str,
    speech_text: str,
    role_action_status: str,
    known_spells: list[str],
    spell_slots_current: dict[str, int],
    known_war_arts: list[str],
    martial_points_current: int,
    equipped_weapon_name: str,
    inventory_item_names: list[str],
) -> dict[str, Any]:
    try:
        config = require_ai_config(config)
    except AiProtocolContractError as exc:
        if exc.code == AI_CONFIG_REQUIRED:
            raise ValueError("AI_CONFIG_REQUIRED: player_input_validation") from exc
        raise

    prompt = _validation_prompt(
        actor_name=actor_name,
        entry_point=entry_point,
        action_text=action_text,
        speech_text=speech_text,
        role_action_status=role_action_status,
        known_spells=known_spells,
        spell_slots_current=spell_slots_current,
        known_war_arts=known_war_arts,
        martial_points_current=martial_points_current,
        equipped_weapon_name=equipped_weapon_name,
        inventory_item_names=inventory_item_names,
    )
    system_prompt = _validation_system_prompt()

    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise ValueError(f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc

    raw_content = str(response.choices[0].message.content or "").strip()
    try:
        parsed = world._extract_json_content(raw_content)
    except Exception as exc:
        raise ValueError(PLAYER_INPUT_VALIDATION_FAILED) from exc

    try:
        with allow_protocol_repair():
            repaired = validate_or_repair_json_payload(
                parsed=parsed if isinstance(parsed, dict) else {},
                raw_json=raw_content,
                fields=_VALIDATION_FIELDS,
                config=config,
                system_prompt=system_prompt,
                original_prompt=prompt,
            )
    except AiProtocolContractError as exc:
        if exc.code == AI_PROVIDER_CALL_FAILED:
            raise ValueError(f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc
        if exc.code in {AI_PROTOCOL_ENUM_INVALID, AI_PROTOCOL_REPAIR_FAILED, AI_CONFIG_REQUIRED}:
            raise ValueError(PLAYER_INPUT_VALIDATION_FAILED) from exc
        raise ValueError(PLAYER_INPUT_VALIDATION_FAILED) from exc

    if not isinstance(repaired, dict):
        raise ValueError(PLAYER_INPUT_VALIDATION_FAILED)
    return repaired


def _build_structural_issues(issue_codes: list[str]) -> list[PlayerInputValidationIssue]:
    issues: list[PlayerInputValidationIssue] = []
    seen: set[str] = set()
    for code in issue_codes:
        if code not in _VALIDATION_ISSUE_CODES:
            continue
        _append_issue(issues, seen, code)
    return issues


def _match_owned_name(owned_names: list[str], normalized_name: str) -> str | None:
    matches = sorted({name for name in owned_names if _normalize_lookup(name) == normalized_name})
    if len(matches) != 1:
        return None
    return matches[0]


def _resolve_spell_owner_name(profile: Any, definition: Any | None, normalized_name: str) -> str | None:
    known_names = _known_spell_names(profile)
    direct_match = _match_owned_name(known_names, normalized_name)
    if direct_match:
        return direct_match
    if definition is None:
        return None
    definition_keys = {
        _normalize_lookup(getattr(definition, "definition_id", "")),
        _normalize_lookup(getattr(definition, "name", "")),
    }
    matches = sorted({name for name in known_names if _normalize_lookup(name) in definition_keys})
    if len(matches) != 1:
        return None
    return matches[0]


def _resolve_war_art_owner_name(profile: Any, definition: Any | None, normalized_name: str) -> str | None:
    known_names = _known_war_art_names(profile)
    direct_match = _match_owned_name(known_names, normalized_name)
    if direct_match:
        return direct_match
    if definition is None:
        return None
    definition_keys = {
        _normalize_lookup(getattr(definition, "definition_id", "")),
        _normalize_lookup(getattr(definition, "name", "")),
    }
    matches = sorted({name for name in known_names if _normalize_lookup(name) in definition_keys})
    if len(matches) != 1:
        return None
    return matches[0]


def _find_unique_definition(definitions: list[Any], normalized_name: str) -> Any | None:
    matches = [
        item
        for item in definitions
        if _normalize_lookup(getattr(item, "definition_id", "")) == normalized_name
        or _normalize_lookup(getattr(item, "name", "")) == normalized_name
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _resolve_spell_status(profile: Any, library: Any, mentioned_name: str) -> tuple[PlayerInputResourceStatus, str | None]:
    normalized_name = _normalize_lookup(mentioned_name)
    definition = _find_unique_definition(list(getattr(library, "spell_definitions", []) or []), normalized_name)
    resolved_name = _resolve_spell_owner_name(profile, definition, normalized_name)
    if not resolved_name:
        known_spells = _known_spell_names(profile)
        return (
            PlayerInputResourceStatus(
                check_status="failed",
                resource_kind="spell",
                mentioned_name=mentioned_name,
                requirement_summary="需要角色已掌握该法术。",
                current_summary=(
                    f"当前已掌握: {', '.join(known_spells[:12])}"
                    if known_spells
                    else "当前未掌握任何法术。"
                ),
            ),
            "spell_not_known",
        )

    required_amount = int(getattr(definition, "spell_cost", 1) or 1) if definition is not None else 1
    slot_level = max(1, required_amount)
    current_amount = _current_spell_slots(profile.dnd5e_sheet, slot_level)
    requirement_summary = (
        f"需要 1 个 {slot_level} 环法术位。"
        if definition is not None
        else "未找到法术定义，按 1 个 1 环法术位兜底校验。"
    )
    current_summary = f"当前 {slot_level} 环法术位: {current_amount}"
    status = PlayerInputResourceStatus(
        check_status="passed" if current_amount >= 1 else "failed",
        resource_kind="spell",
        mentioned_name=mentioned_name,
        resolved_name=resolved_name,
        resolved_definition_id=(getattr(definition, "definition_id", None) if definition is not None else None),
        required_amount=slot_level,
        current_amount=current_amount,
        requirement_summary=requirement_summary,
        current_summary=current_summary,
    )
    if current_amount < 1:
        return status, "spell_slot_insufficient"
    return status, None


def _resolve_war_art_status(profile: Any, library: Any, mentioned_name: str) -> tuple[PlayerInputResourceStatus, str | None]:
    normalized_name = _normalize_lookup(mentioned_name)
    definition = _find_unique_definition(list(getattr(library, "war_art_definitions", []) or []), normalized_name)
    resolved_name = _resolve_war_art_owner_name(profile, definition, normalized_name)
    if not resolved_name:
        known_war_arts = _known_war_art_names(profile)
        return (
            PlayerInputResourceStatus(
                check_status="failed",
                resource_kind="war_art",
                mentioned_name=mentioned_name,
                requirement_summary="需要角色已掌握该武技。",
                current_summary=(
                    f"当前已掌握: {', '.join(known_war_arts[:12])}"
                    if known_war_arts
                    else "当前未掌握任何武技。"
                ),
            ),
            "war_art_not_known",
        )

    required_amount = int(getattr(definition, "martial_cost", 1) or 1) if definition is not None else 1
    current_amount = int(getattr(profile.dnd5e_sheet, "martial_points_current", 0) or 0)
    current_weapon = _equipped_weapon_name(profile) or "未装备"
    status = PlayerInputResourceStatus(
        check_status="passed",
        resource_kind="war_art",
        mentioned_name=mentioned_name,
        resolved_name=resolved_name,
        resolved_definition_id=(getattr(definition, "definition_id", None) if definition is not None else None),
        required_amount=required_amount,
        current_amount=current_amount,
        requirement_summary=(
            f"需要 {required_amount} 点武技点，并且当前已装备任意武器。"
            if definition is not None
            else "未找到武技定义，按 1 点武技点并要求已装备任意武器兜底校验。"
        ),
        current_summary=f"当前武技点: {current_amount}; 当前武器: {current_weapon}",
    )
    if current_amount < required_amount:
        status.check_status = "failed"
        return status, "war_art_points_insufficient"
    if not _has_equipped_weapon(profile):
        status.check_status = "failed"
        return status, "war_art_requires_weapon"
    return status, None


def _resolve_item_status(profile: Any, mentioned_name: str) -> tuple[PlayerInputResourceStatus, str | None]:
    normalized_name = _normalize_lookup(mentioned_name)
    matches: list[tuple[Any, str]] = []
    backpack_items = getattr(getattr(profile.dnd5e_sheet, "backpack", None), "items", []) or []
    for item in backpack_items:
        definition_id = ensure_definition_for_inventory_item(item)
        candidate_keys = {
            _normalize_lookup(getattr(item, "name", "")),
            _normalize_lookup(getattr(item, "item_id", "")),
            _normalize_lookup(definition_id),
        }
        if normalized_name in candidate_keys:
            matches.append((item, definition_id))

    if len(matches) != 1:
        known_items = _inventory_item_names(profile)
        return (
            PlayerInputResourceStatus(
                check_status="failed",
                resource_kind="item",
                mentioned_name=mentioned_name,
                requirement_summary="需要背包里存在该道具。",
                current_summary=(
                    f"当前背包: {', '.join(known_items[:12])}"
                    if known_items
                    else "当前背包为空。"
                ),
            ),
            "item_not_owned",
        )

    matched_item, definition_id = matches[0]
    current_amount = int(getattr(matched_item, "quantity", 0) or 0)
    status = PlayerInputResourceStatus(
        check_status="passed" if current_amount > 0 else "failed",
        resource_kind="item",
        mentioned_name=mentioned_name,
        resolved_name=str(getattr(matched_item, "name", "") or "").strip(),
        resolved_definition_id=definition_id,
        required_amount=1,
        current_amount=current_amount,
        requirement_summary="需要背包里存在该道具。",
        current_summary=f"当前数量: {current_amount}",
    )
    if current_amount <= 0:
        return status, "item_not_owned"
    return status, None


def _resource_status(profile: Any, library: Any, resource_kind: str, resource_name: str) -> tuple[PlayerInputResourceStatus, str | None]:
    if resource_kind == "none" or not resource_name.strip():
        return PlayerInputResourceStatus(), None
    if resource_kind == "spell":
        return _resolve_spell_status(profile, library, resource_name)
    if resource_kind == "war_art":
        return _resolve_war_art_status(profile, library, resource_name)
    if resource_kind == "item":
        return _resolve_item_status(profile, resource_name)
    return PlayerInputResourceStatus(), None


def _action_state_issue(profile: Any, submitted_action_text: str) -> str | None:
    if not submitted_action_text.strip():
        return None
    role_action_status = str(getattr(profile.dnd5e_sheet, "role_action_status", "free_action") or "free_action")
    if role_action_status == "dead":
        return "actor_dead"
    if role_action_status in {"death_saving", "unable_to_act"}:
        return "speech_only_required"
    return None


def _build_summary(
    status: str,
    issues: list[PlayerInputValidationIssue],
    resource_status: PlayerInputResourceStatus,
) -> str:
    if status == "accepted":
        if resource_status.check_status == "passed" and resource_status.resolved_name:
            return f"输入已通过校验，资源检查通过：{resource_status.resolved_name}。"
        return "输入已通过校验，可以直接提交。"
    if issues:
        return "；".join(issue.message for issue in issues[:3])
    return "输入需要玩家确认后再提交。"


def validate_player_input(req: PlayerInputValidationRequest) -> PlayerInputValidationResponse:
    save = world.get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    actor_role_id, profile = world._get_actor_profile(save, req.actor_role_id)
    actor_kind = world._actor_kind(save, actor_role_id)

    action_text = str(req.action_text or "").strip()
    speech_text = str(req.speech_text or "").strip()
    if not action_text:
        return PlayerInputValidationResponse(
            session_id=req.session_id,
            entry_point=req.entry_point,
            actor_role_id=actor_role_id,
            actor_name=profile.name,
            actor_kind=actor_kind,  # type: ignore[arg-type]
            status="accepted",
            normalized_action_text="",
            normalized_speech_text=speech_text,
            fallback_action_text="",
            display_text=_compose_display_text("", speech_text),
            summary="当前没有可校验的动作输入，按原样继续。",
        )

    spell_slots_current = {
        _spell_slot_field(level): _current_spell_slots(profile.dnd5e_sheet, level)
        for level in range(1, 10)
    }
    ai_result = _call_validation_model(
        config=req.config,
        actor_name=profile.name,
        entry_point=req.entry_point,
        action_text=action_text,
        speech_text=speech_text,
        role_action_status=str(getattr(profile.dnd5e_sheet, "role_action_status", "free_action") or "free_action"),
        known_spells=_known_spell_names(profile),
        spell_slots_current=spell_slots_current,
        known_war_arts=_known_war_art_names(profile),
        martial_points_current=int(getattr(profile.dnd5e_sheet, "martial_points_current", 0) or 0),
        equipped_weapon_name=_equipped_weapon_name(profile),
        inventory_item_names=_inventory_item_names(profile),
    )

    normalized_action_text = str(ai_result.get("normalized_action_text") or "").strip() or action_text
    normalized_speech_text = str(ai_result.get("normalized_speech_text") or "").strip() or speech_text
    fallback_action_text = str(ai_result.get("fallback_action_text") or "").strip() or normalized_action_text

    raw_issue_codes = ai_result.get("issue_codes")
    issue_codes = (
        [
            str(item or "").strip().lower()
            for item in raw_issue_codes
            if str(item or "").strip().lower() in _VALIDATION_ISSUE_CODES
        ]
        if isinstance(raw_issue_codes, list)
        else []
    )
    issues = _build_structural_issues(issue_codes)
    seen_issue_codes = {issue.code for issue in issues}

    resource_kind = str(ai_result.get("resource_kind") or "none").strip().lower()
    if resource_kind not in {"none", "spell", "war_art", "item"}:
        resource_kind = "none"
    resource_name = str(ai_result.get("resource_name") or "").strip()
    library = load_template_library()
    resource_status, resource_issue_code = _resource_status(profile, library, resource_kind, resource_name)
    if resource_issue_code is not None:
        _append_issue(issues, seen_issue_codes, resource_issue_code, resource_name)

    action_state_issue = _action_state_issue(profile, normalized_action_text)
    if action_state_issue is not None:
        _append_issue(issues, seen_issue_codes, action_state_issue)

    suggested_action_text = normalized_action_text
    if resource_status.check_status == "failed":
        suggested_action_text = fallback_action_text
    if action_state_issue in {"speech_only_required", "actor_dead"}:
        suggested_action_text = ""
    fallback_action_text = suggested_action_text

    status = "accepted" if not issues else "needs_player_confirmation"
    display_action_text = normalized_action_text if status == "accepted" else fallback_action_text
    return PlayerInputValidationResponse(
        session_id=req.session_id,
        entry_point=req.entry_point,
        actor_role_id=actor_role_id,
        actor_name=profile.name,
        actor_kind=actor_kind,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        normalized_action_text=normalized_action_text,
        normalized_speech_text=normalized_speech_text,
        fallback_action_text=fallback_action_text,
        display_text=_compose_display_text(display_action_text, normalized_speech_text),
        summary=_build_summary(status, issues, resource_status),
        issues=issues,
        resource_status=resource_status,
    )
