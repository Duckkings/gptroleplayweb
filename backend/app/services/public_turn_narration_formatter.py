from __future__ import annotations

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


def _contains_target(text: str, target_name: str | None) -> bool:
    clean_text = _clean(text)
    clean_target = _clean(target_name)
    return bool(clean_text and clean_target and clean_target in clean_text)


def _format_action_fragment(actor_name: str, action: str, target_name: str | None) -> str:
    clean_action = _clean(action)
    if not clean_action:
        return ""
    clean_target = _clean(target_name)
    if clean_target and not _contains_target(clean_action, clean_target):
        return f"{actor_name}对{clean_target}{clean_action}"
    return f"{actor_name}{clean_action}"


def _format_speech_fragment(actor_name: str, speech: str, speech_target_name: str | None, fallback_target_name: str | None = None) -> str:
    clean_speech = _clean(speech)
    if not clean_speech:
        return ""
    clean_target = _clean(speech_target_name) or _clean(fallback_target_name)
    if clean_target:
        return f'{actor_name}朝{clean_target}说：“{clean_speech}”'
    return f'{actor_name}说：“{clean_speech}”'


def _reaction_body(name: str, action: str | None, speech: str | None, focus_name: str | None, speech_target_name: str | None) -> str:
    clean_action = _clean(action)
    clean_speech = _clean(speech)
    clean_focus = _clean(focus_name)
    clean_speech_target = _clean(speech_target_name)
    parts: list[str] = [name]
    if clean_action:
        if clean_focus and clean_focus not in clean_action:
            parts.append(f"盯着{clean_focus}{clean_action}")
        else:
            parts.append(clean_action)
    if clean_speech:
        if clean_speech_target:
            parts.append(f'朝{clean_speech_target}低声说：“{clean_speech}”')
        else:
            parts.append(f'低声说：“{clean_speech}”')
    return "".join(parts).strip()


def format_player_reaction_fragment(row: PublicTurnRelationDelta | PublicTurnTeamAffinityDelta) -> str:
    focus_name = getattr(row, "reaction_focus_actor_name", None)
    speech_target_name = getattr(row, "reaction_speech_target_name", None)
    return _reaction_body(row.name, row.reaction_action, row.reaction_speech, focus_name, speech_target_name)


def format_target_response_fragment(
    target_name: str | None,
    target_action: str | None,
    target_speech: str | None,
    target_speech_target_name: str | None,
    target_response_kind: str = "explicit_response",
) -> list[str]:
    clean_target_name = _clean(target_name) or "对方"
    fragments: list[str] = []
    if target_response_kind == "no_action" and not _clean(target_action) and not _clean(target_speech):
        return [f"{clean_target_name}没有采取任何行动"]
    if _clean(target_action):
        if _contains_target(str(target_action or ""), clean_target_name):
            fragments.append(_clean(target_action))
        else:
            fragments.append(f"{clean_target_name}回应时{_clean(target_action)}")
    if _clean(target_speech):
        speech_target = _clean(target_speech_target_name)
        if speech_target:
            fragments.append(f'{clean_target_name}朝{speech_target}说：“{_clean(target_speech)}”')
        else:
            fragments.append(f'{clean_target_name}说：“{_clean(target_speech)}”')
    return fragments


def format_actor_action_fragment(entry: PublicTurnSettlementEntry | PublicTurnNarrationInputItem) -> str:
    return _format_action_fragment(entry.actor_name, entry.action_summary, getattr(entry, "action_target_name", None))


def format_actor_speech_fragment(entry: PublicTurnSettlementEntry | PublicTurnNarrationInputItem) -> str:
    return _format_speech_fragment(
        entry.actor_name,
        entry.speech_text,
        getattr(entry, "speech_target_name", None),
        getattr(entry, "action_target_name", None),
    )


def format_pause_preview_fragment(item: PublicTurnNarrationInputItem) -> str:
    parts: list[str] = []
    action_fragment = format_actor_action_fragment(item)
    if action_fragment:
        parts.append(action_fragment)
    speech_fragment = format_actor_speech_fragment(item)
    if speech_fragment:
        parts.append(speech_fragment)
    parts.extend(
        format_target_response_fragment(
            item.opposed_target_name,
            item.opposed_target_action,
            item.opposed_target_speech,
            item.opposed_target_speech_target_name,
            "explicit_response",
        )
    )
    return " ".join(part for part in parts if part).strip()


def build_settlement_fragment(entry: PublicTurnSettlementEntry) -> str:
    if entry.entry_kind == "gm_push":
        parts: list[str] = []
        gm_text = _clean(entry.gm_resolution_summary)
        if gm_text:
            parts.append(gm_text)
        result = entry.gm_push_result
        if result is not None:
            label = _clean(result.outcome_label) or result.outcome_kind
            parts.append(f"d6={result.roll_d6}: {label}")
            change_text = _clean(result.environment_change_text)
            if change_text:
                parts.append(change_text)
            if result.spawned_npc_name:
                parts.append(f"{result.spawned_npc_name} joins the scene.")
        return " ".join(parts).strip()

    parts: list[str] = []
    action_fragment = format_actor_action_fragment(entry)
    if action_fragment:
        parts.append(action_fragment)
    speech_fragment = format_actor_speech_fragment(entry)
    if speech_fragment:
        parts.append(speech_fragment)
    parts.extend(
        format_target_response_fragment(
            entry.opposed_target_name,
            entry.opposed_target_action,
            entry.opposed_target_speech,
            entry.opposed_target_speech_target_name,
            entry.target_response_kind,
        )
    )
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


def build_round_narration_from_settlements(entries: list[PublicTurnSettlementEntry], preview_entries: list[PublicTurnNarrativeEntry] | None = None) -> str:
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
    else:
        status = PublicTurnRoundNarrationStatus.PENDING
    round_state.narrative_status = status
    round_state.round_narration_status = status
