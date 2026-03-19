from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ActionCheckResponse,
    ChatConfig,
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
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config


ReactionTone = str


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


_REACTION_ACTION_FORBIDDEN_TOKENS = (
    "push",
    "pull",
    "grab",
    "take",
    "steal",
    "move to",
    "cast",
    "attack",
    "block",
    "trip",
    "drag",
    "shove",
    "抢",
    "推",
    "拉",
    "拖",
    "拽",
    "扑",
    "撞",
    "攻击",
    "施法",
    "阻止",
    "夺",
    "举起武器",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str | None, *, limit: int) -> str:
    return " ".join(str(text or "").split()).strip()[:limit]


def compose_reaction_text(action: str, speech: str) -> str:
    clean_action = _clean(action, limit=120)
    clean_speech = _clean(speech, limit=120)
    if clean_action and clean_speech:
        return f'{clean_action} “{clean_speech}”'
    return clean_action or clean_speech


def infer_reaction_tone(action: str, speech: str) -> str:
    combined = "\n".join(part.strip().lower() for part in (action, speech) if str(part or "").strip())
    if not combined:
        return "neutral"
    if any(token in combined for token in ("support", "good", "well", "帮得好", "干得好", "做得好", "站你这边")):
        return "supportive"
    if any(token in combined for token in ("warning", "最好", "别", "住手", "后果", "不要", "警告")):
        return "warning"
    if any(token in combined for token in ("hostile", "滚", "混账", "闭嘴", "威胁")):
        return "hostile"
    if any(token in combined for token in ("careful", "小心", "先别", "稳住")):
        return "concerned"
    return "neutral"


def sanitize_reaction_tone_deltas(*, tone: str, relation_delta: int = 0, affinity_delta: int = 0, trust_delta: int = 0) -> tuple[int, int, int]:
    normalized_tone = str(tone or "neutral").strip().lower()
    if normalized_tone in {"warning", "hostile"}:
        relation_delta = min(relation_delta, 0)
        affinity_delta = min(affinity_delta, 0)
        trust_delta = max(-1, min(1, trust_delta))
    elif normalized_tone in {"neutral", "concerned"}:
        relation_delta = max(-1, min(1, relation_delta))
        affinity_delta = max(-1, min(1, affinity_delta))
        trust_delta = max(-1, min(1, trust_delta))
    elif normalized_tone in {"supportive", "approving"}:
        relation_delta = max(-3, min(3, relation_delta))
        affinity_delta = max(-3, min(3, affinity_delta))
        trust_delta = max(-3, min(3, trust_delta))
    return relation_delta, affinity_delta, trust_delta


def sanitize_reaction_action(text: str) -> str:
    action = _clean(text, limit=120)
    lowered = action.lower()
    if any(token in lowered for token in _REACTION_ACTION_FORBIDDEN_TOKENS):
        return ""
    return action


def public_turn_zone_reputation_allowed(actor_type: str) -> bool:
    return str(actor_type or "").strip().lower() in {"player", "team"}


