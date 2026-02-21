from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError, RateLimitError
from pydantic import ValidationError

from app.models.schemas import (
    ChatConfig,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ValidateConfigResponse,
    ValidateError,
)
from app.services.chat_service import MissingAPIKeyError, chat_once, chat_stream

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, time=datetime.now(timezone.utc).isoformat())


@router.post("/config/validate", response_model=ValidateConfigResponse)
async def validate_config(payload: dict) -> ValidateConfigResponse:
    try:
        ChatConfig.model_validate(payload)
    except ValidationError as exc:
        errors = [
            ValidateError(field=".".join(str(p) for p in err["loc"]), message=err["msg"])
            for err in exc.errors()
        ]
        return ValidateConfigResponse(valid=False, errors=errors)

    return ValidateConfigResponse(valid=True, errors=[])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    try:
        reply, usage = await chat_once(payload)
    except MissingAPIKeyError:
        raise HTTPException(status_code=401, detail="openai_api_key is not configured in config")
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return ChatResponse(session_id=payload.session_id, reply=reply, usage=usage)


@router.post("/chat/stream")
async def chat_sse(payload: ChatRequest) -> StreamingResponse:
    if not payload.config.stream:
        raise HTTPException(status_code=400, detail="config.stream must be true")

    async def event_gen():
        yield "event: start\ndata: {\"session_id\":\"%s\"}\n\n" % payload.session_id
        try:
            async for delta in chat_stream(payload):
                data = json.dumps({"content": delta}, ensure_ascii=False)
                yield f"event: delta\ndata: {data}\n\n"
        except MissingAPIKeyError:
            data = json.dumps({"code": 401, "message": "openai_api_key is not configured in config"})
            yield f"event: error\ndata: {data}\n\n"
            return
        except RateLimitError as exc:
            data = json.dumps({"code": 429, "message": str(exc)})
            yield f"event: error\ndata: {data}\n\n"
            return
        except APIError as exc:
            data = json.dumps({"code": 502, "message": str(exc)})
            yield f"event: error\ndata: {data}\n\n"
            return

        yield "event: end\ndata: {\"usage\":{\"input_tokens\":0,\"output_tokens\":0}}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")

