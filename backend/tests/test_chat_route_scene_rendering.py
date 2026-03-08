import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.main import app
from app.models.schemas import Message, SceneEvent, Usage


class ChatRouteSceneRenderingTests(unittest.TestCase):
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

    def test_chat_route_keeps_scene_events_out_of_reply_content(self) -> None:
        payload = {
            "session_id": "sess_chat_route_scene",
            "config": {
                "openai_api_key": "test-key",
                "model": "test-model",
                "stream": False,
                "temperature": 0.8,
                "max_tokens": 256,
                "gm_prompt": "gm",
                "speech_time_per_50_tokens_min": 1,
            },
            "messages": [{"role": "user", "content": "玩家输入"}],
        }
        scene_event = SceneEvent(
            event_id="evt_scene_1",
            kind="encounter_started",
            content="【遭遇触发】夜巷异响\n完整遭遇描述",
            metadata={"encounter_id": "enc_1", "encounter_title": "夜巷异响"},
        )

        with patch("app.api.routes.chat_once", new=AsyncMock(return_value=(Message(role="assistant", content="GM正文"), Usage(input_tokens=1, output_tokens=1), []))):
            with patch("app.api.routes.advance_public_scene_in_save", return_value=[scene_event]):
                with patch("app.api.routes.advance_active_encounter_in_save", return_value=None):
                    with patch("app.api.routes.apply_team_reactions"):
                        with patch("app.api.routes.add_game_log"):
                            with patch("app.api.routes.apply_speech_time", return_value=0):
                                response = self.client.post("/api/v1/chat", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reply"]["content"], "GM正文")
        self.assertEqual(len(data["scene_events"]), 1)
        self.assertEqual(data["scene_events"][0]["kind"], "encounter_started")
        self.assertEqual(data["scene_events"][0]["metadata"]["encounter_id"], "enc_1")
        self.assertNotIn("遭遇触发", data["reply"]["content"])
        self.assertNotIn("完整遭遇描述", data["reply"]["content"])


if __name__ == "__main__":
    unittest.main()
