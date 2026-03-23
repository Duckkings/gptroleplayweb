from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import (
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResponse,
    InventoryItem,
    ItemInstance,
    SaveFile,
    SceneEvent,
    SceneInteractable,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.item_instance_service import (
    create_item_instance,
    ensure_item_system,
    get_owner_instance,
    remove_item_instance,
    resolve_owner_instances,
    set_instance_owner,
)
from app.services.item_template_service import ensure_definition_for_inventory_item, load_template_library


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_scene_interactables(save: SaveFile, *, sub_zone_id: str | None = None) -> list[SceneInteractable]:
    ensure_item_system(save)
    target_sub_zone_id = (sub_zone_id or save.area_snapshot.current_sub_zone_id or "").strip()
    items = [item for item in save.scene_interactable_state.items if not target_sub_zone_id or item.sub_zone_id == target_sub_zone_id]
    return [item.model_copy(deep=True) for item in items if item.status != "hidden"]


def _find_interactable(save: SaveFile, interaction_id: str) -> SceneInteractable:
    ensure_item_system(save)
    found = next((item for item in save.scene_interactable_state.items if item.interactable_id == interaction_id), None)
    if found is None:
        raise KeyError("AREA_INVALID_INTERACTION")
    return found


def _resolve_actor(save: SaveFile, req: AreaExecuteInteractionRequest) -> tuple[str, str, str]:
    if req.actor_kind == "role":
        role_id = (req.actor_role_id or "").strip()
        role = next((item for item in save.role_pool if item.role_id == role_id), None)
        if role is None:
            raise KeyError("ROLE_NOT_FOUND")
        if role.sub_zone_id != save.area_snapshot.current_sub_zone_id:
            raise ValueError("ACTOR_NOT_IN_CURRENT_SUB_ZONE")
        return "role", role.role_id, role.name
    return "player", save.player_static_data.player_id, save.player_static_data.name


def _find_template(interactable: SceneInteractable):
    library = load_template_library()
    return next((item for item in library.interactable_templates if item.template_id == interactable.template_id), None)


def _new_scene_event(kind: str, content: str, *, actor_role_id: str = "", actor_name: str = "", metadata: dict[str, Any] | None = None) -> SceneEvent:
    return SceneEvent(
        event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        kind=kind,  # type: ignore[arg-type]
        actor_role_id=actor_role_id,
        actor_name=actor_name,
        content=content,
        metadata=metadata or {},
    )


def _allowed_action(interactable: SceneInteractable, action_kind: str) -> bool:
    if not interactable.allowed_actions:
        return action_kind == "inspect"
    return action_kind in interactable.allowed_actions


def _fallback_reply(actor_name: str, action_kind: str, interactable: SceneInteractable) -> str:
    if action_kind == "inspect":
        return f"{actor_name}仔细观察【{interactable.name}】。{interactable.description or '暂时没有更多细节，但它显然值得留意。'}"
    if action_kind == "pickup":
        return f"{actor_name}将【{interactable.name}】收进了背包。"
    if action_kind in {"open", "search"}:
        return f"{actor_name}对【{interactable.name}】进行了检查。"
    if action_kind in {"trigger", "disable", "reset"}:
        return f"{actor_name}对【{interactable.name}】采取了动作，现场状态随之变化。"
    if action_kind in {"enter", "force_open"}:
        return f"{actor_name}尝试通过【{interactable.name}】。"
    return f"{actor_name}对【{interactable.name}】执行了 {action_kind}。"


def _ai_interaction_resolution(
    req: AreaExecuteInteractionRequest,
    *,
    actor_name: str,
    interactable: SceneInteractable,
    template,
) -> dict[str, Any] | None:
    if req.config is None:
        return None
    api_key = (req.config.openai_api_key or "").strip()
    model = (req.config.model or "").strip()
    if not api_key or not model:
        return None
    client = create_sync_client(req.config, client_cls=OpenAI)
    system_prompt = prompt_table.get_text(
        "scene.interaction.system",
        "Return one JSON object only. Keep narration concise Chinese. Never invent illegal state changes.",
    )
    user_prompt = prompt_table.render(
        "scene.interaction.user",
        (
            "输出 JSON 对象，字段固定为 "
            '{"action_kind":"","narration":"","state_updates":{"state_tags":[],"status_after":""},"spawn_items":[],"destroy_item_instance_ids":[],"transfer_item_instance_ids":[],"status_after":"","clue_payload":{}}。'
            "操作者：$actor_name。交互物：$name。种类：$interactable_kind。描述：$description。"
            "允许动作：$allowed_actions。执行动作：$action_kind。玩家补充：$prompt。"
            "只有在首次打开容器需要掉落时才返回 spawn_items，格式为 [{\"definition_id\":\"\",\"quantity\":1,\"display_name\":\"\"}]。"
        ),
        actor_name=actor_name,
        name=interactable.name,
        interactable_kind=interactable.interactable_kind,
        description=interactable.description or "-",
        allowed_actions="|".join(interactable.allowed_actions),
        action_kind=req.action_kind,
        prompt=req.prompt or "-",
    )
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        **build_completion_options(req.config),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _validate_spawn_items(interactable: SceneInteractable, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    library = load_template_library()
    allowed_ids = set()
    template = _find_template(interactable)
    if template is not None:
        allowed_ids.update(template.allowed_definition_ids)
    valid_item_ids = {item.definition_id for item in library.item_definitions} | {item.definition_id for item in library.equipment_definitions}
    validated: list[dict[str, Any]] = []
    for row in rows:
        definition_id = str(row.get("definition_id") or "").strip()
        if not definition_id or definition_id not in valid_item_ids:
            continue
        if allowed_ids and definition_id not in allowed_ids:
            continue
        quantity = max(1, int(row.get("quantity") or 1))
        validated.append(
            {
                "definition_id": definition_id,
                "quantity": quantity,
                "display_name": str(row.get("display_name") or "").strip(),
            }
        )
    return validated


def _generate_container_loot(
    save: SaveFile,
    interactable: SceneInteractable,
    *,
    actor_name: str,
    req: AreaExecuteInteractionRequest,
) -> list[ItemInstance]:
    if interactable.loot_generation_status == "generated":
        return [
            item
            for item in save.item_instance_state.items
            if item.item_instance_id in interactable.contained_item_instance_ids and item.quantity > 0
        ]
    ai_payload = _ai_interaction_resolution(req, actor_name=actor_name, interactable=interactable, template=_find_template(interactable)) or {}
    spawn_rows = _validate_spawn_items(interactable, list(ai_payload.get("spawn_items") or []))
    if not spawn_rows:
        spawn_rows = [{"definition_id": "healing_potion", "quantity": 1, "display_name": "治疗药水"}]
    created: list[ItemInstance] = []
    for row in spawn_rows:
        instance = create_item_instance(
            save,
            definition_id=row["definition_id"],
            owner_kind="container",
            owner_id=interactable.interactable_id,
            quantity=int(row["quantity"]),
            display_name=str(row.get("display_name") or ""),
            zone_id=interactable.zone_id,
            sub_zone_id=interactable.sub_zone_id,
        )
        created.append(instance)
    interactable.contained_item_instance_ids = [item.item_instance_id for item in created]
    interactable.loot_generation_status = "generated"
    interactable.first_generated_at = _utc_now()
    interactable.updated_at = interactable.first_generated_at
    save.scene_interactable_state.updated_at = interactable.updated_at
    return created


def _create_scene_item_proxy(save: SaveFile, instance: ItemInstance, *, sub_zone_id: str, zone_id: str) -> SceneInteractable:
    interactable = SceneInteractable(
        interactable_id=f"int_{instance.item_instance_id}",
        template_id="item_proxy",
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        name=instance.display_name or instance.definition_id,
        interactable_kind="item_proxy",
        description=instance.description_override,
        allowed_actions=["inspect", "pickup"],
        state_tags=["visible"],
        status="ready",
        generated_mode="instant",
        item_instance_id=instance.item_instance_id,
        updated_at=_utc_now(),
    )
    save.scene_interactable_state.items.append(interactable)
    save.scene_interactable_state.updated_at = interactable.updated_at
    return interactable


def _ensure_item_proxy_instance(save: SaveFile, interactable: SceneInteractable) -> ItemInstance:
    if interactable.item_instance_id:
        existing = next((item for item in save.item_instance_state.items if item.item_instance_id == interactable.item_instance_id), None)
        if existing is not None:
            return existing
    definition_id = ensure_definition_for_inventory_item(
        InventoryItem(
            item_id=interactable.interactable_id,
            name=interactable.name,
            item_type="misc",
            description=interactable.description,
            quantity=1,
        )
    )
    instance = create_item_instance(
        save,
        definition_id=definition_id,
        owner_kind="scene",
        owner_id=interactable.sub_zone_id,
        quantity=1,
        display_name=interactable.name,
        description_override=interactable.description,
        zone_id=interactable.zone_id,
        sub_zone_id=interactable.sub_zone_id,
    )
    interactable.item_instance_id = instance.item_instance_id
    interactable.updated_at = _utc_now()
    save.scene_interactable_state.updated_at = interactable.updated_at
    return instance


def execute_scene_interaction_in_save(save: SaveFile, req: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResponse:
    ensure_item_system(save)
    interactable = _find_interactable(save, req.interaction_id)
    actor_owner_kind, actor_owner_id, actor_name = _resolve_actor(save, req)
    if interactable.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        raise ValueError("INTERACTION_NOT_IN_CURRENT_SUB_ZONE")
    if not _allowed_action(interactable, req.action_kind):
        fallback = _fallback_reply(actor_name, "inspect", interactable)
        return AreaExecuteInteractionResponse(ok=True, status="fallback", message=fallback, reply=fallback)

    reply = _fallback_reply(actor_name, req.action_kind, interactable)
    scene_events: list[SceneEvent] = []
    inventory_changes: list[dict[str, Any]] = []
    interactable_updates: list[dict[str, Any]] = []

    ai_payload = _ai_interaction_resolution(req, actor_name=actor_name, interactable=interactable, template=_find_template(interactable)) or {}
    ai_narration = str(ai_payload.get("narration") or "").strip()
    if ai_narration:
        reply = ai_narration

    if req.action_kind == "inspect":
        if "status_after" in ai_payload:
            interactable.status = str(ai_payload.get("status_after") or interactable.status)  # type: ignore[assignment]
            interactable.updated_at = _utc_now()
    elif req.action_kind in {"open", "search"} and interactable.interactable_kind == "container":
        created_items = _generate_container_loot(save, interactable, actor_name=actor_name, req=req)
        if created_items:
            reply = ai_narration or f"{actor_name}在【{interactable.name}】里发现了：{'、'.join((item.display_name or item.definition_id) for item in created_items)}。"
            inventory_changes.extend(
                {
                    "change_kind": "container_contents",
                    "item_instance_id": item.item_instance_id,
                    "definition_id": item.definition_id,
                    "quantity": item.quantity,
                }
                for item in created_items
            )
        if "open" not in interactable.state_tags:
            interactable.state_tags = [tag for tag in interactable.state_tags if tag != "closed"] + ["open"]
        interactable.updated_at = _utc_now()
        save.scene_interactable_state.updated_at = interactable.updated_at
    elif req.action_kind == "take_all" and interactable.interactable_kind == "container":
        for instance_id in list(interactable.contained_item_instance_ids):
            item = next((entry for entry in save.item_instance_state.items if entry.item_instance_id == instance_id and entry.quantity > 0), None)
            if item is None:
                continue
            set_instance_owner(
                save,
                item_instance_id=item.item_instance_id,
                owner_kind=actor_owner_kind,
                owner_id=actor_owner_id,
            )
            inventory_changes.append(
                {
                    "change_kind": "pickup",
                    "item_instance_id": item.item_instance_id,
                    "definition_id": item.definition_id,
                    "quantity": item.quantity,
                }
            )
        interactable.contained_item_instance_ids = []
        interactable.updated_at = _utc_now()
        save.scene_interactable_state.updated_at = interactable.updated_at
        reply = ai_narration or f"{actor_name}把【{interactable.name}】里的东西都收了起来。"
    elif req.action_kind == "put_in" and interactable.interactable_kind == "container":
        if not req.item_instance_id:
            raise ValueError("ITEM_INSTANCE_ID_REQUIRED")
        item = get_owner_instance(save, owner_kind=actor_owner_kind, owner_id=actor_owner_id, item_instance_id=req.item_instance_id)
        set_instance_owner(
            save,
            item_instance_id=item.item_instance_id,
            owner_kind="container",
            owner_id=interactable.interactable_id,
            zone_id=interactable.zone_id,
            sub_zone_id=interactable.sub_zone_id,
        )
        if item.item_instance_id not in interactable.contained_item_instance_ids:
            interactable.contained_item_instance_ids.append(item.item_instance_id)
        interactable.updated_at = _utc_now()
        save.scene_interactable_state.updated_at = interactable.updated_at
        inventory_changes.append({"change_kind": "put_in", "item_instance_id": item.item_instance_id})
        reply = ai_narration or f"{actor_name}把物品放进了【{interactable.name}】。"
    elif req.action_kind == "pickup" and interactable.interactable_kind == "item_proxy":
        item = _ensure_item_proxy_instance(save, interactable)
        set_instance_owner(
            save,
            item_instance_id=item.item_instance_id,
            owner_kind=actor_owner_kind,
            owner_id=actor_owner_id,
        )
        interactable.status = "hidden"
        interactable.updated_at = _utc_now()
        save.scene_interactable_state.updated_at = interactable.updated_at
        inventory_changes.append({"change_kind": "pickup", "item_instance_id": item.item_instance_id, "quantity": item.quantity})
        reply = ai_narration or f"{actor_name}拾起了【{interactable.name}】。"
    elif req.action_kind == "drop":
        if not req.item_instance_id:
            raise ValueError("ITEM_INSTANCE_ID_REQUIRED")
        item = get_owner_instance(save, owner_kind=actor_owner_kind, owner_id=actor_owner_id, item_instance_id=req.item_instance_id)
        set_instance_owner(
            save,
            item_instance_id=item.item_instance_id,
            owner_kind="scene",
            owner_id=save.area_snapshot.current_sub_zone_id or interactable.sub_zone_id,
            zone_id=save.area_snapshot.current_zone_id,
            sub_zone_id=save.area_snapshot.current_sub_zone_id,
        )
        _create_scene_item_proxy(
            save,
            item,
            sub_zone_id=save.area_snapshot.current_sub_zone_id or interactable.sub_zone_id,
            zone_id=save.area_snapshot.current_zone_id or interactable.zone_id,
        )
        inventory_changes.append({"change_kind": "drop", "item_instance_id": item.item_instance_id})
        reply = ai_narration or f"{actor_name}把物品放在了地上。"
    elif req.action_kind == "give":
        if not req.item_instance_id:
            raise ValueError("ITEM_INSTANCE_ID_REQUIRED")
        target_role_id = (req.prompt or "").strip()
        if not target_role_id:
            raise ValueError("TARGET_ROLE_REQUIRED")
        role = next((entry for entry in save.role_pool if entry.role_id == target_role_id or entry.name == target_role_id), None)
        if role is None:
            raise KeyError("ROLE_NOT_FOUND")
        item = get_owner_instance(save, owner_kind=actor_owner_kind, owner_id=actor_owner_id, item_instance_id=req.item_instance_id)
        set_instance_owner(save, item_instance_id=item.item_instance_id, owner_kind="role", owner_id=role.role_id)
        inventory_changes.append({"change_kind": "give", "item_instance_id": item.item_instance_id, "target_role_id": role.role_id})
        reply = ai_narration or f"{actor_name}把物品交给了{role.name}。"
    elif req.action_kind == "equip":
        if not req.item_instance_id:
            raise ValueError("ITEM_INSTANCE_ID_REQUIRED")
        if actor_owner_kind == "role":
            role = next((entry for entry in save.role_pool if entry.role_id == actor_owner_id), None)
            if role is None:
                raise KeyError("ROLE_NOT_FOUND")
            sheet = role.profile.dnd5e_sheet
        else:
            sheet = save.player_static_data.dnd5e_sheet
        item = get_owner_instance(save, owner_kind=actor_owner_kind, owner_id=actor_owner_id, item_instance_id=req.item_instance_id)
        library = load_template_library()
        equipment = next((entry for entry in library.equipment_definitions if entry.definition_id == item.definition_id), None)
        if equipment is None:
            raise ValueError("ITEM_NOT_EQUIPPABLE")
        if equipment.slot_type == "weapon":
            sheet.equipment_slots.weapon_item_instance_id = item.item_instance_id
        elif equipment.slot_type == "armor":
            sheet.equipment_slots.armor_item_instance_id = item.item_instance_id
        elif equipment.slot_type == "shield":
            sheet.equipment_slots.shield_item_instance_id = item.item_instance_id
        reply = ai_narration or f"{actor_name}装备了【{item.display_name or equipment.name}】。"
        inventory_changes.append({"change_kind": "equip", "item_instance_id": item.item_instance_id, "slot_type": equipment.slot_type})
    elif req.action_kind == "use":
        if not req.item_instance_id:
            raise ValueError("ITEM_INSTANCE_ID_REQUIRED")
        item = get_owner_instance(save, owner_kind=actor_owner_kind, owner_id=actor_owner_id, item_instance_id=req.item_instance_id)
        if item.uses_left is not None:
            item.uses_left = max(0, item.uses_left - 1)
            item.updated_at = _utc_now()
            if item.uses_left == 0 and item.quantity <= 1:
                remove_item_instance(save, item.item_instance_id)
        elif item.quantity > 0:
            item.quantity = max(0, item.quantity - 1)
            item.updated_at = _utc_now()
            if item.quantity == 0:
                remove_item_instance(save, item.item_instance_id)
        reply = ai_narration or f"{actor_name}使用了物品。"
        inventory_changes.append({"change_kind": "use", "item_instance_id": req.item_instance_id})
    else:
        status_after = str(ai_payload.get("status_after") or "").strip()
        if status_after:
            interactable.status = status_after  # type: ignore[assignment]
        state_updates = ai_payload.get("state_updates") if isinstance(ai_payload.get("state_updates"), dict) else {}
        if isinstance(state_updates.get("state_tags"), list):
            interactable.state_tags = [str(item).strip() for item in state_updates.get("state_tags") if str(item).strip()]
        if req.action_kind in {"open", "enter", "force_open"}:
            interactable.state_tags = [tag for tag in interactable.state_tags if tag != "closed"] + ["open"]
        elif req.action_kind == "close":
            interactable.state_tags = [tag for tag in interactable.state_tags if tag != "open"] + ["closed"]
        elif req.action_kind == "lock":
            if "locked" not in interactable.state_tags:
                interactable.state_tags.append("locked")
        elif req.action_kind == "unlock":
            interactable.state_tags = [tag for tag in interactable.state_tags if tag != "locked"]
        elif req.action_kind == "disable":
            interactable.status = "disabled"
        interactable.updated_at = _utc_now()
        save.scene_interactable_state.updated_at = interactable.updated_at
        reply = ai_narration or reply

    ensure_item_system(save)
    if save.area_snapshot.clock is not None:
        from app.services.world_service import _advance_clock

        save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, 1)
    from app.services.world_service import _new_game_log

    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "scene_interaction",
            reply,
            {
                "interaction_id": interactable.interactable_id,
                "action_kind": req.action_kind,
                "actor_kind": actor_owner_kind,
                "actor_id": actor_owner_id,
            },
        )
    )
    scene_events.append(
        _new_scene_event(
            "system_notice",
            reply,
            actor_role_id=(actor_owner_id if actor_owner_kind == "role" else ""),
            actor_name=actor_name,
            metadata={"interaction_id": interactable.interactable_id, "action_kind": req.action_kind},
        )
    )
    interactable_updates.append(
        {
            "interactable_id": interactable.interactable_id,
            "status": interactable.status,
            "state_tags": list(interactable.state_tags),
            "contained_item_instance_ids": list(interactable.contained_item_instance_ids),
        }
    )
    return AreaExecuteInteractionResponse(
        ok=True,
        status="ok",
        message=reply,
        reply=reply,
        scene_events=scene_events,
        inventory_changes=inventory_changes,
        interactable_updates=interactable_updates,
    )
