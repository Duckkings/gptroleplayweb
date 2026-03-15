from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel

from app.models.schemas import ChatConfig, MainTurnSegment, NpcChatSegment, Usage
from app.services.ai_adapter import (
    build_completion_options,
    create_async_client,
    create_gemini_native_client,
    resolve_structured_capability_profile,
)
from app.services.generation_debug_log_service import current_generation_debug_log

logger = logging.getLogger("roleplay.structured_segment")

ReplyEmitCallback = Callable[[str], Awaitable[None]]
CheckCancelledCallback = Callable[[], Awaitable[None]]
SegmentT = TypeVar("SegmentT", bound=BaseModel)


class StructuredSegmentFallbackRequired(RuntimeError):
    def __init__(self, *, provider_path: str, reason: str) -> None:
        super().__init__(reason)
        self.provider_path = provider_path
        self.reason = reason


@dataclass(frozen=True)
class StructuredSegmentResult(Generic[SegmentT]):
    segment: SegmentT
    usage: Usage
    provider_path: str
    synthetic_stream: bool = False


class StructuredReplyFieldStreamParser:
    def __init__(self) -> None:
        self._reply_text = ""

    @property
    def reply_text(self) -> str:
        return self._reply_text

    def feed(self, parsed: Any) -> str:
        current = _extract_reply_text(parsed)
        if not current:
            return ""
        previous = self._reply_text
        if current == previous:
            return ""
        if current.startswith(previous):
            delta = current[len(previous) :]
        else:
            prefix = 0
            max_prefix = min(len(previous), len(current))
            while prefix < max_prefix and previous[prefix] == current[prefix]:
                prefix += 1
            delta = current[prefix:]
        self._reply_text = current
        return delta


def _extract_reply_text(parsed: Any) -> str:
    if parsed is None:
        return ""
    if isinstance(parsed, dict):
        value = parsed.get("reply_text")
        return str(value or "")
    value = getattr(parsed, "reply_text", "")
    return str(value or "")


