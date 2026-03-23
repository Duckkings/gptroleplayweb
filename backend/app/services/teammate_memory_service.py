from __future__ import annotations

import json
from datetime import datetime, timezone

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    NpcDialogueEntry,
    NpcPrivateChatMemoryEntry,
    TeamPrivateChatMemoryGenerateRequest,
    TeamPrivateChatMemoryGenerateResponse,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.ai_protocol_contract_service import require_ai_config
from app.services.team_service import _find_member, ensure_team_state
from app.services.world_service import (
    _build_npc_roleplay_brief,
    _extract_json_content,
    _npc_conversation_state_summary,
    get_current_save,
    save_current,
)


class TeammatePrivateChatMemoryError(ValueError):
    pass


class TeammatePrivateChatMemoryGenerationError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_memory_id() -> str:
    return f"tmem_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def _normalize_source_dialogue_ids(source_dialogue_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in source_dialogue_ids:
        clean = str(raw or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        normalized.append(clean)
    return normalized


def _serialize_dialogue_entries(entries: list[NpcDialogueEntry]) -> list[dict[str, object]]:
    return [
        {
            "id": item.id,
            "speaker": item.speaker,
            "speaker_name": item.speaker_name,
            "world_time_text": item.world_time_text,
            "content": item.content,
        }
        for item in entries
    ]


def build_private_chat_memory_context(role, *, limit: int = 12) -> str:
    memories = list(getattr(role, "private_chat_memories", []) or [])
    if not memories:
        return "[]"
    payload = [
        {
            "world_time_text": item.world_time_text,
            "world_time": dict(item.world_time or {}),
            "summary": item.summary,
        }
        for item in reversed(memories[-limit:])
    ]
    return json.dumps(payload, ensure_ascii=False)


def _find_player_relation_tag(role, player_id: str) -> str:
    relation = next((item for item in role.relations if item.target_role_id == player_id), None)
    return str(relation.relation_tag or "neutral") if relation is not None else "neutral"


def _resolve_dialogue_entries(role, source_dialogue_ids: list[str]) -> list[NpcDialogueEntry]:
    requested_ids = _normalize_source_dialogue_ids(source_dialogue_ids)
    if not requested_ids:
        raise TeammatePrivateChatMemoryError("source_dialogue_ids is required")
    requested_set = set(requested_ids)
    entries = [
        item
        for item in role.dialogue_logs
        if item.id in requested_set and str(item.context_kind or "private_chat") == "private_chat"
    ]
    if len(entries) != len(requested_ids):
        raise TeammatePrivateChatMemoryError("source_dialogue_ids must belong to npc private_chat logs")
    entries_by_id = {item.id: item for item in entries}
    ordered_entries = [entries_by_id[item_id] for item_id in requested_ids]
    if not any(item.speaker == "player" for item in ordered_entries) or not any(item.speaker == "npc" for item in ordered_entries):
        raise TeammatePrivateChatMemoryError("source_dialogue_ids must include a complete private chat exchange")
    if ordered_entries[-1].speaker != "npc":
        raise TeammatePrivateChatMemoryError("source_dialogue_ids must end with npc reply")
    return ordered_entries


def _build_memory_prompt(*, role, member, player_name: str, relation_tag: str, dialogue_entries: list[NpcDialogueEntry]) -> str:
    latest_entry = dialogue_entries[-1]
    return prompt_table.render(
        PromptKeys.TEAM_PRIVATE_CHAT_MEMORY_USER,
        (
            "你要替一个队友 NPC 写下一条刚刚发生过的单聊记忆。\n"
            "只输出 JSON，不要输出额外解释。\n"
            'JSON schema: {"summary":"..."}\n'
            "summary 必须是简体中文，而且必须是这个角色自己心里会记住的一小段念头、判断或提醒。\n"
            "不要写成对玩家说的话，不要写成 GM 旁白，不要写规则说明。\n"
            "必须保留角色自己的口吻和脾气。\n"
            "长度控制在 80 字以内。\n"
            "如果最近这次单聊会影响这个队友在公开场合里的说话、站位、照应玩家或保持距离，就把这种影响写进记忆里。\n"
            "角色名: $role_name\n"
            "角色摘要: $roleplay_brief\n"
            "当前世界时间: $world_time_text\n"
            "当前会话状态: $conversation_state\n"
            "当前队伍关系=affinity:$affinity trust:$trust relation_tag:$relation_tag\n"
            "玩家名: $player_name\n"
            "本次单聊结构化记录: $dialogue_entries_json\n"
        ),
        role_name=role.name,
        roleplay_brief=_build_npc_roleplay_brief(role),
        world_time_text=latest_entry.world_time_text,
        conversation_state=_npc_conversation_state_summary(role),
        affinity=int(member.affinity),
        trust=int(member.trust),
        relation_tag=relation_tag,
        player_name=player_name,
        dialogue_entries_json=json.dumps(_serialize_dialogue_entries(dialogue_entries), ensure_ascii=False),
    )


def _generate_memory_summary(
    *,
    session_id: str,
    role,
    member,
    player_name: str,
    relation_tag: str,
    dialogue_entries: list[NpcDialogueEntry],
    config,
) -> str:
    config = require_ai_config(config)
    model = (config.model or "").strip()
    prompt = _build_memory_prompt(
        role=role,
        member=member,
        player_name=player_name,
        relation_tag=relation_tag,
        dialogue_entries=dialogue_entries,
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = (response.choices[0].message.content or "").strip() or "{}"
        parsed = _extract_json_content(raw_json)
        summary = str(parsed.get("summary") or "").strip()
        usage = getattr(response, "usage", None)
        if usage is not None:
            token_usage_store.add(
                session_id,
                "chat",
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
    except Exception as exc:  # pragma: no cover - exact provider failures vary
        raise TeammatePrivateChatMemoryGenerationError(f"teammate private chat memory generation failed: {exc}") from exc
    if not summary:
        raise TeammatePrivateChatMemoryGenerationError("teammate private chat memory generation returned empty summary")
    return summary[:80]


def generate_teammate_private_chat_memory(
    payload: TeamPrivateChatMemoryGenerateRequest,
) -> TeamPrivateChatMemoryGenerateResponse:
    save = get_current_save(default_session_id=payload.session_id)
    if save.session_id != payload.session_id:
        save.session_id = payload.session_id
    team_state = ensure_team_state(save)
    member = _find_member(team_state, payload.npc_role_id)
    if member is None:
        raise TeammatePrivateChatMemoryError("npc is not a current teammate")
    role = next((item for item in save.role_pool if item.role_id == payload.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")

    dialogue_entries = _resolve_dialogue_entries(role, payload.source_dialogue_ids)
    normalized_ids = [item.id for item in dialogue_entries]
    existing = next((item for item in role.private_chat_memories if item.source_dialogue_ids == normalized_ids), None)
    if existing is not None:
        return TeamPrivateChatMemoryGenerateResponse(
            session_id=payload.session_id,
            npc_role_id=payload.npc_role_id,
            memory=existing,
            role=role,
            deduped_existing=True,
        )

    relation_tag = _find_player_relation_tag(role, save.player_static_data.player_id)
    summary = _generate_memory_summary(
        session_id=payload.session_id,
        role=role,
        member=member,
        player_name=save.player_static_data.name,
        relation_tag=relation_tag,
        dialogue_entries=dialogue_entries,
        config=payload.config,
    )
    latest_entry = dialogue_entries[-1]
    memory = NpcPrivateChatMemoryEntry(
        memory_id=_new_memory_id(),
        world_time_text=latest_entry.world_time_text,
        world_time=dict(latest_entry.world_time or {}),
        created_at=_utc_now(),
        summary=summary,
        source_dialogue_ids=normalized_ids,
    )
    role.private_chat_memories.append(memory)
    role.private_chat_memories = role.private_chat_memories[-100:]
    save_current(save)
    return TeamPrivateChatMemoryGenerateResponse(
        session_id=payload.session_id,
        npc_role_id=payload.npc_role_id,
        memory=memory,
        role=role,
        deduped_existing=False,
    )
