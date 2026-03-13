from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,32}$")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def data_dir() -> Path:
    return _repo_root() / "data"


def auth_dir() -> Path:
    return data_dir() / "auth"


def users_db_path() -> Path:
    return auth_dir() / "users.json"


def get_auth_secret() -> str:
    # MUST be stable across restarts for cookie validation.
    secret = (os.getenv("GRW_AUTH_SECRET") or "").strip()
    if secret:
        return secret
    # fallback: persisted local secret
    path = auth_dir() / "secret.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    # generate random
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
    path.write_text(raw, encoding="utf-8")
    return raw


def serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_auth_secret(), salt="gptroleplayweb.session")


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not _USERNAME_RE.match(name):
        raise ValueError("用户名需为 3-32 位，仅允许字母数字/下划线/短横线")
    return name


def load_users() -> dict[str, Any]:
    path = users_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {"users": {}}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def save_users(payload: dict[str, Any]) -> None:
    from app.core.storage import write_json_atomic

    write_json_atomic(users_db_path(), payload)


def register_user(username: str, password: str) -> None:
    username = validate_username(username)
    password = (password or "").strip()
    if len(password) < 6:
        raise ValueError("密码至少 6 位")

    db = load_users()
    users = db.setdefault("users", {})
    if username in users:
        raise ValueError("用户名已存在")

    users[username] = {
        "password_hash": pwd_context.hash(password),
        "created_at": int(time.time()),
    }
    save_users(db)


def verify_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    password = (password or "").strip()
    db = load_users()
    user = (db.get("users") or {}).get(username)
    if not isinstance(user, dict):
        return False
    ph = str(user.get("password_hash") or "")
    if not ph:
        return False
    try:
        return pwd_context.verify(password, ph)
    except Exception:
        return False


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
    u = str(data.get("u") or "").strip()
    try:
        u = validate_username(u)
    except ValueError:
        return None
    return SessionInfo(username=u)
