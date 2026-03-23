from __future__ import annotations

import base64
from collections import deque
import io
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from PIL import Image, ImageFilter
from openai import OpenAI

from app.core.storage import storage_state, write_json_atomic
from app.core.user_context import get_current_user
from app.models.schemas import (
    AIProvider,
    BuildMediaConfig,
    ChatConfig,
    PortraitAssetRef,
    ProviderBuildMediaConfig,
)
from app.services.ai_adapter import create_gemini_native_client, resolve_base_url


PORTRAIT_WIDTH = 768
PORTRAIT_HEIGHT = 1344
_ASSET_DIR = "build-temp/portrait_assets"
_REVIEW_BG = (245, 245, 245, 255)
_OPENAI_BG_REMOVAL_PROMPT = (
    "Remove the background completely and keep only the main character. "
    "Return a transparent PNG with the full body preserved."
)
_DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
_DEFAULT_GEMINI_SEGMENT_MODEL = "models/gemini-2.5-flash"
_HUMANOID_LABEL_HINTS = ("humanoid", "human", "person", "character", "adventurer", "warrior", "mage")


@dataclass
class EffectiveBuildMediaConfig:
    provider: AIProvider
    api_key: str
    base_url_override: str | None
    generation_model: str
    background_removal_model: str
    vision_model: str


def _user_root() -> Path:
    return storage_state.save_path.parent


def _asset_root() -> Path:
    root = _user_root() / _ASSET_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _asset_json_path(asset_id: str) -> Path:
    return _asset_root() / f"{asset_id}.json"


def _asset_image_path(asset_id: str) -> Path:
    return _asset_root() / f"{asset_id}.png"


def _asset_relative_path(path: Path) -> str:
    return str(path.relative_to(_user_root())).replace("\\", "/")


def _load_image_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _decode_b64(data_base64: str) -> bytes:
    text = str(data_base64 or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    return base64.b64decode(text)


def _normalize_to_portrait_png(raw_bytes: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(raw_bytes)) as source:
        image = source.convert("RGBA")
        if image.size != (PORTRAIT_WIDTH, PORTRAIT_HEIGHT):
            image = image.resize((PORTRAIT_WIDTH, PORTRAIT_HEIGHT))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), image.width, image.height


def _png_has_transparency(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        return False
    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    return bool(extrema and extrema[0] < 255)


def _write_asset(
    image_bytes: bytes,
    *,
    variant_kind: str,
    mime_type: str = "image/png",
    derived_from_asset_id: str | None = None,
    provider: AIProvider | None = None,
    model: str | None = None,
) -> PortraitAssetRef:
    asset_id = f"portrait_{uuid.uuid4().hex}"
    image_path = _asset_image_path(asset_id)
    image_path.write_bytes(image_bytes)
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
    asset = PortraitAssetRef(
        asset_id=asset_id,
        relative_path=_asset_relative_path(image_path),
        mime_type=mime_type,
        width=width,
        height=height,
        variant_kind=variant_kind,  # type: ignore[arg-type]
        derived_from_asset_id=derived_from_asset_id,
        provider=provider,
        model=model,
    )
    write_json_atomic(_asset_json_path(asset_id), asset.model_dump(mode="json"))
    return asset


def load_asset(asset_id: str) -> PortraitAssetRef:
    path = _asset_json_path(asset_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="portrait asset not found")
    return PortraitAssetRef.model_validate(json.loads(path.read_text(encoding="utf-8")))


def resolve_asset_file(asset_id: str) -> Path:
    asset = load_asset(asset_id)
    path = _user_root() / asset.relative_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="portrait asset file missing")
    return path


def duplicate_asset_as_final(asset_id: str) -> PortraitAssetRef:
    source = load_asset(asset_id)
    if source.variant_kind == "final_portrait":
        return source
    if source.variant_kind not in {"uploaded_raw", "generated_raw", "bg_removed"}:
        raise ValueError("only raw or bg_removed assets can be finalized")
    return _write_asset(
        _load_image_bytes(resolve_asset_file(asset_id)),
        variant_kind="final_portrait",
        derived_from_asset_id=asset_id,
        provider=source.provider,
        model=source.model,
    )


def store_uploaded_portrait(data_base64: str, mime_type: str = "image/png") -> PortraitAssetRef:
    raw = _decode_b64(data_base64)
    png_bytes, _, _ = _normalize_to_portrait_png(raw)
    return _write_asset(png_bytes, variant_kind="uploaded_raw", mime_type="image/png")


