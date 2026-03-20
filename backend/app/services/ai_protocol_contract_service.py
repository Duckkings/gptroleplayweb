from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from openai import OpenAI

from app.models.schemas import ChatConfig
from app.services.ai_adapter import build_completion_options, create_sync_client, has_ai_config

AI_CONFIG_REQUIRED = "AI_CONFIG_REQUIRED"
AI_PROVIDER_CALL_FAILED = "AI_PROVIDER_CALL_FAILED"
AI_PROTOCOL_ENUM_INVALID = "AI_PROTOCOL_ENUM_INVALID"
AI_PROTOCOL_REPAIR_FAILED = "AI_PROTOCOL_REPAIR_FAILED"

_ALLOW_PROTOCOL_REPAIR: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "allow_ai_protocol_repair",
    default=False,
)


@dataclass(frozen=True)
class EnumContractField:
    field_path: str
    allowed_ids: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class EnumContractViolation:
    field_path: str
    invalid_value: str | None
    allowed_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class AiProtocolRepairRequest:
    system_prompt: str
    original_prompt: str
    raw_json: str
    fields: tuple[EnumContractField, ...]


@dataclass(frozen=True)
class AiProtocolRepairNotice:
    code: str
    message: str
    violations: tuple[EnumContractViolation, ...]


class AiProtocolContractError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        violations: list[EnumContractViolation] | None = None,
        repair_request: AiProtocolRepairRequest | None = None,
    ) -> None:
        self.code = code
        self.violations = list(violations or [])
        self.repair_request = repair_request
        super().__init__(message or code)


def require_ai_config(config: ChatConfig | None) -> ChatConfig:
    if not has_ai_config(config):
        raise AiProtocolContractError(AI_CONFIG_REQUIRED, message=AI_CONFIG_REQUIRED)
    assert config is not None
    return config


def protocol_repair_enabled() -> bool:
    return bool(_ALLOW_PROTOCOL_REPAIR.get())


@contextmanager
def allow_protocol_repair() -> Iterator[None]:
    token = _ALLOW_PROTOCOL_REPAIR.set(True)
    try:
        yield
    finally:
        _ALLOW_PROTOCOL_REPAIR.reset(token)


def render_enum_pool_text(fields: list[EnumContractField] | tuple[EnumContractField, ...]) -> str:
    rows: list[str] = []
    for field in fields:
        rows.append(f"{field.field_path}={'|'.join(field.allowed_ids)}")
    return "\n".join(rows)


def _walk_path(node: Any, parts: list[str], prefix: str) -> list[tuple[str, Any]]:
    if not parts:
        return [(prefix or "", node)]
    part = parts[0]
    rest = parts[1:]
    if part.endswith("[]"):
        key = part[:-2]
        if not isinstance(node, dict):
            return []
        items = node.get(key)
        if not isinstance(items, list):
            return []
        matches: list[tuple[str, Any]] = []
        for index, item in enumerate(items):
            item_prefix = f"{prefix}.{key}[{index}]" if prefix else f"{key}[{index}]"
            matches.extend(_walk_path(item, rest, item_prefix))
        return matches
    if not isinstance(node, dict) or part not in node:
        return []
    next_prefix = f"{prefix}.{part}" if prefix else part
    return _walk_path(node.get(part), rest, next_prefix)


def validate_enum_fields(
    payload: dict[str, Any] | None,
    fields: list[EnumContractField] | tuple[EnumContractField, ...],
) -> list[EnumContractViolation]:
    if not isinstance(payload, dict):
        return [
            EnumContractViolation(
                field_path="$",
                invalid_value=None,
                allowed_ids=tuple(),
                reason="payload_not_object",
            )
        ]
    violations: list[EnumContractViolation] = []
    for field in fields:
        matches = _walk_path(payload, field.field_path.split("."), "")
        if not matches:
            if field.required:
                violations.append(
                    EnumContractViolation(
                        field_path=field.field_path,
                        invalid_value=None,
                        allowed_ids=field.allowed_ids,
                        reason="missing",
                    )
                )
            continue
        for actual_path, value in matches:
            normalized = str(value or "").strip().lower() if isinstance(value, str) else None
            if normalized is None:
                violations.append(
                    EnumContractViolation(
                        field_path=actual_path or field.field_path,
                        invalid_value=None if value is None else str(value),
                        allowed_ids=field.allowed_ids,
                        reason="not_string",
                    )
                )
                continue
            if normalized not in field.allowed_ids:
                violations.append(
                    EnumContractViolation(
                        field_path=actual_path or field.field_path,
                        invalid_value=normalized,
                        allowed_ids=field.allowed_ids,
                        reason="not_in_allowed_ids",
                    )
                )
    return violations


