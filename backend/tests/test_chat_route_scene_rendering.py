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
            "messages": [{"role": "user", "content": "player input"}],
        }
        scene_event = SceneEvent(
            event_id="evt_scene_1",
            kind="encounter_started",
            content="Encounter content should stay outside the GM reply.",
            metadata={"encounter_id": "enc_1", "encounter_title": "Night Noise"},
        )

        with patch(
            "app.api.routes.resolve_main_chat_turn",
            new=AsyncMock(
                return_value=(
                    Message(role="assistant", content="GM body"),
                    Usage(input_tokens=1, output_tokens=1),
                    [],
                    [scene_event],
                    0,
                    "turn_1",
                )
            ),
        ):
            with patch("app.api.routes.add_game_log"):
                response = self.client.post("/api/v1/chat", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reply"]["content"], "GM body")
        self.assertEqual(len(data["scene_events"]), 1)
        self.assertEqual(data["scene_events"][0]["kind"], "encounter_started")
        self.assertEqual(data["scene_events"][0]["metadata"]["encounter_id"], "enc_1")
        self.assertEqual(data["archived_sub_zone_turn_id"], "turn_1")
        self.assertNotIn("Encounter content", data["reply"]["content"])

    def test_chat_route_returns_409_when_passive_turn_requires_active_encounter(self) -> None:
        payload = {
            "session_id": "sess_chat_route_passive",
            "config": {
                "openai_api_key": "test-key",
                "model": "test-model",
                "stream": False,
                "temperature": 0.8,
                "max_tokens": 256,
                "gm_prompt": "gm",
                "speech_time_per_50_tokens_min": 1,
            },
            "messages": [{"role": "user", "content": '{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}'}],
        }

        with patch("app.api.routes.resolve_main_chat_turn", new=AsyncMock(side_effect=ValueError("PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER"))):
            response = self.client.post("/api/v1/chat", json=payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER")

    def test_chat_stream_returns_409_error_event_for_invalid_passive_turn(self) -> None:
        payload = {
            "session_id": "sess_chat_route_passive_stream",
            "config": {
                "openai_api_key": "test-key",
                "model": "test-model",
                "stream": True,
                "temperature": 0.8,
                "max_tokens": 256,
                "gm_prompt": "gm",
                "speech_time_per_50_tokens_min": 1,
            },
            "messages": [{"role": "user", "content": '{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}'}],
        }

        with patch("app.api.routes.resolve_main_chat_turn", new=AsyncMock(side_effect=ValueError("PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER"))):
            with self.client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
                body = "".join(chunk.decode("utf-8") for chunk in response.iter_raw())

        self.assertEqual(response.status_code, 200)
        self.assertIn('event: error', body)
        self.assertIn('"code": 409', body)
        self.assertIn('PASSIVE_TURN_REQUIRES_ACTIVE_ENCOUNTER', body)

    def test_chat_stream_end_event_contains_archived_turn_id(self) -> None:
        payload = {
            "session_id": "sess_chat_route_stream_archived",
            "config": {
                "openai_api_key": "test-key",
                "model": "test-model",
                "stream": True,
                "temperature": 0.8,
                "max_tokens": 256,
                "gm_prompt": "gm",
                "speech_time_per_50_tokens_min": 1,
            },
            "messages": [{"role": "user", "content": "player input"}],
        }

        with patch(
            "app.api.routes.resolve_main_chat_turn",
            new=AsyncMock(
                return_value=(
                    Message(role="assistant", content="GM body"),
                    Usage(input_tokens=1, output_tokens=1),
                    [],
                    [],
                    1,
                    "turn_stream_1",
                )
            ),
        ):
            with patch("app.api.routes.add_game_log"):
                with self.client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
                    body = "".join(chunk.decode("utf-8") for chunk in response.iter_raw())

        self.assertEqual(response.status_code, 200)
        self.assertIn('"archived_sub_zone_turn_id": "turn_stream_1"', body)


if __name__ == "__main__":
    unittest.main()