def _effective_provider(config: ChatConfig) -> AIProvider:
    build_media = config.build_media
    if build_media.mode == "explicit_provider":
        return (build_media.explicit_provider or "openai")  # type: ignore[return-value]
    return config.provider


def _looks_like_gemini_image_model(model: str | None) -> bool:
    text = str(model or "").strip().lower()
    if not text:
        return False
    return "imagen" in text or "flash-image" in text or "pro-image" in text or "image-generation" in text


def _strip_markdown_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _gemini_client(api_key: str, model: str) -> Any:
    return create_gemini_native_client(
        ChatConfig(
            provider="gemini",
            api_key=api_key,
            model=model,
            stream=False,
            gm_prompt="build_media",
        )
    )


def _extract_gemini_image_payloads(response: Any) -> list[bytes]:
    payloads: list[bytes] = []
    candidates = list(getattr(response, "candidates", None) or [])
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in list(getattr(content, "parts", None) or []):
            inline_data = getattr(part, "inline_data", None)
            if inline_data is None:
                continue
            mime_type = str(getattr(inline_data, "mime_type", "") or "").lower()
            if not mime_type.startswith("image/"):
                continue
            raw = getattr(inline_data, "data", b"") or b""
            if isinstance(raw, str):
                try:
                    raw = base64.b64decode(raw)
                except Exception:
                    raw = raw.encode("utf-8")
            payload = bytes(raw)
            if payload:
                payloads.append(payload)
    return payloads


def _coerce_mask_grid(value: Any) -> list[list[int]]:
    if not isinstance(value, list) or not value:
        raise ValueError("background removal returned no mask")
    rows: list[list[int]] = []
    for row in value:
        if not isinstance(row, list) or not row:
            continue
        normalized: list[int] = []
        for cell in row:
            if isinstance(cell, bool):
                normalized.append(255 if cell else 0)
            elif isinstance(cell, (int, float)):
                normalized.append(255 if float(cell) >= 0.5 else 0)
        if normalized:
            rows.append(normalized)
    if not rows:
        raise ValueError("background removal returned no mask")
    return rows


def _mask_non_zero_count(mask_grid: list[list[int]]) -> int:
    return sum(1 for row in mask_grid for cell in row if cell > 0)


def _choose_segmentation_candidate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("background removal could not isolate the main character")
    best: dict[str, Any] | None = None
    best_score = -1.0
    for item in payload:
        if not isinstance(item, dict):
            continue
        box = item.get("box_2d")
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = [int(float(part)) for part in box]
        except (TypeError, ValueError):
            continue
        try:
            mask_grid = _coerce_mask_grid(item.get("mask"))
        except ValueError:
            continue
        non_zero = _mask_non_zero_count(mask_grid)
        if non_zero <= 0:
            continue
        area = max(0, ymax - ymin) * max(0, xmax - xmin)
        label = str(item.get("label", "") or "").strip().lower()
        label_bonus = 1_000_000 if any(hint in label for hint in _HUMANOID_LABEL_HINTS) else 0
        density_bonus = non_zero * 100
        score = float(label_bonus + density_bonus + area)
        if score > best_score:
            best = {**item, "_normalized_mask": mask_grid}
            best_score = score
    if best is None:
        raise ValueError("background removal could not isolate the main character")
    return best


def _build_fullsize_mask(payload: Any, image_size: tuple[int, int]) -> Image.Image:
    candidate = _choose_segmentation_candidate(payload)
    ymin, xmin, ymax, xmax = [int(float(part)) for part in candidate["box_2d"]]
    width, height = image_size
    xmin = max(0, min(width, xmin))
    xmax = max(0, min(width, xmax))
    ymin = max(0, min(height, ymin))
    ymax = max(0, min(height, ymax))
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("background removal returned an invalid mask box")
    grid = candidate.get("_normalized_mask") if isinstance(candidate.get("_normalized_mask"), list) else _coerce_mask_grid(candidate.get("mask"))
    grid_width = max(len(row) for row in grid)
    grid_height = len(grid)
    if grid_width <= 0 or grid_height <= 0:
        raise ValueError("background removal returned no mask")
    flattened = bytearray()
    for row in grid:
        if len(row) < grid_width:
            row = row + [0] * (grid_width - len(row))
        flattened.extend(row[:grid_width])
    tile = Image.frombytes("L", (grid_width, grid_height), bytes(flattened))
    tile = tile.resize((xmax - xmin, ymax - ymin), resample=Image.BILINEAR)
    mask = Image.new("L", (width, height), 0)
    mask.paste(tile, (xmin, ymin))
    return mask


