from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from app.models.schemas import PathStatusResponse


@dataclass
class StoragePaths:
    config_path: Path
    save_path: Path


class StorageState:
    def __init__(self) -> None:
        self._app_root = Path(__file__).resolve().parents[2]
        self._data_dir = self._app_root / "data"
        self._state_path = self._data_dir / "storage" / "paths.json"
        self._default_config = self._data_dir / "config" / "config.json"
        self._default_save = self._data_dir / "saves" / "current-save.json"
        self._paths = self._load_or_init()

    def _load_or_init(self) -> StoragePaths:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._default_config.parent.mkdir(parents=True, exist_ok=True)
        self._default_save.parent.mkdir(parents=True, exist_ok=True)

        if not self._state_path.exists():
            paths = StoragePaths(config_path=self._default_config, save_path=self._default_save)
            self._persist(paths)
            return paths

        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        return StoragePaths(config_path=Path(data["config_path"]), save_path=Path(data["save_path"]))

    def _persist(self, paths: StoragePaths) -> None:
        self._state_path.write_text(
            json.dumps(
                {
                    "config_path": str(paths.config_path),
                    "save_path": str(paths.save_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @property
    def config_path(self) -> Path:
        return self._paths.config_path

    @property
    def save_path(self) -> Path:
        return self._paths.save_path

    def set_config_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if path.exists() and path.is_dir():
            path = path / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.config_path = path
        self._persist(self._paths)
        return path

    def set_save_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if path.exists() and path.is_dir():
            path = path / "current-save.json"
        elif not path.suffix:
            path = path / "current-save.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.save_path = path
        self._persist(self._paths)
        return path

    @staticmethod
    def path_status(path: Path) -> PathStatusResponse:
        exists = path.exists()
        writable = path.parent.exists()
        if exists:
            writable = path.is_file() or path.is_dir()
        return PathStatusResponse(path=str(path), exists=exists, writable=writable)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_SAVE_BUNDLE_FORMAT = "save_bundle_v1"


def _save_bundle_dir(save_path: Path) -> Path:
    if save_path.suffix:
        return save_path.with_suffix(save_path.suffix + ".bundle")
    return save_path.parent / f"{save_path.name}.bundle"


def _json_hash(payload: Any) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_bundle_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    data = read_json(manifest_path)
    if data.get("format") != _SAVE_BUNDLE_FORMAT:
        return None
    return data


def _assemble_bundle(bundle_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    parts = manifest.get("parts", {})
    if not isinstance(parts, dict):
        raise ValueError("invalid save bundle parts")

    def _read_part(name: str, default: Any | None = None) -> Any:
        rel = parts.get(name)
        if not isinstance(rel, str):
            if default is not None:
                return default
            raise ValueError(f"missing save bundle part: {name}")
        return read_json(bundle_dir / rel)

    meta = _read_part("meta")
    map_snapshot = _read_part("map_snapshot")
    area_snapshot = _read_part("area_snapshot")
    player_data = _read_part("player_data")
    game_logs = _read_part("game_logs")
    role_pool = _read_part("role_pool", {"items": []})

    return {
        "version": meta.get("version", "1.1.0"),
        "session_id": meta.get("session_id", "sess_default"),
        "updated_at": meta.get("updated_at"),
        "game_log_settings": meta.get("game_log_settings", {}),
        "map_snapshot": map_snapshot,
        "area_snapshot": area_snapshot,
        "player_static_data": player_data.get("player_static_data", {}),
        "player_runtime_data": player_data.get("player_runtime_data", {}),
        "game_logs": game_logs.get("items", []),
        "role_pool": role_pool.get("items", []),
    }


def read_save_payload(save_path: Path) -> dict[str, Any] | None:
    bundle_dir = _save_bundle_dir(save_path)
    manifest = _load_bundle_manifest(bundle_dir)
    if manifest is not None:
        return _assemble_bundle(bundle_dir, manifest)

    if not save_path.exists() or not save_path.is_file():
        return None

    raw = read_json(save_path)
    if raw.get("format") == _SAVE_BUNDLE_FORMAT:
        pointer_bundle = raw.get("bundle_dir")
        if isinstance(pointer_bundle, str):
            pointed = Path(pointer_bundle)
            if not pointed.is_absolute():
                pointed = save_path.parent / pointed
            pointer_manifest = _load_bundle_manifest(pointed)
            if pointer_manifest is not None:
                return _assemble_bundle(pointed, pointer_manifest)
    return raw


def write_save_payload(save_path: Path, payload: dict[str, Any]) -> None:
    bundle_dir = _save_bundle_dir(save_path)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    parts: dict[str, tuple[str, Any]] = {
        "meta": (
            "meta.json",
            {
                "version": payload.get("version", "1.1.0"),
                "session_id": payload.get("session_id", "sess_default"),
                "updated_at": payload.get("updated_at"),
                "game_log_settings": payload.get("game_log_settings", {}),
            },
        ),
        "map_snapshot": ("map_snapshot.json", payload.get("map_snapshot", {})),
        "area_snapshot": ("area_snapshot.json", payload.get("area_snapshot", {})),
        "player_data": (
            "player_data.json",
            {
                "player_static_data": payload.get("player_static_data", {}),
                "player_runtime_data": payload.get("player_runtime_data", {}),
            },
        ),
        "game_logs": ("game_logs.json", {"items": payload.get("game_logs", [])}),
        "role_pool": ("role_pool.json", {"items": payload.get("role_pool", [])}),
    }

    old_manifest = _load_bundle_manifest(bundle_dir) or {}
    old_hashes = old_manifest.get("hashes", {}) if isinstance(old_manifest.get("hashes"), dict) else {}

    new_hashes: dict[str, str] = {}
    part_map: dict[str, str] = {}
    for name, (rel_path, body) in parts.items():
        part_map[name] = rel_path
        part_path = bundle_dir / rel_path
        digest = _json_hash(body)
        new_hashes[name] = digest
        if old_hashes.get(name) == digest and part_path.exists():
            continue
        write_json_atomic(part_path, body)

    manifest = {
        "format": _SAVE_BUNDLE_FORMAT,
        "version": 1,
        "updated_at": payload.get("updated_at"),
        "parts": part_map,
        "hashes": new_hashes,
    }
    write_json_atomic(bundle_dir / "manifest.json", manifest)

    pointer = {
        "format": _SAVE_BUNDLE_FORMAT,
        "version": 1,
        "bundle_dir": bundle_dir.name,
        "session_id": payload.get("session_id", "sess_default"),
        "updated_at": payload.get("updated_at"),
    }
    write_json_atomic(save_path, pointer)


storage_state = StorageState()
