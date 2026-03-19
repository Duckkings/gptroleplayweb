from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer

try:
    from passlib.context import CryptContext
except Exception:
    _legacy_pwd_context = None
else:
    _legacy_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,32}$")
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_PASSWORD_SALT_BYTES = 16


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    return _repo_root() / "data"


def _legacy_data_dirs() -> list[Path]:
    this_file = Path(__file__).resolve()
    current = data_dir()
    candidates = [
        this_file.parents[2] / "data",
    ]
    paths: list[Path] = []
    for candidate in candidates:
        if candidate != current and candidate not in paths:
            paths.append(candidate)
    return paths


def auth_dir() -> Path:
    return data_dir() / "auth"


def _legacy_auth_dirs() -> list[Path]:
    return [path / "auth" for path in _legacy_data_dirs()]


def users_db_path() -> Path:
    return auth_dir() / "users.json"


def _existing_auth_file(name: str) -> Path:
    current = auth_dir() / name
    if current.exists():
        return current
    for legacy_dir in _legacy_auth_dirs():
        candidate = legacy_dir / name
        if candidate.exists():
            return candidate
    return current


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _hash_password(password: str) -> str:
    salt = os.urandom(_PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def _verify_pbkdf2_password(password: str, password_hash: str) -> bool:
    prefix = f"{_PASSWORD_SCHEME}$"
    if not password_hash.startswith(prefix):
        return False
    try:
        _, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _verify_legacy_password(password: str, password_hash: str) -> bool:
    if _legacy_pwd_context is None:
        return False
    try:
        return _legacy_pwd_context.verify(password, password_hash)
    except Exception:
        return False


def _load_users_with_source() -> tuple[dict[str, Any], Path]:
    current_path = users_db_path()
    current_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = _existing_auth_file("users.json")
    if not source_path.exists():
        return {"users": {}}, current_path

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid users db")

    if source_path != current_path:
        from app.core.storage import write_json_atomic

        write_json_atomic(current_path, payload)
    return payload, current_path


def get_auth_secret() -> str:
    secret = (os.getenv("GRW_AUTH_SECRET") or "").strip()
    if secret:
        return secret

    path = auth_dir() / "secret.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    legacy_path = _existing_auth_file("secret.txt")
    if legacy_path != path and legacy_path.exists():
        raw = legacy_path.read_text(encoding="utf-8").strip()
        path.write_text(raw, encoding="utf-8")
        return raw

    raw = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
    path.write_text(raw, encoding="utf-8")
    return raw


def serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_auth_secret(), salt="gptroleplayweb.session")


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not _USERNAME_RE.match(name):
        raise ValueError("username must be 3-32 chars and use only letters, digits, '_' or '-'")
    return name


def load_users() -> dict[str, Any]:
    payload, _ = _load_users_with_source()
    return payload


def save_users(payload: dict[str, Any]) -> None:
    from app.core.storage import write_json_atomic

    write_json_atomic(users_db_path(), payload)


def register_user(username: str, password: str) -> None:
    username = validate_username(username)
    password = (password or "").strip()
    if len(password) < 6:
        raise ValueError("password must be at least 6 chars")

    db, _ = _load_users_with_source()
    users = db.setdefault("users", {})
    if username in users:
        raise ValueError("username already exists")

    users[username] = {
        "password_hash": _hash_password(password),
        "created_at": int(time.time()),
    }
    save_users(db)


def reset_user_password(username: str, current_password: str, new_password: str) -> None:
    username = validate_username(username)
    current_password = (current_password or "").strip()
    new_password = (new_password or "").strip()
    if len(new_password) < 6:
        raise ValueError("new password must be at least 6 chars")
    if current_password == new_password:
        raise ValueError("new password must be different from current password")

    db, _ = _load_users_with_source()
    user = (db.get("users") or {}).get(username)
    if not isinstance(user, dict):
        raise ValueError("invalid username or current password")

    password_hash = str(user.get("password_hash") or "")
    if not password_hash:
        raise ValueError("invalid username or current password")

    verified = _verify_pbkdf2_password(current_password, password_hash) or _verify_legacy_password(current_password, password_hash)
    if not verified:
        raise ValueError("invalid username or current password")

    user["password_hash"] = _hash_password(new_password)
    user["updated_at"] = int(time.time())
    save_users(db)


def verify_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    password = (password or "").strip()
    db, _ = _load_users_with_source()
    user = (db.get("users") or {}).get(username)
    if not isinstance(user, dict):
        return False

    password_hash = str(user.get("password_hash") or "")
    if not password_hash:
        return False

    if _verify_pbkdf2_password(password, password_hash):
        return True
    if not _verify_legacy_password(password, password_hash):
        return False

    user["password_hash"] = _hash_password(password)
    try:
        save_users(db)
    except Exception:
        pass
    return True


SESSION_COOKIE = "grw_session"


@dataclass(frozen=True)
class SessionInfo:
    username: str


def sign_session(username: str) -> str:
    username = validate_username(username)
    return serializer().dumps({"u": username})


def load_session(token: str) -> SessionInfo | None:
    raw = (token or "").strip()
    if not raw:
        return None
    try:
        data = serializer().loads(raw)
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    username = str(data.get("u") or "").strip()
    try:
        username = validate_username(username)
    except ValueError:
        return None
    return SessionInfo(username=username)