def _build_heuristic_background_mask(image: Image.Image) -> Image.Image:
    preview_width = 96
    preview_height = max(96, round(image.height * preview_width / max(1, image.width)))
    preview = image.convert("RGBA").resize((preview_width, preview_height), resample=Image.BILINEAR)
    patch = max(6, min(preview_width, preview_height) // 8)
    coords: list[tuple[int, int]] = []
    for x0 in (0, preview_width - patch):
        for y0 in (0, preview_height - patch):
            for x in range(x0, x0 + patch):
                for y in range(y0, y0 + patch):
                    coords.append((x, y))
    samples = [preview.getpixel(coord) for coord in coords]
    if not samples:
        raise ValueError("background removal could not estimate the background color")
    bg_r = sum(pixel[0] for pixel in samples) / len(samples)
    bg_g = sum(pixel[1] for pixel in samples) / len(samples)
    bg_b = sum(pixel[2] for pixel in samples) / len(samples)
    deviations = [
        max(abs(pixel[0] - bg_r), abs(pixel[1] - bg_g), abs(pixel[2] - bg_b))
        for pixel in samples
    ]
    noise = sum(deviations) / max(1, len(deviations))
    seed_threshold = max(18.0, noise * 2.0 + 10.0)
    grow_threshold = seed_threshold + 18.0

    def distance(pixel: tuple[int, int, int, int]) -> float:
        return max(abs(pixel[0] - bg_r), abs(pixel[1] - bg_g), abs(pixel[2] - bg_b))

    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()
    for x in range(preview_width):
        for y in (0, preview_height - 1):
            if distance(preview.getpixel((x, y))) <= seed_threshold:
                queue.append((x, y))
    for y in range(preview_height):
        for x in (0, preview_width - 1):
            if distance(preview.getpixel((x, y))) <= seed_threshold:
                queue.append((x, y))

    background = Image.new("L", (preview_width, preview_height), 0)
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        if distance(preview.getpixel((x, y))) > grow_threshold:
            continue
        background.putpixel((x, y), 255)
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < preview_width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < preview_height:
            queue.append((x, y + 1))

    background = background.resize(image.size, resample=Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius=1.5))
    subject = Image.eval(background, lambda value: 255 - value)
    if subject.getbbox() is None:
        raise ValueError("background removal could not isolate the main character")
    return subject


