from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI, OpenAI

from app.models.schemas import ChatConfig, ModelCapabilityInfo

DEFAULT_BASE_URLS = {
    "openai": None,
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

PROFILE_DEFAULTS: dict[str, dict[str, int | float | bool | str]] = {
    "openai_gpt5": {"temperature": 0.8, "max_completion_tokens": 1200},
    "openai_standard": {"temperature": 0.8, "max_tokens": 1200},
    "deepseek_chat": {"temperature": 0.8, "max_tokens": 1200},
    "deepseek_reasoner": {"max_tokens": 1200},
    "gemini_openai_compatible": {},
    "generic_compatible": {"temperature": 0.8, "max_tokens": 1200},
}

PROFILE_PARAMS: dict[str, list[str]] = {
    "openai_gpt5": ["temperature", "max_completion_tokens"],
    "openai_standard": ["temperature", "max_tokens"],
    "deepseek_chat": ["temperature", "max_tokens"],
    "deepseek_reasoner": ["max_tokens"],
    "gemini_openai_compatible": [],
    "generic_compatible": ["temperature", "max_tokens"],
}


@dataclass(frozen=True)
class ResolvedModelProfile:
    model_id: str
    label: str
    capability_profile: str
    supported_params: list[str]
    defaults: dict[str, int | float | bool | str]
    warning: str | None = None

    def to_schema(self) -> ModelCapabilityInfo:
        return ModelCapabilityInfo(
            id=self.model_id,
            label=self.label,
            capability_profile=self.capability_profile,  # type: ignore[arg-type]
            supported_params=self.supported_params,  # type: ignore[arg-type]
            defaults=self.defaults,
            warning=self.warning,
        )


def resolve_base_url(provider: str, base_url_override: str | None = None) -> str | None:
    override = (base_url_override or "").strip()
    if override:
        return override
    return DEFAULT_BASE_URLS.get(provider)


def resolve_capability_profile(provider: str, model: str) -> str:
    model_id = (model or "").strip().lower()
    if provider == "openai":
        if model_id.startswith("gpt-5"):
            return "openai_gpt5"
        if model_id.startswith(("gpt-", "o1", "o3", "o4")):
            return "openai_standard"
        return "generic_compatible"
    if provider == "deepseek":
        if "reasoner" in model_id:
            return "deepseek_reasoner"
        if "deepseek" in model_id:
            return "deepseek_chat"
        return "generic_compatible"
    if provider == "gemini":
        return "gemini_openai_compatible"
    return "generic_compatible"


def resolve_model_profile(provider: str, model: str) -> ResolvedModelProfile:
    profile = resolve_capability_profile(provider, model)
    model_id = (model or "").strip() or "custom-model"
    warning = None
    if profile == "generic_compatible":
        warning = "Unrecognized model; using generic-compatible parameters."
    elif profile == "gemini_openai_compatible":
        warning = "Gemini uses the OpenAI-compatible endpoint; runtime params are omitted for compatibility."
    return ResolvedModelProfile(
        model_id=model_id,
        label=model_id,
        capability_profile=profile,
        supported_params=list(PROFILE_PARAMS[profile]),
        defaults=dict(PROFILE_DEFAULTS[profile]),
        warning=warning,
    )


def has_ai_config(config: ChatConfig | None) -> bool:
    if config is None:
        return False
    return bool((config.api_key or "").strip() and (config.model or "").strip())


def create_sync_client(config: ChatConfig, client_cls: type[OpenAI] = OpenAI) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": config.api_key}
    base_url = resolve_base_url(config.provider, config.base_url_override)
    if base_url:
        kwargs["base_url"] = base_url
    return client_cls(**kwargs)


def create_async_client(config: ChatConfig, client_cls: type[AsyncOpenAI] = AsyncOpenAI) -> AsyncOpenAI:
    kwargs: dict[str, Any] = {"api_key": config.api_key}
    base_url = resolve_base_url(config.provider, config.base_url_override)
    if base_url:
        kwargs["base_url"] = base_url
    return client_cls(**kwargs)


def build_completion_options(config: ChatConfig) -> dict[str, Any]:
    profile = resolve_model_profile(config.provider, config.model)
    options: dict[str, Any] = {}
    if "temperature" in profile.supported_params:
        value = config.runtime.temperature
        if value is None:
            value = float(profile.defaults["temperature"])
        options["temperature"] = min(max(value, 0), 2)
    if "max_tokens" in profile.supported_params:
        value = config.runtime.max_tokens
        if value is None:
            default_value = profile.defaults.get("max_tokens", 1200)
            value = int(default_value) if isinstance(default_value, (int, float)) else 1200
        options["max_tokens"] = max(1, int(value))
    if "max_completion_tokens" in profile.supported_params:
        value = config.runtime.max_completion_tokens
        if value is None:
            value = config.runtime.max_tokens
        if value is None:
            default_value = profile.defaults.get("max_completion_tokens", 1200)
            value = int(default_value) if isinstance(default_value, (int, float)) else 1200
        options["max_completion_tokens"] = max(1, int(value))
    return options


def discover_models(provider: str, api_key: str, base_url_override: str | None = None) -> list[ModelCapabilityInfo]:
    kwargs: dict[str, Any] = {"api_key": api_key}
    base_url = resolve_base_url(provider, base_url_override)
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    result = client.models.list()
    data = getattr(result, "data", result)
    items: list[ModelCapabilityInfo] = []
    for item in data:
        model_id = str(getattr(item, "id", "") or "").strip()
        if not model_id:
            continue
        items.append(resolve_model_profile(provider, model_id).to_schema())
    items.sort(key=lambda item: item.id.lower())
    return items
