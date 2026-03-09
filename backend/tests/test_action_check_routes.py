import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.main import app
from app.models.schemas import ActionCheckPlanResponse, ActionCheckResponse


class ActionCheckRouteTests(unittest.TestCase):
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

    def test_action_check_plan_route_returns_planned_payload(self) -> None:
        planned = ActionCheckPlanResponse(
            session_id="sess_action_plan_route",
            actor_role_id="player_001",
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="wisdom",
            ability_modifier=2,
            dc=13,
            time_spent_min=2,
            check_task="判断能否识破埋伏",
        )

        with patch("app.api.routes.plan_action_check", return_value=planned):
            response = self.client.post(
                "/api/v1/actions/check/plan",
                json={
                    "session_id": "sess_action_plan_route",
                    "action_type": "check",
                    "action_prompt": "我仔细观察四周",
                    "actor_role_id": "player_001",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["check_task"], "判断能否识破埋伏")
        self.assertEqual(data["dc"], 13)
        self.assertEqual(data["actor_kind"], "player")

    def test_action_check_route_returns_409_when_player_roll_is_required(self) -> None:
        with patch("app.api.routes.action_check", side_effect=ValueError("PLAYER_DICE_ROLL_REQUIRED")):
            response = self.client.post(
                "/api/v1/actions/check",
                json={
                    "session_id": "sess_action_check_route",
                    "action_type": "check",
                    "action_prompt": "我强行撬门",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PLAYER_DICE_ROLL_REQUIRED")

    def test_action_check_route_returns_response_body(self) -> None:
        result = ActionCheckResponse(
            session_id="sess_action_check_ok",
            actor_role_id="player_001",
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=3,
            dc=14,
            check_task="翻过木栅栏",
            dice_roll=12,
            total_score=15,
            success=True,
            critical="none",
            time_spent_min=2,
            narrative="【检定】Player 进行“翻过木栅栏”检定。",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
        )

        with patch("app.api.routes.action_check", return_value=result):
            response = self.client.post(
                "/api/v1/actions/check",
                json={
                    "session_id": "sess_action_check_ok",
                    "action_type": "check",
                    "action_prompt": "我翻过木栅栏",
                    "forced_dice_roll": 12,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["actor_name"], "Player")
        self.assertEqual(data["check_task"], "翻过木栅栏")
        self.assertEqual(data["dice_roll"], 12)


if __name__ == "__main__":
    unittest.main()
