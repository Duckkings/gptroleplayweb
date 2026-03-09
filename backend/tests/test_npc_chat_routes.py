import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.main import app
from app.services.world_service import NpcChatConfigError, NpcChatGenerationError


class NpcChatRouteTests(unittest.TestCase):
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

    def _payload(self) -> dict:
        return {
            "session_id": "sess_route_npc_chat",
            "npc_role_id": "npc_test",
            "player_message": '{"input_type":"player_intent_v1","speech_description":"hello"}',
        }

    def test_npc_chat_route_maps_config_error_to_400(self) -> None:
        with patch("app.api.routes.npc_chat", side_effect=NpcChatConfigError("missing config")):
            response = self.client.post("/api/v1/npc/chat", json=self._payload())
        self.assertEqual(response.status_code, 400)
        self.assertIn("missing config", response.text)

    def test_npc_chat_route_maps_generation_error_to_502(self) -> None:
        with patch("app.api.routes.npc_chat", side_effect=NpcChatGenerationError("bad output")):
            response = self.client.post("/api/v1/npc/chat", json=self._payload())
        self.assertEqual(response.status_code, 502)
        self.assertIn("bad output", response.text)

    def test_npc_chat_route_maps_role_not_found_to_404(self) -> None:
        with patch("app.api.routes.npc_chat", side_effect=KeyError("ROLE_NOT_FOUND")):
            response = self.client.post("/api/v1/npc/chat", json=self._payload())
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
