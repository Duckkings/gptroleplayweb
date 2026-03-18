from __future__ import annotations

from app.models.schemas import ChatConfig, NpcRoleCard, SaveFile
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world

_HIDDEN_ROLE_STATES = {"hidden", "stealth", "ambush", "lurking", "concealed"}
_HOSTILE_TOKENS = ("攻击", "威胁", "阻止", "抢", "强闯", "拔剑", "射击", "法术", "attack", "threat", "force")


def dex_modifier_for_actor(actor: dict[str, object]) -> int:
    role = actor.get("role")
    if isinstance(role, NpcRoleCard):
        return int(role.profile.dnd5e_sheet.current_ability_modifiers.dexterity)
    temp_npc = actor.get("temp_npc")
    if temp_npc is not None:
        return 1
    return 0


def visible_actor_rows(
    save: SaveFile,
    *,
    player_text: str,
    addressed_role_name: str = "",
    incoming_target_candidates: list[str] | None = None,
    config: ChatConfig | None = None,
) -> list[dict[str, object]]:
    return public_scene_runtime.candidate_rows(
        save,
        player_text=player_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=incoming_target_candidates,
        config=config,
    )


def hidden_actor_rows(save: SaveFile, *, player_text: str) -> list[dict[str, object]]:
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    if not current_sub_zone_id:
        return []
    visible_ids = {role.role_id for role in world._visible_public_roles(save)}
    team_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
    hostile = any(token in player_text for token in _HOSTILE_TOKENS)
    rows: list[dict[str, object]] = []
    for role in save.role_pool:
        if role.role_id in visible_ids or role.role_id in team_ids:
            continue
        if role.sub_zone_id != current_sub_zone_id:
            continue
        state = str(role.state or "").strip().lower()
        desire_hidden = any(getattr(desire, "visibility", "hidden") == "hidden" for desire in getattr(role, "desires", []))
        if state not in _HIDDEN_ROLE_STATES and not desire_hidden:
            continue
        if not hostile and state != "hidden":
            continue
        rows.append(
            {
                "actor_id": role.role_id,
                "name": role.name,
                "actor_type": "hidden_npc",
                "priority_reason": "hidden_intervention",
                "role": role,
                "is_hidden": True,
            }
        )
    rows.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("actor_id") or "")))
    return rows[:2]


def initiative_actor_rows(
    save: SaveFile,
    *,
    player_text: str,
    addressed_role_name: str = "",
    incoming_target_candidates: list[str] | None = None,
    config: ChatConfig | None = None,
) -> list[dict[str, object]]:
    rows = visible_actor_rows(
        save,
        player_text=player_text,
        addressed_role_name=addressed_role_name,
        incoming_target_candidates=incoming_target_candidates,
        config=config,
    )
    hidden_rows = hidden_actor_rows(save, player_text=player_text)
    seen = {str(item.get("actor_id") or "") for item in rows}
    for item in hidden_rows:
        actor_id = str(item.get("actor_id") or "")
        if actor_id and actor_id not in seen:
            rows.append(item)
            seen.add(actor_id)
    return rows


def actor_name_match(name: str, text: str) -> bool:
    return public_scene_legacy._find_actor_name_match(name, text)