def _ai_public_turn_npc_reaction(
    save: SaveFile,
    *,
    role,
    player_text: str,
    summary: str,
    relation_delta: int,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None,
) -> tuple[str, str, str, str | None, str | None, str]:
    if not has_ai_config(config):
        return "", "", "neutral", None, None, "player_action"
    assert config is not None
    prompt = (
        "You are generating one NPC reaction after the player acts during a public turn. "
        "Return JSON only with keys reaction_action and reaction_speech. "
        "reaction_action must be expressive only and cannot move, attack, block, grab, cast, or change any state. "
        "reaction_speech should be a short in-character line and may be empty. "
        f"npc_name={role.name}; personality={getattr(role, 'personality', '')}; speaking_style={getattr(role, 'speaking_style', '')}; "
        f"background={getattr(role, 'background', '')[:120]}; player_text={json.dumps(player_text, ensure_ascii=False)}; "
        f"summary={json.dumps(summary, ensure_ascii=False)}; relation_delta_hint={relation_delta}; "
        f"player_action_target_name={json.dumps(player_action_target_name, ensure_ascii=False)}; "
        f"current_primary_aggressor_name={json.dumps(current_primary_aggressor_name, ensure_ascii=False)}; "
        f"current_primary_target_name={json.dumps(current_primary_target_name, ensure_ascii=False)}; "
        f"prior_settlement_excerpt={json.dumps(prior_settlement_excerpt, ensure_ascii=False)}; "
        f"scene_conflict_summary={json.dumps(scene_conflict_summary, ensure_ascii=False)}; "
        "Also return reaction_tone, reaction_focus_target_name, reaction_speech_target_name, reaction_scope."
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
        usage = getattr(resp, "usage", None)
        if usage is not None:
            token_usage_store.add(
                save.session_id,
                "chat",
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
            )
        parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        if not isinstance(parsed, dict):
            return "", "", "neutral", None, None, "player_action"
        return (
            sanitize_reaction_action(str(parsed.get("reaction_action") or "")),
            _clean(str(parsed.get("reaction_speech") or ""), limit=120),
            str(parsed.get("reaction_tone") or infer_reaction_tone(str(parsed.get("reaction_action") or ""), str(parsed.get("reaction_speech") or ""))).strip().lower() or "neutral",
            _clean(str(parsed.get("reaction_focus_target_name") or ""), limit=80) or None,
            _clean(str(parsed.get("reaction_speech_target_name") or ""), limit=80) or None,
            _clean(str(parsed.get("reaction_scope") or "player_action"), limit=40) or "player_action",
        )
    except Exception:
        return "", "", "neutral", None, None, "player_action"


def _ai_public_turn_team_reaction(
    save: SaveFile,
    *,
    role,
    player_text: str,
    summary: str,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None,
) -> tuple[str, str, int, int, str, str | None, str | None, str]:
    if not has_ai_config(config):
        return "", "", 0, 0, "neutral", None, None, "player_action"
    assert config is not None
    prompt = (
        "You are generating one teammate reaction after the player's public-turn action. "
        "Return JSON only with keys reaction_action, reaction_speech, affinity_delta, trust_delta. "
        "reaction_action must be expressive only and cannot move, attack, block, grab, cast, or change any state. "
        "reaction_speech may be empty. affinity_delta and trust_delta must be integers between -3 and 3. "
        f"teammate_name={role.name}; personality={getattr(role, 'personality', '')}; speaking_style={getattr(role, 'speaking_style', '')}; "
        f"background={getattr(role, 'background', '')[:120]}; cognition={getattr(role, 'cognition', '')[:120]}; "
        f"player_text={json.dumps(player_text, ensure_ascii=False)}; summary={json.dumps(summary, ensure_ascii=False)}; "
        f"player_action_target_name={json.dumps(player_action_target_name, ensure_ascii=False)}; "
        f"current_primary_aggressor_name={json.dumps(current_primary_aggressor_name, ensure_ascii=False)}; "
        f"current_primary_target_name={json.dumps(current_primary_target_name, ensure_ascii=False)}; "
        f"prior_settlement_excerpt={json.dumps(prior_settlement_excerpt, ensure_ascii=False)}; "
        f"scene_conflict_summary={json.dumps(scene_conflict_summary, ensure_ascii=False)}; "
        "Also return reaction_tone, reaction_focus_target_name, reaction_speech_target_name, reaction_scope."
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
        usage = getattr(resp, "usage", None)
        if usage is not None:
            token_usage_store.add(
                save.session_id,
                "chat",
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
            )
        parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        if not isinstance(parsed, dict):
            return "", "", 0, 0, "neutral", None, None, "player_action"
        return (
            sanitize_reaction_action(str(parsed.get("reaction_action") or "")),
            _clean(str(parsed.get("reaction_speech") or ""), limit=120),
            clamp(int(parsed.get("affinity_delta") or 0), -3, 3),
            clamp(int(parsed.get("trust_delta") or 0), -3, 3),
            str(parsed.get("reaction_tone") or infer_reaction_tone(str(parsed.get("reaction_action") or ""), str(parsed.get("reaction_speech") or ""))).strip().lower() or "neutral",
            _clean(str(parsed.get("reaction_focus_target_name") or ""), limit=80) or None,
            _clean(str(parsed.get("reaction_speech_target_name") or ""), limit=80) or None,
            _clean(str(parsed.get("reaction_scope") or "player_action"), limit=40) or "player_action",
        )
    except Exception:
        return "", "", 0, 0, "neutral", None, None, "player_action"


def build_public_turn_team_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None,
) -> tuple[list[PublicTurnTeamAffinityDelta], list[SceneEvent]]:
    state = team_service.ensure_team_state(save)
    team_service.sync_team_members_with_player_in_save(save)
    rows: list[PublicTurnTeamAffinityDelta] = []
    events: list[SceneEvent] = []
    created_any = False
    for member in list(getattr(state, "members", [])):
        role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
        if role is None:
            continue
        affinity_before = int(member.affinity)
        trust_before = int(member.trust)
        ai_result = _ai_public_turn_team_reaction(
            save,
            role=role,
            player_text=player_text,
            summary=summary,
            player_action_target_name=player_action_target_name,
            current_primary_aggressor_name=current_primary_aggressor_name,
            current_primary_target_name=current_primary_target_name,
            prior_settlement_excerpt=prior_settlement_excerpt,
            scene_conflict_summary=scene_conflict_summary,
            config=config,
        )
        if isinstance(ai_result, tuple) and len(ai_result) >= 8:
            reaction_action, reaction_speech, affinity_delta, trust_delta, reaction_tone, reaction_focus_name, reaction_speech_target_name, reaction_scope = ai_result[:8]
        else:
            reaction_action, reaction_speech, affinity_delta, trust_delta = ai_result[:4]
            reaction_tone = infer_reaction_tone(reaction_action, reaction_speech)
            reaction_focus_name = None
            reaction_speech_target_name = None
            reaction_scope = "player_action"
        _, affinity_delta, trust_delta = sanitize_reaction_tone_deltas(
            tone=str(reaction_tone),
            affinity_delta=int(affinity_delta),
            trust_delta=int(trust_delta),
        )
        if not (reaction_action or reaction_speech or affinity_delta or trust_delta):
            continue
        member.affinity = clamp(member.affinity + affinity_delta, 0, 100)
        member.trust = clamp(member.trust + trust_delta, 0, 100)
        member.last_reaction_at = _utc_now()
        member.last_reaction_preview = compose_reaction_text(reaction_action, reaction_speech)[:120]
        role.attitude_changes.append(f"{member.last_reaction_at} team:public_turn:{affinity_delta}/{trust_delta}")
        role.attitude_changes = role.attitude_changes[-50:]
        content = compose_reaction_text(reaction_action, reaction_speech)
        row = PublicTurnTeamAffinityDelta(
            member_role_id=member.role_id,
            name=member.name,
            affinity_before=affinity_before,
            affinity_after=int(member.affinity),
            affinity_delta=int(member.affinity) - affinity_before,
            trust_before=trust_before,
            trust_after=int(member.trust),
            trust_delta=int(member.trust) - trust_before,
            reaction_tone=str(reaction_tone),
            reaction_focus_actor_name=reaction_focus_name,
            reaction_speech_target_name=reaction_speech_target_name,
            reaction_action=reaction_action,
            reaction_speech=reaction_speech,
            reaction_text=content,
        )
        rows.append(row)
        if content:
            state.reactions.append(
                TeamReaction(
                    reaction_id=team_service._new_id("treact"),
                    member_role_id=member.role_id,
                    member_name=member.name,
                    trigger_kind="public_turn",
                    content=content,
                    affinity_delta=row.affinity_delta,
                    trust_delta=row.trust_delta,
                )
            )
            state.reactions = state.reactions[-100:]
        created_any = True
        events.append(
            world._new_scene_event(
                "public_turn_team_update",
                f"{member.name}: {content}" if content else member.name,
                actor_role_id=member.role_id,
                actor_name=member.name,
                metadata={
                    "trigger_kind": "public_turn",
                    "member_role_id": member.role_id,
                    "name": member.name,
                    "affinity_before": affinity_before,
                    "affinity_after": int(member.affinity),
                    "affinity_delta": row.affinity_delta,
                    "trust_before": trust_before,
                    "trust_after": int(member.trust),
                    "trust_delta": row.trust_delta,
                    "reaction_tone": str(reaction_tone),
                    "reaction_focus_actor_name": reaction_focus_name,
                    "reaction_speech_target_name": reaction_speech_target_name,
                    "reaction_scope": reaction_scope,
                    "reaction_action": reaction_action,
                    "reaction_speech": reaction_speech,
                    "reaction_text": content,
                },
            )
        )
    if created_any:
        state.updated_at = _utc_now()
    return rows, events


def build_public_turn_npc_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
    relation_delta: int,
    target_role_id: str | None = None,
    max_extra_roles: int = 2,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None,
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
        ai_result = _ai_public_turn_npc_reaction(
            save,
            role=role,
            player_text=player_text,
            summary=summary,
            relation_delta=relation_delta,
            player_action_target_name=player_action_target_name,
            current_primary_aggressor_name=current_primary_aggressor_name,
            current_primary_target_name=current_primary_target_name,
            prior_settlement_excerpt=prior_settlement_excerpt,
            scene_conflict_summary=scene_conflict_summary,
            config=config,
        )
        if isinstance(ai_result, tuple) and len(ai_result) >= 6:
            reaction_action, reaction_speech, reaction_tone, reaction_focus_name, reaction_speech_target_name, reaction_scope = ai_result[:6]
        else:
            reaction_action, reaction_speech = ai_result[:2]
            reaction_tone = infer_reaction_tone(reaction_action, reaction_speech)
            reaction_focus_name = None
            reaction_speech_target_name = None
            reaction_scope = "player_action"
        reaction_text = compose_reaction_text(reaction_action, reaction_speech)
        delta_to_apply = relation_delta
        if index > 0 and relation_delta != 0:
            delta_to_apply = 1 if relation_delta > 0 else -1
        delta_to_apply, _, _ = sanitize_reaction_tone_deltas(tone=str(reaction_tone), relation_delta=int(delta_to_apply))
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
        if not (reaction_text or applied or before_tag != after_tag):
            continue
        row = PublicTurnRelationDelta(
            role_id=role.role_id,
            name=role.name,
            before_tag=before_tag,
            after_tag=after_tag,
            relation_delta=applied,
            reaction_tone=str(reaction_tone),
            reaction_focus_actor_name=reaction_focus_name,
            reaction_speech_target_name=reaction_speech_target_name,
            reaction_action=reaction_action,
            reaction_speech=reaction_speech,
            reaction_text=reaction_text,
        )
        rows.append(row)
        events.append(
            world._new_scene_event(
                "public_turn_relation_update",
                f"{role.name}: {reaction_text}" if reaction_text else role.name,
                actor_role_id=role.role_id,
                actor_name=role.name,
                metadata={
                    "role_id": role.role_id,
                    "name": role.name,
                    "before_tag": before_tag,
                    "after_tag": after_tag,
                    "relation_delta": applied,
                    "reaction_tone": str(reaction_tone),
                    "reaction_focus_actor_name": reaction_focus_name,
                    "reaction_speech_target_name": reaction_speech_target_name,
                    "reaction_scope": reaction_scope,
                    "reaction_action": reaction_action,
                    "reaction_speech": reaction_speech,
                    "reaction_text": reaction_text,
                },
            )
        )
    return rows, events


def apply_player_team_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None = None,
) -> tuple[list[PublicTurnTeamAffinityDelta], list[SceneEvent]]:
    return build_public_turn_team_reactions(
        save,
        session_id=session_id,
        player_text=player_text,
        summary=summary,
        player_action_target_name=player_action_target_name,
        current_primary_aggressor_name=current_primary_aggressor_name,
        current_primary_target_name=current_primary_target_name,
        prior_settlement_excerpt=prior_settlement_excerpt,
        scene_conflict_summary=scene_conflict_summary,
        config=config,
    )


def apply_player_npc_reactions(
    save: SaveFile,
    *,
    session_id: str,
    player_text: str,
    summary: str,
    relation_delta: int,
    target_role_id: str | None = None,
    max_extra_roles: int = 2,
    player_action_target_name: str = "",
    current_primary_aggressor_name: str = "",
    current_primary_target_name: str = "",
    prior_settlement_excerpt: str = "",
    scene_conflict_summary: str = "",
    config: ChatConfig | None = None,
) -> tuple[list[PublicTurnRelationDelta], list[SceneEvent]]:
    return build_public_turn_npc_reactions(
        save,
        session_id=session_id,
        player_text=player_text,
        summary=summary,
        relation_delta=relation_delta,
        target_role_id=target_role_id,
        max_extra_roles=max_extra_roles,
        player_action_target_name=player_action_target_name,
        current_primary_aggressor_name=current_primary_aggressor_name,
        current_primary_target_name=current_primary_target_name,
        prior_settlement_excerpt=prior_settlement_excerpt,
        scene_conflict_summary=scene_conflict_summary,
        config=config,
    )


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
