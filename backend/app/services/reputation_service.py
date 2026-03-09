from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import ReputationState, ReputationStateResponse, SaveFile, SceneEvent, SubZoneReputationEntry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def reputation_band(score: int) -> str:
    value = _clamp(score, 0, 100)
    if value <= 19:
        return "hostile"
    if value <= 39:
        return "cold"
    if value <= 59:
        return "neutral"
    if value <= 79:
        return "trusted"
    return "favored"


def ensure_reputation_state(save: SaveFile) -> ReputationState:
    state = getattr(save, "reputation_state", None)
    if state is None:
        save.reputation_state = ReputationState()
        return save.reputation_state
    for entry in state.entries:
        entry.score = _clamp(entry.score, 0, 100)
        entry.band = reputation_band(entry.score)  # type: ignore[assignment]
    return state


def get_sub_zone_reputation_entry(
    save: SaveFile,
    *,
    sub_zone_id: str | None,
    zone_id: str | None = None,
    create: bool = True,
) -> SubZoneReputationEntry | None:
    if not (sub_zone_id or "").strip():
        return None
    state = ensure_reputation_state(save)
    found = next((item for item in state.entries if item.sub_zone_id == sub_zone_id), None)
    if found is not None:
        if zone_id and not found.zone_id:
            found.zone_id = zone_id
        found.score = _clamp(found.score, 0, 100)
        found.band = reputation_band(found.score)  # type: ignore[assignment]
        return found
    if not create:
        return None
    created = SubZoneReputationEntry(
        sub_zone_id=sub_zone_id,
        zone_id=zone_id,
        score=50,
        band="neutral",
    )
    state.entries.append(created)
    state.updated_at = _utc_now()
    return created


def get_current_sub_zone_reputation(save: SaveFile, *, create: bool = True) -> SubZoneReputationEntry | None:
    return get_sub_zone_reputation_entry(
        save,
        sub_zone_id=save.area_snapshot.current_sub_zone_id,
        zone_id=save.area_snapshot.current_zone_id,
        create=create,
    )


def apply_reputation_relation_bias(score: int, delta: int) -> int:
    value = int(delta)
    if value > 0 and score >= 70:
        return value + 2
    if value < 0 and score <= 30:
        return value - 2
    return value


def apply_sub_zone_reputation_delta(
    save: SaveFile,
    *,
    session_id: str,
    delta: int,
    reason: str,
    sub_zone_id: str | None = None,
    zone_id: str | None = None,
    actor_role_id: str = "",
    actor_name: str = "",
    append_log: bool = True,
    append_scene_event: bool = True,
) -> tuple[SubZoneReputationEntry | None, SceneEvent | None]:
    entry = get_sub_zone_reputation_entry(
        save,
        sub_zone_id=sub_zone_id or save.area_snapshot.current_sub_zone_id,
        zone_id=zone_id or save.area_snapshot.current_zone_id,
        create=True,
    )
    if entry is None:
        return None, None
    state = ensure_reputation_state(save)
    before = entry.score
    applied = _clamp(int(delta), -100, 100)
    entry.score = _clamp(before + applied, 0, 100)
    entry.band = reputation_band(entry.score)  # type: ignore[assignment]
    clean_reason = (reason or "区域行为变化").strip()[:120]
    if clean_reason:
        entry.recent_reasons.append(f"{_utc_now()} {applied:+d} {clean_reason}")
        entry.recent_reasons = entry.recent_reasons[-8:]
    entry.updated_at = _utc_now()
    state.updated_at = entry.updated_at

    scene_event: SceneEvent | None = None
    if append_scene_event:
        scene_event = SceneEvent(
            event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            kind="reputation_update",
            actor_role_id=actor_role_id,
            actor_name=actor_name,
            content=f"当前子区块声望变为 {entry.score}/100（{entry.band}）。{clean_reason}",
            metadata={
                "sub_zone_id": entry.sub_zone_id,
                "score_before": before,
                "score_after": entry.score,
                "delta": applied,
            },
        )

    if append_log:
        from app.services.world_service import _new_game_log

        save.game_logs.append(
            _new_game_log(
                session_id,
                "reputation_update",
                f"子区块声望变动 {applied:+d} -> {entry.score}/100 ({entry.band})",
                {
                    "sub_zone_id": entry.sub_zone_id,
                    "score_before": before,
                    "score_after": entry.score,
                    "delta": applied,
                },
            )
        )
    return entry, scene_event


def get_area_reputation(session_id: str, *, save: SaveFile | None = None, sub_zone_id: str | None = None) -> ReputationStateResponse:
    if save is None:
        from app.services.world_service import get_current_save, save_current

        save = get_current_save(default_session_id=session_id)
        if save.session_id != session_id:
            save.session_id = session_id
            save_current(save)
    ensure_reputation_state(save)
    current_entry = get_sub_zone_reputation_entry(
        save,
        sub_zone_id=sub_zone_id or save.area_snapshot.current_sub_zone_id,
        zone_id=save.area_snapshot.current_zone_id,
        create=not bool(sub_zone_id),
    )
    return ReputationStateResponse(
        session_id=session_id,
        reputation_state=save.reputation_state,
        current_entry=current_entry,
    )