def _remove_background_with_gemini_segmentation(api_key: str, model: str, image_bytes: bytes) -> bytes:
    from google.genai import types as genai_types

    with Image.open(io.BytesIO(image_bytes)) as opened_source:
        source = opened_source.convert("RGBA").copy()
    try:
        client = _gemini_client(api_key, model)
        response = client.models.generate_content(
            model=model,
            contents=[
                (
                    "Return only JSON. Detect the main humanoid character or person in this portrait and return a JSON array. "
                    "Each item must have fields label, box_2d, mask. box_2d must be [ymin, xmin, ymax, xmax] in absolute "
                    "pixel coordinates. mask must be a 64x64 2D array of 0 or 1 values covering the character silhouette "
                    "and excluding the background. Prefer the primary full-body character."
                ),
                source,
            ],
            config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        payload_text = _strip_markdown_json_fence(str(getattr(response, "text", "") or ""))
        if not payload_text:
            raise ValueError("background removal returned no segmentation data")
        payload = json.loads(payload_text)
        mask = _build_fullsize_mask(payload, source.size)
        if mask.getbbox() is None:
            raise ValueError("background removal returned no usable mask")
    except Exception:
        mask = _build_heuristic_background_mask(source)
    result = source.copy()
    result.putalpha(mask)
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def resolve_effective_build_media_config(config: ChatConfig) -> EffectiveBuildMediaConfig:
    build_media = config.build_media if isinstance(config.build_media, BuildMediaConfig) else BuildMediaConfig()
    provider = _effective_provider(config)
    if provider == "deepseek":
        raise ValueError("build media requires explicit provider openai or gemini when chat provider is deepseek")
    provider_cfg = build_media.provider_configs.for_provider(provider)
    api_key = (provider_cfg.api_key or config.api_key or "").strip()
    if provider == "gemini":
        configured_generation = str(provider_cfg.generation_model or "").strip()
        configured_background = str(provider_cfg.background_removal_model or "").strip()
        configured_vision = str(provider_cfg.vision_model or "").strip()
        chat_model = str(config.model or "").strip()
        generation_model = configured_generation or (chat_model if _looks_like_gemini_image_model(chat_model) else _DEFAULT_GEMINI_IMAGE_MODEL)
        background_model = configured_background or configured_vision or _DEFAULT_GEMINI_SEGMENT_MODEL
        vision_model = configured_vision or chat_model or _DEFAULT_GEMINI_SEGMENT_MODEL
    else:
        generation_model = (provider_cfg.generation_model or provider_cfg.background_removal_model or provider_cfg.vision_model or config.model or "").strip()
        background_model = (provider_cfg.background_removal_model or generation_model).strip()
        vision_model = (provider_cfg.vision_model or generation_model).strip()
    if not api_key or not generation_model:
        raise ValueError(f"build media provider '{provider}' is not configured")
    return EffectiveBuildMediaConfig(
        provider=provider,
        api_key=api_key,
        base_url_override=provider_cfg.base_url_override,
        generation_model=generation_model,
        background_removal_model=background_model,
        vision_model=vision_model,
    )


def build_media_capabilities(config: ChatConfig) -> dict[str, Any]:
    try:
        effective = resolve_effective_build_media_config(config)
        return {
            "active_provider": effective.provider,
            "supports_generation": effective.provider in {"openai", "gemini"},
            "supports_background_removal": effective.provider in {"openai", "gemini"},
            "supports_vision": effective.provider in {"openai", "gemini"},
            "requires_explicit_provider": config.provider == "deepseek",
            "detail": "",
        }
    except Exception as exc:
        return {
            "active_provider": None,
            "supports_generation": False,
            "supports_background_removal": False,
            "supports_vision": False,
            "requires_explicit_provider": config.provider == "deepseek",
            "detail": str(exc),
        }


def _openai_client(config: EffectiveBuildMediaConfig) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": config.api_key}
    base_url = resolve_base_url(config.provider, config.base_url_override)
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def generate_portrait_assets(
    config: ChatConfig,
    *,
    prompt: str,
    reference_asset_id: str | None = None,
) -> tuple[list[PortraitAssetRef], str, str]:
    effective = resolve_effective_build_media_config(config)
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise ValueError("portrait prompt is required")
    if effective.provider == "openai":
        client = _openai_client(effective)
        if reference_asset_id:
            image_path = resolve_asset_file(reference_asset_id)
            with image_path.open("rb") as handle:
                response = client.images.edit(
                    image=handle,
                    prompt=prompt_text,
                    background="transparent",
                    model=effective.generation_model,
                    output_format="png",
                    response_format="b64_json",
                    size="1024x1536",
                )
        else:
            response = client.images.generate(
                prompt=prompt_text,
                background="transparent",
                model=effective.generation_model,
                output_format="png",
                response_format="b64_json",
                size="1024x1536",
            )
        assets: list[PortraitAssetRef] = []
        for item in list(getattr(response, "data", None) or []):
            raw = base64.b64decode(str(getattr(item, "b64_json", "") or ""))
            png_bytes, _, _ = _normalize_to_portrait_png(raw)
            assets.append(
                _write_asset(
                    png_bytes,
                    variant_kind="generated_raw",
                    provider=effective.provider,
                    model=effective.generation_model,
                    derived_from_asset_id=reference_asset_id,
                )
            )
        return assets, effective.provider, effective.generation_model

    from google.genai import types as genai_types

    client = _gemini_client(effective.api_key, effective.generation_model)
    contents: list[Any] = [prompt_text]
    if reference_asset_id:
        reference_bytes = resolve_asset_file(reference_asset_id).read_bytes()
        with Image.open(io.BytesIO(reference_bytes)) as opened_reference:
            contents.append(opened_reference.convert("RGBA").copy())
    response = client.models.generate_content(
        model=effective.generation_model,
        contents=contents,
        config=genai_types.GenerateContentConfig(response_modalities=[genai_types.Modality.IMAGE]),
    )

    assets = []
    for raw in _extract_gemini_image_payloads(response):
        png_bytes, _, _ = _normalize_to_portrait_png(raw)
        assets.append(
            _write_asset(
                png_bytes,
                variant_kind="generated_raw",
                provider=effective.provider,
                model=effective.generation_model,
                derived_from_asset_id=reference_asset_id,
            )
        )
    return assets, effective.provider, effective.generation_model


def remove_portrait_background(config: ChatConfig, raw_asset_id: str) -> PortraitAssetRef:
    effective = resolve_effective_build_media_config(config)
    asset = load_asset(raw_asset_id)
    if asset.variant_kind not in {"uploaded_raw", "generated_raw", "bg_removed"}:
        raise ValueError("raw portrait asset is required")
    image_path = resolve_asset_file(raw_asset_id)
    image_bytes = image_path.read_bytes()
    with Image.open(io.BytesIO(image_bytes)) as source:
        rgba = source.convert("RGBA")
        if _png_has_transparency(rgba):
            buffer = io.BytesIO()
            rgba.save(buffer, format="PNG")
            return _write_asset(
                buffer.getvalue(),
                variant_kind="bg_removed",
                derived_from_asset_id=raw_asset_id,
                provider=effective.provider,
                model=effective.background_removal_model,
            )

    if effective.provider == "openai":
        client = _openai_client(effective)
        with image_path.open("rb") as handle:
            response = client.images.edit(
                image=handle,
                prompt=_OPENAI_BG_REMOVAL_PROMPT,
                background="transparent",
                model=effective.background_removal_model,
                output_format="png",
                response_format="b64_json",
                size="1024x1536",
            )
        item = next(iter(list(getattr(response, "data", None) or [])), None)
        if item is None:
            raise ValueError("background removal returned no image")
        raw = base64.b64decode(str(getattr(item, "b64_json", "") or ""))
        png_bytes, _, _ = _normalize_to_portrait_png(raw)
        return _write_asset(
            png_bytes,
            variant_kind="bg_removed",
            derived_from_asset_id=raw_asset_id,
            provider=effective.provider,
            model=effective.background_removal_model,
        )

    png_bytes = _remove_background_with_gemini_segmentation(
        effective.api_key,
        effective.background_removal_model,
        image_bytes,
    )
    png_bytes, _, _ = _normalize_to_portrait_png(png_bytes)
    return _write_asset(
        png_bytes,
        variant_kind="bg_removed",
        derived_from_asset_id=raw_asset_id,
        provider=effective.provider,
        model=effective.background_removal_model,
    )


def describe_portrait(config: ChatConfig, asset_id: str, basic_info_summary: str = "") -> tuple[str, str, str]:
    effective = resolve_effective_build_media_config(config)
    asset = load_asset(asset_id)
    if asset.variant_kind not in {"bg_removed", "final_portrait"}:
        raise ValueError("portrait must be confirmed before description")
    image_bytes = resolve_asset_file(asset_id).read_bytes()
    prompt = (
        "Describe this RPG character's visible appearance in concise Chinese. "
        "Focus only on the person, outfit, posture, hair, eyes, body type, age impression, and carried gear. "
        "Do not mention background. Keep it under 120 Chinese characters."
    )
    if basic_info_summary.strip():
        prompt += f" Known info: {basic_info_summary.strip()}."

    if effective.provider == "openai":
        client = _openai_client(effective)
        data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        response = client.responses.create(
            model=effective.vision_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", None)
        if not text:
            outputs = list(getattr(response, "output", None) or [])
            parts: list[str] = []
            for output in outputs:
                for item in list(getattr(output, "content", None) or []):
                    value = getattr(item, "text", None)
                    if value:
                        parts.append(str(value))
            text = "".join(parts)
        return str(text or "").strip(), effective.provider, effective.vision_model

    client = _gemini_client(effective.api_key, effective.vision_model)
    with Image.open(io.BytesIO(image_bytes)) as opened_image:
        image = opened_image.convert("RGBA").copy()
    response = client.models.generate_content(
        model=effective.vision_model,
        contents=[
            prompt,
            image,
        ],
    )
    text = str(getattr(response, "text", "") or "").strip()
    return text, effective.provider, effective.vision_model


def copy_asset_to_path(asset_id: str, target_path: Path) -> PortraitAssetRef:
    source = load_asset(asset_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolve_asset_file(asset_id), target_path)
    archived = PortraitAssetRef(
        asset_id=f"portrait_{uuid.uuid4().hex}",
        relative_path=_asset_relative_path(target_path),
        mime_type=source.mime_type,
        width=source.width,
        height=source.height,
        variant_kind=source.variant_kind,
        derived_from_asset_id=source.asset_id,
        provider=source.provider,
        model=source.model,
    )
    write_json_atomic(_asset_json_path(archived.asset_id), archived.model_dump(mode="json"))
    return archived
