from __future__ import annotations

import csv
from pathlib import Path
from string import Template


class _PromptTable:
    def __init__(self) -> None:
        this_file = Path(__file__).resolve()
        self._backend_root = this_file.parents[2]
        self._repo_root = this_file.parents[3]
        self._paths = [
            self._repo_root / "data" / "ai-prompts.csv",
            self._backend_root / "data" / "ai-prompts.csv",
        ]
        self._mtime_ns: int | None = None
        self._active_path: Path | None = None
        self._items: dict[str, str] = {}

    def _resolve_path(self) -> Path | None:
        for path in self._paths:
            if path.exists() and path.is_file():
                return path
        return None

    def _load_if_needed(self) -> None:
        path = self._resolve_path()
        if path is None:
            self._active_path = None
            self._mtime_ns = None
            self._items = {}
            return
        stat = path.stat()
        if self._active_path == path and self._mtime_ns == stat.st_mtime_ns:
            return
        items: dict[str, str] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = str((row or {}).get("key") or "").strip()
                if not key:
                    continue
                text = str((row or {}).get("prompt_template") or "")
                items[key] = text.replace("\\n", "\n")
        self._active_path = path
        self._mtime_ns = stat.st_mtime_ns
        self._items = items

    def get_text(self, key: str, default_text: str) -> str:
        self._load_if_needed()
        return self._items.get(key, default_text)

    def has_key(self, key: str) -> bool:
        self._load_if_needed()
        return key in self._items

    def require_keys(self, keys: list[str] | tuple[str, ...]) -> list[str]:
        self._load_if_needed()
        return [key for key in keys if key not in self._items]

    def render(self, key: str, default_template: str, **kwargs: object) -> str:
        tpl = self.get_text(key, default_template)
        safe_vars = {k: str(v) for k, v in kwargs.items()}
        return Template(tpl).safe_substitute(safe_vars)


prompt_table = _PromptTable()
