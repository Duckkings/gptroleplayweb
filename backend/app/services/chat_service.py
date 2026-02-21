from __future__ import annotations

import os
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.models.schemas import ChatRequest, Message, Usage


class MissingAPIKeyError(RuntimeError):
    pass


def _build_messages(payload: ChatRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": payload.config.gm_prompt}]
    messages.extend({"role": m.role, "content": m.content} for m in payload.messages)
    return messages


def _build_usage(resp_usage: object | None) -> Usage:
    if resp_usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(resp_usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(resp_usage, "completion_tokens", 0) or 0,
    )


def _client(payload: ChatRequest) -> AsyncOpenAI:
    api_key = payload.config.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MissingAPIKeyError("openai_api_key is not set")
    return AsyncOpenAI(api_key=api_key)


async def chat_once(payload: ChatRequest) -> tuple[Message, Usage]:
    client = _client(payload)
    response = await client.chat.completions.create(
        model=payload.config.model,
        temperature=payload.config.temperature,
        max_tokens=payload.config.max_tokens,
        messages=_build_messages(payload),
    )
    content = response.choices[0].message.content or ""
    return Message(role="assistant", content=content), _build_usage(response.usage)


async def chat_stream(payload: ChatRequest) -> AsyncIterator[str]:
    client = _client(payload)
    stream = await client.chat.completions.create(
        model=payload.config.model,
        temperature=payload.config.temperature,
        max_tokens=payload.config.max_tokens,
        messages=_build_messages(payload),
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