def build_repair_prompt(
    original_prompt: str,
    raw_json: str,
    violations: list[EnumContractViolation],
) -> str:
    violation_rows = [
        {
            "field_path": item.field_path,
            "invalid_value": item.invalid_value,
            "allowed_ids": list(item.allowed_ids),
            "reason": item.reason,
        }
        for item in violations
    ]
    return (
        "The previous JSON violated enum protocol fields.\n"
        "Return JSON only.\n"
        "Do not rewrite unrelated fields.\n"
        "Keep all non-enum values as close as possible to the original JSON.\n"
        f"Original prompt:\n{original_prompt}\n"
        f"Original JSON:\n{raw_json}\n"
        f"Violations:\n{json.dumps(violation_rows, ensure_ascii=False)}"
    )


def repair_once_with_same_model(
    *,
    config: ChatConfig | None,
    repair_request: AiProtocolRepairRequest,
) -> dict[str, Any]:
    config = require_ai_config(config)
    notice = AiProtocolRepairNotice(
        code=AI_PROTOCOL_ENUM_INVALID,
        message=AI_PROTOCOL_ENUM_INVALID,
        violations=tuple(),
    )
    del notice
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        response = client.chat.completions.create(
            model=config.model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": repair_request.system_prompt},
                {
                    "role": "user",
                    "content": build_repair_prompt(
                        repair_request.original_prompt,
                        repair_request.raw_json,
                        validate_enum_fields(
                            json.loads(repair_request.raw_json or "{}")
                            if str(repair_request.raw_json or "").strip()
                            else {},
                            repair_request.fields,
                        ),
                    ),
                },
            ],
        )
    except AiProtocolContractError:
        raise
    except Exception as exc:
        raise AiProtocolContractError(AI_PROVIDER_CALL_FAILED, message=f"{AI_PROVIDER_CALL_FAILED}: {exc}") from exc
    try:
        parsed = json.loads((response.choices[0].message.content or "").strip() or "{}")
    except Exception as exc:
        raise AiProtocolContractError(AI_PROTOCOL_REPAIR_FAILED, message=f"{AI_PROTOCOL_REPAIR_FAILED}: invalid_json") from exc
    violations = validate_enum_fields(parsed if isinstance(parsed, dict) else {}, repair_request.fields)
    if violations:
        raise AiProtocolContractError(
            AI_PROTOCOL_REPAIR_FAILED,
            message=AI_PROTOCOL_REPAIR_FAILED,
            violations=violations,
            repair_request=repair_request,
        )
    if not isinstance(parsed, dict):
        raise AiProtocolContractError(AI_PROTOCOL_REPAIR_FAILED, message=AI_PROTOCOL_REPAIR_FAILED)
    return parsed


def validate_or_repair_json_payload(
    *,
    parsed: dict[str, Any] | None,
    raw_json: str,
    fields: list[EnumContractField] | tuple[EnumContractField, ...],
    config: ChatConfig | None,
    system_prompt: str,
    original_prompt: str,
) -> dict[str, Any]:
    payload = parsed if isinstance(parsed, dict) else {}
    violations = validate_enum_fields(payload, fields)
    if not violations:
        return payload
    repair_request = AiProtocolRepairRequest(
        system_prompt=system_prompt,
        original_prompt=original_prompt,
        raw_json=raw_json,
        fields=tuple(fields),
    )
    if not protocol_repair_enabled():
        raise AiProtocolContractError(
            AI_PROTOCOL_ENUM_INVALID,
            message=AI_PROTOCOL_ENUM_INVALID,
            violations=violations,
            repair_request=repair_request,
        )
    return repair_once_with_same_model(config=config, repair_request=repair_request)
