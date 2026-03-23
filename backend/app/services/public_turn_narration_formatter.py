from __future__ import annotations

import json

from app.models.schemas import (
    PublicTurnNarrativeEntry,
    PublicTurnNarrationInputItem,
    PublicTurnPhase,
    PublicTurnRelationDelta,
    PublicTurnRound,
    PublicTurnRoundNarrationStatus,
    PublicTurnSettlementEntry,
    PublicTurnTeamAffinityDelta,
)


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def _clean_resolution_text(text: str | None) -> str:
    clean = _clean(text)
    if not clean:
        return ""
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```JSON").removeprefix("```").strip()
        if clean.endswith("```"):
            clean = clean[:-3].strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return clean
    if isinstance(parsed, dict):
        for key in ("outcome", "outcome_description", "outcome_narration", "summary", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return _clean(value)
    return clean


def _format_actor_action_fallback(entry: PublicTurnSettlementEntry) -> str:
    actor_action = _clean(entry.action_summary)
    actor_speech = _clean(entry.speech_text)
    speech_target = _clean(entry.speech_target_name)
    if actor_action and actor_speech and speech_target:
        return f"{actor_action}，朝{speech_target}说：“{actor_speech}”"
    if actor_action and actor_speech:
        return f'{actor_action}，“{actor_speech}”'
    if actor_action:
        return actor_action
    if actor_speech and speech_target:
        return f'{entry.actor_name}朝{speech_target}说：“{actor_speech}”'
    if actor_speech:
        return f'{entry.actor_name}说：“{actor_speech}”'
    return ""


def _format_opposed_check_fragment(entry: PublicTurnSettlementEntry) -> str:
    check = entry.check
    if check is None or check.resolution_rule != "opposed_actor":
        return ""
    target_name = _clean(check.target_name or entry.opposed_target_name or "对手")
    response_parts = [_clean(entry.opposed_target_action)]
    target_speech = _clean(entry.opposed_target_speech)
    if target_speech:
        response_parts.append(f'“{target_speech}”')
    outcome = f"{entry.actor_name}在对抗中压过了{target_name}。" if check.success else f"{entry.actor_name}没能压过{target_name}的回应。"
    return " ".join(part for part in [*response_parts, outcome] if part)


def format_player_reaction_fragment(row: PublicTurnRelationDelta | PublicTurnTeamAffinityDelta) -> str:
    parts = [row.name]
    reaction_text = _clean(getattr(row, "reaction_text", ""))
    if reaction_text:
        parts.append(reaction_text)
    else:
        reaction_action = _clean(getattr(row, "reaction_action", ""))
        reaction_speech = _clean(getattr(row, "reaction_speech", ""))
        if reaction_action:
            parts.append(reaction_action)
        if reaction_speech:
            parts.append(f'“{reaction_speech}”')
    return "，".join(part for part in parts if part).strip()


def format_pause_preview_fragment(item: PublicTurnNarrationInputItem) -> str:
    summary = _clean_resolution_text(item.gm_resolution_summary)
    if summary:
        return summary
    target_name = _clean(item.opposed_target_name or item.action_target_name or item.speech_target_name)
    if target_name:
        return f"{item.actor_name}已向{target_name}发起交互，等待回应。"
    return f"{item.actor_name}的行动正在结算。"


def build_settlement_fragment(entry: PublicTurnSettlementEntry) -> str:
    if entry.entry_kind == "gm_push":
        parts: list[str] = []
        summary = _clean_resolution_text(entry.gm_resolution_summary)
        if summary:
            parts.append(summary)
        result = entry.gm_push_result
        if result is not None:
            label = _clean(result.outcome_label) or result.outcome_kind
            parts.append(f"d6={result.roll_d6}，结果：{label}")
            if _clean(result.environment_change_text):
                parts.append(_clean(result.environment_change_text))
            if _clean(result.spawned_npc_name):
                parts.append(f"{_clean(result.spawned_npc_name)}进入了场景。")
        return " ".join(part for part in parts if part).strip()

    summary = _clean_resolution_text(entry.gm_resolution_summary)
    parts: list[str] = []
    if summary:
        parts.append(summary)
    else:
        actor_fragment = _format_actor_action_fallback(entry)
        opposed_fragment = _format_opposed_check_fragment(entry)
        if actor_fragment:
            parts.append(actor_fragment)
        if opposed_fragment:
            parts.append(opposed_fragment)

    if entry.actor_type == "player":
        for row in entry.relation_deltas:
            fragment = format_player_reaction_fragment(row)
            if fragment:
                parts.append(fragment)
        for row in entry.team_affinity_deltas:
            fragment = format_player_reaction_fragment(row)
            if fragment:
                parts.append(fragment)

    return " ".join(part for part in parts if part).strip()


def build_round_narration_from_settlements(
    entries: list[PublicTurnSettlementEntry],
    preview_entries: list[PublicTurnNarrativeEntry] | None = None,
) -> str:
    fragments = [build_settlement_fragment(entry) for entry in entries]
    fragments.extend(_clean(item.text) for item in (preview_entries or []) if _clean(item.text))
    return "\n\n".join(fragment for fragment in fragments if fragment).strip()


def build_narrative_entries_from_settlements(round_state: PublicTurnRound) -> list[PublicTurnNarrativeEntry]:
    entries: list[PublicTurnNarrativeEntry] = []
    preview_entries = [item for item in round_state.narrative_entries if item.settlement_entry_id is None and _clean(item.text)]
    for settlement in round_state.settlement_entries:
        fragment = build_settlement_fragment(settlement)
        if not fragment:
            settlement.narrative_entry_id = None
            continue
        narrative_entry = PublicTurnNarrativeEntry(
            narrative_entry_id=f"{round_state.round_id}_narr_{len(entries) + 1}",
            round_id=round_state.round_id,
            settlement_entry_id=settlement.entry_id,
            phase=settlement.phase,
            order_index=len(entries),
            actor_id=settlement.actor_id,
            actor_name=settlement.actor_name,
            actor_type=settlement.actor_type,
            text=fragment,
            status="ready",
        )
        settlement.narrative_entry_id = narrative_entry.narrative_entry_id
        entries.append(narrative_entry)
    next_order = len(entries)
    for preview in preview_entries:
        entries.append(
            PublicTurnNarrativeEntry(
                narrative_entry_id=preview.narrative_entry_id,
                round_id=preview.round_id,
                settlement_entry_id=None,
                phase=preview.phase,
                order_index=next_order,
                actor_id=preview.actor_id,
                actor_name=preview.actor_name,
                actor_type=preview.actor_type,
                text=preview.text,
                status="ready",
            )
        )
        next_order += 1
    return entries


def sync_round_narration_from_settlements(round_state: PublicTurnRound) -> None:
    round_state.narrative_entries = build_narrative_entries_from_settlements(round_state)
    preview_entries = [item for item in round_state.narrative_entries if item.settlement_entry_id is None]
    narration = build_round_narration_from_settlements(round_state.settlement_entries, preview_entries=preview_entries)
    round_state.accumulated_narration = narration
    round_state.round_narration = narration
    if narration:
        if round_state.phase in {
            PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            PublicTurnPhase.AWAITING_PLAYER_REACTION,
            PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
        }:
            status = PublicTurnRoundNarrationStatus.PAUSED
        else:
            status = PublicTurnRoundNarrationStatus.READY
    elif round_state.awaiting_player_action:
        status = PublicTurnRoundNarrationStatus.PENDING
    else:
        status = PublicTurnRoundNarrationStatus.EMPTY
    round_state.round_narration_status = status
    round_state.narrative_status = status
