from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from app.models.schemas import ChatConfig, SaveFile, SceneEvent, ZoneMetricEntry, ZoneMetricState
from app.services.ai_adapter import build_completion_options, create_sync_client


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


def danger_band(score: int) -> str:
    value = _clamp(score, 0, 100)
    if value <= 33:
        return "low"
    if value <= 66:
        return "medium"
    return "high"


def danger_fill_color(score: int) -> str:
    value = _clamp(score, 0, 100)
    if value <= 33:
        return "#5b8f35"
    if value <= 66:
        return "#b9901f"
    return "#a63a36"


def ensure_zone_metric_state(save: SaveFile) -> ZoneMetricState:
    state = getattr(save, "zone_metric_state", None)
    if state is None:
        save.zone_metric_state = ZoneMetricState()
        return save.zone_metric_state
    for entry in state.entries:
        entry.reputation_score = _clamp(entry.reputation_score, 0, 100)
        entry.danger_score = _clamp(entry.danger_score, 0, 100)
        entry.reputation_band = reputation_band(entry.reputation_score)  # type: ignore[assignment]
        entry.danger_band = danger_band(entry.danger_score)  # type: ignore[assignment]
    return state


def get_zone_metric_entry(
    save: SaveFile,
    *,
    zone_id: str | None,
    zone_name: str | None = None,
    create: bool = False,
    seed_source: str = "system_default",
) -> ZoneMetricEntry | None:
    normalized_zone_id = (zone_id or "").strip()
    if not normalized_zone_id:
        return None
    state = ensure_zone_metric_state(save)
    found = next((item for item in state.entries if item.zone_id == normalized_zone_id), None)
    if found is not None:
        if zone_name and not found.zone_name:
            found.zone_name = zone_name
        found.reputation_score = _clamp(found.reputation_score, 0, 100)
        found.danger_score = _clamp(found.danger_score, 0, 100)
        found.reputation_band = reputation_band(found.reputation_score)  # type: ignore[assignment]
        found.danger_band = danger_band(found.danger_score)  # type: ignore[assignment]
        return found
    if not create:
        return None
    created = ZoneMetricEntry(
        zone_id=normalized_zone_id,
        zone_name=(zone_name or normalized_zone_id).strip() or normalized_zone_id,
        seed_source=("ai_generated" if seed_source == "ai_generated" else "system_default"),
    )
    state.entries.append(created)
    state.updated_at = _utc_now()
    return created


def get_current_zone_metric(save: SaveFile, *, create: bool = False) -> ZoneMetricEntry | None:
    zone_id = save.area_snapshot.current_zone_id
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), zone_id or "")
    return get_zone_metric_entry(save, zone_id=zone_id, zone_name=zone_name, create=create)


def _append_reason(items: list[str], reason: str, delta: int) -> None:
    clean = " ".join(str(reason or "").split()).strip()[:140]
    if not clean:
        return
    items.append(f"{_utc_now()} {delta:+d} {clean}")
    del items[:-8]


def apply_zone_reputation_delta(
    save: SaveFile,
    *,
    session_id: str,
    delta: int,
    reason: str,
    zone_id: str | None = None,
    zone_name: str | None = None,
    actor_role_id: str = "",
    actor_name: str = "",
    append_log: bool = True,
    append_scene_event: bool = True,
) -> tuple[ZoneMetricEntry | None, SceneEvent | None]:
    entry = get_zone_metric_entry(
        save,
        zone_id=zone_id or save.area_snapshot.current_zone_id,
        zone_name=zone_name,
        create=True,
    )
    if entry is None:
        return None, None
    state = ensure_zone_metric_state(save)
    before = entry.reputation_score
    applied = _clamp(delta, -100, 100)
    entry.reputation_score = _clamp(before + applied, 0, 100)
    entry.reputation_band = reputation_band(entry.reputation_score)  # type: ignore[assignment]
    entry.updated_at = _utc_now()
    _append_reason(entry.reputation_reasons, reason, applied)
    state.updated_at = entry.updated_at

    scene_event: SceneEvent | None = None
    if append_scene_event:
        from app.models.schemas import SceneEvent

        scene_event = SceneEvent(
            event_id=f"scene_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            kind="reputation_update",
            actor_role_id=actor_role_id,
            actor_name=actor_name,
            content=f"当前大区块声望变为 {entry.reputation_score}/100（{entry.reputation_band}）。{reason}",
            metadata={
                "scope": "zone",
                "zone_id": entry.zone_id,
                "score_before": before,
                "score_after": entry.reputation_score,
                "delta": applied,
                "danger_score": entry.danger_score,
            },
        )
    if append_log:
        from app.services.world_service import _new_game_log

        save.game_logs.append(
            _new_game_log(
                session_id,
                "zone_reputation_update",
                f"大区块声望变化 {applied:+d} -> {entry.reputation_score}/100 ({entry.reputation_band})",
                {
                    "zone_id": entry.zone_id,
                    "score_before": before,
                    "score_after": entry.reputation_score,
                    "delta": applied,
                },
            )
        )
    return entry, scene_event


