from __future__ import annotations

import json
from typing import Iterable

from openai import OpenAI

from app.core.prompt_table import prompt_table
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ChatConfig,
    PublicTurnNarrationFragmentBatch,
    PublicTurnNarrationFragmentResult,
    PublicTurnNarrationInputItem,
    PublicTurnNarrativeEntry,
    PublicTurnSettlementEntry,
)
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config


def _clean_line(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _fallback_fragment_from_item(item: PublicTurnNarrationInputItem) -> str:
    action = _clean_line(item.action_summary)
    speech = _clean_line(item.speech_text)
    summary = _clean_line(item.gm_resolution_summary)
    target = _clean_line(item.opposed_target_name or "")
    target_action = _clean_line(item.opposed_target_action or "")
    target_speech = _clean_line(item.opposed_target_speech or "")
    parts = [f"{item.actor_name}先有了动作。"]
    if action:
        parts.append(action)
    if speech:
        parts.append(f"他的话也紧跟着落下：{speech}")
    if target and target_action:
        parts.append(f"{target}立刻作出回应：{target_action}")
    if target_speech:
        parts.append(f"{target}也回了话：{target_speech}")
    if summary:
        parts.append(summary)
    return " ".join(part for part in parts if part).strip()


def _narration_payload(items: Iterable[PublicTurnNarrationInputItem]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in items:
        payload.append(
            {
                "anchor_kind": item.anchor_kind,
                "anchor_id": item.anchor_id,
                "order_index": item.order_index,
                "actor_name": item.actor_name,
                "actor_type": item.actor_type.value,
                "action_summary": item.action_summary,
                "speech_text": item.speech_text,
                "gm_resolution_summary": item.gm_resolution_summary,
                "opposed_target_name": item.opposed_target_name,
                "opposed_target_action": item.opposed_target_action,
                "opposed_target_speech": item.opposed_target_speech,
            }
        )
    return payload


def build_segment_narration_fragments(
    *,
    session_id: str,
    round_number: int,
    phase: str,
    segment_id: str,
    items: list[PublicTurnNarrationInputItem],
    prior_text: str,
    config: ChatConfig | None,
) -> PublicTurnNarrationFragmentBatch:
    fallback = PublicTurnNarrationFragmentBatch(
        segment_id=segment_id,
        fragments=[
            PublicTurnNarrationFragmentResult(
                anchor_kind=item.anchor_kind,
                anchor_id=item.anchor_id,
                text=_fallback_fragment_from_item(item),
            )
            for item in items
        ],
    )
    if not items or not has_ai_config(config):
        return fallback
    assert config is not None
    try:
        prompt = prompt_table.render(
            "public.turn.segment_narration.user",
            (
                "你是跑团公开回合的片段叙述器。只输出 JSON，结构为 "
                "{\"fragments\":[{\"anchor_id\":\"...\",\"text\":\"...\"}]}。"
                "基于本段已经完成的结算，按给定顺序分别为每个 anchor 写 1-3 句连续叙述。"
                "所有 fragment 要前后承接，像连续跑团描写，不是分散点评。"
                "不要输出 d20、DC、总值、数值变化、阶段名、系统提示、等待玩家文案。"
                "只写行为、对话、对手反应、局势连锁和气氛变化。"
                "必须为输入中的每个 anchor 各返回一条 fragment，anchor_id 保持一致。"
                "prior_text=$prior_text; round_number=$round_number; phase=$phase; items_json=$items_json"
            ),
            prior_text=prior_text[-720:],
            round_number=round_number,
            phase=phase,
            items_json=json.dumps(_narration_payload(items), ensure_ascii=False),
        )
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": prompt_table.get_text(
                        "public.turn.segment_narration.system",
                        "你只输出 JSON。所有文本使用简体中文。",
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            token_usage_store.add(
                session_id,
                "chat",
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        parsed = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        raw_fragments = list(parsed.get("fragments") or [])
        by_anchor: dict[str, PublicTurnNarrationFragmentResult] = {}
        for item in raw_fragments:
            if not isinstance(item, dict):
                continue
            anchor_id = _clean_line(str(item.get("anchor_id") or ""))
            if not anchor_id:
                continue
            text = _clean_line(str(item.get("text") or ""))
            if not text:
                continue
            anchor_kind = str(item.get("anchor_kind") or "settlement").strip().lower()
            if anchor_kind not in {"settlement", "pause_preview"}:
                anchor_kind = "settlement"
            by_anchor[anchor_id] = PublicTurnNarrationFragmentResult(
                anchor_kind=anchor_kind,  # type: ignore[arg-type]
                anchor_id=anchor_id,
                text=text,
            )
        normalized: list[PublicTurnNarrationFragmentResult] = []
        for source in items:
            normalized.append(
                by_anchor.get(
                    source.anchor_id,
                    PublicTurnNarrationFragmentResult(
                        anchor_kind=source.anchor_kind,
                        anchor_id=source.anchor_id,
                        text=_fallback_fragment_from_item(source),
                    ),
                )
            )
        return PublicTurnNarrationFragmentBatch(segment_id=segment_id, fragments=normalized)
    except Exception:
        return fallback


def build_narrative_fragment(
    *,
    session_id: str,
    round_number: int,
    settlement: PublicTurnSettlementEntry,
    prior_text: str,
    config: ChatConfig | None,
) -> str:
    item = PublicTurnNarrationInputItem(
        anchor_kind="settlement",
        anchor_id=settlement.entry_id,
        order_index=settlement.order_index,
        actor_name=settlement.actor_name,
        actor_type=settlement.actor_type,
        action_summary=settlement.action_summary,
        speech_text=settlement.speech_text,
        gm_resolution_summary=settlement.gm_resolution_summary,
        opposed_target_name=settlement.opposed_target_name,
        opposed_target_action=settlement.opposed_target_action,
        opposed_target_speech=settlement.opposed_target_speech,
    )
    batch = build_segment_narration_fragments(
        session_id=session_id,
        round_number=round_number,
        phase=settlement.phase.value,
        segment_id=f"{settlement.round_id}_single",
        items=[item],
        prior_text=prior_text,
        config=config,
    )
    if not batch.fragments:
        return _fallback_fragment_from_item(item)
    return _clean_line(batch.fragments[0].text) or _fallback_fragment_from_item(item)


def chunk_narrative_text(text: str, *, size: int = 28) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    return [clean[index : index + size] for index in range(0, len(clean), size)]


def append_narrative_text(existing: str, fragment: str) -> str:
    base = str(existing or "").rstrip()
    clean_fragment = str(fragment or "").strip()
    if not clean_fragment:
        return base
    if not base:
        return clean_fragment
    return f"{base}\n\n{clean_fragment}"


def build_round_narration(entries: Iterable[PublicTurnNarrativeEntry]) -> str:
    parts = [str(entry.text or "").strip() for entry in entries if str(entry.text or "").strip()]
    return "\n\n".join(parts).strip()