def _usage_from_openai_like(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _sum_usage(left: Usage, right: Usage) -> Usage:
    return Usage(
        input_tokens=int(left.input_tokens + right.input_tokens),
        output_tokens=int(left.output_tokens + right.output_tokens),
    )


def _validate_segment(segment_model: type[SegmentT], parsed: Any) -> SegmentT:
    if isinstance(parsed, segment_model):
        return parsed
    if isinstance(parsed, BaseModel):
        return segment_model.model_validate(parsed.model_dump(mode="json"))
    return segment_model.model_validate(parsed)


def _parse_json_text(text: str) -> dict[str, Any]:
    content = str(text or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        parsed, end = json.JSONDecoder().raw_decode(content)
        trailing = content[end:].strip()
        if trailing and trailing not in {'"', "'", "`"}:
            raise exc
    if not isinstance(parsed, dict):
        raise ValueError("structured segment must decode to object")
    return parsed


def _synthetic_reply_chunks(reply_text: str) -> list[str]:
    text = str(reply_text or "")
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    punctuation = "。！？!?；;\n"
    max_len = 18
    for index, char in enumerate(text):
        boundary = char in punctuation or (index - start + 1) >= max_len
        if not boundary:
            continue
        chunk = text[start : index + 1]
        if chunk:
            chunks.append(chunk)
        start = index + 1
    if start < len(text):
        chunks.append(text[start:])
    return [chunk for chunk in chunks if chunk]


async def _emit_synthetic_reply(
    *,
    reply_text: str,
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> None:
    if emit_reply_delta is None:
        return
    for chunk in _synthetic_reply_chunks(reply_text):
        if check_cancelled is not None:
            await check_cancelled()
        await emit_reply_delta(chunk)
        await asyncio.sleep(0)


def _structured_mode(config: ChatConfig) -> str:
    mode = str(getattr(config.runtime, "structured_output_mode", "auto") or "auto").strip().lower()
    return mode if mode in {"auto", "legacy_tags"} else "auto"


async def _stream_openai_schema_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[SegmentT]:
    client = create_async_client(config)
    usage = Usage()
    parser = StructuredReplyFieldStreamParser()
    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "response_format": segment_model,
        **build_completion_options(config),
    }
    kwargs["stream_options"] = {"include_usage": True}
    async with client.beta.chat.completions.stream(**kwargs) as stream:
        async for event in stream:
            if check_cancelled is not None:
                await check_cancelled()
            event_type = getattr(event, "type", "")
            if event_type == "chunk":
                usage = _sum_usage(usage, _usage_from_openai_like(getattr(getattr(event, "chunk", None), "usage", None)))
                continue
            if event_type == "content.delta":
                delta = parser.feed(getattr(event, "parsed", None))
                if delta and emit_reply_delta is not None:
                    await emit_reply_delta(delta)
        completion = await stream.get_final_completion()
    final_usage = _usage_from_openai_like(getattr(completion, "usage", None))
    if final_usage.input_tokens or final_usage.output_tokens:
        usage = final_usage
    parsed = getattr(completion.choices[0].message, "parsed", None)
    if parsed is None:
        raise ValueError("structured completion missing parsed segment")
    segment = _validate_segment(segment_model, parsed)
    if emit_reply_delta is not None and segment.reply_text.startswith(parser.reply_text):
        tail = segment.reply_text[len(parser.reply_text) :]
        if tail:
            await emit_reply_delta(tail)
    return StructuredSegmentResult(segment=segment, usage=usage, provider_path="openai_schema_stream")


async def _complete_openai_schema_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[SegmentT]:
    client = create_async_client(config)
    response = await client.beta.chat.completions.parse(
        model=config.model,
        messages=messages,
        response_format=segment_model,
        **build_completion_options(config),
    )
    parsed = getattr(response.choices[0].message, "parsed", None)
    if parsed is None:
        raise ValueError("structured completion missing parsed segment")
    segment = _validate_segment(segment_model, parsed)
    if check_cancelled is not None:
        await check_cancelled()
    await _emit_synthetic_reply(reply_text=segment.reply_text, emit_reply_delta=emit_reply_delta, check_cancelled=check_cancelled)
    return StructuredSegmentResult(
        segment=segment,
        usage=_usage_from_openai_like(getattr(response, "usage", None)),
        provider_path="openai_schema_stream",
        synthetic_stream=True,
    )


async def _run_deepseek_two_phase_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[SegmentT]:
    client = create_async_client(config)
    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        response_format={"type": "json_object"},
        **build_completion_options(config),
    )
    content = getattr(response.choices[0].message, "content", "") or ""
    if isinstance(content, list):
        content = "".join(str(item.get("text") or "") if isinstance(item, dict) else str(item) for item in content)
    raw = _parse_json_text(str(content))
    segment = segment_model.model_validate(raw)
    await _emit_synthetic_reply(reply_text=segment.reply_text, emit_reply_delta=emit_reply_delta, check_cancelled=check_cancelled)
    return StructuredSegmentResult(
        segment=segment,
        usage=_usage_from_openai_like(getattr(response, "usage", None)),
        provider_path="deepseek_json_two_phase",
        synthetic_stream=True,
    )


def _extract_gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    candidates = getattr(response, "candidates", None) or []
    pieces: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str):
                pieces.append(part_text)
    return "".join(pieces)


def _usage_from_gemini_response(response: Any) -> Usage:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return Usage()
    input_tokens = int(
        getattr(metadata, "prompt_token_count", 0)
        or getattr(metadata, "cached_content_token_count", 0)
        or 0
    )
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens)


async def _run_gemini_native_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[SegmentT]:
    try:
        client = create_gemini_native_client(config)
    except Exception as exc:  # pragma: no cover - dependency unavailable in tests
        raise StructuredSegmentFallbackRequired(
            provider_path="gemini_native_schema_stream",
            reason=f"gemini native sdk unavailable: {exc}",
        ) from exc

    try:  # pragma: no cover - live Gemini path not exercised in unit tests
        module = __import__("google.genai", fromlist=["types"])
        types_mod = getattr(module, "types", None)
        config_cls = getattr(types_mod, "GenerateContentConfig", None)
        if config_cls is None:
            raise RuntimeError("GenerateContentConfig not available")
        contents = [{"role": item["role"], "parts": [{"text": item["content"]}]} for item in messages]
        generation_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": segment_model,
        }
        options = build_completion_options(config)
        if "temperature" in options:
            generation_kwargs["temperature"] = options["temperature"]
        max_output_tokens = options.get("max_completion_tokens", options.get("max_tokens"))
        if isinstance(max_output_tokens, int):
            generation_kwargs["max_output_tokens"] = max_output_tokens
        generation_config = config_cls(**generation_kwargs)
        models_api = getattr(getattr(client, "aio", client), "models", None)
        generate_fn = getattr(models_api, "generate_content", None)
        if generate_fn is None:
            raise RuntimeError("Gemini native client missing models.generate_content")
        response = generate_fn(model=config.model, contents=contents, config=generation_config)
        if asyncio.iscoroutine(response):
            response = await response
        raw_text = _extract_gemini_text(response)
        segment = segment_model.model_validate(_parse_json_text(raw_text))
        await _emit_synthetic_reply(reply_text=segment.reply_text, emit_reply_delta=emit_reply_delta, check_cancelled=check_cancelled)
        return StructuredSegmentResult(
            segment=segment,
            usage=_usage_from_gemini_response(response),
            provider_path="gemini_native_schema_stream",
            synthetic_stream=True,
        )
    except StructuredSegmentFallbackRequired:
        raise
    except Exception as exc:  # pragma: no cover - live Gemini path not exercised in unit tests
        raise StructuredSegmentFallbackRequired(
            provider_path="gemini_native_schema_stream",
            reason=f"gemini native structured segment failed: {exc}",
        ) from exc


