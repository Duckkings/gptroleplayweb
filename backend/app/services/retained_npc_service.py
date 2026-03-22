from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.storage import storage_state, write_json_atomic
from app.core.user_context import get_current_user
from app.models.schemas import NpcRoleCard


@dataclass
class RetainedNpc:
    """A retained NPC that can be reused across sessions."""

    retained_id: str
    name: str
    role_data: dict[str, Any]
    retained_at: str
    notes: str = ""
    archive_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "retained_id": self.retained_id,
            "name": self.name,
            "role_data": self.role_data,
            "retained_at": self.retained_at,
            "notes": self.notes,
            "archive_dir": self.archive_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetainedNpc":
        return cls(
            retained_id=data["retained_id"],
            name=data["name"],
            role_data=data["role_data"],
            retained_at=data["retained_at"],
            notes=data.get("notes", ""),
            archive_dir=data.get("archive_dir"),
        )


class RetainedNpcService:
    """Service for managing retained NPCs per user account.
    
    Each NPC is stored as a separate JSON file in the roles/ directory,
    with the filename based on the character name to prevent JSON bloat.
    """

    _ROLES_DIR = "roles"

    def __init__(self) -> None:
        self._cache: dict[str, list[RetainedNpc]] = {}

    def _get_roles_dir(self, username: str | None = None) -> Path:
        """Get the roles directory for storing individual NPC files."""
        user = username or get_current_user()
        if user:
            user_root = storage_state.save_path.parent
        else:
            user_root = storage_state.save_path.parent
        roles_dir = user_root / self._ROLES_DIR
        roles_dir.mkdir(parents=True, exist_ok=True)
        return roles_dir

    def _get_role_filename(self, name: str) -> str:
        """Generate a safe filename from the role name."""
        # Remove or replace unsafe characters for filenames
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        return f"{safe_name}.json"

    def _get_role_path(self, name: str, username: str | None = None) -> Path:
        """Get the path for a specific role file."""
        return self._get_roles_dir(username) / self._get_role_filename(name)

    def _load_data(self, username: str | None = None) -> list[RetainedNpc]:
        """Load retained NPCs from individual files in the roles directory."""
        cache_key = username or get_current_user() or "_default"
        if cache_key in self._cache:
            return self._cache[cache_key]

        roles_dir = self._get_roles_dir(username)
        npcs: list[RetainedNpc] = []

        if not roles_dir.exists():
            self._cache[cache_key] = npcs
            return npcs

        for file_path in roles_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                npc = RetainedNpc.from_dict(data)
                npcs.append(npc)
            except Exception:
                # Skip corrupted files
                continue

        self._cache[cache_key] = npcs
        return npcs

    def _save_role_file(self, npc: RetainedNpc, username: str | None = None) -> None:
        """Save a single retained NPC to its own file."""
        path = self._get_role_path(npc.name, username)
        # If file exists with same name but different ID, add timestamp to filename
        if path.exists():
            import time
            timestamp = int(time.time())
            base_name = path.stem
            path = path.with_name(f"{base_name}_{timestamp}.json")
        write_json_atomic(path, npc.to_dict())

    def get_all(self, username: str | None = None) -> list[RetainedNpc]:
        """Get all retained NPCs for a user."""
        return self._load_data(username)

    def get_by_id(self, retained_id: str, username: str | None = None) -> RetainedNpc | None:
        """Get a specific retained NPC by ID."""
        npcs = self._load_data(username)
        return next((npc for npc in npcs if npc.retained_id == retained_id), None)

    def retain_npc(
        self,
        role: NpcRoleCard,
        notes: str = "",
        username: str | None = None,
    ) -> RetainedNpc:
        """Retain an NPC for future use."""
        from datetime import datetime, timezone

        # Generate a unique ID
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        retained_id = f"retained_{timestamp}"

        # Create the retained NPC record
        retained = RetainedNpc(
            retained_id=retained_id,
            name=role.name,
            role_data=role.model_dump(mode="json"),
            retained_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )

        # Save to individual file
        self._save_role_file(retained, username)

        # Update cache
        cache_key = username or get_current_user() or "_default"
        if cache_key in self._cache:
            # Remove existing entry with same name if exists
            self._cache[cache_key] = [npc for npc in self._cache[cache_key] if npc.name != role.name]
            self._cache[cache_key].append(retained)
        else:
            self._cache[cache_key] = [retained]

        return retained

    def delete_retained(self, retained_id: str, username: str | None = None) -> bool:
        """Delete a retained NPC by removing its file."""
        npcs = self._load_data(username)
        npc_to_delete = next((npc for npc in npcs if npc.retained_id == retained_id), None)

        if npc_to_delete is None:
            return False

        # Remove the file
        path = self._get_role_path(npc_to_delete.name, username)
        # Check for alternative filenames with timestamp
        if not path.exists():
            roles_dir = self._get_roles_dir(username)
            for file_path in roles_dir.glob(f"{path.stem}_*.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    if data.get("retained_id") == retained_id:
                        file_path.unlink()
                        break
                except Exception:
                    continue
        else:
            try:
                path.unlink()
            except Exception:
                pass

        # Update cache
        cache_key = username or get_current_user() or "_default"
        if cache_key in self._cache:
            self._cache[cache_key] = [npc for npc in self._cache[cache_key] if npc.retained_id != retained_id]

        return True

    def update_notes(
        self,
        retained_id: str,
        notes: str,
        username: str | None = None,
    ) -> RetainedNpc | None:
        """Update notes for a retained NPC."""
        npcs = self._load_data(username)
        for npc in npcs:
            if npc.retained_id == retained_id:
                npc.notes = notes
                # Re-save the file
                self._save_role_file(npc, username)
                return npc
        return None

    def update_role_data(
        self,
        retained_id: str,
        role_data: dict[str, Any],
        *,
        archive_dir: str | None = None,
        username: str | None = None,
    ) -> RetainedNpc | None:
        """Update role data for a retained NPC without changing its ID."""
        npcs = self._load_data(username)
        for npc in npcs:
            if npc.retained_id != retained_id:
                continue
            npc.role_data = role_data
            if archive_dir is not None:
                npc.archive_dir = archive_dir
            self._save_role_file(npc, username)
            return npc
        return None


# Global service instance
retained_npc_service = RetainedNpcService()
