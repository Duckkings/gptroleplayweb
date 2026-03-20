from __future__ import annotations

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.models.schemas import ChatConfig, NpcRoleCard, SaveFile
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services.ai_protocol_contract_service import AI_PROVIDER_CALL_FAILED, require_ai_config
from app.services import public_scene_runtime_v2 as public_scene_runtime
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world

_HIDDEN_ROLE_STATES = {"hidden", "stealth", "ambush", "lurking", "concealed"}


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


def _should_surface_hidden_actor(role: NpcRoleCard, *, player_text: str, config: ChatConfig | None) -> bool:
    clean_text = str(player_text or "").strip()
    if not clean_text:
        return False
    if actor_name_match(role.name, clean_text):
        return True
    if not has_ai_config(config):
        return False
    config = require_ai_config(config)
    prompt = prompt_table.render(
        "public.turn.hidden_reveal.user",
        (
            "Decide whether a currently hidden NPC should surface into the public turn because of the player's latest action. "
            "Return JSON only with should_surface(boolean). "
            "Be conservative: only return true when the player's action would realistically draw this NPC out right now. "
            "role_name=$role_name; role_state=$role_state; role_personality=$role_personality; role_brief=$role_brief; player_text=$player_text"
        ),
        role_name=role.name,
        role_state=str(role.state or ""),
        role_personality=str(role.personality or "")[:120],
        role_brief=str(role.background or "")[:160],
        player_text=clean_text[:240],
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("public.turn.hidden_reveal.system", "Return JSON only.")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = world._extract_json_content((resp.choices[0].message.content or "").strip() or "{}")
        return bool(parsed.get("should_surface"))
    except Exception:
        return False


def hidden_actor_rows(save: SaveFile, *, player_text: str, config: ChatConfig | None = None) -> list[dict[str, object]]:
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    if not current_sub_zone_id:
        return []
    visible_ids = {role.role_id for role in world._visible_public_roles(save)}
    team_ids = {item.role_id for item in getattr(save.team_state, "members", [])}
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
        if state != "hidden" and not _should_surface_hidden_actor(role, player_text=player_text, config=config):
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
    hidden_rows = hidden_actor_rows(save, player_text=player_text, config=config)
    seen = {str(item.get("actor_id") or "") for item in rows}
    for item in hidden_rows:
        actor_id = str(item.get("actor_id") or "")
        if actor_id and actor_id not in seen:
            rows.append(item)
            seen.add(actor_id)
    return rows


def public_turn_normal_actor_rows(
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
    current_sub_zone_id = save.area_snapshot.current_sub_zone_id
    active_encounter = world._active_encounter_for_current_sub_zone(save)
    idle_limit = int(getattr(getattr(config, "public_scene", None), "idle_actor_limit", 2) or 2)
    active_limit = int(getattr(getattr(config, "public_scene", None), "active_actor_limit", 8) or 8)
    limit = max(active_limit, 6) if active_encounter is not None and active_encounter.status == "active" else max(idle_limit, 4)

    def in_current_sub_zone(row: dict[str, object]) -> bool:
        role = row.get("role")
        if isinstance(role, NpcRoleCard):
            return role.sub_zone_id == current_sub_zone_id
        return False

    direct_rows = [row for row in rows if str(row.get("priority_reason") or "") in {"player_targeted_visible_npc", "incoming_player_interaction", "direct_player_reference"}]
    encounter_rows = [row for row in rows if str(row.get("actor_type") or "") == "encounter_temp_npc" or str(row.get("priority_reason") or "") == "active_encounter_anchor"]
    local_npcs = [row for row in rows if str(row.get("actor_type") or "") == "npc" and in_current_sub_zone(row)]
    team_rows = [row for row in rows if str(row.get("actor_type") or "") == "team"]
    others = [row for row in rows if row not in direct_rows and row not in encounter_rows and row not in local_npcs and row not in team_rows]

    ordered: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    def add(row: dict[str, object]) -> None:
        actor_id = str(row.get("actor_id") or "")
        if not actor_id or actor_id in seen_ids or len(ordered) >= limit:
            return
        seen_ids.add(actor_id)
        ordered.append(row)

    for row in direct_rows:
        add(row)
    if local_npcs:
        add(local_npcs[0])
    for bucket in (encounter_rows, team_rows, local_npcs[1:], others):
        for row in bucket:
            add(row)
    return ordered[:limit]


def actor_name_match(name: str, text: str) -> bool:
    return public_scene_legacy._find_actor_name_match(name, text)