async def _stream_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[SegmentT]:
    profile = resolve_structured_capability_profile(config.provider, config.model)
    debug_log = current_generation_debug_log()
    if debug_log is not None:
        debug_log.record(
            "structured_provider_path",
            "resolved structured provider path",
            {
                "provider": config.provider,
                "model": config.model,
                "provider_path": profile,
                "mode": _structured_mode(config),
            },
        )
    if profile == "openai_schema_stream":
        try:
            return await _stream_openai_schema_segment(
                config=config,
                messages=messages,
                segment_model=segment_model,
                emit_reply_delta=emit_reply_delta,
                check_cancelled=check_cancelled,
            )
        except Exception as exc:
            # Fallback to completion mode if streaming fails
            if debug_log is not None:
                debug_log.record(
                    "structured_stream_fallback",
                    "openai schema stream failed, falling back to completion",
                    {"error": str(exc)},
                )
            return await _complete_openai_schema_segment(
                config=config,
                messages=messages,
                segment_model=segment_model,
                emit_reply_delta=emit_reply_delta,
                check_cancelled=check_cancelled,
            )
    if profile == "deepseek_json_two_phase":
        return await _run_deepseek_two_phase_segment(
            config=config,
            messages=messages,
            segment_model=segment_model,
            emit_reply_delta=emit_reply_delta,
            check_cancelled=check_cancelled,
        )
    if profile == "gemini_native_schema_stream":
        return await _run_gemini_native_segment(
            config=config,
            messages=messages,
            segment_model=segment_model,
            emit_reply_delta=emit_reply_delta,
            check_cancelled=check_cancelled,
        )
    raise StructuredSegmentFallbackRequired(provider_path="legacy_tag_fallback", reason="structured provider path unavailable")


async def _complete_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    segment_model: type[SegmentT],
) -> StructuredSegmentResult[SegmentT]:
    profile = resolve_structured_capability_profile(config.provider, config.model)
    if profile == "openai_schema_stream":
        return await _complete_openai_schema_segment(
            config=config,
            messages=messages,
            segment_model=segment_model,
            emit_reply_delta=None,
            check_cancelled=None,
        )
    if profile == "deepseek_json_two_phase":
        return await _run_deepseek_two_phase_segment(
            config=config,
            messages=messages,
            segment_model=segment_model,
            emit_reply_delta=None,
            check_cancelled=None,
        )
    if profile == "gemini_native_schema_stream":
        return await _run_gemini_native_segment(
            config=config,
            messages=messages,
            segment_model=segment_model,
            emit_reply_delta=None,
            check_cancelled=None,
        )
    raise StructuredSegmentFallbackRequired(provider_path="legacy_tag_fallback", reason="structured provider path unavailable")


async def stream_main_turn_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[MainTurnSegment]:
    return await _stream_segment(
        config=config,
        messages=messages,
        segment_model=MainTurnSegment,
        emit_reply_delta=emit_reply_delta,
        check_cancelled=check_cancelled,
    )


async def complete_main_turn_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
) -> StructuredSegmentResult[MainTurnSegment]:
    return await _complete_segment(config=config, messages=messages, segment_model=MainTurnSegment)


async def stream_npc_chat_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
    emit_reply_delta: ReplyEmitCallback | None,
    check_cancelled: CheckCancelledCallback | None,
) -> StructuredSegmentResult[NpcChatSegment]:
    return await _stream_segment(
        config=config,
        messages=messages,
        segment_model=NpcChatSegment,
        emit_reply_delta=emit_reply_delta,
        check_cancelled=check_cancelled,
    )


async def complete_npc_chat_segment(
    *,
    config: ChatConfig,
    messages: list[dict[str, str]],
) -> StructuredSegmentResult[NpcChatSegment]:
    return await _complete_segment(config=config, messages=messages, segment_model=NpcChatSegment)
