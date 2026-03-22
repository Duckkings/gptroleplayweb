import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.models.schemas import PlayerInputResourceStatus, PlayerInputValidationResponse


class _FakeSerializer:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def dumps(self, value):
        return value

    def loads(self, value):
        return value


sys.modules.setdefault(
    "itsdangerous",
    SimpleNamespace(BadSignature=Exception, URLSafeSerializer=_FakeSerializer),
)

from app.main import app


class PlayerInputValidationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def _payload(self) -> dict[str, object]:
        return {
            "session_id": "sess_route_validation",
            "entry_point": "main_chat",
            "action_text": "我先踹门。",
            "speech_text": "开门。",
            "actor_role_id": "player_1",
            "config": {
                "api_key": "test-key",
                "model": "test-model",
                "stream": False,
                "gm_prompt": "gm",
            },
        }

    def test_route_returns_validation_payload(self) -> None:
        expected = PlayerInputValidationResponse(
            session_id="sess_route_validation",
            entry_point="main_chat",
            actor_role_id="player_1",
            actor_name="Player",
            actor_kind="player",
            status="accepted",
            normalized_action_text="我先踹门。",
            normalized_speech_text="开门。",
            fallback_action_text="我先踹门。",
            display_text="Action: 我先踹门。\nSpeech: 开门。",
            summary="输入已通过校验，可以直接提交。",
            issues=[],
            resource_status=PlayerInputResourceStatus(),
        )

        with patch("app.api.routes.validate_player_input", return_value=expected):
            response = self.client.post("/api/v1/player-input/validate", json=self._payload())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "accepted")
        self.assertEqual(data["normalized_action_text"], "我先踹门。")

    def test_route_maps_key_error_to_404(self) -> None:
        with patch("app.api.routes.validate_player_input", side_effect=KeyError("ROLE_NOT_FOUND")):
            response = self.client.post("/api/v1/player-input/validate", json=self._payload())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "role not found")

    def test_route_maps_value_error_to_409(self) -> None:
        with patch("app.api.routes.validate_player_input", side_effect=ValueError("PLAYER_INPUT_VALIDATION_FAILED")):
            response = self.client.post("/api/v1/player-input/validate", json=self._payload())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PLAYER_INPUT_VALIDATION_FAILED")