def apply_zone_danger_delta(
    save: SaveFile,
    *,
    session_id: str,
    delta: int,
    reason: str,
    zone_id: str | None = None,
    zone_name: str | None = None,
    append_log: bool = True,
) -> ZoneMetricEntry | None:
    entry = get_zone_metric_entry(
        save,
        zone_id=zone_id or save.area_snapshot.current_zone_id,
        zone_name=zone_name,
        create=True,
    )
    if entry is None:
        return None
    state = ensure_zone_metric_state(save)
    before = entry.danger_score
    applied = _clamp(delta, -100, 100)
    entry.danger_score = _clamp(before + applied, 0, 100)
    entry.danger_band = danger_band(entry.danger_score)  # type: ignore[assignment]
    entry.updated_at = _utc_now()
    _append_reason(entry.danger_reasons, reason, applied)
    state.updated_at = entry.updated_at
    if append_log:
        from app.services.world_service import _new_game_log

        save.game_logs.append(
            _new_game_log(
                session_id,
                "zone_danger_update",
                f"大区块危险值变化 {applied:+d} -> {entry.danger_score}/100 ({entry.danger_band})",
                {
                    "zone_id": entry.zone_id,
                    "score_before": before,
                    "score_after": entry.danger_score,
                    "delta": applied,
                },
            )
        )
    return entry


