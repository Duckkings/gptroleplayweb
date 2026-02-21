from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UIConfig(BaseModel):
    theme: str = Field(default="dark")


class ChatConfig(BaseModel):
    version: str = Field(default="1.0.0")
    openai_api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    stream: bool
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = Field(default=1200, gt=0)
    gm_prompt: str = Field(..., min_length=1)
    ui: UIConfig | None = None


class ValidateError(BaseModel):
    field: str
    message: str


class ValidateConfigResponse(BaseModel):
    valid: bool
    errors: list[ValidateError]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    config: ChatConfig
    messages: list[Message] = Field(..., min_length=1)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ChatResponse(BaseModel):
    session_id: str
    reply: Message
    usage: Usage


class HealthResponse(BaseModel):
    ok: bool
    time: str
