from __future__ import annotations

from typing import Any

from app.models.schemas import (
    ActionCheckResponse,
    EnvironmentRiskLevel,
    PublicTurnImpact,
    PublicTurnRelationDelta,
    PublicTurnTeamAffinityDelta,
    SaveFile,
    SceneEvent,
    TeamReaction,
)
from app.services import public_scene_service
from app.services import team_service
from app.services import world_service as world
from app.services import zone_metric_service


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def check_outcome_label(action_result: ActionCheckResponse | None) -> str:
    if action_result is None:
        return "none"
    if action_result.critical == "critical_success":
        return "critical_success"
    if action_result.critical == "critical_failure":
        return "critical_failure"
    return "success" if action_result.success else "failure"


def check_bonus(action_result: ActionCheckResponse | None) -> int:
    if action_result is None:
        return 0
    if action_result.critical == "critical_success":
        return 8
    if action_result.critical == "critical_failure":
        return -8
    return 4 if action_result.success else -4


def relation_delta_from_result(action_result: ActionCheckResponse | None, situation_delta: int) -> int:
    if action_result is None:
        if situation_delta > 2:
            return 1
        if situation_delta < -2:
            return -1
        return 0
    if action_result.critical == "critical_success":
        return 2
    if action_result.critical == "critical_failure":
        return -2
    return 1 if action_result.success else -1


def reputation_delta_from_situation(situation_delta: int) -> int:
    if situation_delta >= 4:
        return 1
    if situation_delta <= -4:
        return -1
    return 0


def _player_relation_tag(role, player_id: str) -> str:
    relation = next((item for item in role.relations if item.target_role_id == player_id), None)
    return relation.relation_tag if relation is not None else "neutral"


def apply_player_team_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
) -> tuple[list[PublicTurnTeamAffinityDelta], list[SceneEvent]]:
    before_rows = {
        item.role_id: (int(item.affinity), int(item.trust))
        for item in getattr(save.team_state, "members", [])
    }
    reactions = team_service.apply_team_reactions_in_save(
        save,
        session_id=session_id,
        trigger_kind="public_turn",
        player_text=player_text,
        summary=summary,
    )
    rows: list[PublicTurnTeamAffinityDelta] = []
    events: list[SceneEvent] = []
    for reaction in reactions:
        member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == reaction.member_role_id), None)
        affinity_before, trust_before = before_rows.get(reaction.member_role_id, (0, 0))
        affinity_after = int(getattr(member, "affinity", affinity_before))
        trust_after = int(getattr(member, "trust", trust_before))
        row = PublicTurnTeamAffinityDelta(
            member_role_id=reaction.member_role_id,
            name=reaction.member_name,
            affinity_before=affinity_before,
            affinity_after=affinity_after,
            affinity_delta=affinity_after - affinity_before,
            trust_before=trust_before,
            trust_after=trust_after,
            trust_delta=trust_after - trust_before,
            reaction_text=reaction.content,
        )
        rows.append(row)
        events.append(
            world._new_scene_event(
                "public_turn_team_update",
                f"{reaction.member_name}: {reaction.content}",
                actor_role_id=reaction.member_role_id,
                actor_name=reaction.member_name,
                metadata={
                    "trigger_kind": reaction.trigger_kind,
                    "member_role_id": reaction.member_role_id,
                    "name": reaction.member_name,
                    "affinity_before": affinity_before,
                    "affinity_after": affinity_after,
                    "affinity_delta": affinity_after - affinity_before,
                    "trust_before": trust_before,
                    "trust_after": trust_after,
                    "trust_delta": trust_after - trust_before,
                    "reaction_text": reaction.content,
                },
            )
        )
    return rows, events


