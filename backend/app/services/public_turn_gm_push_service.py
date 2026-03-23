from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.models.schemas import (
    ChatConfig,
    EnvironmentRiskLevel,
    NpcRoleCard,
    PublicTurnGmPushResult,
    PublicTurnImpact,
    PublicTurnRound,
    SaveFile,
    SceneEvent,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config
from app.services import public_scene_service as public_scene_legacy
from app.services import world_service as world
from app.services.encounter_service import apply_active_encounter_situation_delta_in_save
from app.services.public_turn_effects import apply_round_reputation, next_environment_risk


@dataclass
class PublicTurnGmPushOutcome:
    narration: str
    scene_events: list[SceneEvent]
    risk: EnvironmentRiskLevel
    result: PublicTurnGmPushResult
    spawned_role: NpcRoleCard | None = None


def _advance_risk_once(risk: EnvironmentRiskLevel) -> EnvironmentRiskLevel:
    if risk == EnvironmentRiskLevel.STABLE:
        return EnvironmentRiskLevel.RISKY
    if risk == EnvironmentRiskLevel.RISKY:
        return EnvironmentRiskLevel.COLLAPSE
    return EnvironmentRiskLevel.COLLAPSE


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def _gm_push_ai_payload(
    save: SaveFile,
    *,
    round_state: PublicTurnRound,
    impacts: list[PublicTurnImpact],
    total_situation_delta: int,
    total_environment_shift: int,
    outcome_kind: str,
    config: ChatConfig | None,
) -> dict[str, Any]:
    fallback: dict[str, Any] = {"gm_environment_text": "", "environment_change_text": "", "spawn_npc": {}}
    if not has_ai_config(config):
        return fallback
    assert config is not None
    impact_rows = [
        {
            "actor_name": item.actor_name,
            "action_summary": item.action_summary,
            "situation_delta": item.situation_delta,
            "environment_shift": item.environment_shift,
        }
        for item in impacts
    ]
    prompt = (
        "You are generating the end-of-round GM push for a tabletop public turn. "
        "Return JSON only with keys gm_environment_text, environment_change_text, spawn_npc. "
        "gm_environment_text: describe environment/atmosphere only, not NPC direct actions. "
        "environment_change_text: only fill when outcome_kind is environment_change. "
        "spawn_npc: only fill when outcome_kind is extra_npc_intervention, keys may include "
        "name,title,description,speaking_style,agenda,appearance,alignment,likes. "
        "If you do not want to provide a field, return an empty string or empty object. "
        f"round_number={round_state.round_number}; outcome_kind={outcome_kind}; "
        f"total_situation_delta={total_situation_delta}; total_environment_shift={total_environment_shift}; "
        f"impacts_json={json.dumps(impact_rows, ensure_ascii=False)}"
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": str(config.gm_prompt or "")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        if not isinstance(parsed, dict):
            return fallback
        return {
            "gm_environment_text": _clean(str(parsed.get("gm_environment_text") or ""))[:280],
            "environment_change_text": _clean(str(parsed.get("environment_change_text") or ""))[:220],
            "spawn_npc": parsed.get("spawn_npc") if isinstance(parsed.get("spawn_npc"), dict) else {},
        }
    except Exception:
        return fallback


def resolve_public_turn_gm_push(
    save: SaveFile,
    *,
    session_id: str,
    round_state: PublicTurnRound,
    impacts: list[PublicTurnImpact],
    config: ChatConfig | None,
) -> PublicTurnGmPushOutcome:
    total_environment_shift = sum(int(item.environment_shift or 0) for item in impacts)
    total_situation_delta = sum(int(item.situation_delta or 0) for item in impacts)
    total_reputation_delta = sum(int(item.zone_reputation_delta or 0) for item in impacts)
    destructive_failure = total_environment_shift > 0 and total_situation_delta < 0
    risk = next_environment_risk(
        round_state.environment_risk_level,
        total_environment_shift=total_environment_shift,
        destructive_failure=destructive_failure,
    )
    roll_d6 = random.randint(1, 6)
    outcome_kind = "none"
    outcome_label = "No additional push"
    if roll_d6 == 5:
        outcome_kind = "environment_change"
        outcome_label = "Environment shifts"
        risk = _advance_risk_once(risk)
    elif roll_d6 == 6:
        outcome_kind = "extra_npc_intervention"
        outcome_label = "An extra NPC intervenes"

    ai_payload = _gm_push_ai_payload(
        save,
        round_state=round_state,
        impacts=impacts,
        total_situation_delta=total_situation_delta,
        total_environment_shift=total_environment_shift,
        outcome_kind=outcome_kind,
        config=config,
    )
    gm_environment_text = _clean(str(ai_payload.get("gm_environment_text") or ""))
    environment_change_text = _clean(str(ai_payload.get("environment_change_text") or ""))

    events = [
        world._new_scene_event(
            "public_turn_situation",
            gm_environment_text or outcome_label,
            actor_name="GM",
            metadata={
                "round_id": round_state.round_id,
                "situation_delta_total": total_situation_delta,
                "environment_risk_level": risk.value,
                "roll_d6": roll_d6,
                "outcome_kind": outcome_kind,
            },
        )
    ]
    active_encounter = public_scene_legacy._active_encounter_for_current_sub_zone(save)
    if active_encounter is not None and total_situation_delta:
        events.extend(
            apply_active_encounter_situation_delta_in_save(
                save,
                session_id=session_id,
                delta=total_situation_delta,
                summary=gm_environment_text or outcome_label,
                actor_name="public_turn",
            )
        )
    _, reputation_event = apply_round_reputation(
        save,
        session_id=session_id,
        delta=total_reputation_delta,
        reason="public_turn_round",
        actor_name="public_turn",
    )
    if reputation_event is not None:
        events.append(reputation_event)
    if risk != round_state.environment_risk_level or total_environment_shift or outcome_kind == "environment_change":
        events.append(
            world._new_scene_event(
                "public_turn_environment_update",
                environment_change_text or f"Environment risk changes from {round_state.environment_risk_level.value} to {risk.value}.",
                actor_name="GM",
                metadata={
                    "round_id": round_state.round_id,
                    "environment_shift": total_environment_shift,
                    "environment_risk_level_before": round_state.environment_risk_level.value,
                    "environment_risk_level_after": risk.value,
                    "roll_d6": roll_d6,
                    "outcome_kind": outcome_kind,
                },
            )
        )

    spawned_role: NpcRoleCard | None = None
    spawned_name: str | None = None
    spawn_seed = ai_payload.get("spawn_npc") if isinstance(ai_payload.get("spawn_npc"), dict) else {}
    if outcome_kind == "extra_npc_intervention":
        spawned_role = world.spawn_persistent_scene_npc_in_save(
            save,
            name=str(spawn_seed.get("name") or "Intervening Stranger"),
            title=str(spawn_seed.get("title") or ""),
            description=str(spawn_seed.get("description") or ""),
            speaking_style=str(spawn_seed.get("speaking_style") or ""),
            agenda=str(spawn_seed.get("agenda") or ""),
            appearance=str(spawn_seed.get("appearance") or ""),
            alignment=str(spawn_seed.get("alignment") or ""),
            likes=[str(item) for item in list(spawn_seed.get("likes") or [])],
        )
        spawned_name = spawned_role.name
        events.append(
            world._new_scene_event(
                "public_turn_gm_push",
                f"{spawned_name} enters the scene.",
                actor_name="GM",
                metadata={
                    "round_id": round_state.round_id,
                    "round_number": round_state.round_number,
                    "roll_d6": roll_d6,
                    "outcome_kind": outcome_kind,
                    "spawned_npc_role_id": spawned_role.role_id,
                    "spawned_npc_name": spawned_name,
                },
            )
        )

    result = PublicTurnGmPushResult(
        roll_d6=roll_d6,
        outcome_kind=outcome_kind,  # type: ignore[arg-type]
        outcome_label=outcome_label,
        gm_environment_text=gm_environment_text,
        environment_change_text=environment_change_text,
        spawned_npc_role_id=(spawned_role.role_id if spawned_role is not None else None),
        spawned_npc_name=spawned_name,
    )
    narration = gm_environment_text
    if outcome_kind == "environment_change" and environment_change_text:
        narration = f"{narration}\n{environment_change_text}".strip()
    return PublicTurnGmPushOutcome(
        narration=narration,
        scene_events=events,
        risk=risk,
        result=result,
        spawned_role=spawned_role,
    )
