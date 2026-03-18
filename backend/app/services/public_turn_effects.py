from __future__ import annotations

from typing import Any

from app.models.schemas import (
    ActionCheckResponse,
    EnvironmentRiskLevel,
    PublicTurnImpact,
    SaveFile,
    SceneEvent,
    TeamReaction,
)
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


def team_reaction_rows(reactions: list[TeamReaction]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in reactions:
        rows.append(
            {
                "member_role_id": item.member_role_id,
                "member_name": item.member_name,
                "affinity_delta": item.affinity_delta,
                "trust_delta": item.trust_delta,
                "content": item.content,
            }
        )
    return rows


def apply_player_team_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
) -> tuple[list[TeamReaction], list[SceneEvent]]:
    reactions = team_service.apply_team_reactions_in_save(
        save,
        session_id=session_id,
        trigger_kind="public_turn",
        player_text=player_text,
        summary=summary,
    )
    events: list[SceneEvent] = []
    for reaction in reactions:
        events.append(
            world._new_scene_event(
                "public_turn_team_update",
                f"{reaction.member_name}: {reaction.content}",
                actor_role_id=reaction.member_role_id,
                actor_name=reaction.member_name,
                metadata={
                    "trigger_kind": reaction.trigger_kind,
                    "affinity_delta": reaction.affinity_delta,
                    "trust_delta": reaction.trust_delta,
                },
            )
        )
    return reactions, events


def build_impact(
    *,
    actor_id: str,
    actor_name: str,
    action_summary: str,
    action_result: ActionCheckResponse | None,
    situation_delta: int = 0,
    zone_reputation_delta: int = 0,
    relation_deltas: list[dict[str, Any]] | None = None,
    team_affinity_deltas: list[dict[str, Any]] | None = None,
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