def apply_player_npc_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
    relation_delta: int,
    target_role_id: str | None = None,
    max_extra_roles: int = 2,
) -> tuple[list[PublicTurnRelationDelta], list[SceneEvent]]:
    del session_id
    visible_roles = world._visible_public_roles(save)
    if not visible_roles:
        return [], []
    targeted = next((role for role in visible_roles if target_role_id and role.role_id == target_role_id), None)
    ordered: list[Any] = []
    if targeted is not None:
        ordered.append(targeted)
    for role in visible_roles:
        if targeted is not None and role.role_id == targeted.role_id:
            continue
        if len(ordered) >= 1 + max(0, max_extra_roles):
            break
        ordered.append(role)
    zone_metric = zone_metric_service.get_current_zone_metric(save, create=True)
    reputation_score = getattr(zone_metric, "reputation_score", 50)
    rows: list[PublicTurnRelationDelta] = []
    events: list[SceneEvent] = []
    for index, role in enumerate(ordered):
        before_tag = _player_relation_tag(role, save.player_static_data.player_id)
        line, _ = world._public_npc_reaction(role, player_text, summary)
        delta_to_apply = relation_delta
        if index > 0 and relation_delta != 0:
            delta_to_apply = 1 if relation_delta > 0 else -1
        applied = 0
        if delta_to_apply != 0:
            applied = public_scene_service._apply_actor_relation_delta(
                save,
                role,
                "npc",
                delta_to_apply,
                reputation_score,
            )
        after_tag = _player_relation_tag(role, save.player_static_data.player_id)
        row = PublicTurnRelationDelta(
            role_id=role.role_id,
            name=role.name,
            before_tag=before_tag,
            after_tag=after_tag,
            relation_delta=applied,
            reaction_text=line,
        )
        rows.append(row)
        events.append(
            world._new_scene_event(
                "public_turn_relation_update",
                f"{role.name}: {line}",
                actor_role_id=role.role_id,
                actor_name=role.name,
                metadata={
                    "role_id": role.role_id,
                    "name": role.name,
                    "before_tag": before_tag,
                    "after_tag": after_tag,
                    "relation_delta": applied,
                    "reaction_text": line,
                },
            )
        )
    return rows, events


def build_impact(
    *,
    actor_id: str,
    actor_name: str,
    action_summary: str,
    action_result: ActionCheckResponse | None,
    situation_delta: int = 0,
    zone_reputation_delta: int = 0,
    relation_deltas: list[PublicTurnRelationDelta] | None = None,
    team_affinity_deltas: list[PublicTurnTeamAffinityDelta] | None = None,
    hp_changes: list[dict[str, Any]] | None = None,
    environment_shift: int = 0,
    scene_events: list[SceneEvent] | None = None,
) -> PublicTurnImpact:
    return PublicTurnImpact(
        actor_id=actor_id,
        actor_name=actor_name,
        action_summary=action_summary[:200],
        check_outcome=check_outcome_label(action_result),  # type: ignore[arg-type]
        situation_delta=situation_delta,
        zone_reputation_delta=zone_reputation_delta,
        relation_deltas=relation_deltas or [],
        team_affinity_deltas=team_affinity_deltas or [],
        hp_changes=hp_changes or [],
        environment_shift=environment_shift,
        scene_event_ids=[event.event_id for event in scene_events or []],
    )


def next_environment_risk(
    current: EnvironmentRiskLevel,
    *,
    total_environment_shift: int,
    destructive_failure: bool = False,
) -> EnvironmentRiskLevel:
    if destructive_failure or total_environment_shift >= 8:
        return EnvironmentRiskLevel.COLLAPSE
    if current == EnvironmentRiskLevel.COLLAPSE:
        return current
    if current == EnvironmentRiskLevel.RISKY and total_environment_shift > 0:
        return EnvironmentRiskLevel.RISKY
    if total_environment_shift >= 4:
        return EnvironmentRiskLevel.RISKY
    return current


def apply_round_reputation(
    save: SaveFile,
    *,
    session_id: str,
    delta: int,
    reason: str,
    actor_name: str,
) -> tuple[object | None, SceneEvent | None]:
    return zone_metric_service.apply_zone_reputation_delta(
        save,
        session_id=session_id,
        delta=clamp(delta, -6, 6),
        reason=reason,
        actor_name=actor_name,
        append_scene_event=bool(delta),
        append_log=bool(delta),
    )
