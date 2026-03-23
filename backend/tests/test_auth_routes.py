import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_routes import router as auth_router
from app.core import auth as auth_core


class AuthRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self._data_root = self._root / "data"
        self._data_dir_patcher = patch("app.core.auth.data_dir", return_value=self._data_root)
        self._data_dir_patcher.start()
        app = FastAPI()
        app.include_router(auth_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._data_dir_patcher.stop()
        self._tmpdir.cleanup()

    def test_register_login_and_me_round_trip(self) -> None:
        register_response = self.client.post(
            "/api/v1/auth/register",
            json={"username": "blazer", "password": "123456"},
        )
        self.assertEqual(register_response.status_code, 200, register_response.text)

        users_path = self._data_root / "auth" / "users.json"
        self.assertTrue(users_path.exists())
        users_payload = json.loads(users_path.read_text(encoding="utf-8"))
        self.assertTrue(users_payload["users"]["blazer"]["password_hash"].startswith("pbkdf2_sha256$"))

        login_response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "blazer", "password": "123456"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        self.assertIn("grw_session=", login_response.headers.get("set-cookie", ""))

        me_response = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_response.status_code, 200, me_response.text)
        self.assertEqual(me_response.json()["username"], "blazer")

    def test_register_returns_400_for_duplicate_username(self) -> None:
        first = self.client.post(
            "/api/v1/auth/register",
            json={"username": "blazer", "password": "123456"},
        )
        second = self.client.post(
            "/api/v1/auth/register",
            json={"username": "blazer", "password": "123456"},
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 400, second.text)
        self.assertEqual(second.json()["detail"], "username already exists")

    def test_reset_password_updates_credentials(self) -> None:
        register_response = self.client.post(
            "/api/v1/auth/register",
            json={"username": "blazer", "password": "123456"},
        )
        self.assertEqual(register_response.status_code, 200, register_response.text)

        reset_response = self.client.post(
            "/api/v1/auth/reset-password",
            json={"username": "blazer", "current_password": "123456", "new_password": "211613"},
        )
        self.assertEqual(reset_response.status_code, 200, reset_response.text)

        old_login_response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "blazer", "password": "123456"},
        )
        self.assertEqual(old_login_response.status_code, 401, old_login_response.text)

        new_login_response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "blazer", "password": "211613"},
        )
        self.assertEqual(new_login_response.status_code, 200, new_login_response.text)

    def test_reset_password_rejects_wrong_current_password(self) -> None:
        register_response = self.client.post(
            "/api/v1/auth/register",
            json={"username": "blazer", "password": "123456"},
        )
        self.assertEqual(register_response.status_code, 200, register_response.text)

        reset_response = self.client.post(
            "/api/v1/auth/reset-password",
            json={"username": "blazer", "current_password": "badpass", "new_password": "211613"},
        )
        self.assertEqual(reset_response.status_code, 401, reset_response.text)
        self.assertEqual(reset_response.json()["detail"], "invalid username or current password")

    def test_verify_user_reads_legacy_auth_store_and_migrates_it(self) -> None:
        legacy_auth_dir = self._root / "legacy-auth"
        legacy_auth_dir.mkdir(parents=True, exist_ok=True)
        legacy_payload = {
            "users": {
                "legacy_user": {
                    "password_hash": auth_core._hash_password("123456"),
                    "created_at": 0,
                }
            }
        }
        (legacy_auth_dir / "users.json").write_text(json.dumps(legacy_payload), encoding="utf-8")

        with patch("app.core.auth._legacy_auth_dirs", return_value=[legacy_auth_dir]):
            self.assertTrue(auth_core.verify_user("legacy_user", "123456"))

        migrated_path = self._data_root / "auth" / "users.json"
        self.assertTrue(migrated_path.exists())
        migrated_payload = json.loads(migrated_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_user", migrated_payload["users"])

    def test_legacy_data_dirs_only_points_to_backend_data(self) -> None:
        legacy_dirs = auth_core._legacy_data_dirs()

        self.assertEqual(legacy_dirs, [auth_core._repo_root() / "backend" / "data"])


if __name__ == "__main__":
    unittest.main()