def _zone_payloads(save: SaveFile, *, zone_ids: set[str] | None = None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for zone in save.area_snapshot.zones:
        if zone_ids is not None and zone.zone_id not in zone_ids:
            continue
        sub_zone_rows = [
            {
                "sub_zone_id": item.sub_zone_id,
                "name": item.name,
                "description": item.description,
                "interaction_names": [interaction.name for interaction in item.key_interactions[:4]],
                "npc_names": [npc.name for npc in item.npcs[:4]],
            }
            for item in save.area_snapshot.sub_zones
            if item.zone_id == zone.zone_id
        ]
        payloads.append(
            {
                "zone_id": zone.zone_id,
                "zone_name": zone.name,
                "zone_type": zone.zone_type,
                "size": zone.size,
                "description": zone.description,
                "sub_zones": sub_zone_rows[:8],
            }
        )
    return payloads


def _extract_json(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _ai_generate_zone_metrics(
    *,
    session_id: str,
    zone_payloads: list[dict[str, Any]],
    config: ChatConfig,
    seed_source: str,
) -> dict[str, dict[str, Any]]:
    if not zone_payloads:
        return {}
    client = create_sync_client(config, client_cls=OpenAI)
    prompt = (
        "你是跑团地图设定评估器。只输出 JSON。\n"
        "任务：根据大区块设定、子区块、交互物与 NPC 情况，为每个大区块生成两个 0-100 的数值：\n"
        "1. reputation_score：玩家初始在该大区块的社会 standing。数值越高代表默认更受欢迎。\n"
        "2. danger_score：该大区块整体危险程度。数值越高越容易出现冲突、威胁或高压遭遇。\n"
        "输出 schema: {\"zones\":[{\"zone_id\":\"...\",\"reputation_score\":50,\"danger_score\":50,"
        "\"reputation_reason\":\"...\",\"danger_reason\":\"...\"}]}\n"
        "要求：\n"
        "- reputation_score 和 danger_score 都必须是 0 到 100 的整数。\n"
        "- reputation_reason 与 danger_reason 使用简体中文，各不超过 40 字。\n"
        "- reputation_score 必须体现区块设定对玩家 standing 的初始影响。\n"
        "- danger_score 必须体现该区块的整体风险，不是单次遭遇结果。\n"
        f"- 当前生成来源：{seed_source}。\n"
        "区块数据：\n"
        f"{json.dumps(zone_payloads, ensure_ascii=False)}"
    )
    response = client.chat.completions.create(
        model=config.model,
        **build_completion_options(config),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你只输出 JSON，所有说明使用简体中文。"},
            {"role": "user", "content": prompt},
        ],
    )
    parsed = _extract_json(response.choices[0].message.content or "{}")
    rows = parsed.get("zones")
    if not isinstance(rows, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        zone_id = str(item.get("zone_id") or "").strip()
        if not zone_id:
            continue
        by_id[zone_id] = {
            "reputation_score": _clamp(int(item.get("reputation_score") or 50), 0, 100),
            "danger_score": _clamp(int(item.get("danger_score") or 50), 0, 100),
            "reputation_reason": " ".join(str(item.get("reputation_reason") or "").split()).strip()[:40],
            "danger_reason": " ".join(str(item.get("danger_reason") or "").split()).strip()[:40],
        }
    return by_id


def ensure_zone_metrics_for_zones(
    save: SaveFile,
    *,
    session_id: str,
    zone_ids: set[str],
    config: ChatConfig | None,
    seed_source: str = "ai_generated",
) -> list[ZoneMetricEntry]:
    state = ensure_zone_metric_state(save)
    missing_ids = {
        zone_id
        for zone_id in zone_ids
        if get_zone_metric_entry(save, zone_id=zone_id, create=False) is None
    }
    if missing_ids:
        payloads = _zone_payloads(save, zone_ids=missing_ids)
        generated_rows: dict[str, dict[str, Any]] = {}
        if config is not None and payloads:
            try:
                generated_rows = _ai_generate_zone_metrics(
                    session_id=session_id,
                    zone_payloads=payloads,
                    config=config,
                    seed_source=seed_source,
                )
            except Exception:
                generated_rows = {}
        for payload in payloads:
            zone_id = str(payload["zone_id"])
            row = generated_rows.get(zone_id, {})
            entry = get_zone_metric_entry(
                save,
                zone_id=zone_id,
                zone_name=str(payload.get("zone_name") or zone_id),
                create=True,
                seed_source=(seed_source if row else "system_default"),
            )
            if entry is None:
                continue
            entry.zone_name = str(payload.get("zone_name") or entry.zone_name)
            entry.reputation_score = _clamp(int(row.get("reputation_score") or entry.reputation_score), 0, 100)
            entry.danger_score = _clamp(int(row.get("danger_score") or entry.danger_score), 0, 100)
            entry.reputation_band = reputation_band(entry.reputation_score)  # type: ignore[assignment]
            entry.danger_band = danger_band(entry.danger_score)  # type: ignore[assignment]
            entry.seed_source = (seed_source if row else "system_default")  # type: ignore[assignment]
            if row.get("reputation_reason"):
                _append_reason(entry.reputation_reasons, str(row["reputation_reason"]), 0)
            if row.get("danger_reason"):
                _append_reason(entry.danger_reasons, str(row["danger_reason"]), 0)
            entry.updated_at = _utc_now()
        state.updated_at = _utc_now()
    return [entry for entry in state.entries if entry.zone_id in zone_ids]


def ensure_zone_metric_for_zone(
    save: SaveFile,
    *,
    session_id: str,
    zone_id: str | None,
    config: ChatConfig | None,
    seed_source: str = "ai_generated",
) -> ZoneMetricEntry | None:
    normalized_zone_id = (zone_id or "").strip()
    if not normalized_zone_id:
        return None
    ensure_zone_metrics_for_zones(
        save,
        session_id=session_id,
        zone_ids={normalized_zone_id},
        config=config,
        seed_source=seed_source,
    )
    return get_zone_metric_entry(save, zone_id=normalized_zone_id, create=False)


def backfill_zone_metrics_with_ai(save: SaveFile, *, session_id: str, config: ChatConfig | None) -> ZoneMetricState:
    zone_ids = {zone.zone_id for zone in save.area_snapshot.zones}
    ensure_zone_metrics_for_zones(
        save,
        session_id=session_id,
        zone_ids=zone_ids,
        config=config,
        seed_source="migration_backfill",
    )
    return ensure_zone_metric_state(save)
